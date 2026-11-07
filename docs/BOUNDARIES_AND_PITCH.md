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

## Recording-local pitch and gentle matching

Install the optional analyzer with `python -m pip install '.[prosody]'`, or rerun
the builder setup (the builder extra includes it). Analyze an existing pack:

```sh
python scripts/builder.py refine-pitch voice.vcpack --output voice-pitch.vcpack
./cpp/build/phonomenal_splicer_cli --bank voice-pitch.vcpack \
  --text "Please bring me a glass of water." --match-pitch --output speech.wav
```

The player's **Analyze pack for better selection and pitch** action also runs
this analysis after ordinary enrichment or the selected detector comparison.
Its **Match pitch between mixed recordings** checkbox is off by default.

The analyzer applies a Gaussian low-pass transfer function to an analysis copy,
then uses Praat's autocorrelation candidate-path search. Pulse positions are
found by cross-correlation in the original waveform. Each recording is analyzed
separately. The source audio, words, phone labels and sample positions are kept.
See the [filtered-autocorrelation algorithm](https://www.fon.hum.uva.nl/praat/manual/pitch_analysis_by_filtered_autocorrelation.html)
and [waveform pulse alignment](https://www.fon.hum.uva.nl/praat/manual/Sound___Pitch__To_PointProcess__cc_.html).
Parselmouth 0.4.7 embeds Praat 6.1.38, so filtering is applied explicitly before
its raw-AC command; this is not a claim to execute a newer Praat command.

The optional `PITC` section holds rendering-only pitch/pulse evidence. It does
not replace FEAT/ACOU/PROS or change source-selection costs. Missing/unknown data
falls back to the original acoustic metadata. Known malformed measurements or
pulse positions fail validation. Saving source edits in the pack editor drops
PITC rather than carrying forward stale evidence; rerun analysis after edits.

Matching uses stable neighbouring recorded runs as local pitch references,
retains each run's original contour, and shifts reliable vowel interiors by at
most 1.5 semitones. It skips standalone runs, long intact phrases, sentence pauses,
large register differences, clipped/unstable vowels and insufficient pulse data.
It does not snap speech to musical notes or modify consonants/phone boundaries.
An explicit `--pitch-band` takes precedence. Duration normalization does not
reuse the old pulse clock in any vowel that was actually pitch-shifted.

This is optional signal processing, not correction of incorrect transcripts or
phonetic alignments. Source selection and consonant preservation still matter
more than matching F0. Listening remains necessary.

## Short-fragment protection and experimental timing-preserving joins

The previous boundary planner's crossfade is bounded by one quarter of **both** adjacent
rendered fragments. Previously its left bound used the entire output buffer,
which could erase a complete short preceding consonant. This is a waveform
retention guarantee, not evidence that the source label or cut is correct.

`--preserve-phone-timing` enables an experimental alternative. It retains the
planned duration of both fragments, blends up to 2 ms of available original
neighbouring context on each side, and never crosses the recording bounds.
Without context it uses at most 0.5 ms of edge taper instead of removing
samples. Intact contiguous source audio stays unchanged. The boundary report
records `duration_preserving_joins`, `contextual_joins`, and
`overlap_samples_removed`; mappings retain their actual output sample clock.

`--boundary-phone-joins` (alias `--legacy-overlap`) selects that previous bounded
overlap method and its boundary planner. Add `--preserve-phone-timing` after it
to test timing preservation on the previous planner. Timing preservation alone
gave mixed recognition results, including a Heavy book regression. The current
default couples it with the center-join planner described below.

## Joins inside matching phones

`--center-phone-joins` adds source transitions between the middles of matching
phones to the planning graph. The beginning and ending of a word can still use
whole phones, and intact recorded words/phrases remain available. This keeps a
recorded transition such as the consonant into a vowel together, then joins to
another recording inside that same vowel. It does not generate new speech or
correct a wrong source label.

This follows the [Festival diphone synthesis principle](https://www.cs.cmu.edu/~awb/11752/notes/festtut_7.html).
The [FestVox diphone collection paper](https://www.cs.cmu.edu/~awb/papers/ICSLP2000_diphone/kaldiph.html)
also explains why a simple midpoint is unsuitable for stop consonants.

Cuts stay in the middle third of each phone. When reliable pitch pulses are
available, the nearest pulse to the midpoint is used. Stops, affricates and short
aspiration do not expose center cuts: combining arbitrary closure/release halves
could erase or duplicate a burst. Source transitions cannot span a gap over
20 ms, and target punctuation, stress penalties, independent detector disputes
and manual rejections are retained. The option implies duration-preserving joins.
Full and partial phones receive their proportional duration, stress and source
quality costs; an unsplit stop keeps its full penalty. A pitch-band preference
continues to participate in source selection.
Contiguous pieces from one recording merge back into their original waveform.

Plans identify partial-phone endpoints with `starts_at_phone_center` and
`ends_at_phone_center`. Audits add `phone-center` rows carrying the source phone's
evidence and actual output clock. Optional pitch/duration processing still edits
only complete reliable vowels; partial vowels are skipped.

The default now uses matching-phone joins with source runs up to 12 phones.
`--boundary-phone-joins` restores the previous planner and bounded overlap.
The explicit `--center-phone-joins` option retains the earlier two-phone limit.
Before promotion, an unchanged-default check compared 96 plans and WAVs byte for
byte. Controlled synthetic tests verify a
shared-vowel join, intact words, stop-burst protection, recording gaps, punctuation,
manual rejection and output timing. These checks establish mechanics; multi-voice
recognition comparisons and actual listening are separate quality checks.

`--center-run-phones 12` explicitly selects the current default, retaining longer naturally
recorded sequences (the limit accepts 2 through 12 phones). Only the first and
last phone can be partial; every interior phone remains intact. These edges reuse
the existing source-run index and reject interior gaps over 20 ms, overlaps,
collapsed intervals and manually rejected phones. A sentence pause blocks every
longer edge crossing it. Costs retain full interior-phone evidence and duration
penalties, with proportional endpoint costs. Intact recorded words remain anchors.

The existing `--center-phone-joins` option retains its two-phone limit. Plans
identify selected longer edges with `center_run_phone_count`; contiguous pieces
still merge without crossfading their original audio. A compatibility comparison
on the installed packs reproduced 198 default and two-phone-mode plans and WAVs
byte for byte. Synthetic tests cover original interior samples, output duration,
silence gaps, rejected interior phones, punctuation and invalid run limits.
