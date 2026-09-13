"""みまもりくん — FastAPI エントリポイント。Cloud Run で動かす。"""
from __future__ import annotations

import datetime as dt
import os
import re

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mimamori.agent import read_otayori, read_year_plan
from mimamori import images as images_mod
from mimamori.kid_agent import talk
from mimamori.calendar_tools import (
    create_events,
    list_events,
    list_raw,
    list_tasks,
    move_event,
    service_account_email,
    set_status,
)
from mimamori.config import config
from mimamori import points as points_mod
from mimamori import recurring as recurring_mod
from mimamori import year_plan as year_plan_mod

def _key(title: str) -> str:
    """件名の比べ方。空白と ✓ の違いで別物にしない。"""
    return re.sub(r"\s", "", (title or "").replace("✓", ""))


app = FastAPI(title="みまもりくん")
app.mount("/static", StaticFiles(directory="static"), name="static")

MAX_BYTES = 12 * 1024 * 1024


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


@app.get("/board")
def board():
    """親のダッシュボード。タスク一覧と予定を見る場所。"""
    return FileResponse("static/board.html")


@app.get("/api/config")
def get_config():
    return {
        "children": config.children,
        "calendar_id": config.calendar_id,
        "model": config.model,
        "service_account": service_account_email(),
    }


@app.post("/api/extract")
async def extract(image: UploadFile = File(...), hint: str = Form("")):
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
        result = await read_otayori(data, content_type, hint)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"読み取りに失敗しました: {e}") from e
    return JSONResponse(result)


class RegisterRequest(BaseModel):
    items: List[Dict[str, Any]]
    # 子の画面から撮ったものは承認待ちで入れる。親が /board で通すまで、
    # 子のやることには出ない。
    pending: bool = False


@app.post("/api/register")
def register(req: RegisterRequest):
    if not req.items:
        raise HTTPException(400, "登録するものがありません。")
    try:
        return {"results": create_events(req.items, "pending" if req.pending else "todo")}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"カレンダー登録に失敗しました: {e}") from e


@app.get("/api/tasks")
def tasks(days: int = 14):
    # 毎日きまっているもの（公文など）は、ここで足りない分だけ用意する。
    # 別のスケジューラを立てない。朝いちばんに誰かが開いた時点で並ぶ。
    try:
        recurring_mod.ensure()
    except Exception:  # noqa: BLE001
        pass            # 定期タスクが作れなくても、一覧は出す
    try:
        return list_tasks(days)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"タスクの取得に失敗しました: {e}") from e


class StatusRequest(BaseModel):
    event_id: str
    status: str  # todo / doing / done


@app.post("/api/status")
def status(req: StatusRequest):
    if req.status not in ("pending", "todo", "doing", "done", "rejected"):
        raise HTTPException(400, "status は pending / todo / doing / done / rejected のいずれかです。")
    try:
        return set_status(req.event_id, req.status)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"状態の更新に失敗しました: {e}") from e


class KidChatRequest(BaseModel):
    child: str
    history: List[Dict[str, str]]


@app.post("/api/kid/chat")
async def kid_chat(req: KidChatRequest):
    if not req.child:
        raise HTTPException(400, "誰の画面かが分かりません。")
    if len(req.history) > 40:
        req.history = req.history[-40:]
    try:
        return await talk(req.child, req.history)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"うまく話せませんでした: {e}") from e


@app.get("/api/points")
def api_points(child: str):
    """残高と履歴。共同開発者の points.py を呼ぶだけ。"""
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


@app.post("/api/rewards")
def api_set_rewards(req: RewardsRequest):
    try:
        return points_mod.set_rewards(req.rewards)
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"交換レートの保存に失敗しました: {e}") from e


@app.get("/api/recurring")
def api_recurring():
    """毎日きまっていること（テンプレート）を返す。"""
    return {"templates": recurring_mod.templates(), "today": recurring_mod.ensure()}


class RecurringRequest(BaseModel):
    templates: List[Dict[str, Any]]


@app.post("/api/recurring")
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


@app.post("/api/year_plan/extract")
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


@app.post("/api/year_plan/check")
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


@app.post("/api/year_plan/register")
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


@app.post("/api/year_plan/move")
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


@app.get("/healthz")
def healthz():
    return {"ok": True}
