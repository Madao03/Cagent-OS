from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

PROMPT_TIMEZONE = ZoneInfo("Asia/Shanghai")
PROMPT_TIMEZONE_NAME = "Asia/Shanghai"
TIME_SENSITIVITY_GUARDRAILS = (
    "Treat the current datetime as a high-priority constraint.",
    "Resolve any relative date words like today, yesterday, tomorrow, latest, and current against this timestamp before answering.",
    "When time sensitivity matters, cite the concrete date and timezone instead of relying on relative phrasing.",
)


def render_prompt_datetime_context(now: datetime | None = None) -> str:
    current = now.astimezone(PROMPT_TIMEZONE) if now is not None else datetime.now(PROMPT_TIMEZONE)
    return "\n".join([
        "# Current DateTime",
        f"- now: {current.isoformat(timespec='seconds')}",
        f"- timezone: {PROMPT_TIMEZONE_NAME}",
        *(f"- {line}" for line in TIME_SENSITIVITY_GUARDRAILS),
    ])


def render_prompt_datetime_xml_context(now: datetime | None = None) -> str:
    current = now.astimezone(PROMPT_TIMEZONE) if now is not None else datetime.now(PROMPT_TIMEZONE)
    return "\n".join([
        "<current_datetime>",
        f"<now>{current.isoformat(timespec='seconds')}</now>",
        f"<current_date>{current.date().isoformat()}</current_date>",
        f"<timezone>{PROMPT_TIMEZONE_NAME}</timezone>",
        *(f"<instruction>{line}</instruction>" for line in TIME_SENSITIVITY_GUARDRAILS),
        "</current_datetime>",
    ])
