"""#64: 課金先の確認は実接続・ADC・合言葉入力より前に行う。"""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import main
from mimamori import ledger
from mimamori.config import validate_quota_project
from tools import set_passcode


ERROR = (
    "GOOGLE_CLOUD_QUOTA_PROJECT が GOOGLE_CLOUD_PROJECT と一致していません。"
    "課金先を固定するため、.env に GOOGLE_CLOUD_QUOTA_PROJECT を入れてください。"
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in (
        "K_SERVICE", "GOOGLE_GENAI_USE_VERTEXAI", "MIMAMORI_LEDGER",
        "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_QUOTA_PROJECT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ledger, "store", Mock(return_value=Mock(kind="local")))
    monkeypatch.setattr(set_passcode.getpass, "getpass", Mock(return_value="dummy-passcode"))
    monkeypatch.setattr(set_passcode.auth, "set_passcode", Mock())
    monkeypatch.setattr(set_passcode.auth, "logout_all", Mock(return_value=2))


@pytest.fixture(params=["TRUE", "true", "TrUe", "1", "firestore"])
def cloud_usage(monkeypatch, request):
    if request.param == "firestore":
        monkeypatch.setenv("MIMAMORI_LEDGER", "firestore")
    else:
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", request.param)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")


@pytest.mark.parametrize("quota", [None, "", "   ", "other-test-project"])
def test_local_cloud_rejects_invalid_quota(monkeypatch, cloud_usage, quota):
    if quota is not None:
        monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT", quota)
    with pytest.raises(RuntimeError) as exc:
        validate_quota_project()
    assert str(exc.value) == ERROR


@pytest.mark.parametrize("project", [None, "", "   "])
def test_missing_project_cannot_match(monkeypatch, cloud_usage, project):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT")
    if project is not None:
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project)
        monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT", project)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        validate_quota_project()


def test_matching_projects_allow_startup_and_passcode(monkeypatch, cloud_usage):
    monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT", "test-project")
    with TestClient(main.app):
        pass
    assert set_passcode.main(["おうちの人"]) == 0
    set_passcode.auth.set_passcode.assert_called_once()


@pytest.mark.parametrize("service", ["test-service", ""])
def test_cloud_run_skips_check(monkeypatch, cloud_usage, service):
    monkeypatch.setenv("K_SERVICE", service)
    monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT", "other-test-project")
    validate_quota_project()


def test_cloud_run_skips_check_without_quota(monkeypatch, cloud_usage):
    monkeypatch.setenv("K_SERVICE", "test-service")
    monkeypatch.delenv("GOOGLE_CLOUD_QUOTA_PROJECT", raising=False)
    validate_quota_project()


def test_cloud_run_lifespan_without_quota(monkeypatch, cloud_usage):
    monkeypatch.setenv("K_SERVICE", "test-service")
    monkeypatch.delenv("GOOGLE_CLOUD_QUOTA_PROJECT", raising=False)
    with TestClient(main.app):
        ledger.store.assert_called_once_with()


@pytest.mark.parametrize("vertex", [None, "FALSE", "false", "0", ""])
@pytest.mark.parametrize("backend", [None, "json"])
def test_local_without_cloud_needs_no_quota(monkeypatch, vertex, backend):
    if vertex is not None:
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", vertex)
    if backend is not None:
        monkeypatch.setenv("MIMAMORI_LEDGER", backend)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    validate_quota_project()


def test_lifespan_checks_before_store(cloud_usage):
    with pytest.raises(RuntimeError) as exc:
        with TestClient(main.app):
            pytest.fail("起動できてはいけない")
    assert str(exc.value) == ERROR
    ledger.store.assert_not_called()


@pytest.mark.parametrize("target", ["おうちの人", "--logout-all"])
def test_passcode_checks_before_input_or_store(cloud_usage, target, capsys):
    assert set_passcode.main([target]) == 1
    captured = capsys.readouterr()
    assert captured.err == ERROR + "\n"
    assert captured.out == ""
    ledger.store.assert_not_called()
    set_passcode.getpass.getpass.assert_not_called()
    set_passcode.auth.set_passcode.assert_not_called()
    set_passcode.auth.logout_all.assert_not_called()
