"""子ごとの設定（見た目・相棒・学年と読み）の読み書き（UX 塊 F・design/UX_SPEC.md §3.3・§3.7・§4.3）。

塊 A（appearance.js の AppearanceStore／CompanionStore）・B（/kid の相棒の名前）・D（/board の学年とふりがな）・
G（kid_agent の相棒の呼び名と文体）・H（reading.js の読み補助）がこの設定を使う。

- 保存先は台帳の設定（ledger）。子ごとに1つの値 `child_settings:<子>` にまとめ、
  **送った項目だけを変える**（テーマを書いても名前・学年は消えない。その逆も同じ）
- 書き換えは ledger.transact_setting で行う（同じ子の設定を2つの端末から同時に書いても、片方が消えない）
- 子どもが変えられるのは自分の見た目（テーマ）と相棒の名前だけ。学年・漢字の範囲・ふりがな・文体は親だけ（#24）
- 値は形を確かめてから保存する。知らない項目・形の違う値は受け取らない（画面の自由入力を設定として通さない）
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Dict, Iterable, Optional

from mimamori import ledger

THEMES = ("rocket-lab", "monochrome", "snow-bird")
THEME_SCHEMA_VERSION = 1
GRADES = ("e1", "e2", "e3", "e4", "e5", "e6", "j1", "j2", "j3")
NAME_MAX = 12

# 子どもが自分で変えてよい項目（#24）。これ以外は親だけ
CHILD_FIELDS = frozenset({"theme_id", "theme_schema_version", "companion_name"})


class SettingError(ValueError):
    """受け取れない値。画面には message をそのまま出してよい（値そのものは含めない）。"""


def _key(child: str) -> str:
    return "child_settings:" + child


# ---------------------------------------------------------------- 値の確かめ（None は「消して既定に戻す」）

def _theme_id(v: Any) -> Optional[str]:
    if v is None or v in THEMES:
        return v
    raise SettingError("theme_id は rocket-lab・monochrome・snow-bird のどれかです。")


def _schema(v: Any) -> Optional[int]:
    if v is None or (isinstance(v, int) and not isinstance(v, bool) and v == THEME_SCHEMA_VERSION):
        return v
    raise SettingError(f"theme_schema_version は {THEME_SCHEMA_VERSION} です。")


def _name(v: Any) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise SettingError("companion_name は文字で送ってください。")
    v = unicodedata.normalize("NFKC", v).strip()
    if not v:
        return None                                  # 空なら既定（まる）に戻す
    if len(v) > NAME_MAX or any(unicodedata.category(c).startswith("C") for c in v) or re.search(r"[<>{}\\]", v):
        raise SettingError(f"companion_name は {NAME_MAX} 文字までで、記号 < > {{ }} \\ は使えません。")
    return v


def _choice(field: str, allowed: Iterable[str]) -> Callable[[Any], Optional[str]]:
    allowed = tuple(allowed)

    def check(v: Any) -> Optional[str]:
        if v is None or v in allowed:
            return v
        raise SettingError(f"{field} は {'・'.join(allowed)} のどれかです。")
    return check


def _kanji_list(v: Any) -> Optional[list]:
    if v is None:
        return None
    if not isinstance(v, list) or len(v) > 300 or not all(isinstance(c, str) and len(c) == 1 and "一" <= c <= "鿿" for c in v):
        raise SettingError("known_kanji_overrides は漢字1字ずつの一覧（300字まで）です。")
    return sorted(set(v), key=v.index)


def _word_list(v: Any) -> Optional[list]:
    if v is None:
        return None
    if not isinstance(v, list) or len(v) > 100 or not all(isinstance(w, str) and 0 < len(w) <= 20 and not re.search(r"[<>{}\\]", w) for w in v):
        raise SettingError("ruby_word_overrides は語の一覧（100語まで、1語20文字まで）です。")
    return sorted(set(v), key=v.index)


FIELDS: Dict[str, Callable[[Any], Any]] = {
    "theme_id": _theme_id,
    "theme_schema_version": _schema,
    "companion_name": _name,
    "companion_language_level": _choice("companion_language_level", ("easy", "standard")),
    "school_grade": _choice("school_grade", GRADES),
    "kanji_scope": _choice("kanji_scope", ("previous_grade", "current_grade")),
    "ruby_mode": _choice("ruby_mode", ("auto", "all")),
    "known_kanji_overrides": _kanji_list,
    "ruby_word_overrides": _word_list,
}


def clean(values: Dict[str, Any], *, parent: bool) -> Dict[str, Any]:
    """送られた項目を確かめる。知らない項目・親だけの項目を子どもが送ったときは SettingError／PermissionError。"""
    unknown = sorted(set(values) - set(FIELDS))
    if unknown:
        raise SettingError("知らない項目です：" + "・".join(unknown))
    if not parent:
        denied = sorted(set(values) - CHILD_FIELDS)
        if denied:
            raise PermissionError("おうちの人だけが変えられる項目です：" + "・".join(denied))
    return {k: FIELDS[k](v) for k, v in values.items()}


# ---------------------------------------------------------------- 読み書き

def read(child: str) -> Dict[str, Any]:
    """保存されている項目だけを返す（未設定の項目は含めない）。壊れた値は読まない。"""
    raw = ledger.get_setting(_key(child), {}) or {}
    out: Dict[str, Any] = {}
    if isinstance(raw, dict):
        for k, check in FIELDS.items():
            if k in raw and raw[k] is not None:
                try:
                    v = check(raw[k])
                except SettingError:
                    continue                          # 古い形・壊れた値は無いものとして扱う（既定に戻る）
                if v is not None:
                    out[k] = v
    return out


def write(child: str, values: Dict[str, Any], *, parent: bool) -> Dict[str, Any]:
    """送った項目だけを変えて、保存後の設定を返す。None を送った項目は消す（既定に戻る）。"""
    changes = clean(values, parent=parent)

    def apply(current: Any) -> Dict[str, Any]:
        base = dict(current) if isinstance(current, dict) else {}
        for k, v in changes.items():
            if v is None:
                base.pop(k, None)
            else:
                base[k] = v
        if "theme_id" in base:
            base["theme_schema_version"] = THEME_SCHEMA_VERSION
        return base

    ledger.transact_setting(_key(child), apply)
    return read(child)


def reading_policy(settings: Dict[str, Any]) -> Dict[str, Any]:
    """塊 H の Reading.render に渡す形（static/reading.js の policy）。未設定は H の既定に任せる。"""
    return {
        "school_grade": settings.get("school_grade"),
        "kanji_scope": settings.get("kanji_scope", "previous_grade"),
        "ruby_mode": settings.get("ruby_mode", "auto"),
        "known_kanji_overrides": list(settings.get("known_kanji_overrides", [])),
        "ruby_word_overrides": list(settings.get("ruby_word_overrides", [])),
    }


def companion_settings(child: str) -> Dict[str, Any]:
    """塊 G（kid_agent）がサーバー側で読む相棒の名前・文体。未設定の項目は含めない（既定は G が補う）。"""
    s = read(child)
    return {k: s[k] for k in ("companion_name", "companion_language_level") if k in s}
