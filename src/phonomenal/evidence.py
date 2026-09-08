"""Independent recognition evidence, not manufactured alignment confidence.

Recognizer observations retain their labels, clocks and provenance. Disagreement
never moves a source cut automatically. TRST is a small reader-facing summary;
EVID retains the full, reviewable observations and rejected alternatives.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import wave

import numpy as np

VERSION = 3
IPA = dict(zip('ɑ æ ʌ ɔ aʊ aɪ ɛ ɝ eɪ ɪ i oʊ ɔɪ ʊ u b tʃ d ð f ɡ h dʒ k l m n ŋ p ɹ s ʃ t θ v w j z ʒ ə ɚ'.split(),
               'AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW B CH D DH F G HH JH K L M N NG P R S SH T TH V W Y Z ZH AH ER'.split()))

IPA.update({"t͡ʃ":"CH", "d͡ʒ":"JH", "ɹ̩":"ER", "r":"R", "ɾ":"T", "ɫ":"L", "ɐ":"AH", "ɜ":"ER", "ɒ":"AA", "a":"AA", "o":"OW", "e":"EY"})

def normalized(label):
    return re.sub(r"[^a-z0-9']", '', label.lower())


def matched_indices(reference, observed):
    """Keep matching islands even when a recognizer misses an earlier word."""
    matcher = SequenceMatcher(a=reference, b=observed, autojunk=False)
    return {a+k: b+k for a, b, n in matcher.get_matching_blocks() for k in range(n)}


def compare_record(record, observations, rate, origin):
    words = record['words']; phones = record['phones']
    word_rows = [dict(support=0, dispute=0, radius_samples=0, alternatives=[]) for _ in words]
    phone_rows = [dict(support=0, dispute=0, radius_samples=0, alternatives=[]) for _ in phones]
    for observation in observations:
        if observation['kind'] == 'words':
            seen = observation['items']
            matches = matched_indices([normalized(w['label']) for w in words], [normalized(w['label']) for w in seen])
            for i, w in enumerate(words):
                row = word_rows[i]
                if i not in matches:
                    row['dispute'] += 1
                    continue
                other = seen[matches[i]]
                if other.get('crossed_file_boundary'):continue
                row['support'] += 1
                start = origin + round(other['start'] * rate); end = origin + round(other['end'] * rate)
                radius = max(abs(w['start']-start), abs(w['end']-end)) + round(observation['resolution_ms']*rate/1000)
                row['radius_samples'] = max(row['radius_samples'], radius)
                row['alternatives'].append(dict(detector=observation['detector'], start=start, end=end))
        else:
            seen = observation['items']
            matches = matched_indices([p['label'].rstrip('012') for p in phones], [p.get('arpabet', '?') for p in seen])
            for i, p in enumerate(phones):
                row = phone_rows[i]
                # CTC emissions are points inside phones, not precise cut positions.
                overlaps = [x for x in seen if origin+round(x['start']*rate) < p['end']+rate*.045 and
                            origin+round(x['end']*rate) > p['start']-rate*.045]
                if i in matches and seen[matches[i]] in overlaps:
                    row['support'] += 1
                elif overlaps and any(x.get('arpabet') for x in overlaps):
                    row['dispute'] += 1
                row['alternatives'].extend(dict(x, detector=observation['detector']) for x in overlaps)
    for p, row in zip(phones, phone_rows):
        if 0 <= p['word'] < len(word_rows):
            word = word_rows[p['word']]
            row['word_support'] = word['support']; row['word_dispute'] = word['dispute']
            # Word boundaries constrain only the corresponding outer phone edge.
            if p['start'] == words[p['word']]['start'] or p['end'] == words[p['word']]['end']:
                row['radius_samples'] = word['radius_samples']
        else:
            row['word_support'] = row['word_dispute'] = 0
    return dict(id=record['id'], words=word_rows, phones=phone_rows, observations=observations)


def trust_bytes(records, rows):
    from phonomenal.vcpack import string
    out = bytearray(struct.pack('<II', 1, len(records)))
    for r, row in zip(records, rows):
        out += string(r['id']) + struct.pack('<I', len(r['phones']))
        for p in row['phones']:
            out += struct.pack('<5I', p['support'], p['dispute'], p['word_support'], p['word_dispute'], p['radius_samples'])
    return bytes(out)


def contextual_metadata(records, pcm, rate, features):
    """Compact distributions, variants and source-boundary descriptors."""
    hop, dims, count = struct.unpack_from('<IIQ', features)
    frames = np.frombuffer(features, dtype='<f4', offset=16).reshape(count, dims)
    variants = defaultdict(Counter); durations = defaultdict(list); contexts = []; inventory = Counter()
    for record in records:
        phones = record['phones']; items = []
        for wi, w in enumerate(record['words']):
            pronunciation = tuple(p['label'] for p in phones if p['word'] == wi)
            if pronunciation: variants[normalized(w['label'])][pronunciation] += 1
        for i, p in enumerate(phones):
            duration = 1000*(p['end']-p['start'])/rate
            durations[p['label']].append(duration); inventory[p['label'].rstrip('012')] += 1
            first = max(0, p['start']//hop); last = min(count, (p['end']+hop-1)//hop)
            local = frames[first:last]
            edges = []
            for edge in (p['start'], p['end']):
                at = min(count-1, edge//hop); f = frames[max(0, at-1):min(count, at+2)]
                edges.append(dict(sample=edge, rms=float(np.mean(f[:, 2])), spectrum=np.mean(f[:, 3:], axis=0).tolist()))
            items.append(dict(label=p['label'], left=phones[i-1]['label'] if i else None,
                right=phones[i+1]['label'] if i+1<len(phones) else None, word=p['word'],
                stress=int(p['label'][-1]) if p['label'][-1:] in ('0','1','2') else None,
                edges=edges, contour_hop_samples=hop,
                contour=[[first+j, float(f[0]), float(f[1]), float(f[2])] for j, f in enumerate(local)],
                protected_edge_samples=round(.012*rate)))
        contexts.append(dict(id=record['id'], phones=items))
    return dict(version=1, source_sha256=hashlib.sha256(pcm).hexdigest(), frame_hop_samples=hop,
        measurements_are_confidence=False, records=contexts,
        pronunciation_variants={w:[dict(phones=list(p),count=n) for p,n in counts.most_common()] for w,counts in variants.items()},
        durations={p:dict(count=len(v), p10=float(np.percentile(v,10)), median=float(np.median(v)), p90=float(np.percentile(v,90))) for p,v in durations.items()},
        coverage=dict(inventory), speaker=dict(median_rms=float(np.median(frames[:,2])),
        median_voiced_f0=float(np.median(frames[frames[:,0]>0,0])) if np.any(frames[:,0]>0) else None))


def run_detector(name, model, jobs, result):
    """Child process loads one model, completes cached jobs, then releases RAM."""
    if name == 'vosk':
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1); recognizer = Model(str(model))
    elif name == 'allosaurus':
        import torch
        torch.set_num_threads(2)
        from allosaurus.app import read_recognizer
        recognizer = read_recognizer(model)
    elif name == 'whisper':
        from faster_whisper import WhisperModel
        recognizer = WhisperModel(model, device='cpu', compute_type='int8', cpu_threads=2, download_root=str(Path(__file__).resolve().parents[2]/'data/cache/asr'))
    else: raise ValueError('Unknown detector')
    version = importlib.metadata.version({'whisper':'faster-whisper'}.get(name,name))
    jobs=json.loads(Path(jobs).read_text())
    if name=='whisper':
        from faster_whisper.audio import decode_audio
        from phonomenal.transcription import split_batch_words
        groups=defaultdict(list)
        for job in jobs:groups[job['group']].append(job)
        for group,members in groups.items():
            if all(Path(j['output']).exists() for j in members):continue
            audio=[];metadata=[];cursor=0
            for j in members:
                if audio:audio.append(np.zeros(6400,dtype=np.float32));cursor+=6400
                samples=decode_audio(j['audio'],sampling_rate=16000)
                metadata.append(dict(id=j['id'],offset_samples=cursor,sample_count=len(samples)))
                audio.append(samples);cursor+=len(samples)
            segments,_=recognizer.transcribe(np.concatenate(audio),language='en',beam_size=5,word_timestamps=True,
                condition_on_previous_text=False,initial_prompt=None,vad_filter=False)
            split=split_batch_words(list(segments),metadata,16000)
            for j in members:
                items=[dict(label=w['word'].strip(),start=w['start'],end=w['end'],raw_confidence=w['probability'],
                    crossed_file_boundary=w['crossed_file_boundary']) for s in split[j['id']] for w in s['words']]
                value=dict(detector=name,model=model,package_version=version,kind='words',resolution_ms=20,
                    boundary_semantics='word estimate',reference_prompt_used=False,batch_source_sha256=group,items=items)
                dest=Path(j['output']);tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(dest)
                print(f'{name}: {j["id"]}',flush=True)
        Path(result).write_text('complete\n');return
    for job in jobs:
        dest = Path(job['output'])
        if dest.exists(): continue
        path = job['audio']; items = []
        if name == 'vosk':
            with wave.open(path,'rb') as f:
                rec = KaldiRecognizer(recognizer, f.getframerate()); rec.SetWords(True)
                while data := f.readframes(4000):
                    if rec.AcceptWaveform(data): items.extend(json.loads(rec.Result()).get('result',[]))
                items.extend(json.loads(rec.FinalResult()).get('result',[]))
            items = [dict(label=x['word'],start=x['start'],end=x['end'],raw_confidence=x['conf']) for x in items]
        elif name == 'whisper':
            segments, _ = recognizer.transcribe(path, language='en', word_timestamps=True, beam_size=5,
                condition_on_previous_text=False, initial_prompt=None, vad_filter=False)
            items = [dict(label=w.word.strip(),start=w.start,end=w.end,raw_confidence=w.probability) for s in segments for w in s.words or []]
        else:
            raw = recognizer.recognize(path, 'eng', timestamp=True)
            for line in raw.splitlines():
                start, duration, label = line.split(maxsplit=2)
                items.append(dict(label=label, arpabet=IPA.get(label), start=float(start), end=float(start)+float(duration)))
        value = dict(detector=name,model=str(model),package_version=version,kind='phones' if name=='allosaurus' else 'words',
            resolution_ms=45 if name=='allosaurus' else (30 if name=='vosk' else 20),
            boundary_semantics='approximate CTC emission' if name=='allosaurus' else 'word estimate',
            reference_prompt_used=False,items=items)
        tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(dest)
        print(f'{name}: {job["id"]}', flush=True)
    Path(result).write_text('complete\n')


def analyze_pack(path, output, cache=None, vosk_model=None, whisper_model='small.en', phone_model='eng2102', limit=None):
    from phonomenal.acoustics import enrich_pack
    from phonomenal.pack_editor import read_pack
    from phonomenal.vcpack import HEADER, DIRECTORY, _write_sections
    path, output = Path(path).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError('Choose a new output filename')
    cache = Path(cache or output.parent/'.phonomenal-analysis').resolve();cache.mkdir(parents=True,exist_ok=True)
    if not vosk_model or not Path(vosk_model).is_dir():
        raise ValueError('Set --vosk-model to the extracted vosk-model-small-en-us-0.15 directory; see docs/DETECTORS.md')
    meta, records, _, _, pcm, _ = read_pack(path);rate=meta['rate']
    with tempfile.TemporaryDirectory(prefix='phonomenal-evidence-',dir=cache) as temp:
        temp=Path(temp); enriched=temp/'acoustic.vcpack';report=enrich_pack(path,enriched)
        raw=enriched.read_bytes();sections={}
        for i in range(HEADER.unpack_from(raw)[2]):
            tag, flags, start, length, _, _ = DIRECTORY.unpack_from(raw, HEADER.size+DIRECTORY.size*i)
            sections[tag]=(flags,raw[start:start+length])
        selected=records[:limit] if limit else records
        jobs=[];origins={}
        for i,r in enumerate(selected):
            spans=r['words']+r['phones'];start=max(0,min(p['start'] for p in spans)-rate//10);end=min(len(pcm)//2,max(p['end'] for p in spans)+rate//10)
            audio=pcm[start*2:end*2];digest=hashlib.sha256(struct.pack('<I',rate)+audio).hexdigest();wav=temp/f'{i}.wav'
            with wave.open(str(wav),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(audio)
            jobs.append(dict(id=r['id'],audio=str(wav),digest=digest,seconds=(end-start)/rate));origins[r['id']]=start
        results=defaultdict(list)
        for detector, model in [('whisper',whisper_model),('vosk',str(Path(vosk_model).resolve())),('allosaurus',phone_model)]:
            # Content fingerprint includes all model files for local Vosk models.
            model_hash=hashlib.sha256(str(model).encode())
            if detector=='vosk':
                for file in sorted(Path(model).rglob('*')):
                    if file.is_file():model_hash.update(file.relative_to(model).as_posix().encode());model_hash.update(file.read_bytes())
            package=importlib.metadata.version({'whisper':'faster-whisper'}.get(detector,detector))
            key=hashlib.sha256(f'{VERSION}|{model_hash.hexdigest()}|{package}|{detector}'.encode()).hexdigest()[:24]
            directory=cache/key;directory.mkdir(exist_ok=True)
            detector_jobs=[dict(j,output=str(directory/(j['digest']+'.json'))) for j in jobs]
            if detector=='whisper':
                groups=[];pending=[];seconds=0.
                for j in detector_jobs:
                    if pending and seconds+j['seconds']+.4>25:groups.append(pending);pending=[];seconds=0.
                    pending.append(j);seconds+=j['seconds']+.4
                if pending:groups.append(pending)
                for members in groups:
                    group=hashlib.sha256('|'.join(j['digest'] for j in members).encode()).hexdigest()
                    for j in members:
                        j['group']=group;j['output']=str(directory/(hashlib.sha256((j['digest']+group).encode()).hexdigest()+'.json'))
            manifest=temp/'jobs.json';manifest.write_text(json.dumps(detector_jobs))
            if any(not Path(j['output']).exists() for j in detector_jobs):
                subprocess.run([sys.executable,'-m','phonomenal.evidence','--worker',detector,'--model',str(model),
                    '--jobs',str(manifest),'--result',str(temp/'finished')],check=True)
            for j in detector_jobs:results[j['id']].append(json.loads(Path(j['output']).read_text()))
        rows=[compare_record(r,results[r['id']],rate,origins.get(r['id'],0)) for r in records]
        context=contextual_metadata(records,pcm,rate,sections[b'FEAT'][1])
        context['trusted_coverage']=dict(Counter(p['label'].rstrip('012') for r,row in zip(records,rows)
            for p,e in zip(r['phones'],row['phones']) if e['support'] and not e['dispute'] and e['word_support']>=2 and not e['word_dispute']))
        evidence=dict(version=1,source_sha256=hashlib.sha256(pcm+sections[b'RECS'][1]).hexdigest(),
            calibrated=False, analyzed_recordings=len(selected), records=rows)
        report['independent_evidence']=dict(version=1,analyzed_recordings=len(selected),total_recordings=len(records),
            detectors=['whisper','vosk','allosaurus'],calibrated=False,
            disputed_phones=sum(bool(p['dispute'] or p['word_dispute']) for r in rows for p in r['phones']))
        sections.update({b'TRST':(0,trust_bytes(records,rows)),b'EVID':(0,json.dumps(evidence).encode()),
            b'PROS':(0,json.dumps(context).encode()),b'QARE':(0,json.dumps(report).encode())})
        _write_sections(output,[(tag,flags,data) for tag,(flags,data) in sections.items() if tag!=b'SPEC'])
        return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--worker',required=True);parser.add_argument('--model',required=True)
    parser.add_argument('--jobs',required=True);parser.add_argument('--result',required=True)
    args=parser.parse_args();run_detector(args.worker,args.model,args.jobs,args.result)
