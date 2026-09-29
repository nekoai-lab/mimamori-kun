"""#59: 原文検査・確認待ち・親の確定。全データは架空、外部接続なし。"""
import asyncio
import datetime as dt
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from mimamori import agent, ambiguous_dates as dates, auth, calendar_tools, ledger, notify

TODAY = dt.datetime(2026, 12, 1, 12, tzinfo=dates.JST)


def item(**patch):
    return dict(kind="event", title="運動会", child="上の子", date="2026-12-05",
                date_text="12月5日（土）", date_issues=[], bring=["水筒"], note="", **patch) if not patch else {**item(), **patch}


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    for key in ("K_SERVICE", "MIMAMORI_AUTH", "MIMAMORI_LEDGER", "MIMAMORI_NOTIFY_WEBHOOK"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    monkeypatch.setattr(dates, "now", lambda: TODAY)
    monkeypatch.setattr(calendar_tools, "_demo_store", None)
    monkeypatch.setattr(calendar_tools, "_demo_day", None)
    monkeypatch.setattr(main.recurring_mod, "ensure", lambda: None)
    monkeypatch.setattr(notify, "_push", lambda row: None)


def client(child=False):
    auth.set_passcode(auth.PARENT, "4821")
    auth.set_passcode("下の子", "1058")
    c = TestClient(main.app, base_url="https://testserver")
    assert c.post("/api/auth/login", json={"who": "c1" if child else "parent", "passcode": "1058" if child else "4821"}).status_code == 200
    return c


def extract(c, monkeypatch, items):
    async def read(*args, **kwargs):
        return dict(summary="架空のおたより", items=deepcopy(items))
    monkeypatch.setattr(main, "read_otayori", read)
    monkeypatch.setattr(main.images_mod, "normalize", lambda *args: (b"image", "image/png"))
    return c.post("/api/extract", files={"image": ("test.png", b"image", "image/png")})


CASES = [
    ("再来週の土曜日", "relative", {}),
    ("18日（金）", "no_month", {}),
    ("1月8日", "year_cross", {"date": "2027-01-08"}),
    ("12月5日（金）", "weekday_mismatch", {}),
    ("12月30日〜1月3日", "year_cross", {"date": "2026-12-30", "end_date": "2027-01-03"}),
    ("12/19、12/20", "multiple", {}),
    ("12月中旬", "vague", {}),
    ("未定・後日決定", "undecided", {}),
    ("12月19日または20日", "multiple", {}),
    ("毎週土曜日", "recurring", {}),
    ("12月5日（土）", "low_confidence", {"date_issues": ["low_confidence"]}),
]


@pytest.mark.parametrize("text,issue,patch", CASES)
def test_each_issue_waits_without_calendar(text, issue, patch, monkeypatch):
    c = client()
    before = deepcopy(calendar_tools.list_tasks())
    r = extract(c, monkeypatch, [item(date_text=text, **patch)])
    assert r.status_code == 200
    assert r.json()["items"] == [] and r.json()["date_questions_count"] == 1
    row = c.get("/api/date_questions").json()["items"][0]
    assert issue in row["date_issues"] and row["date"] is None
    assert row["date_text"] == text and row["bring"] == ["水筒"]
    assert row["state"] == "waiting" and row["created_at"] == TODAY.isoformat()
    assert calendar_tools.list_tasks() == before


def test_clear_weekday_and_rain_reserve(monkeypatch):
    c = client()
    r = extract(c, monkeypatch, [item(date_text="12月5日（土） 雨天は12月6日（日）")]).json()
    assert r.get("date_questions_count", 0) == 0 and len(r["items"]) == 1
    assert r["items"][0]["date"] == "2026-12-05"
    assert "雨天は12月6日（日）" in r["items"][0]["note"]
    assert c.post("/api/register", json={"items": r["items"]}).json()["results"][0]["status"] == "ok"


@pytest.mark.parametrize("missing_text", [False, True])
def test_model_stub_partition_precedes_dedupe(monkeypatch, missing_text):
    class Runner:
        def __init__(self, **kwargs): self.session_service = self
        async def create_session(self, **kwargs): return SimpleNamespace(id="test")
        async def run_async(self, **kwargs):
            yield SimpleNamespace(is_final_response=lambda: True, content=SimpleNamespace(parts=[SimpleNamespace(
                text=json.dumps({"summary": "架空", "items": [item(date_text="" if missing_text else "明後日", date="2026-12-05" if missing_text else None), item()]}))]))
    monkeypatch.setattr(agent, "InMemoryRunner", Runner)
    checked = []
    def review(items, child):
        checked.extend(items)
        return dict(items=items, skipped=0, skipped_titles=[])
    monkeypatch.setattr(agent, "_review", review)
    result = asyncio.run(agent.read_otayori(b"dummy", "image/png", child="下の子"))
    assert len(checked) == 1 and checked[0]["date"] == "2026-12-05"
    assert result["date_questions"][0]["child"] == "下の子"
    assert result["date_questions"][0]["date"] is None
    assert "必ずこの日付を起点に実日付へ直す" not in agent._instruction()


def queued(c, monkeypatch, **patch):
    extract(c, monkeypatch, [item(date_text="再来週の土曜日", **patch)])
    return c.get("/api/date_questions").json()["items"][-1]["id"]


def test_explicit_register_only_once_new_branch(monkeypatch):
    c = client()
    before = deepcopy(calendar_tools.list_tasks())
    id_ = queued(c, monkeypatch, branch="moved", matched_id="not-used")
    assert calendar_tools.list_tasks() == before
    body = {"date": "2026-12-12"}
    first = c.post(f"/api/date_questions/{id_}/register", json=body)
    assert first.status_code == 200
    assert c.post(f"/api/date_questions/{id_}/register", json=body).json() == first.json()
    added = [r for r in calendar_tools._demo_store if r["summary"] == "運動会"]
    assert len(added) == 1 and added[0]["date"] == body["date"]
    assert c.get("/api/date_questions").json()["items"] == []


def test_later_persists_first_and_dismiss_never_writes(monkeypatch):
    c = client()
    before = deepcopy(calendar_tools.list_tasks())
    id_ = queued(c, monkeypatch)
    second = queued(c, monkeypatch)
    for _ in range(2):
        assert c.post(f"/api/date_questions/{id_}/later").status_code == 200
        assert client().get("/api/tasks").json()["date_questions"][0]["id"] == id_
    assert c.post(f"/api/date_questions/{id_}/dismiss").status_code == 200
    assert [r["id"] for r in c.get("/api/date_questions").json()["items"]] == [second]
    assert calendar_tools.list_tasks() == before


@pytest.mark.parametrize("path", ["/api/tasks", "/api/notices", "/api/date_questions"])
def test_remind_once_at_three_days(path, monkeypatch):
    c = client()
    queued(c, monkeypatch)
    queued(c, monkeypatch)
    monkeypatch.setattr(dates, "now", lambda: TODAY + dt.timedelta(days=3, seconds=-1))
    c.get(path)
    assert not notify.notices()
    monkeypatch.setattr(dates, "now", lambda: TODAY + dt.timedelta(days=3))
    for _ in range(2): c.get(path)
    assert len(notify.notices()) == 1
    assert "2件" in notify.notices()[0]["body"] and "再来週の土曜日" in notify.notices()[0]["body"]
    assert all(r["reminded_at"] for r in dates.pending())


def test_child_handoff_and_parent_only(monkeypatch):
    c = client(True)
    result = extract(c, monkeypatch, [item(date_text="明後日")]).json()
    assert result["date_questions_count"] == 1 and "date_questions" not in result
    row = dates.pending()[0]
    assert row["child"] == "下の子"
    assert "date_questions" not in c.get("/api/tasks").json()
    assert c.get("/api/date_questions").status_code == 403
    for action in ("register", "later", "dismiss"):
        assert c.post(f"/api/date_questions/{row['id']}/{action}", json={"date": "2026-12-12"}).status_code == 403


@pytest.mark.parametrize("body", [{"date": "2026-02-30"}, {"date": "2026-04-31"}, {"date": "2026-12-12", "end_date": "2026-12-11"}])
def test_invalid_selection_never_writes(body, monkeypatch):
    c = client()
    id_ = queued(c, monkeypatch)
    assert c.post(f"/api/date_questions/{id_}/register", json=body).status_code in (400, 422)
    assert dates.pending()[0]["state"] == "waiting"


def test_range_requires_two_dates(monkeypatch):
    c = client()
    id_ = queued(c, monkeypatch, date_is_range=True)
    assert c.post(f"/api/date_questions/{id_}/register", json={"date": "2026-12-12"}).status_code == 409
    r = c.post(f"/api/date_questions/{id_}/register", json={"date": "2026-12-12", "end_date": "2026-12-14"})
    assert r.status_code == 200
    assert next(r for r in calendar_tools._demo_store if r["summary"] == "運動会")["end_date"] == "2026-12-14"


def test_register_api_rejects_model_guess(monkeypatch):
    c = client()
    assert c.post("/api/register", json={"items": [item(date_text="明後日")]}).status_code == 400


def test_unknown_calendar_result_does_not_retry(monkeypatch):
    c = client()
    id_ = queued(c, monkeypatch)
    calls = []
    def unknown(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()
    monkeypatch.setattr(main, "create_events", unknown)
    assert c.post(f"/api/date_questions/{id_}/register", json={"date": "2026-12-12"}).status_code == 502
    assert c.post(f"/api/date_questions/{id_}/register", json={"date": "2026-12-12"}).status_code == 409
    assert len(calls) == 1 and dates.pending()[0]["state"] == "registering"


@pytest.mark.parametrize("title,display_title", [
    ("下の子｜運動会", "運動会"), ("運動会", "運動会"), ("運動会｜集合", "運動会｜集合"),
])
def test_reminder_display_title_and_child_preserve_saved_calendar_title(title, display_title, monkeypatch):
    c = client()
    id_ = queued(c, monkeypatch, title=title, child="下の子")
    monkeypatch.setattr(dates, "now", lambda: TODAY + dt.timedelta(days=3))
    c.get("/api/notices")
    assert notify.notices()[0]["body"] == (
        f"『{display_title}』（下の子、プリントの表記：『再来週の土曜日』）の日付が決まっていません。"
        "みまもりくんの『確認すること』から日付を選んでください。"
    )
    assert dates.pending()[0]["title"] == title
    assert c.post(f"/api/date_questions/{id_}/register", json={"date": "2026-12-12"}).status_code == 200
    assert any(r["summary"] == title for r in calendar_tools._demo_store)


@pytest.mark.parametrize("patch,expected", [
    ({"child": "elementary"}, "下の子"),
    ({"child": "junior_high"}, "上の子"),
    ({"child": "不明", "title": "下の子｜運動会"}, "下の子"),
    ({"child": "elementary", "title": "上の子｜運動会"}, "上の子"),
    ({"child": "判別不能", "school_level": "elementary"}, "下の子"),
    ({"child": "判別不能"}, "不明"),
    ({"child": "下の子", "title": "上の子｜運動会", "school_level": "junior_high"}, "下の子"),
])
@pytest.mark.parametrize("waiting", [False, True])
def test_child_normalization_before_both_branches(monkeypatch, patch, expected, waiting):
    payload = item(**patch, date_text="明後日" if waiting else "12月5日（土）")
    class Runner:
        def __init__(self, **kwargs): self.session_service = self
        async def create_session(self, **kwargs): return SimpleNamespace(id="test")
        async def run_async(self, **kwargs):
            yield SimpleNamespace(is_final_response=lambda: True, content=SimpleNamespace(parts=[SimpleNamespace(
                text=json.dumps({"summary": "架空", "items": [payload]}))]))
    monkeypatch.setattr(agent, "InMemoryRunner", Runner)
    monkeypatch.setattr(agent, "build_agent", lambda child: None)
    reviewed = []
    def review(items, child):
        reviewed.extend(deepcopy(items))
        return dict(items=items, skipped=0, skipped_titles=[])
    monkeypatch.setattr(agent, "_review", review)
    result = asyncio.run(agent.read_otayori(b"dummy", "image/png"))
    row = result["date_questions" if waiting else "items"][0]
    assert row["child"] == expected
    assert row["title"] == payload["title"]
    if expected == "不明":
        assert row["needs_review"] is True
    if not waiting:
        assert reviewed[0]["child"] == expected
    # 子どもが撮った場合はモデルの名前・件名より撮った子を優先する。
    scoped = asyncio.run(agent.read_otayori(b"dummy", "image/png", child="下の子"))
    assert scoped["date_questions" if waiting else "items"][0]["child"] == "下の子"


@pytest.mark.parametrize("waiting", [False, True])
def test_same_school_level_does_not_choose_arbitrary_child(monkeypatch, waiting):
    monkeypatch.setattr(agent.config, "children", [
        {"name": "子A", "school_level": "elementary"},
        {"name": "子B", "school_level": "elementary"},
    ])
    test_child_normalization_before_both_branches(monkeypatch, {"child": "elementary"}, "不明", waiting)


@pytest.mark.parametrize("invalid_child", [None, "不明", "elementary", "設定外"])
def test_unknown_child_requires_valid_selection_before_registration(monkeypatch, invalid_child):
    c = client()
    id_ = queued(c, monkeypatch, child="不明")
    before = deepcopy(calendar_tools.list_tasks())
    body = {"date": "2026-12-12", "child": invalid_child}
    assert c.post(f"/api/date_questions/{id_}/register", json=body).status_code == 409
    assert dates.pending()[0]["state"] == "waiting"
    assert calendar_tools.list_tasks() == before
    body["child"] = "下の子"
    assert c.post(f"/api/date_questions/{id_}/register", json=body).status_code == 200
    assert any(r["child"] == "下の子" and r["summary"] == "運動会" for r in calendar_tools._demo_store)


@pytest.mark.parametrize("original,chosen", [
    ("12月5日（土）", "2026-12-06"),
    ("12月5日（金）", "2026-12-06"),
    ("1月8日", "2027-01-09"),
])
def test_parent_edited_date_registers_without_rechecking_source(original, chosen):
    c = client()
    r = c.post("/api/register", json={"items": [item(date_text=original, date=chosen, date_edited=True)]})
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "ok"
    assert next(r for r in calendar_tools._demo_store if r["summary"] == "運動会")["date"] == chosen


@pytest.mark.parametrize("patch", [
    {"date": "2026-12-06"},
    {"date_text": "12月5日（金）"},
    {"date": None, "date_edited": True},
    {"date": "2026-02-30", "date_edited": True},
    {"date": "20261206", "date_edited": True},
    {"date_issues": ["low_confidence"], "date_edited": True},
    {"end_date": "2026-12-04", "date_edited": True},
])
def test_rejected_date_does_not_block_valid_candidate(patch):
    c = client()
    bad = item(**patch)
    good = item(title="登録できる予定")
    r = c.post("/api/register", json={"items": [bad, good]})
    assert r.status_code == 200
    results = r.json()["results"]
    assert [(r["input_index"], r["status"]) for r in results] == [(0, "rejected"), (1, "ok")]
    assert results[0]["error"]
    assert not any(r["summary"] == bad["title"] for r in calendar_tools._demo_store)
    assert any(r["summary"] == good["title"] for r in calendar_tools._demo_store)
    assert c.post("/api/register", json={"items": [bad]}).status_code == 400


def test_child_cannot_claim_parent_date_edit():
    c = client(True)
    r = c.post("/api/register", json={"items": [item(child="下の子", date="2026-12-06", date_edited=True)]})
    assert r.status_code == 400
