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

Pitch correction is off by default. When enabled it estimates a voiced median
for each selected chunk and shifts it toward the requested lower/upper band.
Resampling followed by waveform-similarity overlap-add preserves the chunk's
sample count. Both raising and lowering are supported, limited to one octave per
chunk; extreme input pitches may therefore remain outside the requested band.
Unvoiced chunks are retained. It does not preserve formants, and cannot fix a
wrong word or missing sound. Pitch estimates can be wrong on noisy or expressive
speech. The report records the estimated input/target pitch and applied factor.

Output boundary coordinates after pitch shifting are nominal mappings from the
source; waveform alignment inside WSOLA can move fine detail. Neither acoustic
flags nor a matching STT transcript prove that each linguistic boundary is
correct. Independent human annotations and listening remain necessary to measure
actual boundary accuracy and naturalness. STT is enabled automatically in the
frontend and can be disabled independently from these boundary checks.
