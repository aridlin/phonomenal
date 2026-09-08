"""Alignment validation and independently labelled boundary evaluation."""
from __future__ import annotations
import json
import math
from pathlib import Path


def validate_alignment(words, phones, sample_count, sample_rate):
    from phonomenal.vcpack import validate_records
    record = dict(id='validation', words=words, phones=phones)
    validate_records([record], sample_count, sample_rate)
    issues = []
    for i, phone in enumerate(phones):
        duration = (phone['end']-phone['start']) / sample_rate
        if duration < .012 or duration > .4:
            issues.append(dict(phone=i, reason='unusual_phone_duration', duration_ms=duration*1000))
    return issues


def compare_boundaries(reference, predicted, tolerance_ms=10.0):
    """Inputs contain matched clip IDs and word/phone labels in seconds.

    Reject mismatched labels instead of matching the wrong sounds by index.
    Separate recognition mistakes from boundary errors and report both tails.
    """
    result = {}
    for tier in ('words', 'phones'):
        errors, mismatches = [], []
        for clip, gold in reference.items():
            expected = gold[tier]
            actual = predicted.get(clip, {}).get(tier, [])
            if [x[2] for x in expected] != [x[2] for x in actual]:
                mismatches.append(clip)
                continue
            for a, b in zip(expected, actual):
                for i in (0, 1):
                    if not math.isfinite(a[i]) or not math.isfinite(b[i]):
                        raise ValueError('Nonfinite reference/prediction timestamp')
                    errors.append(abs(a[i]-b[i])*1000)
        errors.sort()
        def percentile(q):
            return errors[min(len(errors)-1, math.ceil(q*len(errors))-1)] if errors else None
        result[tier] = dict(boundaries=len(errors), median_ms=percentile(.5), p95_ms=percentile(.95),
                            p99_ms=percentile(.99), max_ms=max(errors) if errors else None,
                            within_tolerance=sum(e <= tolerance_ms for e in errors)/len(errors) if errors else None,
                            mismatched_clips=mismatches, tolerance_ms=tolerance_ms)
    return result
