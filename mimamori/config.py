"""環境変数まわり。Cloud Run では --set-env-vars で渡す。"""
import os
from dataclasses import dataclass, field


def _children():
    raw = os.getenv("MIMAMORI_CHILDREN", "上の子:junior_high,下の子:elementary")
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, level = chunk.partition(":")
        out.append({"name": name.strip(), "school_level": (level or "unknown").strip()})
    return out


def _reminders():
    raw = os.getenv("MIMAMORI_REMINDERS", "1200,60")
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.append(int(chunk))
    return out or [1200, 60]


@dataclass
class Config:
    project: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    location: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))
    model: str = field(default_factory=lambda: os.getenv("MIMAMORI_MODEL", "gemini-2.5-flash"))
    calendar_id: str = field(default_factory=lambda: os.getenv("MIMAMORI_CALENDAR_ID", "primary"))
    timezone: str = field(default_factory=lambda: os.getenv("MIMAMORI_TZ", "Asia/Tokyo"))
    children: list = field(default_factory=_children)
    reminders: list = field(default_factory=_reminders)

    @property
    def children_label(self) -> str:
        jp = {"elementary": "小学校", "junior_high": "中学校", "unknown": "不明"}
        return "、".join(
            f"{c['name']}（{jp.get(c['school_level'], c['school_level'])}）" for c in self.children
        )


config = Config()
