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
