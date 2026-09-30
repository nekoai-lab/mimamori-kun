# みまもりくん（mimamorikun）

学校のおたよりを撮ると、日付・提出期限・持ち物を読み取って **Google カレンダーに並べる** エージェント。
第5回 Agentic AI Hackathon ミニハッカソン（2026-09-05）の題材。

## 何を解くか

子ども2人（小学校・中学校）ぶんの連絡が、紙のプリント／学校アプリ／オンラインの行事案内／口頭に
散らばっていて、保護者が突合しきれない。**覚えていなくても回る状態**を作るのが目的。

新しいアプリを開く習慣は要求しない。出口を Google カレンダーに置くことで、
「新しいアプリを覚える」という認知負荷そのものを足さない。

## エージェントが自律で回すステップ

1. おたよりの画像を読む（マルチモーダル）
2. 日付を読み取り、あいまいなものは推測せず親への確認待ちにする
3. 学年表記・教科・持ち物から、どちらの子のものか判定する
4. **コードで既存カレンダーを照会し、重複・追記・日程変更を照合する** ← 書く前に読む
5. 確定日付の登録候補を逐次返す（この時点ではカレンダーに書かない）

親が撮ったものは、候補を画面で確認してから書き込む。**読み取りと判断は自律、処置は承認。**

**子が撮った確定日付の予定は、承認を挟まずそのまま入れて、親に知らせる（D-62）。**
あいまいな日付は台帳の確認待ちに保存し、親が「何月何日？」に答えてから登録する。
承認を挟むと、親が忘れた日は子のやることが空のまま1日が終わり、子は次の日から撮らなくなる。
親には `/board` の帯（と、設定していれば `MIMAMORI_NOTIFY_WEBHOOK` の先）で知らせ、違っていればその場で消せる。

## 画面

ログイン＋6画面。画面の正本は [`design/UX_SPEC.md`](design/UX_SPEC.md)。
後から増えた状態と旧設計からの案内は [`docs/画面設計.md`](docs/画面設計.md)。

| URL | 誰が | 何をする |
|---|---|---|
| `/` | 子ども（親も可） | 撮る／手入力 → 候補確認 → カレンダーに登録 |
| `/kid` | 子ども | 今日やること・完了・相棒と話す。★⑤ 伴走する人。上の子は今日の分と枠バー |
| `/plan` | 上の子 | 学習計画の全体像と割りふり（締切から前倒しで配る） |
| `/board` | 親 | 確認すること・日付の確認待ち・知らせ。管理はメニューから開く |
| `/reward` | 子ども＋親 | 残高・履歴・引き換え（申請 → 親が承認 → 手渡し）・月の上限 |
| `/schedule` | 親・子ども | 予定表（月表示）。日を押すと中身が出る |
| `/login` | だれでも | だれ（おうちの人・中学生・小学生）→ 合言葉 |

子の `/kid`・`/reward`・撮る画面の下部ナビは「きょう・とる・ごほうび」。
親は「確認・撮る・メニュー」。子は3テーマ×明暗を選べ、相棒・学年と読みも子ごとに保存する。
独立した `/settings` はなく、設定は見た目のシートや各画面のメニューから開く。

`/board` と `/kid` は `MIMAMORI_DEMO=1` を付けるとダミーのタスクで動く（`/kid` の会話は Gemini が必要）。

### ログイン（#17）

ログイン用の公開 API と `/healthz` を除き、画面と API はログインで守る（未ログインのページは `/login` へ、API は 401）。
Cloud Run は `--allow-unauthenticated` のまま、アプリの入口で守る。

