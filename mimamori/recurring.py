"""定期タスク。毎日きまっているものを、入力なしで朝ならべる。

なぜ要るか:
    公文のプリントは毎日あるが、内容が日替わりでない。
    「英語・国語・算数のプリント」と決まっているものを毎朝撮らせる／打たせるのは、
    撮る意味のない写真を撮らせているのと同じ。下の子の入力問題は、
    テンプレートを一度決めるだけでほぼ消える。

置き場所:
    新しいDBは作らない。テンプレートは台帳（ledger）の settings に置く。
    ローカルでは .data/ledger.json、GCP を繋げば Firestore に載る。
    生成された「やること」自体はいつも通りカレンダーに入る。

二重に作らないための決まり:
    1. その日のカレンダーを読み、同じ子・同じ件名があれば作らない
    2. その日すでに走ったことを settings に残し、二度目は読むだけで帰る
    どちらか片方でも足りるが、同時アクセスで重複が出るのを避けるため両方やる。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from . import ledger
from .calendar_tools import create_events, list_tasks
from .config import config

_KEY = "recurring_tasks"
_RUN_KEY = "recurring_last_run"
JST = dt.timezone(dt.timedelta(hours=9))

# days の書き方: "daily" または 曜日番号のリスト（0=月 … 6=日）
DAILY = "daily"


def today() -> dt.date:
    return dt.datetime.now(JST).date()


def _elementary() -> str:
    """公文に通っている子（小学生）の呼び名。無ければ最後の子。"""
    names = [c["name"] for c in config.children] or ["下の子"]
    for c in config.children:
        if c.get("school_level") == "elementary":
            return c["name"]
    return names[-1]


def default_templates() -> List[Dict[str, Any]]:
    """初期値。公文の3教科を毎日。親が画面で止めたり足したりできる。"""
    child = _elementary()
    return [
        {"id": "kumon-kokugo", "child": child, "title": "くもん 国語", "kind": "homework", "days": DAILY, "enabled": True},
        {"id": "kumon-sansu", "child": child, "title": "くもん 算数", "kind": "homework", "days": DAILY, "enabled": True},
        {"id": "kumon-eigo", "child": child, "title": "くもん 英語", "kind": "homework", "days": DAILY, "enabled": True},
    ]


def templates() -> List[Dict[str, Any]]:
    """保存済みのテンプレート。まだ無ければ初期値を返す（保存はしない）。"""
    saved = ledger.get_setting(_KEY)
    if not saved:
        return default_templates()
    return [t for t in saved if isinstance(t, dict)]


def set_templates(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """テンプレートを入れ替える。内容が変わったら、その日の生成をやり直せるようにする。"""
    cleaned = []
    for i, t in enumerate(items):
        title = (t.get("title") or "").strip()
        child = (t.get("child") or "").strip()
        if not title or not child:
            raise ValueError("だれの・なにを、の両方が必要です。")
        days = t.get("days", DAILY)
        if days != DAILY:
            days = sorted({int(d) for d in days if 0 <= int(d) <= 6})
            if not days:
                raise ValueError(f"「{title}」の曜日が空です。")
        cleaned.append(
            {
                "id": (t.get("id") or f"r{i}-{title}")[:64],
                "child": child,
                "title": title,
                "kind": t.get("kind") or "homework",
                "days": days,
                "enabled": bool(t.get("enabled", True)),
            }
        )
    ledger.set_setting(_KEY, cleaned)
    ledger.set_setting(_RUN_KEY, "")      # 変えた当日にも反映されるように
    return {"saved": len(cleaned), "templates": cleaned}


def due_on(date: dt.date, items: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """その日に出るテンプレートだけを返す。"""
    wd = date.weekday()
    out = []
    for t in (items if items is not None else templates()):
        if not t.get("enabled", True):
            continue
        days = t.get("days", DAILY)
        if days == DAILY or wd in [int(d) for d in days]:
            out.append(t)
    return out


def _norm(summary: str) -> str:
    """カレンダーの件名を、テンプレートの件名と比べられる形にする。"""
    s = (summary or "").replace("✓", " ").strip()
    if "｜" in s:
        s = s.split("｜", 1)[1]
    return " ".join(s.split())


def ensure(date: Optional[dt.date] = None, force: bool = False) -> Dict[str, Any]:
    """その日ぶんの定期タスクを、足りない分だけカレンダーに作る。

    何度呼んでも結果は変わらない。/api/tasks から毎回呼んでよい。

    Returns:
        {"date": ..., "created": [件名], "skipped": 既にあった数}
    """
    d = date or today()
    iso = d.isoformat()
    if not force and ledger.get_setting(_RUN_KEY) == iso:
        return {"date": iso, "created": [], "skipped": 0, "cached": True}

    due = due_on(d)
    if not due:
        ledger.set_setting(_RUN_KEY, iso)
        return {"date": iso, "created": [], "skipped": 0}

    # 先に読む。すでにあるものは作らない。
    existing = set()
    try:
        data = list_tasks(days=1)
        for it in data.get("items", []):
            if it.get("date") == iso:
                existing.add((it.get("child", ""), _norm(it.get("summary", ""))))
    except Exception:  # noqa: BLE001
        # 読めないときは作らない。読めないまま作ると二重になる。
        return {"date": iso, "created": [], "skipped": 0, "error": "カレンダーが読めませんでした"}

    wanted = [t for t in due if (t["child"], _norm(t["title"])) not in existing]
    created: List[str] = []
    if wanted:
        items = [
            {
                "title": f"{t['child']}｜{t['title']}",
                "child": t["child"],
                "kind": t.get("kind", "homework"),
                "date": iso,
                "note": "毎日のぶん（みまもりくんが用意）",
            }
            for t in wanted
        ]
        for r in create_events(items, "todo"):
            if r.get("status") == "ok":
                created.append(r["title"])

    ledger.set_setting(_RUN_KEY, iso)
    return {"date": iso, "created": created, "skipped": len(due) - len(wanted)}
