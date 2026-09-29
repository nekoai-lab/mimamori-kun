"""みまもりくん — FastAPI エントリポイント。Cloud Run で動かす。"""
from __future__ import annotations

import datetime as dt
import os
import re
from contextlib import asynccontextmanager

from typing import Any, Dict, List, Optional

from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mimamori.agent import read_otayori, read_year_plan
from mimamori import appearance as appearance_mod
from mimamori import ambiguous_dates
from mimamori import auth
from mimamori import images as images_mod
from mimamori import ledger
from mimamori.kid_agent import talk
from mimamori.calendar_tools import (
    create_events,
    validate_updates,
    undo_update,
    event_meta,
    list_events,
    list_raw,
    list_tasks,
    move_event,
    service_account_email,
    set_status,
)
from mimamori.config import config
from mimamori import notify as notify_mod
from mimamori import points as points_mod
from mimamori import redeem as redeem_mod
from mimamori import recurring as recurring_mod
from mimamori import study as study_mod
from mimamori import year_plan as year_plan_mod

def _key(title: str) -> str:
    """件名の比べ方。空白と ✓ の違いで別物にしない。"""
    return re.sub(r"\s", "", (title or "").replace("✓", ""))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 保存先の設定と、Firestore を選んだ場合の接続を起動時に確かめる。
    ledger.store()
    yield


app = FastAPI(title="みまもりくん", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

MAX_BYTES = 12 * 1024 * 1024


# ---------------------------------------------------------------- ログイン（#16）
#
# **入口で守る。** Cloud Run は --allow-unauthenticated のまま、ここで全部のページと /api/* を止める。
# ログインなしで通すのは、ログインの画面と API・画面の部品（/static）・死活確認だけ。
# 子どもは自分のぶんだけ。親だけの機能は 403。

_OPEN = {"/login", "/api/auth/choices", "/api/auth/login", "/healthz"}
_PARENT_PAGES = {"/board"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if not auth.enabled():
        request.state.user = auth.PARENT        # ローカルで外したときは、今までどおり全部使える
        return await call_next(request)
    if path in _OPEN or path.startswith("/static/"):
        request.state.user = None
        return await call_next(request)
    session = auth.read(request.cookies.get(auth.COOKIE))
    if not session:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "ログインしてください。"}, status_code=401)
        return RedirectResponse("/login?next=" + quote(path), status_code=303)
    user = session["user"]
    request.state.user = user
    request.state.back_to = session["back_to"]
    request.state.idle_until = session["idle_until"]
    request.state.epoch = session["epoch"]
    request.state.sid = session["sid"]
    if session["reverted"]:
        # 子どもの端末で親に切り替えたまま10分操作がなかった。元の子に戻す（#16 ①）
        if path.startswith("/api/"):
            # 親のつもりの操作を子として実行しない。401 と印を返し、画面は読み込み直す（who.js）
            res = JSONResponse({"detail": "しばらく操作がなかったので、子どもの画面に戻しました。"},
                               status_code=401, headers={"X-Mimamori-Reverted": "1"})
        else:
            res = RedirectResponse("/kid" if path in _PARENT_PAGES else path, status_code=303)
        auth.end_switch(session["sid"], "back")       # 10分で戻った。遅れて届く親の Cookie も子どもとして扱う
        _set_session(res, user, generation=session["epoch"])
        return res
    if path in _PARENT_PAGES and not auth.is_parent(user):
        return RedirectResponse("/kid", status_code=303)
    response = await call_next(request)
    if session["back_to"] and _is_activity(request):
        # 操作があったので、戻るまでの10分を数え直す（読み込みだけのアクセスでは延ばさない）
        _set_session(response, user, back_to=session["back_to"], generation=session["epoch"], sid=session["sid"])
        request.state.idle_until = int(auth._now()) + auth.IDLE_SECONDS
    return response


def _is_activity(request: Request) -> bool:
    """「操作」に数えるもの：ページを開く、書き込み、画面からの操作の知らせ（/api/auth/touch）。"""
    path = request.url.path
    if not path.startswith("/api/"):
        return True
    if path.startswith("/api/auth/"):
        # ログアウト・全端末ログアウト・子どもに戻すは自分で Cookie を書く。上書きしない
        return path == "/api/auth/touch"
    return request.method != "GET"


def _set_session(res, user: str, back_to: Optional[str] = None, generation: Optional[int] = None,
                 sid: Optional[str] = None) -> None:
    res.set_cookie(auth.COOKIE, auth.issue(user, back_to=back_to, generation=generation, sid=sid),
                   max_age=auth.MAX_AGE,
                   httponly=True, secure=True, samesite="lax", path="/")


def _user(request: Request) -> Optional[str]:
    return getattr(request.state, "user", None)


def parent_only(request: Request) -> None:
    if not auth.is_parent(_user(request)):
        raise HTTPException(403, "おうちの人だけが使えます。")


def _self(request: Request, child: str = "") -> str:
    """子どもなら自分の名前を返す（別の子を指定したら 403）。親は指定どおり。"""
    user = _user(request)
    if auth.is_parent(user):
        return child
    if child and child != user:
        raise HTTPException(403, "自分のぶんだけ使えます。")
    return user or ""


CHILD_EDITABLE = ("todo", "doing", "done")


def _own_event(request: Request, event_id: str) -> None:
    """子どもが変えられるのは、自分のやることで、**今の状態が todo / doing / done のもの**だけ。

    親が保留（pending）や取り消し（rejected）にしたものを、子どもが戻せないようにする（#16）。
    持ち主も今の状態も、画面から来た値ではなく予定に残っている記録で確かめる。
    """
    user = _user(request)
    if auth.is_parent(user):
        return
    meta = event_meta(event_id)
    if not meta or meta["child"] != user:
        raise HTTPException(403, "自分のやることだけ変えられます。")
    if meta["status"] not in CHILD_EDITABLE:
        raise HTTPException(403, "おうちの人が保留・取り消しにしたものは、変えられません。")


