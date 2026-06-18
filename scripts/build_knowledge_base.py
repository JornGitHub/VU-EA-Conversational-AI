#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from src.ingestion.hashing import compute_sha256, iter_source_documents, find_changed_documents, load_manifest, save_manifest
from src.ingestion.extract_text import extract_text
from src.ingestion.chunk_documents import chunk_document, write_chunks
from src.ingestion.extract_definitions import extract_from_chunks
from src.ingestion.build_index import write_json, write_jsonl, build_sqlite
from src.ingestion.validation import validate_build
from src.ingestion.changelog import diff_curated, append_changelog
from src.ingestion.archive import archive_root_generated_artifacts, format_archive_summary
DATA=ROOT/'data'; SOURCE=ROOT/'sources'/'1cHO Documentatie'; LEGACY=ROOT/'1cHO Documentatie'
GEN=['ho_definities_curated.json','ho_definities_index.jsonl','chunks.jsonl','document_manifest.json']
def load_old_curated():
    p=DATA/'ho_definities_curated.json'
    if not p.exists(): return []
    d=json.loads(p.read_text(encoding='utf-8'))
    return d.get('entries',d) if isinstance(d,dict) else d

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--full',action='store_true'); ap.add_argument('--dry-run',action='store_true'); ap.add_argument('--archive-root-leftovers',action='store_true'); args=ap.parse_args()
    SOURCE.mkdir(parents=True,exist_ok=True); DATA.mkdir(exist_ok=True); (DATA/'backups').mkdir(exist_ok=True)
    manifest=load_manifest(DATA/'document_manifest.json')
    source_dir=SOURCE
    docs=iter_source_documents(source_dir)
    if not docs and LEGACY.exists():
        source_dir=LEGACY
        docs=iter_source_documents(source_dir)
    changed=docs if args.full else find_changed_documents(source_dir,manifest)
    skipped=[p for p in docs if p not in changed]
    timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(); warnings=[]; all_chunks=[]; new_manifest={}
    archive_result=archive_root_generated_artifacts(ROOT, dry_run=args.dry_run) if args.archive_root_leftovers else None
    for p in docs:  # rebuild artifacts from all docs for consistency; changed list controls reporting/incremental detection
        try:
            doc=extract_text(p); chunks=chunk_document(doc); all_chunks.extend(chunks)
            new_manifest[p.as_posix()]={'sha256':compute_sha256(p),'last_processed':timestamp if p in changed or args.full else manifest.get(p.as_posix(),{}).get('last_processed',timestamp),'source_type':p.suffix.lower().lstrip('.'),'chunks':len(chunks)}
        except Exception as exc: warnings.append(f'{p}: {exc}')
    curated,index,all_chunks=extract_from_chunks(all_chunks,timestamp)
    old_curated=load_old_curated()
    curated=merge_existing_curated(old_curated, curated, timestamp)
    changes=diff_curated(old_curated,curated,timestamp)
    tmp=DATA/'.build_tmp'; shutil.rmtree(tmp,ignore_errors=True); tmp.mkdir(parents=True)
    write_json(tmp/'ho_definities_curated.json', curated); write_jsonl(tmp/'ho_definities_index.jsonl', index); write_chunks(tmp/'chunks.jsonl', all_chunks); save_manifest(tmp/'document_manifest.json', new_manifest)
    errors=validate_build(tmp/'ho_definities_curated.json', tmp/'ho_definities_index.jsonl', tmp/'chunks.jsonl', old_curated if old_curated else None)
    report=render_report(timestamp,changed,skipped,curated,index,all_chunks,changes,warnings,errors,args.dry_run,archive_result)
    if args.dry_run:
        print(report); return 0 if not errors else 1
    if errors:
        (DATA/'last_build_report.md').write_text(report,encoding='utf-8'); print(report); return 1
    stamp=timestamp.replace(':','').replace('+','_')
    for name in GEN:
        dst=DATA/name
        if dst.exists(): shutil.copy2(dst, DATA/'backups'/f'{stamp}_{name}')
        (tmp/name).replace(dst)
    append_changelog(DATA/'curated_change_log.jsonl', changes)
    warnings+=build_sqlite(DATA/'ho_knowledge.db', curated,index,all_chunks)
    report=render_report(timestamp,changed,skipped,curated,index,all_chunks,changes,warnings,[],False,archive_result)
    (DATA/'last_build_report.md').write_text(report,encoding='utf-8'); print(report); return 0

def merge_existing_curated(existing, generated, timestamp):
    """Keep trusted existing curated concepts unless regenerated with same term.

    In this project, "curated" means automatically cleaned/high-confidence
    definitions prepared for conversational retrieval, not necessarily manually
    approved definitions. This preserves current user-facing behavior while
    still allowing automatic ingestion to overwrite and add generated entries.
    """
    by={str(e.get('term','')).strip().lower(): dict(e) for e in existing if e.get('term')}
    for entry in generated:
        key=str(entry.get('term','')).strip().lower()
        if key:
            by[key]=entry
    for entry in by.values():
        entry.setdefault('generated_by','automatic_ingestion')
        entry.setdefault('last_updated', timestamp)
        entry.setdefault('category','concept')
        entry.setdefault('datasets', entry.get('available_in_datasets', []))
        entry.setdefault('fields', entry.get('related_fields', []))
        entry.setdefault('source_documents', entry.get('source_documents', entry.get('source_terms', [])))
        entry.setdefault('confidence', 0.99 if entry.get('definition') else 0.8)
        entry.setdefault('source_fragments', [entry.get('definition','')[:500]])
    return sorted(by.values(), key=lambda e: str(e.get('term','')).lower())

def render_report(ts,processed,skipped,curated,index,chunks,changes,warnings,errors,dry,archive_result=None):
    counts={t:sum(1 for c in changes if c['change_type']==t) for t in ('added','modified','removed')}
    lines=['# Knowledge base build report','',f'Timestamp: {ts}',f'Dry run: {dry}',f'Source files processed: {len(processed)}',f'Source files skipped because unchanged: {len(skipped)}','','Curated definitions:',f"- added: {counts['added']}",f"- modified: {counts['modified']}",f"- removed: {counts['removed']}",'',f'Index entries: {len(index)}',f'Chunks: {len(chunks)}','','Potential warnings:']
    lines += [f'- {w}' for w in warnings] or ['- none']
    if archive_result is not None:
        lines += ['', format_archive_summary(archive_result)]
    lines += ['', 'Curated terminology note:', '- In this project, "curated" means automatically cleaned/high-confidence definitions, not necessarily manually approved definitions.']
    if errors: lines += ['','Validation errors:']+[f'- {e}' for e in errors]
    return '\n'.join(lines)+'\n'
if __name__=='__main__': raise SystemExit(main())
