#!/usr/bin/env python3
"""実物の画面写真で、読み取りが期待どおりかを確かめる。

使い方:
    GOOGLE_CLOUD_PROJECT=... python3 tools/check_extract.py

材料は **Git に入れない**（学校名・組・氏名が写るため）。
    asetts/下のこPCキャプチャ画像/*.HEIC   … 実物の写真
    asetts/expected/連絡ちょう.json         … 期待する読み取り結果

材料が無ければ何もせずに終わる。公開リポジトリでも壊れないようにするため。

期待の書き方（1ファイル1エントリ）:
    "IMG_1433.HEIC": {
      "date": "2026-09-12",            # この日付の項目が出ること
      "homework_contains": [["音読カード"], ["かん字ドリル", "書く"]],
      "bring_contains": ["ランチョンマット", "マスク"],
      "bring_items": 1,                # 持ち物は1件にまとまっていること
      "must_not_contain": ["どうとく"], # 時間割などを拾っていないこと
      "needs_review_contains": ["絵のぐ"]
    }
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IMAGES = ROOT / "asetts" / "下のこPCキャプチャ画像"
EXPECTED = ROOT / "asetts" / "expected" / "連絡ちょう.json"


def _all_text(item: dict) -> str:
    return " ".join(
        str(item.get(k, "")) for k in ("title", "note", "source_text")
    ) + " " + "、".join(item.get("bring") or [])


def judge(result: dict, exp: dict) -> list:
    """期待と突き合わせる。**通らなかった理由を、人が読める文で返す。**"""
    ng = []
    items = result.get("items", [])
    text = " ".join(_all_text(i) for i in items)

    if exp.get("date") and not any(i.get("date") == exp["date"] for i in items):
        ng.append(f"日付 {exp['date']} の項目が無い（出たのは {sorted({i.get('date') for i in items})}）")

    for words in exp.get("homework_contains", []):
        hit = [i for i in items if i.get("kind") == "homework" and all(w in _all_text(i) for w in words)]
        if not hit:
            ng.append("宿題が拾えていない: " + "＋".join(words))

    brings = [i for i in items if i.get("kind") == "bring"]
    if "bring_items" in exp and len(brings) != exp["bring_items"]:
        ng.append(f"持ち物は {exp['bring_items']}件にまとめたい（実際 {len(brings)}件）")
    for w in exp.get("bring_contains", []):
        if not any(w in _all_text(i) for i in brings):
            ng.append(f"持ち物に「{w}」が無い")

    for w in exp.get("must_not_contain", []):
        if w in text:
            ng.append(f"拾ってはいけないものが入っている: 「{w}」")

    for w in exp.get("needs_review_contains", []):
        hit = [i for i in items if w in _all_text(i)]
        if hit and not any(i.get("needs_review") for i in hit):
            ng.append(f"「{w}」は条件つきなので needs_review を立てたい")
    return ng


async def main() -> int:
    if not EXPECTED.exists() or not IMAGES.exists():
        print(f"材料がありません（{EXPECTED} / {IMAGES}）。何もしません。")
        return 0
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        print("GOOGLE_CLOUD_PROJECT が無いので読み取りは試せません。期待だけ読み込みます。")
        print(json.dumps(json.loads(EXPECTED.read_text()), ensure_ascii=False, indent=1)[:400])
        return 0

    from mimamori.agent import read_otayori
    from mimamori.images import normalize

    expected = json.loads(EXPECTED.read_text())
    bad = 0
    for name, exp in expected.items():
        path = IMAGES / name
        if not path.exists():
            print(f"× {name}: ファイルがありません")
            bad += 1
            continue
        data, ct = normalize(path.read_bytes(), "")
        result = await read_otayori(data, ct)
        ng = judge(result, exp)
        if ng:
            bad += 1
            print(f"× {name}")
            for n in ng:
                print("   -", n)
            print("   読み取り:", json.dumps(result["items"], ensure_ascii=False)[:500])
        else:
            print(f"○ {name}（{len(result['items'])}件）")
    print(f"\n{len(expected) - bad}/{len(expected)} 通過")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
