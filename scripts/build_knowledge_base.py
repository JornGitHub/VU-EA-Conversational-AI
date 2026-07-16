#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from src.ingestion.hashing import compute_sha256, iter_source_documents, find_changed_documents, load_manifest, save_manifest
from src.ingestion.extract_text import extract_text
from src.ingestion.chunk_documents import chunk_document, write_chunks
from src.ingestion.extract_definitions import extract_from_chunks, get_curated_rejection_stats, curated_quality_reason, PROTECTED_TERMS, canonical_term
from src.ingestion.build_index import write_json, write_jsonl, build_sqlite
from src.ingestion.validation import validate_build
from src.ingestion.changelog import diff_curated, append_changelog
from src.ingestion.archive import archive_root_generated_artifacts, format_archive_summary
from src.definitions.inschrijvingen_catalog import build_catalog, write_catalog_and_gold
from src.definitions.reference_resolver import write_document_references
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
    inschrijvingen_report = write_catalog_and_gold(dry_run=args.dry_run)
    reference_report = write_document_references(build_catalog(), dry_run=args.dry_run)
    for p in docs:  # rebuild artifacts from all docs for consistency; changed list controls reporting/incremental detection
        try:
            doc=extract_text(p); chunks=chunk_document(doc); all_chunks.extend(chunks)
            new_manifest[p.as_posix()]={'sha256':compute_sha256(p),'last_processed':timestamp if p in changed or args.full else manifest.get(p.as_posix(),{}).get('last_processed',timestamp),'source_type':p.suffix.lower().lstrip('.'),'chunks':len(chunks)}
        except Exception as exc: warnings.append(f'{p}: {exc}')
    curated,index,all_chunks=extract_from_chunks(all_chunks,timestamp)
    quality_stats=get_curated_rejection_stats()
    old_curated=load_old_curated()
    curated=merge_existing_curated(old_curated, curated, timestamp)
    changes=diff_curated(old_curated,curated,timestamp)
    annotate_quality_removals(changes)
    tmp=DATA/'.build_tmp'; shutil.rmtree(tmp,ignore_errors=True); tmp.mkdir(parents=True)
    write_json(tmp/'ho_definities_curated.json', curated); write_jsonl(tmp/'ho_definities_index.jsonl', index); write_chunks(tmp/'chunks.jsonl', all_chunks); save_manifest(tmp/'document_manifest.json', new_manifest)
    errors=validate_build(tmp/'ho_definities_curated.json', tmp/'ho_definities_index.jsonl', tmp/'chunks.jsonl', old_curated if old_curated else None)
    report=render_report(timestamp,changed,skipped,curated,index,all_chunks,changes,warnings,errors,args.dry_run,archive_result,quality_stats,inschrijvingen_report,reference_report)
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
    report=render_report(timestamp,changed,skipped,curated,index,all_chunks,changes,warnings,[],False,archive_result,quality_stats,inschrijvingen_report,reference_report)
    (DATA/'last_build_report.md').write_text(report,encoding='utf-8'); print(report); return 0

def annotate_quality_removals(changes):
    for change in changes:
        if change.get('change_type') == 'removed':
            reason = curated_quality_reason(change.get('old_entry') or {})
            if reason:
                change['reason'] = f'removed_by_curated_quality_filter: {reason}'

def _merge_lists(*values):
    seen=set(); out=[]
    for value in values:
        items=value if isinstance(value, list) else [value]
        for item in items:
            text=str(item).strip()
            key=text.lower()
            if text and key not in seen:
                seen.add(key); out.append(text)
    return out

def _merge_entries(old, new):
    if old is None:
        return dict(new)
    merged=dict(old)
    if float(new.get('confidence',0) or 0) > float(old.get('confidence',0) or 0) or len(str(new.get('definition',''))) > len(str(old.get('definition',''))):
        merged.update(new)
    for field in ('datasets','fields','source_documents','source_fragments','aliases','source_terms'):
        merged[field]=_merge_lists(old.get(field, []), new.get(field, []))
    return merged

