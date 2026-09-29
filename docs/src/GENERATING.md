# 公開用プリントの再生成

`docs/src/今日つくるもの.html` と `samples/src/*.html` が編集元。
元の画像に合わせた出力寸法は `tools/render_prints.cjs` に固定してある。

外部のディレクトリに `playwright-core` を用意し、リポジトリのルートで実行する。

```sh
NODE_PATH=/path/to/node_modules node tools/render_prints.cjs
```

Chrome は macOS の標準インストール先を使う。別の場所なら `CHROME_PATH` で指定する。
PNG 4件と PDF 1件を既存のパスに出力する。出力後は全文・日付・持ち物・金額・改行と
ページ数を目で確認する。特に学校名・先生名・担当者名を確認する。

## Issue #44 の引き継ぎ

この実装環境では headless Chrome が起動直後に `SIGABRT` で終了し、再生成できなかった。
HTML は用意したが、既存 PNG・PDF は未更新で、旧表記が残っている。
レンダリング後のレイアウト確認も未実施。Claude Code の確認環境で上記のコマンドを実行し、
生成物を確認・コミットする必要がある。

`design/screenshots/` の見本画像を含む画面は、生成物の更新後に Claude Code が撮り直す。
