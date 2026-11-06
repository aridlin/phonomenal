"""Recording-local pitch paths and waveform-correlated pulse positions.

Only derived acoustic sections change. This is pitch/pulse alignment, not a
phonetic forced aligner or a claim that source word labels are correct.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import numpy as np


def analyse_recording(samples, rate, *, step=.005, floor=50., top=800.):
    import parselmouth
    from parselmouth.praat import call

    samples = np.asarray(samples, dtype=np.float64)
    if len(samples) < rate * .14 or np.max(np.abs(samples), initial=0.) < .003:
        return np.empty(0), np.empty(0), np.empty(0), np.empty(0, dtype=np.int64)
    # Parselmouth 0.4 uses Praat 6.1, before its named filtered-AC command.
    # Apply the documented Gaussian transfer function, then use Praat's AC
    # candidate path search with the filtered-AC settings. No audio is exported
    # from the filtered analysis signal.
    # https://www.fon.hum.uva.nl/praat/manual/pitch_analysis_by_filtered_autocorrelation.html
    pad = max(1, round(rate * .1))
    padded = np.pad(samples, (pad, pad), mode='reflect')
    frequencies = np.fft.rfftfreq(len(padded), 1. / rate)
    filtered = np.fft.irfft(np.fft.rfft(padded) * .03 ** ((frequencies / top) ** 2), n=len(padded))[pad:-pad]
    sound = parselmouth.Sound(samples, sampling_frequency=rate)
    analysis = parselmouth.Sound(filtered, sampling_frequency=rate)
    pitch = analysis.to_pitch_ac(time_step=step, pitch_floor=floor,
        pitch_ceiling=top, very_accurate=True, silence_threshold=.09,
        voicing_threshold=.50, octave_cost=.055, octave_jump_cost=.35,
        voiced_unvoiced_cost=.14)
    # Pulses are correlated in the ORIGINAL waveform, using the selected pitch
    # path. Selecting peaks independently per vowel loses the pulse clock.
    pulses = call([sound, pitch], 'To PointProcess (cc)')
    times = call(pulses, 'To Matrix').values[0] if call(pulses, 'Get number of points') else np.empty(0)
    marks = np.unique(np.rint(times * rate - .5).astype(np.int64))
    marks = marks[(marks >= 0) & (marks < len(samples))]
    selected = pitch.selected_array
    return pitch.xs(), selected['frequency'], selected['strength'], marks


def refine_features(pcm, rate, records, feature_bytes, progress=None):
    hop, dims, count = struct.unpack_from('<IIQ', feature_bytes)
    frames = np.frombuffer(feature_bytes, dtype='<f4', offset=16).reshape(count, dims).copy()
    audio = np.frombuffer(pcm, dtype='<i2').astype(np.float64) / 32768.
    # Missing pitch evidence is unknown/unvoiced, never a silently reused old
    # estimate. Keep RMS and spectra in their existing coordinates.
    frames[:, :2] = 0.
    pulses = {}
    for i, record in enumerate(records):
        start, end = record['words'][0]['start'], record['words'][-1]['end']
        times, pitch, strength, marks = analyse_recording(audio[start:end], rate, step=hop/rate)
        pulses[record['id']] = marks + start
        if len(times):
            first = max(0, int(np.ceil((start + times[0] * rate) / hop)))
            last = min(count, int(np.floor((start + times[-1] * rate) / hop)) + 1)
            centres = (np.arange(first, last) * hop - start) / rate
            indices = np.clip(np.rint((centres - times[0]) / (hop/rate)).astype(int), 0, len(times)-1)
            frames[first:last, 0] = pitch[indices]
            frames[first:last, 1] = np.where(pitch[indices] > 0, strength[indices], 0.)
        if progress and (i % 25 == 0 or i + 1 == len(records)):
            progress(f'Pitch/pulse analysis: {i+1}/{len(records)} recordings')
    return struct.pack('<IIQ', hop, dims, count) + frames.astype('<f4').tobytes(), pulses


def refine_pack(source, output, progress=None):
    try:
        import parselmouth
    except ImportError as exc:
        raise RuntimeError('Install pitch analysis with: python -m pip install ".[prosody]"') from exc
    from phonomenal.pack_editor import read_pack
    from phonomenal.vcpack import HEADER, DIRECTORY, _write_sections, extract_features, inspect_pack
    from phonomenal.acoustics import extract_acoustics

    source, output = Path(source), Path(output)
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError('Choose a new output filename; the original pack is preserved')
    meta, records, _, _, pcm, report = read_pack(source)
    raw = source.read_bytes()
    sections = []
    for i in range(HEADER.unpack_from(raw)[2]):
        tag, flags, start, length, _, _ = DIRECTORY.unpack_from(raw, HEADER.size+i*DIRECTORY.size)
        sections.append((tag, flags, raw[start:start+length]))
    features = next((data for tag, _, data in sections if tag == b'FEAT'), None)
    if features is None:
        features = extract_features(pcm, meta['rate'])
    features, pulses = refine_features(pcm, meta['rate'], records, features, progress)
    acoustic = extract_acoustics(pcm, meta['rate'], records, features, pulses=pulses)
    # Pitch analysis must not silently recalibrate the planner's identity and
    # join costs. Keep FEAT/ACOU/PROS byte-for-byte and store editing evidence in
    # its own optional section. Old readers safely ignore it.
    editing = pitch_section(acoustic)
    report['pitch_analysis'] = dict(version=1, phones=sum(len(r['phones']) for r in records),
        pitch_method='Gaussian-filtered AC with Praat candidate path search',
        pulse_method='original-waveform cross-correlation',
        parselmouth_version=parselmouth.__version__, praat_version=parselmouth.PRAAT_VERSION,
        floor_hz=50, top_hz=800, hop_samples=struct.unpack_from('<I', features)[0],
        source_pack_sha256=hashlib.sha256(raw).hexdigest(),
        linguistic_accuracy_verified=False)
    sections = [(t, f, d) for t, f, d in sections if t not in {b'PITC', b'QARE', b'SPEC'}]
    sections += [(b'PITC', 0, bytes(editing)),
        (b'QARE', 0, json.dumps(report, ensure_ascii=False).encode())]
    _write_sections(output, sections)
    return inspect_pack(output)


def pitch_section(acoustic):
    """Encode only editing evidence from an ACOU v2 analysis result."""
    from phonomenal.pack_editor import Reader
    from phonomenal.vcpack import string
    reader = Reader(acoustic)
    version, count = reader.unpack('<II')
    if version != 2:
        raise ValueError('Expected ACOU v2 analysis')
    editing = bytearray(struct.pack('<II', 1, count))
    for _ in range(count):
        rid, phone_count = reader.string(), reader.count()
        editing += string(rid) + struct.pack('<I', phone_count)
        for _ in range(phone_count):
            values = reader.unpack('<9fI')
            reader.unpack('<ffI')
            marks = reader.unpack('<' + 'Q'*values[9])
            editing += struct.pack('<3fI', *values[:3], len(marks))
            editing += struct.pack('<' + 'Q'*len(marks), *marks)
    reader.done()
    return bytes(editing)
