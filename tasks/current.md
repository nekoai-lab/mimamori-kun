レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-28
- 担当エージェント: Claude Code（A の結合（2）・F・C）
- レビュー: UX レビューは PR ごとに `design/reviews/PR-<番号>.md`、`design/UX_REVIEW.md` は目次（2026-09-28 に人が決めた）。#17・#28・#29・#34・#35・#36 は最新判定が ux-pass でよい。UX レビューの担当は `tasks/current.md` を変えない（書き込むのは `design/inbox/UX_REVIEW.md` だけ。UX_RULES.md・CLAUDE.md に明記）

<!-- 上限で交代するときは、次のエージェントがこのファイルだけ読めば続きができるように書く -->

## 現状

- ai-dev-harness を適用した直後（2026-09-27）
- 構成図を `docs/architecture/` に追加（#4）。PRODUCT.md を埋め、README を今の状態に合わせた（#6）
- UX 見直し前の画面を `design/screenshots/before/` に（#7）。撮っていて #8・#9 を見つけ、どちらもマージ（#10・#11）
- 台帳を Firestore に（#5 → #13、実装 Codex）。ローカルは既定で JSON（#14 → #15、実装 Codex）。**GCP への反映（deploy.sh）はまだ**
- ログイン（#16 → #17）をマージ。ページと /api/* をすべて守る。子どもは自分のぶんだけ。合言葉は tools/set_passcode.py で手元から決める（画面からは決めない）。子どもの端末で親に一時的に切り替え（10分で戻る）
- UX の塊：G（#27）・H（#30）・B（#28）・E（#29）をマージ。リマインダーを終日と時刻つきで分けた（#32）
- 塊 A（#34、見た目の共通基盤：3テーマ×明暗・ナビ・見た目の選択シート・プロフィール）・D（#35、親の一覧）・A の結合（#36、見出しの書体・ログアウトの強弱・「暗く」の位置）をマージ。main のテストは 472件通過（2026-09-28、c359d3c）
  - 見た目の保存はまだ（塊 F）。いまは「この画面では変えたけれど、まだ覚えられていないよ」と出す。F は A が決めた口（`GET/POST /api/child-settings`、部分更新。#24 にコメント）で作る
  - /board の再確認のために `GET /api/status?event_id=`（親だけ）を足した（#35）

## やり残し

- **次は A の結合（2）→ F（#24）→ C（#21）**。deploy は F と C のあと（人が確認してから）
  - A の結合（2）の対象（#36 から移す）：/kid の相棒の絵をテーマで着替える・子の / のナビを /kid と同じ下に置く（PR-29 A2）・「もう一度確かめる」の下の余白（PR-29 A1）・/login の色・書体（PR-17 A1）。相棒の着替えが F と同じところ（appearance.js・保存）に触るなら、それだけ F のあとに回す
  - 画面の確認とスクリーンショットは毎回 320px（文字200% も）・375px・PC、明暗、テーマを当てた状態でも（UX_RULES.md）
  - QA のあとに足したコミットが `design/`・`tasks/` の docs だけなら qa-pass をそのまま使う。docs 以外（main を取り込んだマージで入ったファイルも）が入ったら request-qa をやり直す（ai-dev-harness PR #21）
- **デプロイ前にやること**（deploy.sh の実行は人が確認してから）
  - [x] ① デプロイ先のプロジェクト作成と課金 → 済（`mimamorikun-family`、番号 932685100691。2026-09-28）
  - `.env`：`GOOGLE_CLOUD_PROJECT=mimamorikun-family` は入れた（2026-09-28）
  - [x] `.env` に `MIMAMORI_CALENDAR_ID`（アプリ専用のカレンダー）を入れた（2026-09-28）
  - [x] リマインダー：終日と時刻つきを分けた（#31 → PR #32 マージ、実装 Codex）。`.env` に `MIMAMORI_REMINDERS_ALLDAY=360`（前の日 18:00）と `MIMAMORI_REMINDERS_TIMED=1080,60` を入れた（2026-09-28）。deploy.sh が2つを Cloud Run に渡す
  - `.gcloudignore` に `.gitignore` を取り込む（`asetts/`・`.env.*` などがアップロードされる）
  - 通知の Webhook（Slack の #みまもりくん。ローカルは `.env` の `MIMAMORI_NOTIFY_WEBHOOK` で送信確認済み 2026-09-28）を Secret Manager（mimamorikun-family）に入れ、deploy.sh から Cloud Run に渡す（`--set-secrets MIMAMORI_NOTIFY_WEBHOOK=…:latest`。Secret Manager の API 有効化と、実行用 SA に `roles/secretmanager.secretAccessor` を足す）。値は `--set-env-vars` に入れない
  - 実行後に gcloud の既定プロジェクトを戻す（今は okane-kenko-507122）
  - **デプロイのあとにやること**：カレンダーの共有に、deploy.sh が最後に表示するサービスアカウント（`mimamori-run@mimamorikun-family.iam.gserviceaccount.com`）を「予定の変更権限」で追加する（人がやる。しないと登録が 404 で落ちる）
- デプロイのあと：本番の台帳（Firestore）に合言葉を入れる（README「4. 合言葉を決める」）、カレンダー共有（上）、Firestore の読み書き確認 → WBS の A-1 を ✅
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」。実環境で確認するまで ✅ にしない
- **ドキュメントの見直しは、UX の塊 A〜F（#19〜#24）がマージされてから1本の PR でまとめてやる**：README・docs/現在地.md・docs/WBS.md・docs/画面設計.md・構成図（docs/architecture/）。**それまでは触らない**（塊の PR と衝突させない。2026-09-28 に人が決めた）

## 次の1手

- A の結合（2）→ F → C。それぞれ撮影 → ChatGPT の UX レビュー → `design/reviews/PR-<番号>.md` → ux-pass。そのあとデプロイ前チェック → deploy（人が確認してから）
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
