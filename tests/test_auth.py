"""#16：人ごとの合言葉と署名付き Cookie。ページも /api/* もログインで守る。

デモの台帳（MIMAMORI_DEMO=1）とローカルの JSON（tmp）で動かす。GCP には繋がない。
子どもの呼び名はダミー（上の子＝中学生、下の子＝小学生。conftest.py）。
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
from mimamori import auth, calendar_tools, ledger

OLDER, YOUNGER = "上の子", "下の子"
WHO = {auth.PARENT: "parent", OLDER: "c0", YOUNGER: "c1"}
CODES = {auth.PARENT: "4821", OLDER: "7394", YOUNGER: "1058"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("MIMAMORI_AUTH", raising=False)
    monkeypatch.delenv("MIMAMORI_LEDGER", raising=False)
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    calendar_tools._demo_store = None
    calendar_tools._demo_day = None
    for user, code in CODES.items():
        auth.set_passcode(user, code)
    yield


def client():
    # Secure の Cookie を持ち帰れるように https で話す
    return TestClient(main.app, base_url="https://testserver")


def login(user, code=None):
    c = client()
    r = c.post("/api/auth/login", json={"who": WHO[user], "passcode": code or CODES[user]})
    assert r.status_code == 200, r.text
    return c


def task_of(child):
    items = calendar_tools.list_tasks(days=14)["items"]
    return next(i["id"] for i in items if i["child"] == child and i["status"] == "todo")


# ---------------------------------------------------------------- 入口

def test_without_login_pages_redirect_and_api_is_401():
    c = client()
    for path in ["/", "/kid", "/reward", "/plan", "/schedule", "/board"]:
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next="), path
    for path in ["/api/tasks", "/api/config", "/api/points?child=下の子", "/api/auth/me"]:
        assert c.get(path).status_code == 401, path
    assert c.post("/api/status", json={"event_id": "d1", "status": "done"}).status_code == 401


def test_login_page_and_health_are_open_and_do_not_show_child_names():
    c = client()
    assert c.get("/login").status_code == 200
    assert c.get("/healthz").status_code == 200
    body = c.get("/api/auth/choices").text
    assert OLDER not in body and YOUNGER not in body
    labels = [x["label"] for x in c.get("/api/auth/choices").json()["choices"]]
    assert labels == ["おうちの人", "中学生", "小学生"]


def test_cookie_is_signed_httponly_secure_lax_and_lasts_180_days():
    r = client().post("/api/auth/login", json={"who": "parent", "passcode": CODES[auth.PARENT]})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(auth.COOKIE + "=")
    for flag in ["HttpOnly", "Secure", "SameSite=lax", f"Max-Age={180 * 24 * 3600}"]:
        assert flag.lower() in cookie.lower(), flag


def test_passcodes_are_stored_only_as_hashes():
    raw = json.dumps(ledger.get_setting(auth.K_USERS), ensure_ascii=False)
    for code in CODES.values():
        assert code not in raw
    assert set(ledger.get_setting(auth.K_USERS)[YOUNGER]) == {"salt", "hash", "set_at"}


def test_wrong_passcode_locks_for_a_while(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    c = client()
    for i in range(auth.MAX_FAILS - 1):
        r = c.post("/api/auth/login", json={"who": "c1", "passcode": "0000"})
        assert r.status_code == 401
    assert c.post("/api/auth/login", json={"who": "c1", "passcode": "0000"}).status_code == 429
    # ロック中は正しい合言葉でも入れない
    assert c.post("/api/auth/login", json={"who": "c1", "passcode": CODES[YOUNGER]}).status_code == 429
    # ほかの人はロックされない
    assert c.post("/api/auth/login", json={"who": "c0", "passcode": CODES[OLDER]}).status_code == 200
    now[0] += auth.LOCK_SECONDS + 1
    assert c.post("/api/auth/login", json={"who": "c1", "passcode": CODES[YOUNGER]}).status_code == 200


def test_success_resets_the_failure_count():
    c = client()
    for _ in range(auth.MAX_FAILS - 1):
        c.post("/api/auth/login", json={"who": "c1", "passcode": "0000"})
    assert c.post("/api/auth/login", json={"who": "c1", "passcode": CODES[YOUNGER]}).status_code == 200
    assert c.post("/api/auth/login", json={"who": "c1", "passcode": "0000"}).status_code == 401


def test_someone_without_a_passcode_cannot_log_in():
    recs = ledger.get_setting(auth.K_USERS)
    recs.pop(YOUNGER)
    ledger.set_setting(auth.K_USERS, recs)
    assert client().post("/api/auth/login", json={"who": "c1", "passcode": "anything"}).status_code == 403


def test_tampered_or_expired_cookie_is_rejected(monkeypatch):
    c = login(YOUNGER)
    token = c.cookies.get(auth.COOKIE)
    body, sig = token.rsplit(".", 1)
    forged = auth._b64(json.dumps({"u": auth.PARENT, "e": 0, "x": 9_999_999_999}).encode())
    c.cookies.clear()
    c.cookies.set(auth.COOKIE, f"{forged}.{sig}")          # 中身を親に書き換え、署名はそのまま
    assert c.get("/api/tasks").status_code == 401
    c.cookies.clear()
    c.cookies.set(auth.COOKIE, token)                       # 元のものは通る（テストが正しく差し替えている確認）
    assert c.get("/api/tasks").status_code == 200

    c = login(YOUNGER)
    later = auth._now() + auth.MAX_AGE + 1
    monkeypatch.setattr(auth, "_now", lambda: later)
    assert c.get("/api/tasks").status_code == 401


# ---------------------------------------------------------------- 子ども

def test_child_cannot_open_the_parent_board():
    r = login(YOUNGER).get("/board", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/kid"


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/notices", None),
    ("post", "/api/notices/seen", {"id": ""}),
    ("get", "/api/notify/config", None),
    ("get", "/api/recurring", None),
    ("post", "/api/recurring", {"templates": []}),
    ("post", "/api/rewards", {"rewards": []}),
    ("post", "/api/year_plan/check", {"text": "4月\n1日 (水) 始業式"}),
    ("post", "/api/year_plan/move", {"event_id": "d1", "date": "2026-10-01"}),
    ("post", "/api/redeem/approve", {"id": "x"}),
    ("post", "/api/redeem/reject", {"id": "x", "note": "x"}),
    ("post", "/api/redeem/hand", {"id": "x"}),
    ("post", "/api/redeem/cap", {"yen": 100}),
    ("post", "/api/auth/logout_all", None),
    ("get", "/api/status?event_id=d1", None),   # 予定の今の状態（/board の再確認。PR #35）
])
def test_child_cannot_use_parent_only_api(method, path, body):
    c = login(YOUNGER)
    r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
    assert r.status_code == 403, (path, r.text)


def test_child_sees_only_themselves():
    c = login(YOUNGER)
    assert [x["name"] for x in c.get("/api/config").json()["children"]] == [YOUNGER]
    data = c.get("/api/tasks").json()
    assert data["items"] and {i["child"] for i in data["items"]} == {YOUNGER}
    assert list(data["points"]) == [YOUNGER]
    assert c.get("/api/schedule").json()["children"] == [YOUNGER]
    assert {i["child"] for i in c.get("/api/schedule").json()["items"]} <= {YOUNGER}
    assert c.get("/api/auth/me").json()["role"] == "child"


@pytest.mark.parametrize("method,path,body", [
    ("get", f"/api/points?child={OLDER}", None),
    ("get", f"/api/week?child={OLDER}", None),
    ("get", f"/api/plan?child={OLDER}", None),
    ("get", f"/api/redeem/pace?child={OLDER}", None),
    ("get", f"/api/redeem?child={OLDER}", None),
    ("get", f"/api/assignments?child={OLDER}", None),
    ("post", "/api/kid/chat", {"child": OLDER, "history": []}),
    ("post", "/api/redeem", {"child": OLDER, "label": "x", "cost": 1}),
    ("post", "/api/quick/repeat", {"child": OLDER}),
    ("post", "/api/register", {"items": [{"title": "x", "child": OLDER, "date": "2026-10-01", "kind": "homework"}]}),
])
def test_child_cannot_act_for_a_sibling(method, path, body):
    c = login(YOUNGER)
    r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
    assert r.status_code == 403, (path, r.text)


def test_child_can_change_only_their_own_tasks():
    c = login(YOUNGER)
    sibling, mine = task_of(OLDER), task_of(YOUNGER)
    assert c.post("/api/status", json={"event_id": sibling, "status": "done"}).status_code == 403
    assert c.post("/api/postpone", json={"event_id": sibling}).status_code == 403
    assert c.post("/api/register/undo", json={"ids": [sibling]}).status_code == 403
    # 保留・取り消しは親だけ
    assert c.post("/api/status", json={"event_id": mine, "status": "rejected"}).status_code == 403
    assert c.post("/api/status", json={"event_id": mine, "status": "done"}).status_code == 200


def test_what_a_child_registers_is_theirs_and_tells_the_parent():
    c = login(YOUNGER)
    r = c.post("/api/register", json={"items": [{"title": "音読", "date": "2026-10-01", "kind": "homework"}],
                                      "source": "parent", "pending": True})
    assert r.status_code == 200
    assert r.json()["notice"] is not None          # 子が入れた扱いで親に知らせる
    added = [i for i in calendar_tools._demo_store if "音読" in i["summary"]]
    assert added and added[0]["child"] == YOUNGER and added[0]["status"] == "todo"


def test_only_the_planner_child_can_change_study_capacity():
    assert login(YOUNGER).post("/api/capacity", json={"minutes": 60}).status_code == 403
    assert login(OLDER).post("/api/capacity", json={"minutes": 60}).status_code == 200


# ---------------------------------------------------------------- 親

def test_parent_can_use_everything():
    c = login(auth.PARENT)
    assert c.get("/board").status_code == 200
    assert c.get("/api/notices").status_code == 200
    assert c.get(f"/api/points?child={OLDER}").status_code == 200
    assert len(c.get("/api/config").json()["children"]) == 2
    assert c.post("/api/status", json={"event_id": task_of(OLDER), "status": "done"}).status_code == 200


def test_parent_can_log_out_every_device():
    parent, kid = login(auth.PARENT), login(YOUNGER)
    assert kid.get("/api/tasks").status_code == 200
    assert parent.post("/api/auth/logout_all").status_code == 200
    assert kid.get("/api/tasks").status_code == 401
    assert login(YOUNGER).get("/api/tasks").status_code == 200     # 入り直せば使える


# ---------------------------------------------------------------- 外せるか

def test_auth_can_be_turned_off_only_locally(monkeypatch):
    monkeypatch.setenv("MIMAMORI_AUTH", "off")
    assert client().get("/api/tasks").status_code == 200
    monkeypatch.setenv("K_SERVICE", "test-service")        # Cloud Run では外せない
    assert client().get("/api/tasks").status_code == 401


# ---------------------------------------------------------------- レビューで見つかった穴（#17）

def test_child_reading_does_not_see_sibling_events():
    """子どもが撮ったときの重複チェックに、兄弟の予定（件名・id・日付）が出ない。"""
    from mimamori import agent
    sibling = next(i for i in calendar_tools.list_tasks(days=14)["items"]
                   if i["child"] == OLDER and "三者面談" in i["summary"])
    item = {"title": sibling["summary"].split("｜")[-1], "date": sibling["date"], "kind": "deadline",
            "child": YOUNGER}
    as_family = agent._review([dict(item)])
    as_child = agent._review([dict(item)], YOUNGER)
    leaked = json.dumps(as_child, ensure_ascii=False)
    assert sibling["id"] not in leaked and OLDER not in leaked
    # 親として見たときは、兄弟の予定とも突き合わせる（比べ方そのものは変えていない確認）
    assert sibling["id"] in json.dumps(as_family, ensure_ascii=False) or as_family["skipped"]


def test_child_reading_tool_lists_only_their_events():
    from mimamori import agent
    rows = agent._scoped_list_events(YOUNGER)("2000-01-01", "2100-01-01")
    titles = [r["summary"] for r in rows]
    assert titles and all(t.startswith(YOUNGER) for t in titles)


def test_extract_passes_the_logged_in_child(monkeypatch):
    seen = {}

    async def fake_read(data, content_type, hint="", child=None):
        seen["child"] = child
        return {"items": []}

    monkeypatch.setattr(main, "read_otayori", fake_read)
    monkeypatch.setattr(main.images_mod, "normalize", lambda data, ct: (data, "image/jpeg"))
    files = {"image": ("a.jpg", b"x", "image/jpeg")}
    assert login(YOUNGER).post("/api/extract", files=files).status_code == 200
    assert seen["child"] == YOUNGER
    assert login(auth.PARENT).post("/api/extract", files=files).status_code == 200
    assert seen["child"] is None


def test_child_can_undo_only_what_they_just_added(monkeypatch):
    c = login(YOUNGER)
    # 親が入れた自分の予定は取り消せない（/api/status の「取り消しは親だけ」の抜け道にしない）
    calendar_tools.list_tasks(days=14)                     # デモの台帳を作らせる
    by_parent = next(i["id"] for i in calendar_tools._demo_store if i["child"] == YOUNGER)
    assert c.post("/api/register/undo", json={"ids": [by_parent]}).status_code == 403
    # 自分で入れた直後なら取り消せる
    r = c.post("/api/register", json={"items": [{"title": "音読", "date": "2026-10-01", "kind": "homework"}]})
    mine = r.json()["results"][0]["id"]
    assert c.post("/api/register/undo", json={"ids": [mine]}).json()["undone"] == 1
    # 10分を過ぎたら取り消せない
    r = c.post("/api/register", json={"items": [{"title": "計算", "date": "2026-10-01", "kind": "homework"}]})
    old = r.json()["results"][0]["id"]
    row = next(i for i in calendar_tools._demo_store if i["id"] == old)
    row["created"] -= main.UNDO_SECONDS + 1
    assert c.post("/api/register/undo", json={"ids": [old]}).status_code == 403


def test_parallel_wrong_logins_compare_at_most_max_fails(monkeypatch):
    """同時に何回投げても、ロックまでに合言葉を比べるのは MAX_FAILS 回だけ。回数も消えない。"""
    from concurrent.futures import ThreadPoolExecutor
    import threading

    compared = []
    lock = threading.Lock()
    real = auth._hash

    def counting(passcode, salt):
        with lock:
            compared.append(passcode)
        return real(passcode, salt)

    monkeypatch.setattr(auth, "_hash", counting)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: auth.check(YOUNGER, "0000")[0], range(24)))
    assert len(compared) <= auth.MAX_FAILS
    assert results.count("wrong") + results.count("locked") == 24
    assert auth.locked_seconds(YOUNGER) > 0
    # ロック中は正しい合言葉でも比べない
    assert auth.check(YOUNGER, CODES[YOUNGER])[0] == "locked"


def test_another_persons_failures_do_not_clear_a_lock(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    for _ in range(auth.MAX_FAILS):
        auth.check(YOUNGER, "0000")
    assert auth.locked_seconds(YOUNGER) > 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: auth.check(OLDER, "0000"), range(8)))
    assert auth.locked_seconds(YOUNGER) > 0


@pytest.mark.parametrize("held", ["pending", "rejected"])
def test_child_cannot_undo_what_the_parent_held_or_removed(held):
    """親が保留・取り消しにしたものを、子どもが戻したり済にしたり動かしたりできない。"""
    parent, kid = login(auth.PARENT), login(YOUNGER)
    mine = task_of(YOUNGER)
    assert parent.post("/api/status", json={"event_id": mine, "status": held}).status_code == 200
    for status in ["todo", "doing", "done"]:
        assert kid.post("/api/status", json={"event_id": mine, "status": status}).status_code == 403
    assert kid.post("/api/postpone", json={"event_id": mine}).status_code == 403
    row = next(i for i in calendar_tools._demo_store if i["id"] == mine)
    assert row["status"] == held


def test_child_redeem_must_match_the_parents_list_exactly(monkeypatch):
    """子どもの申し込みは、親の交換リストに名前・ポイント・金額がそろって一致するものだけ。"""
    from mimamori import points as points_mod
    seen = []

    def fake_request(child, label, cost, yen=0):
        seen.append((child, label, cost, yen))
        return {"id": "r1", "child": child}

    monkeypatch.setattr(main.redeem_mod, "request", fake_request)
    # 同じ名前で値段の違うものを2つ（Codex のレビューの再現）
    points_mod.set_rewards([{"label": "図書カード", "points": 100, "yen": 500},
                            {"label": "図書カード", "points": 200, "yen": 1000}])
    c = login(YOUNGER)
    ok = c.post("/api/redeem", json={"child": YOUNGER, "label": "図書カード", "cost": 200, "yen": 1000})
    assert ok.status_code == 200 and seen[-1] == (YOUNGER, "図書カード", 200, 1000)
    for body in [{"label": "図書カード", "cost": 1, "yen": 1000},        # 値段を書き換え
                 {"label": "図書カード", "cost": 200, "yen": 0},         # 金額を消して月の上限をすり抜け
                 {"label": "なんでも", "cost": 1, "yen": 0}]:           # リストにないもの
        assert c.post("/api/redeem", json=dict(body, child=YOUNGER)).status_code == 400, body
    assert len(seen) == 1


XSS = "<img src=x onerror=\"fetch('/api/auth/logout_all',{method:'POST'})\">"


@pytest.mark.parametrize("who", [YOUNGER, auth.PARENT])
@pytest.mark.parametrize("field,value", [
    ("kind", XSS),
    ("date", XSS),
    ("time_start", XSS),
])
def test_register_rejects_html_in_fields_shown_on_screens(who, field, value):
    """画面に出る種類・日付・時刻に、決まった形以外を入れさせない（親から来たものも同じ）。"""
    item = {"title": "確認", "date": "2026-09-28", "kind": "homework", field: value}
    r = login(who).post("/api/register", json={"items": [item]})
    assert r.status_code == 400, r.text
    assert not any("確認" in i["summary"] for i in calendar_tools._demo_store or [])


def test_schedule_page_escapes_the_kind():
    """予定表は種類をエスケープして出す（#17 のレビューで見つかった保存型 XSS）。"""
    from pathlib import Path
    html = Path(main.__file__).with_name("static").joinpath("schedule.html").read_text(encoding="utf-8")
    assert '(KIND[it.kind]||it.kind||"")' not in html.replace('esc(KIND[it.kind]||it.kind||"")', "")