- 親・子どもそれぞれに合言葉。入れると署名付き Cookie（HttpOnly・Secure・SameSite=Lax、180日）で端末が覚える
- **子どもは自分のぶんだけ**。「だれ？」は自分だけになり、兄弟には切り替えられない。`/board` と親だけの API（知らせ・年間予定・定期タスク・ごほうびの設定・引き換えの承認）は使えない。予定・課題・引き換えは、持ち主が自分のものだけ変えられる
- 親は全部。子の端末から合言葉で親に一時切替でき、操作がないまま10分たつと子へ戻る。`/board` に端末単位・全端末のログアウトがある
- ログイン画面には子どもの呼び名を出さない（ログイン前の画面は誰でも開けるため）。学齢で見せる
- 同じ人で5回続けて間違えると15分ロック
- 合言葉はハッシュ（scrypt）だけを台帳に置く。Cookie の署名の鍵と「世代」（全端末ログアウト用）も台帳。環境変数には置かない
- ローカルだけ `MIMAMORI_AUTH=off` で外せる（Cloud Run では無視）

## いまどこまで動くか

**2026-09-30 時点：UX の塊 A〜F とデプロイ前の修正が入り、人のデプロイ待ち。**
いまの状態と次の手は [`docs/現在地.md`](docs/現在地.md)、実装の残タスクは [`docs/WBS.md`](docs/WBS.md) が正本。

- ログイン、撮る→読む→登録→おわった、ごほうびの申請→承認→手渡し、親の「確認すること」が動く
- 日付の確認待ち・同じ質問の照合・登録直前の重複防止、完了時のポイント記録まで実装済み
- Cloud Run の台帳は Firestore 必須。実環境の永続化・連携はデプロイ手順⑤で確認する（WBS A-1 は未完了）
- ローカルのテスト **1311件通過**、デプロイ準備チェックは指摘0件。CI は `test` と `check`（deploy-ready）

## 画面と API の契約

主な API を挙げる。契約を変えるときは、その API を使っている画面も合わせて直す。
ログインは `/api/auth/*`、見た目・相棒・学年の設定は `/api/child-settings` を使う。

| 画面 | 叩く口 |
|---|---|
| `/`（index.html） | `/api/config` `/api/extract/stream` `/api/register` `/api/register/undo` `/api/quick/repeat` |
| `/kid`（kid.html） | `/api/config` `/api/tasks` `/api/status` `/api/kid/chat` `/api/week` `/api/capacity` `/api/postpone` |
| `/plan`（plan.html） | `/api/config` `/api/plan` `/api/study/range` `/api/assignments`（`/update` `/remove`）`/api/capacity` |
| `/board`（board.html） | `/api/config` `/api/tasks` `/api/status` `/api/register`（手で足す）`/api/date_questions` とその操作 API `/api/notices` `/api/notices/seen` `/api/recurring` `/api/year_plan/*` |
| `/reward`（reward.html） | `/api/config` `/api/points` `/api/rewards` `/api/redeem/*` |
| `/schedule`（schedule.html） | `/api/schedule` |

`mimamori/points.py` は、次のシグネチャを保てば `main.py` と繋がる。中身は作り替えてよい。

```python
balance(child) -> int
history(child, limit=30) -> list[dict]
get_rewards() -> list[dict]
set_rewards(rewards) -> dict     # 台帳（mimamori/ledger.py）の settings に保存する
points_for(kind, fixed_count=0) -> int
RULES: dict                      # calendar_tools._points_for と値を揃えること
```

## タスクは Google カレンダー、ポイント・設定は台帳

タスクは予定の `extendedProperties.private` に
`app / child / kind / status / points / bring` を持たせ、`/board` はそれを読むだけ。
日程変更・追記は同じ予定の ID を保って更新する。完了しても予定は消さず、件名に ✓ を付けて残す。

ポイント・親への知らせ・日付の確認待ち・設定・認証は、別の台帳（`mimamori/ledger.py`）に持つ。
ローカルは `.data/ledger.json`、Cloud Run は Firestore（`families/default/points_ledger` と `settings`）。
あいまいな日付の確認待ちはカレンダーの `pending` とは別で、親が日付を決めるまで予定にしない。

`status` は5つ。保留も「けした」も、保存先を増やさずここで表す。

