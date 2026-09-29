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
            read.events = [json.loads(line) for line in response.text.splitlines()]
            result = read.events[-1]
            assert result["type"] == "done"
            return result
        return response.json()
    read.events = []
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
    first_question_events = [e["type"] for e in capture.events if e["type"] == "question"]
    original_id = records()[0]["id"]
    if state == "registered":
        parent = client()
        response = parent.post(f"/api/date_questions/{original_id}/register", json={"date": "2026-12-09"})
        assert response.status_code == 200
    elif state != "waiting":
        ledger.transact_setting(dates.KEY, lambda rows: [dict(r, state=state) for r in rows])
    second = capture(c, [question(title="社会科見学 A 参加同意書 提出")])
    assert second.get("date_questions_count", 0) == int(state in ("waiting", "registering"))
    assert second["items"] == []
    if state in ("waiting", "registering"):
        assert [e["type"] for e in capture.events if e["type"] == "question"] == first_question_events
        if capture.events:
            assert first_question_events == ["question"]
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
    assert all(r["count"] == 1 for r in results)
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
    assert result["count"] == int(state == "waiting")
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


@pytest.mark.parametrize("state", ["waiting", "registering", "registered", "answered"])
@pytest.mark.parametrize("before,after,old_date,new_date", [
    ("予行練習", "運動会予行練習", "運動会の前週の木曜日 午前中", "運動会の前週の木曜日 午前中"),
    ("はちまき準備", "はちまき持参", "今週の金曜日まで", "今週の金曜日まで"),
    ("はちまき準備", "はちまき(黒い布) 持参", "今週の金曜日まで", "今週の金曜日までに"),
])
def test_fuzzy_paraphrases(capture, state, before, after, old_date, new_date):
    c = client()
    capture(c, [question(title=before, date_text=old_date)])
    original = records()[0]
    ledger.transact_setting(dates.KEY, lambda rows: [dict(r, state=state) for r in rows])
    result = capture(c, [question(title=after, date_text=new_date)])
    pending = state in ("waiting", "registering")
    assert result["date_questions_count"] == 1
    assert result["skipped_titles"] == []
    assert records()[0] == dict(original, state=state)
    assert len(records()) == (1 if pending else 2)


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("before,after,date_text", [
    ("はちまき準備 期限", "はちまき準備", "今週の金曜日まで"),
    ("観覧者名簿 提出期限", "観覧者名簿提出", "来週の水曜日まで"),
    ("お弁当の有無確認票 提出期限", "お弁当の有無確認票提出", "運動会の前日まで"),
])
def test_deadline_suffix_reread(capture, registered, before, after, date_text):
    c = client()
    capture(c, [question(title=before, date_text=date_text)])
    if registered:
        assert c.post(f"/api/date_questions/{records()[0]['id']}/register",
                      json={"date": "2026-12-09"}).status_code == 200
    original = records()[0]
    result = capture(c, [question(title=after, date_text=date_text)])
    assert result["date_questions_count"] == 1
    assert result["skipped_titles"] == []
    assert records()[0] == original
    assert len(records()) == (2 if registered else 1)
    if registered:
        assert records()[1]["title"] == after
        assert records()[1]["state"] == "waiting"


@pytest.mark.parametrize("suffix", ["期限", "締切", "締め切り", "〆切", "しめきり"])
@pytest.mark.parametrize("after", ["はちまき準備", "はちまき持参"])
@pytest.mark.parametrize("reverse", [False, True])
def test_deadline_suffix_before_title_paraphrase(suffix, after, reverse):
    before = f"はちまき準備 {suffix}"
    if reverse:
        before, after = after, before
    dates.enqueue([question(title=before)])
    original = records()
    assert dates.enqueue([question(title=after)]) == {"count": 1, "skipped_titles": []}
    assert records() == original


@pytest.mark.parametrize("before,after,old_date,new_date", [
    ("運動会", "運動会振替休業日", "再来週の土曜日", "再来週の土曜日"),
    ("運動会", "運動会当日の持ち物", "再来週の土曜日 午前8時45分開会（雨天順延）", "再来週の土曜日"),
    ("観覧者名簿 提出", "お弁当の有無確認票 提出", "今週の金曜日まで", "今週の金曜日まで"),
])
def test_fuzzy_distinct_questions(before, after, old_date, new_date):
    dates.enqueue([question(title=before, date_text=old_date)])
    result = dates.enqueue([question(title=after, date_text=new_date)])
    assert result == {"count": 1, "skipped_titles": []}
    assert [r["title"] for r in records()] == [before, after]


