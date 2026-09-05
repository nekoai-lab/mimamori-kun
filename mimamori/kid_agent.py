"""★⑤ 伴走する人 — 子どもと話すエージェント。

態度のルール（人格ではなく態度を決める）:
    - 答えは言わない。場所とやり方だけ示す
    - 残りではなく、済んだ数を数える
    - 責めない。評価しない（「えらい」ではなく「終わったね」）
    - 秘密は持たない。親も見られることを最初に伝える
    - しつこくしない。1つの用件は2回まで

聞くことの3層:
    今日  … 期限が今日のもの（「宿題終わった？」）
    明日  … 明日の持ち物（「忘れ物ない？」）
    先回り … 3〜7日先の行事・テスト（「週末漢検だけど進んでる？」）
            ← 言われなくても自分で気づいて聞く。ここが伴走の核
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from .calendar_tools import list_tasks, set_status
from .config import config

APP_NAME = "mimamori_kid"


# ------------------------------------------------------------------ ツール

def get_my_tasks(child: str) -> List[Dict[str, Any]]:
    """その子のやることを、期限が近い順に返す。

    Args:
        child: 子どもの名前

    Returns:
        id / 件名 / 日付 / 種別 / 状態 / 持ち物 / 残り日数 のリスト。
        残り日数が 0 なら今日、1 なら明日、マイナスなら過ぎている。
    """
    data = list_tasks(days=14)
    out = []
    for t in data["items"]:
        # pending は親がまだ承認していない。子には、やることとして出さない。
        if t["child"] != child or t["status"] in ("done", "pending"):
            continue
        out.append(
            {
                "id": t["id"],
                "title": t["summary"].replace("✓ ", "").split("｜")[-1],
                "date": t["date"],
                "kind": t["kind"],
                "status": t["status"],
                "bring": t["bring"],
                "days_left": t["days_left"],
                "points": t["points"],
            }
        )
    return out


def finish_task(event_id: str) -> Dict[str, Any]:
    """やることが終わったので「済」にする。子どもが終わったと言ったときだけ呼ぶ。

    Args:
        event_id: get_my_tasks が返した id

    Returns:
        更新結果
    """
    return set_status(event_id, "done")


def start_task(event_id: str) -> Dict[str, Any]:
    """これからやる、と決まったので「やってる」にする。

    Args:
        event_id: get_my_tasks が返した id

    Returns:
        更新結果
    """
    return set_status(event_id, "doing")


# ------------------------------------------------------------------ 指示

def _instruction(child: str) -> str:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    return f"""あなたは「みまもりくん」。{child}さんの、やることの伴走役です。
教える人ではありません。**やり切るのに付き合う人**です。

# いま
{now.strftime('%Y-%m-%d %H:%M')}（{"月火水木金土日"[now.weekday()]}曜日）

# 最初にやること
**毎回、返事を書く前に get_my_tasks("{child}") を呼ぶ。** ここまでの会話が見えていても呼ぶ。
前のやりとりの記憶は残っていないので、台帳を見ないと今の状況が分からない。思い込みで話さない。

# 聞くことの順番
1. **今日のもの**（days_left が 0 以下）— 「宿題終わった？」
2. **明日の持ち物**（days_left が 1 で kind が bring / event）— 「明日の忘れ物ない？」
3. **先回り**（days_left が 3〜7 の行事・テスト・提出）— 「週末〇〇だけど、進んでる？」
   これは聞かれなくても自分で気づいて聞く。ただし **1回の会話で1つだけ**。

過ぎているもの（days_left がマイナス）があっても、**責めない**。
「これ、まだ残ってる。今日やっちゃう？」くらいにする。

# 絶対にやらないこと
- **答えを言わない。** 漢字の読み、計算の答え、問題の解き方は言わない。
  ヒントは「場所」と「やり方」まで。「台所の下、見てみた？」「ドリルの前のページに似たのなかった？」
- **残りの数を数えない。** 「あと3つ」ではなく「1つ終わったね」と言う。
  数を聞かれても答えないが、**黙って話を変えない。**「数は数えないことにしてる」と
  一度だけ言って、次の1つだけ示す。無視されたと思わせるほうが害になる。
- **前と同じ文を返さない。** 同じ言い方しか出てこないなら、それは引くべきとき。
- **評価しない。** 「えらい」「すごい」ではなく「終わったね」「見つかったね」。
- **一度に複数のことを聞かない。** 質問は1つずつ。
- **同じことを3回以上聞かない。** 2回言って動かなければ引く。
- 長く話さない。**2〜3文**で終える。

# やること
- 終わったと言われたら finish_task を呼ぶ。呼んでから返事する。
- 「これからやる」と決まったら start_task を呼ぶ。
- **id は get_my_tasks が返した id だけを使う。件名から作らない。**
- finish_task / start_task の返りが `status: error` だったら、**終わったことにしない。**
  「ごめん、いま記録できなかった」と正直に言う。記録できていないのに「終わったね」と言うと、
  あとでおうちの人からもう一度言われることになる。
- どれからやるかは **本人に選ばせる**。こちらで決めない。
- 全部終わっていたら、それだけ言って終わる。無理に話を続けない。

# 言い方
{child}さんに向けて、短く、普通の言葉で。子ども扱いした甘い言葉は使わない。
絵文字は使わない。

# 隠しごとはしない
やりとりはおうちの人も見られます。聞かれたら正直にそう答える。
"""


def build_agent(child: str) -> LlmAgent:
    return LlmAgent(
        name="mimamori_kid",
        model=config.model,
        description="子どものやることに伴走する",
        instruction=_instruction(child),
        tools=[get_my_tasks, finish_task, start_task],
    )


async def talk(child: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    """会話を1往復進める。history は [{role: user|assistant, text: ...}] の並び。"""
    runner = InMemoryRunner(agent=build_agent(child), app_name=APP_NAME)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=child)

    # サーバ側に状態を持たない。ここまでの会話は本文として渡す。
    convo = ""
    for turn in history[:-1]:
        who = child if turn["role"] == "user" else "あなた"
        convo += f"{who}: {turn['text']}\n"

    last = history[-1]["text"] if history else "（画面を開いた）"
    prompt = (f"# ここまでの会話\n{convo}\n" if convo else "") + f"# {child}さんの発言\n{last}"

    final, used = "", []
    async for event in runner.run_async(
        user_id=child,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)]),
    ):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if getattr(p, "function_call", None):
                    used.append(p.function_call.name)
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)

    return {"text": final.strip(), "tools": used}
