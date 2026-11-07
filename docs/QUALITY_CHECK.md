# Speech regression check

The current default is the verified long-transition center planner. The previous
bounded renderer remains available with `--boundary-phone-joins` or
`--legacy-overlap`. The historical experiments below retain their original
labels; see the current-default evaluation at the end for the promotion decision
and known limitations. Recognition diagnostics remain separate from listening.

The diagnostic sentence is **I hate getting homework**. These are unprompted
`small.en` STT results on the actual rendered WAV, without the expected text
supplied as a prompt or hotword. They are diagnostics, not listening scores.

| Heavy source pack / selection | STT heard | Raw word error rate |
|---|---|---|
| Original legacy selection | I HATE DEALING YER | 50% |
| Duration/stress selection on legacy data | I hate taking home bank | 75% |
| Fresh 97-clip alignment with timing selection | I hate getting home, but | 50% |
| Small curated source set with word-boundary selection | I hate getting home work | 50% |

The last result was reproduced through the deployed FT web player and STT
button. Its recognized letters match the requested sentence after removing
spaces, but splitting `homework` into `home work` still counts as two word
edits under standard WER. The UI reports this distinction without replacing
the raw score with a misleading zero.

The diagnosis found incorrectly transcribed words, very short vowel intervals,
fragments spanning target word boundaries, and a final stop taken from inside
a source word. The planner now considers stress, implausible durations and
source word boundaries. Whole recorded words and long phrases remain preferred.
Strict mode rejects missing or suspect sound coverage; it cannot correct a
wrong source transcript or independently establish boundary accuracy.

`heavy-core` is a small regression corpus with limited coverage. Its success
on this sentence is not evidence of intelligible arbitrary prompts. The nine
legacy TF2 packs retain their original, unmeasured alignment quality. A broader
Heavy corpus rebuild is a separate long-running job; it must be checked before
being treated as a quality upgrade. No human-labelled boundary benchmark or
blind listening study has been completed.

Game recordings and these private local voice packs are not distributed in the
public source or releases. `examples/demo.vcpack` is an original synthetic tone
fixture for format and planner testing, not a speech-quality demonstration.

## Cross-voice check, 2026-09-08

Every voice uses the same planner rules. Exact words/phrases now receive the same phone-duration checks as phoneme fallback candidates; casual contractions are normalized. No Medic/Soldier-specific source curation is applied.

All four prompts are in `examples/regression-prompts.json`. The table compares the previous engine and the new generic engine **on the same legacy pack audio/alignment**, using unprompted `small.en` recognition. These are raw WER values; lower is better, and insertions can make WER exceed 100%.

| Voice | Reading passage: previous → current | TTS passage: previous → current | Short sentence: previous → current | You are straight and I approve: current |
|---|---|---|---|---|
| medic | 57.1% → 69.4% | 88.2% → 76.5% | 25.0% → 25.0% | 66.7% |
| soldier | 42.9% → 16.3% | 88.2% → 52.9% | 0.0% → 0.0% | 0.0% |
| librivox-phil | not tested → 20.4% | not tested → 29.4% | not tested → 75.0% | 33.3% |
| heavy | 95.9% → 106.1% | 64.7% → 58.8% | 75.0% → 75.0% | 66.7% |
| scout | 75.5% → 46.9% | 64.7% → 41.2% | 75.0% → 75.0% | 16.7% |
| demoman | 49.0% → 51.0% | 82.4% → 64.7% | 75.0% → 75.0% | 33.3% |
| engineer | 67.3% → 71.4% | 29.4% → 41.2% | 100.0% → 100.0% | 66.7% |
| sniper | 106.1% → 63.3% | 52.9% → 41.2% | 100.0% → 125.0% | 0.0% |
| spy | 16.3% → 16.3% | 41.2% → 35.3% | 50.0% → 50.0% | 0.0% |
| pyro | coverage failure → coverage failure | coverage failure → coverage failure | coverage failure → coverage failure | coverage failure |

