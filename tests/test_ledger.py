"""#5・#14: 保存先の選択と起動時の接続確認。GCP はモックする。"""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import DeadlineExceeded, NotFound, PermissionDenied
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import firestore

import main
from mimamori import ledger


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("MIMAMORI_LEDGER", raising=False)
    monkeypatch.setattr(ledger, "_store", None)
    local = ledger._LocalStore
    monkeypatch.setattr(ledger, "_LocalStore", Mock(side_effect=lambda: local(tmp_path / "ledger.json")))
    # 全ケースで実クライアントの生成を防ぐ。
    client = Mock()
    monkeypatch.setattr(firestore, "Client", client)
    return client


@pytest.fixture(params=["cloud_run", "cloud_run_json", "cloud_run_firestore", "local_firestore"])
def firestore_environment(monkeypatch, request):
    if request.param.startswith("cloud_run"):
        monkeypatch.setenv("K_SERVICE", "test-service")
    if request.param == "cloud_run_json":
        monkeypatch.setenv("MIMAMORI_LEDGER", "json")
    elif request.param.endswith("firestore"):
        monkeypatch.setenv("MIMAMORI_LEDGER", "firestore")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")


@pytest.mark.parametrize("project", [None, "", "   "])
def test_firestore_requires_project(monkeypatch, isolated_store, firestore_environment, project):
    if project is None:
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT")
    else:
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        with TestClient(main.app):
            pytest.fail("起動できてはいけない")
    isolated_store.assert_not_called()
    ledger._LocalStore.assert_not_called()
    assert ledger._store is None


@pytest.mark.parametrize("error", [ImportError("missing package"), DefaultCredentialsError("no credentials")])
def test_firestore_initialization_failure_stops_startup(monkeypatch, isolated_store, firestore_environment, error):
    # パッケージ import 失敗も含めて初期化失敗を再現する。
    monkeypatch.setattr(ledger, "_FirestoreStore", Mock(side_effect=error))
    with pytest.raises(RuntimeError, match="Firestore") as exc:
        with TestClient(main.app):
            pytest.fail("起動できてはいけない")
    assert exc.value.__cause__ is error
    ledger._LocalStore.assert_not_called()
    assert ledger._store is None


@pytest.mark.parametrize("error", [PermissionDenied("denied"), NotFound("no database"), DeadlineExceeded("timeout")])
def test_firestore_rpc_failure_stops_startup(monkeypatch, isolated_store, firestore_environment, error):
    family = isolated_store.return_value.collection.return_value.document.return_value
    family.get.side_effect = error
    with pytest.raises(RuntimeError, match="Firestore") as exc:
        with TestClient(main.app):
            pytest.fail("起動できてはいけない")
    assert exc.value.__cause__ is error
    family.get.assert_called_once_with(retry=None, timeout=10)
    ledger._LocalStore.assert_not_called()
    assert ledger._store is None
    # 失敗したクライアントをキャッシュせず、次回も接続を確かめる。
    with pytest.raises(RuntimeError):
        ledger.store()
    assert family.get.call_count == 2


def test_firestore_checks_connection_and_reuses_store(monkeypatch, isolated_store, firestore_environment):
    family = isolated_store.return_value.collection.return_value.document.return_value
    family.get.return_value.exists = False  # 空の DB でも起動できる。
    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
        first = ledger.store()
        assert first.kind == "firestore"
        assert ledger.store() is first
    isolated_store.assert_called_once_with(project="test-project")
    isolated_store.return_value.collection.assert_called_once_with("families")
    isolated_store.return_value.collection.return_value.document.assert_called_once_with("default")
    family.get.assert_called_once_with(retry=None, timeout=10)
    ledger._LocalStore.assert_not_called()


@pytest.mark.parametrize("project", [False, True])
@pytest.mark.parametrize("backend", [None, "json"])
def test_local_development_persists_json(monkeypatch, isolated_store, tmp_path, project, backend):
    if backend is not None:
        monkeypatch.setenv("MIMAMORI_LEDGER", backend)
    if project:
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    with TestClient(main.app):
        assert ledger._store.kind == "local"
        ledger.add("テストの子", 3, "homework")
        ledger.set_setting("rewards", [{"title": "テスト", "cost": 3}])
    assert ledger.store().kind == "local"
    # 作り直しても残高と設定が残る。
    monkeypatch.setattr(ledger, "_store", None)
    assert ledger.balance("テストの子") == 3
    assert ledger.get_setting("rewards") == [{"title": "テスト", "cost": 3}]
    assert (tmp_path / "ledger.json").exists()
    isolated_store.assert_not_called()


@pytest.mark.parametrize("on_cloud_run", [False, True])
@pytest.mark.parametrize("backend", ["", "sqlite", "FIRESTORE", " firestore "])
def test_invalid_backend_stops_startup(monkeypatch, isolated_store, on_cloud_run, backend):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("MIMAMORI_LEDGER", backend)
    if on_cloud_run:
        monkeypatch.setenv("K_SERVICE", "test-service")
    with pytest.raises(RuntimeError, match="MIMAMORI_LEDGER"):
        with TestClient(main.app):
            pytest.fail("起動できてはいけない")
    isolated_store.assert_not_called()
    ledger._LocalStore.assert_not_called()
    assert ledger._store is None
