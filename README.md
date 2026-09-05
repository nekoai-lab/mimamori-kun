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
- 評価しない。「えらい」ではなく「終わったね」
- 質問は1つずつ。同じことは2回まで
- 秘密を持たない。親も見られることを画面にも明示

## 構成

| 層 | 使うもの |
|---|---|
| エージェント | Google ADK (`LlmAgent` + `list_events` ツール) |
| モデル | Vertex AI Gemini |
| カレンダー | Google Calendar API（実行サービスアカウントの ADC） |
| API / UI | FastAPI + 単一 HTML |
| 実行環境 | Cloud Run |

```
app/
├── main.py                  FastAPI（/api/extract, /api/register）
├── mimamori/
│   ├── config.py            環境変数
│   ├── schema.py            抽出結果の型
│   ├── calendar_tools.py    list_events / create_events
│   └── agent.py             ADK エージェントと実行
├── static/index.html        撮る → 確認 → 登録 の1画面
├── samples/                 テスト用のダミーおたより
├── Dockerfile
└── deploy.sh
```

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

- **`404 Not Found` on insert** → カレンダーをサービスアカウントに共有できていない
- **終日予定が1日ずれる** → Calendar API の `end.date` は排他。`calendar_tools._body` で +1 日している
- **`403 Vertex AI API has not been used`** → `gcloud services enable aiplatform.googleapis.com`
- **ADK のバージョン差** → `agent.py` の `InMemoryRunner` / `run_async` のシグネチャが版で変わることがある

## 今日やらなかったこと

- Google ToDo リストへの反映（Tasks API は OAuth ユーザー認証が必須で、当日の時間に合わない）
- 学校アプリからの自動取り込み（今はスクリーンショットを撮って渡す）
- 複数枚まとめて投入
