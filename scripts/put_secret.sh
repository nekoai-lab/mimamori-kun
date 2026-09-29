#!/bin/bash
# 値は人が端末で入力する。引数・環境変数・一時ファイルに載せない。
set +x
set -euo pipefail
: "${PROJECT:?PROJECT を設定してください}"
: "${SERVICE_ACCOUNT:?SERVICE_ACCOUNT を設定してください}"
[ "$#" = 1 ] || { printf '使い方: scripts/put_secret.sh <名前>\n' >&2; exit 1; }
[ -t 0 ] || { printf '端末から人が入力してください\n' >&2; exit 1; }
SECRET_NAME="$1"
unset SECRET_VALUE
trap 'unset SECRET_VALUE' EXIT
if ! gcloud secrets describe "$SECRET_NAME" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET_NAME" --replication-policy automatic --project "$PROJECT" >/dev/null 2>&1
fi
printf '秘密の値を入力してください: ' >&2
IFS= read -r -s SECRET_VALUE
printf '\n' >&2
[ -n "$SECRET_VALUE" ] || { printf '空の値は登録しません\n' >&2; exit 1; }
printf '%s' "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" \
  --project "$PROJECT" --data-file=- >/dev/null 2>&1
unset SECRET_VALUE
gcloud secrets add-iam-policy-binding "$SECRET_NAME" --project "$PROJECT" \
  --member "serviceAccount:${SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com" \
  --role roles/secretmanager.secretAccessor >/dev/null 2>&1
printf 'Secret の登録と読み取り権限の付与が完了しました\n'
