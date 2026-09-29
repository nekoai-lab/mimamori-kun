"""#69: 架空のプリントをモデル応答で再現。Calendar/台帳もローカルのみ。"""
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

import main
from mimamori import ambiguous_dates as dates, calendar_tools, dedupe, ledger
from test_ambiguous_dates import TODAY, client, fresh, item
from test_extract_retry import fake_runner


@pytest.fixture(params=["/api/extract", "/api/extract/stream"])
def capture(request, monkeypatch, fake_runner):
    monkeypatch.setattr(main.images_mod, "normalize", lambda *a: (b"fixture", "image/png"))

    def read(c, rows):
        fake_runner.replies = [json.dumps({"summary": "架空", "items": deepcopy(rows)})]
        response = c.post(request.param, files={"image": ("fixture.png", b"fixture", "image/png")})
        assert response.status_code == 200
        if request.param.endswith("/stream"):
            result = json.loads(response.text.splitlines()[-1])
            assert result["type"] == "done"
            return result
        return response.json()
    return read


def question(**patch):
    return item(title="社会科見学 Ａ 参加同意書 提出", child="下の子",
                date=None, date_text="来週の水曜日まで", **patch) if not patch else {**question(), **patch}


def records():
    return ledger.get_setting(dates.KEY) or []


def events():
    return [r for r in calendar_tools.list_raw("2025-01-01", "2028-01-01")
            if dedupe.norm(r["summary"]) == dedupe.norm(question()["title"])]


@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("state", ["waiting", "registering", "registered", "answered"])
def test_repeat_question(capture, child, state):
    c = client(child)
    first = capture(c, [question()])
    assert first["date_questions_count"] == 1
    original_id = records()[0]["id"]
    if state == "registered":
        parent = client()
        response = parent.post(f"/api/date_questions/{original_id}/register", json={"date": "2026-12-09"})
        assert response.status_code == 200
    elif state != "waiting":
        ledger.transact_setting(dates.KEY, lambda rows: [dict(r, state=state) for r in rows])
    second = capture(c, [question(title="社会科見学 A 参加同意書 提出")])
    assert second.get("date_questions_count", 0) == 0
    assert len(records()) == 1 and records()[0]["id"] == original_id
    assert records()[0]["state"] == state
    assert len(events()) == (1 if state == "registered" else 0)
    assert second["skipped"] == (1 if state in ("registered", "answered") else 0)
    assert second["skipped_titles"] == (["社会科見学 A 参加同意書 提出"] if state in ("registered", "answered") else [])


@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("registered", [False, True])
def test_different_date_text_keeps_question(capture, child, registered):
    c = client(child)
    capture(c, [question()])
    if registered:
        assert client().post(f"/api/date_questions/{records()[0]['id']}/register",
                             json={"date": "2026-12-09"}).status_code == 200
    result = capture(c, [question(date_text="再来週の水曜日まで")])
    assert result["date_questions_count"] == 1
    assert result["skipped"] == 0
    assert len(records()) == 2
    assert len(events()) == int(registered)


@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("registered", [False, True])
def test_sibling_keeps_question(capture, child, registered):
    capture(client(), [question(child="上の子")])
    if registered:
        assert client().post(f"/api/date_questions/{records()[0]['id']}/register",
                             json={"date": "2026-12-09"}).status_code == 200
    result = capture(client(child), [question()])
    assert result["date_questions_count"] == 1 and result["skipped"] == 0
    assert [r["child"] for r in records()] == ["上の子", "下の子"]
    assert len(events()) == int(registered)


@pytest.mark.parametrize("child", [False, True])
def test_calendar_only_counts_as_skipped(capture, child):
    calendar_tools.create_events([question(date="2026-12-09")])
    result = capture(client(child), [question()])
    assert result.get("date_questions_count", 0) == 0
    assert result["skipped"] == 1 and result["skipped_titles"] == [question()["title"]]
    assert records() == [] and len(events()) == 1


def test_atomic_enqueue_and_batch_duplicates(monkeypatch):
    monkeypatch.setattr(calendar_tools, "list_raw", lambda *a: [])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: dates.enqueue([question(), question()]), range(4)))
    assert len(records()) == 1
    assert sum(r["count"] for r in results) == 1
    assert all(r["skipped_titles"] == [] for r in results)


@pytest.mark.parametrize("state", ["waiting", "registered"])
def test_nfkc_date_text_and_calendar_failure(monkeypatch, state):
    dates.enqueue([question(date_text="１２月中旬")])
    ledger.transact_setting(dates.KEY, lambda rows: [dict(r, state=state) for r in rows])
    def unavailable(*args):
        raise TimeoutError("fixture")
    monkeypatch.setattr(calendar_tools, "list_raw", unavailable)
    result = dates.enqueue([question(date_text="12月中旬")])
    assert len(records()) == 1
    assert result["count"] == 0
    assert len(result["skipped_titles"]) == int(state == "registered")
    assert dates.enqueue([question(date_text="１月中旬")])["count"] == 1


def test_dismissed_question_can_be_asked_again():
    dates.enqueue([question()])
    dates.change(records()[0]["id"], "dismiss")
    dates.enqueue([question()])
    assert len(dates.pending()) == 1


def test_confirmed_without_calendar_id_keeps_other_date_text():
    dates.enqueue([question()])
    row = records()[0]
    dates.change(row["id"], "register", "2026-12-09")
    calendar_tools.create_events([question(date="2026-12-09")])
    dates.change(row["id"], "confirmed")
    dates.enqueue([question(date_text="再来週の水曜日まで")])
    assert len(records()) == 2 and len(events()) == 1


def test_existing_skipped_totals_are_preserved():
    calendar_tools.create_events([question(date="2026-12-09")])
    result = main._finish_extract({"items": [], "date_questions": [question()],
                                  "skipped": 1, "skipped_titles": ["明確な日付の予定"]}, "parent")
    assert result["skipped"] == 2
    assert result["skipped_titles"] == ["明確な日付の予定", question()["title"]]
    assert records() == []
