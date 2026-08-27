"""Repair definitions that the text extraction cut in the wrong place.

Every one of the 42 begrippen in ``ho_definities_curated.json`` carries
``generated_by: automatic_ingestion``. The 23 with confidence 0.99 were seeded
by hand and are short and clean. The 19 below that were lifted straight out of
the source documents, and they show three mechanical faults - none of which
needs judgement to repair, because the source marks each boundary itself:

1. **The next section came along.** A heading in these documents is a line of
   text with a row of dashes under it. Extraction flattened that to one
   paragraph, so "Sleutel domein actuele opleiding" ends with the whole of
   "Soort inschrijving actuele instelling". The dashes still mark the cut.

2. **The code list is prose.** "Mogelijke waarden: 1 = hoofdinschrijving ..."
   sits inside the definition as running text, which is how a 2400-character
   wall happens. It is a list, and it reads like one once it is one.

3. **The last code swallowed the next section.** Same fault as (1) but without
   the dashes. What marks it there is that the tail begins with the name of
   another documented term, capitalised, followed by a new sentence - which an
   ordinary code meaning never does.

4. **A block of derivation rules came first.** "EOI-cohort" opens with
   "o Als Ex1 = k ... -> Exgf = [leeg]" and keeps going for 400 characters
   before the actual prose starts. Those rules belong to the fields, not to the
   term; the definition is what follows the last of them.

Nothing here rewrites documentation. It only cuts where the source says the
text ends, and moves a list out of a paragraph into a list.
"""

from __future__ import annotations

import re

# Een kopje in de brondocumenten: tekst met een rij streepjes eronder.
HEADING_UNDERLINE = re.compile(r"\s[A-Z][^-]{3,60}?\s-{4,}\s")
VALUES_HEADING = re.compile(r"\bMogelijke waarden\s*:\s*", re.I)
# Codes zijn 1-9, letters, of [leeg], gevolgd door "= " en de betekenis.
CODE_START = re.compile(r"(?:(?<=^)|(?<=\s))(\[leeg\]|[0-9A-Za-z])\s*=\s+")
# Korte namen ("Uitval") komen ook als gewoon woord voor; die zeggen niets.
MIN_TERM_LENGTH = 9


# Een afleidingsregel: operand = waarde -> operand = waarde.
DERIVATION_ARROW = "->"
FORMULA_TAIL = re.compile(r"^\s*\S+\s*=\s*\S+\s*")
# Waarmee zo'n blok begint: het opsommingsteken dat de extractie ervan maakte
# ("o Als ..."), of meteen een vergelijking ("Ex1 = k ..."). Een gewone
# definitie begint met geen van beide, ook niet als er verderop een pijl staat.
FORMULA_OPENING = re.compile(r"^(?:o\s+Als\b|\S+\s*=\s*\S+)")


def strip_derivation_block(text: str) -> str:
    """Drop a leading block of derivation rules.

    Only when the text *opens* with one, so an ordinary definition that mentions
    an arrow somewhere keeps it. The definition is what comes after the last
    rule, which ends with its own "operand = value".
    """
    if not FORMULA_OPENING.match(text) or DERIVATION_ARROW not in text:
        return text
    last = text.rfind(DERIVATION_ARROW)
    if last == -1:
        return text
    remainder = text[last + len(DERIVATION_ARROW):]
    tail = FORMULA_TAIL.match(remainder)
    prose = remainder[tail.end():] if tail else remainder
    return prose.strip() or text


def cut_at_next_heading(text: str) -> str:
    """Drop everything from the next underlined heading onwards."""
    match = HEADING_UNDERLINE.search(text)
    return text[: match.start()].rstrip() if match else text


def next_term_boundary(text: str, known_terms: frozenset[str]) -> int | None:
    """Return where another documented term starts a new sentence, or None.

    Two signals together, because either alone is wrong. A meaning mentions
    other terms all the time ("neveninschrijving binnen het domein opleiding
    actueel equivalent"), but it does so in lower case and in mid-sentence. A
    heading that lost its dashes is capitalised *and* followed by the first
    word of a new sentence.
    """
    earliest: int | None = None
    for term in known_terms:
        if len(term) < MIN_TERM_LENGTH:
            continue
        heading = re.escape(term[0].upper() + term[1:])
        for match in re.finditer(heading, text):
            following = text[match.end():].lstrip()
            if following[:1].isupper() and (earliest is None or match.start() < earliest):
                earliest = match.start()
    return earliest


def split_off_values(text: str, known_terms: frozenset[str]) -> tuple[str, list[dict[str, str]]]:
    """Lift a "Mogelijke waarden:" list out of the prose.

    Returns the remaining text and the codes. A single code is left alone: one
    "x = y" in a sentence is a sentence, not a list.
    """
    heading = VALUES_HEADING.search(text)
    if not heading:
        return text, []

    body = text[: heading.start()].rstrip()
    tail = text[heading.end():]
    starts = list(CODE_START.finditer(tail))
    if len(starts) < 2:
        return text, []

    codes: list[dict[str, str]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(tail)
        meaning = tail[start.end():end]
        if index + 1 == len(starts):
            boundary = next_term_boundary(meaning, known_terms)
            if boundary is not None:
                meaning = meaning[:boundary]
        meaning = " ".join(meaning.split()).strip(" .;")
        if meaning:
            codes.append({"code": start.group(1), "meaning": meaning})
    if len(codes) < 2:
        return text, []
    return body, codes


def clean_definition(text: str, known_terms: frozenset[str]) -> tuple[str, list[dict[str, str]]]:
    """Return the definition's own text and its code list, separated."""
    trimmed = cut_at_next_heading(" ".join(str(text or "").split()))
    trimmed = strip_derivation_block(trimmed)
    body, codes = split_off_values(trimmed, known_terms)
    return " ".join(body.split()), codes
