import io
import json
from pathlib import Path
import tempfile
import struct
import unittest
import wave

import numpy as np
from phonomenal.vcpack import write_pack, string
import test_vcpack


class CenterJoinTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pack = Path(self.tmp.name)/'voice.vcpack'
        self.audio = (np.sin(np.arange(10000)*2*np.pi*180/16000)*6000).astype('<i2')
        self.records = [dict(id='left', words=[dict(label='leftword',start=0,end=3840)],phones=[
            dict(label='K',word=0,start=0,end=960),dict(label='AA1',word=0,start=960,end=3840)]),
            dict(id='right',words=[dict(label='rightword',start=4800,end=8640)],phones=[
            dict(label='AA1',word=0,start=4800,end=7680),dict(label='T',word=0,start=7680,end=8640)])]
        self.write()

    def write(self, extras=None):
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=self.audio.tobytes(),
            records=self.records,features=False,extra_sections=extras)

    def plan(self,*args):
        return json.loads(self.native('--phones','K AA1 T','--plan','--center-phone-joins',*args).stdout)

    def test_unseen_word_keeps_native_transitions_and_joins_inside_matching_vowel(self):
        units=self.plan()['units']
        self.assertEqual([(u['clip_id'],u['start_sample'],u['end_sample']) for u in units],
                         [('left',0,2400),('right',6240,8640)])
        self.assertTrue(units[0]['ends_at_phone_center'])
        self.assertTrue(units[1]['starts_at_phone_center'])
        audit=Path(self.tmp.name)/'audit.json'
        output=self.native('--phones','K AA1 T','--center-phone-joins','--stdout-wav','--audit',str(audit))
        with wave.open(io.BytesIO(output.stdout),'rb') as wav:
            self.assertEqual(wav.getnframes(),4800)
        centers=[b for b in json.loads(audit.read_text())['boundaries'] if b['kind']=='phone-center']
        self.assertEqual([(b['label'],b['edge'],b['source_sample'],b['output_sample']) for b in centers],
                         [('AA1','end',2400,2400),('AA1','start',6240,2400)])

    def test_existing_word_remains_one_original_recording(self):
        units=json.loads(self.native('--text','leftword','--center-phone-joins','--plan').stdout)['units']
        self.assertEqual(len(units),1)
        self.assertEqual(units[0]['kind'],'exact_word')
        self.assertEqual((units[0]['start_sample'],units[0]['end_sample']),(0,3840))
        self.assertNotIn('starts_at_phone_center',units[0])

    def test_source_silence_cannot_supply_a_center_to_center_transition(self):
        self.records[0]['phones'][1]['start']=1760
        self.write()
        for unit in self.plan()['units']:
            if unit['clip_id']=='left' and unit.get('ends_at_phone_center'):
                self.assertGreaterEqual(unit['start_sample'],1760)

    def test_punctuation_does_not_get_hidden_inside_a_diphone(self):
        units=json.loads(self.native('--text','leftword. rightword','--center-phone-joins','--plan').stdout)['units']
        self.assertEqual(len(units),2)
        self.assertEqual(units[1]['pause_before_ms'],180)

    def test_manually_rejected_phone_cannot_enter_through_center_edges(self):
        review=struct.pack('<II',1,2)
        for record in self.records:
            review+=string(record['id'])+struct.pack('<III',2,0,2 if record['id']=='left' else 0)
        self.write({'QREV':review})
        for unit in self.plan()['units']:
            if unit['clip_id']=='left':self.assertLessEqual(unit['end_sample'],960)

    def test_stop_bursts_are_not_split_between_recordings(self):
        self.records[0]['phones'][1]['label']='T'
        self.records[1]['phones'][0]['label']='T'
        self.write()
        units=json.loads(self.native('--phones','K T T','--center-phone-joins','--plan').stdout)['units']
        self.assertTrue(all(not u.get('starts_at_phone_center') and not u.get('ends_at_phone_center') for u in units))

    def test_reliable_pulses_anchor_vowel_cuts_inside_the_middle_third(self):
        pitch=struct.pack('<II',1,len(self.records))
        for record in self.records:
            pitch+=string(record['id'])+struct.pack('<I',len(record['phones']))
            for phone in record['phones']:
                marks=([2237,2317,2397,2477,2557] if record['id']=='left' else
                       [6089,6169,6249,6329,6409]) if phone['label']=='AA1' else []
                pitch+=struct.pack('<3fI',200. if marks else 0.,0.,1. if marks else 0.,len(marks))
                pitch+=struct.pack('<'+'Q'*len(marks),*marks)
        self.write({'PITC':pitch})
        units=self.plan()['units']
        self.assertEqual([(u['start_sample'],u['end_sample']) for u in units],[(0,2397),(6249,8640)])


if __name__=='__main__':unittest.main()