UNDO_SECONDS = 10 * 60      # 子どもが自分で入れたものを取り消せるのは、入れてから10分（D-3）


def _child_can_undo(request: Request, event_id: str) -> None:
    """子どもが取り消せるのは、**自分が入れて、10分以内のもの**だけ（#16）。

    それ以外（親が入れた自分の予定・古いもの）を消せると、/api/status の「取り消しは親だけ」の抜け道になる。
    だれが・いつ入れたかは、画面から来た値ではなく予定に残っている記録で確かめる。
    """
    user = _user(request)
    if auth.is_parent(user):
        return
    meta = event_meta(event_id)
    fresh = bool(meta) and (dt.datetime.now(dt.timezone.utc).timestamp() - meta["created"]) <= UNDO_SECONDS
    if not meta or meta["child"] != user or meta["source"] != "kid" or not fresh:
        raise HTTPException(403, "取り消せるのは、自分で入れてから10分のあいだだけです。")


def _own_assignment(request: Request, assignment_id: str) -> None:
    user = _user(request)
    if auth.is_parent(user):
        return
    row = next((a for a in study_mod.assignments(None, True) if a.get("id") == assignment_id), None)
    if not row or row.get("child") != user:
        raise HTTPException(403, "自分の課題だけ変えられます。")


def _can_set_capacity(request: Request) -> None:
    """学習の枠を変えられるのは、親と、計画を持つ上の子（中学生）だけ。"""
    user = _user(request)
    if auth.is_parent(user):
        return
    level = next((c.get("school_level") for c in config.children if c["name"] == user), "")
    if level != "junior_high":
        raise HTTPException(403, "おうちの人か、計画を立てる人だけが変えられます。")


@app.get("/login")
def login_page():
    return FileResponse("static/login.html")


@app.get("/api/auth/choices")
def api_auth_choices():
    """ログイン画面の選択肢。子どもの呼び名は出さない（学齢で見せる）。"""
    return {"choices": auth.login_choices()}


class LoginRequest(BaseModel):
    who: str
    passcode: str


@app.post("/api/auth/login")
def api_auth_login(req: LoginRequest, request: Request):
    user = auth.user_from_choice(req.who)
    if not user:
        raise HTTPException(400, "だれかを選んでください。")
    result, n = auth.check(user, req.passcode)
    # 言葉の出し分け：小学生はひらがな中心、中学生と親は漢字（UX_REVIEW R6 の文言の表）
    kid = not auth.is_parent(user) and next(
        (c.get("school_level") for c in config.children if c["name"] == user), "") == "elementary"
    teen = not auth.is_parent(user) and not kid
    minutes = auth.LOCK_SECONDS // 60
    if result == "locked":
        # 待つ秒数は Retry-After で渡す（画面は日本語の文から数字を抜き出さない。UX_REVIEW R6）
        return JSONResponse({
            "detail": ("いまは はいれません。しばらく まってから「もういちど たしかめる」を おしてね。" if kid else
                       "入力が続けて一致しなかったため、一時的にログインできません。時間をおいて「もう一度確認する」を押してください。"),
            "note": (f"まちがいが つづくと、{minutes}分 おやすみに なります。" if kid else f"ロック時間は{minutes}分です。"),
            "retry_after": n,
        }, status_code=429, headers={"Retry-After": str(n)})
    if result == "unset":
        raise HTTPException(403, "まだ あいことばが きまっていません。おうちの人に きいてね。" if kid else
                            "まだ合言葉が決まっていません。おうちの人に聞いてください。" if teen else
                            "まだ合言葉が決まっていません。tools/set_passcode.py で決めてください。")
    if result != "ok":
        return JSONResponse({
            "detail": ("あいことばが あわなかったよ。えらんだ人と、あいことばを たしかめてね。わからないときは、おうちの人に きいてね。"
                       if kid else "合言葉が一致しませんでした。選んだ人と合言葉を確かめてください。"
                       + ("わからないときは、おうちの人に聞いてください。" if teen else "")),
            "note": (f"あと {n}回 まちがえると、しばらく はいれなく なるよ。" if kid else
                     f"あと{n}回続けて一致しないと、{minutes}分ログインできなくなります。"),
            "remaining": n,
        }, status_code=401)
    # 子どもでログインしている端末で親が入ったら、「親に切り替え」の一時の状態にする（#16 ①）。
    # 操作がなければ10分で元の子に戻る。親の端末（子どもでログインしていない）なら今までどおり180日
    current = auth.read(request.cookies.get(auth.COOKIE))
    back_to, sid = None, None
    if auth.is_parent(user) and current:
        if current["back_to"]:
            back_to, sid = current["back_to"], current["sid"]     # 切り替え中にもう一度入った
        elif not auth.is_parent(current["user"]):
            back_to, sid = current["user"], auth.start_switch()
    elif current and current["back_to"]:
        auth.end_switch(current["sid"], "back")          # 切り替え中の端末で子どもが入り直した
    res = JSONResponse({"user": auth.display_name(user), "role": "parent" if auth.is_parent(user) else "child",
                        "home": "/board" if auth.is_parent(user) else "/kid",
                        "back_to": back_to})
    _set_session(res, user, back_to=back_to, sid=sid)
    return res


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    user = _user(request)
    back_to = getattr(request.state, "back_to", None)
    idle_until = getattr(request.state, "idle_until", 0)
    return {"user": auth.display_name(user) if user else "", "name": user or "",
            "role": "parent" if auth.is_parent(user) else "child", "auth": auth.enabled(),
            "switched": bool(back_to), "back_to": back_to or "",
            "idle_seconds": max(0, int(idle_until - auth._now())) if back_to else 0}


@app.post("/api/auth/touch")
def api_auth_touch(request: Request):
    """画面で操作があったことの知らせ。親に切り替え中なら、戻るまでの10分を数え直す（middleware がやる）。"""
    return {"ok": True, "switched": bool(getattr(request.state, "back_to", None))}


