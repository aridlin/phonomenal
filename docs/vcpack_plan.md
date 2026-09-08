# Phonomenal: automatic voice packs and native synthesis

Proposed implementation plan, 2026-09-08. Scope: this `codexp/phonomenal` tree and its bundled `vctts/` integration. This describes work to implement; it is not a claim that these features already exist. It supersedes the architecture and next steps in `vctts_splicer_plan.md`.

## Outcome

Two independently usable products:

1. **Builder:** give it speech MP3s, get one portable `.vcpack` containing audio, transcripts, word/phone alignment, pronunciations, acoustic features, and search indexes. The builder may use any programming language; Python is the initial implementation choice because it reuses the existing speech tooling. Only playback is required to be C++.
2. **C++ engine:** load that pack once, accept text, choose and join recorded speech, return PCM/WAV to vctts or a standalone player. No Python, ASR service, or original MP3s needed during playback.

Prefer the longest usable recordings of the requested speech. For words absent from the recordings, generate their pronunciation and reuse the longest matching sequences of speech sounds (phonemes). Choose occurrences with compatible pitch, timbre, energy, and articulation at their boundaries.

Arbitrary text and arbitrary sound coverage are different requirements. The frontend should process new words, numbers, names, and punctuation; a finite recording collection cannot guarantee an accurate rendition of a sound absent from it. The default best-effort mode reports substitutions. Strict mode reports missing coverage without silently dropping words. Start with English for the existing TF2 material; additional languages require their own tested normalization, pronunciation, and alignment profiles.

## Verified starting point

Source inspection, without running a synthesis benchmark:

| Existing component | Change needed |
|---|---|
| `src/phonomenal/align.py`: WhisperX, MFA, accepted/rejected state | Generic MP3 import, robust automatic quality checks, resumable jobs, distinct confidence fields |
| `src/phonomenal/audio.py`, `config.py`: 16 kHz normalized masters | Separate analysis audio from playback audio and map timing explicitly |
| `src/phonomenal/packager.py`: tab-separated `.phbank` plus external WAV | A real binary, self-contained container |
| `cpp/src/splicer.cpp`: greedy `PlanText`, letter-based word pieces, guessed pronunciations | Pronunciation-aware search across the entire utterance |
| Same file: per-slice pitch/RMS estimates and fixed fades/gaps | Precomputed boundary features, context-aware joins, natural pauses |
| `cpp/include/phonomenal_splicer/splicer.h`: library interface | Pack metadata, diagnostics, cancellation, reusable engine state |
| `vctts/tts_phonomenal.cpp`: native adapter | Dynamic pack discovery and caching; currently hardcodes nine voices and loads each bank per message |

`PlanPhonemes` contains a separate memoized search, but normal text uses its own greedy phone fallback. Unify these paths. Packaging currently strips stress digits from phone labels, and alignment parsing passes clip confidence down to words/phones; neither should be mistaken for measured phone-level confidence.

## Side A: automatic builder

Proposed interface (commands do not exist yet):

```sh
phonomenal build-pack ./speech --voice my-voice --language en --output my-voice.vcpack
phonomenal inspect-pack my-voice.vcpack
```

The normal flow is select a folder, select/name a voice, and build. Show progress, usable speech duration, rejected clips, sound coverage, and a few generated previews. Transcript corrections and boundary editing are optional repair tools, not mandatory steps for every file.

1. **Discover and decode.** Accept arbitrary filenames and folders; keep TF2 discovery as a preset. Hash sources, detect duplicates and corrupt files, decode MP3 once. Use one configured playback rate per pack (48 kHz mono default), retaining original quality as far as the source permits. Upsampling is not restoration. Create a separate 16 kHz analysis copy.
2. **Segment speech.** Apply VAD with boundary padding. Detect clipping, music, overlapping speech, and anomalous silence. Default to a declared single speaker per build. Mixed-speaker mode uses diarization and emits separate candidate packs for review; do not silently combine speakers. Keep expressive speech when usable and label style rather than rejecting all shouting.
3. **Transcribe.** Reuse WhisperX as the initial backend; CPU mode must work, with optional GPU acceleration. Preserve raw and normalized transcripts. Supplied transcripts override ASR when provided. Retry suspicious clips with stronger decoding; filenames/category hints cannot establish transcript truth.
4. **Align words and phones.** Reuse MFA with a matched acoustic model and pronunciation dictionary. Preserve stress, pronunciation variants, pauses, and context. Track every crop/resample offset back to playback sample positions. Never trim or re-time the playback waveform afterward without recomputing those positions.
5. **Validate and quarantine.** Check bounds, monotonicity, implausible durations, speech/transcript disagreement, and unexplained audio. Keep ASR confidence, alignment evidence, and audio-quality measures separate; use null for unavailable confidence. Retry once under a documented policy, then exclude unreliable units and explain why. A plausible forced alignment alone is not proof of a correct transcript.
6. **Extract acoustic features.** Precompute frame-level F0, voicing probability, energy, spectral envelope features, and trustworthy pitch marks. Store boundary summaries plus contours, speaking rate, stress/context labels, and quality flags. Unvoiced consonants have no reliable pitch; do not assign them fabricated F0 values.
7. **Index recorded spans.** Store each recording once. Index phrase/word sequences and phone sequences with source ranges. Include phone spans across word boundaries when continuous. Model diphones as transitions between sounds, with appropriate internal cut anchors, rather than merely concatenating two isolated phones. Retain varied pitch/style occurrences, not just one example per word.
8. **Package and verify.** Write a temporary pack, validate it using the C++ reader, synthesize smoke previews, then atomically publish the completed pack. Persist per-stage state keyed by source hashes, settings, and model versions so interruptions and incremental additions reuse valid work. Bound retries and report empty/insufficient inventories explicitly.

