"""Conversation helpers: turn history and follow-up question resolution."""

from .context import (
    Turn,
    format_history_for_prompt,
    is_followup_question,
    resolve_followup_query,
)

__all__ = [
    "Turn",
    "format_history_for_prompt",
    "is_followup_question",
    "resolve_followup_query",
]
