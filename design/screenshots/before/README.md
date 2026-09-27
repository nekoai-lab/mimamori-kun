# before — UX 見直し前の画面（2026-09-28、main `ee30bb1`）

下の子の導線（`/`・`/kid`・`/reward`・`/board`）。PC は 1440×900、スマホは 390×844（2倍）。ライトモード、ページ全体を撮った。

- `MIMAMORI_DEMO=1`、`--reload` なしで起動。子どもの表示名はダミー（`上の子` / `下の子`）、タスクはデモ用のダミー
- 選んでいる子は「下の子」。台帳は空から始めた

| ファイル | 状態 |
|---|---|
| `shoot-pc.png` / `shoot-sp.png` | `/` 撮る画面（読み取る前） |
| `kid-pc.png` / `kid-sp.png` | `/kid` 今日やることが5件 |
| `kid-done-pc.png` / `kid-done-sp.png` | `/kid` 今日の分を全部終えたあと（台紙が5つ埋まった） |
| `reward-empty-pc.png` / `reward-empty-sp.png` | `/reward` ポイント・記録が0 |
| `reward-pc.png` / `reward-sp.png` | `/reward` 今日の分を終えて 14pt たまったあと |
| `board-pc.png` / `board-sp.png` | `/board` 遅れ・今日・明日・今週・予定が並んだ状態 |
| `board-empty-pc.png` / `board-empty-sp.png` | `/board` 全部終えたあと（「抜けはありません」） |

`/kid` の会話は Gemini（AI Studio のキー）につないで撮った。返事は毎回変わる。

**撮っていて気づいたこと（UX 見直しで一緒に見てほしい）**
- `/kid`（下の子）の相棒が「体育祭の係希望票」に触れている。デモのデータでは、これは上の子のタスク。`get_my_tasks` は子どもで絞っているので、モデルが別の子の名前でツールを呼んだか、別の子のものを話題にした可能性がある
- `/kid` を開くと、相棒の話しかけが2つ続けて出る
