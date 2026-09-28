"""親の一覧の再確認・重複送信。デモ台帳だけを使う。"""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import main
from mimamori import auth, calendar_tools, ledger, notify


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    for name in ("K_SERVICE", "MIMAMORI_AUTH", "MIMAMORI_LEDGER", "MIMAMORI_NOTIFY_WEBHOOK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    monkeypatch.setattr(calendar_tools, "_demo_store", None)
    monkeypatch.setattr(calendar_tools, "_demo_day", None)
    assert calendar_tools.DEMO
    auth.set_passcode(auth.PARENT, "4821")
    auth.set_passcode("下の子", "1058")


def login(who="parent"):
    c = TestClient(main.app, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"who": who, "passcode": "4821" if who == "parent" else "1058"})
    assert r.status_code == 200
    return c


def task_id():
    return next(i["id"] for i in calendar_tools.list_tasks(days=14)["items"] if i["status"] == "todo")


def test_get_status_parent_only_and_missing():
    id_ = task_id()
    c = login()
    assert c.get("/api/status", params={"event_id": id_}).json() == {"id": id_, "status": "todo"}
    assert c.get("/api/status?event_id=unknown").status_code == 404
    assert login("c1").get("/api/status", params={"event_id": id_}).status_code == 403
    assert TestClient(main.app, base_url="https://testserver").get("/api/status", params={"event_id": id_}).status_code == 401


@pytest.mark.parametrize("status", ["rejected", "done"])
def test_status_repeat_preserves_other_events_and_points(status):
    c, id_ = login(), task_id()
    others = deepcopy([i for i in calendar_tools._demo_store if i["id"] != id_])
    payload = {"event_id": id_, "status": status}
    first = c.post("/api/status", json=payload)
    assert first.status_code == 200 and first.json()["status"] == status
    assert [i for i in calendar_tools._demo_store if i["id"] != id_] == others
    points = c.get("/api/tasks").json()["points"]
    after = deepcopy(calendar_tools._demo_store)
    entries = deepcopy(ledger.store().entries())
    second = c.post("/api/status", json=payload)
    assert second.status_code == 200 and second.json() == first.json()
    assert calendar_tools._demo_store == after
    assert c.get("/api/tasks").json()["points"] == points
    assert ledger.store().entries() == entries
    assert c.get("/api/status", params={"event_id": id_}).json() == {"id": id_, "status": status}
    if status == "rejected":
        assert id_ not in [i["id"] for i in c.get("/api/tasks").json()["items"]]


def test_seen_repeat_and_unknown_and_bulk():
    c = login()
    n = notify.add("kid_added", "ダミーの知らせ")
    other = notify.add("kid_added", "別の知らせ")
    for _ in range(2):
        r = c.post("/api/notices/seen", json={"id": n["id"]})
        assert r.status_code == 200 and r.json() == {"seen": 1}
    assert [i["id"] for i in c.get("/api/notices?unseen=true").json()["items"]] == [other["id"]]
    assert c.post("/api/notices/seen", json={"id": "unknown"}).status_code == 404
    assert c.post("/api/notices/seen", json={}).json() == {"seen": 1}
    assert c.post("/api/notices/seen", json={}).json() == {"seen": 0}
