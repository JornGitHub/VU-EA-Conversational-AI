"""High-level chatbot functions combining retrieval with optional LLM wording."""

from __future__ import annotations

from src.definitions.search import answer_deep_context_question_json, answer_definition_question_json
from src.llm.ollama_client import generate_with_ollama
from src.llm.prompt_builder import build_grounded_prompt


def answer_with_llm(
    query: str,
    model: str = "qwen3:30b-instruct",
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
    prompt = build_grounded_prompt(query, retrieval_result)

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
