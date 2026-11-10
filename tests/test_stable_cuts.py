import json
import struct
import unittest

import numpy as np
import test_center_joins as center
import test_vcpack as vcpack
from test_vcpack_extensions import sections
from phonomenal.vcpack import string,_write_sections


class StableCutTests(unittest.TestCase):
    native=vcpack.VcpackTests.native
    write=center.CenterJoinTests.write

    def setUp(self):
        center.CenterJoinTests.setUp(self)
        self.enrich()

    def enrich(self,features=True,reliable=True):
        pitch=struct.pack('<II',1,len(self.records))
        for record in self.records:
            pitch+=string(record['id'])+struct.pack('<I',len(record['phones']))
            for phone in record['phones']:
                marks=([2237,2317,2397,2477,2557] if record['id']=='left' else [6089,6169,6249,6329,6409]) if phone['label']=='AA1' else []
                pitch+=struct.pack('<3fI',200. if marks else 0.,0.,1. if reliable and marks else 0.,len(marks))
                pitch+=struct.pack('<'+'Q'*len(marks),*marks)
        self.write({'PITC':pitch})
        if features:
            frames=np.zeros((125,11),dtype='<f4');frames[:,0]=200;frames[:,1]=1;frames[:,2]=.2
            for i in range(125):
                target=32 if i<60 else 80
                frames[i,3]=(i-target)**2*.02;frames[i,4]=-frames[i,3]
            payload=struct.pack('<IIQ',80,11,len(frames))+frames.tobytes()
            parts=sections(self.pack)
            _write_sections(self.pack,[(tag,flags,raw) for tag,(flags,raw) in parts.items()]+[(b'FEAT',0,payload)])

    def plan(self,*flags,phones='K AA1 T'):
        return json.loads(self.native('--phones',phones,'--plan',*flags).stdout)

    def test_stable_option_uses_nearby_reliable_pulses_instead_of_changing_default(self):
        before=self.plan();after=self.plan('--stable-vowel-cuts')
        self.assertEqual([(u['start_sample'],u['end_sample']) for u in before['units']],[(0,2397),(6249,8640)])
        self.assertEqual([(u['start_sample'],u['end_sample']) for u in after['units']],[(0,2557),(6409,8640)])
        for original,changed in [(2397,2557),(6249,6409)]:self.assertLessEqual(abs(changed-original),320)
        self.assertTrue(after['units'][0]['ends_at_phone_center'])
        self.assertTrue(after['units'][1]['starts_at_phone_center'])

    def test_missing_features_and_unreliable_voicing_leave_original_cuts(self):
        for features,reliable in [(False,True),(True,False)]:
            self.enrich(features,reliable)
            self.assertEqual(self.plan(),self.plan('--stable-vowel-cuts'))

    def test_complete_native_word_and_phone_run_keep_original_audio(self):
        for command in [('--text','leftword'),('--phones','K AA1')]:
            before=self.native(*command,'--stdout-wav').stdout
            after=self.native(*command,'--stable-vowel-cuts','--stdout-wav').stdout
            self.assertEqual(before,after)

    def test_stop_bursts_cannot_get_stable_center_cuts(self):
        self.records[0]['phones'][1]['label']='T';self.records[1]['phones'][0]['label']='T';self.enrich()
        for u in self.plan('--stable-vowel-cuts',phones='K T T')['units']:
            self.assertFalse(u.get('starts_at_phone_center'))
            self.assertFalse(u.get('ends_at_phone_center'))
