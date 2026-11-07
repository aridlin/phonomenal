import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave
import zlib

import numpy as np
from phonomenal.vcpack import HEADER, DIRECTORY, _write_sections, string, write_pack
import test_vcpack


class AcousticPhoneScoreTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pack = Path(self.tmp.name) / 'voice.vcpack'
        tone = (6000*np.sin(2*np.pi*200*np.arange(4800)/16000)).astype('<i2')
        self.audio = np.concatenate([tone, np.zeros(1600, dtype='<i2'), tone])
        self.records = []
        for rid, offset in [('first', 0), ('second', 6400)]:
            self.records.append(dict(id=rid, words=[dict(label='shared', start=offset, end=offset+4800)],
                phones=[dict(label=p, word=0, start=offset+a, end=offset+b)
                    for p,a,b in [('K',0,960),('AA1',960,3840),('T',3840,4800)]]))
        self.write()

    def sections(self):
        raw = self.pack.read_bytes()
        out = {}
        for i in range(HEADER.unpack_from(raw)[2]):
            tag,flags,start,size,*_ = DIRECTORY.unpack_from(raw, HEADER.size+i*DIRECTORY.size)
            out[tag] = (flags, raw[start:start+size])
        return out

    def write(self, review=None):
        extra = {}
        if review is not None:
            blob = struct.pack('<II',1,len(self.records))
            for r, states in zip(self.records,review):
                blob += string(r['id'])+struct.pack('<I',len(r['phones']))
                blob += b''.join(struct.pack('<I',v) for v in states)
            extra['QREV'] = blob
        write_pack(self.pack,voice='synthetic',language='en',rate=16000,
            pcm=self.audio.tobytes(),records=self.records,features=False,extra_sections=extra)
        self.base = self.sections()

    def scores(self, penalties=None, version=1, audio_crc=None, record_crc=None, records=None):
        records = self.records if records is None else records
        audio_crc = zlib.crc32(self.base[b'AUDI'][1]) if audio_crc is None else audio_crc
        record_crc = zlib.crc32(self.base[b'RECS'][1]) if record_crc is None else record_crc
        data = struct.pack('<IIII',version,audio_crc,record_crc,len(records))
        for r, values in zip(records, penalties or [[-1.]*len(r['phones']) for r in records]):
            data += string(r['id'])+struct.pack('<I',len(r['phones']))
            data += b''.join(struct.pack('<f',v) for v in values)
        return data

    def attach(self, data):
        sections = [(tag,flags,payload) for tag,(flags,payload) in self.base.items() if tag!=b'GOPQ']
        _write_sections(self.pack,sections+[(b'GOPQ',0,data)])

    def plan(self, *flags, text=None):
        args = ['--text',text] if text else ['--phones','K AA1 T']
        return json.loads(self.native(*args,'--plan',*flags).stdout)

    def wav(self, *flags):
        return self.native('--phones','K AA1 T','--stdout-wav',*flags).stdout

    def test_scores_are_opt_in_and_choose_the_better_source_without_editing_audio(self):
        default_plan, default_wav = self.plan(), self.wav()
        self.assertEqual({u['clip_id'] for u in default_plan['units']},{'first'})
        self.attach(self.scores([[60.]*3,[0.]*3]))
        self.assertEqual(self.plan(),default_plan)
        self.assertEqual(self.wav(),default_wav)
        chosen = self.plan('--acoustic-phone-scores')
        self.assertEqual({u['clip_id'] for u in chosen['units']},{'second'})
        self.assertEqual(chosen['units'][0]['start_sample'],6400)
        self.assertEqual(chosen['units'][0]['end_sample'],11200)
        with wave.open(io.BytesIO(self.wav('--acoustic-phone-scores')),'rb') as f:
            samples = np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
        np.testing.assert_array_equal(samples,self.audio[6400:11200])

    def test_manual_acceptance_overrides_scores_and_rejection_remains_absolute(self):
        self.write(review=[[1]*3,[0]*3])
        self.attach(self.scores([[60.]*3,[0.]*3]))
        for text in [None,'shared']:
            self.assertEqual({u['clip_id'] for u in self.plan('--acoustic-phone-scores',text=text)['units']},{'first'})
        self.write(review=[[2]*3,[0]*3])
        self.attach(self.scores([[0.]*3,[60.]*3]))
        for text in [None,'shared']:
            self.assertEqual({u['clip_id'] for u in self.plan('--acoustic-phone-scores',text=text)['units']},{'second'})

    def test_absent_unknown_and_zero_scores_leave_old_banks_unchanged(self):
        plan, wav = self.plan(), self.wav()
        self.assertEqual(self.plan('--acoustic-phone-scores'),plan)
        self.assertEqual(self.wav('--acoustic-phone-scores'),wav)
        for values in [[[-1.]*3]*2, [[0.]*3]*2]:
            self.attach(self.scores(values))
            self.assertEqual(self.plan('--acoustic-phone-scores'),plan)
            self.assertEqual(self.wav('--acoustic-phone-scores'),wav)

    def test_source_audio_or_record_edits_invalidate_old_scores(self):
        original_scores = self.scores([[60.]*3,[0.]*3])
        for which in ['audio','records']:
            with self.subTest(which=which):
                original_audio, original_records = self.audio.copy(), copy.deepcopy(self.records)
                if which=='audio': self.audio[1200] += 1
                else: self.records[0]['words'][0]['label'] = 'edited'
                self.write()
                reference = self.plan('--acoustic-phone-scores'), self.wav('--acoustic-phone-scores')
                self.attach(original_scores)
                self.assertEqual((self.plan('--acoustic-phone-scores'),self.wav('--acoustic-phone-scores')),reference)
                self.audio, self.records = original_audio, original_records

    def test_stale_or_future_optional_scores_are_not_applied(self):
        plan, wav = self.plan(), self.wav()
        current = self.scores([[60.]*3,[0.]*3])
        a,r = struct.unpack_from('<II',current,4)
        for blob in [struct.pack('<I',2)+b'future bytes',struct.pack('<III',1,a^1,r)+b'stale',struct.pack('<III',1,a,r^1)+b'stale']:
            self.attach(blob)
            self.assertEqual(self.plan('--acoustic-phone-scores'),plan)
            self.assertEqual(self.wav('--acoustic-phone-scores'),wav)

    def test_malformed_matching_scores_fail_before_synthesis(self):
        good = self.scores([[0.]*3,[0.]*3])
        bad = [b'',good[:3],good[:8],good[:-1],good+b'trailing']
        bad += [self.scores([[v]*3,[0.]*3]) for v in [float('nan'),float('inf'),-2.,60.001]]
        bad += [good[:12]+struct.pack('<I',3)+good[16:]]
        records = copy.deepcopy(self.records);records[0]['id']='wrong'
        bad.append(self.scores([[0.]*3,[0.]*3],records=records))
        records = copy.deepcopy(self.records);records[0]['phones'].pop()
        bad.append(self.scores([[0.]*3,[0.]*3],records=records))
        for i, blob in enumerate(bad):
            with self.subTest(case=i):
                self.attach(blob)
                result = self.native('--phones','K AA1 T','--acoustic-phone-scores','--stdout-wav',check=False)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,b'')

    def test_only_emitted_halves_contribute_to_center_join_source_cost(self):
        self.records = [dict(id='left',words=[dict(label='left',start=0,end=3840)],phones=[
            dict(label='K',word=0,start=0,end=960),dict(label='AA1',word=0,start=960,end=3840)]),
            dict(id='right',words=[dict(label='right',start=4800,end=8640)],phones=[
            dict(label='AA1',word=0,start=4800,end=7680),dict(label='T',word=0,start=7680,end=8640)])]
        self.write();before = self.plan('--center-phone-joins');wav = self.wav('--center-phone-joins')
        self.attach(self.scores([[10.,20.],[30.,40.]]))
        after = self.plan('--center-phone-joins','--acoustic-phone-scores')
        self.assertEqual(after['units'],before['units'])
        self.assertAlmostEqual(after['score']-before['score'],10.+20./2+30./2+40.,places=2)
        self.assertEqual(self.wav('--center-phone-joins','--acoustic-phone-scores'),wav)

    def test_long_native_transition_includes_interior_scores_once(self):
        self.audio = (np.linspace(-10000,10000,16000)).astype('<i2')
        self.records = [dict(id='long',words=[dict(label='source',start=0,end=9120)],phones=[
            dict(label=p,word=0,start=a,end=b) for p,a,b in [('N',0,800),('K',800,1760),('AA1',1760,4640),('S',4640,6240),('IH1',6240,9120)]]),
            dict(id='tail',words=[dict(label='tail',start=10000,end=13840)],phones=[
                dict(label='IH1',word=0,start=10000,end=12880),dict(label='T',word=0,start=12880,end=13840)])]
        self.write()
        args = ('--phones','K AA1 S IH1 T','--center-run-phones','12','--plan')
        before = json.loads(self.native(*args).stdout)
        self.attach(self.scores([[2.]*5,[2.]*2]))
        after = json.loads(self.native(*args,'--acoustic-phone-scores').stdout)
        self.assertEqual(after['units'],before['units'])
        self.assertTrue(any(u.get('center_run_phone_count',0)>=4 for u in after['units']))
        self.assertAlmostEqual(after['score']-before['score'],10.,places=2)

    def test_whole_word_cost_retains_recorded_word_quality_weight(self):
        before = self.plan(text='shared')
        self.attach(self.scores([[2.]*3,[2.]*3]))
        after = self.plan('--acoustic-phone-scores',text='shared')
        self.assertEqual(before['units'],after['units'])
        self.assertAlmostEqual(after['score']-before['score'],3*2*.35,places=2)

    def test_rejected_interior_phone_cannot_hide_in_a_scored_long_transition(self):
        self.audio = np.linspace(-10000,10000,16000).astype('<i2')
        self.records = [dict(id='long',words=[dict(label='source',start=0,end=9120)],phones=[
            dict(label=p,word=0,start=a,end=b) for p,a,b in [('N',0,800),('K',800,1760),('AA1',1760,4640),('S',4640,6240),('IH1',6240,9120)]]),
            dict(id='tail',words=[dict(label='tail',start=10000,end=13840)],phones=[
                dict(label='IH1',word=0,start=10000,end=12880),dict(label='T',word=0,start=12880,end=13840)]),
            dict(id='fallback',words=[dict(label='fallback',start=14500,end=15500)],phones=[dict(label='S',word=0,start=14500,end=15500)])]
        self.write(review=[[0,0,0,2,0],[0,0],[0]])
        self.attach(self.scores([[0.]*5,[0.]*2,[60.]]))
        result=json.loads(self.native('--phones','K AA1 S IH1 T','--center-run-phones','12','--acoustic-phone-scores','--plan').stdout)
        self.assertTrue(any(u['clip_id']=='fallback' for u in result['units']))
        for unit in result['units']:
            if unit['clip_id']=='long':self.assertTrue(unit['end_sample']<=4640 or unit['start_sample']>=6240)