The reported Soldier phrase transcribes exactly after rejecting a collapsed vowel inside the previous screaming “you are” phrase. Its exact match is not evidence that arbitrary Soldier text is solved. Several other voices regress on particular prompts; duration heuristics alone cannot repair incorrect source transcripts. The completed Medic and full Heavy rebuilds are evaluated separately below.

The single-narrator comparison uses only the **16:47 first chapter, The Telltale Heart**, from *Six Creepy Stories* by Edgar Allan Poe, read by Phil Chenevert. [LibriVox catalog and reader credits](https://librivox.org/six-creepy-tales-by-edgar-allan-poe/). LibriVox identifies the recordings as public domain in the USA. The resulting pack contains 188 accepted clips, 2,153 words and 7,085 phones; it was built with unprompted small.en ASR and MFA fine-tuning. It was tested on the same unrelated text, with no special narrator selection rules. The complete two-hour book was not processed.

Machine-readable results with recognized text are in [cross-voice-results.json](cross-voice-results.json). Audio and voice assets remain in the local/deployed workspace. No independent human-labelled phone-boundary benchmark has been performed.

## Full rebuilt packs

Both builds use the same rules. Medic uses medium.en source transcription and
Heavy uses small.en, followed by MFA fine-tuning and automatic checks on every
accepted boundary. Runaway laughter/scream tokens are rejected before G2P.
These are full source-folder rebuilds, without selecting clips for the test text.

| Rebuilt pack | Accepted clips | Words / phones | Reading WER | TTS WER | Short WER | Approve WER |
|---|---:|---:|---:|---:|---:|---:|
| Heavy | 522 | 2,227 / 7,291 | 71.4% | 29.4% | 0% | 33.3% |
| Medic | 371 | 1,648 / 5,621 | 38.8% | 35.3% | 75% | 66.7% |

The full Heavy pack now transcribes **I HATE GETTING HOMEWORK!** exactly and
improves both long prompts relative to its legacy pack. Medic improves the long
reading prompt from 69.4% to 38.8% and the TTS prompt from 76.5% to 35.3% under
the same generic engine, but its short sentence regresses from 25% to 75%.
The legacy Medic pack is retained as `medic-legacy.vcpack`. The rebuilt pack is
available as `medic.vcpack`, including the requested project-root copy.

The extended reading passage remains poor for Heavy, and neither rebuild makes
arbitrary text consistently intelligible. Both successful rebuilds ran in
separate memory-limited services after an ASR laughter token caused G2P memory
exhaustion. Heavy finished at 2.8 GiB peak and Medic at 3 GiB peak; the corrected
builds reused transcription caches and did not require re-recording sources.

## Intelligibility update, 2026-11-06

The native planner now discounts internal timing/acoustic penalties when it can
keep an intact recorded word, while preserving strict duration rejection and
manual rejection. For phoneme fallback, a source word rejected by two word
recognizers with no supporting word recognizer gets a substantially larger
identity penalty. Detector evidence remains uncalibrated, and manual acceptance
still takes precedence. The existing independently analyzed packs are now used
by the local installation, with source audio and aligned labels preserved.

`repair-lexicon INPUT --output NEW.vcpack` explicitly repairs legacy English
target pronunciations that match no CMUdict variant. It preserves valid variants,
unknown names, audio, forced source labels, acoustic/evidence sections and opaque
extensions, and records every change plus its input hash. It never overwrites
its input. This repaired 17 Medic and 16 Heavy target entries; the other six
normal-speech merc packs needed no lexical changes.

The same six everyday sentences were rendered before and after, without pitch
or duration modification. The before engine is frozen from the starting source;
the after engine uses identical rules for every voice. Whisper small.en received
only each actual output WAV, with no expected-text prompt or hotwords.

| Voice | Before word errors / 45 | After word errors / 45 |
| --- | ---: | ---: |
| Medic | 13 | 8 |
| Heavy | 7 | 0 |
| Soldier | 5 | 0 |
| Scout | 16 | 5 |
| Demoman | 22 | 3 |
| Engineer | 6 | 4 |
| Sniper | 21 | 8 |
| Spy | 3 | 1 |
| Total | 93 / 360 (25.8%) | 29 / 360 (8.1%) |

A second pass over the same saved Medic/Heavy/Soldier WAVs using the larger
Whisper medium.en model gave 15/135 (11.1%) before and 12/135 (8.9%) after.
These are two sizes of the same recognition family, not independent human
listening studies. The two models disagree about several sentences. The smaller
model's much larger improvement must not be interpreted as a measured human
intelligibility improvement of the same size.

Regressions remain. Medic's "Where are we going after this game?" worsened in
both models. Heavy's "Give me a minute. I am almost ready." improved in small.en
but worsened in medium.en. Medic's old homework regression still fails badly
when disputed "home" fragments are avoided. Pyro has no normal-speech coverage
and was left unchanged. Arbitrary speech is not solved.

Validation: 78 Python/native integration tests passed, including three new
regressions for intact words, conflicting source evidence and lossless lexical
repair; the standalone VCTTS native integration test passed. Player and VCTTS
binaries were rebuilt. Browser interaction was unavailable because local browser
use is disabled in Work settings; no browser playback or human listening result
is claimed. Raw WAVs, source hashes, plans and unprompted transcripts are retained
in this task workspace's `work/phonomenal/evidence` directory.

## Pitch/pulse milestone, 2026-11-06

A new recording-local filtered-AC pitch path and original-waveform correlated
pulse analysis supplies a separate optional PITC section. In eight local packs,
6,028 vowel intervals passed the editing guards, compared with 2,038 under the
old per-vowel peak picker. This is coverage of the editing checks, not a measured
count of correct glottal pulses or phonetic boundaries.

The first experiment replaced the planner's FEAT/ACOU estimates as well. It
regressed the 48-sentence small.en comparison from 29 to 51 word errors and was
rejected. The final design preserves all source-selection data byte-for-byte.
With matching disabled, all 80 plans and WAVs (eight voices, ten prompts) matched
the previous installed engine byte-for-byte.

Optional gentle pitch matching made 28/360 word errors on the six-sentence,
eight-voice comparison, versus 29/360 without it. It helped some sentences and
regressed others. The larger medium.en model remained at 12/135 errors on the
Medic/Heavy/Soldier subset. Matching therefore remains off by default; these
results do not establish a human intelligibility or naturalness improvement.

Synthetic signal checks cover fundamental/pulse tracking under strong harmonics,
silence/unvoiced rejection, bounded pitch movement, unchanged consonants and
sample count, source-selection invariance, malformed optional data, source-edit
invalidation, and the complete enrich/refine CLI path. Browser listening remains
unverified. The next target is preserving short sounds at source joins.

## Book input and pause alignment, 2026-11-06

The requested three-paragraph reading demo uses a public-domain passage from
Chapter VI of Lewis Carroll's *Alice's Adventures in Wonderland*, preserved in
`examples/book-demo`. Voice audio stays local. The 207-reference-word baseline
was recognized at 19.8% WER for Heavy and 9.2% for Soldier by medium.en. These
are diagnostics on a new longer passage, not a human listening score.

Preparing the demo exposed two input bugs: typographic apostrophes split
contractions, and a separate pause scanner lost synchronization after digits or
ampersands expanded into spoken words. A single tokenizer now emits words and
their preceding pauses together. It canonicalizes English book punctuation,
keeps curly-apostrophe contractions intact, handles typographic dashes/ellipses,
and gives blank-line paragraph breaks one 300 ms pause. Ordinary single line
breaks remain whitespace. Tests cover the exact contraction/pause behavior and
LF/CRLF paragraph equivalence. This fixes text/pause alignment, not source
phoneme boundaries; duration-preserving source joins remain the next target.

The Windows follow-up fixes the CLI's argument encoding as well: it now reads
wide command-line arguments, converts speech to UTF-8, and constructs file paths
from UTF-8 explicitly. The Windows ANSI conversion had damaged smart punctuation
before tokenization. A regression also covers non-ASCII bank, WAV and audit paths.
The Linux suite passes 93 tests; a MinGW Windows CLI cross-build passes. Native
Windows runtime validation is tracked by the subsequent CI run.

## Join-duration comparison, 2026-11-06

A 2 ms consonant fixture reproduced complete loss under the previous renderer:
its overlap bound used the full accumulated output, not the preceding fragment.
The default now caps overlap at one quarter of both adjacent rendered fragments.
Tests verify retention of the consonant's core, full sample-clock preservation
in the experimental mode, recording-bound context, and unchanged contiguous audio.

The experimental `--preserve-phone-timing` mode keeps the complete planned
fragment durations and blends short real source contexts. It is not enabled by
default. Eight voices were compared on 12 prompts, including six new everyday
sentences. The same frozen packs and planner were used for all three renders;
only join processing changed. No requested words were supplied as recognition
prompts or hotwords.

| Diagnostic | Previous overlap | Bounded overlap (default) | Preserve timing (experimental) |
| --- | ---: | ---: | ---: |
| small.en, 96 cases / 752 reference words | 91 errors (12.1%) | 89 (11.8%) | 92 (12.2%) |
| medium.en, 48 new-sentence cases / 392 words | 49 (12.5%) | 49 (12.5%) | 40 (10.2%) |
| medium.en, Heavy/Soldier book / 414 words | 65 (15.7%) | 65 (15.7%) | 71 (17.1%) |

The two recognizer sizes disagree, and preserving durations is not by itself
proof of clearer arbitrary speech. The mixed results are why its mode remains
experimental. Current defaults take the definite short-consonant retention fix
while source-transcript/alignment work continues. The reading demos, plans,
audits and unprompted recognition records remain in the task workspace.

## Experimental matching-phone joins, 2026-11-07

`--center-phone-joins` preserves native transitions between phones, joining
recordings inside a matching vowel, sonorant or sustained fricative. Stops and
affricates retain their complete closure/release sequence. Exact recorded words
and phrases remain available, rejected phones remain excluded, and partial
phones retain proportional source-quality, stress and duration costs. The option
uses duration-preserving rendering; it is off by default.

Eight unchanged packs were compared on 12 ordinary sentences. The same three
Alice paragraphs were also rendered in Medic, Heavy and Soldier. The medium
comparison used CUDA int8_float16 on both versions; the small comparison used
CPU int8. Neither recognizer received expected text as a prompt.

| Diagnostic | Bounded overlap/default | Experimental center joins |
| --- | ---: | ---: |
| small.en, 96 cases / 752 words | 89 errors | 89 errors |
| medium.en, 96 cases / 752 words | 73 | 59 |
| medium.en, three book readings / 621 words | 126 | 102 |

These are development comparisons on packs without the newer optional `PITC`
pulse analysis. Their waveform, labels, lexicon and original acoustic/evidence
sections match the installed packs, but experimental center-cut coordinates can
differ. A separate 12-sentence comparison on these packs reduced medium-model
errors from 138 to 113 across 872 words. The unchanged small-model aggregate and
absence of listening feedback were reasons to retain the current default.
The disabled-option check reproduced all 96 existing plans and WAVs byte for
byte. Native tests also check a shared-vowel transition, reliable pulse cuts,
intact words, stop-burst protection, recording gaps, punctuation, manual rejection,
and the actual output clock.

A separate Medic rebuild tested 520 archive recordings using unprompted
large-v3 source transcription. Automatic filtering retained 411, and 409 passed
structural alignment checks after MFA fine-tuning. Its small-model errors rose
from 11 to 25 on the sentences and 61 to 81 on the book; the medium model also
regressed (12 to 22 and 53 to 73). The new source recordings and automatic
transcript provenance are preserved privately; the installed voice was retained.
Neither fresh alignment nor more recordings alone established a quality gain.

### Exact installed-pack verification

The installation check detected the missing `PITC` section in the development
pack links. The comparison was repeated on frozen, checksummed copies of all
eight installed packs, including their newer pitch pulses. All 195 default
plans and WAVs matched the earlier baseline byte for byte before reusing its
recognition results. Experimental renders were recognized again without hints.

| Diagnostic | Current default | Installed center-join option |
| --- | ---: | ---: |
| small.en, 96 development cases / 752 words | 89 errors | 92 |
| medium.en, 96 development cases / 752 words | 73 | 60 |
| medium.en, three book readings / 621 words | 126 | 94 |
| medium.en, 96 held-out cases / 872 words | 138 | 118 |

The installed option improves the larger-model aggregates but regresses the
smaller-model development aggregate. It remains optional. The three updated
book demos were checked against the actual installed-pack benchmark WAVs and
match byte for byte. No human-listening acceptance or linguistic boundary
accuracy is claimed. Aggregate results are in
[center-installed-results.json](center-installed-results.json).

### Longer native transitions and additional decoders

`--center-run-phones 12` retains longer naturally contiguous sound sequences,
with center cuts only at their exposed endpoints. The two-phone mode is unchanged.
The same frozen installed packs, 12 development sentences, 12 held-out sentences
and three book readings were used. No expected words or phones were supplied to
any recognizer. Vosk supplies a separate word decoder; Allosaurus supplies phone
emissions, mapped to ARPABET and compared against the pack's canonical lexicon.
Unknown emissions remain errors rather than being silently discarded.

| Diagnostic | Bounded/default | Two-phone center | Up to 12 phones |
| --- | ---: | ---: | ---: |
| Whisper small, development / 752 words | 89 | 92 | 83 |
| Whisper medium, development / 752 words | 73 | 60 | 67 |
| Whisper medium, book / 621 words | 126 | 94 | 92 |
| Whisper medium, held-out / 872 words | 138 | 118 | 110 |
| Vosk small English, development / 752 words | 312 | 272 | 277 |
| Vosk small English, book / 621 words | 351 | 341 | 331 |
| Vosk small English, held-out / 872 words | 432 | 417 | 409 |
| Allosaurus, 48 development cases / 1290 phones | 770 | 733 | 737 |
| Allosaurus, three readings / 1964 phones | 1042 | 1003 | 975 |
| Allosaurus, 48 held-out cases / 1416 phones | 885 | 810 | 820 |

Every number is an edit-error count within its own decoder/reference. The phone
comparison uses the six newer development sentences and first six held-out
sentences per voice. Canonical phone references do not cover every accent,
allophone or reduction, so their absolute error rate is not an intelligibility
percentage. Recognizer families agree on aggregate gains over the old renderer,
while the two center modes trade places on some material. No listening acceptance
is implied. Both center modes remain optional in this milestone.

The implementation passes 110 native tests, a MinGW cross-build and VCTTS
integration checks. The original/default and two-phone modes retain their exact
previous output in the 198-case compatibility check. Aggregate diagnostics are in
[center-long-results.json](center-long-results.json); audio, observations and
private model/voice fingerprints stay in the workspace.

## Current default: long native transitions

The up-to-12-phone center planner is now the ordinary synthesis path in the CLI,
desktop frontend and VCTTS library defaults. This promotes the same output already
evaluated above; it adds no pitch or duration normalization. Exact recorded words
and phrases remain anchors. The previous bounded planner is selectable with
`--boundary-phone-joins` (also `--legacy-overlap`). `--center-phone-joins` explicitly
keeps the earlier two-phone variant. The benchmark helper records the requested
planning mode and offers the boundary-planner control.

Across the eight game voices, the long mode improves the aggregate results over
the previous renderer for both Whisper sizes, Vosk, and canonical-phone
recognition. An additional 188-clip ordinary audiobook narrator was checked on
the same unrelated text: medium-model errors changed from 5 to 3 over the 94
development words, stayed at 7 over the 109 held-out words, and fell from 14 to
10 over the 207 Alice words. Its original waveform and labels were retained;
the local test copy received optional pitch analysis. See
[narrator-center-results.json](narrator-center-results.json).

This is an aggregate improvement, with remaining per-prompt and per-voice
regressions. Demoman's Vosk and phone totals still worsen, and Spy has small word
decoder regressions. The retained boundary option permits direct comparison.
No human-listening acceptance is claimed, and source-label/alignment work remains.

A more restrictive source-center policy was tested and rejected. It preserved
brief/uncertain phones whole, but medium-model development errors rose from 67
to 83 and held-out errors from 110 to 124; the small-model count rose from 83 to
97. Its improvement on the game book readings did not generalize to ordinary
sentences or the narrator. That policy is not part of the shipped default.

The promotion passes 112 native tests, a MinGW cross-build and the VCTTS
integration check. A 372-case comparison across all eight game voices and the
narrator verifies that the ordinary default reproduces the previously evaluated
long-mode plans and WAVs byte for byte. The explicit two-phone and boundary modes
also reproduce their earlier outputs. This changes which verified mode is chosen;
it does not introduce a newly measured waveform variant at deployment time.

## Rejected gain and vowel-evidence trials, 2026-11-07

Four private prototypes were evaluated against the current default on the same
220 sentence/book cases across eight game voices and the ordinary narrator.
None is promoted or exposed as a new production option. Source audio and labels
were unchanged. Policies and complete cohort totals are retained in
[experimental-join-results.json](experimental-join-results.json).

| TF2 medium.en errors | Development / 752 words | Prior heldout / 872 | Book / 621 |
| --- | ---: | ---: | ---: |
| Current default | 67 | 110 | 92 |
| Recording-level gain | 67 | 104 | 95 |
| Matching-vowel seam gain | 71 | 114 | 98 |
| Extra unsupported-vowel fallback cost | 63 | 111 | 98 |
| Extra unsupported-vowel exposed-cut cost | 69 | 112 | 98 |

Vosk and independent phone diagnostics do not support a broad readability claim
for these changes. Recording-level normalization improves some aggregate results
and the narrator, but harms particular game voices; its recording-level proxy
also hides worse actual vowel amplitude jumps in Soldier and Sniper. Restricting
correction to stable same-vowel joins reduces measured RMS discontinuity but still
increases medium.en errors. A smoother amplitude trace alone is insufficient.
Soft vowel-identity penalties likewise improve some Vosk results while worsening
other families or book passages. Manual acceptance and intact-word priority were
preserved in those experiments.

Every recognizer received only the actual output audio, without the requested
text as a prompt. Canonical-phone diagnostics include accent, reduction and
inventory mismatch; their absolute errors are not human intelligibility scores.
Repeatedly evaluated prompts are now development evidence. The unchanged current
default remains the comparison point for subsequent fresh-text checks.

A further 12 fresh sentences were fixed after those policies and before their
complete existing-corpus results were examined, then tested in all nine voices.
The existing `--beam 128` search was also checked without changing cost weights.
On the fresh 96 game-voice cases, default / wider search / exposed-cut penalty
made 142 / 148 / 137 medium.en word errors out of 1,176 reference words; Vosk
made 601 / 616 / 586. On the 48-case phone subset the corresponding errors were
1,117 / 1,091 / 1,098 out of 2,020 canonical phones. Narrator word errors were
3 / 2 / 3 (147 words), while phone errors were 88 / 77 / 97 (253 phones).
The wider search's earlier book gain does not consistently generalize to fresh
sentences. The exposed-cut penalty's fresh game-word gain does not erase its
book regressions or the narrator phone regression. Production beam width stays
32. Fresh prompts and all cohort totals are retained alongside the decisions;
no weight or threshold was retuned to individual voices or these new sentences.

## Search performance without changing speech, 2026-11-07

The planner now shares immutable path history and caches acoustic boundary
windows within each request. It retains the same costs, beam width and tie
ordering. All 440 plan/WAV pairs across nine voices and beam widths 32/128
match the previous implementation exactly. Maximum-length 512-word renders
also match in default, wider-search and boundary modes, including sanitizer
runs. The regular and address/undefined-behavior suites each pass 112 tests;
leak detection was disabled because this execution environment uses ptrace.
The Windows cross-build and VCTTS integration check pass.

Three interleaved CLI runs per engine/case measured the following median wall
clock times, including pack loading, planning and WAV output. Background work
can affect timings; these are local measurements, not portable latency promises.

| Voice / prompt | Beam | Before seconds | Optimized seconds | Speedup |
| --- | ---: | ---: | ---: | ---: |
| medic / alice | 32 | 7.059 | 0.879 | 8.03x |
| medic / alice | 128 | 10.479 | 2.097 | 5.00x |
| librivox-phil / alice | 32 | 7.867 | 1.099 | 7.16x |
| librivox-phil / alice | 128 | 13.075 | 2.723 | 4.80x |
| sniper / fresh-04 | 32 | 0.324 | 0.267 | 1.21x |
| sniper / fresh-04 | 128 | 0.491 | 0.323 | 1.52x |

This enables faster source-search experiments while keeping the verified
production speech unchanged. It is a performance improvement, not an additional
intelligibility claim. Measurements and validation details are in
[search-performance-results.json](search-performance-results.json).

## Runtime pronunciation adapter repair, 2026-11-07

Words absent from a pack's dictionary previously lost eSpeak vowel stress, and
valid ASCII phoneme variants could reject an entire pronunciation. The new book
passage reproduced this with `futurity`, which fell through to the spelling
heuristic. The adapter now requests IPA, maps supported English phones to ARPABET
and retains primary/secondary vowel stress. Unknown phones still reject the
conversion and keep the existing explicit fallback behavior. eSpeak supplies
pronunciation only; all rendered audio remains from the selected pack.

The 328 existing sentence/book plans and WAVs remain byte-identical. All nine
voices were additionally checked on 12 extended-vocabulary sentences and the
first three paragraphs of chapter V of H. G. Wells's *The Time Machine*.
The original adapter, IPA conversion without stress, and the complete repair
were compared without pitch, gain, duration or source-cost changes.

| TF2 diagnostic | Original | IPA phones only | IPA + stress |
| --- | ---: | ---: | ---: |
| medium.en, vocabulary / 856 words | 311 | 300 | 298 |
| medium.en, new book / 3,048 words | 658 | 664 | 666 |
| Vosk, vocabulary / 856 words | 701 | 700 | 695 |
| Vosk, new book / 3,048 words | 1,870 | 1,838 | 1,823 |
| Canonical phones, vocabulary / 3,840 phones | 2,120 | 2,109 | 2,111 |
| Canonical phones, new book / 10,424 phones | 5,309 | 5,266 | 5,263 |

The ordinary narrator remains mixed: vocabulary medium.en errors change
20 → 23 and book errors 31 → 29, while Vosk changes 60 → 57 and 109 → 121.
Canonical-phone errors change 164 → 165 and 476 → 469. This repairs information
lost by the adapter; the modest aggregates do not establish generally intelligible
speech. Source coverage, alignment and individual prompt regressions remain.
G2P itself is also imperfect: eSpeak's `futurity` stress differs from dictionary
variants. Phone references for five dictionary-missing book words and five
additional challenge forms are fixed separately and documented; no reference
pronunciation is supplied to the recognizers or synthesis.

Validation includes 113 Python/native integration tests, 13 native parser
fixtures, the Windows cross-build and VCTTS integration. Parser fixtures run on
Linux and Windows CI without requiring a system eSpeak install. UTF-8 byte
literals also cover embedded Windows consumers that compile the source directly.
[Complete results and reference provenance](pronunciation-repair-results.json)
retain per-voice regressions and the private phone-only control.

The separate stable-vowel-cut experiment was rejected. On the new book's game
voices, medium.en / Vosk / phone errors changed 658 → 688, 1,870 → 1,875 and
5,309 → 5,320. A locally steadier spectrum did not reliably improve rendered
speech. Its policy and comparison totals remain in
[experimental-join-results.json](experimental-join-results.json).
