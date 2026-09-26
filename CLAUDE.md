# mimamori-kun

<!-- このリポジトリのルールの正本。AGENTS.md（Codex 用）はここを指すだけ -->

## 概要

みまもりくん：学校・塾の連絡（プリントの写真など）を束ねて、子どもの完了まで見届けるアプリ（public）。FastAPI ＋ Google ADK。本番は Cloud Run の予定（`deploy.sh`、まだデプロイしていない）。

## よく使うコマンド

| 用途 | コマンド |
|---|---|
| install | `uv pip install -r requirements.txt` |
| dev | `（未定）` |
| lint | `（未定）` |
| test | `uv run pytest` |
| build | `（未定）` |

## レーン

`full`（正本は `tasks/current.md` の1行目。基準は `~/Projects/ai-dev-harness/policies/lanes.md`）

## 共通ルール

作業の前に `~/Projects/ai-dev-harness/bin/preflight` を実行し、`~/Projects/ai-dev-harness/policies/` を読むこと。

- git-flow.md：ブランチ → PR → CI・レビュー → テストが通れば AI がマージ
- agents.md：役割、1 Issue = 1 Agent = 1 Branch = 1 Worktree（`~/Projects/mimamori-kun.wt/<branch>/`）、交代の順番
- lanes.md：full / solo
- secrets.md：鍵の値は表示しない。`.env*` は .gitignore

## 完了の定義

- [ ] build・lint・test が通る
- [ ] `tasks/current.md` を更新した（現状／やり残し／次の1手）
- [ ] PR を作り、CI が通った
- [ ] full は、実装者と別の AI のレビューでラベル `qa-pass`（UI の変更ありは `ux-pass` も）が付いた。付かないうちはマージしない

## このリポジトリ固有のルール

- **子ども・学校名・氏名が写る実物は公開しない**（public リポジトリ。`.gitignore` の `samples/real/`・`asetts/`・`.data/` を守る）。鍵は `.env`（変数名だけ確認する）
- テストはまだない（`tools/check_extract.py` は手で動かす確認）。本番に出す前に pytest と CI を足す
- public なので、コミットは noreply アドレス（REPOS.md の置き場所のルール）
