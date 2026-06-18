"""Build strict grounded prompts for the optional LLM formulation layer."""

from __future__ import annotations

import json


def build_grounded_prompt(user_query: str, retrieval_result: dict) -> str:
    """Return a Dutch prompt grounded only in the retrieval result.

    The retrieval JSON is the source of truth. The LLM receives explicit
    instructions to formulate naturally without adding unsupported facts.
    """
    retrieval_json = json.dumps(retrieval_result, ensure_ascii=False, indent=2)
    return f"""Je bent een assistent voor Nederlandse hoger-onderwijsdata.

Beantwoord de vraag van de gebruiker uitsluitend op basis van de retrieval-output hieronder.
De retrieval-output is de enige bron van waarheid.

Regels:
- Verzin geen definities.
- Verzin geen velden.
- Verzin geen databestanden.
- Verzin geen bronbestanden.
- Verzin geen notes of aandachtspunten.
- Als iets niet in de retrieval-output staat, zeg dan dat dit niet in de beschikbare definities/documentatiefragmenten staat.
- Gebruik de velden, datasets en notes alleen als ze letterlijk in de retrieval-output staan.
- Bewaar belangrijke waarschuwingen en nuances uit notes.
- Vermijd overclaimen: presenteer alleen wat uit de retrieval-output volgt.
- Antwoord in helder, beknopt Nederlands.
- Noem waar relevant: definitie, relevante velden, databestanden en aandachtspunten.
- Maak het antwoord natuurlijker dan de ruwe JSON, maar blijf feitelijk trouw aan de JSON.

Gebruikersvraag:
{user_query}

Retrieval-output:
{retrieval_json}

Antwoord:"""
