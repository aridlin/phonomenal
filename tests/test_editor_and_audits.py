import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
import wave

import numpy as np
from phonomenal.boundary_audit import audit_boundaries
from phonomenal.pack_editor import open_project, save_project, read_pack, preview, replace_audio, change_record
from phonomenal.transcription import split_batch_words, batch_short_recordings, transcript_issue
from phonomenal.vcpack import write_pack
from test_vcpack import CLI


class EditorAndAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.pack=self.root/'original.vcpack';self.rate=16000
        self.pcm=(np.sin(np.arange(16000)*2*np.pi*200/self.rate)*6000).astype('<i2').tobytes()
        self.words=[dict(label='tone',start=0,end=16000)]
        self.phones=[dict(label='OW1',word=0,start=0,end=16000)]
        self.records=[dict(id='sample',transcript='tone',words=self.words,phones=self.phones)]
        write_pack(self.pack,voice='test',language='en-us',rate=self.rate,pcm=self.pcm,records=self.records,
                   lexicon={'example':['EH1','G']},extra_sections={'FUTR':b'\x00future\xff'})

    def test_editor_roundtrip_preserves_audio_extensions_and_lexicon(self):
        original=self.pack.read_bytes();project=self.root/'project';open_project(self.pack,project)
        lex=json.loads((project/'lexicon.json').read_text());lex['tone']=['T','OW1','N']
        (project/'lexicon.json').write_text(json.dumps(lex))
        output=self.root/'edited.vcpack';save_project(project,output)
        meta,records,actual,extras,pcm,report=read_pack(output)
        self.assertEqual(pcm,self.pcm);self.assertEqual(extras,read_pack(self.pack)[3])
        self.assertEqual(actual['tone'],['T','OW1','N']);self.assertEqual(actual['example'],['EH1','G'])
        self.assertEqual(self.pack.read_bytes(),original)
        self.assertEqual(report['boundary_audit']['boundaries_checked'],4)
        self.assertFalse(report['boundary_audit']['recordings'][0]['linguistic_accuracy_verified'])
        with self.assertRaisesRegex(ValueError,'never overwritten'):save_project(project,output)

    def test_editor_changed_labels_samples_and_audio_reach_new_pack(self):
        project=self.root/'project';open_project(self.pack,project)
        record=dict(id='edited',transcript='new',words=[dict(label='new',start=137,end=9137)],
                    phones=[dict(label='UW1',word=0,start=137,end=9137)])
        (project/'record-000000.json').write_text(json.dumps(record))
        output=self.root/'preview.wav';preview(project,0,output)
        with wave.open(str(output),'rb') as f:self.assertEqual(f.readframes(f.getnframes()),self.pcm[274:18274])
        save_project(project,self.root/'new.vcpack')
        self.assertEqual(read_pack(self.root/'new.vcpack')[1][0]['phones'][0]['start'],137)
        record['phones'][0]['end']=10000
        (project/'record-000000.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'outside'):save_project(project,self.root/'bad.vcpack')
        self.assertFalse((self.root/'bad.vcpack').exists())

    def test_every_edge_checked_and_silence_and_disagreement_flagged(self):
        result=audit_boundaries(self.words,self.phones,bytes(32000),self.rate,
                                [dict(word='tone',start=.2,end=.7,crossed_file_boundary=True)])
        self.assertEqual(result['boundaries_checked'],4)
        self.assertEqual(result['asr_boundaries_compared'],2)
        for row in result['boundaries']:self.assertIn('near_silent_interval',row['flags'])
        self.assertIn('asr_alignment_disagreement_over_80ms',result['boundaries'][0]['flags'])
        self.assertIn('asr_crossed_recording_boundary',result['boundaries'][0]['flags'])

    def test_editor_add_remove_recordings_and_replace_master(self):
        project=self.root/'project';open_project(self.pack,project)
        change_record(project,0)
        change_record(project,0,delete=True)
        with self.assertRaisesRegex(ValueError,'at least one'):change_record(project,1,delete=True)
        replacement=self.root/'replacement.wav'
        with wave.open(str(replacement),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(self.rate);f.writeframes(bytes(len(self.pcm)))
        replace_audio(project,replacement)
        output=self.root/'changed.vcpack';save_project(project,output)
        _,records,_,_,pcm,_=read_pack(output)
        self.assertEqual(len(records),1);self.assertIn('-copy-',records[0]['id'])
        self.assertEqual(pcm,bytes(len(self.pcm)))
        preview(project,1,self.root/'range.wav',137,9137)
        with wave.open(str(self.root/'range.wav'),'rb') as f:self.assertEqual(f.getnframes(),9000)

    def test_asr_words_keep_original_file_coordinates_and_ignore_gap(self):
        clips=[dict(id='a',offset_samples=0,sample_count=16000),dict(id='b',offset_samples=22400,sample_count=16000)]
        words=[NS(word='hello',start=.1,end=.6,probability=.9),NS(word='noise',start=1.1,end=1.2,probability=.3),NS(word='world',start=1.35,end=1.8,probability=.8)]
        result=split_batch_words([NS(words=words,avg_logprob=-.2)],clips,16000)
        self.assertEqual(result['a'][0]['text'],'hello');self.assertEqual(result['b'][0]['text'],'world')
        word=result['b'][0]['words'][0];self.assertEqual(word['start'],0)
        self.assertAlmostEqual(word['end'],.4);self.assertTrue(word['crossed_file_boundary'])

    def test_batch_is_bounded_and_deduplicates_audio_keys(self):
        calls=[]
        def decode(src,dest,rate):
            with wave.open(str(dest),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(bytes(rate*2))
        class Recognizer:
            def transcribe(_self,path,**kwargs):
                with wave.open(path,'rb') as f:seconds=f.getnframes()/f.getframerate()
                calls.append((seconds,kwargs));return [],None
        items=[dict(key=k,path=Path(k+'.mp3')) for k in ['a','a','b','c']]
        results=batch_short_recordings(items,self.root,16000,Recognizer,decode,lambda _:None,maximum_seconds=2.4)
        self.assertEqual(len(calls),2);self.assertEqual(set(results),{'a','b','c'})
        self.assertTrue(all(seconds<=2.4 for seconds,_ in calls))
        self.assertTrue(all('initial_prompt' not in kwargs and kwargs['word_timestamps'] for _,kwargs in calls))

    def test_runaway_asr_tokens_rejected_before_g2p(self):
        self.assertIsNotNone(transcript_issue('ho'*250,2))
        self.assertIsNotNone(transcript_issue('raaaaaarrrrrrrrrrrrrrrrrr',2))
        self.assertIsNotNone(transcript_issue('hello '*80,1))
        self.assertIsNone(transcript_issue('pneumonoultramicroscopicsilicovolcanoconiosis',4))
        self.assertIsNone(transcript_issue('You are straight and I approve',2))

    def test_pitch_raises_and_lowers_without_changing_duration(self):
        if not CLI.exists():self.skipTest('Native CLI unavailable')
        for band,target in [('100:100',100),('300:300',300)]:
            report=self.root/'audit.json'
            result=subprocess.run([str(CLI),'--bank',str(self.pack),'--text','tone','--pitch-band',band,'--audit',str(report),'--stdout-wav'],capture_output=True,check=True)
            with wave.open(io.BytesIO(result.stdout),'rb') as f:
                self.assertEqual(f.getnframes(),16000);samples=np.frombuffer(f.readframes(16000),dtype='<i2')[2000:-2000]
            spectrum=np.abs(np.fft.rfft(samples*np.hanning(len(samples))))
            measured=np.fft.rfftfreq(len(samples),1/16000)[spectrum.argmax()]
            self.assertAlmostEqual(measured,target,delta=8)
            audit=json.loads(report.read_text());self.assertEqual(audit['boundaries_checked'],6)
            self.assertEqual(len(audit['pitch_adjustments']),1)
            self.assertTrue(all(0<=b['output_sample']<=16000 for b in audit['boundaries']))

    def test_exact_word_cannot_bypass_strict_collapsed_vowel_filter(self):
        if not CLI.exists():self.skipTest('Native CLI unavailable')
        records=[dict(id='scream',words=[dict(label='you',start=0,end=400)],phones=[dict(label='UW1',word=0,start=0,end=400)]),
                 dict(id='speech',words=[dict(label='you',start=2000,end=5000)],phones=[dict(label='UW1',word=0,start=2000,end=5000)])]
        write_pack(self.pack,voice='any-voice',language='en-us',rate=16000,pcm=self.pcm,records=records)
        result=subprocess.run([str(CLI),'--bank',str(self.pack),'--text','you','--strict','--plan'],capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)['units'][0]['clip_id'],'speech')


if __name__=='__main__':unittest.main()
