from __future__ import annotations
import json, sqlite3
from pathlib import Path

def write_json(path:Path, data)->None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def write_jsonl(path:Path, rows)->None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows),encoding='utf-8')
def build_sqlite(db_path:Path, curated, index, chunks)->list[str]:
    warnings=[]
    try:
        con=sqlite3.connect(db_path); cur=con.cursor()
        cur.executescript('DROP TABLE IF EXISTS definitions; DROP TABLE IF EXISTS chunks; CREATE TABLE definitions(term TEXT, definition TEXT, source TEXT); CREATE TABLE chunks(chunk_id TEXT, text TEXT, source_document TEXT);')
        cur.executemany('INSERT INTO definitions VALUES(?,?,?)', [(r.get('term'),r.get('definition'),'curated') for r in curated]+[(r.get('term'),r.get('definition'),'index') for r in index])
        cur.executemany('INSERT INTO chunks VALUES(?,?,?)', [(r.get('chunk_id'),r.get('text'),r.get('source_document')) for r in chunks])
        con.commit(); con.close()
    except Exception as exc: warnings.append(f'SQLite index skipped: {exc}')
    return warnings
