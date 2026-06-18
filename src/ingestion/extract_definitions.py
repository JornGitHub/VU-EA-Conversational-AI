from __future__ import annotations
import json, re
from datetime import datetime, timezone
from typing import Any
DATASET_RE=re.compile(r'\b[\w*(). -]+\.(?:csv|asc|txt|pdf|xlsx|jsonl?|docx)\b', re.I)
DEF_RE=re.compile(r'^(?P<term>[A-ZÁÉÍÓÚÄËÏÖÜ][\w /()\-]{2,80})\s*(?:[:–-]|\bis\b|\bbetekent\b|\bwordt gedefinieerd als\b|\bgeeft aan of\b)\s*(?P<definition>.{20,})', re.I)
FIELD_RE=re.compile(r'^(?P<term>(?:Indicatie|Code|Naam|Datum|Soort|Type|Aantal|Status)[\w /()\-]{2,100})\s*(?:[:–-]|=)\s*(?P<definition>.{5,})', re.I)
KNOWN=['Internationale student','Student / ingeschrevene','Instroom','Inschrijvingen','Studiesucces','Uitval','EER-student','EOI-cohort','Gediplomeerdencohort']

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
                conf=0.84 if term.lower().startswith('indicatie') else 0.78
                if any(p in line.lower() for p in ('wordt gedefinieerd als','betekent','geeft aan of','mogelijke waarden')): conf+=0.08
                typ='important_field' if term.lower().startswith('indicatie') else 'concept'
                raw.append(_entry(term,definition,c,datasets,[term] if typ=='important_field' else [],typ,min(conf,0.97),timestamp))
                terms.append(term); fields += [term] if typ=='important_field' else []
        low=text.lower()
        for term in KNOWN:
            if term.lower() in low and not any(r['term'].lower()==term.lower() and r['chunk_id']==c['chunk_id'] for r in raw):
                sent=next((s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if term.lower() in s.lower()), text[:500])
                if len(sent)>30: raw.append(_entry(term,sent,c,datasets,fields,'concept',0.72,timestamp)); terms.append(term)
        c['datasets']=datasets; c['fields']=_uniq(fields); c['terms']=_uniq(terms)
    curated=select_curated(raw)
    return curated, raw, chunks

def _entry(term,definition,c,datasets,fields,category,confidence,timestamp):
    return {'term':term,'category':category,'definition':definition,'datasets':_uniq(datasets),'fields':_uniq(fields),'source_documents':[c['source_document']],'source_fragments':[definition[:500]],'source_document':c['source_document'],'source_path':c['source_path'],'page':c.get('page'),'chunk_id':c['chunk_id'],'source_type':'field_definition' if category=='important_field' else 'concept_definition','confidence':round(confidence,2),'generated_by':'automatic_ingestion','last_updated':timestamp}

def select_curated(entries, threshold=0.78):
    by={}
    for e in entries:
        if not(e.get('term') and e.get('definition') and e.get('source_documents') and e.get('confidence',0)>=threshold): continue
        term=str(e.get('term','')).strip()
        if len(term) < 3 or len(term) > 80 or term.count('-') > 3 or not any(ch.isalpha() for ch in term): continue
        if term[:1].islower() and len(term.split()) < 2: continue
        k=e['term'].strip().lower(); old=by.get(k)
        if not old or e['confidence']>old['confidence'] or len(e['definition'])>len(old['definition']): by[k]=dict(e)
        else:
            old['datasets']=_uniq(old.get('datasets',[])+e.get('datasets',[])); old['fields']=_uniq(old.get('fields',[])+e.get('fields',[])); old['source_documents']=_uniq(old.get('source_documents',[])+e.get('source_documents',[]))
    return sorted(({k:v for k,v in e.items() if k not in {'source_document','source_path','page','chunk_id','source_type'}} for e in by.values()), key=lambda x:x['term'].lower())
