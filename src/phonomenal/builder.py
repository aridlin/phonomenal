"""Resumable MP3 -> fine-tuned MFA phones -> VCPACK builder.

No equal-duration phones or word-timestamp substitutes are ever generated.
"""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
import re
import shlex
import shutil
import subprocess
import wave
from pathlib import Path
from phonomenal.vcpack import write_pack, validate_records
from phonomenal.alignment_quality import validate_alignment


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def log(message):
    print(message, flush=True)


def run(command, log_path=None):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if log_path:
        log_path.write_text(result.stdout, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{command[0]} exited {result.returncode}: {result.stdout[-3000:]}')
    return result.stdout


def decode(source, dest, rate):
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-ac', '1', '-ar', str(rate), '-c:a', 'pcm_s16le', str(dest)])


def read_wave(path):
    with wave.open(str(path), 'rb') as wav:
        return wav.getframerate(), wav.readframes(wav.getnframes())


def write_wave(path, pcm, rate):
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


def build_pack(source, output, voice, language='en', model='small.en', mfa_command='mfa', acoustic_model='english_us_arpa', work=None, force=False, device='cpu', tf2=False):
    if language not in ('en', 'en-us', 'en-gb'):
        raise ValueError('This build currently supports English ARPABET packs; additional language profiles need a matched phone set and G2P.')
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir():
        raise ValueError('Source must be a directory of speech recordings')
    project = Path(__file__).resolve().parents[2]
    local_mamba = project / ('.tools/micromamba/Library/bin/micromamba.exe' if os.name == 'nt' else '.tools/micromamba/bin/micromamba')
    if mfa_command == 'mfa' and local_mamba.exists() and (project/'.tools/aligner').exists():
        mfa = [str(local_mamba), 'run', '-p', str(project/'.tools/aligner'), 'python', str(project/'scripts/mfa_entry.py')]
    elif Path(mfa_command).is_file():
        mfa = [mfa_command]
    else:
        mfa = shlex.split(mfa_command, posix=os.name != 'nt')
    if not mfa or not shutil.which(mfa[0]):
        raise RuntimeError('MFA is required for real phoneme timings. Run scripts/setup_builder.sh or set --mfa-command.')
    rate = 48000
    work = Path(work or output.with_suffix('.build')).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source_files = sorted(p for p in source.rglob('*') if p.suffix.lower() in ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.webm') and work not in p.parents)
    if tf2:
        source_files = [p for p in source_files if not any(marker in str(p.relative_to(source)).lower() for marker in ('vo/robot', 'robot_vo', 'robotvoice')) and not p.name.lower().startswith('test_')]
    if not source_files:
        raise ValueError('No audio files found')
    version = run(mfa + ['version']).strip()
    settings = dict(builder=2, language=language, model=model, acoustic_model=acoustic_model, rate=rate, mfa=version, fine_tune=True)
    config_hash = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]
    job = work/config_hash
    job.mkdir(exist_ok=True)
    atomic_json(job/'settings.json', settings)
    corpus = job/'corpus'/'speaker'
    corpus.mkdir(parents=True, exist_ok=True)
    playback = job/'playback'
    playback.mkdir(exist_ok=True)
    clips, rejected, seen = [], [], set()
    asr = None
    def get_recognizer():
        nonlocal asr
        if asr is None:
            from faster_whisper import WhisperModel
            asr = WhisperModel(model, device=device, compute_type='int8' if device=='cpu' else 'float16', cpu_threads=2, download_root=str(project/'data/cache/asr'))
        return asr
    from phonomenal.transcription import batch_short_recordings
    pending=[]
    for path in source_files:
        if path.with_suffix('.txt').exists(): continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        key=hashlib.sha256(digest.encode()).hexdigest()[:24]
        if not force and (job/(key+'.json')).exists(): continue
        if force:
            (job/(key+'.asr.json')).unlink(missing_ok=True)
        pending.append(dict(path=path,key=key))
    batched=batch_short_recordings(pending,job,rate,get_recognizer,decode,log)
    for number, path in enumerate(source_files, 1):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            log(f'[{number}/{len(source_files)}] duplicate skipped: {path.name}')
            continue
        seen.add(digest)
        sidecar = path.with_suffix('.txt')
        supplied = sidecar.read_text(encoding='utf-8').strip() if sidecar.exists() else ''
        key = hashlib.sha256((digest+supplied).encode()).hexdigest()[:24]
        manifest = job/(key+'.json')
        if manifest.exists() and not force:
            saved = json.loads(manifest.read_text())
            if all((playback/(c['id']+'.wav')).exists() and (corpus/(c['id']+'.wav')).exists() for c in saved):
                clips.extend(saved)
                log(f'[{number}/{len(source_files)}] cached: {path.name}')
                continue
        log(f'[{number}/{len(source_files)}] decoding/transcribing: {path.name}')
        decoded = job/(key+'.wav')
        try:
            decode(path, decoded, rate)
            _, pcm = read_wave(decoded)
            duration = len(pcm)/2/rate
            if supplied:
                spans = [dict(start=0., end=duration, text=supplied, confidence=None)]
            elif key in batched:
                spans = batched[key]
            else:
                segments, _ = get_recognizer().transcribe(str(decoded), language='en', beam_size=5, vad_filter=True, word_timestamps=True, condition_on_previous_text=False)
                spans = [dict(start=max(0., s.start-.12), end=min(duration, s.end+.12), text=s.text.strip(), confidence=s.avg_logprob,
                              words=[dict(word=w.word, start=w.start, end=w.end, probability=w.probability) for w in (s.words or [])]) for s in segments if s.text.strip() and s.no_speech_prob < .6]
            saved = []
            for i, span in enumerate(spans):
                text = ' '.join(re.findall(r"[a-z]+(?:'[a-z]+)*", span['text'].lower()))
                if not text:
                    continue
                cid = f'{key}_{i:04d}'
                start, end = round(span['start']*rate), min(len(pcm)//2, round(span['end']*rate))
                if end <= start:
                    continue
                wav = playback/(cid+'.wav')
                write_wave(wav, pcm[start*2:end*2], rate)
                decode(wav, corpus/(cid+'.wav'), 16000)
                (corpus/(cid+'.lab')).write_text(text, encoding='utf-8')
                saved.append(dict(id=cid, transcript=text, raw_transcript=span['text'], source_sha256=digest, source_file=path.name,
                                  source_start_sample=start, source_end_sample=end, asr_logprob=span['confidence'], supplied_transcript=bool(supplied), recognition_method=span.get('recognition_method', 'supplied' if supplied else 'segment-asr'), asr_words=span.get('words', [])))
            atomic_json(manifest, saved)
            clips.extend(saved)
        except Exception as exc:
            rejected.append(dict(source=path.name, reason=str(exc)))
            log('  rejected: '+str(exc))
    if not clips:
        atomic_json(work/'report.json', dict(rejected=rejected))
        raise ValueError('No usable transcripts; see build report')
    # Make corpus membership exact so removed or edited files cannot leak into a resumed job.
    current_ids = {c['id'] for c in clips}
    for p in corpus.iterdir():
        if p.suffix in ('.wav', '.lab') and p.stem not in current_ids:
            p.unlink()
    import cmudict
    lexicon = {w: variants[0] for w, variants in cmudict.dict().items()}
    # Use a supplied MFA model dictionary, with native model G2P for OOVs.
    signature = hashlib.sha256(json.dumps(clips, sort_keys=True).encode()).hexdigest()
    aligned = job/'aligned'
    marker = job/'alignment.complete.json'
    if force or not marker.exists() or json.loads(marker.read_text()).get('signature') != signature or not json.loads(marker.read_text()).get('refinement_verified'):
        log('Aligning words and phonemes, then refining boundaries on the 1 ms grid...')
        run(mfa + ['align', str(corpus.parent), 'english_us_arpa', acoustic_model, str(aligned), '--fine_tune', '--clean', '--overwrite', '--output_format', 'json', '--g2p_model_path', 'english_us_arpa', '--temporary_directory', str(job/'mfa-temp')], job/'mfa.log')
        if 'fine tuning alignments' not in (job/'mfa.log').read_text().lower():
            raise RuntimeError('MFA did not run boundary refinement. Use scripts/mfa-local; this detects and repairs the known MFA 3.3.9 flag bug.')
        atomic_json(marker, dict(signature=signature, refinement_verified=True))
    else:
        log('Using cached fine-tuned alignment')
    from phonomenal.align import parse_mfa_alignment
    records, audio, issues, audits = [], bytearray(), [], []
    for clip in clips:
        alignment_paths = list(aligned.rglob(clip['id']+'.json'))
        if not alignment_paths:
            rejected.append(dict(id=clip['id'], reason='missing MFA alignment'))
            continue
        try:
            words, phones = parse_mfa_alignment(alignment_paths[0], confidence=None, sample_rate=rate)
            _, pcm = read_wave(playback/(clip['id']+'.wav'))
            ws = [dict(label=w.text.lower(), start=w.start_sample, end=w.end_sample, confidence=None) for w in words]
            ps = [dict(label=p.label, word=p.word_index, start=p.start_sample, end=p.end_sample, confidence=None) for p in phones]
            from phonomenal.boundary_audit import audit_boundaries
            audit = audit_boundaries(ws, ps, pcm, rate, clip.get('asr_words', []))
            flags = validate_alignment(ws, ps, len(pcm)//2, rate)
            if flags:
                issues.append(dict(id=clip['id'], flags=flags))
            if ' '.join(w['label'] for w in ws) != clip['transcript']:
                raise ValueError('Aligned words disagree with transcript; inspect raw alignment')
            audits.append(dict(id=clip['id'], source_offset_sample=len(audio)//2, **audit))
            base = len(audio)//2
            for u in ws+ps:
                u['start'] += base
                u['end'] += base
            records.append(dict(id=clip['id'], transcript=clip['raw_transcript'], words=ws, phones=ps))
            audio += pcm + bytes(round(.15*rate)*2)
        except Exception as exc:
            rejected.append(dict(id=clip['id'], reason=str(exc)))
    if not records:
        atomic_json(work/'report.json', dict(rejected=rejected))
        raise ValueError('No structurally valid alignments; see report and MFA log')
    report = dict(settings=settings, alignment_method='MFA fine_tune', alignment_grid_ms=1,
                  boundary_accuracy='unmeasured: use compare-alignments with independent references',
                  accepted_clips=len(records), rejected=rejected, boundary_warnings=issues, sources=clips,
                  boundary_audit=dict(version=1, every_boundary_checked=True, linguistic_accuracy_verified=False,
                    boundaries_checked=sum(a['boundaries_checked'] for a in audits),
                    flagged_boundaries=sum(a['flagged_boundaries'] for a in audits),recordings=audits),
                  versions={p: importlib.metadata.version(p) for p in ('numpy', 'cmudict', 'faster-whisper')})
    log('Extracting boundary acoustics and writing self-contained voice pack...')
    report = write_pack(output, voice=voice, language='en-us', rate=rate, pcm=audio, records=records, report=report, lexicon=lexicon)
    atomic_json(work/'report.json', report)
    log(f'Built {output}: {len(records)} clips, {report["words"]} words, {report["phones"]} phones')
    return report
