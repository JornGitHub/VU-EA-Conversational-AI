# HO definities - overzicht voor conversational AI

Dit bestand is gegenereerd uit de aangeleverde documentatie rond 1cHO/UNL/VH/DUO. Gebruik het als menselijke leeslaag naast de machineleesbare JSON-bestanden.

## Aanbevolen gebruik in een chatbot

1. Gebruik `ho_definities_curated.json` voor antwoorden op begripsvragen zoals “wat is een internationale student?”.

2. Gebruik `ho_definities_index.jsonl` als ruwe RAG-index met veldbeschrijvingen, databestanden en indicator-definities.

3. Antwoorden over “waar vind ik X?” moeten zoeken in `available_in_datasets`, `related_fields`, `source_file` en `tags`.

## Curated glossary

### Internationale student

Een student wordt als internationale student beschouwd wanneer de student geen Nederlandse nationaliteit heeft en geen Nederlandse vooropleiding voor het hoger onderwijs heeft. In de 1cHO-bestanden wordt dit vastgelegd via indicatievelden. Let op het verschil tussen de actuele variant en de peildatumvariant: bij de actuele variant kan naturalisatie met terugwerkende kracht eerdere jaren wijzigen; bij de peildatumvariant blijft de status voor jaren vóór naturalisatie behouden.

**Gerelateerde velden:** Indicatie internationale student, Indicatie internationale student op peildatum 1 oktober

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv, EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv, Gediplomeerdencohort_UNL_2025.csv / Gediplomeerdencohort_21P*_2025.csv, VH informatieproducten / 1cijferHO

**Let op:** De exacte operationalisatie hangt af van het veld: actuele nationaliteit versus nationaliteit op peildatum 1 oktober.


### Indicatie internationale student

Veld dat aangeeft of een student als internationale student wordt beschouwd. De documentatie vermeldt de waarden J = internationale student en N = geen internationale student. Voor de nationaliteit wordt uitgegaan van de actuele eerste nationaliteit. Daardoor kan een student die later Nederlander wordt in nieuwere 1cHO-bestanden met terugwerkende kracht niet meer als internationale student tellen.

**Gerelateerde velden:** Indicatie internationale student

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, EOIcohort_aggr_UNL_2025.csv, Gediplomeerdencohort_aggr_UNL_2025.csv


### Indicatie internationale student op peildatum 1 oktober

Veld dat aangeeft of een student op 1 oktober van het betreffende inschrijvingsjaar als internationale student wordt beschouwd. Hierbij wordt gebruikgemaakt van de eerste nationaliteit op peildatum 1 oktober. Bij latere naturalisatie blijft de student voor jaren vóór naturalisatie als internationale student geregistreerd.

**Gerelateerde velden:** Indicatie internationale student op peildatum 1 oktober

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv, Gediplomeerdencohort_UNL_2025.csv / Gediplomeerdencohort_21P*_2025.csv


### Student / ingeschrevene

In de 1cHO-bestanden is een student/ingeschrevene een persoon die met een persoonsgebonden nummer voorkomt in een inschrijvingsrecord. Afhankelijk van de vraag telt niet elke persoon precies één keer: tellingen kunnen per inschrijving, hoofdinschrijving, opleiding, instelling, type hoger onderwijs of cohort worden bepaald.

**Gerelateerde velden:** Persoonsgebonden nummer, Inschrijvingsvorm, Indicatie actief op peildatum

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, VH informatieproducten / 1cijferHO


### Inschrijvingen

In overzichten met inschrijvingen wordt elke inschrijving geteld waarbij de student actief was op 1 oktober van het betreffende studiejaar. Standaard worden inschrijvingen ontdubbeld per onderwijstype, waardoor een student met meerdere opleidingen maximaal één keer per onderwijstype wordt meegeteld.

**Gerelateerde velden:** Indicatie actief op peildatum, Soort inschrijving type ho binnen soort ho, Inschr_type_hbo, Inschr_type_inst, Inschr_type

**Beschikbaar in:** Inschrijvingen_aggr_UNL_2025.csv, VH informatieproducten / 1cijferHO


