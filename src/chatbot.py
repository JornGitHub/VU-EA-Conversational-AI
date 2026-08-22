"""High-level chatbot functions combining retrieval with optional LLM wording."""

from __future__ import annotations

from typing import Any, Iterator, Sequence

from src.definitions.mock_data import examples_for_fields
from src.definitions.search import answer_deep_context_question_json, answer_definition_question_json
from src.llm.ollama_client import generate_with_ollama, stream_with_ollama
from src.llm.ollama_setup import DEFAULT_OLLAMA_MODEL
from src.llm.prompt_builder import build_grounded_prompt


def answer_with_llm(
    query: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    debug: bool = False,
    source_focus: str = "primary",
    include_supplemental: bool = True,
    deep_context: bool = False,
    web_mode: str = "fallback",
    allow_external_web: bool = False,
    allow_web_sources: bool | None = None,
    allow_llm_inference: bool = True,
) -> dict:
    """Return an LLM-formulated Dutch answer grounded in retrieval output."""
    if deep_context:
        retrieval_result = answer_deep_context_question_json(query, debug=debug, source_focus=source_focus, include_supplemental=include_supplemental, web_mode=web_mode, allow_external_web=allow_external_web, allow_llm_inference=allow_llm_inference, allow_web_sources=allow_web_sources)
    else:
        retrieval_result = answer_definition_question_json(query, debug=debug, source_focus=source_focus, include_supplemental=include_supplemental, web_mode=web_mode)
    prompt = build_grounded_prompt(query, retrieval_result)  # compact, budgeted

    try:
        llm_answer = generate_with_ollama(prompt, model=model)
    except Exception as exc:  # noqa: BLE001 - keep apps usable when local Ollama fails.
        result = {
            "query": query,
            "model": model,
            "llm_answer": None,
            "error": str(exc),
            "retrieval_result": retrieval_result,
        }
        if debug:
            result["prompt"] = prompt
        return result

    result = {
        "query": query,
        "model": model,
        "llm_answer": llm_answer,
        "retrieval_result": retrieval_result,
    }
    if debug:
        result["prompt"] = prompt
    return result


def retrieve(
    query: str,
    *,
    deep_context: bool = True,
    debug: bool = False,
    source_focus: str = "primary",
    include_supplemental: bool = True,
    web_mode: str = "fallback",
    allow_external_web: bool = False,
    allow_llm_inference: bool = True,
    use_semantic: bool = True,
    include_synthetic_examples: bool = False,
) -> dict[str, Any]:
    """Return retrieval output only, without touching the LLM.

    The chat UI needs the grounded payload before it starts streaming an answer,
    and questions can be answered from this payload alone when no LLM is used.

    ``include_synthetic_examples`` attaches example values from the synthetic
    dataset under their own key. They never reach the answer text or the LLM
    prompt: invented counts must not be able to pass for evidence.
    """
    if deep_context:
        result = answer_deep_context_question_json(
            query,
            debug=debug,
            source_focus=source_focus,
            include_supplemental=include_supplemental,
            web_mode=web_mode,
            allow_external_web=allow_external_web,
            allow_llm_inference=allow_llm_inference,
            use_semantic=use_semantic,
        )
    else:
        result = answer_definition_question_json(
            query,
            debug=debug,
            source_focus=source_focus,
            include_supplemental=include_supplemental,
            web_mode=web_mode,
            use_semantic=use_semantic,
        )
    if include_synthetic_examples:
        result["synthetic_examples"] = examples_for_fields(result.get("matched_fields") or [])
    return result


def build_chat_prompt(query: str, retrieval_result: dict[str, Any], history: Sequence[Any] | None = None) -> str:
    """Return the grounded prompt, including a short conversation context.

    The prompt builder keeps every section within a budget, so the prompt stays
    small enough for a local model to process quickly.
    """
    return build_grounded_prompt(query, retrieval_result, history or [])


def stream_llm_answer(
    query: str,
    retrieval_result: dict[str, Any],
    model: str = DEFAULT_OLLAMA_MODEL,
    history: Sequence[Any] | None = None,
) -> Iterator[str]:
    """Stream a grounded answer for an already-computed retrieval payload."""
    yield from stream_with_ollama(build_chat_prompt(query, retrieval_result, history), model=model)
