import json, subprocess, sys, tempfile, unittest
from pathlib import Path
from src.ingestion.hashing import compute_sha256
from src.ingestion.validation import validate_curated_entries
from src.ingestion.changelog import diff_curated
from src.ingestion.chunk_documents import chunk_document

class IngestionTests(unittest.TestCase):
    def test_hashing_same_and_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.txt'; p.write_text('x',encoding='utf-8'); h1=compute_sha256(p); self.assertEqual(h1, compute_sha256(p)); p.write_text('y',encoding='utf-8'); self.assertNotEqual(h1, compute_sha256(p))
    def valid_entry(self):
        return {'term':'T','definition':'Definitie','datasets':[],'fields':[],'source_documents':['s.txt'],'confidence':0.9}
    def test_validation(self):
        self.assertEqual([], validate_curated_entries([self.valid_entry()]))
        e=self.valid_entry(); del e['term']; self.assertTrue(validate_curated_entries([e]))
        e=self.valid_entry(); e['definition']=' '; self.assertTrue(validate_curated_entries([e]))
        e=self.valid_entry(); e['confidence']=2; self.assertTrue(validate_curated_entries([e]))
    def test_changelog(self):
        old=[{'term':'A','definition':'old','datasets':[],'fields':[],'source_documents':['s'],'confidence':.8},{'term':'B','definition':'b','datasets':[],'fields':[],'source_documents':['s'],'confidence':.8}]
        new=[{'term':'A','definition':'new','datasets':[],'fields':[],'source_documents':['s'],'confidence':.8},{'term':'C','definition':'c','datasets':[],'fields':[],'source_documents':['s'],'confidence':.8}]
        changes=diff_curated(old,new,'2026-01-01T00:00:00')
        types={c['change_type'] for c in changes}; self.assertEqual({'added','removed','modified'}, types)
        mod=next(c for c in changes if c['change_type']=='modified'); self.assertIn('definition', mod['changed_fields'])
    def test_chunking_metadata_and_stable_ids(self):
        doc={'source_document':'doc.txt','source_path':'sources/doc.txt','pages':[{'page':1,'text':'A. '*1000}]}
        a=chunk_document(doc,max_chars=200); b=chunk_document(doc,max_chars=200)
        self.assertGreater(len(a),1); self.assertEqual([x['chunk_id'] for x in a],[x['chunk_id'] for x in b]); self.assertIn('source_document', a[0])
    def test_build_script_dry_run_does_not_overwrite(self):
        target=Path('data/ho_definities_curated.json'); before=target.read_bytes() if target.exists() else b''
        subprocess.run([sys.executable,'scripts/build_knowledge_base.py','--dry-run'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        after=target.read_bytes() if target.exists() else b''
        self.assertEqual(before, after)
if __name__=='__main__': unittest.main()
