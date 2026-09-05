"""みまもりくんのエージェント本体。

設計方針（お金の主治医エージェントと同じ）：
    読み取りと判断は自律、カレンダーへの書き込みは承認。

エージェントが自分で回すステップ：
    1. おたよりの画像を読む（マルチモーダル）
    2. 相対的な日付表現を実日付に直す
    3. どの子・どの学校のものか判定する
    4. list_events で既存カレンダーを照会し、重複を見つける  ← 書く前に読む
    5. 登録候補を JSON で返す（この時点では書かない）
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from typing import Any, Dict, List

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from .calendar_tools import list_events
from .config import config
from .schema import Extraction

APP_NAME = "mimamorikun"


def _instruction() -> str:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    return f"""あなたは「みまもりくん」。共働き家庭の保護者に代わって、学校からのおたよりを読み、
カレンダーに載せるべきものを拾い出す担当です。

# 今日の日付
{today.isoformat()}（{"月火水木金土日"[today.weekday()]}曜日）
相対表現（来週金曜、今月末、明後日など）は必ずこの日付を起点に実日付へ直すこと。

# 対象の子ども
{config.children_label}
おたよりの学年表記・校名・教科・持ち物から、どちらの子のものか推定する。
判別できないときは child を「不明」にし、needs_review を true にする。

# 手順
1. 画像を丁寧に読む。日付、提出期限、持ち物、集合時刻、金額を落とさない。
2. カレンダーに載せる価値のあるものだけを items にする。
   挨拶文、校長のコラム、一般的な注意書きは載せない。
3. 期間を決めたら **必ず list_events を呼び**、その期間の既存予定を確認する。
   同じ行事がアプリと紙の両方から来ることがあるため、重複登録は最も嫌われる失敗。
   似た予定があれば duplicate_of にその件名を入れる。
4. 最終出力は JSON のみ。前置きも説明も、コードフェンスも付けない。

# title の付け方
必ず「子の名前」を先頭に置き、一目で誰のものか分かるようにする。
例: 「下の子｜図工 ペットボトル2本 持参」「上の子｜期末テスト範囲 提出」

# needs_review を true にする場合
- 日付が読み取れない、または曖昧
- どちらの子か判別できない
- 金額や持ち物が読み取れたか自信がない

# 出力する JSON の形
{{
  "summary": "このおたよりが何だったか1〜2文",
  "items": [
    {{
      "kind": "event|deadline|homework|bring",
      "title": "子の名前｜件名",
      "child": "子の名前 または 不明",
      "school_level": "elementary|junior_high|unknown",
      "date": "YYYY-MM-DD",
      "end_date": null,
      "time_start": "HH:MM または null",
      "time_end": "HH:MM または null",
      "bring": ["持ち物"],
      "note": "補足",
      "source_text": "根拠になった原文の抜粋",
      "confidence": 0.0,
      "needs_review": false,
      "duplicate_of": null
    }}
  ]
}}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="mimamori_reader",
        model=config.model,
        description="学校のおたよりを読み、カレンダー登録候補を作る",
        instruction=_instruction(),
        tools=[list_events],
    )


def _parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON が見つかりません: {text[:300]}")
    return json.loads(text[start : end + 1])


async def read_otayori(image_bytes: bytes, mime_type: str, hint: str = "") -> Dict[str, Any]:
    """画像を1枚渡して、登録候補を返す。カレンダーへの書き込みはしない。"""
    runner = InMemoryRunner(agent=build_agent(), app_name=APP_NAME)
    user_id = "parent"
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=user_id)

    parts = [types.Part.from_bytes(data=image_bytes, mime_type=mime_type)]
    prompt = "このおたよりを読んで、カレンダー登録候補を JSON で返してください。"
    if hint.strip():
        prompt += f"\n補足（保護者からのメモ）: {hint.strip()}"
    parts.append(types.Part.from_text(text=prompt))

    final = ""
    trace: List[str] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=parts),
    ):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if getattr(p, "function_call", None):
                    trace.append(f"ツール呼び出し: {p.function_call.name}")
                if getattr(p, "function_response", None):
                    trace.append(f"ツール応答: {p.function_response.name}")
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)

    data = _parse_json(final)
    parsed = Extraction.model_validate(data)
    out = parsed.model_dump()
    for item in out["items"]:
        item["id"] = uuid.uuid4().hex[:8]
        item["selected"] = not item.get("duplicate_of")
    out["trace"] = trace
    return out