### Instroom

Instroom is een subset van inschrijvingen: een student is actief op 1 oktober en stond sinds 1986 niet eerder op die peildatum ingeschreven binnen het gekozen teldomein. Het teldomein bepaalt of iemand als nieuwe student telt, bijvoorbeeld binnen hoger onderwijs, onderwijssoort, onderwijstype, opleiding of opleiding-instelling.

**Gerelateerde velden:** Indicatie eerstejaars continu hoger onderwijs, Indicatie eerstejaars continu soort ho, Indicatie eerstejaars continu actuele instelling, Instr_type_hbo, Instr_type_inst, Instr_type

**Beschikbaar in:** Inschrijvingen_aggr_UNL_2025.csv, VH informatieproducten / 1cijferHO, Trendrapport HO 2025


### Diploma’s

Diploma’s worden geteld over een volledig studiejaar, niet op een peildatum. In de VH-handleiding worden propedeusediploma’s niet meegeteld. In de 1cHO/UNL-diplomabestanden gaat het om records met een relevant soort diploma/opleidingsfase en een examenresultaat.

**Gerelateerde velden:** Code examenresultaat, Maand examenresultaat, Opleidingsfase actueel van het diploma

**Beschikbaar in:** Diplomas_aggr_UNL_2025.csv, Gediplomeerdencohort_UNL_2025.csv / Gediplomeerdencohort_21P*_2025.csv, VH informatieproducten / 1cijferHO


### EER-student

Een EER-student is een student van wie de nationaliteit behoort tot de Europese Economische Ruimte, aangevuld met Zwitserland en Suriname. Nederland is inbegrepen. Bij de peildatumvariant geldt de EER-lijst op 1 oktober van het inschrijvingsjaar; daardoor worden Britse studenten t/m academisch jaar 2021 nog als EER geteld en daarna niet meer.

**Gerelateerde velden:** Indicatie EER actueel, Indicatie EER op peildatum 1 oktober

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv


### Soort hoger onderwijs

Geeft aan of de inschrijving valt onder hbo of wo. In VH-informatieproducten is standaard hbo geselecteerd, maar sommige hogescholen bieden ook wo-opleidingen aan.

**Gerelateerde velden:** Soort hoger onderwijs

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, VH informatieproducten / 1cijferHO


### Type hoger onderwijs binnen soort hoger onderwijs

Classificeert de opleiding binnen de onderwijssoort, bijvoorbeeld associate degree, bachelor of master binnen hbo/wo. Dit veld wordt vaak gebruikt als teldomein voor ontdubbeling, instroom en verblijfsjaarberekeningen.

**Gerelateerde velden:** Type hoger onderwijs binnen soort hoger onderwijs

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, VH informatieproducten / 1cijferHO


### Opleidingsvorm

Code voor de studievorm waarin de student staat geregistreerd: voltijd, deeltijd of duaal/coöp. In oudere jaren kan het veld soms leeg zijn.

**Gerelateerde velden:** Opleidingsvorm

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv


### Opleidingsfase

Fase van de opleiding waarvoor de student staat ingeschreven of waarvoor het diploma is behaald. De documentatie bevat onder meer codes voor propedeuse, bachelor, master, associate degree, schakelprogramma en oude-stijl fasen.

**Gerelateerde velden:** Opleidingsfase, Opleidingsfase actueel, Opleidingsfase actueel van het diploma

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv, Gediplomeerdencohort_UNL_2025.csv / Gediplomeerdencohort_21P*_2025.csv


### Actuele instelling

Administratie- of BRIN-code van de instelling zoals die geldig is in het laatst beschikbare inschrijvingsjaar. In de UNL-bestanden worden records beperkt tot 13 door UNL vertegenwoordigde universiteiten.

**Gerelateerde velden:** Actuele instelling

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv, EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv


### Opleiding actueel equivalent

Actuele opleidingscode/equivalent waarmee historische opleidingen naar een actuele opleiding kunnen worden vertaald. Dit maakt vergelijkingen door de tijd mogelijk.

