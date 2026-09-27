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

**注意：`/kid` の会話欄の「うまくつながらなかった」は本来の表示ではない。** 撮影した環境の Gemini の API キーが無効で、会話が Gemini につながらなかった。カード・台紙・ポイントは正しく出ている。会話を含めて見直すときは、キーを直して撮り直す。
