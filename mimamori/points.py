"""ポイントと交換。

決まっているルール（変えるときは相談）:
    - ポイントは「行動」に付ける。結果（テストの点数）には付けない
    - テストは点数ではなく「直した問題の数」に付ける
      → 点が悪いテストほどポイントが取れる＝隠す動機が消える
    - 交換レートはアプリに持たせない。親が決める

残高の出し方（2026-09-13 変更）:
    以前はカレンダーの完了予定を毎回合計していた。
    それだと「引き換え（マイナス）」が記録できず、90日より前も消えるため、
    **台帳（ledger）の合算**に変えた。カレンダーの完了は台帳へ取り込む。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from . import ledger
from .calendar_tools import list_tasks

# 種別ごとの付与ポイント。calendar_tools._points_for と揃えること。
RULES: Dict[str, int] = {
    "homework": 3,   # 宿題
    "deadline": 3,   # 提出物
    "bring": 2,      # 持ち物
    "event": 0,      # 行事（やることではないので0）
}
FIX_POINT = 1  # テストの直し 1問につき


def points_for(kind: str, fixed_count: int = 0) -> int:
    """付与ポイントを決める。

    Args:
        kind: event / deadline / homework / bring
        fixed_count: テストの直しの場合、直した問題の数

    Returns:
        ポイント
    """
    if fixed_count:
        return fixed_count * FIX_POINT
    return RULES.get(kind, 1)


# ------------------------------------------------------------------ 取り込み

def sync_from_calendar(child: str, days: int = 90) -> int:
    """完了済みの予定を台帳に取り込む。**同じ予定は二度入らない。**

    カレンダー側で完了にしたものを台帳に反映するための橋渡し。
    何度呼んでも結果が変わらないので、残高を出す前に毎回呼んでよい。

    Returns:
        今回新しく取り込んだ件数
    """
    try:
        data = list_tasks(days=days)
    except Exception:  # noqa: BLE001
        # カレンダーに繋がらなくても残高表示は止めない
        return 0
    added = 0
    for t in data.get("items", []):
        if t.get("child") != child or t.get("status") != "done":
            continue
        pts = t.get("points") or 0
        if not pts or ledger.has_ref(child, t["id"]):
            continue
        ledger.add(
            child=child,
            delta=pts,
            reason=t.get("kind", "unknown"),
            ref_id=t["id"],
            title=t.get("summary", "").replace("✓ ", "").split("｜")[-1],
        )
        added += 1
    return added


# ------------------------------------------------------------------ 残高と履歴

def balance(child: str) -> int:
    """その子の現在の残高。台帳の合算。"""
    sync_from_calendar(child)
    return ledger.balance(child)


def history(child: str, limit: int = 30) -> List[Dict[str, Any]]:
    """何で増えた／減ったかの履歴。子どもに見せる用。"""
    sync_from_calendar(child)
    out = []
    for e in ledger.history(child, limit=limit):
        out.append(
            {
                "title": e.get("title") or _label(e.get("reason", "")),
                "date": (e.get("created_at") or "")[:10],
                "kind": e.get("reason"),
                "points": e.get("delta"),
                "revoked": bool(e.get("revoked")),
            }
        )
    return out


_LABELS = {
    "homework": "宿題",
    "deadline": "提出物",
    "bring": "持ち物",
    "event": "行事",
    "test_fix": "テストの直し",
    "redeem": "こうかん",
}


def _label(reason: str) -> str:
    return _LABELS.get(reason, reason or "—")


# ------------------------------------------------------------------ 加点と取り消し

def add_test_fix(child: str, fixed_count: int, title: str = "テストの直し") -> Dict[str, Any]:
    """テストの直しを加点する。直した問題の数だけ。"""
    return ledger.add(
        child=child,
        delta=points_for("", fixed_count=fixed_count),
        reason="test_fix",
        title=title,
    )


def revoke(entry_id: str) -> bool:
    """親が加点を取り消す。行は消さず、印を付けるだけ。"""
    return ledger.revoke(entry_id)


# ------------------------------------------------------------------ 交換

DEFAULT_REWARDS = [
    {"points": 30, "label": "ゲームの時間を30分のばす"},
    {"points": 100, "label": "週末に行きたいところを1つ決められる"},
]


def get_rewards() -> List[Dict[str, Any]]:
    """交換できるもの一覧。親が決める。金額はアプリが持たない。

    優先順位: 台帳の設定 → 環境変数 → 既定値
    """
    saved = ledger.get_setting("rewards")
    if saved:
        return saved
    raw = os.getenv("MIMAMORI_REWARDS", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return DEFAULT_REWARDS


def set_rewards(rewards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """親が交換レートを設定する。台帳と同じ保存先に置く。"""
    return ledger.set_setting("rewards", rewards)


def redeem(child: str, cost: int, label: str) -> Dict[str, Any]:
    """引き換え。**台帳にマイナスで入れる。**

    実際の受け渡し（ギフトカードを買って手渡す）は親がやる。
    アプリは記録するだけで、決済には一切触れない。
    """
    if cost <= 0:
        raise ValueError("交換に必要なポイントが正しくありません")
    if balance(child) < cost:
        raise ValueError("ポイントが足りません")
    return ledger.add(
        child=child,
        delta=-abs(cost),
        reason="redeem",
        created_by="parent",
        title=label,
    )
