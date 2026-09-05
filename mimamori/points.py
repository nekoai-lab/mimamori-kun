"""ポイントと交換の仕組み。

【このファイルは共同開発者の担当】
動く骨だけ置いてあります。中身は好きに作り替えてください。
main.py 側の口（/api/points, /api/rewards）はすでに用意してあるので、
ここの関数のシグネチャだけ保ってもらえれば繋がります。

決まっているルール（変えるときは相談）:
    - ポイントは「行動」に付ける。結果（テストの点数）には付けない
    - テストは点数ではなく「直した問題の数」に付ける
      → 点が悪いテストほどポイントが取れる＝隠す動機が消える
    - 交換レートはアプリに持たせない。親が決める
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

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


def balance(child: str) -> int:
    """その子の現在の残高。完了済みタスクのポイント合計。"""
    data = list_tasks(days=90)
    return sum(t["points"] for t in data["items"] if t["child"] == child and t["status"] == "done")


def history(child: str, limit: int = 30) -> List[Dict[str, Any]]:
    """何で貯まったかの履歴。子どもに見せる用。"""
    data = list_tasks(days=90)
    out = [
        {
            "title": t["summary"].replace("✓ ", "").split("｜")[-1],
            "date": t["date"],
            "kind": t["kind"],
            "points": t["points"],
        }
        for t in data["items"]
        if t["child"] == child and t["status"] == "done" and t["points"]
    ]
    return sorted(out, key=lambda x: x["date"], reverse=True)[:limit]


# ------------------------------------------------------------------ 交換
#
# TODO（共同開発者へ）
#   いまは環境変数から読むだけで、画面から保存できません。
#   Cloud Run はステートレスなのでファイル保存は消えます。選択肢は3つ:
#     A. 環境変数のまま（今日はこれで十分）
#     B. カレンダーに「みまもりくん設定」という終日予定を1つ作り、
#        その description に JSON を持たせる（台帳をカレンダーに寄せる方針と一致）
#     C. Firestore を足す（確実だが、DBを作らない方針から外れる）
#   今日は A、余裕があれば B、を勧めます。

DEFAULT_REWARDS = [
    {"points": 30, "label": "好きなおやつ 1つ"},
    {"points": 100, "label": "週末に行きたいところを1つ決められる"},
]


def get_rewards() -> List[Dict[str, Any]]:
    """交換できるもの一覧。親が決める。金額はアプリが持たない。"""
    raw = os.getenv("MIMAMORI_REWARDS", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return DEFAULT_REWARDS


def set_rewards(rewards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """親が交換レートを設定する。※未実装。上の TODO を参照。"""
    raise NotImplementedError("交換レートの保存はまだ実装されていません（docs/分担.md を参照）")
