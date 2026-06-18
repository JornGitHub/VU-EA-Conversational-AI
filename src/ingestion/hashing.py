from __future__ import annotations
import hashlib, json
from pathlib import Path
SUPPORTED_EXTENSIONS={'.txt','.md','.json','.jsonl','.pdf','.docx'}

def compute_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def load_manifest(path: Path) -> dict:
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError: return {}

def save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)+'\n', encoding='utf-8')

def iter_source_documents(source_dir: Path) -> list[Path]:
    if not source_dir.exists(): return []
    return sorted(p for p in source_dir.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)

def find_changed_documents(source_dir: Path, manifest: dict) -> list[Path]:
    changed=[]
    for p in iter_source_documents(source_dir):
        key=p.as_posix(); old=manifest.get(key,{})
        if old.get('sha256') != compute_sha256(p): changed.append(p)
    return changed
