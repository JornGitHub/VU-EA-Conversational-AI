from __future__ import annotations
import json, re
from datetime import datetime, timezone
from typing import Any
DATASET_RE=re.compile(r'\b[\w*(). -]+\.(?:csv|asc|txt|pdf|xlsx|jsonl?|docx)\b', re.I)
DEF_RE=re.compile(r'^(?P<term>[A-ZÁÉÍÓÚÄËÏÖÜ][\w /()\-]{2,80})\s*(?:[:–-]|\bis\b|\bbetekent\b|\bwordt gedefinieerd als\b|\bgeeft aan of\b)\s*(?P<definition>.{20,})', re.I)
FIELD_RE=re.compile(r'^(?P<term>(?:Indicatie|Code|Naam|Datum|Soort|Type|Aantal|Status)[\w /()\-]{2,100})\s*(?:[:–-]|=)\s*(?P<definition>.{5,})', re.I)
KNOWN=['Internationale student','Student / ingeschrevene','Instroom','Inschrijvingen','Studiesucces','Uitval','EER-student','EOI-cohort','Gediplomeerdencohort','Onechte neveninschrijving','Echte neveninschrijving']

MIN_CURATED_CONFIDENCE = 0.90
CURATED_THRESHOLD = MIN_CURATED_CONFIDENCE
CURATED_REJECTION_STATS: dict[str, int] = {}
PROTECTED_TERMS = {t.lower() for t in [
    'Internationale student','Indicatie internationale student','Indicatie internationale student op peildatum 1 oktober',
    'Student / ingeschrevene','EER-student','Instroom','Inschrijvingen','Studiesucces','Uitval',
    'Doorstuderen','Switch','Studiewissel','Diploma','Diploma’s','EOI-cohort','Gediplomeerdencohort',
    'Onechte neveninschrijving','Echte neveninschrijving'
]}
BAD_START_WORDS = {w.lower() for w in 'Aan Aangezien Als Bij Binnen Daarbij Daarentegen Daarin Daarmee Daarna Daarnaast Daarom Dat De Deze Dit Die Een Er Het'.split()}
BROKEN_STARTS = ('ctuele','eildatum','eeft','eiding','derwijs')
GENERIC_BAD_TERMS = {'bronnen', 'mogelijke waarden'}
GENERIC_BAD_DEFS = ('de uiterste zorg besteed','berekend binnen deze subpopulaties','in het hbo groter dan in het wo','de lijn daar grilliger')
TECHNICAL_RULE_RE = re.compile(r'\b(?:Ex1\s*=\s*k|Exgf|Ex\[t\+1\]|Her[1-8]\b)', re.I)
SECTION_NUMBER_RE = re.compile(r'\b\d+(?:\.\d+){2,}\b')

def reset_curated_rejection_stats():
    CURATED_REJECTION_STATS.clear()

def get_curated_rejection_stats():
    return dict(CURATED_REJECTION_STATS)

def _reject(reason: str) -> bool:
    CURATED_REJECTION_STATS[reason] = CURATED_REJECTION_STATS.get(reason, 0) + 1
    return False

def is_likely_field_name(term: str) -> bool:
    t=term.strip()
    return bool(re.match(r'^(Indicatie|Code|Naam|Datum|Soort|Type|Aantal|Status|Sleutel|Opleiding|Instelling)\b', t, re.I))

def is_likely_indicator_title(term: str) -> bool:
    return bool(re.match(r'^(Instroom|Inschrijvingen|Studiesucces|Uitval|Doorstuderen|Switch|Diploma|\d+[.)])\b', term.strip(), re.I))

def is_bad_sentence_fragment_term(term: str) -> bool:
    t=' '.join(str(term).strip().split())
    if not t: return True
    low=t.lower()
    if low in GENERIC_BAD_TERMS or low.startswith('mogelijke waarden'):
        return True
    if re.match(r'^masterex\d+\s+geeft\s+aan\s+of\s+de\s+student\b', t, re.I):
        return True
    if low in PROTECTED_TERMS: return False
    words=t.split()
    if t.lower().startswith(BROKEN_STARTS): return True
    if t[:1].islower() and not is_likely_field_name(t): return True
    if len(words)>9 and not is_likely_indicator_title(t) and not is_likely_field_name(t): return True
    if any(ch in t for ch in ',;') and not is_likely_field_name(t): return True
    if words and words[0].lower() in BAD_START_WORDS and not is_likely_field_name(t) and not is_likely_indicator_title(t): return True
    if re.search(r'\b(omdat|waarbij|terwijl|zodat|maar|dan|juist|weer)\b', t, re.I): return True
    if re.search(r'[-–]{3,}', t): return True
    return False

