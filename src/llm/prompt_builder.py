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
- Beantwoord alleen met informatie uit de meegegeven context. Als de context een verwijzing bevat naar een ontbrekende bron, zeg dat de primaire bron het verschil niet volledig uitlegt en noem welke bron nodig is. Als aanvullende broncontext aanwezig is, gebruik die om het verschil uit te leggen en label dit als aanvullende context.
- Voor deep-context antwoorden gebruik je altijd herkenbare kopjes: "Uit het primaire document", "Aanvullende context", "Conclusie / verschil" en, indien relevant, "Onzekerheid of ontbrekende bron".
- Laat bij internationale student nooit de nuance "geen Nederlandse vooropleiding voor het HO" weg als die in de retrieval-output staat.

Gebruikersvraag:
{user_query}

Retrieval-output:
{retrieval_json}

Antwoord:"""
