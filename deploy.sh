#!/usr/bin/env bash
# Cloud Run へのデプロイ。事前に .env を埋めてから実行する。
#
# 方針：みまもりくんは外部から来た画像を LLM に食わせるアプリなので、
#       専用プロジェクト + 専用サービスアカウントで隔離する。
#       SA には Vertex AI と Firestore の利用権限を与える。カレンダーへの権限は
#       IAM ではなく「カレンダー側の共有設定」で個別に渡す。
set +x
set -euo pipefail

cd "$(dirname "$0")"
[ -f .env ] || { echo ".env がありません。.env.example をコピーして埋めてください。"; exit 1; }
set -a
# shellcheck disable=SC1091
source .env
set +a

bash scripts/check_deploy_ready.sh

SERVICE="${SERVICE:-mimamorikun}"
REGION="${REGION:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
PROJECT="${GOOGLE_CLOUD_PROJECT}"
SA_NAME="${SA_NAME:-mimamori-run}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

SECRET_NAME="${SECRET_NAME:-mimamori-notify-webhook}"
: "${PROJECT:?GOOGLE_CLOUD_PROJECT を設定してください}"

if ! gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT" >/dev/null 2>&1; then
  echo "SA を確認できません。先に scripts/setup_service_account.sh を実行してください。" >&2
  exit 1
fi
if ! gcloud secrets describe "$SECRET_NAME" --project "$PROJECT" >/dev/null 2>&1; then
  echo "Secret を確認できません。先に scripts/put_secret.sh を実行してください。" >&2
  exit 1
fi
if ! gcloud secrets versions describe latest --secret "$SECRET_NAME" --project "$PROJECT" >/dev/null 2>&1; then
  echo "Secret のバージョンを確認できません。先に scripts/put_secret.sh を実行してください。" >&2
  exit 1
fi
if ! gcloud firestore databases describe --database='(default)' --project "$PROJECT" >/dev/null 2>&1; then
  echo "Firestore を確認できません。先に scripts/setup_service_account.sh を実行してください。" >&2
  exit 1
fi

echo "▶ デプロイ"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --source . \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --set-secrets "MIMAMORI_NOTIFY_WEBHOOK=${SECRET_NAME}:latest" \
  --set-env-vars "^|^GOOGLE_CLOUD_PROJECT=${PROJECT}|GOOGLE_CLOUD_LOCATION=${REGION}|GOOGLE_GENAI_USE_VERTEXAI=TRUE|MIMAMORI_MODEL=${MIMAMORI_MODEL}|MIMAMORI_THINKING_BUDGET=${MIMAMORI_THINKING_BUDGET:-512}|MIMAMORI_CALENDAR_ID=${MIMAMORI_CALENDAR_ID}|MIMAMORI_CHILDREN=${MIMAMORI_CHILDREN}|MIMAMORI_REMINDERS_ALLDAY=${MIMAMORI_REMINDERS_ALLDAY:-360}|MIMAMORI_REMINDERS_TIMED=${MIMAMORI_REMINDERS_TIMED:-${MIMAMORI_REMINDERS:-1200,60}}"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')

cat <<MSG

──────────────────────────────────────────────────────────
 URL: ${URL}

 カレンダー共有（予定の変更権限）はデプロイ前に完了している前提です。
 docs/デプロイ手順.md の「⑤ デプロイ直後の確認」を実施してください。
──────────────────────────────────────────────────────────
MSG
