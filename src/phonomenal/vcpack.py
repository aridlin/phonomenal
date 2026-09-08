"""VCPACK v1: portable typed binary sections, sample coordinates, embedded PCM.

The schema is deliberately independent of Python; see docs/vcpack_format.md.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import struct
import tempfile
import wave
import zlib
from pathlib import Path

MAGIC = b'VCPACK\0\0'
HEADER = struct.Struct('<8sIIQ')
DIRECTORY = struct.Struct('<4sIQQII')
MAX_BYTES = 2 * 1024**3


def string(value):
    encoded = str(value).encode('utf-8')
    return struct.pack('<I', len(encoded)) + encoded


def confidence(value):
    return -1.0 if value is None else max(0.0, min(1.0, float(value)))


def validate_records(records, sample_count, sample_rate):
    """Structural validation is distinct from measured alignment accuracy."""
    ids = set()
    for record in records:
        if record['id'] in ids:
            raise ValueError('Duplicate recording ID')
        ids.add(record['id'])
        if not record['words'] or not record['phones']:
            raise ValueError('Recording has no aligned speech')
        for name in ('words', 'phones'):
            previous = -1
            for unit in record[name]:
                start, end = unit['start'], unit['end']
                if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= sample_count):
                    raise ValueError(f'Invalid {name} sample interval: {start}:{end}')
                if start < previous:
                    raise ValueError(f'Overlapping/out-of-order {name} intervals')
                previous = end
                if not unit['label']:
                    raise ValueError('Empty alignment label')
        for phone in record['phones']:
            wi = phone['word']
            if not 0 <= wi < len(record['words']):
                raise ValueError('Phone references missing word')
            word = record['words'][wi]
            if phone['start'] < word['start'] or phone['end'] > word['end']:
                raise ValueError('Phone extends outside its word')
        # Reject broken 0.001 s "phones"; flag plausible but short sounds for review elsewhere.
        if any(p['end'] - p['start'] < max(1, round(sample_rate * .002)) for p in record['phones']):
            raise ValueError('Implausibly short phone (<2 ms)')


def extract_features(pcm, rate):
    import numpy as np
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
    hop = max(1, round(rate * .005))
    window = max(64, round(rate * .040))
    fft_size = 1 << (2 * window - 1).bit_length()
    features = []
    bands = np.geomspace(60, rate / 2, 9)
    freqs = np.fft.rfftfreq(fft_size, 1 / rate)
    taper = np.hanning(window)
    # Batches bound memory even for hour-long masters.
    padded = np.pad(samples, (window // 2, window))
    for offset in range(0, len(samples), hop * 256):
        positions = np.arange(offset, min(len(samples), offset + hop * 256), hop)
        frames = padded[positions[:, None] + np.arange(window)]
        frames -= frames.mean(axis=1, keepdims=True)
        rms = np.sqrt(np.mean(frames * frames, axis=1))
        spectrum = np.abs(np.fft.rfft(frames * taper, n=fft_size)) ** 2
        ac = np.fft.irfft(np.abs(np.fft.rfft(frames, n=fft_size)) ** 2, n=fft_size)[:, :window]
        lo, hi = max(1, rate // 500), min(window // 2, rate // 60)
        # Normalized correlation, not energy-biased lag selection.
        power = np.cumsum(frames * frames, axis=1)
        lags = np.arange(lo, hi)
        denom = np.sqrt(np.maximum(1e-15, power[:, window - lags - 1] * (power[:, -1, None] - power[:, lags - 1])))
        corr = ac[:, lo:hi] / denom
        best = corr.argmax(axis=1)
        voicing = np.clip(corr[np.arange(len(frames)), best], 0, 1)
        pitch = rate / (best + lo).astype(float)
        pitch[(voicing < .65) | (rms < .003)] = 0
        energies = np.stack([np.log(np.maximum(1e-12, spectrum[:, (freqs >= a) & (freqs < b)].sum(axis=1))) for a, b in zip(bands[:-1], bands[1:])], axis=1)
        energies -= energies.mean(axis=1, keepdims=True)
        features.append(np.column_stack((pitch, voicing, rms, energies)).astype('<f4'))
    values = np.concatenate(features) if features else np.empty((0, 11), dtype='<f4')
    return struct.pack('<IIQ', hop, 11, len(values)) + values.tobytes()


def write_pack(path, *, voice, language, rate, pcm, records, report=None, lexicon=None, features=True):
    if not 8000 <= rate <= 192000 or len(pcm) % 2 or not pcm:
        raise ValueError('Expected nonempty mono PCM16 and valid sample rate')
    validate_records(records, len(pcm) // 2, rate)
    metadata = string(voice) + string(language) + string('arpabet') + struct.pack('<I', rate)
    aligned = bytearray(struct.pack('<I', len(records)))
    for record in records:
        aligned += string(record['id']) + string(record.get('transcript', ''))
        aligned += struct.pack('<I', len(record['words']))
        for word in record['words']:
            aligned += string(word['label']) + struct.pack('<QQf', word['start'], word['end'], confidence(word.get('confidence')))
        aligned += struct.pack('<I', len(record['phones']))
        for phone in record['phones']:
            aligned += string(phone['label']) + struct.pack('<iQQf', phone['word'], phone['start'], phone['end'], confidence(phone.get('confidence')))
    pronunciations = dict(lexicon or {})
    for r in records:
        for wi, w in enumerate(r['words']):
            phones = [p['label'] for p in r['phones'] if p['word'] == wi]
            if phones:
                pronunciations[w['label'].lower()] = phones
    lex = bytearray(struct.pack('<I', len(pronunciations)))
    for word, phones in sorted(pronunciations.items()):
        lex += string(word) + struct.pack('<I', len(phones))
        for phone in phones:
            lex += string(phone)
    report = dict(report or {})
    if lexicon:
        import cmudict
        report.setdefault("licenses", {})["CMUdict"] = cmudict.license_string()
    report.update(format='vcpack-1', sample_resolution_ms=1000/rate,
                  sample_count=len(pcm)//2, audio_sha256=hashlib.sha256(pcm).hexdigest(),
                  words=sum(len(r['words']) for r in records),
                  phones=sum(len(r['phones']) for r in records),
                  phone_inventory=sorted({p['label'].rstrip('012') for r in records for p in r['phones']}))
    sections = [(b'META', metadata), (b'RECS', aligned), (b'AUDI', pcm), (b'LEXI', lex), (b'QARE', json.dumps(report, ensure_ascii=False).encode())]
    if features:
        sections.append((b'FEAT', extract_features(pcm, rate)))
    offset = HEADER.size + DIRECTORY.size * len(sections)
    directory = bytearray()
    for kind, data in sections:
        directory += DIRECTORY.pack(kind, 1 if kind in (b'META', b'RECS', b'AUDI') else 0, offset, len(data), zlib.crc32(data), 0)
        offset += len(data)
    if offset > MAX_BYTES:
        raise ValueError('v1 implementation limits packs to 2 GiB')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(HEADER.pack(MAGIC, 1, len(sections), offset))
            out.write(directory)
            for _, data in sections:
                out.write(data)
            out.flush()
            os.fsync(out.fileno())
        inspect_pack(Path(temporary))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return report


def inspect_pack(path):
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError('Pack exceeds resource limit')
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise ValueError('Truncated header')
    magic, version, count, length = HEADER.unpack_from(data)
    if magic != MAGIC or version != 1 or length != len(data) or not 3 <= count <= 32:
        raise ValueError('Unsupported/corrupt pack header')
    previous = HEADER.size + DIRECTORY.size * count
    if previous > len(data):
        raise ValueError('Truncated directory')
    sections = {}
    for i in range(count):
        tag, flags, start, n, crc, reserved = DIRECTORY.unpack_from(data, HEADER.size + i * DIRECTORY.size)
        if tag in sections or start != previous or n > len(data) - start or reserved or flags > 1:
            raise ValueError('Invalid section bounds/flags')
        payload = data[start:start+n]
        if zlib.crc32(payload) != crc:
            raise ValueError('Section checksum mismatch')
        if flags and tag not in (b'META', b'RECS', b'AUDI', b'LEXI', b'FEAT', b'QARE'):
            raise ValueError('Unknown required section')
        sections[tag] = payload
        previous = start + n
    if previous != len(data) or not {b'META', b'RECS', b'AUDI'} <= sections.keys():
        raise ValueError('Incomplete pack')
    return json.loads(sections.get(b'QARE', b'{}'))


def convert_legacy(root, voice, output, full_lexicon=True):
    from phonomenal.align import load_alignment_state
    from phonomenal.config import ProjectLayout
    state = load_alignment_state(ProjectLayout(Path(root)), voice)
    accepted = [r for r in state if r.alignment_status == 'accepted' and r.words and r.phonemes and r.master_audio_path]
    if not accepted:
        raise ValueError('No accepted source alignments')
    master = Path(root) / accepted[0].master_audio_path
    if not master.exists():
        master = Path(root) / 'data/packages' / (voice + '.wav')
    with wave.open(str(master), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError('Legacy master must be mono PCM16')
        rate, pcm = wav.getframerate(), wav.readframes(wav.getnframes())
    records, rejected = [], []
    for old in accepted:
        def coords(u):
            return dict(start=old.master_start_sample + u.start_sample, end=old.master_start_sample + u.end_sample, confidence=None)
        record = dict(id=old.clip_id, transcript=old.transcript_raw,
                      words=[dict(label=w.text, **coords(w)) for w in old.words],
                      phones=[dict(label=p.label, word=p.word_index, **coords(p)) for p in old.phonemes])
        try:
            validate_records([record], len(pcm)//2, rate)
        except ValueError as exc:
            rejected.append(dict(id=old.clip_id, reason=str(exc)))
        else:
            records.append(record)
    lexicon = {}
    if full_lexicon:
        import cmudict
        lexicon = {w: variants[0] for w, variants in cmudict.dict().items()}
    return write_pack(output, voice=voice, language='en-us', rate=rate, pcm=pcm, records=records,
                      lexicon=lexicon, report=dict(alignment_method='legacy-import', boundary_accuracy='unmeasured',
                      rejected=rejected, source_state_sha256=hashlib.sha256((Path(root)/'data/aligned'/f'{voice}.json').read_bytes()).hexdigest()))
