"""人ごとの合言葉と、署名付き Cookie（#16）。

だれが使っているかを、端末の「だれ？」ではなくログインで決める。
    - 親・子どもそれぞれに合言葉。入れたら署名付き Cookie（180日）で端末に覚えさせる
    - 子どもは自分のぶんだけ。親は全部

**秘密は環境変数にもリポジトリにも置かない。** すべて台帳の settings に置く
（本番は Firestore、ローカルは JSON）。
    - 合言葉は scrypt（ソルトつき）のハッシュだけ
    - Cookie の署名の鍵は、最初に要ったときに乱数で作る
    - 「世代」を進めると、それより前に出した Cookie がすべて無効になる（全端末のログアウト）

合言葉は画面からは決めない（URL は公開なので、最初に開いた人が決められてしまう）。
手元で tools/set_passcode.py を使う。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from . import ledger
from .config import config

COOKIE = "mimamori_session"
MAX_AGE = 180 * 24 * 3600          # 180日
PARENT = "parent"
MIN_LENGTH = 4
MAX_FAILS = 5                      # 続けて5回間違えたら
LOCK_SECONDS = 15 * 60             # 15分ロック

K_USERS, K_SECRET, K_EPOCH, K_FAILS = "auth_users", "auth_secret", "auth_epoch", "auth_fails"
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}

_LEVEL_LABEL = {"junior_high": "中学生", "elementary": "小学生"}


def _now() -> float:
    return time.time()


def enabled() -> bool:
    """ログインを求めるか。**Cloud Run では必ず求める。** ローカルだけ MIMAMORI_AUTH=off で外せる。"""
    if "K_SERVICE" in os.environ:
        return True
    return os.getenv("MIMAMORI_AUTH", "on").strip().lower() != "off"


# ------------------------------------------------------------------ 人

def children() -> List[str]:
    return [c["name"] for c in config.children]


def users() -> List[str]:
    return [PARENT] + children()


def is_parent(user: Optional[str]) -> bool:
    return user == PARENT


def display_name(user: str) -> str:
    return "おうちの人" if is_parent(user) else user


def login_choices() -> List[Dict[str, Any]]:
    """ログイン画面に出す選択肢。**子どもの呼び名は出さない**（ログイン前の画面は誰でも開ける）。

    id は "parent" と "c0" "c1"…。呼び名の代わりに学齢で見せる。
    """
    out = [{"id": PARENT, "label": "おうちの人", "ready": has_passcode(PARENT)}]
    seen: Dict[str, int] = {}
    for i, c in enumerate(config.children):
        base = _LEVEL_LABEL.get(c.get("school_level", ""), "子ども")
        seen[base] = seen.get(base, 0) + 1
        out.append({"id": f"c{i}", "label": base, "ready": has_passcode(c["name"])})
    # 同じ学齢が2人以上いるときだけ番号を付ける
    for base, n in seen.items():
        if n > 1:
            k = 0
            for o in out:
                if o["label"] == base:
                    k += 1
                    o["label"] = f"{base}（{k}）"
    return out


def user_from_choice(choice_id: str) -> Optional[str]:
    if choice_id == PARENT:
        return PARENT
    if choice_id.startswith("c") and choice_id[1:].isdigit():
        i = int(choice_id[1:])
        names = children()
        if 0 <= i < len(names):
            return names[i]
    return None


# ------------------------------------------------------------------ 合言葉

def _hash(passcode: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passcode.encode("utf-8"), salt=salt, **_SCRYPT)


def _records() -> Dict[str, Any]:
    return dict(ledger.get_setting(K_USERS) or {})


def has_passcode(user: str) -> bool:
    return user in _records()


def set_passcode(user: str, passcode: str) -> None:
    """合言葉を決める（手元の tools/set_passcode.py から呼ぶ）。ハッシュだけを残す。"""
    if user not in users():
        raise ValueError(f"知らない人です: {user}")
    if len(passcode) < MIN_LENGTH:
        raise ValueError(f"合言葉は {MIN_LENGTH} 文字以上にしてください。")
    salt = secrets.token_bytes(16)
    recs = _records()
    recs[user] = {
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(_hash(passcode, salt)).decode(),
        "set_at": int(_now()),
    }
    ledger.set_setting(K_USERS, recs)
    _secret()                      # 署名の鍵も、ここで作っておく（起動した台数ぶん作られないように）
    _clear_fails(user)


# ------------------------------------------------------------------ 間違いの回数とロック
#
# **人ごとに別の記録にして、1回ずつ原子的に数える**（台帳の transact_setting）。
# 同時に何回試しても回数が消えないように、また別の人の書き込みでロックが消えないように。
# さらに、**合言葉を比べる前に「1回ぶん」を確保する**。並列で投げても、ロックまでに比べるのは MAX_FAILS 回だけ。

def _fail_key(user: str) -> str:
    return f"{K_FAILS}:{user}"


def _clear_fails(user: str) -> None:
    ledger.set_setting(_fail_key(user), {})


def locked_seconds(user: str) -> int:
    until = float((ledger.get_setting(_fail_key(user)) or {}).get("until") or 0)
    return max(0, int(until - _now() + 0.999))


def _reserve(user: str) -> Tuple[bool, Dict[str, Any]]:
    """比べてよいか。よければ回数を1つ進めて True。ロック中・使い切ったなら False（使い切ったらロックする）。"""
    decision = {"ok": False}

    def step(row):
        row = dict(row or {})
        now = _now()
        until = float(row.get("until") or 0)
        if until > now:
            decision["ok"] = False
            return row
        if until:                               # ロックが明けた
            row = {}
        count = int(row.get("count") or 0)
        if count >= MAX_FAILS:                  # もう5回ぶん使っている（同時に投げられた分も含む）
            decision["ok"] = False
            return {"count": 0, "until": now + LOCK_SECONDS}
        decision["ok"] = True
        return {"count": count + 1}

    row = ledger.transact_setting(_fail_key(user), step)
    return decision["ok"], row


def _lock_now(user: str) -> None:
    ledger.transact_setting(_fail_key(user), lambda row: {"count": 0, "until": _now() + LOCK_SECONDS})


def check(user: str, passcode: str) -> Tuple[str, int]:
    """合言葉を確かめる。返りは (結果, 数)。

    結果: "ok" / "wrong"（数＝あと何回で止まるか）/ "locked"（数＝あと何秒）/ "unset" / "unknown"
    """
    if user not in users():
        return "unknown", 0
    rec = _records().get(user)
    if not rec:
        return "unset", 0
    allowed, row = _reserve(user)
    if not allowed:
        return "locked", max(1, locked_seconds(user))
    salt = base64.b64decode(rec["salt"])
    if hmac.compare_digest(_hash(passcode, salt), base64.b64decode(rec["hash"])):
        _clear_fails(user)
        return "ok", 0
    used = int(row.get("count") or 0)
    if used >= MAX_FAILS:
        _lock_now(user)
        return "locked", LOCK_SECONDS
    return "wrong", MAX_FAILS - used


# ------------------------------------------------------------------ Cookie

def _secret() -> bytes:
    s = ledger.get_setting(K_SECRET)
    if not s:
        s = secrets.token_hex(32)
        ledger.set_setting(K_SECRET, s)
    return bytes.fromhex(s)


def epoch() -> int:
    return int(ledger.get_setting(K_EPOCH) or 0)


def logout_all() -> int:
    """世代を1つ進める。これより前に出した Cookie は、どの端末のものも使えなくなる。"""
    nxt = epoch() + 1
    ledger.set_setting(K_EPOCH, nxt)
    return nxt


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(user: str) -> str:
    body = _b64(json.dumps({"u": user, "e": epoch(), "x": int(_now()) + MAX_AGE},
                           ensure_ascii=False, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token: Optional[str]) -> Optional[str]:
    """正しい Cookie ならその人を返す。署名・期限・世代・人のどれかが合わなければ None。"""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    try:
        data = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(data.get("x") or 0) <= _now():
        return None
    if int(data.get("e", -1)) != epoch():
        return None
    user = data.get("u")
    return user if user in users() else None
