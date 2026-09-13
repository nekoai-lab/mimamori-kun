"""親への知らせ。

なぜ承認をやめて知らせにしたか（D-62）:
    子が撮ったものを「親が承認するまで出さない」にすると、
    **親が承認を忘れた日は、子のやることが空のまま1日が終わる。**
    子から見れば「出したのに何も起きない」で、次の日から撮らなくなる。
    止めるより、入れてから知らせるほうがいい。間違いは後から消せる。

どこに出すか:
    1. アプリの中（`/board` の帯）— 必ず残る。既定
    2. Webhook（`MIMAMORI_NOTIFY_WEBHOOK`）— Slack / Chat / Pushover など、
       親のスマホに届く先を1本だけ設定できる。設定が無ければ何もしない

**知らせが送れなくても、登録は止めない。** 知らせは添え物であって、本体ではない。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from . import ledger

K_NOTICES = "notices"
MAX_KEEP = 50           # 溜め続けない。古いものから落とす
JST = dt.timezone(dt.timedelta(hours=9))


def notices(unseen_only: bool = False) -> List[Dict[str, Any]]:
    rows = ledger.get_setting(K_NOTICES) or []
    rows = [r for r in rows if isinstance(r, dict)]
    if unseen_only:
        rows = [r for r in rows if not r.get("seen")]
    return sorted(rows, key=lambda r: r.get("at", ""), reverse=True)


def add(kind: str, title: str, body: str = "", items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """知らせを1つ残す。**必ず残す**（Webhook が失敗しても、ここには残る）。"""
    row = {
        "id": uuid.uuid4().hex[:8],
        "kind": kind,
        "title": title,
        "body": body,
        "items": [
            {"id": i.get("id", ""), "title": i.get("title", ""), "date": i.get("date", "")}
            for i in (items or [])
        ],
        "at": dt.datetime.now(JST).isoformat(timespec="seconds"),
        "seen": False,
    }
    rows = (ledger.get_setting(K_NOTICES) or []) + [row]
    ledger.set_setting(K_NOTICES, rows[-MAX_KEEP:])
    _push(row)
    return row


def mark_seen(notice_id: str = "") -> int:
    """見たことにする。id を渡さなければ全部。"""
    rows = ledger.get_setting(K_NOTICES) or []
    n = 0
    for r in rows:
        if notice_id and r.get("id") != notice_id:
            continue
        if not r.get("seen"):
            r["seen"] = True
            n += 1
    ledger.set_setting(K_NOTICES, rows)
    return n


def _push(row: Dict[str, Any]) -> None:
    """設定されていれば、親のスマホに届く先へ1本投げる。失敗しても黙って続ける。"""
    url = os.getenv("MIMAMORI_NOTIFY_WEBHOOK", "").strip()
    if not url:
        return
    lines = [row["title"]]
    if row.get("body"):
        lines.append(row["body"])
    for i in row.get("items", [])[:8]:
        lines.append("・" + i["title"] + "（" + i["date"] + "）")
    text = "\n".join(lines)
    # Slack / Google Chat / Discord / Pushover のどれでも拾える形にしておく
    payload = {"text": text, "message": text, "content": text, "title": row["title"]}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:  # noqa: BLE001
        # 知らせが届かないことより、登録が止まることのほうが困る。
        pass