WhisperX provides transcription, VAD, word alignment, and optional diarization; MFA remains the explicit word/phone alignment stage in this design. Pin tested tool and model versions in the build manifest. Sources: [WhisperX](https://github.com/m-bain/whisperX), [MFA alignment workflow](https://montreal-forced-aligner.readthedocs.io/en/latest/user_guide/workflows/alignment.html).

## Boundary accuracy is a primary release gate

Recognition correctness and timing correctness are measured separately. Use MFA's extra fine-tuning pass, which refines around phone boundaries on a 1 ms feature grid. That grid is not a guarantee of 1 ms accuracy. Retain integer sample positions, original and refined timestamps, method/version provenance and explicit unknown confidence. Validate crop/resample mapping to within one output sample; never use rounded seconds as the authoritative coordinates.

Use an independently hand-labelled, held-out boundary corpus with waveforms/spectrograms and normal/slow cut-point listening. Include stops, fricatives, fast connected speech, breaths, short words, accents and expressive speech. Report word and phone onset/offset median, p95/p99 errors, >20/40 ms outliers, and label mismatches separately. Initial proposed clean-speech targets: median <=5 ms and p95 <=15 ms, subject to annotation agreement; these are acceptance goals, not measured promises. Ambiguous coarticulated transitions need annotated tolerance ranges, not invented exact truth.

Keep linguistic boundaries distinct from renderer cut anchors. A zero crossing does not locate a phoneme boundary. Do not shift boundaries solely to low amplitude or divide word duration evenly into phonemes. A questionable internal boundary should disable that cut while still allowing a reliable larger phrase to be reused. Automatic import must report unresolved uncertainty and usable cut coverage.

Source: [MFA fine tuning](https://montreal-forced-aligner.readthedocs.io/en/latest/user_guide/implementations/fine_tune.html).

## `.vcpack` v1 format

A specified little-endian binary container with typed sections. Define the schema before implementing either writer or reader; never serialize native C++ structs or pointers directly.

| Section | Contents |
|---|---|
| Header and directory | Magic, major/minor version, flags, total length, section types, offsets, lengths, checksums |
| Metadata and strings | Voice ID/name, language/accent, phone inventory/version, sample rate, builder/model versions, source hashes |
| Audio | PCM16 mono playback blocks for v1, recording boundaries, logical sample positions |
| Alignment | Utterances, words, phones, stress, pauses, sample ranges, source IDs, quality/confidence fields |
| Features | F0/voicing/energy tracks, spectral summaries, pitch/cut anchors and feature schema version |
| Pronunciation | Observed variants and overrides, phoneme symbols and contextual labels |
| Search indexes | Token and phone sequence indexes pointing into aligned source spans |
| Coverage | Available/missing sounds and transitions, usable durations, quality statistics |

Use 64-bit lengths/sample offsets, length-delimited UTF-8 strings, and explicit numeric encodings. Validate arithmetic, bounds, references, resource limits, and required sections before reading. Unknown optional sections may be skipped; incompatible major versions fail clearly.

PCM keeps v1 slicing deterministic and inexpensive. 48 kHz mono PCM16 costs about 346 MB per hour before metadata. Add independently decodable lossless blocks and a seek table later if size warrants it; do not cut or repeatedly encode MP3 frames. Store audio once and reference it from overlapping units. Use a suffix/trie-style sequence index rather than materializing every possible phrase length quadratically.

All voice-specific data lives inside the pack. Generic language/G2P assets ship with the runtime and are versioned; required language profiles must be discoverable before synthesis. No source paths need to exist on the playback computer.

Migration: retain `.phbank` reading temporarily and add an explicit converter that embeds its master audio. Recompute acoustic features; mark inherited alignment quality accurately. Recover stress from original alignments where available, otherwise mark it unknown. Converting old 16 kHz banks cannot recover discarded audio quality.

## Side B: C++ planning and rendering

### Text and pronunciation

Normalize UTF-8 text with the pack's language profile. Preserve punctuation and sentence boundaries. Expand numbers and common abbreviations; handle acronyms and names with deterministic defaults and optional pronunciation overrides.

Resolve pronunciations through contextual variants/overrides, a full language lexicon, then a real G2P model. Replace handwritten `GuessPronunciation` as the main unseen-word path. Prototype an English finite-state G2P with native inference, and gate adoption on Windows/Linux packaging and held-out pronunciation accuracy. [Phonetisaurus](https://github.com/AdolfVonKleist/Phonetisaurus) supplies C++ G2P tools; the exact shipping backend remains a short implementation spike, not an assumed solved dependency.

Match unknown words by sound. A written fragment such as `read` or `ough` is not a reusable acoustic unit unless its pronunciation matches this occurrence. Preserve stress and neighboring phones to distinguish otherwise similar candidates.

### Global chunk selection

Build a target pronunciation lattice with word/stress/punctuation annotations. Candidate edges cover matching target spans using continuous source audio:

1. Entire utterance or longest recorded phrase.
2. Shorter recorded phrases and whole words.
3. Pronunciation-matched syllables and longer phone runs, including runs extracted from other words.
4. Diphone transitions and individual phones.
5. Explicit phonetic approximations only when exact phone coverage cannot form a complete path.

Find the best complete path using Viterbi/dynamic programming over candidate endings. State must retain the previous occurrence and pronunciation branch, because join cost depends on both sides. A single score per text position loses this information. Use bounded candidate sets and beam pruning for large inventories, retaining diverse boundary/pitch candidates. Report pruning: a beam result is the best explored path, not a proof of the mathematical optimum.

After pronunciation correctness and unit-quality gates, make **fewer artificial joins the dominant preference**. Among equally fragmented valid paths, prefer longer uninterrupted runs and lower acoustic cost. Use an explicit severe-boundary mismatch threshold to let a slightly more fragmented path beat an obviously bad join. This threshold and tie-breaking need listening tests, not arbitrary claims about ideal weights.

Candidate target cost considers stress, phrase position, duration, speaking style, and confidence. Pairwise join cost considers boundary F0 difference/slope, voicing transitions, spectral envelope difference, energy difference, phonetic context, and required audio modification. Calculate pitch distance in semitones only where voiced and reliable. Similar pitch cannot justify using the wrong phoneme.

This follows the established distinction between target fit and adjacent-unit join cost; the chunk preference and thresholds are project design choices. See [Festival waveform/unit selection notes](https://www.cs.cmu.edu/~awb/11752/notes/festtut_7.html).

Keep truly adjacent samples from the same recording contiguous, with no artificial join. Preserve pauses inside selected spans. Avoid the current four-word default becoming a hard ceiling on phrase reuse.

Example: if the prompt begins `I need a medic`, and those words were recorded together, reuse that recording. If the next word is unseen, obtain its phones and cover them with the largest recorded matching phone runs. Evaluate multiple occurrences against both the preceding phrase and what follows, rather than committing to the first locally attractive slice.

### Rendering

Selection quality comes first. Render from pack sample ranges and validated cut anchors:

- Preserve coarticulation and intact source runs; do not re-fade internal boundaries.
- Search a small permitted boundary window for compatible waveform/phase cuts without removing consonant attacks.
- Use adaptive short fades. Voiced-to-voiced joins can use pitch-synchronous overlap; unvoiced/transient regions need different treatment. A universal 12 ms fade can erase short events.
- Apply modest smooth gain correction and headroom management without flattening the voice's expression.
- Add pauses from punctuation and source context, replacing the blanket 24 ms gap between words.
- Only after selection/join improvements, trial conservative pitch/duration adjustment for reliable voiced regions. Initial experimental limits: roughly two semitones and ten percent duration change; tune or disable from listening evidence. Preserve formants and reject processing that worsens the join.

Pitch-synchronous overlap-add is an established technique for pitch/time manipulation, not a guarantee of artifact-free edits: [Praat overlap-add documentation](https://www.fon.hum.uva.nl/praat/manual/overlap-add.html).

Return a plan report alongside audio: source spans, exact-word/phone-fallback coverage, substitutions, join count, transformations, and timings. Never silently omit a failed word. Missing phones cause a high-penalty articulatory approximation in best-effort mode, or a structured error in strict mode. Spell-out is a separately selected policy because it changes the spoken message.

## Runtime and vctts contract

Keep `phonomenal_splicer` as the shared C++20 engine, with CLI/player/vctts as consumers. Split the monolithic implementation into pack reader, language frontend, inventory, planner, and renderer modules as those components change.

Proposed API shape:

```cpp
auto pack = VoicePack::Load(path);           // immutable shared inventory
auto engine = Engine(pack, language_assets);
auto result = engine.Synthesize(text, options, stop_token);
// result: PCM + sample rate + diagnostics; WAV serialization is an adapter
```

Use per-request scratch state and bounded shared caches so simultaneous playback/tests cannot race on mutable feature caches. Keep heavy work on a worker thread. Define cancel/replace/queue behavior and maximum prompt/resource limits. Start with completed-utterance PCM; later stream at planned clause boundaries without changing committed joins.

The standalone CLI should support text from stdin, WAV to a file/stdout, and JSON plan diagnostics on stderr or a separate file. Binary WAV stdout must contain no logs. A player can use the same PCM interface.

In the bundled `vctts/`:

- Discover `.vcpack` files by validated metadata and display arbitrary voice names; remove the nine-merc-only assumption.
- Persist selection by voice ID/path, cache the selected pack/engine, and reload on an explicit switch or detected replacement.
- Route generated audio through the existing playback/output-device path; keep synthesis independent of audio routing.
- Display loading/build-quality errors and concise approximation status. Keep detailed source inspection in the player/debug view.
- Verify Test TTS, normal overlay submission, stop/queue handling, selected output device, and actual captured playback audio.

The bundled adapter is the first integration target. If distributing to another vctts tree, port the validated adapter there after identifying that release source; this plan does not assume the older separate checkouts are current.

## Implementation sequence and acceptance gates

| Stage | Concrete deliverable | Acceptance gate |
|---|---|---|
| 0. Baseline | Fixed audio corpus, prompts, current-engine outputs, manual transcript/boundary sample | Document present failures and freeze evaluation data before tuning |
| 1. Portable packs | v1 schema, Python writer, C++ reader, legacy converter, inspect command | One pack works after original sources/external WAV are unavailable; Python/C++ fixtures agree; corrupt/truncated files fail safely |
| 2. Automatic import | Generic MP3 build command, analysis/playback mapping, QA, resume, features | Folder-to-pack without hand-written transcripts; restart reuses complete stages; rejected clips are explained; sampled boundaries audibly/visually checked |
| 3. Unseen text | Language frontend, lexicon/G2P, unified global planner | Novel words assembled from existing phones; no letter-fragment mispronunciations or omitted words; synthetic cases prove global search and long-span reuse |
| 4. Audible quality | Boundary-aware costs and renderer, calibrated chunk preference | Blind comparison beats baseline for intelligibility and join smoothness while preserving voice identity |
| 5. Shipping playback | Cached engine, dynamic pack selection, CLI/player and vctts integration | Windows/Linux core builds; vctts playback and cancellation verified; no Python/network runtime dependency |

Stages 2–4 are the quality-critical work. A new extension and nicer UI alone will not improve bad alignments or incorrect pronunciations. Add pitch shifting only after there is evidence that the selection baseline needs it.

Evaluation must separate: recorded exact phrases; recombined known words; unseen words whose phone sequences are available; missing-phone cases; names/numbers/homographs; punctuation and long prompts; whisper/shout changes; noisy/short inputs; and mixed-speaker rejection. Remove whole test utterances before building the novel-text inventory and check duplicate leakage.

Measure listener transcription accuracy, blind naturalness/voice-identity preference, joins per utterance, uninterrupted span lengths, fallback/substitution rates, boundary pitch jumps where voiced, clipping, cold/warm latency, real-time factor, and peak memory. ASR round-trips are a secondary signal; they cannot establish naturalness by themselves.

Set the initial performance budget on the actual test machine: aim for warm synthesis of a typical 20-word message within 500 ms and cancellation within 100 ms, then report median/p95, pack size, and hardware. These are proposed budgets, not measured claims. Have the quality trial win at least 65% of blinded non-tied baseline comparisons across at least 100 prompts and several listeners, report ties and uncertainty, and require no intelligibility regression. Adjust only with documented evidence.

The first milestone should be one generic MP3 folder producing one self-contained pack, with exact recorded text playing through the native library and vctts. Then improve coverage and joins against the frozen baseline until the listening gate passes.

## Default target and implementation update

The primary target is TF2, with Heavy first, Medic second, Soldier third, followed
by Scout, Demoman, Engineer, Sniper, Spy and Pyro. Both generator and TTS/player
have FT frontends, defaulting to Gruvbox. The builder also includes an original
124-take recording script and generic MP3/own-voice support. See README for the
implemented interface and explicit remaining quality limitations; this document's
acceptance targets remain goals until their measurements are recorded.
