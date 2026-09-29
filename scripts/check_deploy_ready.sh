#!/bin/bash
# リポジトリ直下で実行。Python 3 標準ライブラリのみ（macOS / Ubuntu）。
set -eu
exec python3 "$(dirname "$0")/../.claude/hooks/gcloud-policy.py" --check "$PWD"
