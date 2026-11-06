import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

import numpy as np
from phonomenal.vcpack import write_pack, string
import test_vcpack


class CenterRunTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pack=Path(self.tmp.name)/'voice.vcpack'
        self.audio=np.linspace(-10000,10000,16000).astype('<i2')
        self.records=[dict(id='long',words=[dict(label='sourceword',start=0,end=9120)],phones=[
            dict(label=label,word=0,start=lo,end=hi) for label,lo,hi in [
                ('N',0,800),('K',800,1760),('AA1',1760,4640),('S',4640,6240),('IH1',6240,9120)]]),
            dict(id='tail',words=[dict(label='otherword',start=10000,end=13840)],phones=[
                dict(label='IH1',word=0,start=10000,end=12880),dict(label='T',word=0,start=12880,end=13840)])]
        self.write()

    def write(self,extras=None):
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=self.audio.tobytes(),
            records=self.records,features=False,extra_sections=extras,
            lexicon={'alpha':['K','AA1'],'beta':['S','IH1','T']})

    def plan(self,*args):
        return json.loads(self.native('--phones','K AA1 S IH1 T','--center-run-phones','12','--plan',*args).stdout)

    def test_long_native_transition_preserves_interior_and_reduces_fragment_cost(self):
        short=json.loads(self.native('--phones','K AA1 S IH1 T','--center-phone-joins','--plan').stdout)
        long=self.plan()
        self.assertLess(long['score'],short['score'])
        self.assertTrue(any(u.get('center_run_phone_count',0)>=4 for u in long['units']))
        self.assertEqual([(u['clip_id'],u['start_sample'],u['end_sample']) for u in long['units']],
                         [('long',800,7680),('tail',11440,13840)])
        result=self.native('--phones','K AA1 S IH1 T','--center-run-phones','12','--stdout-wav')
        with wave.open(io.BytesIO(result.stdout),'rb') as wav:
            output=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
        self.assertEqual(len(output),9280)
        np.testing.assert_array_equal(output[:6848],self.audio[800:7648])

    def test_long_transition_cannot_bridge_an_interior_silence(self):
        self.records[0]['phones'][3]['start']=5200
        self.write()
        self.assertTrue(all(u.get('center_run_phone_count',0)<=2 for u in self.plan()['units']))

    def test_rejected_interior_phone_cannot_be_hidden_in_a_long_transition(self):
        self.records.append(dict(id='fallback',words=[dict(label='fallback',start=14500,end=15500)],
            phones=[dict(label='S',word=0,start=14500,end=15500)]))
        review=struct.pack('<II',1,len(self.records))
        for record in self.records:
            review+=string(record['id'])+struct.pack('<I',len(record['phones']))
            review+=b''.join(struct.pack('<I',2 if record['id']=='long' and p['label']=='S' else 0) for p in record['phones'])
        self.write({'QREV':review})
        for unit in self.plan()['units']:
            if unit['clip_id']=='long':
                self.assertTrue(unit['end_sample']<=4640 or unit['start_sample']>=6240)

    def test_target_sentence_pause_blocks_all_longer_crossing_edges(self):
        plan=json.loads(self.native('--text','alpha. beta','--center-run-phones','12','--plan').stdout)
        self.assertFalse(any('alpha beta' in u['target_text'] for u in plan['units']))
        self.assertEqual(sum(u['pause_before_ms'] for u in plan['units']),180)

    def test_invalid_run_limits_fail_with_an_actionable_error(self):
        for limit in ['1','13']:
            result=self.native('--phones','K AA1','--center-run-phones',limit,'--plan',check=False)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'between 2 and 12',result.stderr)
