レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-28
- 担当エージェント: Codex（Issue #14）／Claude Code（ほか）
- レビュー: #14 は別担当が PR 作成後、Claude Code がレビュー（request-qa）。レビュー待ち（PR 未作成）

<!-- 上限で交代するときは、次のエージェントがこのファイルだけ読めば続きができるように書く -->

## 現状

- PR #28 UXレビュー（2026-09-28）：`design/inbox/UX_REVIEW.md` を追加。高1件・中4件。次はB1〜B5の指摘対応と短画面・完了取消の再確認。見た目と設定／会話／読み補助の結合は担当塊へ持ち越し。今回アプリコードは変更していない。

- #14：コメントなしのため Issue 本文の方針で実装。ローカルは `MIMAMORI_LEDGER` 未指定または `json` なら JSON（プロジェクト・ADC の有無によらず Firestore クライアントを作らない）。`firestore` 明示時と Cloud Run では Firestore 必須で、設定不足・初期化／接続失敗は起動エラー。Cloud Run は `json` より優先し、空文字を含む未知の値は両環境で拒否する。
- #14 の検証：`.venv/bin/python -m pytest` は 56 件成功（既存の子どもスコープ 8 件＋台帳 48 件）。`git diff --check` 成功。専用 build・lint コマンドは未定義。依存ライブラリ由来の警告あり。Firestore はモックのみ、GCP 操作なし。独立 QA は未実施。
- #14：README・`docs/セットアップ.md`・`.env.example`・台帳の説明を更新。作業ブランチは `fix/14-local-ledger-json`。preflight の fetch はネットワーク制限で失敗。ユーザー指定によりコミットまでで、push・PR は別担当。

- ai-dev-harness を適用した直後（2026-09-27）
- 構成図を `docs/architecture/` に追加（#4）。本番で台帳が消える問題を Issue #5 に（2026-09-28）
- PRODUCT.md を人が決めた文面で埋め、README を今の状態（6画面・D-62・full レーン）に合わせた（2026-09-28）
- UX 見直し前の画面を `design/screenshots/before/` に（#7）。撮っていて #8・#9 を見つけた（2026-09-28）
- #8（/kid の相棒が別の子のタスクを読める・済にできる）を Claude Code が実装し、マージ（#10）。初めてのテスト（`tests/`）と pytest を足した（2026-09-28）
- #5 の方針が決まった（Firestore ネイティブモード。#5 のコメント）（2026-09-28）
- #9（/kid を開くと別の子あての話しかけが出る）を Claude Code が実装。who.js が子を決めてから読み込む（2026-09-28）

- #5：Firestore 2.32.0 を追加（google-genai は 1.75.0 のまま）。Cloud Run 起動時に読み取りで接続を確認し、設定不足・初期化／接続失敗では JSON に切り替えず起動を停止。ローカルの従来動作は維持。
- 検証：`.venv/bin/python -m pytest` は 20 件成功（既存 8 件＋追加 12 件）。`bash -n deploy.sh` と `git diff --check` も成功。専用 build・lint コマンドは未定義。依存ライブラリ由来の警告あり。独立 QA は未実施。
- deploy.sh に Firestore API・Native のデフォルト DB（Cloud Run と同じリージョン、既定 us-central1）・roles/datastore.user を追加。スクリプトは未実行、GCP 操作なし。既存の本番 JSON は移行しない。

## やり残し

- Issue #14：実装・ローカルテスト済み。別担当による push・PR 作成・CI・Claude Code のレビュー待ち（PR 未作成）。
- Issue #5：#13 の実装を引き継いだ状態。GCP の実環境確認は今回の対象外。
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」に訂正済み。実環境で確認するまで ✅ にしない。
- #9 は #11 でマージ済み

## 次の1手

- 別担当が `fix/14-local-ledger-json` を push して Issue #14 の PR を作成し、Claude Code に request-qa を依頼する（実装: Codex）。
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
