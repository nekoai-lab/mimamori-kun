"""ごほうびの親操作・他の子の情報は、画面だけでなく API でも止める。"""
import pytest
from fastapi.testclient import TestClient

import main
from mimamori import auth, ledger


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("MIMAMORI_AUTH", raising=False)
    monkeypatch.delenv("MIMAMORI_LEDGER", raising=False)
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    auth.set_passcode("下の子", "1058")  # conftest のダミー利用者・テスト専用合言葉


def client():
    return TestClient(main.app, base_url="https://testserver")


def login():
    c = client()
    assert c.post("/api/auth/login", json={"who": "c1", "passcode": "1058"}).status_code == 200
    return c


@pytest.mark.parametrize("action,body", [
    ("approve", {"id": "test-request"}),
    ("reject", {"id": "test-request", "note": "また今度"}),
    ("hand", {"id": "test-request"}),
    ("cap", {"yen": 1000, "count": 2}),
])
@pytest.mark.parametrize("logged_in,status", [(True, 403), (False, 401)])
def test_parent_reward_api_denies_child_and_anonymous(action, body, logged_in, status):
    c = login() if logged_in else client()
    assert c.post(f"/api/redeem/{action}", json=body).status_code == status


@pytest.mark.parametrize("path", ["/api/redeem", "/api/points"])
def test_child_cannot_read_sibling_reward_data(path):
    assert login().get(path, params={"child": "上の子"}).status_code == 403