@pytest.mark.parametrize("reverse", [False, True])
def test_fuzzy_exact_titles_take_priority(reverse):
    batch = [question(title=t, date_text="今週の金曜日まで")
             for t in ("算数プリント 提出", "国語プリント 提出")]
    assert dates.enqueue(batch)["count"] == 2
    original = records()
    # 状態を分け、片方がもう片方の記録に吸収されていないことも確かめる。
    ledger.transact_setting(dates.KEY, lambda rows: [dict(rows[0], state="registered"), rows[1]])
    result = dates.enqueue(list(reversed(batch)) if reverse else batch)
    assert result == {"count": 1, "skipped_titles": [batch[0]["title"]]}
    assert records() == [dict(original[0], state="registered"), original[1]]


def test_fuzzy_one_existing_row_cannot_absorb_two_candidates():
    dates.enqueue([question(title="はちまき準備")])
    original = records()[0]
    result = dates.enqueue([question(title="はちまき持参"), question(title="はちまき準備")])
    assert result == {"count": 2, "skipped_titles": []}
    assert len(records()) == 2
    assert records()[0] == original
    assert records()[1]["title"] == "はちまき持参"


def test_fuzzy_one_pending_row_accepts_only_one_paraphrase():
    dates.enqueue([question(title="予行練習")])
    result = dates.enqueue([question(title="運動会予行練習"), question(title="秋の予行練習")])
    assert result == {"count": 2, "skipped_titles": []}
    assert len(records()) == 2
    assert records()[1]["title"] == "秋の予行練習"


def test_fuzzy_siblings_remain_separate():
    dates.enqueue([question(title="はちまき準備", child="上の子")])
    assert dates.enqueue([question(title="はちまき（黒い布）持参")])["count"] == 1
    assert len(records()) == 2


@pytest.mark.parametrize("brackets", ["(黒い布)", "（黒い布）", "【黒い布】", "[黒い布]", "〔黒い布〕", "（黒い【布】）"])
def test_batch_keeps_supplements_and_rereads_exactly(brackets):
    batch = [question(title="はちまき持参", date_text="今週の金曜日まで"),
             question(title=f"はちまき{brackets} 持参", date_text="今週の金曜日まで（朝）")]
    assert dates.enqueue(batch) == {"count": 2, "skipped_titles": []}
    original = records()
    assert dates.enqueue(batch[::-1])["count"] == 2
    assert records() == original


def test_fuzzy_two_pending_prints_survive_rereading():
    batch = [question(title=t, date_text="今週の金曜日まで")
             for t in ("算数プリント 提出", "国語プリント 提出")]
    assert dates.enqueue(batch)["count"] == 2
    original = records()
    assert dates.enqueue(batch[::-1]) == {"count": 2, "skipped_titles": []}
    assert records() == original


def test_date_supplement_is_part_of_original_date_similarity():
    dates.enqueue([question(title="はちまき【黒い布】準備", date_text="今週の金曜日まで（朝に教室で先生に提出）")])
    original = records()
    assert dates.enqueue([question(title="はちまき持参", date_text=" 今週の 金曜日までに ")])["count"] == 1
    assert len(records()) == 2
    assert records()[0] == original[0]


@pytest.mark.parametrize("state", ["waiting", "registering", "registered", "answered"])
@pytest.mark.parametrize("old_date,new_date", [
    ("来週の水曜日まで", "再来週の水曜日まで"),
    ("12月中旬", "1月中旬"),
    ("運動会の前週の水曜日まで", "運動会の翌週の水曜日まで"),
    ("来週の水曜日まで", "来週の木曜日まで"),
    ("来週の提出日(水)まで", "来週の提出日(木)まで"),
    ("来週の提出日(水)まで", "来週の提出日まで"),
    ("12月中旬までに提出", "12月下旬までに提出"),
    ("12月末までに提出", "12月初までに提出"),
    ("運動会の前日までに提出", "運動会の前々日までに提出"),
    ("運動会の翌日までに提出", "運動会の翌々日までに提出"),
    ("提出予定日(12月中旬)", "提出予定日(1月中旬)"),
])
def test_date_anchors_keep_separate_questions(state, old_date, new_date):
    dates.enqueue([question(date_text=old_date)])
    ledger.transact_setting(dates.KEY, lambda rows: [dict(r, state=state) for r in rows])
    original = records()[0]
    assert dates.enqueue([question(date_text=new_date)]) == {"count": 1, "skipped_titles": []}
    assert len(records()) == 2 and records()[0] == original
    assert records()[1]["date_text"] == new_date


