import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import wave

import numpy as np
from phonomenal.acoustics import enrich_pack
from phonomenal.pack_editor import read_pack
from phonomenal.vcpack import write_pack, extract_features, _write_sections
from test_vcpack import CLI
from test_vcpack_extensions import sections


class AcousticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.pack=self.root/'voice.vcpack';self.rate=16000
        rng=np.random.default_rng(15)
        self.audio=np.concatenate([rng.normal(0,1200,3200),np.sin(np.arange(9600)*2*np.pi*200/16000)*6000,rng.normal(0,1500,3200)]).astype('<i2')
        self.records=[dict(id='speech',words=[dict(label='test',start=0,end=16000)],phones=[
            dict(label='T',word=0,start=0,end=3200),dict(label='EH1',word=0,start=3200,end=12800),dict(label='S',word=0,start=12800,end=16000)])]

    def write(self,**kwargs):
        write_pack(self.pack,voice='any speaker',language='en',rate=self.rate,pcm=self.audio.tobytes(),records=self.records,**kwargs)

    def native(self,*args,check=True):
        if not CLI.exists():self.skipTest('Build C++ CLI first')
        return subprocess.run([str(CLI),'--bank',str(self.pack),*args],capture_output=True,check=check)

    def test_pitch_fundamental_not_arbitrary_subharmonic(self):
        for hz in [80,120,200,310,440]:
            t=np.arange(16000)/16000
            audio=(5000*np.sin(2*np.pi*hz*t)+2000*np.sin(4*np.pi*hz*t)).astype('<i2')
            features=extract_features(audio.tobytes(),16000)
            f=np.frombuffer(features,dtype='<f4',offset=16).reshape(-1,11)[10:-10]
            self.assertAlmostEqual(float(np.median(f[:,0])),hz,delta=5)

    def test_pitch_preserves_consonants_edges_duration_and_limits_shift(self):
        self.write()
        for band,target in [('100:100',200*2**-.25),('300:300',200*2**.25)]:
            report=self.root/'audit.json'
            result=self.native('--text','test','--pitch-band',band,'--audit',str(report),'--stdout-wav')
            with wave.open(io.BytesIO(result.stdout),'rb') as f:
                samples=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
            self.assertEqual(len(samples),len(self.audio))
            np.testing.assert_array_equal(samples[:3328],self.audio[:3328])
            np.testing.assert_array_equal(samples[12672:],self.audio[12672:])
            middle=samples[5000:11000]
            measured=np.fft.rfftfreq(len(middle),1/16000)[np.abs(np.fft.rfft(middle*np.hanning(len(middle)))).argmax()]
            self.assertAlmostEqual(measured,target,delta=5)
            a=json.loads(report.read_text())['pitch_adjustments'];self.assertEqual(len(a),1)
            self.assertEqual((a[0]['start_sample'],a[0]['end_sample']),(3200,12800))

    def test_old_pack_pitch_fails_closed_and_enrichment_preserves_payloads(self):
        self.write(features=False,extra_sections={'FUTR':b'opaque future metadata'})
        original=self.pack.read_bytes();old=sections(self.pack)
        plain=self.native('--text','test','--stdout-wav').stdout
        self.assertEqual(self.native('--text','test','--pitch-band','100:100','--stdout-wav').stdout,plain)
        enriched=self.root/'enriched.vcpack';enrich_pack(self.pack,enriched)
        current=sections(enriched)
        for tag in [b'META',b'RECS',b'AUDI',b'LEXI',b'FUTR']:
            self.assertEqual(old[tag],current[tag])
        self.assertEqual(self.pack.read_bytes(),original)
        self.assertIn(b'ACOU',current);self.assertEqual(current[b'ACOU'][0],0)
        self.assertTrue(enriched.read_bytes().endswith(Path('src/phonomenal/vcpack_spec.txt').read_bytes()))
        self.pack=enriched;self.native('--inspect')

    def test_acoustic_quality_avoids_silent_vowel_despite_valid_timing(self):
        self.audio=np.concatenate([np.zeros(4000),np.sin(np.arange(4000)*2*np.pi*200/16000)*6000]).astype('<i2')
        self.records=[dict(id=name,words=[dict(label='hello',start=start,end=start+4000)],
                           phones=[dict(label='EH1',word=0,start=start,end=start+4000)]) for name,start in [('silent',0),('voiced',4000)]]
        self.write()
        plan=json.loads(self.native('--text','hello','--strict','--plan').stdout)
        self.assertEqual(plan['units'][0]['clip_id'],'voiced')

    def test_canonical_lexicon_and_majority_are_not_last_take(self):
        self.records=[dict(id=str(i),words=[dict(label='test',start=0,end=16000)],phones=[dict(label=p,word=0,start=0,end=16000)]) for i,p in enumerate(['EH1','EH1','AH0'])]
        self.write(features=False)
        self.assertEqual(read_pack(self.pack)[2]['test'],['EH1'])
        self.write(features=False,lexicon={'test':['T','EH1','S','T']})
        self.assertEqual(read_pack(self.pack)[2]['test'],['T','EH1','S','T'])

    def test_keeps_known_words_instead_of_reusing_a_different_words_phone_run(self):
        self.records=[
            dict(id='known',words=[dict(label='alpha',start=0,end=3200)],phones=[dict(label='AA1',word=0,start=0,end=3200)]),
            dict(id='ending',words=[dict(label='beta',start=3200,end=4800)],phones=[dict(label='B',word=0,start=3200,end=4800)]),
            dict(id='unrelated',words=[dict(label='other',start=6400,end=11200)],phones=[dict(label='AA1',word=0,start=6400,end=9600),dict(label='B',word=0,start=9600,end=11200)])]
        self.write(features=False)
        plan=json.loads(self.native('--text','alpha beta','--plan').stdout)
        self.assertEqual([u['clip_id'] for u in plan['units']],['known','ending'])

    def test_duration_normalization_preserves_pitch_and_maps_all_boundaries(self):
        for duration in [800, 9600]:
            self.audio=(np.sin(np.arange(duration)*2*np.pi*200/16000)*6000).astype('<i2')
            self.records=[dict(id='0',words=[dict(label='target',start=0,end=duration)],
                phones=[dict(label='EH1',word=0,start=0,end=duration)])]
            self.write()
            # Supply independently measured corpus statistics without adding
            # alternative audio that the planner would correctly prefer.
            payloads=sections(self.pack); ac=bytearray(payloads[b'ACOU'][1])
            offset=8+4+1+4
            struct.pack_into('<f',ac,offset+32,-3. if duration<4000 else 3.)
            struct.pack_into('<ffI',ac,offset+40,250.,.35,9)
            _write_sections(self.pack,[(tag,flags,bytes(ac) if tag==b'ACOU' else data) for tag,(flags,data) in payloads.items()])
            report=self.root/'duration.json'
            result=self.native('--text','target','--normalize-duration','--audit',str(report),'--stdout-wav')
            with wave.open(io.BytesIO(result.stdout),'rb') as f: samples=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
            audit=json.loads(report.read_text());self.assertEqual(audit['duration_adjustments'],1)
            self.assertGreater(len(samples),duration) if duration<4000 else self.assertLess(len(samples),duration)
            np.testing.assert_array_equal(samples[:192],self.audio[:192])
            np.testing.assert_array_equal(samples[-192:],self.audio[duration-192:duration])
            ends=[b['output_sample'] for b in audit['boundaries'] if b['edge']=='end']
            self.assertEqual(set(ends),{len(samples)})
            hz=np.fft.rfftfreq(len(samples),1/16000)[np.abs(np.fft.rfft(samples*np.hanning(len(samples)))).argmax()]
            self.assertAlmostEqual(hz,200,delta=12)

    def test_adaptive_gaps_only_between_mixed_words(self):
        self.audio=np.ones(4800,dtype='<i2')*1000
        self.records=[dict(id=str(i),words=[dict(label=label,start=i*1600,end=(i+1)*1600)],
            phones=[dict(label=phone,word=0,start=i*1600,end=(i+1)*1600)]) for i,(label,phone) in enumerate([('alpha','AA1'),('beta','B'),('other','T')])]
        self.write(features=False)
        report=self.root/'gap.json'
        result=self.native('--text','alpha beta','--audit',str(report),'--stdout-wav')
        audit=json.loads(report.read_text());self.assertEqual(audit['word_pauses'],1)
        self.assertEqual(audit['word_pause_samples'],800) # 70 - .2*100 = 50 ms.
        with wave.open(io.BytesIO(result.stdout),'rb') as f: self.assertEqual(f.getnframes(),4000)
        self.native('--text','alpha beta','--no-auto-word-gaps','--audit',str(report),'--stdout-wav')
        self.assertEqual(json.loads(report.read_text())['word_pauses'],0)

    def test_reader_rejects_bad_measurement_and_ignores_future_optional_version(self):
        self.write();payloads=sections(self.pack);ac=bytearray(payloads[b'ACOU'][1])
        # version, record count, string length + 'speech', phone count, pitch.
        struct.pack_into('<f',ac,8+4+len('speech')+4,float('nan'))
        _write_sections(self.pack,[(tag,flags,bytes(ac) if tag==b'ACOU' else data) for tag,(flags,data) in payloads.items()])
        self.assertNotEqual(self.native('--inspect',check=False).returncode,0)
        struct.pack_into('<I',ac,0,999)
        _write_sections(self.pack,[(tag,flags,bytes(ac) if tag==b'ACOU' else data) for tag,(flags,data) in payloads.items()])
        self.native('--inspect')


if __name__=='__main__':unittest.main()
