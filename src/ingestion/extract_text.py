from __future__ import annotations
import json, re, zipfile, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

def _clean(t:str)->str: return re.sub(r'\s+',' ',t.replace('\x00',' ')).strip()

def _read_text(path:Path)->str:
    for enc in ('utf-8','utf-8-sig','latin-1'):
        try: return path.read_text(encoding=enc)
        except UnicodeDecodeError: pass
    return path.read_text(errors='replace')

def extract_text(path: Path) -> dict[str, Any]:
    ext=path.suffix.lower().lstrip('.')
    if ext in {'txt','md'}: pages=[{'page':1,'text':_clean(_read_text(path))}]
    elif ext=='json': pages=[{'page':1,'text':_clean(json.dumps(json.loads(_read_text(path)), ensure_ascii=False, indent=2))}]
    elif ext=='jsonl': pages=[{'page':1,'text':_clean('\n'.join(_read_text(path).splitlines()))}]
    elif ext=='pdf': pages=_extract_pdf(path)
    elif ext=='docx': pages=[{'page':1,'text':_clean(_extract_docx(path))}]
    else: raise ValueError(f'Unsupported source type: {path.suffix}')
    return {'source_document':path.name,'source_path':path.as_posix(),'source_type':ext,'pages':pages}

def _extract_pdf(path:Path)->list[dict[str,Any]]:
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError as exc:
        raise RuntimeError('PDF extraction requires optional dependency pypdf; no OCR is performed.') from exc
    pages=[]
    for i,page in enumerate(PdfReader(str(path)).pages, start=1):
        text=_clean(page.extract_text() or '')
        if text: pages.append({'page':i,'text':text})
    if not pages: raise RuntimeError(f'No extractable text found in PDF {path}; OCR is not supported.')
    return pages

def _extract_docx(path:Path)->str:
    try:
        import docx  # type: ignore
        return '\n'.join(p.text for p in docx.Document(str(path)).paragraphs if p.text.strip())
    except ImportError:
        # Minimal dependency-free fallback for standard DOCX files.
        with zipfile.ZipFile(path) as z:
            xml=z.read('word/document.xml')
        root=ET.fromstring(xml)
        ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        return '\n'.join(''.join(t.text or '' for t in p.iter(ns+'t')) for p in root.iter(ns+'p'))