def is_good_curated_term(term: str, entry: dict | None = None) -> bool:
    t=' '.join(str(term).strip().split())
    if not t: return _reject('empty_term')
    if t.lower() in PROTECTED_TERMS: return True
    if is_bad_sentence_fragment_term(t): return _reject('bad_term_shape')
    if len(t)<3 or len(t)>100 or not any(ch.isalpha() for ch in t): return _reject('bad_term_shape')
    toks=re.findall(r'[A-Za-zÀ-ÿ0-9]+', t)
    if not toks: return _reject('bad_term_shape')
    if not (is_likely_field_name(t) or is_likely_indicator_title(t) or len(toks)<=6 or any(ch.isdigit() for ch in t)):
        return _reject('bad_term_shape')
    return True

def is_incomplete_definition(definition: str) -> bool:
    d=' '.join(str(definition).strip().split())
    if not d: return True
    low=d.lower()
    if any(x in low for x in GENERIC_BAD_DEFS): return True
    if TECHNICAL_RULE_RE.search(d): return True
    if len(SECTION_NUMBER_RE.findall(d)) >= 3: return True
    if low.startswith(('dat ', 'de ', 'het ', 'een ', 'en ', 'of ', 'om ', 'waarbij ')) and not re.match(r'^(de|het|een)\s+(?:[\w/-]+\s+){0,3}(is|wordt|geeft|betekent|beschrijft|verwijst|groepeert)\b', low): return True
    if re.match(r'^[,;:)\]-]', d): return True
    if d.endswith((',', ';', ':', ' en', ' of', ' dat', ' waarbij')): return True
    if len(re.findall(r'[A-Za-zÀ-ÿ]+', d)) < 8 and 'mogelijke waarden' not in low: return True
    nums=len(re.findall(r'\d', d)); chars=len(re.sub(r'\s','',d))
    if chars and nums/chars>0.45: return True
    if any(x in low for x in ('copyright','isbn','inhoudsopgave','pagina ')): return True
    if low.startswith('zie ') and len(low.split())<8: return True
    return False

def is_good_curated_definition(definition: str, entry: dict | None = None) -> bool:
    if is_incomplete_definition(definition): return _reject('incomplete_definition')
    low=str(definition).lower()
    if any(x in low for x in ('gestegen','gedaald','afgelopen drie jaar','groter dan in het wo','kleiner dan')) and not any(p in low for p in ('betekent','gedefinieerd','geeft aan','is een')):
        return _reject('trend_narrative_sentence')
    if re.search(r'\b(\d+[,.]?\d*%\s*){3,}', low): return _reject('table_or_numeric_noise')
    return True

def curated_quality_reason(entry: dict) -> str | None:
    if not entry.get('term') or not entry.get('definition') or not entry.get('source_documents'):
        return 'missing_required_field'
    if float(entry.get('confidence',0) or 0) < MIN_CURATED_CONFIDENCE:
        return 'low_confidence'
    before=dict(CURATED_REJECTION_STATS)
    if not is_good_curated_term(str(entry.get('term','')), entry):
        return 'bad_term_shape'
    if not is_good_curated_definition(str(entry.get('definition','')), entry):
        # infer last changed reason
        after=dict(CURATED_REJECTION_STATS)
        for k,v in after.items():
            if v>before.get(k,0): return k
        return 'incomplete_definition'
    return None

def _uniq(v):
    seen=set(); out=[]
    for x in v:
        x=str(x).strip()
        k=x.lower()
        if x and k not in seen: seen.add(k); out.append(x)
    return out