def merge_existing_curated(existing, generated, timestamp):
    """Keep trusted existing curated concepts unless regenerated with same term.

    In this project, "curated" means automatically cleaned/high-confidence
    definitions prepared for conversational retrieval, not necessarily manually
    approved definitions. This preserves current user-facing behavior while
    still allowing automatic ingestion to overwrite and add generated entries.
    """
    by={}
    for e in existing:
        entry=dict(e)
        original=str(entry.get('term','')).strip()
        canonical=canonical_term(original)
        if canonical.lower() != original.lower():
            entry['term']=canonical
            entry['aliases']=_merge_lists(entry.get('aliases', []), [original])
            entry['source_terms']=_merge_lists(entry.get('source_terms', []), [original])
        key=str(entry.get('term','')).strip().lower()
        if key and (key in PROTECTED_TERMS or curated_quality_reason(entry) is None):
            by[key]=_merge_entries(by.get(key), entry)
    for entry in generated:
        entry=dict(entry)
        original=str(entry.get('term','')).strip()
        canonical=canonical_term(original)
        if canonical.lower() != original.lower():
            entry['term']=canonical
            entry['aliases']=_merge_lists(entry.get('aliases', []), [original])
            entry['source_terms']=_merge_lists(entry.get('source_terms', []), [original])
        key=str(entry.get('term','')).strip().lower()
        if key:
            by[key]=_merge_entries(by.get(key), entry)
    for entry in protected_seed_definitions(timestamp):
        key=str(entry.get('term','')).strip().lower()
        current=by.get(key)
        if current is None or curated_quality_reason(current) is not None or float(current.get('confidence',0) or 0) < float(entry.get('confidence',0) or 0):
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

def protected_seed_definitions(timestamp):
    """Small high-confidence quality anchors for core conversational concepts."""
    common_docs=['Bestandsbeschrijving_1cyferho_2025_v1.0.txt']
    def seed(term, definition, datasets=None, fields=None, fragments=None, confidence=0.99, aliases=None):
        return {
            'term':term, 'category':'concept', 'definition':definition,
            'datasets':datasets or ['1cyferho_2025_v1.0.asc'],
            'fields':fields or [], 'source_documents':common_docs,
            'source_fragments':fragments or [definition[:500]],
            'aliases':aliases or [],
            'source_terms':[term],
            'confidence':confidence, 'generated_by':'automatic_ingestion', 'last_updated':timestamp,
        }
    return [
        seed('Internationale student', 'Een student wordt als internationale student beschouwd wanneer de student geen Nederlandse nationaliteit heeft en geen Nederlandse vooropleiding voor het HO heeft. Deze definitie sluit aan op het veld Indicatie internationale student.', ['1cyferho_2025_v1.0.asc','Inschrijvingen_aggr_UNL_2025.csv','Diplomas_aggr_UNL_2025.csv','EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv'], ['Indicatie internationale student','Indicatie internationale student op peildatum 1 oktober'], ['Mogelijke waarden: J = internationale student N = niet-internationale student.'], aliases=['Internationale studenten','internationale student','internationale studenten']),
        seed('Indicatie internationale student', 'Geeft aan of een student als internationale student wordt geteld: een student zonder Nederlandse nationaliteit en zonder Nederlandse vooropleiding voor het HO.', ['1cyferho_2025_v1.0.asc','Inschrijvingen_aggr_UNL_2025.csv'], ['Indicatie internationale student'], ['J = internationale student; N = niet-internationale student.']),
        seed('Indicatie internationale student op peildatum 1 oktober', 'Geeft aan of een student op peildatum 1 oktober als internationale student wordt geteld: geen Nederlandse nationaliteit en geen Nederlandse vooropleiding voor het HO, waarbij jaren vóór naturalisatie behouden blijven als de student toen internationale student was.', ['1cyferho_2025_v1.0.asc'], ['Indicatie internationale student op peildatum 1 oktober']),
        seed('Student / ingeschrevene', 'Een student/ingeschrevene is een persoon met een persoonsgebonden nummer en minimaal één inschrijvingsrecord in het hoger onderwijs.', ['1cyferho_2025_v1.0.asc','Inschrijvingen_aggr_UNL_2025.csv'], ['Persoonsgebonden nummer']),
        seed('Instroom', 'Instroom beschrijft studenten die in een telperiode nieuw instromen in een opleiding, instelling of aggregatie volgens de gebruikte HO-afbakening.', ['Inschrijvingen_aggr_UNL_2025.csv'], ['Instroom']),
        seed('Inschrijvingen', 'Inschrijvingen beschrijft het aantal of de set inschrijvingsrecords van studenten in het hoger onderwijs binnen de gekozen peildatum, opleiding, instelling of aggregatie.', ['1cyferho_2025_v1.0.asc','Inschrijvingen_aggr_UNL_2025.csv'], ['Soort inschrijving','Persoonsgebonden nummer']),
        seed('Studiesucces', 'Studiesucces beschrijft voortgangs- en uitkomstmaten van studenten, zoals uitval, switch, doorstuderen en diploma binnen een cohort of telperiode.', ['EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv'], ['Uitval','Switch','Doorstuderen','Diploma']),
        seed('Uitval', 'Uitval betekent dat een student volgens de gebruikte cohortafbakening niet meer ingeschreven staat in het hoger onderwijs of de relevante opleiding/instelling.', ['EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv'], ['Uitval']),
        seed('EER-student', 'Een EER-student is een student met een nationaliteit uit de Europese Economische Ruimte volgens de nationaliteitsinformatie in de HO-bronbestanden.', ['1cyferho_2025_v1.0.asc'], ['Nationaliteit'], aliases=['EER-studenten','EER student','EER studenten']),
        seed('EOI-cohort', 'Een EOI-cohort is een cohort voor eerstejaars onderwijsinstroom dat wordt gebruikt om studiesuccesuitkomsten zoals uitval, switch, doorstuderen en diploma te volgen.', ['EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv'], ['EOI-cohort']),
        seed('Gediplomeerdencohort', 'Een gediplomeerdencohort groepeert studenten op basis van het behalen van een diploma, zodat vervolgstappen of aansluitende uitkomsten voor die diplomagroep kunnen worden geanalyseerd.', ['Diplomas_aggr_UNL_2025.csv'], ['Gediplomeerdencohort','Diploma']),
        seed('Studiewissel', 'Studiewissel betekent dat een student van studie of opleiding wisselt volgens de in de bron gebruikte switch- of opleidingsafbakening.', ['EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv'], ['Switch','Studiewissel']),
        seed('Diploma’s', 'Diploma’s verwijst naar behaalde diplomaresultaten in het hoger onderwijs, vastgelegd in diplomabestanden of als uitkomstmaat binnen cohortanalyses.', ['Diplomas_aggr_UNL_2025.csv','EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv'], ['Diploma']),
        seed('Onechte neveninschrijving', 'Een onechte neveninschrijving is een neveninschrijving waarbij de combinatie opleiding-instelling wel voorkomt bij een andere inschrijving van dezelfde student binnen het betreffende domein of teldomein. De bron gebruikt hiervoor onder meer waarde 4 bij sleutel-domeinvelden en soort-inschrijvingsvelden.', ['1cyferho_2025_v1.0.asc'], ['Soort inschrijving type ho binnen soort ho','Soort inschrijving actuele opleiding-instelling','Sleutel domein hoger onderwijs','Sleutel domein type hoger onderwijs binnen soort hoger onderwijs','Sleutel domein actuele opleiding-instelling'], ['4 = neveninschrijving ... combinatie opleiding-instelling komt WEL voor bij een andere inschrijving van de betreffende student (onechte neveninschrijving).'], 0.95),
        seed('Echte neveninschrijving', 'Een echte neveninschrijving is een neveninschrijving waarbij de combinatie opleiding-instelling niet voorkomt bij een andere inschrijving van dezelfde student binnen het betreffende domein of teldomein. De bron gebruikt hiervoor onder meer waarde 2 bij sleutel-domeinvelden en soort-inschrijvingsvelden.', ['1cyferho_2025_v1.0.asc'], ['Soort inschrijving type ho binnen soort ho','Soort inschrijving actuele opleiding-instelling','Sleutel domein hoger onderwijs','Sleutel domein type hoger onderwijs binnen soort hoger onderwijs','Sleutel domein actuele opleiding-instelling'], ['2 = neveninschrijving ... combinatie opleiding-instelling komt NIET voor bij een andere inschrijving van de betreffende student (echte neveninschrijving).'], 0.95),
    ]

