レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-29
- 担当エージェント: Codex（実装）・Claude Code（確認）。C のあとの単位は実装 Codex・確認 Claude（2026-09-29 に人が決めた）
- レビュー: UX レビューは PR ごとに `design/reviews/PR-<番号>.md`、`design/UX_REVIEW.md` は目次（2026-09-28 に人が決めた）。#17・#28・#29・#34・#35・#36・#38・#39・#41 は最新判定が ux-pass でよい。UX レビューの担当は `tasks/current.md` を変えない（書き込むのは `design/inbox/UX_REVIEW.md` だけ。UX_RULES.md・CLAUDE.md に明記）

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
- C（#21 → #41、ごほうびの画面）をマージ（2026-09-29、876d824）。UX の塊はすべて入った。main のテストは 615件通過
- ai-dev-harness に「デプロイの準備」（#22・#23）：`scripts/check_deploy_ready.sh`（gcloud の `--project`・`config set project` 禁止・`.gcloudignore` の許可リスト・秘密は `--set-secrets`）とその CI、Claude Code の `.claude/` の gcloud フック、雛形。mimamori には PR #43（デプロイ前チェック）で入れる

## やり残し

- **デプロイ前チェック（PR #43、実装 Codex・確認 Claude）**。deploy.sh の実行は人が確認してから
  - [x] デプロイ先のプロジェクト作成と課金、`.env` の設定、リマインダー（2026-09-28）
  - [x] `.gcloudignore` を許可リストに（Dockerfile・requirements.txt・main.py・mimamori/・static/ だけ。`__pycache__`・`*.pyc`・`.DS_Store` は除外）。`gcloud meta list-files-for-upload` で 42件、禁止対象なし
  - [x] deploy.sh：すべての gcloud に `--project`、`config set project` を削除、Webhook は `--set-secrets`、SA・Secret・Firestore は **あるかを確かめるだけ**（作るのは `scripts/setup_service_account.sh`・`scripts/put_secret.sh`）
  - [x] `bash scripts/check_deploy_ready.sh` が 0件。CI（deploy-ready.yml）も同じ PR で入れる
  - [x] 手順書 `docs/デプロイ手順.md`：① SA の作成とカレンダー共有 ② Webhook を Secret Manager へ（read -s → --data-file=-） ③ 合言葉3つ ④ デプロイ ⑤ デプロイ直後の確認 ⑥ 戻し方・初回の公開停止。**値はすべて人が入れる。Claude・Codex は見ない・聞かない**
  - [x] main での通し確認（ログイン → 撮る → 親の一覧 → 子の一日 → ごほうび、375・PC。2026-09-29）
  - [x] 公開リポジトリの点検（報告だけ、消していない。PR #43 のコメント）
  - [ ] 人：手順書の ①〜③ → ④ `bash deploy.sh` → ⑤
- **判断待ち**：Issue #42（申込の冪等キー・見送りの原子化）をデプロイの前にやるか後か
- **気づいたこと（Issue にするか人が決める）**：/kid の「pt」は完了した予定の合計（14日）、/reward は台帳の残高で、ごほうびを申し込むと数字がずれる／同じおたよりを2回登録すると、括弧の全角・半角の違いで重複を見分けられないことがある
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」。実環境で確認するまで ✅ にしない（手順書の⑤が通ったら）
- **ドキュメントの見直しは、UX の塊 A〜F（#19〜#24）がマージされてから1本の PR でまとめてやる**：README・docs/現在地.md・docs/WBS.md・docs/画面設計.md・構成図（docs/architecture/）。**それまでは触らない**（塊の PR と衝突させない。2026-09-28 に人が決めた）

## 次の1手

- PR #43（デプロイ前チェック）を CI・request-qa のあとマージ（人の確認のあと）→ 人が手順書 ①〜③ → `bash deploy.sh` → ⑤ デプロイ直後の確認
- 後回し（今の順番のまま）：ドキュメントの見直し（上）・tasks の整理・screenshots の容量ルール（今 29MB）
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
