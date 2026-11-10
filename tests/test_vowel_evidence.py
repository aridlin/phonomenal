import json
from pathlib import Path
import struct
import tempfile
import unittest
from phonomenal.vcpack import write_pack,string
import test_vcpack


class VowelEvidenceTests(unittest.TestCase):
    native=test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pack=Path(self.tmp.name)/'voice.vcpack'
        self.records=[dict(id=name,words=[dict(label='same',start=start,end=start+2000)],
            phones=[dict(label='AH1',word=0,start=start,end=start+2000)])
            for name,start in [('disputed',0),('supported',4000)]]

    def write(self,review=False,evidence=True):
        trust=struct.pack('<II',1,2)
        trust+=string('disputed')+struct.pack('<I5I',1,0,1,2,0,0)
        trust+=string('supported')+struct.pack('<I5I',1,1,0,1,1,1920)
        extras={'TRST':trust} if evidence else {}
        if review:
            extras['QREV']=struct.pack('<II',1,2)+string('disputed')+struct.pack('<II',1,1)+string('supported')+struct.pack('<II',1,0)
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=struct.pack('<h',1000)*8000,
                   records=self.records,features=False,lexicon={'unseen':['AH1']},extra_sections=extras)

    def test_fallback_can_prefer_a_supported_vowel_without_losing_coverage(self):
        self.write()
        original=json.loads(self.native('--text','unseen','--plan').stdout)
        biased=json.loads(self.native('--text','unseen','--prefer-supported-vowels','--plan').stdout)
        self.assertEqual([u['clip_id'] for u in original['units']],['disputed'])
        self.assertEqual([u['clip_id'] for u in biased['units']],['supported'])

    def test_intact_words_and_manual_acceptance_keep_their_priority(self):
        self.write()
        word=json.loads(self.native('--text','same','--prefer-supported-vowels','--plan').stdout)
        self.assertEqual([u['clip_id'] for u in word['units']],['disputed'])
        self.write(review=True)
        manual=json.loads(self.native('--text','unseen','--prefer-supported-vowels','--plan').stdout)
        self.assertEqual([u['clip_id'] for u in manual['units']],['disputed'])

    def test_unmeasured_packs_are_not_given_fake_identity_evidence(self):
        self.write(evidence=False)
        plain=json.loads(self.native('--text','unseen','--plan').stdout)
        biased=json.loads(self.native('--text','unseen','--prefer-supported-vowels','--plan').stdout)
        self.assertEqual(plain,biased)

    def test_cut_preference_changes_exposed_vowel_but_preserves_intact_word(self):
        records=[];trust=struct.pack('<II',1,3)
        for name,start,evidence in [('disputed',0,(0,1,2,0,0)),('supported',4000,(1,0,1,1,1920)),('tail',8000,(1,0,2,0,0))]:
            labels=['AH1','T'] if name=='tail' else ['K','AH1']
            middle=start+(1600 if name=='tail' else 800)
            records.append(dict(id=name,words=[dict(label='same' if name!='tail' else 'tailword',start=start,end=start+2400)],phones=[
                dict(label=labels[0],word=0,start=start,end=middle),dict(label=labels[1],word=0,start=middle,end=start+2400)]))
            trust+=string(name)+struct.pack('<I',2)
            for label in labels:trust+=struct.pack('<5I',*(evidence if label=='AH1' else (1,0,2,0,0)))
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=struct.pack('<h',1000)*12000,
            records=records,features=False,lexicon={'unseen':['K','AH1','T']},extra_sections={'TRST':trust})
        original=json.loads(self.native('--text','unseen','--plan').stdout)
        biased=json.loads(self.native('--text','unseen','--prefer-supported-vowel-cuts','--plan').stdout)
        self.assertEqual(original['units'][0]['clip_id'],'disputed')
        self.assertEqual(biased['units'][0]['clip_id'],'supported')
        self.assertTrue(biased['units'][0]['ends_at_phone_center'])
        word=json.loads(self.native('--text','same','--prefer-supported-vowel-cuts','--plan').stdout)
        self.assertEqual([u['clip_id'] for u in word['units']],['disputed'])

    def test_cut_preference_does_not_penalize_complete_phone_fallback(self):
        self.write()
        plain=json.loads(self.native('--text','unseen','--plan').stdout)
        biased=json.loads(self.native('--text','unseen','--prefer-supported-vowel-cuts','--plan').stdout)
        self.assertEqual(plain,biased)
