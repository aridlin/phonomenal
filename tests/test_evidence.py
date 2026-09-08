import unittest
from phonomenal.evidence import compare_record, matched_indices

class EvidenceTests(unittest.TestCase):
    def test_matching_islands_survive_wrong_first_word(self):
        self.assertEqual(matched_indices(['you','are','straight'],['ah','are','straight']),{1:1,2:2})

    def test_ctc_emissions_do_not_claim_precise_cuts(self):
        record=dict(id='voice',words=[dict(label='cat',start=100,end=900)],phones=[dict(label='AE1',start=300,end=600,word=0)])
        observation=dict(detector='allosaurus',kind='phones',resolution_ms=45,items=[dict(label='æ',arpabet='AE',start=.4,end=.445)])
        row=compare_record(record,[observation],1000,0)['phones'][0]
        self.assertEqual(row['support'],1);self.assertEqual(row['radius_samples'],0)
        self.assertEqual(record['phones'][0]['start'],300)

    def test_word_disagreement_and_timing_uncertainty_are_separate(self):
        record=dict(id='voice',words=[dict(label='cat',start=100,end=900)],phones=[dict(label='K',start=100,end=300,word=0)])
        base=dict(detector='vosk',kind='words',resolution_ms=30)
        row=compare_record(record,[dict(base,items=[dict(label='cat',start=.15,end=.8)])],1000,0)
        self.assertEqual(row['words'][0]['radius_samples'],130)
        self.assertEqual(row['phones'][0]['word_support'],1)
        self.assertEqual(row['phones'][0]['support'],0)
        changed=compare_record(record,[dict(base,items=[dict(label='dog',start=.1,end=.9)])],1000,0)
        self.assertEqual(changed['phones'][0]['word_dispute'],1)
        self.assertEqual(changed['words'][0]['radius_samples'],0)

    def test_editor_review_excludes_rejected_audio_and_invalidates_changed_review(self):
        import json, subprocess, tempfile
        from pathlib import Path
        import numpy as np
        from phonomenal.vcpack import write_pack
        from phonomenal.pack_editor import open_project, save_project
        from test_vcpack import CLI
        if not CLI.exists():self.skipTest('Build C++ reader first')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pack=root/'original.vcpack';project=root/'edit'
            records=[dict(id=str(i),words=[dict(label='hello',start=i*4000,end=(i+1)*4000)],
                phones=[dict(label='EH1',word=0,start=i*4000,end=(i+1)*4000)]) for i in range(2)]
            write_pack(pack,voice='test',language='en',rate=16000,pcm=np.ones(8000,dtype='<i2').tobytes(),records=records,features=False)
            open_project(pack,project)
            file=project/'record-000000.json';record=json.loads(file.read_text());record['phones'][0]['review']['state']='rejected';file.write_text(json.dumps(record))
            saved=root/'reviewed.vcpack';save_project(project,saved)
            def plan(path):return json.loads(subprocess.check_output([str(CLI),'--bank',str(path),'--text','hello','--plan']))
            self.assertEqual(plan(saved)['units'][0]['clip_id'],'1')
            record['phones'][0]['review']['end']-=1;file.write_text(json.dumps(record));changed=root/'changed.vcpack';save_project(project,changed)
            self.assertEqual(plan(changed)['units'][0]['clip_id'],'0')
