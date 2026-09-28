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

- #16：PR #17 の UX_REVIEW 再確認の R1追補（back も me も失敗したとき）を直した。ChatGPT の再確認のあと ux-pass（人が頼む）
- **デプロイ前にやること**（deploy.sh の実行は人が確認してから）
  - [x] ① デプロイ先のプロジェクト作成と課金 → 済（`mimamorikun-family`、番号 932685100691。2026-09-28）
  - `.env`：`GOOGLE_CLOUD_PROJECT=mimamorikun-family` は入れた（2026-09-28）
  - [x] `.env` に `MIMAMORI_CALENDAR_ID`（アプリ専用のカレンダー）を入れた（2026-09-28）
  - リマインダー：終日と時刻つきを分ける（Issue #31、実装 Codex）。終日は `MIMAMORI_REMINDERS_ALLDAY=360`（前の日 18:00）、時刻つきは `MIMAMORI_REMINDERS_TIMED=1080,60`（`MIMAMORI_REMINDERS` は時刻つきの既定として残す）。**#31 がマージされてから `.env` に2つを入れる**（人が決めた。2026-09-28。`1200,60` はやめた）
  - `.gcloudignore` に `.gitignore` を取り込む（`asetts/`・`.env.*` などがアップロードされる）
  - 通知の Webhook（Slack の #みまもりくん。ローカルは `.env` の `MIMAMORI_NOTIFY_WEBHOOK` で送信確認済み 2026-09-28）を Secret Manager（mimamorikun-family）に入れ、deploy.sh から Cloud Run に渡す（`--set-secrets MIMAMORI_NOTIFY_WEBHOOK=…:latest`。Secret Manager の API 有効化と、実行用 SA に `roles/secretmanager.secretAccessor` を足す）。値は `--set-env-vars` に入れない
  - 実行後に gcloud の既定プロジェクトを戻す（今は okane-kenko-507122）
  - **デプロイのあとにやること**：カレンダーの共有に、deploy.sh が最後に表示するサービスアカウント（`mimamori-run@mimamorikun-family.iam.gserviceaccount.com`）を「予定の変更権限」で追加する（人がやる。しないと登録が 404 で落ちる）
- デプロイのあと：本番の台帳（Firestore）に合言葉を入れる（README「4. 合言葉を決める」）、カレンダー共有（上）、Firestore の読み書き確認 → WBS の A-1 を ✅
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」。実環境で確認するまで ✅ にしない
- **ドキュメントの見直しは、UX の塊 A〜F（#19〜#24）がマージされてから1本の PR でまとめてやる**：README・docs/現在地.md・docs/WBS.md・docs/画面設計.md・構成図（docs/architecture/）。**それまでは触らない**（塊の PR と衝突させない。2026-09-28 に人が決めた）

## 次の1手

- #17 は R1追補を直して qa-pass 待ち → ChatGPT の再確認 → ux-pass → マージ → 塊 A・C・D・F
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