@app.post("/api/auth/back")
def api_auth_back(request: Request):
    """「子どもに戻す」。子どもの端末で親に切り替えているときだけ使える。"""
    back_to = getattr(request.state, "back_to", None)
    if not back_to:
        raise HTTPException(400, "子どもの端末で親に切り替えているときだけ使えます。")
    auth.end_switch(getattr(request.state, "sid", None), "back")
    res = JSONResponse({"user": back_to, "home": "/kid"})
    _set_session(res, back_to, generation=getattr(request.state, "epoch", None))
    return res


@app.post("/api/auth/logout")
def api_auth_logout(request: Request):
    # 切り替え中なら、その切り替えを「ログアウトした」にする（遅れて届く親の Cookie を使えなくする）
    auth.end_switch(getattr(request.state, "sid", None), "logout")
    res = JSONResponse({"ok": True})
    res.delete_cookie(auth.COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return res


@app.post("/api/auth/logout_all", dependencies=[Depends(parent_only)])
def api_auth_logout_all(request: Request):
    """すべての端末をログアウトさせる（この端末も含む）。"""
    auth.logout_all()
    return api_auth_logout(request)


@app.get("/")
def index():
    """親の画面。撮る／承認する。"""
    return FileResponse("static/index.html")


@app.get("/kid")
def kid():
    """子どもの画面。撮る／話す／終わらせる。"""
    return FileResponse("static/kid.html")


@app.get("/reward")
def reward():
    """ポイントと交換の画面。※共同開発者が作成中。"""
    path = "static/reward.html"
    if not os.path.exists(path):
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:2rem'>この画面はまだありません。"
            "<code>static/reward.html</code> を作ると表示されます。</p>",
            status_code=200,
        )
    return FileResponse(path)


@app.get("/schedule")
def schedule():
    """予定表。月ごとに、入っているものを見る場所。"""
    return FileResponse("static/schedule.html")


@app.get("/plan")
def plan_page():
    """学習スケジュール。配分の結果を見て、枠と優先度を決める場所。"""
    return FileResponse("static/plan.html")


@app.get("/board")
def board():
    """親のダッシュボード。タスク一覧と予定を見る場所。"""
    return FileResponse("static/board.html")


@app.get("/api/config")
def get_config(request: Request):
    user = _user(request)
    if not auth.is_parent(user):
        # 子どもには自分だけを見せる。兄弟に切り替えられないようにするのは、ここ（「だれ？」が1人になる）
        return {"children": [c for c in config.children if c["name"] == user], "model": config.model}
    return {
        "children": config.children,
        "calendar_id": config.calendar_id,
        "model": config.model,
        "service_account": service_account_email(),
    }


@app.post("/api/extract")
async def extract(request: Request, image: UploadFile = File(...), hint: str = Form("")):
    data = await image.read()
    if not data:
        raise HTTPException(400, "画像が空です。")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "画像が大きすぎます。12MB 以下にしてください。")
    # iPhone の写真は HEIC で来る。ここで JPEG に直す。直せないものは理由を返す。
    try:
        data, content_type = images_mod.normalize(data, image.content_type or "")
    except ValueError as e:
        raise HTTPException(415, str(e)) from e
    try:
        user = _user(request)
        result = await read_otayori(data, content_type, hint,
                                    child=None if auth.is_parent(user) else user)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"読み取りに失敗しました: {e}") from e
    waiting = result.pop("date_questions", [])
    # API 境界でも検査する。子どもの帰属はセッションから決める。
    candidates = []
    for item in result["items"]:
        checked = ambiguous_dates.check(item)
        (waiting if checked["date_issues"] else candidates).append(checked)
    if not auth.is_parent(user):
        waiting = [dict(i, child=user) for i in waiting]
    result["items"] = candidates
    count = ambiguous_dates.enqueue(waiting)
    if count:
        result["date_questions_count"] = count
    return JSONResponse(result)


class RegisterRequest(BaseModel):
    items: List[Dict[str, Any]]
    pending: bool = False          # 親が自分の判断で保留にしたいときだけ使う
    source: str = "parent"         # "kid" なら、子が入れたものとして親に知らせる


KINDS = ("event", "deadline", "homework", "bring")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"\d{2}:\d{2}")


def _check_item(item: Dict[str, Any]) -> None:
    """登録する1件の形を確かめる（#16）。**親から来たものも同じ**。

    おたよりの読み取り結果は画像の中身に左右されるし、子どもも入れられる。
    画面に出る値（種類・日付・時刻）に、決まった形以外のものを入れさせない。
    """
    if item.get("kind") not in KINDS:
        raise HTTPException(400, "種類は event / deadline / homework / bring のどれかです。")
    for key in ("date", "end_date"):
        v = item.get(key)
        if v is not None and not (isinstance(v, str) and _DATE.fullmatch(v)):
            if key == "date" or v != "":
                raise HTTPException(400, "日付は YYYY-MM-DD の形で入れてください。")
    for key in ("time_start", "time_end"):
        v = item.get(key)
        if v not in (None, "") and not (isinstance(v, str) and _TIME.fullmatch(v)):
            raise HTTPException(400, "時刻は HH:MM の形で入れてください。")
    if not isinstance(item.get("title"), str) or not item["title"].strip():
        raise HTTPException(400, "件名がありません。")


