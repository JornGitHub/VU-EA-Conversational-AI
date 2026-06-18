from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any

def split_text(text:str, max_chars:int=1400, overlap:int=180)->list[str]:
    paras=[p.strip() for p in re.split(r'\n\s*\n|(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÄËÏÖÜa-z])', text) if p.strip()]
    chunks=[]; cur=''
    for p in paras:
        if cur and len(cur)+len(p)+1>max_chars:
            chunks.append(cur.strip()); tail=cur[-overlap:] if overlap else ''; cur=(tail+' '+p).strip()
        elif len(p)>max_chars:
            if cur: chunks.append(cur.strip()); cur=''
            for i in range(0,len(p),max_chars-overlap): chunks.append(p[i:i+max_chars].strip())
        else: cur=(cur+' '+p).strip()
    if cur: chunks.append(cur.strip())
    return chunks

def chunk_document(doc:dict[str,Any], max_chars:int=1400)->list[dict[str,Any]]:
    out=[]
    for page in doc.get('pages',[]):
        page_no=page.get('page') or 1
        for idx,text in enumerate(split_text(page.get('text',''), max_chars=max_chars), start=1):
            out.append({'chunk_id':f"{doc['source_document']}::p{page_no}::c{idx}",'text':text,'source_document':doc['source_document'],'source_path':doc['source_path'],'page':page_no,'chunk_index':idx,'terms':[],'datasets':[],'fields':[]})
    return out

def write_chunks(path:Path, chunks:list[dict[str,Any]])->None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(c,ensure_ascii=False,sort_keys=True)+'\n' for c in chunks), encoding='utf-8')
