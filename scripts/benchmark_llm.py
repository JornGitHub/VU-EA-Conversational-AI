#!/usr/bin/env python3
"""Measure how fast the local LLM layer answers on this machine.

Answer speed on a laptop is decided by three things: the size of the model, the
size of the prompt, and whether the model is already loaded. This script reports
all three so you can pick a model that is comfortable on your hardware.

    python scripts/benchmark_llm.py
    python scripts/benchmark_llm.py --model qwen3:4b
    python scripts/benchmark_llm.py --model qwen3:1.7b --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chatbot import retrieve
from src.llm.ollama_client import DEFAULT_BASE_URL, stream_with_ollama, warm_up
from src.llm.ollama_setup import DEFAULT_OLLAMA_MODEL
from src.llm.prompt_builder import build_grounded_prompt

QUESTIONS = [
    "wat is een internationale student?",
    "wat betekent Opleiding actueel equivalent?",
    "wat is een onechte neveninschrijving?",
]


def measure(question: str, model: str, base_url: str) -> dict[str, object]:
    """Answer one question and report prompt size, first-token and total time."""
    payload = retrieve(question, web_mode="off")
    prompt = build_grounded_prompt(question, payload)

    start = time.perf_counter()
    first_token: float | None = None
    answer = ""
    for fragment in stream_with_ollama(prompt, model=model, base_url=base_url):
        if first_token is None:
            first_token = time.perf_counter() - start
        answer += fragment
    total = time.perf_counter() - start

    return {
        "question": question,
        "prompt_chars": len(prompt),
        "prompt_tokens_estimate": len(prompt) // 4,
        "first_token_seconds": round(first_token or total, 1),
        "total_seconds": round(total, 1),
        "answer_chars": len(answer),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help=f"Ollama model (default: {DEFAULT_OLLAMA_MODEL}).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Ollama base URL (default: {DEFAULT_BASE_URL}).")
    parser.add_argument("--questions", type=int, default=len(QUESTIONS), help="How many questions to run.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a readable table.")
    args = parser.parse_args(argv)

    load_start = time.perf_counter()
    loaded = warm_up(args.model, args.base_url, timeout=900)
    load_seconds = round(time.perf_counter() - load_start, 1)
    if not loaded:
        print(f"Model '{args.model}' kon niet geladen worden.")
        print(f"Draait Ollama? Is het model aanwezig? Zo niet: ollama pull {args.model}")
        return 1

    try:
        runs = [measure(question, args.model, args.base_url) for question in QUESTIONS[: max(1, args.questions)]]
    except RuntimeError as exc:
        print(f"LLM-benchmark mislukt: {exc}")
        return 1

    report = {"model": args.model, "model_load_seconds": load_seconds, "runs": runs}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"LLM-benchmark met model '{args.model}'")
    print(f"  model laden (eenmalig): {load_seconds}s")
    for run in runs:
        print(
            f"  {str(run['question'])[:44]:46} prompt ~{run['prompt_tokens_estimate']:>5} tokens | "
            f"eerste woord na {run['first_token_seconds']:>5}s | klaar in {run['total_seconds']:>5}s"
        )
    slowest = max(run["first_token_seconds"] for run in runs)
    if slowest > 15:
        print("\nEerste woord duurt lang op deze machine. Kies een kleiner model, bijvoorbeeld:")
        print("  python main.py --model qwen3:4b     (of qwen3:1.7b)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
