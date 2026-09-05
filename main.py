"""みまもりくん — FastAPI エントリポイント。Cloud Run で動かす。"""
from __future__ import annotations

import os

from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mimamori.agent import read_otayori
from mimamori.kid_agent import talk
from mimamori.calendar_tools import create_events, list_tasks, service_account_email, set_status
from mimamori.config import config
from mimamori import points as points_mod

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
    try:
        result = await read_otayori(data, image.content_type or "image/jpeg", hint)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"読み取りに失敗しました: {e}") from e
    return JSONResponse(result)


class RegisterRequest(BaseModel):
    items: List[Dict[str, Any]]


@app.post("/api/register")
def register(req: RegisterRequest):
    if not req.items:
        raise HTTPException(400, "登録するものがありません。")
    try:
        return {"results": create_events(req.items)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"カレンダー登録に失敗しました: {e}") from e


@app.get("/api/tasks")
def tasks(days: int = 14):
    try:
        return list_tasks(days)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"タスクの取得に失敗しました: {e}") from e


class StatusRequest(BaseModel):
    event_id: str
    status: str  # todo / doing / done


@app.post("/api/status")
def status(req: StatusRequest):
    if req.status not in ("todo", "doing", "done"):
        raise HTTPException(400, "status は todo / doing / done のいずれかです。")
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


@app.get("/healthz")
def healthz():
    return {"ok": True}
