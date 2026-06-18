from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
FIELDS=['definition','datasets','fields','source_documents','confidence']
def normalize_term(t): return ' '.join(str(t).lower().split())
def entry_hash(e): return hashlib.sha256(json.dumps(e,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def diff_curated(old,new,timestamp=None,reason='automatic_ingestion_rebuild'):
    timestamp=timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    oldm={normalize_term(e.get('term')):e for e in old}; newm={normalize_term(e.get('term')):e for e in new}; changes=[]
    for k in sorted(newm.keys()-oldm.keys()): changes.append(_rec(timestamp,'added',newm[k].get('term'),None,newm[k],list(newm[k].get('source_documents',[])),reason))
    for k in sorted(oldm.keys()-newm.keys()): changes.append(_rec(timestamp,'removed',oldm[k].get('term'),oldm[k],None,list(oldm[k].get('source_documents',[])),reason))
    for k in sorted(oldm.keys()&newm.keys()):
        ch=[f for f in FIELDS if oldm[k].get(f)!=newm[k].get(f)]
        if ch:
            r=_rec(timestamp,'modified',newm[k].get('term'),oldm[k],newm[k],list(newm[k].get('source_documents',[])),reason); r['changed_fields']=ch; changes.append(r)
    return changes
def _rec(ts,typ,term,old,new,docs,reason):
    return {'timestamp':ts,'change_type':typ,'term':term,'old_entry':old,'new_entry':new,'changed_fields':[] if typ!='modified' else None,'source_documents':docs,'reason':reason,'old_hash':entry_hash(old) if old else None,'new_hash':entry_hash(new) if new else None}
def append_changelog(path:Path, changes):
    if not changes: return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a',encoding='utf-8') as f:
        for c in changes: f.write(json.dumps(c,ensure_ascii=False,sort_keys=True)+'\n')