@pytest.mark.parametrize("old_date,new_date", [
    ("来週の提出日(水)まで", "来週の提出日(木)まで"),
    ("提出予定日(12月中旬)", "提出予定日(1月中旬)"),
])
def test_batch_keeps_different_date_anchors(old_date, new_date):
    assert dates.enqueue([question(date_text=old_date), question(date_text=new_date)]) == {
        "count": 2, "skipped_titles": []}
    assert [r["date_text"] for r in records()] == [old_date, new_date]


@pytest.mark.parametrize("old_date,new_date", [
    ("来週の提出日（水）まで", "来週の提出日(水曜)までに"),
    ("来週の水曜日まで", "来週の水曜までに"),
    ("運動会の前週の木曜日 午前中", "運動会の前週の木曜日"),
    ("１２月中旬ごろ", "12月中旬ごろまで"),
])
def test_date_anchor_spelling_variations(old_date, new_date):
    dates.enqueue([question(date_text=old_date)])
    original = records()
    assert dates.enqueue([question(date_text=new_date)]) == {"count": 1, "skipped_titles": []}
    assert records() == original


@pytest.mark.parametrize("state", ["waiting", "registering", "registered", "answered"])
@pytest.mark.parametrize("before,after,date_text", [
    ("算数プリント 提出", "国語プリント 提出", "今週の金曜日まで"),
    ("算数プリント 提出期限", "国語プリント 提出", "今週の金曜日まで"),
    ("保護者会 出欠票 提出", "遠足 出欠票 提出", "今週の金曜日まで"),
    ("持ち物(体操服)", "持ち物(水着)", "来週の月曜日"),
])
def test_distinct_questions_are_never_silently_dropped(capture, state, before, after, date_text):
    c = client()
    capture(c, [question(title=before, date_text=date_text)])
    original = records()[0]
    if state == "registered":
        assert c.post(f"/api/date_questions/{original['id']}/register",
                      json={"date": "2026-12-09"}).status_code == 200
    else:
        ledger.transact_setting(dates.KEY, lambda rows: [dict(r, state=state) for r in rows])
    result = capture(c, [question(title=after, date_text=date_text)])
    assert result["date_questions_count"] == 1
    assert result["skipped"] == 0
    assert [r["title"] for r in records()] == [before, after]


def test_batch_preserves_different_parenthesis_contents(capture):
    result = capture(client(), [question(title=t, date_text="来週の月曜日")
                                for t in ("持ち物(体操服)", "持ち物(水着)")])
    assert result["date_questions_count"] == 2
    assert result["skipped"] == 0
    assert [r["title"] for r in records()] == ["持ち物(体操服)", "持ち物(水着)"]


@pytest.mark.parametrize("old_date,new_date", [
    ("今週の金曜日まで", "今週の金曜日までに"),
    ("今週の金曜日まで", " 今週の金曜日まで "),
    ("今週の金曜日まで(朝)", "今週の金曜日まで"),
])
def test_nonexact_dates_do_not_match_completed_question(old_date, new_date):
    dates.enqueue([question(date_text=old_date)])
    ledger.transact_setting(dates.KEY, lambda rows: [dict(r, state="registered") for r in rows])
    assert dates.enqueue([question(date_text=new_date)]) == {"count": 1, "skipped_titles": []}
    assert len(records()) == 2

@pytest.mark.parametrize("verb", [
    "準備", "持参", "用意", "持ってくる", "持っていく", "持ってくること", "持ってくるもの",
])
def test_allowed_terminal_verbs(verb):
    dates.enqueue([question(title="はちまき準備")])
    original = records()
    assert dates.enqueue([question(title=f"はちまき{verb}")]) == {"count": 1, "skipped_titles": []}
    assert records() == original


@pytest.mark.parametrize("before,after", [
    ("服準備", "服持参"),
    ("会", "運動会"),
    ("はちまき準備", "はちまき"),
    ("はちまき持参", "はちまき持参予定"),
    ("はちまき(黒い布)準備", "はちまき(赤い布)持参"),
    ("はちまき準備期限締切", "はちまき準備"),
    ("期限はちまき準備", "はちまき持参"),
    ("服期限", "冬服"),
    ("期限", "提出"),
])
def test_title_paraphrase_boundaries(before, after):
    dates.enqueue([question(title=before)])
    dates.enqueue([question(title=after)])
    assert len(records()) == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_full_exact_key_precedes_date_paraphrase(reverse):
    dates.enqueue([question()])
    batch = [question(date_text="来週の水曜日までに"), question()]
    assert dates.enqueue(batch[::-1] if reverse else batch)["count"] == 2
    assert [r["date_text"] for r in records()] == ["来週の水曜日まで", "来週の水曜日までに"]
