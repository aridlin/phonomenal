import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import wave
from phonomenal.vcpack import write_pack, inspect_pack, validate_records
from phonomenal.alignment_quality import compare_boundaries
from phonomenal.align import parse_mfa_alignment

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get('PHONOMENAL_TEST_CLI', ROOT/'cpp/build-vcpack/phonomenal_splicer_cli'))


def fixture(path):
    rate=48000
    words=[];phones=[]
    tokens=['alpha','beta','gamma','delta','epsilon','zeta','eta','theta','iota','kappa','lambda','mu']
    for i, word in enumerate(tokens):
        start=37+i*4800
        words.append(dict(label=word,start=start,end=start+3601))
        phones.append(dict(label='AA1',word=i,start=start,end=start+3200))
        phones.append(dict(label='B',word=i,start=start+3200,end=start+3601))
    pcm=struct.pack('<'+'h'*60000,*[int(5000*((i%61)/30-1)) for i in range(60000)])
    records=[dict(id='continuous-recording',words=words,phones=phones)]
    return write_pack(path,voice='fixture "voice"',language='en-us',rate=rate,pcm=pcm,records=records,lexicon={'newword':['AA','B']},features=True)


class VcpackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pack=Path(self.tmp.name)/'fixture.vcpack';fixture(self.pack)

    def test_checksums_and_self_containment(self):
        report=inspect_pack(self.pack)
        self.assertEqual(report['sample_count'],60000)
        raw=bytearray(self.pack.read_bytes());raw[-1]^=1;self.pack.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'checksum'):inspect_pack(self.pack)

    def test_sample_positions_have_no_centisecond_rounding(self):
        mfa=Path(self.tmp.name)/'align.json'
        mfa.write_text(json.dumps({'tiers':{'words':{'entries':[[.1234375,.2303125,'test']]},'phones':{'entries':[[.1234375,.150125,'T'],[.150125,.2303125,'EH1']]}}}))
        words,phones=parse_mfa_alignment(mfa,.99,48000)
        self.assertEqual(words[0].start_sample,5925)
        self.assertEqual(phones[0].end_sample,7206)
        self.assertIsNone(phones[0].confidence)

    def test_measures_errors_and_label_mismatches_separately(self):
        ref={'one':{'words':[[.1,.2,'a']],'phones':[[.1,.2,'AH']]}}
        pred={'one':{'words':[[.103,.205,'a']],'phones':[[.1,.2,'B']]}}
        result=compare_boundaries(ref,pred)
        self.assertAlmostEqual(result['words']['max_ms'],5)
        self.assertEqual(result['phones']['mismatched_clips'],['one'])
        self.assertIsNone(result['phones']['median_ms'])

    def native(self,*args,check=True):
        if not CLI.exists():self.skipTest('Build native CLI or set PHONOMENAL_TEST_CLI')
        return subprocess.run([str(CLI),'--bank',str(self.pack),*args],capture_output=True,check=check)

    def test_native_prefers_entire_long_phrase(self):
        result=json.loads(self.native('--text','alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu','--plan').stdout)
        self.assertEqual(len(result['units']),1)
        self.assertEqual(result['units'][0]['start_sample'],37)
        self.assertEqual(result['units'][0]['end_sample'],37+11*4800+3601)

    def test_unseen_word_uses_phone_run_not_spelling(self):
        result=json.loads(self.native('--text','newword','--plan','--strict').stdout)
        self.assertEqual(len(result['units']),1)
        self.assertEqual(result['units'][0]['kind'],'phoneme')
        self.assertFalse(result['warnings'])

    def write_phone_choices(self, choices, lexicon):
        rate=48000; records=[]; cursor=0
        for name, labels, durations in choices:
            phones=[]; start=cursor
            for label, duration in zip(labels, durations):
                end=cursor+round(duration*rate)
                phones.append(dict(label=label,word=0,start=cursor,end=end))
                cursor=end
            records.append(dict(id=name,words=[dict(label=name,start=start,end=cursor)],phones=phones))
            cursor+=2400
        pcm=struct.pack('<'+'h'*cursor,*[int(3000*((i%61)/30-1)) for i in range(cursor)])
        write_pack(self.pack,voice='choices',language='en-us',rate=rate,pcm=pcm,records=records,lexicon=lexicon,features=False)

    def test_strict_avoids_collapsed_vowel_even_with_matching_phones(self):
        self.write_phone_choices([
            ('collapsed',['HH','OW1','M'],[.03,.03,.03]),
            ('home',['HH','OW1','M'],[.06,.22,.09]),
        ], {'homophone':['HH','OW1','M']})
        result=json.loads(self.native('--text','homophone','--strict','--plan').stdout)
        self.assertEqual([u['clip_id'] for u in result['units']],['home'])

    def test_strict_rejects_only_suspect_phone_coverage(self):
        self.write_phone_choices([('collapsed',['OW1'],[.03])], {'newword':['OW1']})
        result=self.native('--text','newword','--strict','--plan',check=False)
        self.assertNotEqual(result.returncode,0)

    def test_lexicon_stress_survives_native_reader(self):
        self.write_phone_choices([
            ('reduced',['ER0'],[.12]), ('stressed',['ER1'],[.12]),
        ], {'newword':['ER1']})
        result=json.loads(self.native('--text','newword','--strict','--plan').stdout)
        self.assertEqual(result['units'][0]['clip_id'],'stressed')

    def test_word_final_stop_prefers_source_word_ending(self):
        self.write_phone_choices([
            ('doctor',['AA1','K','T','ER0'],[.12,.07,.05,.12]),
            ('back',['B','AE1','K'],[.07,.14,.07]),
        ], {'closure':['K']})
        result=json.loads(self.native('--text','closure','--strict','--plan').stdout)
        self.assertEqual(result['units'][0]['clip_id'],'back')

    def test_stdout_wav_is_clean_when_plan_requested(self):
        result=self.native('--text','alpha beta','--plan','--stdout-wav')
        self.assertTrue(result.stdout.startswith(b'RIFF'))
        json.loads(result.stderr)
        with wave.open(io.BytesIO(result.stdout),'rb') as w:
            self.assertEqual(w.getframerate(),48000)
            self.assertEqual(w.getnframes(),4800+3601)

    def test_missing_phone_fails_without_silent_omission(self):
        result=self.native('--phones','ZH','--plan','--strict',check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,b'')

    def test_native_rejects_truncation_and_checksum_damage(self):
        original=self.pack.read_bytes()
        for cut in (0,12,23,24,40,100,len(original)-1):
            self.pack.write_bytes(original[:cut])
            self.assertNotEqual(self.native('--inspect',check=False).returncode,0)
        raw=bytearray(original);raw[-1]^=4;self.pack.write_bytes(raw)
        self.assertNotEqual(self.native('--inspect',check=False).returncode,0)

    def test_punctuation_adds_one_pause_at_word_start(self):
        result=json.loads(self.native('--text','alpha. newword','--plan','--strict').stdout)
        self.assertEqual(sum(x['pause_before_ms'] > 0 for x in result['units']),1)
        self.assertEqual(result['units'][-1]['pause_before_ms'],180)

    def test_explicit_phone_search_uses_same_contiguous_planner(self):
        result=json.loads(self.native('--phones','AA B','--plan','--strict').stdout)
        self.assertEqual(len(result['units']),1)
        self.assertFalse(result['warnings'])

if __name__=='__main__':unittest.main()
