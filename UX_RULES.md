# UX_RULES — mimamori-kun

`full` レーンで ChatGPT が担当する UX の成果物の置き場所と受け渡し。

## 成果物

| ファイル | 誰が | いつ | 置き場所 |
|---|---|---|---|
| `UX_SPEC.md` | ChatGPT | 実装の前（最初） | `design/UX_SPEC.md` |
| UX レビュー | ChatGPT | 実装のあと（最後） | `design/reviews/PR-<番号>.md`（PR ごとに1つ） |
| レビューの目次 | Claude Code | レビューを移したとき | `design/UX_REVIEW.md`（各レビューへのリンクと最新判定だけ） |
| スクリーンショット | Claude Code | UX レビューの前 | `design/screenshots/` |

## 受け渡し

1. ChatGPT の成果物は、人が `design/inbox/` に置く
2. Claude Code が中身を確かめ、上の表の場所へ移してコミットする（`design/inbox/` には残さない）
3. Claude Code は UX_SPEC.md に沿って実装し、スクリーンショットを撮って `design/screenshots/` に置く
   - **PC とスマホ、それぞれ1枚以上**
   - ファイル名：`<画面名>-pc.png`／`<画面名>-sp.png`
4. 人が ChatGPT にスクリーンショットを渡し、UX_REVIEW.md をもらって `design/inbox/` に置く → 2 へ

### UX レビューを移すとき（2 の続き）

- inbox の UX_REVIEW.md は、その PR の `design/reviews/PR-<番号>.md` に移す。初めてなら新しく作る
- 再確認で inbox に前回の本文の写しが入っているときは、写しが `design/reviews/PR-<番号>.md` と同じことを確かめ、**新しい再確認の節だけを末尾に足す**（二重にしない）。ファイルの冒頭には最新判定を1行置く
- `design/UX_REVIEW.md`（目次）のその PR の行を、最新判定とリンクで更新する
- レビューの本文は変えない。PR ごとに別のファイルなので、ほかの PR のレビューとはぶつからない

UX レビューの指摘のうち、直すものは PR で直す。直さないものは理由を `design/reviews/PR-<番号>.md` の末尾に書く。
最新判定が合格（直す指摘がない）になったら、PR にラベル `ux-pass` を付ける（UI の変更がある full の PR はマージに必須。`~/Projects/ai-dev-harness/policies/git-flow.md`）。

## UI の変更がある full の PR で確かめること

UI の変更がある `full` の PR **だけ**。solo や、UI の変更がない PR では不要。

ux-pass が要るのは、見た目・文言・画面の流れ（どこから何へ進むか）が変わるとき。見た目が変わらない不具合の修正（読み込み順・競合・データの取り違え）は UI の変更に数えない。ただし通しの確認とスクリーンショットは残す

- [ ] **変更に関係する主要操作を通しで1回**（Playwright か手動）。やった方法と結果を PR に書く
- [ ] **変更に関係する空・エラー・完了状態のうち、該当するものだけスクリーンショット**を撮り、`design/screenshots/` に置く（該当しない状態は撮らなくてよい）
  - ファイル名：`<画面名>-<empty|error|done>-<pc|sp>.png`
- [ ] **幅は毎回 320px・375×667・390×844・PC（1440×900）で確かめる**。320px では画面・シート・カードが横にはみ出さず、主な操作まで届くこと。スクリーンショットにも 320px を1枚以上入れる（`<画面名>-320-sp.png`）。文字200%・横向きも、シートや狭いカードがある画面では確かめる（PR-34 A1 で 320px の見落としがあったため。2026-09-28 に人が決めた）
