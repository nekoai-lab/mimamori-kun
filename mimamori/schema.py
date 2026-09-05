"""おたよりから抜き出す構造。UI と Calendar 登録の共通言語。"""
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

Kind = Literal["event", "deadline", "homework", "bring"]


class Item(BaseModel):
    """おたより1枚から取れた、カレンダーに載る単位ひとつ。"""

    @model_validator(mode="before")
    @classmethod
    def _null_to_default(cls, data: Any) -> Any:
        """モデルは空欄を null で返すことがある。既定値のある項目は既定値に落とす。

        既定値はキーが無いときにしか効かないので、null が来ると弾かれる。
        補足のないおたよりで note が null になり、抽出全体が 500 で落ちていた。
        kind / title / child / date は必須のまま。null なら落として人に見せる。
        """
        if not isinstance(data, dict):
            return data
        return {
            k: v
            for k, v in data.items()
            if not (v is None and k in cls.model_fields and not cls.model_fields[k].is_required())
        }

    kind: Kind = Field(description="event=行事 / deadline=提出期限 / homework=宿題 / bring=持ち物")
    title: str = Field(description="カレンダーに出す短い件名。子どもの名前を先頭に付ける")
    child: str = Field(description="どの子のものか。判別できなければ '不明'")
    school_level: str = Field(default="unknown", description="elementary / junior_high / unknown")
    date: str = Field(description="YYYY-MM-DD。締切なら締切日、行事なら開催日")
    end_date: Optional[str] = Field(default=None, description="複数日にまたがる場合の最終日 YYYY-MM-DD")
    time_start: Optional[str] = Field(default=None, description="HH:MM。終日なら null")
    time_end: Optional[str] = Field(default=None, description="HH:MM。終日なら null")
    bring: List[str] = Field(default_factory=list, description="持ち物・準備するもの")
    note: str = Field(default="", description="補足。金額や集合場所など")
    source_text: str = Field(default="", description="根拠になった原文の抜粋。ユーザーが検算するため")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="読み取りの確からしさ")
    needs_review: bool = Field(default=False, description="日付が曖昧、子どもが不明など、人が見るべきもの")
    duplicate_of: Optional[str] = Field(
        default=None, description="既存カレンダー予定と重複していると判断した場合、その予定の件名"
    )


class Extraction(BaseModel):
    summary: str = Field(description="このおたよりが何だったか、1〜2文")
    items: List[Item] = Field(default_factory=list)
