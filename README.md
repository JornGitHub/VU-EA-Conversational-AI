
## Bronfocus: Aggregaatbestand inschrijvingen 1cHO2025

De definitiezoeker gebruikt voor vragen over `Inschrijvingen_aggr_UNL_2025.csv` standaard het primaire document `Aggregaatbestand inschrijvingen_1cHO2025.docx`. De build detecteert dit document robuust via de bestaande source-structuur (`sources/1cHO Documentatie/...`) en de legacy-map (`1cHO Documentatie/...`).

Tijdens de build wordt `data/inschrijvingen_aggr_2025_field_catalog.json` gemaakt met alle 54 velden, inclusief veldnummer, bron, type veld, beschrijving, mogelijke waarden, NB's, verwijzingen en bewerkingen. Daarnaast wordt `data/gold_standard_inschrijvingen_aggr_2025.jsonl` gegenereerd als pseudo-gold/retrieval-regressieset.

Retrieval accepteert `source_focus="primary"` en `include_supplemental=True/False`. Bij veldvragen is het bronbeleid normaal `primary_only`; aanvullende documentatie wordt alleen als aanvullende context gelabeld wanneer die nodig is of expliciet wordt toegestaan.

## Deep context retrieval en bronverwijzingen

Naast losse definitievragen ondersteunt de zoeklaag nu deep-contextvragen via `answer_deep_context_question_json(...)`. Deze route herkent meerdere velden tegelijk, bijvoorbeeld `Opleiding actueel equivalent` en `Opleiding historisch equivalent`, bouwt een contextpakket met primaire veldinformatie uit `Aggregaatbestand inschrijvingen_1cHO2025.docx` en volgt veldverwijzingen naar aanvullende documentatie zoals `hoacth.csv`, `hoacth_vest.csv`, `Iscedf2013.txt`, `Dec_vopl.csv`, `Dec_nationaliteitscode.csv` en `dec_landcode.csv`.

De resolver schrijft `data/document_references.json`. Als een gerefereerde bron niet in de repository of chunk-index staat, vermeldt de app dit expliciet bij `missing_references` en legt het antwoord uit wat wel uit het primaire document volgt en welke aanvullende bron nodig is. Helper-/decoderbestanden worden dus niet meer als hoofddataset gepresenteerd, maar blijven wel beschikbaar als bronverwijzing en aanvullende context.

De LLM-laag krijgt hetzelfde evidence-first contextpakket en de instructie om niet te gokken: ontbrekende broninformatie moet als onzekerheid worden benoemd, terwijl aanwezige aanvullende broncontext apart wordt gelabeld.
