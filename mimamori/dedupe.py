"""取り込みの4分岐 — 完全一致／差分／日程変更／新規。

なぜ要るか（D-33 / D-34）:
    同じ行事が、親のプリントと子の連絡ちょうの両方から来る。毎回「二重登録です、
    承認しますか」と聞いていたら、**承認そのものが面倒になってアプリが死ぬ。**
    だから完全一致は**黙って飛ばす**。人に見せるのは、
      追記（持ち物が増えた） / 日程変更（日にちが動いた） / 新規
    の3つだけにする。

ここもモデルを呼ばない:
    モデルは実行ごとに件名を言い換える（「三者面談 希望調査票 提出」と
    「三者面談希望調査票 提出期限」）。判定が揺れると、昨日飛ばしたものが
    今日また出てくる。**判定は計算でやる。**
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata
from typing import Any, Dict, List, Optional

# これ以上似ていれば「同じもの」とみなす。
# 上げすぎると「体育祭」と「体育祭 予備日」が同じになる。下げすぎると見逃す。
SAME_RATIO = 0.82

# 日にちが動いたと見る幅。予備日や締切の訂正はこのくらいの幅で動く。
MOVE_DAYS = 21


def norm(text: str) -> str:
    """件名の比べ方。✓・全角半角・空白・かっこの違いで別物にしない。"""
    s = unicodedata.normalize("NFKC", text or "").replace("✓", "")
    # NFKC は、子の名前との区切り「｜」も半角にする。
    if "|" in s:
        s = s.split("|", 1)[1]
    s = re.sub(r"[\s()\[\]「」『』・,、.。:]+", "", s)
    return s.lower()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _bring_set(value: Any) -> set:
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[、,／/]+", str(value or ""))
    return {p.strip() for p in parts if p and p.strip()}


def classify(item: Dict[str, Any], existing: List[Dict[str, Any]]) -> Dict[str, Any]:
    """1件を4つのどれかに分ける。

    Args:
        item: 読み取った候補（title / date / bring / time_start / note）
        existing: 既存の予定（summary / date / bring / time / id）

    Returns:
        {"branch": "same|diff|moved|new", "matched": 既存の予定 or None,
         "changes": ["持ち物が増えた", ...]}
    """
    title = item.get("title") or ""
    date = item.get("date") or ""
    best, score = None, 0.0
    for ev in existing:
        r = similarity(title, ev.get("summary", ""))
        # 同名の別日予定（デモの初期予定など）が先にあっても、
        # 同点なら同日の登録済み予定を選ぶ。再取り込みを日程変更にしない。
        if r > score or (best is not None and r == score
                         and ev.get("date") == date and best.get("date") != date):
            best, score = ev, r
    if not best or score < SAME_RATIO:
        return {"branch": "new", "matched": None, "changes": [], "score": round(score, 2)}

    changes: List[str] = []
    same_day = (best.get("date") or "") == date

    # 追記：新しい情報が増えたか。**減った分は見ない**（読み落としで消さないため）
    new_bring = _bring_set(item.get("bring"))
    old_bring = _bring_set(best.get("bring"))
    added = new_bring - old_bring
    if added:
        changes.append("持ち物が増えた（" + "、".join(sorted(added)) + "）")
    if item.get("time_start") and not best.get("time"):
        changes.append("時刻がついた（" + str(item["time_start"]) + "）")
    elif item.get("time_start") and best.get("time") and item["time_start"] != best["time"]:
        changes.append("時刻が変わった（" + str(best["time"]) + "→" + str(item["time_start"]) + "）")

    if not same_day:
        gap = _gap(date, best.get("date"))
        if gap is not None and abs(gap) <= MOVE_DAYS:
            return {"branch": "moved", "matched": best, "changes": changes,
                    "score": round(score, 2), "from": best.get("date"), "to": date}
        # 離れすぎているものは別物として扱う（去年の同じ行事など）
        return {"branch": "new", "matched": None, "changes": [], "score": round(score, 2)}

    if changes:
        return {"branch": "diff", "matched": best, "changes": changes, "score": round(score, 2)}
    return {"branch": "same", "matched": best, "changes": [], "score": round(score, 2)}


def _gap(a: str, b: Optional[str]) -> Optional[int]:
    try:
        return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days
    except (TypeError, ValueError):
        return None


LABEL = {"same": "すでにある", "diff": "追記", "moved": "日程変更", "new": "新規"}


def review(items: List[Dict[str, Any]], existing: List[Dict[str, Any]]) -> Dict[str, Any]:
    """候補をまとめて分ける。**完全一致は候補から外す**（承認を出さない）。

    Returns:
        {"items": 人に見せるぶん, "skipped": 黙って飛ばした件数, "skipped_titles": [...]}
    """
    show, skipped = [], []
    for it in items:
        verdict = classify(it, existing)
        it = dict(it)
        it["branch"] = verdict["branch"]
        it["branch_label"] = LABEL[verdict["branch"]]
        it["changes"] = verdict["changes"]
        it["match_score"] = verdict["score"]
        if verdict["matched"]:
            it["duplicate_of"] = verdict["matched"].get("summary", "")
            it["matched_id"] = verdict["matched"].get("id", "")
            it["matched_date"] = verdict["matched"].get("date", "")
        if verdict["branch"] == "same":
            skipped.append(it.get("title", ""))
            continue
        # 既定でチェックを入れるのは新規だけ。追記と日程変更は人が見てから。
        it["selected"] = verdict["branch"] == "new"
        show.append(it)
    return {"items": show, "skipped": len(skipped), "skipped_titles": skipped}
