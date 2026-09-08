Implemented foundation (September 2026): ACOU v2 acoustic and duration metadata;
TRST/EVID independent word/phone evidence; PROS contours, context, spectra,
variants, duration distributions and coverage; QREV manual decisions; optional
vowel-duration editing with an output-clock map; adaptive mixed-word spacing;
coverage-based supplemental reading. Detector agreement remains uncalibrated.
The sections below also describe research extensions, including multiple F0
candidates, syllable models and annotated-boundary calibration, which must not
be mistaken for validated accuracy claims.

# Speech quality and metadata design

Design proposal, 2026-09-08. These proposals are not all implemented. The working
ACOU prototype already contains acoustic summaries and pitch marks; boundary
uncertainty, pronunciation lattices, perceptual calibration, duration correction
and the Discord plugin still require implementation and validation.

## Selection priorities

1. Correct, complete speech sounds with trustworthy boundaries.
2. Preserve suitable recorded phrases, words and long phone sequences.
3. Match phonetic context, stress, rhythm and delivery.
4. Minimize audible joins and required signal modification.
5. Make bounded pitch/duration changes only where evidence supports them.

Target suitability and acoustic join compatibility should remain separate costs,
with global candidate search rather than independent greedy choices. This follows
[unit-selection synthesis](https://www.cs.cmu.edu/~awb/papers/IEEE2002/allthetime/node1.html).
A pitch estimate must not outweigh evidence that a candidate contains the wrong
or an incomplete sound.

## Generator data and matching reader behavior

| Data to store | Generator work | Reader use |
| --- | --- | --- |
| Boundary uncertainty and alternatives | Keep nominal sample cuts, plausible start/end ranges, alternative cuts, provenance, model disagreement and manual corrections. Keep measured confidence separate from heuristics. | Avoid uncertain tiny pieces; search a bounded set of cuts and preserve consonant releases. |
| Independent phone identity evidence | Compare forced labels with an independent acoustic phone recognizer where available; retain posterior alternatives and an explicit unknown state. | Penalize suspected mislabels instead of assuming every forced-aligned label is true. Never manufacture confidence from timestamp precision. |
| Coarticulation and prosodic context | Neighboring phones, syllable/stress, word position, phrase position, nearby pauses and speaking-rate estimate. RECS-derived facts need not be redundantly stored. | Prefer the same sound in a compatible context, especially stop releases and word-final sounds. |
| Detailed pitch evidence | Several F0 candidates and their strengths, contour continuity, reliable voiced spans, pulse marks and pulse confidence. | Avoid octave errors and skip unreliable edits; choose a suitable recording before changing pitch. |
| Duration distributions and editable regions | Robust duration distributions by stressed phone/context, sample counts, speaker/session rate, stationary vowel spans, protected attacks/releases and bounded stretch factors. | Lengthen or shorten only suitable regions; preserve consonants and map every source boundary to its actual output position. |
| Boundary spectra and transients | Short mel/cepstral windows on both sides, energy slopes, spectral flux, burst locations, noise and clipping. | Choose joins with similar spectral shape and energy; protect transients and limit gain changes. |
| Pronunciation alternatives | Canonical and observed variants, dialect/reduction markers, counts and source provenance. | Search multiple valid pronunciations while retaining exact-word/phrase priority. A final recording must never silently redefine the dictionary. |
| Intelligibility evidence | Unprompted word/chunk STT results, disagreement, manual keep/reject decisions and source-audio hashes. | Rank suspect recordings lower, allow optional slow reranking of several output candidates, explain choices in the editor. STT is a diagnostic, not proof. |
| Recording/session consistency | Session identity, sample-rate conversion history, channel/noise profile, loudness, and delivery clusters where supported. | Prefer compatible delivery within a sentence rather than mixing whispering, shouting and ordinary speech solely on F0. |
| Coverage and useful recording prompts | Counts of trusted phones, transitions, stressed syllables and common words, with weaknesses weighted by observed failures. | Show missing coverage and generate targeted additional reading prompts. More poor recordings should not count as better coverage. |

Pitch detection has separate voicing and octave ambiguities, and different
analysis methods suit different signals; see [Praat's pitch-method guidance](https://uvafon.hum.uva.nl/praat/manual/how_to_choose_a_pitch_analysis_method.html).
Per-frame maximum autocorrelation alone is insufficient evidence for an edit.

## Multiple independent detectors

Prioritize an optional multi-detector builder mode. Use distinct model families
rather than counting two configurations of the same model as independent votes.
Separate three questions: which words were spoken, which phones are supported
by the audio, and where their boundaries lie. Forced alignment is conditional
on a transcript and must not count as independent confirmation of that transcript.

1. Produce independent word hypotheses without feeding the expected words as
   a recognition hint. Align hypothesis sequences, including insertions/deletions.
2. Preserve pronunciation alternatives and normalize phone alphabets explicitly;
   retain stress distinctions and mark missing/unmappable distinctions unknown.
3. Compare independent boundary estimates only for matched labels. Keep sample
   coordinates and each detector's native frame resolution. Do not imply a
   coarse-frame estimate became accurate by converting it to integer samples.
4. Refine disputed regions using local acoustic evidence and candidate transcripts;
   retain conflicting hypotheses rather than average incompatible timestamps.
5. Store detector family/version, raw hypothesis, raw score/score meaning,
   optional calibrated confidence, accepted hypothesis, boundary uncertainty,
   disagreement flags and manual overrides. Model agreement is not ground truth.
6. Prefer agreement-supported phrases and words. Use phone fragments only when
   their identities and cuts have adequate support. Disputed regions remain
   visible in the editor and can be excluded or reprocessed automatically.

Keep a fast single-model mode and a thorough comparison mode. Cache inference
per source-audio hash, detector version and settings; rerun only invalidated
stages and analyze disputed spans more deeply. Benchmark thresholds against
hand-annotated speech from several voices; do not compare uncalibrated confidence
numbers from unrelated models as if they were the same probability.

## Format contract

Keep META/RECS/AUDI compatible. Use optional, individually versioned sections for
new evidence (candidate names: BNDY, PHPR, PROS, DURT, JOIN, QUAL). An absent field
means unknown, not perfect quality. Link records to stable recording/unit IDs and
source hashes; include analyzer name/version, units and coordinate system.
Distinguish derived measurements from manual overrides. Recompute or invalidate
stale derived data after editing. Check counts, bounds, finiteness and CRCs.
Old readers skip optional sections; known malformed schemas fail explicitly.
Keep the full raw ASCII wire specification as the physical final SPEC payload.
Do not precompute an unbounded all-pairs join graph; store per-unit features and
build/cache a shortlist of compatible candidates.

## Implementation order

1. Boundary/identity evidence and editor visibility, followed by target/phrase
   selection that cannot trade lexical correctness for a nicer pitch match.
2. Context, pronunciation alternatives and robust join features.
3. Duration distributions, protected regions, small pitch/duration edits and
   explicit output time maps. Word pauses are separate from phoneme stretching.
4. Independent output comparisons and optional slower candidate reranking.
5. Targeted reading-script improvements based on trusted coverage deficits.

Validate on all mercs and an ordinary single-reader audiobook. Keep separate
held-out prompts and source clips, compare against the preserved old engine,
report regressions, and include listening plus hand-annotated boundary samples.
A small mean word-error-rate improvement does not establish naturalness or
accurate phoneme boundaries. Do not optimize weights solely for the example
homework/approve sentences.
