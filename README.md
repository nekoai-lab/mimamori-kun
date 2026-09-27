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
2. 「来週金曜まで」などの相対表現を実日付に直す
3. 学年表記・教科・持ち物から、どちらの子のものか判定する
4. **`list_events` で既存カレンダーを照会し、重複を見つける** ← 書く前に読む
5. 登録候補を返す（この時点では書かない）

親が撮ったものは、候補を画面で確認してから書き込む。**読み取りと判断は自律、処置は承認。**

**子が撮ったものは、承認を挟まずそのまま入れて、親に知らせる（D-62）。**
承認を挟むと、親が忘れた日は子のやることが空のまま1日が終わり、子は次の日から撮らなくなる。
親には `/board` の帯（と、設定していれば `MIMAMORI_NOTIFY_WEBHOOK` の先）で知らせ、違っていればその場で消せる。

## 画面

6画面。要素・状態・遷移の詳細は [`docs/画面設計.md`](docs/画面設計.md)。

| URL | 誰が | 何をする |
|---|---|---|
| `/` | 子ども（親も可） | 撮る／手入力 → 候補確認 → カレンダーに登録 |
| `/kid` | 子ども | 今日やること・完了・相棒と話す。★⑤ 伴走する人。上の子は今日の分と枠バー |
| `/plan` | 上の子 | 学習計画の全体像と割りふり（締切から前倒しで配る） |
| `/board` | 親 | 知らせの帯・やること一覧・予定。手で1件足す、年間予定をまとめて入れる |
| `/reward` | 子ども＋親 | 残高・履歴・引き換え（申請 → 親が承認 → 手渡し）・月の上限 |
| `/schedule` | 親・子ども | 予定表（月表示）。日を押すと中身が出る |

6画面ともヘッダの2行目に同じナビがある（撮る／一覧／やりとり／計画／ごほうび／予定表）。
右端のボタンで明るい／暗いを選べる。選ぶまでは OS の設定に従う。
画面設計にある `/settings` はまだ無い。

`/board` と `/kid` は `MIMAMORI_DEMO=1` を付けるとダミーのタスクで動く（`/kid` の会話は Gemini が必要）。

## いまどこまで動くか

**正本は [`docs/現在地.md`](docs/現在地.md)（いまの状態と次の手）と [`docs/WBS.md`](docs/WBS.md)（残タスク。全タスクに DoD つき）。** ここは要約だけ（2026-09-13 時点の現在地.md による）。

