# Medic independent-evidence comparison

Local result, 2026-09-08. The same frozen C++ engine rendered each pair; Whisper small.en transcribed without expected-text hints. Default adaptive word gaps were enabled, duration normalization was off. Pitch-on cases used a 100:180 Hz band.

Engine SHA-256: `64c01aed3346316fd5609abd24118f9318e9ef25a7c515ef5fa4c8a3f4a713dd`.

| Prompt | Before, pitch off | Reviewed, pitch off | Before, pitch on | Reviewed, pitch on |
| --- | ---: | ---: | ---: | ---: |
| reading-passage | 38.8% | 28.6% | 34.7% | 71.4% |
| tts-passage | 52.9% | 29.4% | 52.9% | 29.4% |
| short | 50.0% | 50.0% | 50.0% | 125.0% |
| soldier-approve | 83.3% | 83.3% | 83.3% | 83.3% |

These are word error rates; lower is better. The reviewed pack improved both long prompts without pitch editing, but the short prompts remain poor. Pitch editing materially regressed the reviewed reading and homework cases. This pack has not replaced the default Medic pack. The improvements do not establish general intelligibility, boundary accuracy or naturalness.

All 371 source recordings received independent Whisper, Vosk and Allosaurus observations. 3,756 of 5,621 phones have some detector disagreement; those flags are uncalibrated review evidence, not a measured error count. Audio, source labels, lexicon and metadata are byte-identical to the input. The original C++ reader accepted the extended pack, and SPEC remains at the physical end.

Raw WAVs, plans, boundary reports and recognized transcripts are in `data/verification/acoustic-v2/medic-evidence-comparison` and `medic-evidence-pitch-comparison`. The remaining mercs and narrator have a resumable local queue, including water/tomorrow prompts outside the four reported examples. Their results are not yet complete.
