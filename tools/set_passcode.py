#!/usr/bin/env python3
"""合言葉を決める・変える（#16）。**画面からは決めない。** 手元で動かす。

使い方:
    # ローカルの台帳（.data/ledger.json）に入れる
    python3 tools/set_passcode.py おうちの人
    python3 tools/set_passcode.py 下の子

    # 本番の台帳（Firestore）に入れる。ADC が要る。
    # GOOGLE_CLOUD_QUOTA_PROJECT を GOOGLE_CLOUD_PROJECT と同じ値で export しておく。
    MIMAMORI_LEDGER=firestore GOOGLE_CLOUD_PROJECT=<プロジェクト> python3 tools/set_passcode.py おうちの人

    # すべての端末をログアウトさせる（合言葉を変えたあとなど）
    python3 tools/set_passcode.py --logout-all

人は「おうちの人」か、MIMAMORI_CHILDREN の呼び名。
合言葉は画面に出さずに2回聞く。保存するのはハッシュだけ。
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mimamori import auth, ledger  # noqa: E402
from mimamori.config import validate_quota_project  # noqa: E402


def main(argv: list) -> int:
    if len(argv) != 1:
        print(__doc__.strip())
        return 2
    target = argv[0]
    try:
        validate_quota_project()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"台帳: {ledger.store().kind}")

    if target == "--logout-all":
        print(f"すべての端末をログアウトさせました（世代 {auth.logout_all()}）。")
        return 0

    user = auth.PARENT if target in ("おうちの人", "親", auth.PARENT) else target
    if user not in auth.users():
        print(f"知らない人です: {target}。使えるのは おうちの人・" + "・".join(auth.children()))
        return 1

    first = getpass.getpass(f"{auth.display_name(user)} の合言葉: ")
    again = getpass.getpass("もう一度: ")
    if first != again:
        print("2回の入力が違います。やり直してください。")
        return 1
    try:
        auth.set_passcode(user, first)
    except ValueError as e:
        print(e)
        return 1
    print(f"{auth.display_name(user)} の合言葉を決めました。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
