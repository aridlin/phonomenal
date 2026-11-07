import copy
import unittest
from phonomenal.evidence import compare_record


class SpokenWordEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(id='voice', words=[dict(label='their', start=100, end=500),
                          dict(label='home', start=500, end=900)], phones=[
            dict(label=p, word=w, start=a, end=b) for p,w,a,b in
            [('DH',0,100,200),('EH1',0,200,400),('R',0,400,500),
             ('HH',1,500,600),('OW1',1,600,800),('M',1,800,900)]])
        self.observation = dict(detector='local', kind='words', resolution_ms=30,
            items=[dict(label='there', start=.1, end=.5), dict(label='home', start=.5, end=.9)])
        self.pronunciations = {'their':[['DH','EH1','R']], 'there':[['DH','EH0','R']],
                               'home':[['HH','OW1','M']]}

    def compare(self, **kwargs):
        return compare_record(self.record, [self.observation], 1000, 0, **kwargs)

    def test_spoken_form_is_supported_without_relabelling_observations_or_source(self):
        before = copy.deepcopy((self.record,self.observation))
        row = self.compare(word_pronunciations=self.pronunciations)
        self.assertEqual([r['support'] for r in row['words']], [1,1])
        match = row['words'][0]['alternatives'][0]
        self.assertEqual((match['match_type'],match['observed_label']), ('pronunciation','there'))
        self.assertEqual(row['observations'], [self.observation])
        self.assertEqual((self.record,self.observation), before)
        self.assertTrue(all(p['word_support']==1 for p in row['phones']))

    def test_default_and_no_alias_cases_preserve_exact_comparison(self):
        strict = self.compare()
        self.assertEqual(strict['words'][0]['support'],0)
        self.observation['items'][0]['label']='their'
        self.assertEqual(self.compare(),self.compare(word_pronunciations=self.pronunciations))

    def test_both_spellings_must_support_the_complete_aligned_source_pronunciation(self):
        for key in ['their','there']:
            with self.subTest(missing=key):
                pron=copy.deepcopy(self.pronunciations);pron.pop(key)
                self.assertEqual(self.compare(word_pronunciations=pron)['words'][0]['support'],0)
        self.record['phones'][1]['label']='IY1'
        self.assertEqual(self.compare(word_pronunciations=self.pronunciations)['words'][0]['support'],0)

    def test_different_final_consonant_is_not_a_spelling_alias(self):
        self.observation['items'][0]['label']='them'
        self.pronunciations['them']=[['DH','EH1','M']]
        self.assertEqual(self.compare(word_pronunciations=self.pronunciations)['words'][0]['support'],0)

    def test_alias_needs_physical_overlap_and_cannot_cross_a_recording(self):
        item=self.observation['items'][0]
        for start,end,crossed in [(1.,1.4,False),(.1,.5,True),(.1,float('nan'),False),(.5,.5,False)]:
            with self.subTest(start=start,end=end,crossed=crossed):
                item.update(start=start,end=end,crossed_file_boundary=crossed)
                self.assertEqual(self.compare(word_pronunciations=self.pronunciations)['words'][0]['support'],0)

    def test_an_insertion_does_not_erase_a_unique_phonetic_matching_island(self):
        self.observation['items'].insert(0,dict(label='well',start=0.,end=.1))
        self.assertEqual(self.compare(word_pronunciations=self.pronunciations)['words'][0]['support'],1)

    def test_multiple_words_are_never_combined_into_a_source_alias(self):
        self.observation['items'][:1] = [dict(label='the',start=.1,end=.25),
                                       dict(label='air',start=.25,end=.5)]
        self.pronunciations.update(the=[['DH']],air=[['EH1','R']])
        self.assertEqual(self.compare(word_pronunciations=self.pronunciations)['words'][0]['support'],0)

    def test_ambiguous_phonetic_word_occurrences_are_not_guessed(self):
        self.observation['items'].insert(0,dict(label='there',start=.1,end=.5))
        self.assertEqual(self.compare(word_pronunciations=self.pronunciations)['words'][0]['support'],0)

    def test_interjections_do_not_gain_word_identity_through_aliasing(self):
        self.record['words'][0]['label']='oh';self.observation['items'][0]['label']='owe'
        self.record['phones'][:3]=[dict(label='OW1',word=0,start=100,end=500)]
        self.pronunciations.update(oh=[['OW1']],owe=[['OW0']])
        self.assertEqual(self.compare(word_pronunciations=self.pronunciations)['words'][0]['support'],0)


class SpokenWordNativeSelectionTests(unittest.TestCase):
    def test_phonetic_support_recovers_native_transition_without_overriding_review(self):
        import json
        import struct
        import tempfile
        from pathlib import Path
        import numpy as np
        import test_vcpack
        from phonomenal.evidence import trust_bytes
        from phonomenal.vcpack import write_pack, string
        cli=test_vcpack.CLI
        if not cli.exists():self.skipTest('Build the native splicer to check source selection')
        records=[];cursor=0
        for name,labels in [('pear',['P','EH1','R']),('pin',['P','IH1','N']),
                            ('bed',['B','EH1','D']),('ready',['R','EH1','D','IY0']),
                            ('hard',['HH','AA1','R','D'])]:
            start=cursor;phones=[]
            for label in labels:
                length=2240 if label.rstrip('012') in {'EH','IH','IY','AA'} else 1280
                phones.append(dict(label=label,word=0,start=cursor,end=cursor+length));cursor+=length
            records.append(dict(id=name,words=[dict(label=name,start=start,end=cursor)],phones=phones));cursor+=2400
        observation=dict(detector='one',kind='words',resolution_ms=30,
                         items=[dict(label='pair',start=0.,end=records[0]['words'][0]['end']/16000)])
        observations=[observation,dict(observation,detector='two')]
        pronunciations={'pear':[['P','EH1','R']],'pair':[['P','EH1','R']]}
        strict=compare_record(records[0],observations,16000,0)
        supported=compare_record(records[0],observations,16000,0,word_pronunciations=pronunciations)
        pcm=(5000*np.sin(np.arange(cursor)*2*np.pi*200/16000)).astype('<i2').tobytes()
        with tempfile.TemporaryDirectory() as temp:
            self.pack=Path(temp)/'voice.vcpack'
            def save(row,review=False):
                rows=[row]+[dict(phones=[dict(support=0,dispute=0,word_support=0,word_dispute=0,radius_samples=0) for _ in r['phones']]) for r in records[1:]]
                extra={'TRST':trust_bytes(records,rows)}
                if review:
                    data=struct.pack('<II',1,len(records))
                    for r in records:data+=string(r['id'])+struct.pack('<I',len(r['phones']))+b''.join(struct.pack('<I',2 if r['id']=='pear' else 0) for _ in r['phones'])
                    extra['QREV']=data
                write_pack(self.pack,voice='test',language='en',rate=16000,pcm=pcm,records=records,
                           lexicon={'paired':['P','EH1','R','D']},features=False,extra_sections=extra)
            def plan():
                return json.loads(test_vcpack.VcpackTests.native(self,'--text','paired','--plan').stdout)['units']
            save(strict);before=plan()
            save(supported);after=plan()
            self.assertFalse(any(u['clip_id']=='pear' for u in before))
            self.assertTrue(any(u['clip_id']=='pear' for u in after))
            self.assertLess(len(after),len(before))
            save(supported,review=True)
            self.assertFalse(any(u['clip_id']=='pear' for u in plan()))
