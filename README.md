
## Bronfocus: Aggregaatbestand inschrijvingen 1cHO2025

De definitiezoeker gebruikt voor vragen over `Inschrijvingen_aggr_UNL_2025.csv` standaard het primaire document `Aggregaatbestand inschrijvingen_1cHO2025.docx`. De build detecteert dit document robuust via de bestaande source-structuur (`sources/1cHO Documentatie/...`) en de legacy-map (`1cHO Documentatie/...`).

Tijdens de build wordt `data/inschrijvingen_aggr_2025_field_catalog.json` gemaakt met alle 54 velden, inclusief veldnummer, bron, type veld, beschrijving, mogelijke waarden, NB's, verwijzingen en bewerkingen. Daarnaast wordt `data/gold_standard_inschrijvingen_aggr_2025.jsonl` gegenereerd als pseudo-gold/retrieval-regressieset.

Retrieval accepteert `source_focus="primary"` en `include_supplemental=True/False`. Bij veldvragen is het bronbeleid normaal `primary_only`; aanvullende documentatie wordt alleen als aanvullende context gelabeld wanneer die nodig is of expliciet wordt toegestaan.
