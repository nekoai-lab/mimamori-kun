"""UX 塊 F：子ごとの設定（見た目・相棒・学年と読み）の口（design/UX_SPEC.md §3.3・§4.3、Issue #24）。

GET  /api/child-settings?child=<子>     → {"child", "settings", "reading_policy"}
POST /api/child-settings  {"child", 送る項目だけ} → 同じ形（送った項目だけを変える）

- 子どもは自分のぶんだけ（ほかの子は 403）。子どもが変えられるのは見た目と相棒の名前だけ。学年・読み・文体は親だけ
- 送った項目だけを変える：テーマを書いても名前・学年は消えない。その逆も同じ
- 保存して読み直す・別の端末（別の Cookie）で開く・保存先を開き直す、のどれでも同じ値が戻る
- 形の違う値・知らない項目は受け取らない。保存できなかったのに成功を返さない
- G（kid_agent）がサーバー側で相棒の名前・文体を読める。/api/week は取得失敗を 0件にしない
デモの台帳（MIMAMORI_DEMO=1）とローカルの JSON（tmp）で動かす。GCP には繋がない。
"""
import pytest
from fastapi.testclient import TestClient

import main
from mimamori import appearance, auth, calendar_tools, kid_agent, ledger

OLDER, YOUNGER = "上の子", "下の子"
WHO = {auth.PARENT: "parent", OLDER: "c0", YOUNGER: "c1"}
CODES = {auth.PARENT: "4821", OLDER: "7394", YOUNGER: "1058"}
API = "/api/child-settings"


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    for name in ("K_SERVICE", "MIMAMORI_AUTH", "MIMAMORI_LEDGER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    monkeypatch.setattr(calendar_tools, "_demo_store", None)
    monkeypatch.setattr(calendar_tools, "_demo_day", None)
    for user, code in CODES.items():
        auth.set_passcode(user, code)
    yield tmp_path


def login(user):
    c = TestClient(main.app, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"who": WHO[user], "passcode": CODES[user]})
    assert r.status_code == 200, r.text
    return c


def post(c, **body):
    return c.post(API, json=body)


# ---------------------------------------------------------------- 権限

def test_login_required():
    c = TestClient(main.app, base_url="https://testserver")
    assert c.get(API, params={"child": YOUNGER}).status_code == 401
    assert c.post(API, json={"child": YOUNGER, "theme_id": "snow-bird"}).status_code == 401


def test_child_reads_and_writes_only_their_own():
    kid = login(YOUNGER)
    assert kid.get(API, params={"child": YOUNGER}).status_code == 200
    assert kid.get(API).json()["child"] == YOUNGER                       # 省略したら自分
    assert kid.get(API, params={"child": OLDER}).status_code == 403
    assert post(kid, child=OLDER, theme_id="snow-bird").status_code == 403
    assert appearance.read(OLDER) == {}


@pytest.mark.parametrize("field,value", [
    ("school_grade", "e3"), ("kanji_scope", "current_grade"), ("ruby_mode", "all"),
    ("companion_language_level", "standard"), ("known_kanji_overrides", ["学"]), ("ruby_word_overrides", ["音読"]),
])
def test_child_cannot_change_parent_only_fields(field, value):
    kid = login(YOUNGER)
    r = post(kid, child=YOUNGER, **{field: value})
    assert r.status_code == 403 and field in r.json()["detail"]
    assert appearance.read(YOUNGER) == {}
    # 親は変えられる
    assert post(login(auth.PARENT), child=YOUNGER, **{field: value}).status_code == 200


def test_child_can_change_theme_and_companion_name():
    kid = login(YOUNGER)
    r = post(kid, child=YOUNGER, theme_id="snow-bird", theme_schema_version=1, companion_name="ぴよ")
    assert r.status_code == 200
    assert r.json()["settings"] == {"theme_id": "snow-bird", "theme_schema_version": 1, "companion_name": "ぴよ"}


def test_parent_reads_any_family_child_but_not_strangers():
    parent = login(auth.PARENT)
    assert parent.get(API, params={"child": OLDER}).status_code == 200
    assert parent.get(API, params={"child": "知らない子"}).status_code == 404
    assert parent.get(API).status_code == 400                            # 親はだれのぶんかを指定する


# ---------------------------------------------------------------- 部分更新

def test_writing_theme_keeps_name_and_grade_and_vice_versa():
    parent, kid = login(auth.PARENT), login(YOUNGER)
    assert post(parent, child=YOUNGER, school_grade="e2", ruby_mode="all").status_code == 200
    assert post(kid, child=YOUNGER, companion_name="ぴよ").status_code == 200
    assert post(kid, child=YOUNGER, theme_id="monochrome").status_code == 200
    s = kid.get(API).json()["settings"]
    assert s == {"school_grade": "e2", "ruby_mode": "all", "companion_name": "ぴよ", "theme_id": "monochrome", "theme_schema_version": 1}
    assert post(kid, child=YOUNGER, companion_name="まるこ").status_code == 200
    s = kid.get(API).json()["settings"]
    assert s["theme_id"] == "monochrome" and s["school_grade"] == "e2" and s["companion_name"] == "まるこ"