@app.post("/api/register")
def register(req: RegisterRequest, request: Request):
    """カレンダーに入れる。

    **子が入れたものも、承認を待たずにそのまま入れる（D-62）。**
    承認を挟むと、親が忘れた日は子のやることが空のまま終わる。
    子から見れば「出したのに何も起きない」で、次の日から撮らなくなる。
    代わりに、入ったことを親に知らせ、違ったら消せるようにする。
    """
    if not req.items:
        raise HTTPException(400, "登録するものがありません。")
    for i in req.items:
        _check_item(i)
        try:
            issues = ambiguous_dates.check(i)["date_issues"]
        except (TypeError, ValueError):
            raise HTTPException(400, "日付の確認情報が不正です。")
        if issues:
            raise HTTPException(400, "日付の確認が必要です。『確認すること』から日付を選んでください。")
    user = _user(request)
    if not auth.is_parent(user):
        # 子どもは自分のぶんだけ入れられる。「子が入れた」として親に知らせる。保留にはできない
        for i in req.items:
            if i.get("child") not in (None, "", "不明", user):
                raise HTTPException(400 if i.get("branch") in ("moved", "diff") else 403,
                                    "自分のぶんだけ入れられます。")
        req.items = [dict(i, child=user) for i in req.items]
        req.source, req.pending = "kid", False
    kid = req.source == "kid"
    items = [dict(i, source=("kid" if kid else "parent")) for i in req.items]
    try:
        validate_updates(items)
        results = create_events(items, "pending" if req.pending else "todo", actor=user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"カレンダー登録に失敗しました: {e}") from e

    notice = None
    if kid:
        ok = [r for r in results if r.get("status") == "ok"]
        if ok:
            who = (items[0].get("child") or "子ども")
            try:
                notice = notify_mod.add(
                    "kid_added",
                    f"{who}が {len(ok)}件 入れました",
                    "撮ったものから入りました。違っていたら消せます。",
                    [{"id": r.get("id", ""), "title": r.get("title", ""),
                      "date": next((i.get("date", "") for i in items if i.get("title") == r.get("title")), "")}
                     for r in ok],
                )
            except Exception:  # noqa: BLE001
                notice = None          # 知らせが出せなくても、登録は止めない
    return {"results": results, "notice": notice}



class DateAnswer(BaseModel):
    date: dt.date
    end_date: Optional[dt.date] = None
    child: Optional[str] = None


@app.get("/api/date_questions", dependencies=[Depends(parent_only)])
def api_date_questions():
    ambiguous_dates.remind()
    return {"items": ambiguous_dates.pending()}


def _date_action(id_, action, date=None, end_date=None, child=None):
    try:
        return ambiguous_dates.change(id_, action, date, end_date, child)
    except KeyError as exc:
        raise HTTPException(404, "日付の確認待ちが見つかりません。") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/date_questions/{id_}/later", dependencies=[Depends(parent_only)])
def api_date_later(id_: str):
    _date_action(id_, "later")
    return {"state": "waiting"}


@app.post("/api/date_questions/{id_}/dismiss", dependencies=[Depends(parent_only)])
def api_date_dismiss(id_: str):
    _date_action(id_, "dismiss")
    return {"state": "dismissed"}


@app.post("/api/date_questions/{id_}/register", dependencies=[Depends(parent_only)])
def api_date_register(id_: str, req: DateAnswer, request: Request):
    if req.end_date and req.end_date < req.date:
        raise HTTPException(400, "いつまでは、いつから以降の日付を選んでください。")
    row = _date_action(id_, "register", req.date.isoformat(),
                       req.end_date.isoformat() if req.end_date else None, req.child)
    if row["state"] == "registered":
        return row["result"]
    # #52 の照合・更新情報は持ち越さない。親が決めた日付で新規登録する。
    item = {k: row[k] for k in ("kind", "title", "child", "school_level", "bring", "note",
                                "time_start", "time_end") if k in row}
    item.update(date=row["chosen_date"], end_date=row["chosen_end_date"], source="parent", branch="new")
    item["note"] = (item.get("note", "") + "\nプリントの表記：" + row["date_text"]).strip()
    try:
        _check_item(item)
        results = create_events([item], "todo", actor=_user(request))
        if len(results) != 1 or results[0].get("status") != "ok":
            raise ValueError("登録結果を確認できませんでした。")
        result = {"results": results, "state": "registered"}
        ambiguous_dates.finish(id_, result)
        return result
    except Exception as exc:
        # Calendar は台帳と一括 commit できない。通信切断時は再送せず、確認対象として残す。
        raise HTTPException(502, "登録結果を確認できません。カレンダーを確認してください。二重登録を避けるため再送を止めています。") from exc


@app.post("/api/notify/test", dependencies=[Depends(parent_only)])
def api_notify_test():
    """送り先が本当に届くかを、1本だけ投げて確かめる。"""
    cfg = notify_mod.configured()
    if not cfg["enabled"]:
        raise HTTPException(400, "送り先が設定されていません。MIMAMORI_NOTIFY_WEBHOOK を入れてください。")
    row = notify_mod.add("test", "みまもりくん、つながりました",
                         "ここに、子どもが入れたものの知らせが届きます。")
    return {"sent": True, "style": cfg["style"], "notice": row}


@app.get("/api/notify/config", dependencies=[Depends(parent_only)])
def api_notify_config():
    return notify_mod.configured()


@app.get("/api/notices", dependencies=[Depends(parent_only)])
def api_notices(unseen: bool = False):
    ambiguous_dates.remind()
    return {"items": notify_mod.notices(unseen_only=unseen)}


class NoticeSeen(BaseModel):
    id: str = ""


@app.post("/api/notices/seen", dependencies=[Depends(parent_only)])
def api_notices_seen(req: NoticeSeen):
    if req.id and not any(n["id"] == req.id for n in notify_mod.notices()):
        raise HTTPException(404, "その知らせが見つかりませんでした。")
    seen = notify_mod.mark_seen(req.id)
    return {"seen": 1 if req.id else seen}


class UndoRequest(BaseModel):
    ids: List[str]


@app.post("/api/register/undo")
def api_register_undo(req: UndoRequest, request: Request):
    """まとめて入れたものを、まとめて取り消す（10分以内・D-3）。

    **消さずに隠す。** 予定は rejected にするだけなので、何を取り消したかは残る。
    18件を1件ずつ消させると、間違えて入れた日が地獄になる。
    """
    if not req.ids:
        raise HTTPException(400, "取り消すものがありません。")
    if len(req.ids) > 60:
        raise HTTPException(400, "一度に取り消せるのは60件までです。")
    for eid in req.ids:
        if not eid.startswith("update:"):
            _child_can_undo(request, eid)
    done, failed = 0, []
    for eid in req.ids:
        try:
            if eid.startswith("update:"):
                undo_update(eid, _user(request), auth.is_parent(_user(request)))
                done += 1
                continue
            r = set_status(eid, "rejected")
            if r.get("status") == "error":
                failed.append(eid)
            else:
                done += 1
        except Exception:  # noqa: BLE001
            failed.append(eid)
    return {"undone": done, "failed": failed}


