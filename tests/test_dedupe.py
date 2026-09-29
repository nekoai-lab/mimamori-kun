"""#46: 表記揺れと、デモの同名・別日予定がある場合の再取り込み。

見本は9月18日、デモの社会科見学は今日+6日。同点で先の予定を
選び続けると、同日の登録があっても moved になり、再び登録候補に残る。
"""
import datetime as dt
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
from mimamori import agent, calendar_tools, dedupe


@pytest.mark.parametrize("title", [
    "下の子｜ＡＢＣ１２３（見学）",
    "✓ 下の子｜ABC123 (見学)",
    "下の子|ＡＢＣ　１２３ ［見学］",
    "ABC123見学",
])
def test_norm_width_spaces_and_child_prefix(title):
    assert dedupe.norm(title) == "abc123見学"


@pytest.mark.parametrize("reverse", [False, True])
def test_same_day_wins_title_score_tie(reverse):
    item = dict(title="下の子｜社会科見学 (清掃工場)", date="2026-09-18")
    other_day = dict(id="demo", summary="下の子｜社会科見学（清掃工場）", date="2026-10-05")
    same_day = dict(other_day, id="registered", date=item["date"])
    rows = [other_day, same_day]
    verdict = dedupe.classify(item, rows[::-1] if reverse else rows)
    assert verdict["branch"] == "same"
    assert verdict["matched"]["id"] == "registered"


@pytest.mark.parametrize(("patch", "branch"), [
    ({}, "same"),
    ({"bring": ["水筒"]}, "diff"),
    ({"time_start": "08:15"}, "diff"),
    ({"date": "2026-09-19"}, "moved"),
    ({"date": "2027-09-18"}, "new"),
    ({"title": "運動会"}, "new"),
])
def test_four_branches_preserve_information_and_date_changes(patch, branch):
    item = dict(title="社会科見学 (清掃工場)", date="2026-09-18")
    existing = [dict(summary="下の子｜社会科見学（清掃工場）", date=item["date"])]
    assert dedupe.classify(dict(item, **patch), existing)["branch"] == branch


@pytest.mark.parametrize(("first_title", "second_title"), [
    ("下の子｜社会科見学 (清掃工場)", "下の子｜社会科見学（清掃工場）"),
    ("下の子｜ABC123 (見学)", "下の子｜ＡＢＣ１２３（見学）"),
    ("下の子｜社会科 見学　(清掃 工場)", "社会科見学（清掃工場）"),
])
def test_phone_then_pc_extract_register_once(monkeypatch, first_title, second_title):
    # Gemini の結果だけを固定し、実際の照合・期間検索・API・デモ書き込みを通す。
    # 今日が変わっても、初期予定と見本の17日差を再現する。
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("MIMAMORI_AUTH", "off")
    monkeypatch.setattr(calendar_tools, "DEMO", True)
    monkeypatch.setattr(calendar_tools, "_demo_store", [])
    monkeypatch.setattr(calendar_tools, "_demo_day", "")
    demo_items = calendar_tools._demo_items
    monkeypatch.setattr(calendar_tools, "_demo_items", lambda today: demo_items(dt.date(2026, 9, 29)))
    titles = iter([first_title, second_title])
    base = dict(child="下の子", kind="event", date="2026-09-18", time_start="08:15",
                bring=["お弁当", "水筒", "ハンカチ", "しおり", "筆記用具"])

    async def fake_read(image_bytes, mime_type, hint="", child=None):
        return agent._review([dict(base, title=next(titles))], child)

    monkeypatch.setattr(main, "read_otayori", fake_read)
    image = BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="PNG")
    phone = TestClient(main.app)
    pc = TestClient(main.app)

    def extract(client):
        response = client.post("/api/extract", files={"image": ("sample.png", image.getvalue(), "image/png")})
        assert response.status_code == 200
        return response.json()

    first = extract(phone)
    assert first["skipped"] == 0
    assert len(first["items"]) == 1
    demo_event = next(e.copy() for e in calendar_tools._demo_store if e["id"] == "d5")
    moves_demo = dedupe.norm(first_title) == dedupe.norm(demo_event["summary"])
    if moves_demo:
        assert first["items"][0]["branch"] == "moved"
        assert first["items"][0]["matched_id"] == demo_event["id"]
        assert demo_event["date"] != base["date"]
    # 同名の初期予定があるケースは moved。親が選んだ候補を登録する。
    # 子ども画面でも same 以外は登録対象になる。
    response = phone.post("/api/register", json={"items": first["items"]})
    assert response.status_code == 200
    assert [r["status"] for r in response.json()["results"]] == ["ok"]
    if moves_demo:
        moved = next(e for e in calendar_tools._demo_store if e["id"] == demo_event["id"])
        assert moved["date"] == base["date"]
        assert moved["summary"] == demo_event["summary"]
        assert response.json()["results"][0]["id"] == demo_event["id"]
    second = extract(pc)
    assert second == {"items": [], "skipped": 1, "skipped_titles": [second_title]}
    # 完全一致は画面から登録しない。同日分は1件、日程変更なら既存のID・件名を保つ。
    rows = calendar_tools.list_raw(base["date"], base["date"])
    assert len(rows) == 1
    assert rows[0]["summary"] == (demo_event["summary"] if moves_demo else first_title)
    assert rows[0]["id"] == response.json()["results"][0]["id"]
    if moves_demo:
        same_event = [e for e in calendar_tools._demo_store
                      if dedupe.norm(e["summary"]) == dedupe.norm(demo_event["summary"])]
        assert len(same_event) == 1
        assert same_event[0]["id"] == demo_event["id"]
    else:
        assert any(e["id"] == "d5" for e in calendar_tools._demo_store)
