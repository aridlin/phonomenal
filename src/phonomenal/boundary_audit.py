"""Per-boundary structural, waveform and cross-aligner timing diagnostics.

Acoustic checks flag suspicious intervals, not proof of linguistic correctness.
"""
from __future__ import annotations
import math
import re


def audit_boundaries(words, phones, pcm, rate, asr_words=()):
    import numpy as np
    from phonomenal.vcpack import validate_records
    validate_records([dict(id='audit',words=words,phones=phones)],len(pcm)//2,rate)
    audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768.
    radius=max(1,round(rate*.005))
    rows=[];warnings=[]
    for tier,units in [('word',words),('phone',phones)]:
        for index,unit in enumerate(units):
            start,end=unit['start'],unit['end'];duration=(end-start)*1000/rate
            segment=audio[start:end]
            rms=float(np.sqrt(np.mean(segment*segment)))
            flags=[]
            if rms<.002:flags.append('near_silent_interval')
            if float(np.mean(np.abs(segment)>=.999))>.02:flags.append('clipped_interval')
            if tier=='phone':
                vowel=unit['label'].rstrip('012') in 'AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW'.split()
                minimum=45 if vowel else 12
                if duration<minimum:flags.append('short_phone')
                if duration>(650 if vowel else 300):flags.append('long_phone')
            for edge,sample in [('start',start),('end',end)]:
                left=audio[max(0,sample-radius):sample];right=audio[sample:min(len(audio),sample+radius)]
                jump=abs(float(audio[sample])-float(audio[sample-1])) if 0<sample<len(audio) else 0.
                row=dict(tier=tier,index=index,label=unit['label'],edge=edge,sample=sample,
                         time_ms=sample*1000/rate,interval_rms=rms,duration_ms=duration,
                         sample_jump=jump,left_rms=float(np.sqrt(np.mean(left*left))) if len(left) else 0.,
                         right_rms=float(np.sqrt(np.mean(right*right))) if len(right) else 0.,flags=list(flags))
                if jump>.35:row['flags'].append('large_sample_jump')
                rows.append(row)
    norm=lambda x: ''.join(re.findall(r"[a-z']+",x.lower()))
    timing_compared=0
    if asr_words and [norm(w['label']) for w in words]==[norm(w['word']) for w in asr_words]:
        for index,(word,asr) in enumerate(zip(words,asr_words)):
            for edge in ['start','end']:
                delta=abs(word[edge]/rate-asr[edge])*1000
                row=rows[index*2+(edge=='end')]
                row['asr_alignment_difference_ms']=delta;timing_compared+=1
                if delta>80:row['flags'].append('asr_alignment_disagreement_over_80ms')
                if asr.get('crossed_file_boundary'):row['flags'].append('asr_crossed_recording_boundary')
    elif asr_words:
        warnings.append('ASR and aligned word sequences differ; timestamp comparison was not possible')
    return dict(version=1,boundaries_checked=len(rows),flagged_boundaries=sum(bool(r['flags']) for r in rows),
                structural_valid=True,linguistic_accuracy_verified=False,asr_boundaries_compared=timing_compared,
                checks=['sample bounds','ordered intervals','phone-word containment','duration','local waveform','available ASR timing agreement'],
                warnings=warnings,boundaries=rows,
                limitation='These diagnostics do not prove every word or phoneme boundary is linguistically correct.')
