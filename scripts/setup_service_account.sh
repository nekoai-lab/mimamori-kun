#!/bin/bash
set +x
set -euo pipefail
: "${PROJECT:?PROJECT を設定してください}"
: "${SERVICE_ACCOUNT:?SERVICE_ACCOUNT を設定してください}"
gcloud iam service-accounts describe "${SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com" \
  --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SERVICE_ACCOUNT" --project "$PROJECT" >/dev/null 2>&1
printf 'サービスアカウントを用意しました。必要なカレンダー共有などを人が済ませてください。\n'
