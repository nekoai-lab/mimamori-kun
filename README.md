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

書き込みは保護者が画面で確認してから。**読み取りと判断は自律、処置は承認。**

## 画面

| URL | 誰が | 何をする |
|---|---|---|
| `/` | 親（または子） | おたよりを撮る → 抽出結果を確認 → カレンダーに登録 |
| `/board` | 親 | タスク一覧と予定。遅れているものが最上部。子ども別チップ、ポイント |
| `/kid` | 子 | 撮る／話す／終わらせる。★⑤ 伴走する人 |

`/board` と `/kid` は `MIMAMORI_DEMO=1` を付けるとダミーのタスクで動く（`/kid` の会話は Gemini が必要）。

## いまどこまで動くか（2026-09-05 時点）

| | 状態 |
|---|---|
| `/kid` の会話 | **動く。** 今日のやることを聞かれ、「終わった」と言うと `/board` から外れる |
| 先回り（3〜7日先の行事を自分で聞く） | **動く。** 1回の会話で1つだけ |
| 態度の禁止事項 | **会話ログで確認済み。** 答えを4回求めても言わない／数を答えない／評価しない／責めない |
| `/board` のやること一覧 | **動く。** 遅れているものが最上部 |
| `/` のおたより抽出 → 承認 → 登録 | 実装済み。`samples/` の2枚での通し確認は未 |
| `/reward` の交換画面 | **未作成。** `static/reward.html` を置けば表示される |
| 交換レートの保存 | **未実装。** `points.set_rewards` が `NotImplementedError` |
| 本物のカレンダーへの書き込み | 実装済み。今日は `MIMAMORI_DEMO=1` で繋いでいない |

## 画面と API の契約

画面は自分の口だけを叩く。口の形を変えるときは、使っている画面の持ち主に声をかける。

| 画面 | 叩く口 |
|---|---|
| `/`（index.html） | `/api/config` `/api/extract` `/api/register` |
| `/kid`（kid.html） | `/api/config` `/api/extract` `/api/register` `/api/tasks` `/api/kid/chat` |
| `/board`（board.html） | `/api/config` `/api/tasks` `/api/status` |
| `/reward`（未作成） | `/api/points` `/api/rewards` ← **この2つはまだ誰も使っていない。空いている** |

`mimamori/points.py` は、この5つのシグネチャを保てば `main.py` と繋がる。中身は作り替えてよい。

```python
balance(child) -> int
history(child, limit=30) -> list[dict]
get_rewards() -> list[dict]
set_rewards(rewards) -> dict     # 未実装。NotImplementedError なら 501 が返る
points_for(kind, fixed_count=0) -> int
RULES: dict                      # calendar_tools._points_for と値を揃えること
```

## 台帳は Google カレンダー

新しいDBは作らない。予定の `extendedProperties.private` に
`app / child / kind / status / points / bring` を持たせ、`/board` はそれを読むだけ。
カレンダー側で人が手で直しても整合が壊れない。完了しても予定は消さず、件名に ✓ を付けて残す。

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

| 層 | 使うもの |
|---|---|
| エージェント | Google ADK (`LlmAgent` + `list_events` ツール) |
| モデル | Vertex AI Gemini |
| カレンダー | Google Calendar API（実行サービスアカウントの ADC） |
| API / UI | FastAPI + 単一 HTML |
| 実行環境 | Cloud Run |

```
mimamori-kun/
├── main.py                  FastAPI。画面と API の入口
├── mimamori/
│   ├── config.py            環境変数
│   ├── schema.py            抽出結果の型
│   ├── calendar_tools.py    カレンダーの読み書き（台帳）
│   ├── agent.py             おたよりを読むエージェント
│   ├── kid_agent.py         子どもと話すエージェント（★⑤）
│   └── points.py            ポイントと交換        ← 共同開発者
├── static/
│   ├── index.html           撮る → 確認 → 登録（親）
│   ├── board.html           やること一覧（親）
│   ├── kid.html             会話画面（子）        ← 共同開発者
│   └── reward.html          交換画面              ← 共同開発者・未作成
├── samples/                 テスト用のダミーおたより
├── docs/分担.md             担当・決定事項・動作確認済みの版
├── Dockerfile
└── deploy.sh
```

**誰がどのファイルを持つかは [`docs/分担.md`](docs/分担.md) にある。**
表にないファイルを触るときは先に一声かける。PRは回さず main に直コミット、push 前に `git pull --rebase`。

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

- **`No matching distribution found for google-genai`** → `python3` が 3.9 になっている。
  `google-genai` は 3.10 以上が必要。`python3.13 -m venv .venv` のように版を指定して作り直す
- **`404 Not Found` on insert** → カレンダーをサービスアカウントに共有できていない
- **終日予定が1日ずれる** → Calendar API の `end.date` は排他。`calendar_tools._body` で +1 日している
- **`403 Vertex AI API has not been used`** → `gcloud services enable aiplatform.googleapis.com`
- **ADK のバージョン差** → `agent.py` の `InMemoryRunner` / `run_async` のシグネチャが版で変わることがある

## 今後の進め方

### 次にやること（上から順に）

1. **共同開発者** — `static/reward.html` を作る。`/api/points?child=名前` と `/api/rewards` は
   すでに動いているので、fetch するだけで残高・履歴・交換候補が返る。`main.py` はファイルの有無を
   リクエストごとに見るので、置いた瞬間から `/reward` に出る（再起動不要）
2. **共同開発者** — `points.set_rewards` を実装する。保存先の案は `mimamori/points.py` の
   TODO に3つ書いてある（環境変数のまま／カレンダーに設定用の予定を1つ作る／Firestore）。
   今日は環境変数のままで十分
3. **奈緒美** — `/kid` を素で触って、崩れたところを会話ログで渡す。
   台本ではない言い方（言い直す、話が飛ぶ、無言）で崩れ方が変わる
4. `samples/` の2枚で `/` の通し（抽出 → 重複照会 → 承認 → 登録）を確認する

### 決めていない判断が2つある

- **「2回言って動かなければ引く」を件単位にするか、会話単位にするか。**
  いまは件単位で、断られた用件からは引くが別の用件では声をかけ得る。会話単位にすると確実に止まる
  代わりに、伴走の核である先回りがその会話では効かなくなる。態度の決定事項なので相談して決める
- **`/kid` からの登録に承認を挟むか。**
  いまの `kid.html` は `/api/extract` の直後に `/api/register` を呼んでいて、親が見る段階がない。
  上に書いた「処置は承認」と食い違っている。外から来た画像を LLM に読ませる経路なので、
  インジェクションの入口が書き込みに直結している状態

### そのあと（今日はやらない）

- Cloud Run へのデプロイ
- 本物の Google カレンダー接続（`MIMAMORI_DEMO` を 0 にして、カレンダーをサービスアカウントに共有）
- 実物のおたよりでの検証
- LINE通知

## 今日やらなかったこと

- Google ToDo リストへの反映（Tasks API は OAuth ユーザー認証が必須で、当日の時間に合わない）
- 学校アプリからの自動取り込み（今はスクリーンショットを撮って渡す）
- 複数枚まとめて投入
