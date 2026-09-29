"""環境変数まわり。Cloud Run では --set-env-vars で渡す。"""
import logging
import os
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


def _thinking_budget() -> int:
    raw = os.getenv("MIMAMORI_THINKING_BUDGET", "512")
    try:
        budget = int(raw)
        if budget >= 0:
            return budget
    except ValueError:
        pass
    logger.warning("MIMAMORI_THINKING_BUDGET must be a non-negative integer; using default")
    return 512


def validate_quota_project() -> None:
    """ローカルのクラウド利用では、環境変数だけで課金先を確認する。"""
    if "K_SERVICE" in os.environ:
        return
    uses_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"true", "1"}
    if not uses_vertex and os.getenv("MIMAMORI_LEDGER") != "firestore":
        return
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    quota_project = os.getenv("GOOGLE_CLOUD_QUOTA_PROJECT", "")
    if not project.strip() or not quota_project.strip() or quota_project != project:
        raise RuntimeError(
            "GOOGLE_CLOUD_QUOTA_PROJECT が GOOGLE_CLOUD_PROJECT と一致していません。"
            "課金先を固定するため、.env に GOOGLE_CLOUD_QUOTA_PROJECT を入れてください。"
        )


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


def _reminders(name="MIMAMORI_REMINDERS_TIMED", default=(1200, 60)):
    raw = os.getenv(name)
    if raw is None:
        raw = os.getenv("MIMAMORI_REMINDERS", "") if name == "MIMAMORI_REMINDERS_TIMED" else ""
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.append(int(chunk))
    return out or list(default)


@dataclass
class Config:
    project: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    location: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))
    model: str = field(default_factory=lambda: os.getenv("MIMAMORI_MODEL", "gemini-2.5-flash"))
    thinking_budget: int = field(default_factory=_thinking_budget)
    calendar_id: str = field(default_factory=lambda: os.getenv("MIMAMORI_CALENDAR_ID", "primary"))
    timezone: str = field(default_factory=lambda: os.getenv("MIMAMORI_TZ", "Asia/Tokyo"))
    children: list = field(default_factory=_children)
    reminders_timed: list = field(default_factory=_reminders)
    reminders_allday: list = field(
        default_factory=lambda: _reminders("MIMAMORI_REMINDERS_ALLDAY", (360,))
    )

    @property
    def children_label(self) -> str:
        jp = {"elementary": "小学校", "junior_high": "中学校", "unknown": "不明"}
        return "、".join(
            f"{c['name']}（{jp.get(c['school_level'], c['school_level'])}）" for c in self.children
        )


config = Config()
