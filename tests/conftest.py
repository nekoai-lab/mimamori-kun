"""テストはデモの台帳で動かす。GCP にもカレンダーにも繋がない。

設定は import のときに読まれるので、mimamori を読み込む前に環境変数を決める。
子どもの呼び名はダミー（実名は公開履歴に残さない）。
"""
import os
import sys
from pathlib import Path

os.environ["MIMAMORI_DEMO"] = "1"
os.environ["MIMAMORI_CHILDREN"] = "上の子:junior_high,下の子:elementary"
os.environ.pop("GOOGLE_CLOUD_PROJECT", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
