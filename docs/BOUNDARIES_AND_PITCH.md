# Automatic diagnostics and optional pitch correction

The generator audits both ends of every accepted word and phoneme. It checks
sample geometry, ordering, phone/word containment, interval duration, silence,
clipping, waveform jumps, and ASR/MFA timing disagreement when their recognized
word sequences match. `QARE.boundary_audit` contains each check, including the
recording's source offset. The ASR pass uses bounded windows for short files,
retains each file's own sample clock, and flags words crossing recording edges.
Recognition never receives the expected test message as a hint.

Before pronunciation generation, fresh and cached transcripts are screened for
runaway tokens (over 64 characters, repeated non-word syllables, or an implausible
word count for the audio duration). Rejected clips remain listed in the report;
the generator does not invent a replacement transcript. This prevents ASR-rendered
laughter from creating enormous pronunciation lattices. The ASR model is released
before MFA starts, MFA uses two jobs, and the isolated aligner limits BLAS threads.
Alignment progress is streamed into the builder log while it runs.

The C++ player separately audits every selected source word/phone endpoint and
every output splice on every render. Out-of-range intervals fail generation.
Suspicious waveform jumps and phone durations are reported for review. Exact
recorded phrases now receive duration checks too; a whole-word match no longer
bypasses strict rejection of an implausibly short vowel. These are common rules
for all speakers, including TF2 mercs and ordinary audiobook narration.

```sh
bin/phonomenal_splicer_cli --bank voice.vcpack --text "Your message" \
  --output message.wav --audit boundaries.json --pitch-band 100:180
```

Pitch correction is off by default. It now prefers recordings near the requested
band and edits only reliable vowel interiors, with a maximum shift of three
semitones in either direction. Consonants, at least 8 ms at each vowel edge,
phone durations and output sample counts are preserved. A band is a preference;
large requested changes deliberately remain outside it.

The former whole-chunk resampling/WSOLA implementation could move consonants and
change vowel tone. It has been replaced by pitch-synchronous overlap-add using
source waveform grains without resampling (see [Praat's method description](https://www.fon.hum.uva.nl/praat/manual/overlap-add.html)).
This reduces those specific risks; listening and independent STT comparisons
are still required. Unstable, clipped, short or unvoiced intervals are skipped.
The audit records each adjusted vowel's source sample interval and the count of
uncertain vowels skipped. Old packs without reliable pitch marks play normally
and receive no waveform pitch edits.

New packs contain the optional `ACOU` section: per-phone pitch and spread,
voiced fraction, RMS, clipping, silence, edge energy, robust speaker-relative
duration scores, and sample-accurate pitch marks. Selection uses acoustic quality,
neighboring phone context and the requested pitch band while retaining the
existing preference for intact long recordings. Acoustic scores do not certify
that the labels or boundaries are correct. The manual editor regenerates them.

To analyze an existing pack without rerunning STT/alignment or changing its audio,
labels, lexicon or unknown extensions:

```sh
.venv-vcpack/bin/python scripts/builder.py enrich-pack voice.vcpack --output voice-enriched.vcpack
```

`ACOU` is optional, so old readers can open enriched packs. The complete updated
ASCII specification remains the last payload in every newly written pack.
Neither acoustic flags nor a matching STT transcript prove naturalness or the
correctness of each linguistic boundary. Independent annotations and listening
remain necessary. STT remains enabled automatically in the frontend.

## Word spacing and duration

Mixed words receive a 20–70 ms pause, longer after short words. A manual minimum
can increase it. Intact source phrases keep their native spacing; phones within
the same word receive no artificial word gap. Punctuation retains its own pause.
Use `--no-auto-word-gaps` to disable adaptive pauses.

`--normalize-duration` (also a frontend checkbox) adjusts only unusually short or
long stable vowel interiors with at least eight same-phone duration examples.
The interior factor is limited to 0.75–1.4; consonants and 12 ms at each vowel edge
remain intact. Every rendered boundary is mapped through the duration changes
before the output audit runs. This is optional: naturally expressive vowels may
be duration outliers too. A vowel receiving a pitch change skips duration editing
to avoid reusing stale pulse marks. Older ACOU v1 packs remain readable.

See [independent detector analysis](DETECTORS.md) for label disagreement, source
uncertainty, manual phone review and the additional portable metadata sections.

Rendered phone-boundary reports now include `source_uncertainty_samples`,
`independent_disputes`, and `manual_review`. Disputed or widely separated detector
estimates are flagged even when the waveform join itself is smooth. These values
refer to source evidence; output positions still follow the actual time map.