# ---------------------------------------------------------------- 子どもの端末で親に切り替える（#16 ①）

def switch_to_parent(c):
    r = c.post("/api/auth/login", json={"who": "parent", "passcode": CODES[auth.PARENT]})
    assert r.status_code == 200, r.text
    return r


def test_parent_login_on_a_child_device_is_a_temporary_switch():
    c = login(YOUNGER)
    assert switch_to_parent(c).json()["back_to"] == YOUNGER
    me = c.get("/api/auth/me").json()
    assert me["role"] == "parent" and me["switched"] and me["back_to"] == YOUNGER
    assert 0 < me["idle_seconds"] <= auth.IDLE_SECONDS
    assert c.get("/board", follow_redirects=False).status_code == 200


def test_parent_on_their_own_device_is_not_temporary():
    c = login(auth.PARENT)
    me = c.get("/api/auth/me").json()
    assert me["role"] == "parent" and not me["switched"]


def test_switch_goes_back_to_the_child_after_10_idle_minutes(monkeypatch):
    now = [2_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    c = login(YOUNGER)
    switch_to_parent(c)
    now[0] += auth.IDLE_SECONDS + 1
    r = c.get("/board", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/kid"
    me = c.get("/api/auth/me").json()                      # Cookie が子どもに書き換わっている
    assert me["role"] == "child" and me["name"] == YOUNGER and not me["switched"]


def test_activity_restarts_the_10_minutes_but_reads_do_not(monkeypatch):
    now = [3_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    c = login(YOUNGER)
    switch_to_parent(c)
    now[0] += auth.IDLE_SECONDS - 60
    assert c.post("/api/auth/touch").json()["switched"]      # 画面で操作があった
    now[0] += auth.IDLE_SECONDS - 60
    assert c.get("/api/auth/me").json()["role"] == "parent"  # 操作から10分たっていない
    now[0] += 120                                            # 読み込みだけでは延びない
    r = c.get("/api/tasks")                                  # 親のつもりの操作は子として実行しない
    assert r.status_code == 401 and r.headers["x-mimamori-reverted"] == "1"
    assert c.get("/api/auth/me").json()["role"] == "child"


def test_back_to_child_button():
    c = login(YOUNGER)
    switch_to_parent(c)
    assert c.post("/api/auth/back").json()["user"] == YOUNGER
    me = c.get("/api/auth/me").json()
    assert me["role"] == "child" and not me["switched"]
    assert login(auth.PARENT).post("/api/auth/back").status_code == 400   # 切り替えていなければ使えない


def test_logout_and_logout_all_are_not_undone_while_switched():
    c = login(YOUNGER)
    switch_to_parent(c)
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/tasks").status_code == 401
    c = login(YOUNGER)
    switch_to_parent(c)
    assert c.post("/api/auth/logout_all").status_code == 200
    assert c.get("/api/tasks").status_code == 401


def test_a_child_cannot_forge_a_switch():
    """元の子（b）や期限（i）は署名の中。書き換えれば通らない。"""
    c = login(YOUNGER)
    token = c.cookies.get(auth.COOKIE)
    body, sig = token.rsplit(".", 1)
    data = json.loads(auth._unb64(body))
    forged = auth._b64(json.dumps(dict(data, u=auth.PARENT, b=YOUNGER, i=9_999_999_999)).encode())
    c.cookies.clear()
    c.cookies.set(auth.COOKIE, f"{forged}.{sig}")
    assert c.get("/api/tasks").status_code == 401


def test_logout_all_during_a_request_is_not_undone_by_the_refresh(monkeypatch):
    """切り替え中の延長で、処理の途中の全端末ログアウトを取り消さない（Codex のレビュー #17）。"""
    c = login(YOUNGER)
    switch_to_parent(c)
    real = main.study_mod.set_capacity

    def logout_all_meanwhile(**kw):
        auth.logout_all()                                   # 処理の途中で、別の端末から全端末ログアウト
        return real(**kw)

    monkeypatch.setattr(main.study_mod, "set_capacity", logout_all_meanwhile)
    c.post("/api/capacity", json={"minutes": 60})          # 書き込み＝操作なので、応答で延長の Cookie が出る
    assert c.get("/api/tasks").status_code == 401            # 延長された Cookie も無効のまま


def test_wrong_and_locked_responses_speak_to_the_person_and_carry_retry_after(monkeypatch):
    """UX_REVIEW R6：子ども向けの言葉。ロックの待ち時間は Retry-After で渡す。"""
    now = [5_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    c = client()
    r = c.post("/api/auth/login", json={"who": "c1", "passcode": "0000"})
    j = r.json()
    assert r.status_code == 401 and "あいことばが あわなかったよ" in j["detail"]
    assert j["remaining"] == auth.MAX_FAILS - 1 and "まちがえると" in j["note"]
    for _ in range(auth.MAX_FAILS - 1):
        r = c.post("/api/auth/login", json={"who": "c1", "passcode": "0000"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) == auth.LOCK_SECONDS
    assert "いまは はいれません" in r.json()["detail"]
    now[0] += 60
    r = c.post("/api/auth/login", json={"who": "c1", "passcode": CODES[YOUNGER]})
    assert r.status_code == 429 and int(r.headers["retry-after"]) == auth.LOCK_SECONDS - 60
    p = c.post("/api/auth/login", json={"who": "parent", "passcode": "0000"}).json()
    assert "合言葉が一致しませんでした" in p["detail"] and "おうちの人" not in p["detail"]   # 親には親の言葉
    t = c.post("/api/auth/login", json={"who": "c0", "passcode": "0000"}).json()
    assert "合言葉が一致しませんでした" in t["detail"] and "おうちの人に聞いて" in t["detail"]  # 中学生は漢字で


def _late_parent_cookie(c):
    """切り替え中に始まった遅い処理の応答が、あとから Set-Cookie で親の Cookie を送り直す場面を作る。"""
    c.post("/api/auth/touch")                                   # 延長の Cookie（＝遅い応答が返すもの）
    return c.cookies.get(auth.COOKIE)


def test_a_late_parent_cookie_after_back_to_child_stays_a_child():
    """Codex のレビュー（#17）：子どもに戻したあとに遅い応答が届いても、親には戻らない。"""
    c = login(YOUNGER)
    switch_to_parent(c)
    late = _late_parent_cookie(c)
    assert c.post("/api/auth/back").status_code == 200
    c.cookies.clear()
    c.cookies.set(auth.COOKIE, late)                            # 遅い応答が子どもの Cookie を上書きした
    r = c.get("/board", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/kid"
    assert c.get("/api/auth/me").json()["role"] == "child"
    assert c.get("/api/notices").status_code == 403


def test_a_late_parent_cookie_after_logout_is_rejected():
    c = login(YOUNGER)
    switch_to_parent(c)
    late = _late_parent_cookie(c)
    assert c.post("/api/auth/logout").status_code == 200
    c.cookies.clear()
    c.cookies.set(auth.COOKIE, late)
    assert c.get("/api/tasks").status_code == 401


def test_a_late_parent_cookie_after_the_idle_revert_stays_a_child(monkeypatch):
    now = [7_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    c = login(YOUNGER)
    switch_to_parent(c)
    late = _late_parent_cookie(c)
    now[0] += auth.IDLE_SECONDS + 1
    c.get("/api/tasks")                                         # 10分たって子どもに戻る
    now[0] -= auth.IDLE_SECONDS                                 # 期限内に作られた延長の Cookie が遅れて届いた
    c.cookies.clear()
    c.cookies.set(auth.COOKIE, late)
    r = c.get("/api/notices")                                   # 親のつもりの操作は、子どもとしても親としても実行しない
    assert r.status_code == 401 and r.headers["x-mimamori-reverted"] == "1"
    assert c.get("/api/auth/me").json()["role"] == "child"
