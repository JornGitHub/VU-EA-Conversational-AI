# Synthetische 1cHO-voorbeelddata

**Dit is géén echte data.** Er staan geen studentgegevens in deze map en die komen er
ook niet in voordat de echte export is geschoond voor privacy.

## Wat het wel is

`inschrijvingen_aggr_MOCK_2025.csv` volgt de documentatie van
`Inschrijvingen_aggr_UNL_2025.csv` exact: dezelfde 54 kolommen, in dezelfde volgorde, en
elke gecodeerde waarde komt uit een codelijst in de officiële documentatie. De aantallen
zijn verzonnen.

Identificerende velden zonder codelijst (instelling, opleiding, ISCED, vooropleiding)
krijgen bewust waarden **buiten de echte coderuimte**: `ZZ01` is geen Nederlandse
instelling en `90001` is geen CROHO-nummer. Een bestand dat per ongeluk ergens belandt,
is daardoor herkenbaar nep.

## Waarom het er is

1. **Definities worden concreet.** "Opleidingsvorm is een code" zegt minder dan die code
   met voorbeeldwaarden ernaast.
2. **Het is de proef op de som voor de echte data.** De weg van bestand → profiel →
   antwoord werkt hiermee end-to-end. Komt de geschoonde export binnen, dan verandert
   alleen wáár de rijen vandaan komen.

## Herbouwen

```bash
python scripts/generate_mock_data.py            # standaard 5000 rijen
python scripts/check_data_against_docs.py       # data vs. documentatie
```

Het is deterministisch: dezelfde seed geeft hetzelfde bestand. De CSV staat daarom niet
in git (`.gitignore`); `mock_profile.json` wel, want de app leest dat.

## Als de echte data er is

Richt de checker op het echte bestand:

```bash
python scripts/check_data_against_docs.py pad/naar/export.csv
```

Die meldt kolommen zonder documentatie en codes zonder gedocumenteerde betekenis — de
twee dingen die een antwoord stilletjes fout maken.