def test_null_or_empty_returns_a_field_to_its_default():
    kid = login(YOUNGER)
    post(kid, child=YOUNGER, theme_id="rocket-lab", companion_name="ぴよ")
    assert post(kid, child=YOUNGER, companion_name="  ").json()["settings"] == {"theme_id": "rocket-lab", "theme_schema_version": 1}
    assert "theme_id" not in post(kid, child=YOUNGER, theme_id=None).json()["settings"]


def test_settings_are_separate_per_child():
    parent = login(auth.PARENT)
    post(parent, child=YOUNGER, theme_id="snow-bird")
    post(parent, child=OLDER, theme_id="monochrome", school_grade="j1")
    assert appearance.read(YOUNGER) == {"theme_id": "snow-bird", "theme_schema_version": 1}
    assert appearance.read(OLDER)["school_grade"] == "j1"


# ---------------------------------------------------------------- 残ること（再読込・別の端末・保存先を開き直す）

def test_saved_settings_come_back_on_another_device_and_after_reopening_the_store(fresh):
    post(login(YOUNGER), child=YOUNGER, theme_id="snow-bird", companion_name="ぴよ")
    # 別の端末（新しくログインした Cookie）
    assert login(YOUNGER).get(API).json()["settings"]["theme_id"] == "snow-bird"
    # 保存先を開き直す（サーバーの再起動に当たる）
    ledger._store = ledger._LocalStore(fresh / "ledger.json")
    assert login(auth.PARENT).get(API, params={"child": YOUNGER}).json()["settings"]["companion_name"] == "ぴよ"


# ---------------------------------------------------------------- 値の確かめ

@pytest.mark.parametrize("body", [
    {"theme_id": "dino-2030"}, {"theme_schema_version": 2}, {"companion_name": 123},
    {"companion_name": "あ" * 13}, {"companion_name": "<b>"}, {"companion_name": "まる\u0000"},
    {"favorite_color": "blue"},
])
def test_invalid_values_or_unknown_fields_are_refused(body):
    r = post(login(YOUNGER), child=YOUNGER, **body)
    assert r.status_code == 400, r.text
    assert appearance.read(YOUNGER) == {}


@pytest.mark.parametrize("body", [
    {"school_grade": "e7"}, {"kanji_scope": "all"}, {"ruby_mode": "none"}, {"companion_language_level": "kid"},
    {"known_kanji_overrides": ["学校"]}, {"known_kanji_overrides": "学"}, {"ruby_word_overrides": ["<script>"]},
])
def test_invalid_parent_values_are_refused(body):
    assert post(login(auth.PARENT), child=YOUNGER, **body).status_code == 400
    assert appearance.read(YOUNGER) == {}


def test_broken_stored_values_are_ignored_not_trusted():
    ledger.set_setting("child_settings:" + YOUNGER, {"theme_id": "old-theme", "companion_name": "ぴよ", "school_grade": 3})
    assert login(YOUNGER).get(API).json()["settings"] == {"companion_name": "ぴよ"}


def test_failed_save_is_not_reported_as_saved(monkeypatch):
    kid = login(YOUNGER)                     # ログインも transact_setting を使うので、先に入っておく

    def boom(key, fn):
        raise RuntimeError("firestore unavailable")
    monkeypatch.setattr(ledger, "transact_setting", boom)
    r = post(kid, child=YOUNGER, theme_id="snow-bird")
    assert r.status_code == 500


def test_write_goes_through_the_atomic_update(monkeypatch):
    """同じ子の設定を2つの端末から書いても片方が消えないよう、読み→書きを transact_setting で1回にする。"""
    kid = login(YOUNGER)
    calls = []
    real = ledger.transact_setting
    monkeypatch.setattr(ledger, "transact_setting", lambda key, fn: calls.append(key) or real(key, fn))
    post(kid, child=YOUNGER, theme_id="snow-bird")
    calls = [k for k in calls if k.startswith("child_settings:")]
    assert calls == ["child_settings:" + YOUNGER]


# ---------------------------------------------------------------- 読み補助（H）・相棒（G）・台紙

def test_reading_policy_has_the_shape_reading_js_expects():
    parent = login(auth.PARENT)
    body = parent.get(API, params={"child": YOUNGER}).json()
    assert body["reading_policy"] == {"school_grade": None, "kanji_scope": "previous_grade", "ruby_mode": "auto",
                                      "known_kanji_overrides": [], "ruby_word_overrides": []}
    post(parent, child=YOUNGER, school_grade="e3", kanji_scope="current_grade", known_kanji_overrides=["算", "算"])
    p = parent.get(API, params={"child": YOUNGER}).json()["reading_policy"]
    assert p["school_grade"] == "e3" and p["kanji_scope"] == "current_grade" and p["known_kanji_overrides"] == ["算"]


def test_companion_agent_reads_the_saved_name_and_level():
    assert kid_agent._companion_settings(YOUNGER)["companion_name"] == "まる"          # 未設定は既定
    post(login(auth.PARENT), child=YOUNGER, companion_name="ぴよ", companion_language_level="standard")
    s = kid_agent._companion_settings(YOUNGER)
    assert s == {"companion_name": "ぴよ", "companion_language_level": "standard"}
    # ほかの子の設定は混ざらない
    assert kid_agent._companion_settings(OLDER)["companion_name"] == "まる"


def test_week_failure_is_an_error_not_zero(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("calendar down")
    monkeypatch.setattr(main, "list_raw", boom)
    r = login(YOUNGER).get("/api/week")
    assert r.status_code == 500 and "台紙" in r.json()["detail"]
