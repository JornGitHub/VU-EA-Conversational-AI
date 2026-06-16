"""Command-line wrapper for the reusable HO definition retrieval module.

The search, ranking, grouping and answer-building logic lives in
``src.definitions.search`` so Streamlit, FastAPI, Flask or a local chatbot can
reuse the same dependency-free retrieval layer.
"""

from __future__ import annotations

import argparse
import json

from src.definitions.search import (
    DEMO_QUERY,
    answer_definition_question,
    answer_definition_question_json,
)

USAGE_TEXT = """Gebruik:
  python zoek_definities_voorbeeld.py "wat is een internationale student?"
  python zoek_definities_voorbeeld.py "waar vind ik data over internationale studenten?"
  python zoek_definities_voorbeeld.py "wat telt als student?" --debug
  python zoek_definities_voorbeeld.py "waar vind ik data over internationale studenten?" --json
  python zoek_definities_voorbeeld.py "wat is een internationale student?" --llm
  python zoek_definities_voorbeeld.py --demo
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zoek in HO-definities en toon een conversational antwoord.",
        epilog=(
            'Voorbeelden:\n'
            '  python zoek_definities_voorbeeld.py "wat is een internationale student?"\n'
            '  python zoek_definities_voorbeeld.py "waar vind ik data over internationale studenten?"\n'
            '  python zoek_definities_voorbeeld.py "wat telt als student?" --debug\n'
            '  python zoek_definities_voorbeeld.py "waar vind ik data over internationale studenten?" --json\n'
            '  python zoek_definities_voorbeeld.py "wat is een internationale student?" --llm'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="Vraag of zoekterm.")
    parser.add_argument("--debug", action="store_true", help="Toon ook ruwe, gerankte zoekmatches met scores.")
    parser.add_argument("--json", action="store_true", help="Geef het antwoord terug als gestructureerde JSON.")
    parser.add_argument("--llm", action="store_true", help="Formuleer het antwoord met een lokale Ollama-LLM.")
    parser.add_argument("--model", default="qwen3:8b", help="Ollama-model voor --llm.")
    parser.add_argument("--demo", action="store_true", help="Draai een expliciete demoquery over internationale studenten.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    query = DEMO_QUERY if args.demo else args.query
    if not query:
        print(USAGE_TEXT)
        return

    if args.llm:
        from src.chatbot import answer_with_llm

        payload = answer_with_llm(query, model=args.model, debug=args.debug)
        if payload.get("llm_answer"):
            print(payload["llm_answer"])
        else:
            print("De LLM kon geen antwoord genereren.")
            print(payload.get("error", "Onbekende fout."))
            print("\nTerugval naar het normale retrieval-antwoord:\n")
            print(answer_definition_question(query, debug=args.debug))
    elif args.json:
        payload = answer_definition_question_json(query, debug=args.debug)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(answer_definition_question(query, debug=args.debug))


if __name__ == "__main__":
    main()
