
## Bronfocus: Aggregaatbestand inschrijvingen 1cHO2025

De definitiezoeker gebruikt voor vragen over `Inschrijvingen_aggr_UNL_2025.csv` standaard het primaire document `Aggregaatbestand inschrijvingen_1cHO2025.docx`. De build detecteert dit document robuust via de bestaande source-structuur (`sources/1cHO Documentatie/...`) en de legacy-map (`1cHO Documentatie/...`).

Tijdens de build wordt `data/inschrijvingen_aggr_2025_field_catalog.json` gemaakt met alle 54 velden, inclusief veldnummer, bron, type veld, beschrijving, mogelijke waarden, NB's, verwijzingen en bewerkingen. Daarnaast wordt `data/gold_standard_inschrijvingen_aggr_2025.jsonl` gegenereerd als pseudo-gold/retrieval-regressieset.

Retrieval accepteert `source_focus="primary"` en `include_supplemental=True/False`. Bij veldvragen is het bronbeleid normaal `primary_only`; aanvullende documentatie wordt alleen als aanvullende context gelabeld wanneer die nodig is of expliciet wordt toegestaan.

## Deep context retrieval en bronverwijzingen

Naast losse definitievragen ondersteunt de zoeklaag nu deep-contextvragen via `answer_deep_context_question_json(...)`. Deze route herkent meerdere velden tegelijk, bijvoorbeeld `Opleiding actueel equivalent` en `Opleiding historisch equivalent`, bouwt een contextpakket met primaire veldinformatie uit `Aggregaatbestand inschrijvingen_1cHO2025.docx` en volgt veldverwijzingen naar aanvullende documentatie zoals `hoacth.csv`, `hoacth_vest.csv`, `Iscedf2013.txt`, `Dec_vopl.csv`, `Dec_nationaliteitscode.csv` en `dec_landcode.csv`.

De resolver schrijft `data/document_references.json`. Als een gerefereerde bron niet in de repository of chunk-index staat, vermeldt de app dit expliciet bij `missing_references` en legt het antwoord uit wat wel uit het primaire document volgt en welke aanvullende bron nodig is. Helper-/decoderbestanden worden dus niet meer als hoofddataset gepresenteerd, maar blijven wel beschikbaar als bronverwijzing en aanvullende context.

De LLM-laag krijgt hetzelfde evidence-first contextpakket en de instructie om niet te gokken: ontbrekende broninformatie moet als onzekerheid worden benoemd, terwijl aanwezige aanvullende broncontext apart wordt gelabeld.

## Webbronnen en LLM-interpretatie

De primaire bronlaag blijft altijd de lokale officiële documentatie die in de repository is verwerkt, zoals de 1cHO-bronbestanden en de gegenereerde catalogi in `data/`. Als die context ontbreekt of kaal is, kan de deep-contextlaag optioneel aanvullende webcontext proberen op te halen. Webcontext wordt nooit stilzwijgend als waarheid gebruikt: iedere webbron houdt een `source_tier`, titel, URL, domein, `retrieved_at`, excerpt en gebruiksstatus bij.

Bronlagen worden in vaste prioriteit behandeld:

1. `official_documentation`: lokale officiële bronbestanden.
2. `official_supplemental`: lokale decoder- of helperbestanden waar primaire documentatie naar verwijst.
3. `official_web`: allowlisted officiële websites/documenten.
4. `external_web`: overige webbronnen; standaard uit en lager geprioriteerd.
5. `manual_knowledge`: gereserveerd voor later, expliciet gelabelde interne kennis.
6. `llm_inference`: interpretatie op basis van gevonden bronlagen; geen zelfstandige bron.

Bij conflicten blijft lokale officiële documentatie leidend, tenzij later expliciet een nieuwere officiële webbron wordt gevonden en als nieuwer/actueler wordt gelabeld. Webresultaten worden niet automatisch toegevoegd aan curated of gold-standard datasets.

De officiële web-allowlist staat in `config/web_sources.yaml` en bevat standaard:

- `cbs.nl`
- `opendata.cbs.nl`
- `duo.nl`
- `onderwijsdata.duo.nl`
- `rijksoverheid.nl`
- `ocwincijfers.nl`
- `universiteitenvannederland.nl`

Caching staat standaard aan. Opgehaalde webbronnen worden per URL gehasht en lokaal bewaard in `data/web_cache/`, zodat dezelfde bron niet steeds opnieuw hoeft te worden opgehaald. Als gratis webcontext niet beschikbaar is, blijft de app werken met lokale documentatie en verschijnt de melding: “Geen aanvullende gratis webbron gevonden/gebruikt.”

In Streamlit kun je web- en interpretatiegebruik sturen met de sidebar-opties:

- **Gebruik officiële webbronnen**: standaard aan.
- **Gebruik overige externe webbronnen**: standaard uit.
- **Sta LLM-interpretatie toe**: standaard aan.
- **Toon bronstatus**: standaard aan.

Handige commando’s:

```bash
python main.py --skip-install --tests
python main.py --skip-install --query "Wat is een onechte neveninschrijving?" --json
python scripts/run_evaluation.py --dataset web_context
```

## Gratis-only ontwerp

Dit project blijft gratis-only. Standaardgebruik vereist geen `.env`, secrets, betaalde accounts of API keys. Er zijn geen betaalde web-search services of hosted LLM API’s toegevoegd. De weblaag accepteert alleen providers die geen API key vereisen en niet betaald of usage-based zijn.

De gratis-only architectuur gebruikt:

- lokale documentatie in `sources/`/`1cHO Documentatie/` en generated artifacts in `data/`;
- optionele lokale LLM-formulering via Ollama, bijvoorbeeld `qwen3:8b`;
- optionele no-key webcontext via directe HTTP-fetches van allowlisted of bekende URL’s;
- lokale caching in `data/web_cache/`.

Niet gebruikt of vereist: Bing Search API, Tavily, SerpAPI, Google Custom Search API, OpenAI API, Anthropic API, Azure OpenAI, Gemini API of commerciële hosted embedding/search/vector APIs. Als Ollama niet draait, geeft de app retrieval-output zonder hosted fallback en crasht de zoeklaag niet.

Tests draaien zonder live internet door webproviders te mocken of de weblaag te monkeypatchen:

```bash
pytest
python scripts/run_evaluation.py --dataset web_context
```

### Weergave van interpretatie en bronstatus

De UI toont `LLM-interpretatie` alleen wanneer de retrieval-laag een inhoudelijke, brongebonden interpretatietekst heeft opgebouwd. Een lege tekst of alleen een standaarddisclaimer wordt niet als aparte interpretatiesectie weergegeven. Als er geen webcontext in `web_context` staat en `web_sources_used` false is, verwijzen disclaimers naar lokale officiële documentatie en niet naar webbronnen. Technische source tiers blijven beschikbaar in JSON/debug-output, maar de normale Streamlit-weergave gebruikt leesbare Nederlandse bronstatusregels zoals “Geen webbronnen gebruikt.”

### Webcontext-modus

Streamlit biedt vier modi voor gratis/no-key webcontext: `off` gebruikt nooit web; `fallback` is de veilige default en probeert web alleen wanneer lokale officiële context onvoldoende is; `enhance` houdt lokale documentatie leidend maar probeert ook aanvullende officiële webcontext; `force` probeert web altijd en meldt expliciet wanneer geen gratis officiële webbron is gevonden. In alle modi blijven lokale officiële bronnen leidend en webcontext wordt apart gelabeld.