@app.get("/api/tasks")
def tasks(request: Request, days: int = 14):
    # 毎日きまっているもの（公文など）は、ここで足りない分だけ用意する。
    # 別のスケジューラを立てない。朝いちばんに誰かが開いた時点で並ぶ。
    try:
        recurring_mod.ensure()
    except Exception:  # noqa: BLE001
        pass            # 定期タスクが作れなくても、一覧は出す
    try:
        data = list_tasks(days)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"タスクの取得に失敗しました: {e}") from e
    user = _user(request)
    if auth.is_parent(user):
        ambiguous_dates.remind()
        data["date_questions"] = ambiguous_dates.pending()
    if not auth.is_parent(user):
        # 子どもには自分のぶんだけ（兄弟のやること・ポイントは見せない）
        data["items"] = [i for i in data["items"] if i.get("child") == user]
        data["children"] = [user]
        data["points"] = {user: data["points"].get(user, 0)}
    return data


class StatusRequest(BaseModel):
    event_id: str
    status: str  # todo / doing / done


@app.get("/api/status", dependencies=[Depends(parent_only)])
def api_status(event_id: str):
    meta = event_meta(event_id)
    if meta is None:
        raise HTTPException(404, "その予定が見つかりませんでした。")
    return {"id": event_id, "status": meta["status"]}


@app.post("/api/status")
def status(req: StatusRequest, request: Request):
    if req.status not in ("pending", "todo", "doing", "done", "rejected"):
        raise HTTPException(400, "status は pending / todo / doing / done / rejected のいずれかです。")
    if not auth.is_parent(_user(request)):
        if req.status not in CHILD_EDITABLE:
            raise HTTPException(403, "保留・取り消しは、おうちの人だけができます。")
        _own_event(request, req.event_id)
    try:
        return set_status(req.event_id, req.status)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"状態の更新に失敗しました: {e}") from e


class KidChatRequest(BaseModel):
    child: str
    history: List[Dict[str, str]]


@app.post("/api/kid/chat")
async def kid_chat(req: KidChatRequest, request: Request):
    req.child = _self(request, req.child)
    if not req.child:
        raise HTTPException(400, "誰の画面かが分かりません。")
    if len(req.history) > 40:
        req.history = req.history[-40:]
    try:
        return await talk(req.child, req.history)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"うまく話せませんでした: {e}") from e


# ---------------------------------------------------------------- 子ごとの設定（UX 塊 F）

def _settings_child(request: Request, child: str) -> str:
    """設定を読み書きする子。子どもは自分だけ（ほかの子は 403）。親は家族の子なら誰でも。"""
    child = _self(request, (child or "").strip())
    if not child:
        raise HTTPException(400, "だれの設定かが分かりません。")
    if child not in [c["name"] for c in config.children]:
        raise HTTPException(404, "その子が見つかりません。")
    return child


def _settings_body(child: str) -> Dict[str, Any]:
    settings = appearance_mod.read(child)
    return {"child": child, "settings": settings, "reading_policy": appearance_mod.reading_policy(settings)}


@app.get("/api/child-settings")
def api_child_settings(request: Request, child: str = ""):
    """子ごとの設定（見た目・相棒・学年と読み）。塊 A の AppearanceStore／CompanionStore が読む。"""
    return _settings_body(_settings_child(request, child))


@app.post("/api/child-settings")
async def api_child_settings_write(request: Request):
    """送った項目だけを変える（部分更新）。子どもは自分のテーマと相棒の名前だけ。学年・読み・文体は親だけ。"""
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, "JSON で送ってください。") from e
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON のオブジェクトで送ってください。")
    child = _settings_child(request, str(body.pop("child", "") or ""))
    try:
        appearance_mod.write(child, body, parent=auth.is_parent(_user(request)))
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except appearance_mod.SettingError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        # 保存できなかったのに成功を返さない（画面は「まだ覚えられていない」を出す）
        raise HTTPException(500, f"設定を保存できませんでした: {e}") from e
    return _settings_body(child)


WEEK_GOAL = 5          # 週の台紙。★5つで1枚


@app.get("/api/week")
def api_week(request: Request, child: str = ""):
    """今週の台紙。**日曜に戻る**（週は日曜はじまり）。

    `/api/tasks` は過去の「済」を落とす（やることの一覧なので、それでいい）。
    台紙は済んだ数を数えるものなので、カレンダーから直接読む。
    """
    child = _self(request, child)
    if not child:
        raise HTTPException(400, "だれのぶんかが分かりません。")
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7)   # 直近の日曜
    end = start + dt.timedelta(days=6)                              # その週の土曜まで
    # 明日ぶんを今日やることもある。週のうちなら数える。
    try:
        rows = list_raw(start.isoformat(), end.isoformat())
    except Exception as e:  # noqa: BLE001
        # 取れなかったのに 0件と返すと、台紙が「まだ0こ」に見える（UX_SPEC §4.3）。取れなかったと返す
        raise HTTPException(500, f"今週の台紙を取得できませんでした: {e}") from e
    done = [r for r in rows if r.get("child") == child and r.get("status") == "done"]
    return {
        "child": child,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": today.isoformat(),
        "done": len(done),
        "goal": WEEK_GOAL,
        "full": len(done) >= WEEK_GOAL,
    }


@app.get("/api/capacity")
def api_capacity():
    """今日の枠と、曜日ごとの枠。**当日の上書きが曜日より強い。**"""
    cap = study_mod.capacity()
    return {
        "minutes": study_mod.minutes_on(study_mod.today(), cap),
        "week": cap["week"],
        "days": cap["days"],
        "today": study_mod.today().isoformat(),
    }


