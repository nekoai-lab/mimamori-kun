"""#47: 閲覧に依存しない加点と、日本時間の完了日による実績。"""
import copy
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import main
from mimamori import auth, calendar_tools as cal, ledger, points

CHILD = "上の子"
REAL_DATETIME = dt.datetime


@pytest.fixture(params=[True, False], ids=["demo", "calendar"])
def task(request, monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    monkeypatch.setattr(cal, "DEMO", request.param)
    monkeypatch.setenv("MIMAMORI_AUTH", "off")
    monkeypatch.setattr(main.recurring_mod, "ensure", lambda: None)
    clock = ["2026-09-29T23:59:00+09:00"]

    class Clock(REAL_DATETIME):
        @classmethod
        def now(cls, tz=None):
            return REAL_DATETIME.fromisoformat(clock[0]).astimezone(tz)

    monkeypatch.setattr(cal.dt, "datetime", Clock)
    row = dict(id="task47", child=CHILD, kind="homework", points=3, status="todo",
               summary="上の子｜宿題", date="2026-09-28", mine=True)
    monkeypatch.setattr(cal, "_demo_store", [row])
    monkeypatch.setattr(cal, "_demo_day", "2026-09-29")
    event = {"id": row["id"], "summary": row["summary"], "start": {"date": row["date"]},
             "extendedProperties": {"private": {"app": cal.MARK, "child": CHILD,
              "kind": "homework", "points": "3", "status": "todo"}}}
    lock = Lock()
    calls = []

    def get(**kwargs):
        with lock:
            return Mock(execute=lambda: copy.deepcopy(event))

    def patch(**kwargs):
        def execute():
            with lock:
                body = kwargs["body"]
                if "summary" in body:
                    event["summary"] = body["summary"]
                priv = event["extendedProperties"]["private"]
                for k, v in body["extendedProperties"]["private"].items():
                    if v is None:
                        priv.pop(k, None)
                    else:
                        priv[k] = v
                return copy.deepcopy(event)
        return Mock(execute=execute)

    def listing(**kwargs):
        calls.append(kwargs)
        if "privateExtendedProperty" in kwargs:
            found = event["extendedProperties"]["private"].get("done_date") == kwargs["privateExtendedProperty"].split("=")[1]
        else:
            found = kwargs["timeMin"][:10] <= event["start"]["date"] < kwargs["timeMax"][:10]
        return Mock(execute=lambda: {"items": [copy.deepcopy(event)] if found else []})

    service = Mock()
    service.events.return_value.get.side_effect = get
    service.events.return_value.patch.side_effect = patch
    service.events.return_value.list.side_effect = listing
    monkeypatch.setattr(cal, "_svc", lambda: service)
    return row, event, clock, calls


def post(status="done"):
    with TestClient(main.app) as client:
        response = client.post("/api/status", json={"event_id": "task47", "status": status})
    assert response.status_code == 200, response.text
    return response


def today_points():
    with TestClient(main.app) as client:
        response = client.get("/api/tasks")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("date", ["2026-09-28", "2026-08-01", "2026-10-01", "2027-01-01"])
def test_completion_records_immediately_and_counts_today(task, date):
    row, event, _, _ = task
    row["date"] = event["start"]["date"] = date
    post()
    # 残高・タスク API を一度も開く前に永続化されている。
    entries = ledger.store().entries(CHILD)
    assert len(entries) == 1
    assert entries[0]["delta"] == 3 and entries[0]["ref_id"] == "task47"
    data = today_points()
    assert data["points"][CHILD] == 3
    assert data["items"][0]["done_at"] == "2026-09-29T23:59:00+09:00"


@pytest.mark.parametrize("undo_status", ["todo", "doing", "rejected"])
def test_complete_undo_complete_is_one_active_credit(task, undo_status):
    post()
    post()
    post(undo_status)
    assert ledger.balance(CHILD) == 0
    assert ledger.history(CHILD)[0]["revoked"] is True
    row, event, _, _ = task
    state = row if cal.DEMO else event["extendedProperties"]["private"]
    assert not state.get("done_at")
    post()
    post()
    assert ledger.balance(CHILD) == 3
    assert len(ledger.history(CHILD)) == 2
    assert sum(not e["revoked"] for e in ledger.history(CHILD)) == 1


def test_midnight_preserves_credit_but_not_todays_points(task):
    row, event, clock, _ = task
    row["date"] = event["start"]["date"] = "2026-10-01"
    post()
    clock[0] = "2026-09-30T00:01:00+09:00"
    post()  # 同じ完了の再送で完了日を翌日に変えない。
    assert ledger.balance(CHILD) == 3
    assert today_points()["points"][CHILD] == 0
    assert ledger.history(CHILD)[0]["created_at"].startswith("2026-09-29")


def test_concurrent_completion_is_one_credit(task, monkeypatch):
    barrier = Barrier(2)
    original = ledger.transact_setting_entries

    def together(*args):
        barrier.wait(timeout=5)
        return original(*args)

    monkeypatch.setattr(ledger, "transact_setting_entries", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(), range(2)))
    assert len(results) == 2
    assert ledger.balance(CHILD) == 3
    assert len(ledger.history(CHILD)) == 1


def test_reading_balance_history_and_legacy_sync_never_imports(task):
    row, event, _, _ = task
    row["status"] = event["extendedProperties"]["private"]["status"] = "done"
    assert points.balance(CHILD) == 0
    assert points.history(CHILD) == []
    assert points.sync_from_calendar(CHILD) == 0
    assert ledger.store().entries() == []


def test_other_child_cannot_complete(task, monkeypatch):
    monkeypatch.delenv("MIMAMORI_AUTH", raising=False)
    auth.set_passcode("下の子", "test-only-passcode")
    with TestClient(main.app, base_url="https://testserver") as client:
        assert client.post("/api/auth/login", json={"who": "c1", "passcode": "test-only-passcode"}).status_code == 200
        assert client.post("/api/status", json={"event_id": "task47", "status": "done"}).status_code == 403
    assert ledger.store().entries() == []


@pytest.mark.parametrize("status", ["done", "todo"])
def test_failed_ledger_save_can_be_retried_without_partial_credit(task, monkeypatch, status):
    if status == "todo":
        post()
    store = ledger.store()
    before = copy.deepcopy(store._read())
    with monkeypatch.context() as patcher:
        patcher.setattr(store, "_write", Mock(side_effect=OSError("test write failure")))
        with TestClient(main.app) as client:
            assert client.post("/api/status", json={"event_id": "task47", "status": status}).status_code == 500
    assert store._read() == before
    post(status)
    post(status)
    assert ledger.balance(CHILD) == (3 if status == "done" else 0)
    assert len(ledger.history(CHILD)) == 1


def test_register_undo_revokes_credit(task):
    post()
    with TestClient(main.app) as client:
        response = client.post("/api/register/undo", json={"ids": ["task47"]})
    assert response.status_code == 200
    assert response.json()["undone"] == 1
    assert ledger.balance(CHILD) == 0
    assert ledger.history(CHILD)[0]["revoked"] is True
