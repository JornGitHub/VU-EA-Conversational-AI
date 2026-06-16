"""High-level chatbot functions combining retrieval with optional LLM wording."""

from __future__ import annotations

from src.definitions.search import answer_definition_question_json
from src.llm.ollama_client import generate_with_ollama
from src.llm.prompt_builder import build_grounded_prompt


def answer_with_llm(
    query: str,
    model: str = "qwen3:30b-instruct",
    debug: bool = False,
) -> dict:
    """Return an LLM-formulated Dutch answer grounded in retrieval output."""
    retrieval_result = answer_definition_question_json(query, debug=debug)
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
