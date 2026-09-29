"""#52: 照合済み候補を ID と完了記録を保って更新する。"""
import copy
import datetime as dt
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import main
from mimamori import calendar_tools as cal, ledger

CHILD = "上の子"


@pytest.fixture(params=[True, False], ids=["demo", "calendar"])
def calendar(request, monkeypatch, tmp_path):
    monkeypatch.setattr(cal, "DEMO", request.param)
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    monkeypatch.setenv("MIMAMORI_AUTH", "off")
    monkeypatch.setattr(main.recurring_mod, "ensure", lambda: None)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    row = dict(id="task52", summary="宿題", child=CHILD, date=today,
               kind="homework", status="todo", points=3, mine=True,
               bring="鉛筆", description="持ち物: 鉛筆\n元の補足", time=None)
    event = dict(id="task52", summary="宿題", description=row["description"],
                 start={"date": today}, end={"date": (dt.date.fromisoformat(today) + dt.timedelta(days=1)).isoformat()},
                 extendedProperties={"private": dict(app=cal.MARK, child=CHILD,
                     kind="homework", status="todo", points="3", bring="鉛筆")})
    monkeypatch.setattr(cal, "_demo_store", [row])
    monkeypatch.setattr(cal, "_demo_day", today)
    events = {"task52": event}
    service = Mock()

    def get(**kw):
        return Mock(execute=lambda: copy.deepcopy(events[kw["eventId"]]))

    def patch(**kw):
        def execute():
            ev = events[kw["eventId"]]
            def merge(target, changes):
                for key, value in changes.items():
                    if value is None:
                        target.pop(key, None)
                    elif isinstance(value, dict):
                        merge(target.setdefault(key, {}), value)
                    else:
                        target[key] = copy.deepcopy(value)
            merge(ev, kw["body"])
            return copy.deepcopy(ev)
        return Mock(execute=execute)

    def insert(**kw):
        eid = "inserted" + str(len(events))
        events[eid] = dict(kw["body"], id=eid)
        return Mock(execute=lambda: copy.deepcopy(events[eid]))

    service.events.return_value.get.side_effect = get
    service.events.return_value.patch.side_effect = patch
    service.events.return_value.insert.side_effect = insert
    service.events.return_value.list.side_effect = lambda **kw: Mock(execute=lambda: {"items": copy.deepcopy(list(events.values()))})
    monkeypatch.setattr(cal, "_svc", lambda: service)
    return row, event, events, service


def candidate(branch="moved", **changes):
    return dict(dict(title="宿題", kind="homework", child=CHILD,
                     date="2027-01-10", matched_id="task52", branch=branch), **changes)


def register(item):
    with TestClient(main.app) as client:
        return client.post("/api/register", json={"items": [item]})


def undo(result):
    with TestClient(main.app) as client:
        return client.post("/api/register/undo", json={"ids": [result.get("undo_id", result["id"])]})


def state(calendar):
    row, event, _, _ = calendar
    return row if cal.DEMO else event["extendedProperties"]["private"]


def test_move_keeps_one_id_and_changes_time(calendar):
    row, event, events, service = calendar
    response = register(candidate(time_start="09:00", time_end="10:00"))
    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == "task52"
    assert len(cal._demo_store if cal.DEMO else events) == 1
    assert (row["date"] if cal.DEMO else event["start"]["dateTime"][:10]) == "2027-01-10"
    assert (row["time"] if cal.DEMO else event["start"]["dateTime"][11:16]) == "09:00"
    service.events.return_value.insert.assert_not_called()


def test_diff_appends_once_and_preserves_date(calendar):
    row, event, events, _ = calendar
    original_date = row["date"]
    item = candidate("diff", bring=["鉛筆", "水筒"], note="集合場所は教室")
    assert register(item).status_code == 200
    assert register(item).status_code == 200
    desc = row["description"] if cal.DEMO else event["description"]
    assert "元の補足" in desc
    assert desc.count("水筒") == desc.count("集合場所は教室") == 1
    assert set(state(calendar)["bring"].split("、")) == {"鉛筆", "水筒"}
    assert (row["date"] if cal.DEMO else event["start"]["date"]) == original_date
    assert len(cal._demo_store if cal.DEMO else events) == 1


