#!/usr/bin/env bash
# Cloud Run へのデプロイ。事前に .env を埋めてから実行する。
#
# 方針：みまもりくんは外部から来た画像を LLM に食わせるアプリなので、
#       専用プロジェクト + 専用サービスアカウントで隔離する。
#       SA には Vertex AI を呼ぶ権限しか与えない。カレンダーへの権限は
#       IAM ではなく「カレンダー側の共有設定」で個別に渡す。
set -euo pipefail

cd "$(dirname "$0")"
[ -f .env ] || { echo ".env がありません。.env.example をコピーして埋めてください。"; exit 1; }
set -a; source .env; set +a

SERVICE="${SERVICE:-mimamorikun}"
REGION="${REGION:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
PROJECT="${GOOGLE_CLOUD_PROJECT}"
SA_NAME="${SA_NAME:-mimamori-run}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

echo "▶ project=$PROJECT  region=$REGION  service=$SERVICE"
gcloud config set project "$PROJECT" >/dev/null

echo "▶ 必要な API を有効化"
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  calendar-json.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com

echo "▶ 専用サービスアカウントを用意（既にあればそのまま）"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="みまもりくん Cloud Run 実行用" \
    --description="Vertex AI の呼び出しのみ。カレンダー権限はカレンダー側の共有設定で渡す"

echo "▶ Vertex AI を呼ぶ権限だけ付与"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" \
  --condition=None >/dev/null

echo "▶ デプロイ"
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=TRUE,MIMAMORI_MODEL=${MIMAMORI_MODEL},MIMAMORI_CALENDAR_ID=${MIMAMORI_CALENDAR_ID},MIMAMORI_CHILDREN=${MIMAMORI_CHILDREN},MIMAMORI_REMINDERS=${MIMAMORI_REMINDERS}"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')

cat <<MSG

──────────────────────────────────────────────────────────
 URL: ${URL}

 最後にひとつ。Google カレンダーを開いて、
   対象カレンダーの設定 → 「特定のユーザーやグループとの共有」
 に次のアドレスを 【予定の変更権限】 で追加してください。

   ${SA_EMAIL}

 これをやらないと、登録時に 404 で落ちます。
 逆に言うと、この共有を外せばアプリはカレンダーに触れなくなります。
──────────────────────────────────────────────────────────
MSG