| status | 意味 | 親の一覧 | 子のやること |
|---|---|---|---|
| `pending` | 親が自分の判断で保留にした（子が撮ったものは D-62 で `todo` として入る） | 「承認まち」に出る | **出ない** |
| `todo` | やること | 出る | 出る |
| `doing` | 子が「やってる」と言った | 印だけ出る | 出る |
| `done` | 終わった | 「済も表示」で出る | 出ない |
| `rejected` | 親が「けす」を押した | 出ない | 出ない |

`/board` は今日の 14日前から 14日後までを読む。前に遡るのは遅れているものを拾うためで、
過去の済んだものは一覧の取得対象から外す。ポイントは予定の一覧から数え直さず、台帳の記録を合算する。

## ポイントの付け方

**行動に付ける。結果（テストの点数）には付けない。**
宿題 3pt ／ 提出 3pt ／ 持ち物 2pt ／ 行事 0pt。
テストは点数ではなく「直した問題の数」に付ける（点が悪いほどポイントが取れる＝隠す動機を消す）。
何ptで何と交換するかは親が決め、設定として保存する。
完了時に台帳へ加点し、取り消しはその記録を無効化する。再送・再完了で二重に増やさない（#53）。

## ★⑤ の態度（人格ではなく態度）

`mimamori/kid_agent.py` の instruction に禁止事項として書いてある。

- 答えを言わない。ヒントは「場所」と「やり方」まで
- 残りを数えない。「あと3つ」ではなく「1つ終わったね」
- 数を聞かれても答えないが、**黙って話を変えない。**
  「数は数えないことにしてる」と言って、次の1つだけ示す（無視されたと思わせるほうが害になる）
- 評価しない。「えらい」ではなく「終わったね」
- 責めない。期限を過ぎていても「まだ残ってる。今日やっちゃう？」
- 質問は1つずつ。同じことは2回まで
- 秘密を持たない。親も見られることを画面にも明示

**この態度は決定事項。変えるときは相談する。**
UIの文言もこれに合わせる。理由は「漏れる→怒られる→子が自信をなくす」の連鎖を解こうとしているため。
ここで催促を強めると、怒る役をアプリに移しただけになる。

## 構成

構成図は [`docs/architecture/`](docs/architecture/)（元データは `mimamori-kun.architecture.json`）。
JSON は main 45bc3eb に更新済み。HTML は Claude による再生成待ち。

| 層 | 使うもの |
|---|---|
| 読み取り | おたよりは Gen AI SDK `generate_content_stream`、通常1回。日付検証・重複照合はコード。空・不正 JSON のみ1回再試行、全体25秒 |
| エージェント | 年間予定の読み取りと伴走は Google ADK `LlmAgent`（伴走のツールは本人の予定に限定） |
| モデル | Vertex AI `gemini-2.5-flash`。おたよりの thinking budget は512（設定で変更可） |
| カレンダー | Google Calendar API（実行サービスアカウントの ADC）。タスクの正本 |
| 台帳 | `mimamori/ledger.py`。ローカル JSON／Cloud Run は Firestore 必須、接続失敗は起動停止 |
| 認証 | `mimamori/auth.py`。合言葉のハッシュと署名 Cookie、所有者・親専用操作の確認 |
| API / UI | FastAPI + 画面ごとの単一 HTML |
| 実行環境 | Cloud Run |

