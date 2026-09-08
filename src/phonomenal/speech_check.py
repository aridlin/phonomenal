"""Independent, unprompted STT comparison for rendered speech.

Word agreement is a diagnostic, not a human-listening or naturalness score.
"""
from __future__ import annotations
import re
from pathlib import Path


def words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", text.lower().replace('\u2019', "'"))


def compare_words(expected, recognized):
    reference, hypothesis = words(expected), words(recognized)
    if not reference:
        raise ValueError('Expected text must contain spoken words')
    costs = [list(range(len(hypothesis)+1))]
    for i in range(1, len(reference)+1):
        row=[i]+[0]*len(hypothesis)
        for j in range(1, len(hypothesis)+1):
            row[j]=min(costs[i-1][j-1]+(reference[i-1]!=hypothesis[j-1]), costs[i-1][j]+1, row[j-1]+1)
        costs.append(row)
    errors=costs[-1][-1]
    edits=[]; i=len(reference); j=len(hypothesis)
    while i or j:
        if i and j and reference[i-1]==hypothesis[j-1]:
            i-=1; j-=1
        elif i and j and costs[i][j]==costs[i-1][j-1]+1:
            edits.append(dict(operation='substitution',expected=reference[i-1],heard=hypothesis[j-1]));i-=1;j-=1
        elif i and costs[i][j]==costs[i-1][j]+1:
            edits.append(dict(operation='missing',expected=reference[i-1],heard=''));i-=1
        else:
            edits.append(dict(operation='extra',expected='',heard=hypothesis[j-1]));j-=1
    edits.reverse()
    return dict(expected=expected,recognized=recognized,word_errors=errors,reference_words=len(reference),
                word_error_rate=errors/len(reference),words_match=errors==0,
                spacing_only_difference=errors>0 and "".join(reference)=="".join(hypothesis),differences=edits)


def verify_speech(audio, expected, model='small.en', recognizer=None):
    if len(words(expected)) > 512:
        raise ValueError('Speech checks support up to 512 expected words')
    if recognizer is None:
        from faster_whisper import WhisperModel
        root=Path(__file__).resolve().parents[2]
        recognizer=WhisperModel(model,device='cpu',compute_type='int8',cpu_threads=2,download_root=str(root/'data/cache/asr'))
    # Never pass expected text as an initial prompt/hotword: it would bias this check.
    segments,_=recognizer.transcribe(str(audio),language='en',beam_size=5,vad_filter=False,
                                    condition_on_previous_text=False,temperature=0.,word_timestamps=True)
    segments=list(segments)
    result=compare_words(expected,' '.join(s.text.strip() for s in segments).strip())
    result.update(model=model,unprompted=True,audio=str(Path(audio).resolve()),
                  recognized_words=[dict(word=w.word.strip(),start=w.start,end=w.end,probability=w.probability)
                                    for s in segments for w in (s.words or [])],
                  limitation='STT agreement does not prove intelligibility to a listener or natural voice quality.')
    return result