- v0.2（下の子が毎日使える状態）と v0.3（上の子の学習計画 `/plan`）は済み
- ごほうびの引き換え（申請 → 承認 → 手渡し）・月の上限・「今のペースだと約◯日」も済み（E-1〜E-3）
- 残りの主なもの：カレンダー共有で同期を本番にする（P-3）、週次目標・おやすみ券・スタンプ・調整（E-4〜E-6）、`/board` の「例外だけ」画面（D-6）、オフラインでも開ける（A-12）。上の子まわり（B-6 / B-7 / C系）は実物を見てから作る
- **既知の問題：本番（Cloud Run）では、台帳（ポイント・知らせ・設定）が再デプロイ・再起動で消える。** → [#5](https://github.com/nekoai-lab/mimamori-kun/issues/5)

## 画面と API の契約

画面は自分の口だけを叩く。口の形を変えるときは、その口を使っている画面も合わせて直す。

| 画面 | 叩く口 |
|---|---|
| `/`（index.html） | `/api/config` `/api/extract` `/api/register` `/api/register/undo` `/api/quick/repeat` |
| `/kid`（kid.html） | `/api/config` `/api/extract` `/api/register` `/api/tasks` `/api/status` `/api/kid/chat` `/api/week` `/api/capacity` `/api/postpone` |
| `/plan`（plan.html） | `/api/config` `/api/plan` `/api/study/range` `/api/assignments`（`/update` `/remove`）`/api/capacity` |
| `/board`（board.html） | `/api/config` `/api/tasks` `/api/status` `/api/register`（手で足す）`/api/notices` `/api/notices/seen` `/api/recurring` `/api/year_plan/*` |
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

## 台帳は Google カレンダー

新しいDBは作らない。予定の `extendedProperties.private` に
`app / child / kind / status / points / bring` を持たせ、`/board` はそれを読むだけ。
カレンダー側で人が手で直しても整合が壊れない。完了しても予定は消さず、件名に ✓ を付けて残す。

ポイントの加減算・親への知らせ・設定（ごほうび一覧・定期タスクなど）だけは、別の台帳（`mimamori/ledger.py`）に持つ。
本番でこの台帳が消える問題は [#5](https://github.com/nekoai-lab/mimamori-kun/issues/5)。

`status` は5つ。保留も「けした」も、保存先を増やさずここで表す。

| status | 意味 | 親の一覧 | 子のやること |
|---|---|---|---|
| `pending` | 親が自分の判断で保留にした（子が撮ったものは D-62 で `todo` として入る） | 「承認まち」に出る | **出ない** |
| `todo` | やること | 出る | 出る |
| `doing` | 子が「やってる」と言った | 印だけ出る | 出る |
| `done` | 終わった | 「済も表示」で出る | 出ない |
| `rejected` | 親が「けす」を押した | 出ない | 出ない |

`/board` は今日の 14日前から 14日後までを読む。前に遡るのは遅れているものを拾うためで、
過去の済んだものは捨てる（拾うとポイント合計が膨らみ、やり残しを探す目的から外れる）。

## ポイントの付け方

**行動に付ける。結果（テストの点数）には付けない。**
宿題 3pt ／ 提出 3pt ／ 持ち物 2pt ／ 行事 0pt。
テストは点数ではなく「直した問題の数」に付ける（点が悪いほどポイントが取れる＝隠す動機を消す）。
何ptで何と交換するかはアプリに持たせない。親が決める。

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

構成図は [`docs/architecture/`](docs/architecture/)（archify で生成。元データは `mimamori-kun.architecture.json`）。

| 層 | 使うもの |
|---|---|
| エージェント | Google ADK `LlmAgent`：おたより読み取り（`list_events` ツール）・年間予定の読み取り・伴走（`get_my_tasks` / `finish_task` / `start_task`） |
| モデル | Vertex AI Gemini |
| カレンダー | Google Calendar API（実行サービスアカウントの ADC）。タスクの正本 |
| 台帳 | `mimamori/ledger.py`（ポイント・知らせ・設定。本番の保存先は [#5](https://github.com/nekoai-lab/mimamori-kun/issues/5)） |
| API / UI | FastAPI + 画面ごとの単一 HTML |
| 実行環境 | Cloud Run |

```
mimamori-kun/
├── main.py                  FastAPI。画面と API の入口
├── mimamori/
│   ├── config.py            環境変数
│   ├── schema.py            抽出結果の型
│   ├── calendar_tools.py    カレンダーの読み書き（タスクの正本）
│   ├── agent.py             おたより・年間予定を読むエージェント
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
│   ├── theme.js             明暗の切り替え。6画面で共有
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

サービスアカウントも専用のものを `deploy.sh` が作る。付与するのは `roles/aiplatform.user` のみ。
**カレンダーへの権限は IAM ではなく、カレンダー側の共有設定で個別に渡す。**
共有を外せば、アプリはカレンダーに触れなくなる。

## いちばん速い動かし方（会話画面だけ見たいとき）

GCPプロジェクトも課金も要りません。**AI Studio の APIキー1本**で動きます。
必要なのは **Python 3.10 以上**（`python3 -V` で確認。macOS 同梱の 3.9 だと `pip install` が落ちる）。

```bash
cp .env.example .env
# .env の GOOGLE_API_KEY に https://aistudio.google.com/apikey で取ったキーを入れる

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a; source .env; set +a
uvicorn main:app --reload --port 8080
```

`http://localhost:8080/kid` を開く。ダミーのやることで会話が始まります。
「終わった」と言えば消え、`/board` にも反映されます（再起動すると戻ります）。

カレンダーに本当に書き込むのは、下の「本番」の手順に進んでから。

## セットアップ

### 1. 設定

```bash
cp .env.example .env
# GOOGLE_CLOUD_PROJECT と MIMAMORI_CALENDAR_ID、MIMAMORI_CHILDREN を埋める
```

### 2. ローカルで動かす

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/calendar

set -a; source .env; set +a
uvicorn main:app --reload --port 8080
```

`http://localhost:8080` を開く。
ローカルでは自分のユーザー資格情報で動くので、カレンダー共有の設定は不要。

### 3. Cloud Run へ

```bash
./deploy.sh
```

デプロイの最後に **サービスアカウントのメールアドレス** が表示される。
Google カレンダー → 対象カレンダーの設定 → 「特定のユーザーとの共有」に、
そのアドレスを **「予定の変更権限」** で追加する。これをやらないと登録が 404 で落ちる。

## つまずきポイント

- **デモの途中でやることが初期化される** → `--reload` で起動していると、誰かがファイルを
  保存したときにサーバーが再起動する。`MIMAMORI_DEMO=1` の台帳はプロセス内にあるので消える。
  見せるとき・録画するときは `--reload` を外して起動する
- **`No matching distribution found for google-genai`** → `python3` が 3.9 になっている。
  `google-genai` は 3.10 以上が必要。`python3.13 -m venv .venv` のように版を指定して作り直す
- **`404 Not Found` on insert** → カレンダーをサービスアカウントに共有できていない
- **終日予定が1日ずれる** → Calendar API の `end.date` は排他。`calendar_tools._body` で +1 日している
- **`403 Vertex AI API has not been used`** → `gcloud services enable aiplatform.googleapis.com`
- **ADK のバージョン差** → `agent.py` の `InMemoryRunner` / `run_async` のシグネチャが版で変わることがある

## 残りタスク

正本は [`docs/WBS.md`](docs/WBS.md)（全タスクに DoD つき）。いまの状態と次の手は [`docs/現在地.md`](docs/現在地.md)。
要約は上の「いまどこまで動くか」。
