"""Make follow-up questions work in a chat without changing the retrieval layer.

A chat user writes "en op peildatum?" or "waarom telt die niet mee?" instead of
repeating the subject. Retrieval is stateless and scores such a question against
the whole corpus, which usually finds nothing. This module detects those turns
and rewrites the question with the subject of the previous answer appended, so
the existing intent detection and lexical ranking keep working unchanged.

The rewrite is always visible to the caller (and shown in the UI), never silent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from src.definitions.text_utils import normalize_text, tokenize

# Openers that only make sense as a continuation of the previous question.
FOLLOWUP_OPENERS = (
    "en ",
    "en?",
    "maar ",
    "waarom",
    "hoezo",
    "hoe dan",
    "en dan",
    "wat dan",
    "en hoe",
    "en wat",
    "en welke",
    "en waar",
    "klopt dat",
    "geef een voorbeeld",
    "leg uit",
    "waarom niet",
    "en als",
)

# Words that point back at something already discussed.
BACKREFERENCE_WORDS = {
    "die",
    "dat",
    "deze",
    "dit",
    "hiervan",
    "daarvan",
    "ervan",
    "hiermee",
    "daarmee",
    "hierover",
    "daarover",
    "hierbij",
    "daarbij",
    "ze",
    "hun",
    "zulke",
    "zo",
}

SHORT_QUESTION_TOKENS = 3
MAX_HISTORY_TURNS_IN_PROMPT = 3


@dataclass
class Turn:
    """One completed question/answer exchange."""

    question: str
    answer: str
    main_term: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def _as_turn(item: Any) -> Turn | None:
    if isinstance(item, Turn):
        return item
    if isinstance(item, dict):
        return Turn(
            question=str(item.get("question", "")),
            answer=str(item.get("answer", "")),
            main_term=item.get("main_term"),
            payload=item.get("payload") or {},
        )
    return None


def last_subject(history: Sequence[Any]) -> str | None:
    """Return the most recent answered subject, if any."""
    for item in reversed(list(history)):
        turn = _as_turn(item)
        if turn and turn.main_term:
            return str(turn.main_term)
    return None


def is_followup_question(query: str, history: Sequence[Any]) -> bool:
    """Return True when this question only makes sense with the previous subject."""
    if not last_subject(history):
        return False

    normalized = normalize_text(query)
    if not normalized:
        return False

    openers = tuple(opener.strip() for opener in FOLLOWUP_OPENERS if opener.strip())
    if normalized in openers or normalized.startswith(tuple(f"{opener} " for opener in openers)):
        return True

    words = normalized.split()
    tokens = tokenize(query)
    if len(tokens) <= SHORT_QUESTION_TOKENS and any(word in BACKREFERENCE_WORDS for word in words):
        return True
    # Nothing but stopwords/pronouns left: the subject must come from the chat.
    if not tokens:
        return True
    return False


def resolve_followup_query(query: str, history: Sequence[Any]) -> tuple[str, str | None]:
    """Return ``(effective_query, subject)`` for one chat turn.

    ``subject`` is None when the question was used as typed. The subject is
    appended in parentheses so phrase-based intent detection ("wat is ...")
    still sees the user's own wording first.
    """
    subject = last_subject(history)
    if not subject or not is_followup_question(query, history):
        return query, None
    if normalize_text(subject) in normalize_text(query):
        return query, None
    return f"{query.strip()} ({subject})", subject


def format_history_for_prompt(history: Sequence[Any], limit: int = MAX_HISTORY_TURNS_IN_PROMPT) -> str:
    """Render recent turns for the LLM prompt, so pronouns resolve naturally."""
    turns = [turn for turn in (_as_turn(item) for item in history) if turn and turn.question]
    if not turns:
        return ""
    lines = ["Eerdere vragen in dit gesprek (alleen als context voor verwijswoorden):"]
    for turn in turns[-max(1, limit):]:
        answer = " ".join(str(turn.answer).split())
        lines.append(f"- Vraag: {turn.question}")
        lines.append(f"  Antwoord (samengevat): {answer[:300]}")
    return "\n".join(lines)
