レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-28
- 担当エージェント: Claude Code（#16）
- レビュー: PR #17 のUX再確認を `design/inbox/UX_REVIEW.md` に追加（2026-09-28）。R2〜R6は解消、R1の状態確認も失敗する条件が中1件残る。次はR1追補を修正して再確認（ux-pass は未付与）。

<!-- 上限で交代するときは、次のエージェントがこのファイルだけ読めば続きができるように書く -->

## 現状

- ai-dev-harness を適用した直後（2026-09-27）
- 構成図を `docs/architecture/` に追加（#4）。PRODUCT.md を埋め、README を今の状態に合わせた（#6）
- UX 見直し前の画面を `design/screenshots/before/` に（#7）。撮っていて #8・#9 を見つけ、どちらもマージ（#10・#11）
- 台帳を Firestore に（#5 → #13、実装 Codex）。ローカルは既定で JSON（#14 → #15、実装 Codex）。**GCP への反映（deploy.sh）はまだ**
- #16（人ごとの合言葉でログイン）を Claude Code が実装中。ページと /api/* をすべて守る。子どもは自分のぶんだけ。合言葉は tools/set_passcode.py で手元から決める（画面からは決めない）

## やり残し

- #16：PR #17 の UX_REVIEW の指摘対応・再確認（ux-pass）。認証コードは今回のレビューでは変更していない。
- **デプロイ前にやること**（deploy.sh の実行は人が確認してから）
  - [x] ① デプロイ先のプロジェクト作成と課金 → 済（`mimamorikun-family`、番号 932685100691。2026-09-28）
  - `.env`：`GOOGLE_CLOUD_PROJECT=mimamorikun-family` は入れた（2026-09-28）
  - `MIMAMORI_CALENDAR_ID`：人がアプリ専用のカレンダーを作ってから教えてもらう（待ち）。未設定だと本番はサービスアカウント自身のカレンダーに書く
  - `MIMAMORI_REMINDERS`：人は既定の `1200,60` でよいとした（「前の日の夕方と1時間前」のつもり）。ただし終日の予定では前の日の 4:00 と 23:00 になる（終日の予定は 0:00 開始として数えるため）。「前の日の夕方」なら 360（18:00）。どうするか人に確かめる（待ち）
  - `.gcloudignore` に `.gitignore` を取り込む（`asetts/`・`.env.*` などがアップロードされる）
  - 通知の Webhook（Slack の #みまもりくん。ローカルは `.env` の `MIMAMORI_NOTIFY_WEBHOOK` で送信確認済み 2026-09-28）を Secret Manager（mimamorikun-family）に入れ、deploy.sh から Cloud Run に渡す（`--set-secrets MIMAMORI_NOTIFY_WEBHOOK=…:latest`。Secret Manager の API 有効化と、実行用 SA に `roles/secretmanager.secretAccessor` を足す）。値は `--set-env-vars` に入れない
  - 実行後に gcloud の既定プロジェクトを戻す（今は okane-kenko-507122）
- デプロイのあと：本番の台帳（Firestore）に合言葉を入れる（README「4. 合言葉を決める」）、カレンダー共有、Firestore の読み書き確認 → WBS の A-1 を ✅
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」。実環境で確認するまで ✅ にしない
- **ドキュメントの見直しは、UX の塊 A〜F（#19〜#24）がマージされてから1本の PR でまとめてやる**：README・docs/現在地.md・docs/WBS.md・docs/画面設計.md・構成図（docs/architecture/）。**それまでは触らない**（塊の PR と衝突させない。2026-09-28 に人が決めた）

## 次の1手

- #17 の `design/inbox/UX_REVIEW.md` を確認し、R1〜R6を修正または採らない理由を記録する。修正後の主要操作と状態別スクショでUXを再確認する。
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
