"""#69: 親の登録時だけ既存予定を照合する。外部接続なし。"""
from copy import deepcopy

import pytest

import main
from mimamori import ambiguous_dates as dates, calendar_tools, dedupe, ledger
from test_ambiguous_dates import client, fresh, item  # noqa: F401

DAY = "2026-10-17"


def question(title, child="下の子", text="再来週の土曜日 午前8時45分開会（雨天順延）"):
    # 原文の違いで別々に残った確認待ちを再現する。
    dates.enqueue([item(title=title, child=child, date=None, date_text=text)])
    return dates.pending()[-1]["id"]


def register(c, id_, day=DAY, **patch):
    response = c.post(f"/api/date_questions/{id_}/register", json={"date": day, **patch})
    assert response.status_code == 200, response.text
    return response.json()


def test_second_question_keeps_existing_event_and_points(monkeypatch):
    c = client()
    first = question("下の子｜運動会", text="再来週の土曜日")
    second = question("運動会")
    assert first != second
    original = register(c, first)["results"][0]["id"]
    before = deepcopy(calendar_tools._demo_store)
    points = {child: ledger.balance(child) for child in ("上の子", "下の子")}
    assert dedupe.norm("下の子｜運動会") == dedupe.norm("運動会")
    result = register(c, second, time_start="08:45")
    assert result["already"] is True and result["state"] == "registered"
    assert result["results"][0]["status"] == "same"
    assert result["results"][0]["id"] == original
    assert calendar_tools._demo_store == before
    assert {child: ledger.balance(child) for child in points} == points
    assert c.get("/api/date_questions").json()["items"] == []
    saved = next(r for r in ledger.get_setting(dates.KEY) if r["id"] == second)
    assert saved["state"] == "registered" and saved["result"] == result
    assert register(c, second) == result
    assert calendar_tools._demo_store == before


@pytest.mark.parametrize("old,new", [
    ("予行練習", "運動会予行練習"),
    ("はちまき準備", "はちまき持参"),
    ("申込書提出", "申込書提出期限"),
    ("申込書提出締切", "申込書提出"),
])
def test_conservative_paraphrases(old, new, monkeypatch):
    c = client()
    q = question(new)
    existing = calendar_tools.create_events([item(title=old, child="下の子", date=DAY)])[0]
    before = deepcopy(calendar_tools._demo_store)
    monkeypatch.setattr(dedupe, "similarity", lambda *args: pytest.fail("類似度は使わない"))
    result = register(c, q)
    assert result["already"] is True
    assert result["results"][0]["id"] == existing["id"]
    assert calendar_tools._demo_store == before


@pytest.mark.parametrize("old,new,day,child", [
    ("算数プリント 提出", "国語プリント 提出", DAY, "下の子"),
    ("持ち物(体操服)", "持ち物(水着)", DAY, "下の子"),
    ("運動会", "運動会", "2026-10-18", "下の子"),
    ("運動会", "運動会", DAY, "上の子"),
    ("運動会", "運動会予備日", DAY, "下の子"),
])
def test_distinct_events_are_created(old, new, day, child):
    c = client()
    q = question(new)
    calendar_tools.create_events([item(title=old, child=child, date=day)])
    before = deepcopy(calendar_tools._demo_store)
    result = register(c, q)
    assert not result.get("already") and result["results"][0]["status"] == "ok"
    assert len(calendar_tools._demo_store) == len(before) + 1
    assert calendar_tools._demo_store[:-1] == before


def test_calendar_read_failure_still_creates(monkeypatch):
    c = client()
    q = question("運動会")
    def unavailable(*args):
        raise OSError("offline")
    monkeypatch.setattr(main, "list_raw", unavailable)
    assert register(c, q)["results"][0]["status"] == "ok"
    assert not dates.pending()


def test_rejected_event_does_not_block_registration():
    c = client()
    q = question("運動会")
    calendar_tools.create_events([item(child="下の子", date=DAY)], "rejected")
    assert register(c, q)["results"][0]["status"] == "ok"


@pytest.mark.parametrize("persisted", [False, True])
def test_undo_same_result_cannot_change_existing_but_can_undo_new(persisted):
    c = client()
    q = question("運動会")
    original = calendar_tools.create_events([item(child="下の子", date=DAY)])[0]["id"]
    if persisted:
        # 保存済み結果だけでも保護する（登録ガードとは独立した回帰検査）。
        dates.change(q, "register", DAY)
        result = {"state": "registered", "already": True,
                  "results": [{"status": "same", "id": original}]}
        dates.finish(q, result)
    else:
        result = register(c, q)
    before = deepcopy(next(e for e in calendar_tools._demo_store if e["id"] == original))
    other = calendar_tools.create_events([item(title="別の予定", child="下の子", date=DAY)])[0]["id"]
    undone = c.post("/api/register/undo", json={"ids": [result["results"][0]["id"], other]})
    assert undone.status_code == 200
    assert undone.json() == {"undone": 1, "failed": [original]}
    assert next(e for e in calendar_tools._demo_store if e["id"] == original) == before
    assert next(e for e in calendar_tools._demo_store if e["id"] == other)["status"] == "rejected"
