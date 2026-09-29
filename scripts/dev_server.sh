#!/bin/bash
# 手元専用。値や source の診断（値を含みうる）を表示しない。
set +x
set -eu
cd "$(dirname "$0")/.."
if [[ ${MIMAMORI_LEDGER+x} ]]; then
  echo 'MIMAMORI_LEDGER を外してから起動してください。' >&2
  exit 1
fi
if [[ -f .env ]]; then
  set -a
  if ! source .env >/dev/null 2>&1; then
    echo '.env を読み込めませんでした。' >&2
    exit 1
  fi
  set +a
fi
if [[ ${MIMAMORI_LEDGER+x} || ${K_SERVICE+x} ]]; then
  echo 'ローカル JSON 台帳で起動できない設定があります。' >&2
  exit 1
fi
if [[ -z "${GOOGLE_CLOUD_PROJECT:-}" || "${GOOGLE_CLOUD_QUOTA_PROJECT:-}" != "$GOOGLE_CLOUD_PROJECT" ]]; then
  echo 'GOOGLE_CLOUD_QUOTA_PROJECT を GOOGLE_CLOUD_PROJECT と同じに設定してください。' >&2
  exit 1
fi
export GOOGLE_GENAI_USE_VERTEXAI=TRUE
export GOOGLE_CLOUD_LOCATION=us-central1
export MIMAMORI_DEMO=1
unset GOOGLE_API_KEY GEMINI_API_KEY MIMAMORI_NOTIFY_WEBHOOK MIMAMORI_CALENDAR_ID
exec .venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8080
