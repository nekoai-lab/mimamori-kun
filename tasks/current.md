レーン: full

# 今の作業 — mimamori-kun

- 更新日: 2026-09-28
- 担当エージェント: Claude Code
- レビュー: #9 の PR を Codex がレビュー（request-qa）。#5 の PR（Codex 実装）が来たら Claude Code がレビュー

<!-- 上限で交代するときは、次のエージェントがこのファイルだけ読めば続きができるように書く -->

## 現状

- ai-dev-harness を適用した直後（2026-09-27）
- 構成図を `docs/architecture/` に追加（#4）。本番で台帳が消える問題を Issue #5 に（2026-09-28）
- PRODUCT.md を人が決めた文面で埋め、README を今の状態（6画面・D-62・full レーン）に合わせた（2026-09-28）
- UX 見直し前の画面を `design/screenshots/before/` に（#7）。撮っていて #8・#9 を見つけた（2026-09-28）
- #8（/kid の相棒が別の子のタスクを読める・済にできる）を Claude Code が実装し、マージ（#10）。初めてのテスト（`tests/`）と pytest を足した（2026-09-28）
- #5 の方針が決まった（Firestore ネイティブモード。#5 のコメント）（2026-09-28）
- #9（/kid を開くと別の子あての話しかけが出る）を Claude Code が実装。who.js が子を決めてから読み込む（2026-09-28）

## やり残し

- Issue #5（台帳の永続化）：**実装は Codex**（Claude Code は触らない）。方針は #5 のコメントのとおり。deploy.sh の実行はマージのあと人が確認してから
- docs/WBS.md の A-1（Firestore 導入）が ✅ だが、requirements.txt に google-cloud-firestore が無い（#5 と合わせて直す）

## 次の1手

- ARCHITECTURE.md と CLAUDE.md のコマンドを埋める
