レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-28
- 担当エージェント: Claude Code（#16）
- レビュー: #16 の PR を Codex がレビュー（request-qa）。UI の変更なので ux-pass も要る（ChatGPT の UX_REVIEW 待ち）

<!-- 上限で交代するときは、次のエージェントがこのファイルだけ読めば続きができるように書く -->

## 現状

- ai-dev-harness を適用した直後（2026-09-27）
- 構成図を `docs/architecture/` に追加（#4）。PRODUCT.md を埋め、README を今の状態に合わせた（#6）
- UX 見直し前の画面を `design/screenshots/before/` に（#7）。撮っていて #8・#9 を見つけ、どちらもマージ（#10・#11）
- 台帳を Firestore に（#5 → #13、実装 Codex）。ローカルは既定で JSON（#14 → #15、実装 Codex）。**GCP への反映（deploy.sh）はまだ**
- #16（人ごとの合言葉でログイン）を Claude Code が実装中。ページと /api/* をすべて守る。子どもは自分のぶんだけ。合言葉は tools/set_passcode.py で手元から決める（画面からは決めない）

## やり残し

- #16：PR・Codex のレビュー・ChatGPT の UX レビュー（ux-pass）
- deploy.sh の前に：デプロイ先のプロジェクト作成と課金、`.env` に `GOOGLE_CLOUD_PROJECT`・`MIMAMORI_CALENDAR_ID`・`MIMAMORI_REMINDERS`、`.gcloudignore` に `.gitignore` を取り込む（`asetts/`・`.env.*` などがアップロードされる）、実行後に gcloud の既定プロジェクトを戻す
- デプロイのあと：本番の台帳（Firestore）に合言葉を入れる（README「4. 合言葉を決める」）、カレンダー共有、Firestore の読み書き確認 → WBS の A-1 を ✅
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」。実環境で確認するまで ✅ にしない

## 次の1手

- #16 の PR を出して request-qa（Codex）、スクショを ChatGPT に渡して UX_REVIEW をもらう
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
