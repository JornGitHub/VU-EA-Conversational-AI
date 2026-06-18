from __future__ import annotations
import json
from pathlib import Path
REQ={'term','definition','datasets','fields','source_documents','confidence'}
def validate_curated_entries(entries, previous_entries=None):
    errors=[]
    if not isinstance(entries,list): return ['curated JSON must be a list']
    seen=set()
    for i,e in enumerate(entries):
        miss=REQ-set(e)
        if miss: errors.append(f'entry {i} missing {sorted(miss)}')
        if not str(e.get('term','')).strip(): errors.append(f'entry {i} has empty term')
        if not str(e.get('definition','')).strip(): errors.append(f'entry {i} has empty definition')
        for f in ('datasets','fields','source_documents'):
            if not isinstance(e.get(f),list): errors.append(f'entry {i} {f} must be list')
        c=e.get('confidence')
        if not isinstance(c,(int,float)) or not 0<=c<=1: errors.append(f'entry {i} confidence invalid')
        k=str(e.get('term','')).strip().lower()
        if k in seen: errors.append(f'duplicate term {e.get("term")}')
        seen.add(k)
    # Stricter quality filters can legitimately remove many weak legacy pseudo-definitions.
    if previous_entries and len(entries) < 3:
        errors.append('curated output is suspiciously empty after quality filtering')
    return errors
def validate_curated_file(path:Path, previous_entries=None): return validate_curated_entries(json.loads(path.read_text(encoding='utf-8')), previous_entries)
def validate_jsonl_file(path:Path, kind:str):
    errors=[]
    for n,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
        if not line.strip(): continue
        try: e=json.loads(line)
        except json.JSONDecodeError as exc: errors.append(f'{kind} line {n}: {exc}'); continue
        if kind=='index':
            if not (e.get('term') or e.get('title')): errors.append(f'index line {n} missing term/title')
            if not (e.get('definition') or e.get('text')): errors.append(f'index line {n} missing definition/text')
            if not (e.get('source_document') or e.get('source_path') or e.get('source_documents')): errors.append(f'index line {n} missing source metadata')
        if kind=='chunks':
            for f in ('chunk_id','text','source_document','source_path'):
                if not e.get(f): errors.append(f'chunks line {n} missing {f}')
    return errors
def validate_build(curated_path,index_path,chunks_path,previous_entries=None):
    return validate_curated_file(curated_path,previous_entries)+validate_jsonl_file(index_path,'index')+validate_jsonl_file(chunks_path,'chunks')
