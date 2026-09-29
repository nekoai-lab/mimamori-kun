"""ポイントと交換。

決まっているルール（変えるときは相談）:
    - ポイントは「行動」に付ける。結果（テストの点数）には付けない
    - テストは点数ではなく「直した問題の数」に付ける
      → 点が悪いテストほどポイントが取れる＝隠す動機が消える
    - 交換レートはアプリに持たせない。親が決める

残高の出し方（2026-09-13 変更）:
    以前はカレンダーの完了予定を毎回合計していた。
    それだと「引き換え（マイナス）」が記録できず、90日より前も消えるため、
    **台帳（ledger）の合算**に変えた。完了操作の時点で台帳へ記録する。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from . import ledger

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
    """旧呼び出し元との互換用。加点は set_status だけで行う。"""
    return 0


def record_status(task: Dict[str, Any], status: str, done_at: str) -> str:
    """予定ごとの状態と加点・取消を一体で保存し、確定した完了時刻を返す。"""
    import hashlib

    key = "task_completion_" + hashlib.sha256(task["id"].encode()).hexdigest()

    def change(current, balance, extra):
        current = current or {}
        entry = current.get("entry")
        if status == "done":
            if current.get("done_at"):
                return current, [], current["done_at"]
            entry = ledger.make_entry(
                child=task.get("child", ""), delta=int(task.get("points") or 0),
                reason=task.get("kind", "unknown"), ref_id=task["id"],
                title=task.get("summary", "").lstrip("✓ ").split("｜")[-1],
            )
            entry["created_at"] = done_at
            return {"done_at": done_at, "entry": entry}, [entry], done_at
        rows = []
        if entry and current.get("done_at"):
            entry = {**entry, "revoked": True, "revoked_at": ledger._now()}
            rows.append(entry)
        return {"done_at": "", "entry": entry}, rows, ""

    return ledger.transact_setting_entries(key, task.get("child", ""), change)


# ------------------------------------------------------------------ 残高と履歴

def balance(child: str) -> int:
    """その子の現在の残高。台帳の合算。"""
    return ledger.balance(child)


def history(child: str, limit: int = 30) -> List[Dict[str, Any]]:
    """何で増えた／減ったかの履歴。子どもに見せる用。"""
    out = []
    for e in ledger.history(child, limit=limit):
        out.append(
            {
                "title": e.get("title") or _label(e.get("reason", "")),
                "date": (e.get("created_at") or "")[:10],
                "kind": e.get("reason"),
                "points": e.get("delta"),
                "revoked": bool(e.get("revoked")),
                **({"redeem_id": e["redeem_id"]} if e.get("redeem_id") else {}),
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
    "adjust": "調整",
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
    """親が加点を取り消す。行は消さず、印を付けるだけ。

    **日常の導線には置かない。** 親が子のポイントを取り消すのは、子から見れば
    「疑われた」体験になる。ズルへの対応は、引き換えの承認のときに人が話せばよい。
    ここは入力ミスの訂正のために残してあるだけの口。
    """
    return ledger.revoke(entry_id)


def adjust(child: str, delta: int, note: str) -> Dict[str, Any]:
    """親が理由つきで増減を1行足す。**ルールを増やさずに運用で調整するための口。**

    想定している使い方:
        - 残高がマイナスになったのをリセットする
        - 「これもやったらポイントあげよう」と決めた臨時の加点
        - 数え間違いの訂正

    ルールを先に全部決めきるのではなく、走らせながら家族で相談して直していく。
    その調整が台帳に理由つきで残るので、あとから経緯を辿れる。

    Args:
        child: 子どもの識別子
        delta: 増減。減らすときはマイナス
        note: 理由。子どもにもそのまま見える

    Returns:
        追加した台帳の行
    """
    if not note.strip():
        raise ValueError("理由を書いてください（あとで経緯が分からなくなります）")
    return ledger.add(
        child=child,
        delta=int(delta),
        reason="adjust",
        created_by="parent",
        title=note.strip(),
    )


def reset_negative(child: str, note: str = "マイナス分をリセット") -> Optional[Dict[str, Any]]:
    """残高がマイナスなら0に戻す。プラスなら何もしない。"""
    bal = balance(child)
    if bal >= 0:
        return None
    return adjust(child, -bal, note)


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
