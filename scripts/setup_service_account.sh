#!/usr/bin/env bash
# 人が実行する。PROJECT と REGION は docs/デプロイ手順.md の準備で設定する。
set +x
set -euo pipefail
: "${PROJECT:?PROJECT を設定してください}"
: "${REGION:?REGION を設定してください}"
SA_NAME="${SA_NAME:-mimamori-run}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
trap 'printf "準備に失敗しました。API・実行者の権限を確認してください。\n" >&2' ERR

gcloud services enable run.googleapis.com aiplatform.googleapis.com \
  firestore.googleapis.com calendar-json.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iam.googleapis.com secretmanager.googleapis.com \
  --project "$PROJECT" >/dev/null 2>&1

gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
    --display-name="みまもりくん Cloud Run 実行用" >/dev/null 2>&1
for role in roles/aiplatform.user roles/datastore.user; do
  gcloud projects add-iam-policy-binding "$PROJECT" --project "$PROJECT" \
    --member="serviceAccount:${SA_EMAIL}" --role="$role" --condition=None >/dev/null 2>&1
done

# 初回公開前に、本番の台帳へ合言葉を登録できるようにする。
gcloud firestore databases describe --database='(default)' --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud firestore databases create --database='(default)' --project "$PROJECT" \
    --location="$REGION" --type=firestore-native >/dev/null 2>&1

printf 'カレンダーの共有に追加するアドレス（予定の変更権限）:\n%s\n' "$SA_EMAIL"
