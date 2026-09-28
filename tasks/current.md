レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-29
- 担当エージェント: Claude Code（C・デプロイ前チェック）
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
  - A の結合（2）（#38）・F（#39、子ごとの設定の保存：見た目・相棒の名前・学年とふりがな。`GET/POST /api/child-settings`、部分更新）をマージ。main のテストは 517件通過（2026-09-29、3c3e4b7）。本番の Firestore での保存は未確認（デプロイ直後に確認）
  - /board の再確認のために `GET /api/status?event_id=`（親だけ）を足した（#35）

## やり残し

- **次は C（#21、ごほうびの画面）**。A の結合（2）（#38）と F（#24 → #39）はマージ済み。相棒の着替えは F のあとに回さず #38 で入った（ux-pass）
  - 画面の確認とスクリーンショットは毎回 320px（文字200% も）・375px・PC、明暗、テーマを当てた状態でも（UX_RULES.md）
  - QA のあとに足したコミットが `design/`・`tasks/` の docs だけなら qa-pass をそのまま使う。docs 以外（main を取り込んだマージで入ったファイルも）が入ったら request-qa をやり直す（ai-dev-harness PR #21）
- **デプロイ前チェック**（C のマージのあと。deploy.sh の実行は人が確認してから）
  - [x] デプロイ先のプロジェクト作成と課金 → 済（`mimamorikun-family`、番号 932685100691。2026-09-28）
  - [x] `.env`：`GOOGLE_CLOUD_PROJECT=mimamorikun-family`・`MIMAMORI_CALENDAR_ID`（アプリ専用のカレンダー）を入れた（2026-09-28）
  - [x] リマインダー：終日と時刻つきを分けた（#31 → PR #32 マージ、実装 Codex）。`.env` に `MIMAMORI_REMINDERS_ALLDAY=360`（前の日 18:00）と `MIMAMORI_REMINDERS_TIMED=1080,60` を入れた（2026-09-28）。deploy.sh が2つを Cloud Run に渡す
  - 画面の通し確認（main で、ログイン・撮る・親の一覧・子の今日・ごほうび。スマホと PC）
  - `.gcloudignore`：`design/`（screenshots を含む）・`tests/`・`.env.*`・`asetts/` がアップロード対象に入らないこと。**今は `.env` だけ除外で、この4つは入ってしまう**（2026-09-29 に確認）。`gcloud meta list-files-for-upload` で確かめる
  - deploy.sh：`--project` を明示する。**今は `gcloud config set project` で既定を書き換えるだけで、`run deploy`・`services describe` などに `--project` がない**（2026-09-29 に確認）。全部の gcloud に `--project "$PROJECT"` を付け、既定は書き換えない（okane-kenko-507122 側に行かないように。既定を戻す作業もいらなくなる）
  - 通知の Webhook：Secret Manager（mimamorikun-family）から読む形か。**今の deploy.sh には `--set-secrets` がない**。Secret Manager の API 有効化・Secret の作成（値は人が入れる）・実行用 SA に `roles/secretmanager.secretAccessor`・deploy.sh に `--set-secrets MIMAMORI_NOTIFY_WEBHOOK=…:latest`。値は `--set-env-vars` に入れない。確認は変数名と Secret 名だけ（URL は表示しない）
  - Google カレンダーが実行用 SA（`mimamori-run@mimamorikun-family.iam.gserviceaccount.com`）に「予定の変更権限」で共有されているか（人がやる。しないと登録が 404。カレンダー ID は表示しない）。SA は deploy.sh の初回に作られるので、まだ無ければ「デプロイ直後」の最初にやる
  - 合言葉3つ（おうちの人・上の子・下の子）：設定の手順だけ用意する（README「4. 合言葉を決める」、本番は `MIMAMORI_LEDGER=firestore`）。**値は人が自分で決めて入れる。Claude は値を見ない・聞かない**
  - 公開リポジトリの点検：`design/`（screenshots を含む）・`docs/`・`samples/`・履歴に、実名・学校名・実物のプリントが写っていないか
  - 戻す手順を先に書いておく（下の「デプロイ直後」）
- **デプロイ直後**（本番で1回ずつ）
  - 保存：見た目・相棒の名前・学年が、再読込・別の端末でも残る（Firestore）
  - プリントの読み取り（Gemini、Vertex AI 経由）
  - カレンダーへの登録
  - 通知が届く（Slack の #みまもりくん）
  - 子どものログインで、親専用の画面（/board など）と API（`parent_only`）に入れない（403）
  - 問題が出たら前の版へ戻す：`gcloud run revisions list --service mimamorikun --region us-central1 --project mimamorikun-family` で前のリビジョン名を見て、`gcloud run services update-traffic mimamorikun --to-revisions <前のリビジョン>=100 --region us-central1 --project mimamorikun-family`（初回のデプロイは戻す先がないので、止めるなら `--no-allow-unauthenticated` にする）
  - すべて通ったら WBS の A-1 を ✅
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」。実環境で確認するまで ✅ にしない
- **ドキュメントの見直しは、UX の塊 A〜F（#19〜#24）がマージされてから1本の PR でまとめてやる**：README・docs/現在地.md・docs/WBS.md・docs/画面設計.md・構成図（docs/architecture/）。**それまでは触らない**（塊の PR と衝突させない。2026-09-28 に人が決めた）

## 次の1手

- C（#21）。撮影 → UX レビュー → `design/reviews/PR-<番号>.md` → ux-pass。そのあとデプロイ前チェック → deploy（人が確認してから）→ デプロイ直後の確認
- 後回し（今の順番のまま）：ドキュメントの見直し（上）・tasks の整理・screenshots の容量ルール（今 29MB）
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
