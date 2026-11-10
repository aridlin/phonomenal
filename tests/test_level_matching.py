import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np
from phonomenal.vcpack import write_pack,_write_sections
from test_vcpack_extensions import sections
import test_vcpack


class LevelMatchingTests(unittest.TestCase):
    native=test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.pack=self.root/'voice.vcpack'
        rng=np.random.default_rng(9)
        self.audio=np.concatenate([rng.normal(0,100,800),
            1600*np.cos(2*np.pi*180*np.arange(4800)/16000),np.zeros(800),
            6400*np.cos(2*np.pi*180*np.arange(4800)/16000),rng.normal(0,400,800)]).astype('<i2')
        self.records=[dict(id='quiet',words=[dict(label='quietword',start=0,end=5600)],phones=[
            dict(label='K',word=0,start=0,end=800),dict(label='EH1',word=0,start=800,end=5600)]),
            dict(id='loud',words=[dict(label='loudword',start=6400,end=12000)],phones=[
            dict(label='EH1',word=0,start=6400,end=11200),dict(label='S',word=0,start=11200,end=12000)])]
        self.write()

    def write(self,features=True):
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=self.audio.tobytes(),
                   records=self.records,features=features)

    def render(self,*flags,text=None):
        audit=self.root/'audit.json'
        command=['--text',text] if text else ['--phones','K EH1 S']
        result=self.native(*command,'--stdout-wav','--audit',str(audit),*flags)
        with wave.open(io.BytesIO(result.stdout)) as wav:
            output=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
        return output,json.loads(audit.read_text())

    @staticmethod
    def rms(x):return np.sqrt(np.mean(x.astype(float)**2))

    def test_level_jump_reduces_with_pitch_clock_and_within_record_shape_preserved(self):
        original,before=self.render();matched,after=self.render('--match-level')
        self.assertEqual(len(original),len(matched))
        edges=[b['output_sample'] for b in before['boundaries'] if b['kind']=='splice' and b['edge']=='end'];join=edges[0]
        ratio=lambda x:abs(20*np.log10(self.rms(x[join+300:-1000])/self.rms(x[1000:join-300])))
        self.assertGreater(ratio(original),10)
        self.assertLess(ratio(matched),3)
        gains=after['level_adjustments'];self.assertEqual(len(gains),2)
        self.assertTrue(all(abs(20*np.log10(g['applied_gain']))<=6.001 for g in gains))
        np.testing.assert_allclose(matched[:800],np.round(original[:800]*gains[0]['applied_gain']),atol=1)
        np.testing.assert_allclose(matched[-800:],np.round(original[-800:]*gains[1]['applied_gain']),atol=1)
        np.testing.assert_allclose(matched[:join-32],np.round(original[:join-32]*gains[0]['applied_gain']),atol=1)
        np.testing.assert_allclose(matched[join+32:],np.round(original[join+32:]*gains[1]['applied_gain']),atol=1)
        self.assertEqual([(b['kind'],b['edge'],b['output_sample']) for b in before['boundaries']],
                         [(b['kind'],b['edge'],b['output_sample']) for b in after['boundaries']])
        self.assertEqual(after['pitch_adjustments'],[])

    def test_peak_cap_keeps_original_peak_without_turning_boost_into_attenuation(self):
        self.audio[200]=32440;self.write()
        original,_=self.render();output,audit=self.render('--match-level')
        self.assertEqual(output[200],original[200])
        self.assertLessEqual(int(np.max(np.abs(output.astype(np.int32)))),32440)
        limited=[g for g in audit['level_adjustments'] if g['peak_limited']]
        self.assertEqual(len(limited),1)
        self.assertGreater(limited[0]['requested_gain'],1)
        self.assertEqual(limited[0]['applied_gain'],1)

    def test_small_level_difference_and_legacy_joins_remain_unchanged(self):
        original,_=self.render('--boundary-phone-joins')
        matched,audit=self.render('--match-level','--boundary-phone-joins')
        np.testing.assert_array_equal(original,matched)
        self.assertEqual(audit['level_adjustments'],[])
        self.audio[6400:11200]=(self.audio[6400:11200]/4*1.2).astype('<i2');self.write()
        original,_=self.render();matched,audit=self.render('--match-level')
        np.testing.assert_array_equal(original,matched)
        self.assertEqual(audit['level_adjustments'],[])

    def test_standalone_recording_and_missing_features_remain_unchanged(self):
        original,_=self.render(text='quietword');matched,audit=self.render('--match-level',text='quietword')
        np.testing.assert_array_equal(original,matched)
        self.assertEqual(audit['level_adjustments'],[])

    def test_legacy_overlap_with_unknown_recording_level_remains_unchanged(self):
        parts=sections(self.pack);feature=bytearray(parts[b'FEAT'][1])
        hop=int.from_bytes(feature[:4],'little');dims=int.from_bytes(feature[4:8],'little')
        frames=np.frombuffer(feature,dtype='<f4',offset=16).reshape(-1,dims)
        frames[6400//hop:,:2]=0
        _write_sections(self.pack,[(tag,flags,bytes(feature) if tag==b'FEAT' else payload)
                                  for tag,(flags,payload) in parts.items()])
        original,_=self.render('--boundary-phone-joins')
        matched,audit=self.render('--boundary-phone-joins','--match-level')
        np.testing.assert_array_equal(original,matched)
        self.assertEqual(audit['level_adjustments'],[])
        self.write(features=False)
        original,_=self.render();matched,audit=self.render('--match-level')
        np.testing.assert_array_equal(original,matched)
        self.assertEqual(audit['level_adjustments'],[])