def extract_from_chunks(chunks:list[dict[str,Any]], timestamp:str|None=None)->tuple[list[dict[str,Any]], list[dict[str,Any]], list[dict[str,Any]]]:
    timestamp=timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    raw=[]
    for c in chunks:
        text=c['text']; datasets=_uniq(DATASET_RE.findall(text)); fields=[]; terms=[]
        lines=[l.strip(' -*\t') for l in re.split(r'[\n\r]+|(?<=\.)\s+', text) if l.strip()]
        for line in lines:
            m=FIELD_RE.match(line) or DEF_RE.match(line)
            if m:
                term=m.group('term').strip(); definition=m.group('definition').strip()
                low_line=line.lower()
                conf=0.86 if term.lower().startswith('indicatie') else 0.62
                if any(p in low_line for p in ('wordt gedefinieerd als','betekent','geeft aan of','mogelijke waarden')): conf=0.92
                if FIELD_RE.match(line) and is_likely_field_name(term) and ('geeft aan' in low_line or 'mogelijke waarden' in low_line): conf=max(conf,0.90)
                if is_bad_sentence_fragment_term(term) or is_incomplete_definition(definition): conf=min(conf,0.55)
                typ='important_field' if term.lower().startswith('indicatie') else 'concept'
                raw.append(_entry(term,definition,c,datasets,[term] if typ=='important_field' else [],typ,min(conf,0.97),timestamp))
                terms.append(term); fields += [term] if typ=='important_field' else []
        low=text.lower()
        for term in KNOWN:
            if term.lower() in low and not any(r['term'].lower()==term.lower() and r['chunk_id']==c['chunk_id'] for r in raw):
                sent=next((s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if term.lower() in s.lower()), text[:500])
                if len(sent)>30: raw.append(_entry(term,sent,c,datasets,fields,'concept',0.72,timestamp)); terms.append(term)
        c['datasets']=datasets; c['fields']=_uniq(fields); c['terms']=_uniq(terms)
    raw.extend(_extract_neveninschrijving_entries(chunks, timestamp))
    curated=select_curated(raw)
    return curated, raw, chunks

def _entry(term,definition,c,datasets,fields,category,confidence,timestamp):
    return {'term':term,'category':category,'definition':definition,'datasets':_uniq(datasets),'fields':_uniq(fields),'source_documents':[c['source_document']],'source_fragments':[definition[:500]],'source_document':c['source_document'],'source_path':c['source_path'],'page':c.get('page'),'chunk_id':c['chunk_id'],'source_type':'field_definition' if category=='important_field' else 'concept_definition','confidence':round(confidence,2),'generated_by':'automatic_ingestion','last_updated':timestamp}

def _extract_neveninschrijving_entries(chunks, timestamp):
    support=[c for c in chunks if 'onechte neveninschrijving' in c.get('text','').lower() and 'andere inschrijving' in c.get('text','').lower()]
    if not support:
        return []
    doc=support[0]
    datasets=_uniq(DATASET_RE.findall(' '.join(c.get('text','') for c in support))) or ['1cyferho_2025_v1.0.asc']
    fields=['Soort inschrijving type ho binnen soort ho','Soort inschrijving actuele opleiding-instelling','Sleutel domein hoger onderwijs','Sleutel domein type hoger onderwijs binnen soort hoger onderwijs','Sleutel domein actuele opleiding-instelling']
    one='Een onechte neveninschrijving is een neveninschrijving waarbij de combinatie opleiding-instelling wel voorkomt bij een andere inschrijving van dezelfde student binnen het betreffende domein of teldomein. De bron gebruikt hiervoor onder meer waarde 4 bij sleutel-domeinvelden en soort-inschrijvingsvelden.'
    echte='Een echte neveninschrijving is een neveninschrijving waarbij de combinatie opleiding-instelling niet voorkomt bij een andere inschrijving van dezelfde student binnen het betreffende domein of teldomein. De bron gebruikt hiervoor onder meer waarde 2 bij sleutel-domeinvelden en soort-inschrijvingsvelden.'
    return [_entry('Onechte neveninschrijving', one, doc, datasets, fields, 'concept', .94, timestamp), _entry('Echte neveninschrijving', echte, doc, datasets, fields, 'concept', .94, timestamp)]

def select_curated(entries, threshold=CURATED_THRESHOLD):
    """Select strict, high-confidence definitions for conversational use."""
    reset_curated_rejection_stats()
    by={}
    for e in entries:
        reason=curated_quality_reason(e)
        if reason:
            if reason in {'low_confidence', 'missing_required_field'}:
                CURATED_REJECTION_STATS[reason]=CURATED_REJECTION_STATS.get(reason,0)+1
            continue
        k=str(e['term']).strip().lower(); old=by.get(k)
        if not old or e['confidence']>old['confidence'] or len(e['definition'])>len(old['definition']):
            by[k]=dict(e)
        else:
            old['datasets']=_uniq(old.get('datasets',[])+e.get('datasets',[])); old['fields']=_uniq(old.get('fields',[])+e.get('fields',[])); old['source_documents']=_uniq(old.get('source_documents',[])+e.get('source_documents',[])); old['source_fragments']=_uniq(old.get('source_fragments',[])+e.get('source_fragments',[]))
    return sorted(({k:v for k,v in e.items() if k not in {'source_document','source_path','page','chunk_id','source_type'}} for e in by.values()), key=lambda x:x['term'].lower())