```
mimamori-kun/
├── main.py                  FastAPI。画面と API の入口
├── mimamori/
│   ├── config.py            環境変数
│   ├── schema.py            抽出結果の型
│   ├── calendar_tools.py    カレンダーの読み書き（タスクの正本）
│   ├── agent.py             おたよりのストリーミング・年間予定の読み取り
│   ├── ambiguous_dates.py   日付の確認待ち・同じ質問の照合
│   ├── auth.py              ログイン・親への一時切替
│   ├── appearance.py        子ごとの見た目・相棒・学年と読み
│   ├── kid_agent.py         子どもと話すエージェント（★⑤）
│   ├── ledger.py            台帳（ポイント・知らせ・設定）
│   ├── points.py            ポイントと交換レート
│   ├── redeem.py            引き換え（申請 → 承認 → 手渡し）
│   ├── notify.py            親への知らせ（帯・Webhook）
│   ├── recurring.py         定期タスク（公文など）
│   ├── study.py             上の子の学習計画の割りふり
│   ├── year_plan.py         年間予定の取り込み
│   ├── dedupe.py            取り込みの4分岐（完全一致／差分／日程変更／新規）
│   └── images.py            HEIC などを JPEG に直す
├── static/
│   ├── index.html           撮る・手入力 → 確認 → 登録
│   ├── kid.html             今日やること・相棒（子）
│   ├── plan.html            学習計画（上の子）
│   ├── board.html           一覧（親）
│   ├── reward.html          ごほうび・引き換え
│   ├── schedule.html        予定表（月表示）
│   ├── login.html           合言葉でログイン
│   ├── theme.js             明暗の切り替え
│   ├── appearance.js        テーマ・ナビ・子ごとの設定
│   └── who.js               「だれ？」の選択
├── samples/                 テスト用のダミーおたより（実物は置かない）
├── tools/check_extract.py   読み取り結果の突き合わせ（手で動かす）
├── docs/                    要件定義・画面設計・WBS・現在地・構成図
├── Dockerfile
└── deploy.sh
```

**変更はブランチ → PR で入れる（レーンは full）。**
CI が通り、実装者と別の AI のレビュー（`request-qa`）でラベル `qa-pass` が付いたらマージする。
UI の変更がある PR は `ux-pass` も要る。ルールの正本は ai-dev-harness の `policies/git-flow.md`。

## GCP プロジェクトは分ける

**okane-kenko（本戦提出物）とは別のプロジェクトを使う。** 理由は3つ。

1. 本戦アプリの API 有効化・クォータ・IAM を触らずに済む
2. ハッカソン後にプロジェクトごと消せる
3. **みまもりくんは外部から来た画像を LLM に食わせるアプリ**で、インジェクションの入口を持つ。
   同じ売りを持つ okane-kenko と事故の影響範囲を共有させない

専用サービスアカウントは手順①の `scripts/setup_service_account.sh` で用意する。
Vertex AI・Firestore の権限と、手順②で通知用 Secret 単位の読み取り権限を付与する。
`deploy.sh` は SA・Secret・Firestore の存在を確かめるだけ。
**カレンダーへの権限は IAM ではなく、カレンダー側の共有設定で個別に渡す。**
共有を外せば、アプリはカレンダーに触れなくなる。

## いちばん速い動かし方（開発用デモ）

**開発の読み取りは Vertex AI＋ADC を使う。** Python 3.10 以上と依存関係を用意する。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

人が下の設定と ADC の準備を済ませてから、起動する。

```bash
bash scripts/dev_server.sh
```

`http://localhost:8080` を開く。ローカル JSON 台帳、デモのカレンダー、通知なしで動く。
ログインは既定で有効なので、人がローカル用の合言葉を設定する（下の「4」）。
画面だけのローカル確認では `MIMAMORI_AUTH=off bash scripts/dev_server.sh` でも起動できる。
デモでも読み取り・会話は実際の Vertex AI を呼ぶ。

**AI Studio の `GOOGLE_API_KEY` はこの起動方法では使わない。**
`dev_server.sh` は `GOOGLE_API_KEY`・`GEMINI_API_KEY` を外し、Vertex AI を明示する。
`agent.py` の `genai.Client()` 自体は SDK の標準環境変数による Gemini API の選択にも対応するが、
キー1本の旧手順は現在の開発・デプロイ手順ではない。

## セットアップ

### 1. 設定

人が `.env.example` を参考に、Git 管理外の `.env` に設定する（値は AI と共有しない）。
開発では `GOOGLE_CLOUD_PROJECT` と **同じ値の `GOOGLE_CLOUD_QUOTA_PROJECT`** を必ず入れる。
ローカルで Vertex AI または Firestore を使うとき、未設定・空・不一致は接続前に停止する。
既定の ADC ファイルの課金先を変更する必要はない。
モデルの既定は `gemini-2.5-flash`、`MIMAMORI_THINKING_BUDGET=512`。