class CapacityRequest(BaseModel):
    minutes: Optional[int] = None                 # 今日だけ変える
    week: Optional[Dict[str, Any]] = None         # 曜日ごと
    days: Optional[Dict[str, Any]] = None         # 日を指定して上書き


@app.post("/api/capacity", dependencies=[Depends(_can_set_capacity)])
def api_set_capacity(req: CapacityRequest):
    days = dict(req.days or {})
    if req.minutes is not None:
        days[study_mod.today().isoformat()] = req.minutes
    try:
        study_mod.set_capacity(week=req.week, days=days or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return api_capacity()


class PostponeRequest(BaseModel):
    event_id: str


@app.post("/api/postpone")
def api_postpone(req: PostponeRequest, request: Request):
    """「明日に送る」。**消さない。減らさない。日にちを1日ずらすだけ。**

    入らない日がある。詰め込ませるより、動かせるほうがいい。
    動かしたことは予定に残るので、親も見れば分かる。
    """
    _own_event(request, req.event_id)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    try:
        rows = list_raw((today - dt.timedelta(days=14)).isoformat(),
                        (today + dt.timedelta(days=30)).isoformat())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"予定を読めませんでした: {e}") from e
    row = next((r for r in rows if r.get("id") == req.event_id), None)
    if not row:
        raise HTTPException(404, "その予定が見つかりませんでした。")
    base = dt.date.fromisoformat(row["date"])
    nxt = max(base, today) + dt.timedelta(days=1)
    result = move_event(req.event_id, nxt.isoformat())
    if result.get("status") == "error":
        raise HTTPException(404, result.get("note", "動かせませんでした"))
    return result


@app.get("/api/points")
def api_points(request: Request, child: str = ""):
    """残高と履歴。共同開発者の points.py を呼ぶだけ。"""
    child = _self(request, child)
    if not child:
        raise HTTPException(400, "だれのぶんかが分かりません。")
    try:
        return {
            "child": child,
            "balance": points_mod.balance(child),
            "history": points_mod.history(child),
            "rules": points_mod.RULES,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"ポイントの取得に失敗しました: {e}") from e


@app.get("/api/rewards")
def api_rewards():
    return {"rewards": points_mod.get_rewards()}


class RewardsRequest(BaseModel):
    rewards: List[Dict[str, Any]]


@app.post("/api/rewards", dependencies=[Depends(parent_only)])
def api_set_rewards(req: RewardsRequest):
    try:
        return points_mod.set_rewards(req.rewards)
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"交換レートの保存に失敗しました: {e}") from e


@app.get("/api/recurring", dependencies=[Depends(parent_only)])
def api_recurring():
    """毎日きまっていること（テンプレート）を返す。"""
    return {"templates": recurring_mod.templates(), "today": recurring_mod.ensure()}


class RecurringRequest(BaseModel):
    templates: List[Dict[str, Any]]


@app.post("/api/recurring", dependencies=[Depends(parent_only)])
def api_set_recurring(req: RecurringRequest):
    try:
        saved = recurring_mod.set_templates(req.templates)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"保存に失敗しました: {e}") from e
    saved["today"] = recurring_mod.ensure()
    return saved


class YearPlanRequest(BaseModel):
    """年間行事予定の貼り付け。PDFが落とせない学校があるので、テキストでも受ける。"""
    text: str
    child: str = ""
    fiscal_year: Optional[int] = None
    levels: List[str] = ["family"]
    confirm: bool = False          # 資料が怪しいと分かったうえで入れる、の意思表示


def _year_plan_rows(req: YearPlanRequest):
    rows = year_plan_mod.parse(req.text, req.fiscal_year)
    if not rows:
        raise HTTPException(400, "日付のある行が見つかりませんでした。「4月」「1日 (水) 始業式」の形で貼ってください。")
    return rows


@app.post("/api/year_plan/extract", dependencies=[Depends(parent_only)])
async def api_year_plan_extract(
    files: List[UploadFile] = File(...),
    fiscal_year: Optional[int] = Form(None),
):
    """年間行事予定表の**表そのもの**（PDF・写真）を読み、貼り付け用の文字にして返す。

    アプリの「テキストで表示」は表を1行に潰すときに壊れることが分かっているので
    （曜日の列が2行ずれていた）、画像から読む道を用意する。
    ここでは**写すだけ**。日付が正しいかは /api/year_plan/check が計算で確かめる。
    """
    pages: List[tuple] = []
    for f in files[:4]:
        data = await f.read()
        if not data:
            continue
        if len(data) > MAX_BYTES:
            raise HTTPException(413, f"{f.filename} が大きすぎます。12MB 以下にしてください。")
        try:
            pages += images_mod.to_pages(data, f.content_type or "")
        except ValueError as e:
            raise HTTPException(415, str(e)) from e
    if not pages:
        raise HTTPException(400, "読み取るものがありません。")
    if len(pages) > 6:
        raise HTTPException(400, "一度に読めるのは6ページまでです。")

    sample = os.getenv("MIMAMORI_YEAR_PLAN_SAMPLE", "")
    if sample and os.path.exists(sample):
        text = open(sample, encoding="utf-8").read()      # デモ・検証用の差し替え
    else:
        try:
            text = (await read_year_plan(pages))["text"]
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"読み取りに失敗しました: {e}") from e

    rows = year_plan_mod.parse(text, fiscal_year)
    return {
        "text": text,
        "pages": len(pages),
        "rows": len(rows),
        "check": year_plan_mod.check(rows) if rows else None,
        "counts": year_plan_mod.summarize(rows),
    }


@app.post("/api/year_plan/check", dependencies=[Depends(parent_only)])
def api_year_plan_check(req: YearPlanRequest):
    """**入れる前に、資料そのものを確かめる。** ここで止めるのが仕事。"""
    rows = _year_plan_rows(req)
    child = req.child or (config.children[-1]["name"] if config.children else "")
    items = year_plan_mod.to_items(rows, child, tuple(req.levels))
    return {
        "check": year_plan_mod.check(rows),
        "counts": year_plan_mod.summarize(rows),
        "child": child,
        "will_add": len(items),
        "preview": items[:10],
    }


