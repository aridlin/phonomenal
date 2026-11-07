import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

import numpy as np
from phonomenal.synthesis_defaults import configure_synthesis
from phonomenal.vcpack import HEADER,DIRECTORY,_write_sections,write_pack,string
import test_vcpack


class SynthesisDefaultTests(unittest.TestCase):
    native=test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pack=Path(self.tmp.name)/'voice.vcpack'
        self.audio=(np.sin(np.arange(10000)*2*np.pi*180/16000)*6000).astype('<i2')
        self.records=[dict(id='left',words=[dict(label='left',start=0,end=3840)],phones=[
            dict(label='K',word=0,start=0,end=960),dict(label='AA1',word=0,start=960,end=3840)]),
            dict(id='right',words=[dict(label='right',start=4800,end=8640)],phones=[
            dict(label='AA1',word=0,start=4800,end=7680),dict(label='T',word=0,start=7680,end=8640)])]
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=self.audio.tobytes(),records=self.records,features=False)
        self.original=self.pack.read_bytes();self.base=self.sections()

    def sections(self):
        raw=self.pack.read_bytes();out={}
        for i in range(HEADER.unpack_from(raw)[2]):
            tag,flags,start,size,*_=DIRECTORY.unpack_from(raw,HEADER.size+i*DIRECTORY.size);out[tag]=(flags,raw[start:start+size])
        return out

    def plan(self,*args):
        return json.loads(self.native('--phones','K AA1 T','--plan',*args).stdout)

    def wav(self,*args):
        return self.native('--phones','K AA1 T','--stdout-wav',*args).stdout

    def attach(self,blob):
        _write_sections(self.pack,[(k,f,b) for k,(f,b) in self.base.items()]+[(b'SOPT',0,blob)])

    def test_old_bank_uses_previous_default(self):
        self.assertEqual(self.plan(),self.plan('--center-join-cost','35'))
        self.assertEqual(self.wav(),self.wav('--center-join-cost','35'))

    def test_bank_preference_matches_explicit_policy_and_override_restores_previous_result(self):
        before,before_wav=self.plan(),self.wav()
        expected,expected_wav=self.plan('--center-join-cost','100'),self.wav('--center-join-cost','100')
        self.assertNotEqual(expected['score'],before['score'])
        configure_synthesis(self.pack,center_join_cost=100)
        self.assertEqual(self.plan(),expected);self.assertEqual(self.wav(),expected_wav)
        self.assertEqual(self.plan('--center-join-cost','35'),before)
        self.assertEqual(self.wav('--center-join-cost','35'),before_wav)
        for tag,payload in self.base.items():self.assertEqual(self.sections()[tag],payload)

    def test_output_copy_and_removal_preserve_source(self):
        target=Path(self.tmp.name)/'copy.vcpack'
        configure_synthesis(self.pack,center_join_cost=100,output=target)
        self.assertEqual(self.pack.read_bytes(),self.original)
        self.assertNotEqual(target.read_bytes(),self.original)
        configure_synthesis(target,center_join_cost=35)
        configure_synthesis(target,center_join_cost=None)
        self.assertEqual(target.read_bytes(),self.original)

    def test_future_preferences_are_ignored(self):
        plan,wav=self.plan(),self.wav()
        for payload in [struct.pack('<I',2),struct.pack('<I',2)+b'future data']:
            self.attach(payload);self.assertEqual(self.plan(),plan);self.assertEqual(self.wav(),wav)

    def test_invalid_preference_is_rejected_before_audio_output(self):
        payloads=[b'',b'\x01',struct.pack('<I',1),struct.pack('<If',1,35)+b'trailing']
        payloads += [struct.pack('<If',1,cost) for cost in [float('nan'),float('inf'),-1,1001]]
        for i,payload in enumerate(payloads):
            with self.subTest(case=i):
                self.attach(payload);result=self.native('--phones','K AA1 T','--stdout-wav',check=False)
                self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,b'')

    def test_invalid_python_values_leave_bank_untouched(self):
        for value in [True,'35',float('nan'),float('inf'),-1,1001]:
            with self.subTest(value=str(value)):
                with self.assertRaises(ValueError):configure_synthesis(self.pack,center_join_cost=value)
                self.assertEqual(self.pack.read_bytes(),self.original)

    def test_explicit_cli_values_are_validated(self):
        for value in ['nan','inf','-1','1001','35ms','invalid']:
            result=self.native('--phones','K AA1 T','--center-join-cost',value,'--stdout-wav',check=False)
            self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,b'')
        for value in ['0','1000']:self.plan('--center-join-cost',value)

    def test_preference_cannot_override_manual_phone_rejection(self):
        review=struct.pack('<II',1,2)
        for record,states in zip(self.records,[[0,2],[0,0]]):
            review+=string(record['id'])+struct.pack('<I',len(states))+b''.join(struct.pack('<I',v) for v in states)
        _write_sections(self.pack,[(k,f,b) for k,(f,b) in self.base.items()]+[(b'QREV',0,review)])
        configure_synthesis(self.pack,center_join_cost=100)
        for unit in self.plan()['units']:
            if unit['clip_id']=='left':self.assertLessEqual(unit['end_sample'],960)
