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


@pytest.fixture
def funded(monkeypatch):
    from mimamori import points
    monkeypatch.setattr(points, "sync_from_calendar", lambda child: 0)
    points.set_rewards([{"label": "ごほうび", "points": 30}])
    ledger.add("下の子", 100, "adjust")
    return login()


@pytest.mark.parametrize("keys,count", [
    (["test-request-key-01", "test-request-key-01"], 1),
    (["test-request-key-01", "test-request-key-02"], 2),
    ([None, None], 2),
])
def test_request_key_api(funded, keys, count):
    responses = []
    for key in keys:
        body = {"child": "下の子", "label": "ごほうび", "cost": 30}
        if key is not None:
            body["request_key"] = key
        response = funded.post("/api/redeem", json=body)
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"request", "balance"}
        assert data["request"].get("request_key") == key
        responses.append(data)
    assert len(funded.get("/api/redeem").json()["items"]) == count
    assert ledger.balance("下の子") == 100 - count * 30
    if count == 1:
        assert responses[0] == responses[1]


@pytest.mark.parametrize("key", ["", "short", "a" * 129, "a" * 15 + "!", "あ" * 16, 123])
def test_invalid_request_key_is_rejected(funded, key):
    response = funded.post("/api/redeem", json={"child": "下の子", "label": "ごほうび", "cost": 30, "request_key": key})
    assert response.status_code in (400, 422)
    assert ledger.balance("下の子") == 100
    assert funded.get("/api/redeem").json()["items"] == []


def test_retry_after_reward_removed_and_refund_history(funded):
    from mimamori import points, redeem
    body = {"child": "下の子", "label": "ごほうび", "cost": 30, "request_key": "test-request-key-01"}
    row = funded.post("/api/redeem", json=body).json()["request"]
    redeem.reject(row["id"], "また今度")
    points.set_rewards([{"label": "別のごほうび", "points": 60}])
    again = funded.post("/api/redeem", json=body)
    assert again.status_code == 200
    assert again.json()["request"]["status"] == "rejected"
    hist = funded.get("/api/points").json()["history"]
    refunds = [e for e in hist if e["points"] == 30]
    assert len(refunds) == 1 and refunds[0]["redeem_id"] == row["id"]
    assert refunds[0]["kind"] == "adjust"
    assert "redeem_id" not in next(e for e in hist if e["points"] == 100)


@pytest.mark.parametrize("action", ["reject", "approve", "hand"])
def test_parallel_parent_decisions_return_one_400(funded, monkeypatch, action):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, current_thread
    from mimamori import redeem

    row = funded.post("/api/redeem", json={"child": "下の子", "label": "ごほうび", "cost": 30}).json()["request"]
    auth.set_passcode(auth.PARENT, "4821")  # テスト専用
    parent = client()
    assert parent.post("/api/auth/login", json={"who": "parent", "passcode": "4821"}).status_code == 200
    start, read = Barrier(2), Barrier(2)
    get = ledger.get_setting

    def intercepted(key, *args):
        saved = get(key, *args)
        # FastAPI の同期エンドポイントは AnyIO のワーカースレッドで実行される。
        if key == redeem.K_REQ and current_thread().name == "AnyIO worker thread":
            read.wait(timeout=5)
        return saved

    monkeypatch.setattr(ledger, "get_setting", intercepted)

    def send(_):
        start.wait(timeout=5)
        return parent.post("/api/redeem/" + action, json={"id": row["id"], "note": "また今度"})

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(send, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 400]
    assert ledger.balance("下の子") == (100 if action == "reject" else 70)
    refunds = [e for e in ledger.history("下の子") if e["delta"] == 30]
    assert len(refunds) == (1 if action == "reject" else 0)
    assert all(e["redeem_id"] == row["id"] for e in refunds)
