レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-28
- 担当エージェント: Codex（Issue #5）
- レビュー: #5 は Claude Code のレビュー待ち（PR は別担当が作成予定、番号未定）

<!-- 上限で交代するときは、次のエージェントがこのファイルだけ読めば続きができるように書く -->

## 現状

- ai-dev-harness を適用した直後（2026-09-27）
- 構成図を `docs/architecture/` に追加（#4）。本番で台帳が消える問題を Issue #5 に（2026-09-28）
- PRODUCT.md を人が決めた文面で埋め、README を今の状態（6画面・D-62・full レーン）に合わせた（2026-09-28）
- UX 見直し前の画面を `design/screenshots/before/` に（#7）。撮っていて #8・#9 を見つけた（2026-09-28）
- #8（/kid の相棒が別の子のタスクを読める・済にできる）を Claude Code が実装。子どもをツールに閉じ込め、持ち主を確かめる。初めてのテスト（`tests/`）と pytest を足した（2026-09-28）

- #5：Firestore 2.32.0 を追加（google-genai は 1.75.0 のまま）。Cloud Run 起動時に読み取りで接続を確認し、設定不足・初期化／接続失敗では JSON に切り替えず起動を停止。ローカルの従来動作は維持。
- 検証：`.venv/bin/python -m pytest` は 20 件成功（既存 8 件＋追加 12 件）。`bash -n deploy.sh` と `git diff --check` も成功。専用 build・lint コマンドは未定義。依存ライブラリ由来の警告あり。独立 QA は未実施。
- deploy.sh に Firestore API・Native のデフォルト DB（Cloud Run と同じリージョン、既定 us-central1）・roles/datastore.user を追加。スクリプトは未実行、GCP 操作なし。既存の本番 JSON は移行しない。

## やり残し

- Issue #5：実装・ローカルテスト済み。別担当による push・PR 作成・CI・Claude Code のレビュー待ち。マージ後、人が確認してから GCP へ反映し、Firestore の読み書きを確認する。
- Issue #9（/kid を開くと話しかけが2つ出て、1つ目は別の子あて。画面側の競合）：担当未定
- docs/WBS.md の A-1 は「実装済み・実環境確認待ち」に訂正済み。実環境で確認するまで ✅ にしない。

## 次の1手

- 別担当が fix/5-firestore-ledger を push して PR を作成し、Claude Code に request-qa を依頼する（実装: Codex）。
- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