@app.post("/api/year_plan/register", dependencies=[Depends(parent_only)])
def api_year_plan_register(req: YearPlanRequest):
    """確かめたうえで入れる。すでにある予定は作らない。件名が同じで日付が違うものは作らず、報告する。"""
    rows = _year_plan_rows(req)
    report = year_plan_mod.check(rows)
    if not report["ok"] and not req.confirm:
        raise HTTPException(409, "資料の日付が確かめられません。内容を見てから「それでも入れる」を押してください。")

    child = req.child or (config.children[-1]["name"] if config.children else "")
    items = year_plan_mod.to_items(rows, child, tuple(req.levels))
    if not items:
        return {"created": 0, "skipped": 0, "moved": [], "note": "入れるものがありませんでした。"}
    if len(items) > 400:
        raise HTTPException(400, "一度に入れられるのは400件までです。")

    dates = sorted(i["date"] for i in items)
    try:
        existing = list_raw(dates[0], dates[-1])
    except Exception:  # noqa: BLE001
        existing = []
    by_date = {(e["date"], _key(e.get("summary", ""))) for e in existing}
    titles: Dict[str, Dict[str, str]] = {}
    for e in existing:
        titles.setdefault(_key(e.get("summary", "")), {"date": e["date"], "id": e.get("id", "")})

    # 版。改訂版を入れたときに「どの取り込みで入ったか」を予定に残す。
    batch = "yp-" + dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y%m%d-%H%M")

    fresh, skipped, moved = [], 0, []
    for it in items:
        key = _key(it["title"])
        if (it["date"], key) in by_date:
            skipped += 1
            continue
        if key in titles:
            # 同じ行事が別の日に入っている。**勝手に直さず、勝手に増やさない。**
            moved.append(
                {
                    "title": it["title"],
                    "before": titles[key]["date"],
                    "after": it["date"],
                    "event_id": titles[key]["id"],
                }
            )
            continue
        fresh.append(dict(it, batch=batch))

    results = create_events(fresh, "todo") if fresh else []
    ok = [r for r in results if r.get("status") == "ok"]
    return {
        "created": len(ok),
        "skipped": skipped,
        "moved": moved,
        "batch": batch,
        "errors": [r for r in results if r.get("status") != "ok"][:5],
        "check": report,
    }


class MoveRequest(BaseModel):
    event_id: str
    date: str


@app.post("/api/year_plan/move", dependencies=[Depends(parent_only)])
def api_year_plan_move(req: MoveRequest):
    """改訂版で日にちが変わったものを、1件ずつ直す。

    消して作り直さない。id が変わるとポイント台帳の紐づけが切れる。
    まとめて直さないのは、**改訂版の読み取りが間違っている場合があるため**。
    親が1件ずつ見て押す。
    """
    try:
        result = move_event(req.event_id, req.date)
        if result.get("status") == "error":
            # 直せていないのに 200 を返すと、画面には「直しました」と出て台帳はそのままになる。
            raise HTTPException(404, result.get("note", "その予定が見つかりませんでした"))
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, f"日付の形が違います: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"日にちを直せませんでした: {e}") from e


class RepeatRequest(BaseModel):
    child: str


@app.post("/api/quick/repeat")
def api_quick_repeat(req: RepeatRequest, request: Request):
    """「昨日と同じ」。昨日その子に出ていた宿題・持ち物を、今日ぶんとして作る。

    公文のような定期ぶんは A-5 が並べる。こちらは**学校の宿題**用。
    毎日ほぼ同じ（音読・漢字ドリル・計算）なので、打ち直させない。
    """
    req.child = _self(request, req.child)
    if not req.child:
        raise HTTPException(400, "だれのぶんかが分かりません。")
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    yest = today - dt.timedelta(days=1)
    try:
        rows = list_raw(yest.isoformat(), today.isoformat())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"昨日のぶんを取れませんでした: {e}") from e

    have = {_key(r.get("summary", "")) for r in rows if r["date"] == today.isoformat()}
    items, skipped = [], 0
    for r in rows:
        if r["date"] != yest.isoformat() or r.get("child") != req.child:
            continue
        if r.get("kind") not in ("homework", "bring"):
            continue
        title = (r.get("summary") or "").replace("✓", "").strip()
        if _key(title) in have:
            skipped += 1
            continue
        have.add(_key(title))
        items.append(
            {
                "title": title,
                "child": req.child,
                "kind": r.get("kind", "homework"),
                "date": today.isoformat(),
                "note": "昨日と同じぶん",
            }
        )
    if not items:
        return {"created": [], "skipped": skipped,
                "note": "昨日のぶんが見つかりませんでした。" if not skipped else "もう入っています。"}
    results = create_events(items, "todo")
    return {
        "created": [r["title"] for r in results if r.get("status") == "ok"],
        "skipped": skipped,
    }


@app.get("/api/schedule")
def api_schedule(request: Request, ym: str = "", child: str = ""):
    """1か月ぶんの予定。**年間予定を入れたあと、それを見る場所がないと意味がない。**

    /api/tasks は「これからの14日」しか返さない（やることの一覧なので、それでいい）。
    予定表は過去も未来も、月の単位で見る。
    """
    child = _self(request, child)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    try:
        y, m = (int(x) for x in (ym or today.strftime("%Y-%m")).split("-"))
        first = dt.date(y, m, 1)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, "月の指定は YYYY-MM の形で書いてください。") from e
    last = dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)

    try:
        items = list_raw(first.isoformat(), last.isoformat())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"予定を取れませんでした: {e}") from e

    items = [i for i in items if i.get("status") != "rejected"]
    if child:
        items = [i for i in items if i.get("child") == child]
    for i in items:
        i["days_left"] = (dt.date.fromisoformat(i["date"]) - today).days

    return {
        "ym": first.strftime("%Y-%m"),
        "first": first.isoformat(),
        "last": last.isoformat(),
        "today": today.isoformat(),
        "children": [c["name"] for c in config.children] if auth.is_parent(_user(request)) else [child],
        "items": sorted(items, key=lambda x: (x["date"], x.get("child", ""), x.get("summary", ""))),
    }