**Gerelateerde velden:** Opleiding actueel equivalent

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv


### Opleiding historisch equivalent

Historische opleidingsequivalent waarmee records door de tijd heen aan dezelfde historische opleiding kunnen worden gekoppeld. Wordt veel gebruikt in cohortbestanden en ontdubbeling op opleiding-instelling.

**Gerelateerde velden:** Opleiding historisch equivalent

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv


### CROHO-onderdeel actuele opleiding

Sector/onderdeel waartoe de actuele opleiding behoort. Mogelijke hoofdwaarden zijn onder andere onderwijs, landbouw/natuurlijke omgeving, natuur, techniek, gezondheidszorg, economie, recht, gedrag en maatschappij, taal en cultuur, en sectoroverstijgend.

**Gerelateerde velden:** Croho-onderdeel actuele opleiding

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv


### Verblijfsjaar

Aantal jaren dat een student al in een bepaald domein verblijft, bijvoorbeeld hoger onderwijs, soort ho, type ho, actuele opleiding, instelling of opleiding-instelling. Verblijfsjaarvelden zijn belangrijk voor instroom/eerstejaarslogica.

**Gerelateerde velden:** Verblijfsjaar hoger onderwijs, Verblijfsjaar soort ho, Verblijfsjaar type ho binnen soort ho, Verblijfsjaar Actuele Opleiding-Instelling

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv


### EOI-cohort

EOI staat voor eerste opleiding-instelling/cohort. Het EOI-cohortbestand selecteert studenten vanaf hun eerste inschrijvingsjaar aan een specifieke opleiding-instelling, met filters zoals inschrijvingsjaar vanaf 2011, inschrijvingsvorm S, actief op peildatum en soort inschrijving soort ho 1 t/m 4.

**Gerelateerde velden:** Eerste jaar aan deze opleiding-instelling, Voorkomen, Her1 t/m Her8

**Beschikbaar in:** EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv, EOIcohort_aggr_UNL_2025.csv


### Voorkomen

In het EOI-cohortbestand geeft Voorkomen het aantal unieke combinaties Actuele instelling + Opleiding historisch equivalent aan dat een student heeft in het EOI-jaar, met correctie voor joint-degree inschrijvingen.

**Gerelateerde velden:** Voorkomen

**Beschikbaar in:** EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv, EOIcohort_aggr_UNL_2025.csv


### Her1 t/m Her8

Afgeleide herinschrijvings-/statusvelden in EOI-cohortbestanden die met een afleidingsschema bepalen wat de status van de student is in de jaren na het EOI-jaar. Ze gebruiken onder meer persoonsnummer, inschrijvingsjaar, soort ho, instelling, opleiding historisch equivalent, CROHO-onderdeel en opleidingsfase.

**Gerelateerde velden:** Her1, Her2, Her3, Her4, Her5, Her6, Her7, Her8

**Beschikbaar in:** EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv, EOIcohort_aggr_UNL_2025.csv


### Gediplomeerdencohort

Cohortbestand gebaseerd op studenten die een relevant diploma hebben behaald. Het bestand wordt gebruikt om diplomering, studieduur en bachelor-masterdoorstroom te analyseren, waaronder directe/indirecte masterinstroom en masterdiploma binnen drie jaar.

**Gerelateerde velden:** Masterin, Masterintwee, Masterintot, Masterex3

**Beschikbaar in:** Gediplomeerdencohort_UNL_2025.csv / Gediplomeerdencohort_21P*_2025.csv, Gediplomeerdencohort_aggr_UNL_2025.csv


### Studiesucces

Aandeel van een instroomcohort dat na een bepaald aantal jaar een diploma heeft behaald. Standaard kijkt de VH naar studiesucces na vijf en acht jaar voor voltijd bachelorstudenten; voor associate degree/bachelor telt elk einddiploma in het Nederlandse bekostigde hoger onderwijs mee.

**Beschikbaar in:** VH informatieproducten / 1cijferHO, Trendrapport HO 2025


### Uitval

