"""Bounded ASR windows for short recordings, retaining original file coordinates."""
from __future__ import annotations
import hashlib
import json
import wave
from pathlib import Path


def split_batch_words(segments, clips, rate):
    """Assign recognized words to their original clip; never splice source files.

    Clip dicts contain id, offset_samples and sample_count in the batch clock.
    Returned times use each original file's clock. Cross-file words are flagged.
    """
    assigned={c['id']:[] for c in clips}
    scores={c['id']:[] for c in clips}
    for segment in segments:
        for word in segment.words or []:
            start,end=float(word.start)*rate,float(word.end)*rate
            midpoint=(start+end)/2
            for clip in clips:
                lo=clip['offset_samples'];hi=lo+clip['sample_count']
                if lo <= midpoint < hi:
                    assigned[clip['id']].append(dict(word=word.word,start=max(0.,(start-lo)/rate),
                        end=min(clip['sample_count']/rate,(end-lo)/rate),probability=float(word.probability),
                        crossed_file_boundary=start<lo-rate*.03 or end>hi+rate*.03))
                    scores[clip['id']].append(float(segment.avg_logprob))
                    break
    result={}
    for clip in clips:
        words=assigned[clip['id']]
        result[clip['id']]=[dict(start=0.,end=clip['sample_count']/rate,
            text=' '.join(w['word'].strip() for w in words),words=words,
            confidence=sum(scores[clip['id']])/len(scores[clip['id']]) if words else None,
            recognition_method='bounded-short-file-batch-v1')] if words else []
    return result


def batch_short_recordings(items, job, rate, get_recognizer, decode, log, *, maximum_seconds=25.):
    """Decode once; pack short files into <=25 s ASR windows with silent gaps.

    Each result is cached independently. Long recordings follow the normal ASR
    segment path. No expected words or filenames are supplied to the recognizer.
    """
    results={};pending=[];samples=0;gap=round(rate*.4);seen=set()
    def flush():
        nonlocal pending,samples
        if not pending:return
        metadata=[];pcm=bytearray()
        for item,data in pending:
            if pcm: pcm.extend(bytes(gap*2))
            metadata.append(dict(id=item['key'],offset_samples=len(pcm)//2,sample_count=len(data)//2))
            pcm.extend(data)
        batch=job/'asr-window.wav'
        with wave.open(str(batch),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(pcm)
        log(f'Transcribing one bounded window: {len(pending)} source clips, {len(pcm)/2/rate:.1f} seconds')
        segments,_=get_recognizer().transcribe(str(batch),language='en',beam_size=5,
            vad_filter=False,word_timestamps=True,condition_on_previous_text=False)
        spans=split_batch_words(list(segments),metadata,rate)
        for item,_ in pending:
            value=spans[item['key']];cache=job/(item['key']+'.asr.json')
            temporary=cache.with_suffix('.tmp');temporary.write_text(json.dumps(value));temporary.replace(cache)
            results[item['key']]=value
        pending=[];samples=0
    for item in items:
        if item['key'] in seen: continue
        seen.add(item['key'])
        cache=job/(item['key']+'.asr.json')
        if cache.exists():
            results[item['key']]=json.loads(cache.read_text());continue
        decoded=job/(item['key']+'.wav')
        try:
            if not decoded.exists():decode(item['path'],decoded,rate)
            with wave.open(str(decoded)) as f:
                count=f.getnframes()
                if count/rate>maximum_seconds:continue
                pcm=f.readframes(count)
        except Exception as exc:
            log(f'Cannot prepare {item["path"].name} for a short-file batch: {exc}');continue
        if pending and samples+count+gap>maximum_seconds*rate:flush()
        samples+=count+(gap if pending else 0)
        pending.append((item,pcm))
    flush()
    return results
