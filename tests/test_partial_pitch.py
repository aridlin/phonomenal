import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

import numpy as np
from phonomenal.vcpack import write_pack,string
import test_vcpack


class PartialPitchTests(unittest.TestCase):
    native=test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.pack=self.root/'voice.vcpack'
        self.write()

    def write(self,right_hz=270,pitch=True):
        rng=np.random.default_rng(3)
        self.audio=np.concatenate([rng.normal(0,600,800),
            6000*np.cos(2*np.pi*240*np.arange(4800)/16000),np.zeros(800),
            6000*np.cos(2*np.pi*right_hz*np.arange(4800)/16000),rng.normal(0,600,800)]).astype('<i2')
        self.records=[dict(id='left',words=[dict(label='leftword',start=0,end=5600)],phones=[
            dict(label='K',word=0,start=0,end=800),dict(label='EH1',word=0,start=800,end=5600)]),
            dict(id='right',words=[dict(label='rightword',start=6400,end=12000)],phones=[
            dict(label='EH1',word=0,start=6400,end=11200),dict(label='S',word=0,start=11200,end=12000)])]
        data=struct.pack('<II',1,len(self.records))
        for record,hz in zip(self.records,[240,right_hz]):
            data+=string(record['id'])+struct.pack('<I',len(record['phones']))
            for phone in record['phones']:
                marks=[phone['start']+round(n*16000/hz) for n in range(1000)
                       if phone['label']=='EH1' and round(n*16000/hz)<phone['end']-phone['start']]
                data+=struct.pack('<3fI',hz if marks else 0.,0.,1. if marks else 0.,len(marks))
                data+=struct.pack('<'+'Q'*len(marks),*marks)
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=self.audio.tobytes(),
                   records=self.records,features=False,extra_sections={'PITC':data} if pitch else {})

    def render(self,*flags):
        report=self.root/'audit.json'
        result=self.native('--phones','K EH1 S','--center-run-phones','12','--stdout-wav',
                           '--audit',str(report),*flags)
        with wave.open(io.BytesIO(result.stdout)) as wav:
            output=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
        return output,json.loads(report.read_text())

    @staticmethod
    def f0(samples):
        spectrum=np.abs(np.fft.rfft(samples*np.hanning(len(samples)),n=16384))
        frequencies=np.fft.rfftfreq(16384,1/16000)
        spectrum[(frequencies<180)|(frequencies>350)]=0
        return frequencies[spectrum.argmax()]

    def test_partial_matching_aligns_actual_vowel_pitch_and_retains_consonants(self):
        original,before=self.render();legacy,_=self.render('--match-pitch')
        np.testing.assert_array_equal(original,legacy)
        matched,after=self.render('--match-partial-pitch')
        self.assertEqual(len(original),len(matched))
        np.testing.assert_array_equal(original[:800],matched[:800])
        np.testing.assert_array_equal(original[-800:],matched[-800:])
        self.assertEqual(len(after['pitch_adjustments']),2)
        self.assertTrue(all(p['mode']=='match-partial' for p in after['pitch_adjustments']))
        self.assertTrue(all(abs(12*np.log2(p['factor']))<=1.50001 for p in after['pitch_adjustments']))
        ends=[b['output_sample'] for b in before['boundaries'] if b['kind']=='splice' and b['edge']=='end']
        join=ends[0]
        self.assertAlmostEqual(self.f0(matched[1200:join-200]),np.sqrt(240*270),delta=3)
        self.assertAlmostEqual(self.f0(matched[join+200:-1200]),np.sqrt(240*270),delta=3)
        self.assertEqual([(b['kind'],b['edge'],b['output_sample']) for b in before['boundaries']],
                         [(b['kind'],b['edge'],b['output_sample']) for b in after['boundaries']])
        self.assertGreater(np.sqrt(np.mean(matched[join-80:join+80].astype(float)**2)),3500)

    def test_old_packs_and_large_register_changes_remain_unchanged(self):
        for kwargs in [dict(pitch=False),dict(right_hz=400)]:
            self.write(**kwargs)
            original,_=self.render();matched,audit=self.render('--match-partial-pitch')
            np.testing.assert_array_equal(original,matched)
            self.assertEqual(audit['pitch_adjustments'],[])