@pytest.mark.parametrize("branch", ["moved", "diff"])
def test_done_points_and_undo_preserved(calendar, branch):
    row, event, _, _ = calendar
    cal.set_status("task52", "done")
    before = copy.deepcopy(row if cal.DEMO else event)
    entries = copy.deepcopy(ledger.store().entries(CHILD))
    done_at = state(calendar)["done_at"]
    result = register(candidate(branch, bring=["水筒"], note="補足", time_start="09:00", time_end="10:00")).json()["results"][0]
    assert result["id"] == "task52"
    assert "補足" in (row if cal.DEMO else event)["description"]
    assert "水筒" in state(calendar)["bring"]
    assert len(cal._demo_store if cal.DEMO else calendar[2]) == 1
    for restoring in (False, True):
        if restoring:
            assert undo(result).json() == {"undone": 1, "failed": []}
            assert undo(result).json() == {"undone": 1, "failed": []}
        assert state(calendar)["status"] == "done"
        assert state(calendar)["done_at"] == done_at
        assert ledger.store().entries(CHILD) == entries
        assert ledger.balance(CHILD) == 3
        assert cal.list_tasks()["points"][CHILD] == 3
    for key in ("description", "date", "time", "start", "end"):
        assert (row if cal.DEMO else event).get(key) == before.get(key)
    assert state(calendar)["bring"] == "鉛筆"


@pytest.mark.parametrize("bad", ["other_child", "foreign", "missing", "no_id", "cancelled"])
def test_invalid_target_returns_400_without_creating(calendar, bad):
    row, event, events, service = calendar
    item = candidate()
    if bad == "other_child":
        row["child"] = event["extendedProperties"]["private"]["child"] = "下の子"
    elif bad == "foreign":
        row["mine"] = False
        event["extendedProperties"]["private"]["app"] = "other"
    elif bad == "missing":
        item["matched_id"] = "gone"
    elif bad == "no_id":
        item.pop("matched_id")
    else:
        row["mine"] = False
        event["status"] = "cancelled"
    before = copy.deepcopy(row if cal.DEMO else events)
    with TestClient(main.app) as client:
        response = client.post("/api/register", json={"items": [candidate("new"), item]})
    assert response.status_code == 400
    assert response.json()["detail"]
    assert (row if cal.DEMO else events) == before
    assert len(cal._demo_store) == 1
    service.events.return_value.insert.assert_not_called()
    service.events.return_value.patch.assert_not_called()


def test_child_cannot_spoof_candidate_owner(calendar, monkeypatch):
    monkeypatch.setattr(main, "_user", lambda request: "下の子")
    assert register(candidate(child="下の子")).status_code == 400
    assert register(candidate()).status_code == 400


def test_update_undo_rejects_later_edit_and_other_child(calendar, monkeypatch):
    row, event, _, _ = calendar
    result = register(candidate("diff", note="新しい補足")).json()["results"][0]
    with monkeypatch.context() as patcher:
        patcher.setattr(main, "_user", lambda request: "下の子")
        assert undo(result).json()["undone"] == 0
    (row if cal.DEMO else event)["description"] += "\nその後の変更"
    assert undo(result).json()["undone"] == 0
    assert "その後の変更" in (row if cal.DEMO else event)["description"]


def test_move_preserves_existing_duration(calendar):
    if cal.DEMO:
        cal._demo_store[0].update(date="2026-10-02", time="23:00", time_end="01:00", end_date="2026-10-03")
    else:
        event = calendar[1]
        event.update(start={"dateTime": "2026-10-02T23:00:00+09:00"},
                     end={"dateTime": "2026-10-03T01:00:00+09:00"})
    response = register(candidate(date="2026-10-07"))
    assert response.status_code == 200
    if not cal.DEMO:
        assert calendar[1]["end"]["dateTime"] == "2026-10-08T01:00:00+09:00"
    else:
        assert calendar[0]["time"] == "23:00"
        assert calendar[0]["end_date"] == "2026-10-08"


def test_browser_sends_match_and_update_undo_id():
    import json
    import subprocess
    from pathlib import Path

    html = Path("static/index.html").read_text()
    collect = html.split("function collect(){", 1)[1].split("async function doRegister", 1)[0]
    script = """
const src = {id: 'candidate', matched_id: 'task52', branch: 'diff',
             child: '上の子', bring: ['鉛筆', '水筒']};
const extraction = {items: [src]};
const fields = {selected: {checked: true}, note: {value: '水筒 / 集合は教室'},
 child: {textContent: '上の子'}, title: {value: '宿題'}, date: {value: '2026-10-02'},
 time_start: {value: ''}};
const document = {querySelectorAll: () => [{dataset: {id: 'candidate'},
 querySelector: selector => fields[selector.match(/data-f="([^"]+)"/)[1]]}]};
""" + "function collect(){" + collect + "console.log(JSON.stringify(collect()));"
    items = json.loads(subprocess.check_output(["node", "-e", script], text=True))
    assert items[0]["matched_id"] == "task52"
    assert items[0]["branch"] == "diff"
    assert items[0]["bring"] == ["水筒"]
    assert items[0]["note"] == "集合は教室"


def test_new_still_creates_and_undo_rejects(calendar):
    response = register(candidate("new"))
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["id"] != "task52"
    assert undo(result).json()["undone"] == 1
    if cal.DEMO:
        assert next(e for e in cal._demo_store if e["id"] == result["id"])["status"] == "rejected"
    else:
        assert calendar[2][result["id"]]["extendedProperties"]["private"]["status"] == "rejected"