Aandeel van een instroomcohort dat na een bepaald aantal jaar niet staat ingeschreven in het Nederlands bekostigd hoger onderwijs. Standaard wordt uitval na één jaar en na drie jaar bepaald voor voltijd bachelorstudenten.

**Beschikbaar in:** VH informatieproducten / 1cijferHO, Trendrapport HO 2025


### Studiewissel

Aandeel van een instroomcohort dat na een bepaald aantal jaar nog geen diploma heeft behaald, nog wel in het hoger onderwijs staat ingeschreven, maar niet meer bij dezelfde opleiding. Wisselen van instelling met dezelfde studie telt niet als studiewissel.

**Beschikbaar in:** VH informatieproducten / 1cijferHO, Trendrapport HO 2025


### Studieduur

Gemiddeld aantal maanden dat studenten ingeschreven hebben gestaan in het hbo op het moment van uitstroom, onderscheiden naar uitstroom met of zonder diploma. Alleen maanden waarin de student daadwerkelijk stond ingeschreven worden meegeteld.

**Gerelateerde velden:** Maand hoger onderwijs, Maand soort, Maand instelling, Maand equivalent

**Beschikbaar in:** VH informatieproducten / 1cijferHO


### Hoogste vooropleiding voor het HO

Vooropleiding die relevant is voor de instroom in het hoger onderwijs. Deze wordt gebruikt voor analyses van doorstroom, instroom, internationalisering en studentachtergrond.

**Gerelateerde velden:** Hoogste vooropleiding voor het HO, Vestigingsnummer van de hoogste vooropl. vóór het HO

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv, VH informatieproducten / 1cijferHO


### Generatie / herkomst

Studentachtergrondkenmerken rond migratie/herkomst. In 1cHO 2025 wordt expliciet vermeld dat migratieachtergrond en generatie een verouderde indeling zijn en daarom leeg zijn in het basisbestand; sommige afgeleide/aggregeerde bestanden bevatten nog velden zoals geboorteland en generatie.

**Gerelateerde velden:** Geboorteland, Generatie, Herkomstland volgens CBS-definitie, Herkomst-indikking volgens CBS-definitie

**Beschikbaar in:** 1cyferho_2025_v1.0.asc, Inschrijvingen_aggr_UNL_2025.csv, Diplomas_aggr_UNL_2025.csv


### Vakkenbestanden

Apart bestand met vakgegevens van havo- en vwo-gediplomeerden van studenten aan de instelling. Het bevat vakcode, omschrijving, gemiddelde cijfers, schoolexamen, centraal examen, eindcijfers, BSN en onderwijsnummer. Het bevat alleen geslaagden havo/vwo aan reguliere vo-instellingen, dus geen vavo en geen particulier vo.

**Gerelateerde velden:** Vakcode, Omschrijving vak, Gemiddeld cijfer cijferlijst, Cijfer schoolexamen, Cijfer centraal examen, Burgerservicenummer, Onderwijsnummer

**Beschikbaar in:** Dec_vakcode.asc / vakgegevens


## Samenvatting ruwe index

### Aantallen per type

- concept_definition: 82
- field_definition: 378
- field_index: 256
- field_layout: 140
- indicator_definition: 143

### Aantallen per bron

- Aggregaatbestand diploma's_1cHO2025.docx: 48
- Aggregaatbestand inschrijvingen_1cHO2025.docx: 109
- Bestandsbeschrijving EOIcohort_UNL _1cH2025.docx: 158
- Bestandsbeschrijving EOIcohort_aggr_UNL_1cHO2025.docx: 67
- Bestandsbeschrijving Examencohort (aggr)_UNL-1cH2025.docx: 50
- Bestandsbeschrijving Examencohort_UNL_1cHO2025.docx: 86
- Bestandsbeschrijving_1cyferho_2025_v1.0.txt: 231
- Bestandsbeschrijving_Vakkenbestanden.txt: 26
- DUO-trendrapport-ho-2025.pdf: 143
- Handleiding_studentenaantallen_en_studievoortgang_20210809.pdf: 81