@app.get("/api/assignments")
def api_assignments(request: Request, child: str = "", include_done: bool = False):
    child = _self(request, child)
    return {"items": study_mod.assignments(child or None, include_done)}


class AssignmentRequest(BaseModel):
    child: str
    subject: str
    title: str
    due: str
    range_text: str = ""          # 「p.42-78」。数に直せればこちらだけでよい
    total: Optional[int] = None
    unit: str = "page"
    priority: int = 0


@app.post("/api/assignments")
def api_add_assignment(req: AssignmentRequest, request: Request):
    """課題を足す。範囲は**まず計算で**数に直す（モデルは呼ばない）。"""
    req.child = _self(request, req.child)
    total, unit = req.total, req.unit
    parsed = study_mod.parse_range(req.range_text or req.title)
    if total is None:
        if not parsed:
            raise HTTPException(
                400,
                "範囲を数に直せませんでした。「p.42-78」「1〜50問」「20ページ」のように書くか、量を直接入れてください。",
            )
        total, unit = parsed["total"], parsed["unit"]
    try:
        row = study_mod.add_assignment(req.child, req.subject, req.title, total, unit, req.due, req.priority)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"assignment": row, "parsed": parsed}


class AssignmentUpdate(BaseModel):
    id: str
    done: Optional[int] = None
    priority: Optional[int] = None
    due: Optional[str] = None


@app.post("/api/assignments/update")
def api_update_assignment(req: AssignmentUpdate, request: Request):
    _own_assignment(request, req.id)
    try:
        return {"assignment": study_mod.update_assignment(req.id, req.done, req.priority, req.due)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


class AssignmentDelete(BaseModel):
    id: str


@app.post("/api/assignments/remove")
def api_remove_assignment(req: AssignmentDelete, request: Request):
    _own_assignment(request, req.id)
    if not study_mod.remove_assignment(req.id):
        raise HTTPException(404, "その課題が見つかりませんでした。")
    return {"ok": True}


@app.get("/api/plan")
def api_plan(request: Request, child: str = ""):
    """配分の結果。**コードだけで出す**ので、押した瞬間に返る。"""
    child = _self(request, child)
    if not child:
        raise HTTPException(400, "だれのぶんかが分かりません。")
    return study_mod.plan(child)


@app.get("/api/plan/today")
def api_plan_today(request: Request, child: str = ""):
    child = _self(request, child)
    if not child:
        raise HTTPException(400, "だれのぶんかが分かりません。")
    return study_mod.today_plan(child)


class RangeRequest(BaseModel):
    text: str


@app.post("/api/study/range")
def api_study_range(req: RangeRequest):
    """「ワーク p.42-78」→ 37ページ。読めなければ null を返す（人に聞く）。"""
    return {"parsed": study_mod.parse_range(req.text)}


# ---------------------------------------------------------------- ごほうび（E系）

@app.get("/api/redeem")
def api_redeem_list(request: Request, child: str = "", status: str = ""):
    child = _self(request, child)
    return {
        "items": redeem_mod.requests(child=child, status=status),
        "remaining": redeem_mod.remaining(child),
        "labels": redeem_mod.LABEL,
    }


class RedeemRequest(BaseModel):
    request_key: Optional[str] = None
    child: str
    label: str
    cost: int
    yen: int = 0


@app.post("/api/redeem")
def api_redeem_request(req: RedeemRequest, request: Request):
    """子が申し込む。**ここでポイントを引く**（断られたら戻る）。"""
    req.child = _self(request, req.child)
    try:
        row = redeem_mod.request(
            req.child, req.label, req.cost, req.yen, request_key=req.request_key,
            allowed_rewards=None if auth.is_parent(_user(request)) else points_mod.get_rewards())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    try:
        notify_mod.add("redeem", f"{req.child}が「{req.label}」を申しこみました",
                       f"{req.cost}pt" + (f"／{req.yen}円" if req.yen else ""))
    except Exception:  # noqa: BLE001
        pass
    return {"request": row, "balance": points_mod.balance(req.child)}


class RedeemDecision(BaseModel):
    id: str
    note: str = ""


@app.post("/api/redeem/approve", dependencies=[Depends(parent_only)])
def api_redeem_approve(req: RedeemDecision):
    try:
        return {"request": redeem_mod.approve(req.id, req.note)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/redeem/reject", dependencies=[Depends(parent_only)])
def api_redeem_reject(req: RedeemDecision):
    """断る。**理由が要る**（子どもに伝わる）。引いたポイントは戻す。"""
    try:
        row = redeem_mod.reject(req.id, req.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"request": row, "balance": points_mod.balance(row["child"])}


@app.post("/api/redeem/hand", dependencies=[Depends(parent_only)])
def api_redeem_hand(req: RedeemDecision):
    try:
        return {"request": redeem_mod.hand(req.id)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class CapRequest(BaseModel):
    yen: Optional[int] = None
    count: Optional[int] = None


@app.post("/api/redeem/cap", dependencies=[Depends(parent_only)])
def api_redeem_cap(req: CapRequest):
    return redeem_mod.set_cap(req.yen, req.count)


@app.get("/api/redeem/pace")
def api_redeem_pace(request: Request, child: str = "", cost: int = 0):
    """「今のペースだと約◯日」。分からないときは言わない。"""
    child = _self(request, child)
    if not child:
        raise HTTPException(400, "だれのぶんかが分かりません。")
    return {
        "child": child,
        "balance": points_mod.balance(child),
        "per_day": round(redeem_mod.pace(child), 1),
        "days": redeem_mod.days_to(child, cost) if cost else None,
    }


@app.get("/healthz")
def healthz():
    return {"ok": True}