def render_report(ts,processed,skipped,curated,index,chunks,changes,warnings,errors,dry,archive_result=None,quality_stats=None,inschrijvingen_report=None,reference_report=None):
    counts={t:sum(1 for c in changes if c['change_type']==t) for t in ('added','modified','removed')}
    lines=['# Knowledge base build report','',f'Timestamp: {ts}',f'Dry run: {dry}',f'Source files processed: {len(processed)}',f'Source files skipped because unchanged: {len(skipped)}','','Curated definitions:',f"- added: {counts['added']}",f"- modified: {counts['modified']}",f"- removed: {counts['removed']}",'',f'Index entries: {len(index)}',f'Chunks: {len(chunks)}','','Potential warnings:']
    lines += [f'- {w}' for w in warnings] or ['- none']
    lines += ['', 'Curated candidates rejected:']
    if quality_stats:
        lines += [f'- {reason}: {count}' for reason, count in sorted(quality_stats.items())]
    else:
        lines += ['- none']
    if inschrijvingen_report is not None:
        lines += ['', 'Primary inschrijvingen field catalog:']
        lines += [f'- {k}: {v}' for k, v in inschrijvingen_report.items()]
    if reference_report is not None:
        lines += ['', 'Reference resolver:']
        lines += [f'- {k}: {v}' for k, v in reference_report.items()]
    if archive_result is not None:
        lines += ['', format_archive_summary(archive_result)]
    lines += ['', 'Curated terminology note:', '- In this project, "curated" means automatically cleaned/high-confidence definitions, not necessarily manually approved definitions.']
    if errors: lines += ['','Validation errors:']+[f'- {e}' for e in errors]
    return '\n'.join(lines)+'\n'
if __name__=='__main__': raise SystemExit(main())