### 2. ローカルで動かす

人が AI と共有しない端末で、対象プロジェクトの Vertex AI を使える ADC を準備する。
カレンダーを実際に使う場合は Calendar API の権限も必要。通常の開発は上の `scripts/dev_server.sh` を使う。
このスクリプトは `.env` を読み、課金先を確かめ、`127.0.0.1:8080` で起動する。
`MIMAMORI_LEDGER` や `K_SERVICE` があると停止するので、開発用の設定から外しておく。

ポイント・知らせ・設定の台帳は、ローカルでは既定で `.data/ledger.json` に保存する。
`GOOGLE_CLOUD_PROJECT` や ADC があっても、台帳の Firestore クライアントは作らない。
保存先を選ぶ変数は `MIMAMORI_LEDGER`（未指定または `json` なら JSON、
`firestore` を明示したときだけ Firestore）。Firestore には `GOOGLE_CLOUD_PROJECT` が必要で、
起動時の初期化・接続確認に失敗すると起動を止める。JSON への自動切り替えはしない。
Cloud Run（`K_SERVICE` がある環境）は `json` を指定しても Firestore を使う。
`MIMAMORI_LEDGER` の空文字を含む未知の値は、どちらの環境でも起動エラーになる。
`MIMAMORI_DEMO` はカレンダーの切り替えで、この台帳の保存先には影響しない。

### 3. Cloud Run へ

**[デプロイ手順](docs/デプロイ手順.md) が正本。**
人が AI と共有しない端末で、① SA とカレンダー共有 → ② Webhook を Secret Manager へ →
③ 合言葉 → ④ デプロイ → ⑤ 実環境確認の順に行う。戻し方は⑥。
Claude・Codex は gcloud・deploy.sh・set_passcode を実行せず、秘密の値や SA アドレスを受け取らない。

### 4. 合言葉を決める

**画面からは決めない。** 人が AI と共有しない端末で `tools/set_passcode.py` を使い、
親・子それぞれに非表示入力する。合言葉を引数・文書・ログに書かない。
ローカルの台帳に設定した合言葉は、本番には反映されない。
本番は必ず [デプロイ手順③](docs/デプロイ手順.md#③-合言葉3つを本番の台帳へ設定) のとおり、
Firestore を用意してから初回公開前に設定する。未設定の人はログインできない。

## つまずきポイント

- **デモの途中でやることが初期化される** → `--reload` で起動していると、誰かがファイルを
  保存したときにサーバーが再起動する。デモのカレンダーはプロセス内にあるので消える（ポイント・設定などの JSON 台帳とは別）。
  見せるとき・録画するときは `--reload` を外して起動する
- **`No matching distribution found for google-genai`** → `python3` が 3.9 になっている。
  `google-genai` は 3.10 以上が必要。`python3.13 -m venv .venv` のように版を指定して作り直す
- **`404 Not Found` on insert** → カレンダーをサービスアカウントに共有できていない
- **終日予定が1日ずれる** → Calendar API の `end.date` は排他。`calendar_tools._body` で +1 日している
- **課金先の不一致で起動しない** → 人が `GOOGLE_CLOUD_QUOTA_PROJECT` と `GOOGLE_CLOUD_PROJECT` を同じ値に設定する
- **`403 Vertex AI API has not been used`** → 人が対象プロジェクトの API 有効化・権限を確認する
- **ADK のバージョン差** → 年間予定・伴走は ADK を使う。`requirements.txt` の依存条件を保つ

## 残りタスク

正本は [`docs/WBS.md`](docs/WBS.md)（全タスクに DoD つき）。いまの状態と次の手は [`docs/現在地.md`](docs/現在地.md)。
要約は上の「いまどこまで動くか」。
