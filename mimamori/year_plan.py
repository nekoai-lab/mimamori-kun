"""年間行事予定のまとめ取り込み。

なぜコードで書くか:
    年間予定は「1枚の紙に144行」ある。読み取りはモデルに任せてよいが、
    **144件をカレンダーに書くかどうかの判断を、モデルに任せてはいけない。**
    日付と曜日が食い違っていても、モデルはもっともらしく埋めてしまう。
    ここは全部、計算で確かめる。

実物で分かったこと（2026-09-13 / 練馬区立小 令和8年度の予定表テキスト）:
    - **曜日が全行ずれていた（144行すべてが実際の曜日+2日ぶん）**
    - 日付そのものは合っていた（5/6 の振替休日が2026年の並びと一致）
    - ただし一部の祝日の日付が違った（山の日 8/7、敬老の日 9/22 など）
    → 書いてある曜日は信じない。日付から引き直す。
      そのうえで **ズレが多ければ登録を止めて人に見せる。**
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple

WD = "月火水木金土日"

_MONTH = re.compile(r"^\s*(\d{1,2})\s*月\s*$")
_DAY = re.compile(r"^\s*(\d{1,2})\s*日\s*[（(]\s*(.)\s*[）)]\s*(.*)$")
_SKIP = re.compile(r"^\s*(授業日数|学校名|令和|平成)")

# 日付が動かない祝日。資料の検算に使う（ハッピーマンデーと春分・秋分は動くので使わない）。
FIXED_HOLIDAYS = {
    (1, 1): "元日",
    (2, 11): "建国記念の日",
    (2, 23): "天皇誕生日",
    (4, 29): "昭和の日",
    (5, 3): "憲法記念日",
    (5, 4): "みどりの日",
    (5, 5): "こどもの日",
    (8, 11): "山の日",
    (11, 3): "文化の日",
    (11, 23): "勤労感謝の日",
}

# 家（親と子）に関係する予定。既定で登録する。
FAMILY = [
    "保護者会", "面談", "運動会", "学習発表会", "発表会", "遠足", "移動教室", "社会科見学",
    "見学", "始業式", "終業式", "修了式", "卒業式", "入学式", "土曜授業", "引き渡し",
    "就学時健康診断", "給食始", "給食終", "下校", "音楽鑑賞", "心の劇場", "新体力テスト",
    "水泳指導", "交通安全教室", "写生会", "6年生を送る会", "書き初め展", "ゆずり葉",
]
# 校内の運用。子の持ち物も予定も変わらないので、既定では入れない。
SCHOOL = [
    "委員会", "クラブ", "安全指導", "避難訓練", "計測", "検診", "内科", "眼科", "耳鼻科",
    "歯科", "定期健康診断", "地区別協議会", "研鑽", "upweek", "学力補充",
]
# 休み。Google カレンダーの祝日と二重になるので入れない。
# 「〜の日」で拾うと「1学期・終業の日」まで休みになる。祝日は名前で並べる。
HOLIDAY_NAMES = [
    "元日", "成人の日", "建国記念の日", "天皇誕生日", "春分の日", "昭和の日", "憲法記念日",
    "みどりの日", "こどもの日", "海の日", "山の日", "敬老の日", "秋分の日", "スポーツの日",
    "文化の日", "勤労感謝の日", "国民の休日", "都民の日", "開校記念日",
]
HOLIDAY = ["休日", "休業", "休務", "振替"] + HOLIDAY_NAMES


def fiscal_year(today: Optional[dt.date] = None) -> int:
    """年度（4月始まり）を返す。3月までは前の年が年度。"""
    d = today or dt.date.today()
    return d.year if d.month >= 4 else d.year - 1


def _year_for(month: int, fy: int) -> int:
    return fy if month >= 4 else fy + 1


def parse(text: str, fy: Optional[int] = None) -> List[Dict[str, Any]]:
    """「4月」「1日 (金) 始業式」の形を行に分解する。年度から年を補う。"""
    fy = fy if fy is not None else fiscal_year()
    month = None
    rows: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _SKIP.match(line):
            continue
        m = _MONTH.match(line)
        if m:
            month = int(m.group(1))
            continue
        m = _DAY.match(line)
        if not m or month is None:
            continue
        day, wd_label, rest = int(m.group(1)), m.group(2), m.group(3).strip()
        try:
            date = dt.date(_year_for(month, fy), month, day)
        except ValueError:
            rows.append({"date": None, "raw": line, "error": f"{month}月{day}日 は存在しません"})
            continue
        titles = [t.strip() for t in re.split(r"[,、]", rest) if t.strip()]
        rows.append(
            {
                "date": date.isoformat(),
                "weekday_label": wd_label,
                "weekday_real": WD[date.weekday()],
                "titles": titles,
                "raw": line,
            }
        )
    return rows


def classify(title: str) -> str:
    """family（登録する）/ school（既定では入れない）/ holiday（入れない）。"""
    for w in HOLIDAY:
        if w in title:
            return "holiday"
    for w in FAMILY:
        if w in title:
            return "family"
    for w in SCHOOL:
        if w in title:
            return "school"
    return "family"          # 迷ったら見せる。取りこぼすより多い方がまし


def check(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """資料そのものが信用できるかを確かめる。**登録の可否はここで決める。**"""
    dated = [r for r in rows if r.get("date")]
    mismatch = [r for r in dated if r["weekday_label"] != r["weekday_real"]]

    # 全行が同じだけずれているなら、資料の曜日の列がまるごと別の年のもの。
    shifts = {
        (WD.index(r["weekday_label"]) - dt.date.fromisoformat(r["date"]).weekday()) % 7
        for r in dated
        if r["weekday_label"] in WD
    }
    uniform = len(shifts) == 1 and shifts != {0}

    # 日付が動かない祝日で検算する。ここが合わないと、日付自体がずれている。
    holiday_ng = []
    for r in dated:
        for t in r["titles"]:
            for (mm, dd), name in FIXED_HOLIDAYS.items():
                if name in t:
                    d = dt.date.fromisoformat(r["date"])
                    if (d.month, d.day) != (mm, dd):
                        holiday_ng.append({"date": r["date"], "title": t, "should_be": f"{mm}/{dd}"})

    # 同じ行事が近い日に二度出ていないか。紙の予定表では珍しくない写し間違い。
    seen: Dict[str, str] = {}
    dup = []
    for r in dated:
        for t in r["titles"]:
            # 休みや校内運用は同じ名前が何度も出るのが普通。見るのは家に関わるものだけ。
            if classify(t) != "family":
                continue
            key = re.sub(r"[\s・（）()]", "", t)
            if not key:
                continue
            prev = seen.get(key)
            if prev and 0 < (dt.date.fromisoformat(r["date"]) - dt.date.fromisoformat(prev)).days <= 14:
                dup.append({"title": t, "dates": [prev, r["date"]]})
            seen[key] = r["date"]

    rate = round(len(mismatch) * 100 / len(dated)) if dated else 0
    ok = rate < 10 and not holiday_ng

    notes = []
    if uniform:
        s = shifts.pop()
        notes.append(f"**曜日が全行そろって {s} 日ぶんずれています。** 別の年度の曜日が入っている可能性が高いです。")
    elif mismatch:
        notes.append(f"曜日が合わない行が {len(mismatch)} 件あります（全体の {rate}%）。")
    if holiday_ng:
        names = "、".join(f"{h['title']}（{h['date'][5:]}→{h['should_be']}）" for h in holiday_ng[:4])
        notes.append(f"日付が動かないはずの祝日がずれています: {names}。**日付そのものが疑わしいです。**")
    if dup:
        notes.append("同じ行事が近い日に二度出ています: "
                     + "、".join(f"{d['title']}（{d['dates'][0][5:]}と{d['dates'][1][5:]}）" for d in dup[:3]))
    if ok and not notes:
        notes.append("日付と曜日は合っています。")

    return {
        "rows": len(rows),
        "dated": len(dated),
        "mismatch": len(mismatch),
        "mismatch_rate": rate,
        "uniform_shift": uniform,
        "holiday_ng": holiday_ng,
        "duplicates": dup,
        "ok": ok,
        "notes": notes,
        "examples": [
            {"date": r["date"], "label": r["weekday_label"], "real": r["weekday_real"],
             "title": "、".join(r["titles"])}
            for r in mismatch[:5]
        ],
    }


def to_items(rows: List[Dict[str, Any]], child: str, levels: Tuple[str, ...] = ("family",)) -> List[Dict[str, Any]]:
    """カレンダーに入れる形にする。**曜日は資料のものを捨て、日付から引き直す。**"""
    items = []
    for r in rows:
        if not r.get("date"):
            continue
        for t in r["titles"]:
            if classify(t) not in levels:
                continue
            items.append(
                {
                    "title": f"{child}｜{t}",
                    "child": child,
                    "kind": "event",
                    "date": r["date"],
                    "note": "年間行事予定より（みまもりくんが取り込み）",
                    "source_text": r["raw"],
                }
            )
    return items


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """どれを入れてどれを入れないかを、数で見せる。"""
    out = {"family": 0, "school": 0, "holiday": 0}
    for r in rows:
        for t in r.get("titles", []):
            out[classify(t)] += 1
    return out
