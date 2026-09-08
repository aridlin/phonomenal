"""Optional ACOU v2: measured phone quality and source-clock pitch marks.

All measurements are acoustic heuristics, never phonetic alignment confidence.
No ASR model is needed to enrich an existing pack; audio/labels stay unchanged.
"""
from collections import defaultdict
import struct

import numpy as np

VOWELS = set('AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW'.split())


def pitch_marks(samples, rate, pitch):
    """Track positive waveform peaks near the predicted period; fail closed."""
    period = rate / pitch
    if len(samples) < period * 5:
        return []
    # Smooth sub-millisecond high-frequency detail, leaving the pulse clock.
    width = max(1, round(rate * .0005))
    smooth = np.convolve(samples, np.ones(width) / width, mode='same')
    cursor = int(np.argmax(smooth[:min(len(samples), round(period * 2))]))
    marks = [cursor]
    while cursor + period * 1.25 < len(samples):
        lo = max(cursor + 1, round(cursor + period * .8))
        hi = min(len(samples), round(cursor + period * 1.2) + 1)
        cursor = lo + int(np.argmax(smooth[lo:hi]))
        marks.append(cursor)
    if len(marks) < 5:
        return []
    periods = np.diff(marks)
    if np.std(periods) / np.mean(periods) > .10:
        return []
    return marks


def extract_acoustics(pcm, rate, records, feature_bytes):
    from phonomenal.vcpack import string
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
    hop, dims, count = struct.unpack_from('<IIQ', feature_bytes)
    frames = np.frombuffer(feature_bytes, dtype='<f4', offset=16).reshape(count, dims)
    durations = defaultdict(list)
    for record in records:
        for p in record['phones']:
            durations[p['label']].append(np.log((p['end'] - p['start']) / rate))
    norms = {}
    for label, values in durations.items():
        values = np.asarray(values)
        median = float(np.median(values))
        # A minimum spread avoids over-penalizing normal speaking-rate changes.
        norms[label] = (median, max(.35, float(np.median(np.abs(values - median))) * 1.4826), len(values))
    out = bytearray(struct.pack('<II', 2, len(records)))
    for record in records:
        out += string(record['id']) + struct.pack('<I', len(record['phones']))
        for p in record['phones']:
            start, end = p['start'], p['end']
            audio = samples[start:end]
            # Use frame centres inside the phone, inset to reduce boundary bleed.
            inset = min(round(rate * .010), (end - start) // 4)
            first = (start + inset + hop - 1) // hop
            last = (end - inset - 1) // hop + 1
            f = frames[first:last]
            voiced = f[(f[:, 0] > 0) & (f[:, 1] >= .80) & (f[:, 2] > .003)]
            pitch = float(np.median(voiced[:, 0])) if len(voiced) else 0.
            spread = float(np.percentile(12 * np.log2(voiced[:, 0] / pitch), 90) -
                           np.percentile(12 * np.log2(voiced[:, 0] / pitch), 10)) if pitch else 0.
            voiced_fraction = len(voiced) / max(1, len(f))
            rms = float(np.sqrt(np.mean(audio * audio)))
            clipping = float(np.mean(np.abs(audio) >= .985))
            silence = float(np.mean(f[:, 2] < .003)) if len(f) else float(rms < .003)
            edge = max(1, min(len(audio), round(rate * .008)))
            onset = float(np.sqrt(np.mean(audio[:edge] ** 2)))
            offset = float(np.sqrt(np.mean(audio[-edge:] ** 2)))
            median, scale, n = norms[p['label']]
            duration_z = float((np.log(len(audio) / rate) - median) / scale) if n >= 8 else 0.
            marks = []
            if (p['label'].rstrip('012') in VOWELS and pitch and voiced_fraction >= .8
                    and spread <= 2.5 and clipping < .01 and len(audio) >= rate * .050):
                marks = pitch_marks(audio, rate, pitch)
            out += struct.pack('<9fI', pitch, spread, voiced_fraction, rms, clipping,
                               silence, onset, offset, duration_z, len(marks))
            out += struct.pack('<ffI', float(np.exp(median)*1000), scale, n)
            for mark in marks:
                out += struct.pack('<Q', start + mark)
    return bytes(out)


def enrich_pack(path, output):
    """Refresh only derived sections; preserve every original audio/label byte."""
    from pathlib import Path
    import json
    from phonomenal.pack_editor import read_pack
    from phonomenal.vcpack import HEADER, DIRECTORY, _write_sections, extract_features
    path, output = Path(path), Path(output)
    if output.exists():
        raise ValueError('Choose a new output filename; original packs are preserved')
    meta, records, _, _, pcm, report = read_pack(path)
    raw = path.read_bytes()
    existing = {}
    for i in range(HEADER.unpack_from(raw)[2]):
        tag, flags, start, length, _, _ = DIRECTORY.unpack_from(raw, HEADER.size + DIRECTORY.size * i)
        existing[tag] = raw[start:start + length]
    # Reuse only the current estimator: older FEAT had octave-selection errors.
    features = existing.get(b'FEAT') if report.get('acoustic_analysis', {}).get('version', 0) >= 1 else None
    if features is None:
        features = extract_features(pcm, meta['rate'])
    acoustic = extract_acoustics(pcm, meta['rate'], records, features)
    sections = []
    for i in range(HEADER.unpack_from(raw)[2]):
        tag, flags, start, length, _, _ = DIRECTORY.unpack_from(raw, HEADER.size + DIRECTORY.size * i)
        if tag not in {b'FEAT', b'ACOU', b'QARE', b'SPEC'}:
            sections.append((tag, flags, raw[start:start + length]))
    report['acoustic_analysis'] = dict(version=2, phones=sum(len(r['phones']) for r in records),
                                      pitch_marks=True, linguistic_accuracy_verified=False)
    sections += [(b'FEAT', 0, features), (b'ACOU', 0, acoustic),
                 (b'QARE', 0, json.dumps(report, ensure_ascii=False).encode())]
    _write_sections(output, sections)
    return report
