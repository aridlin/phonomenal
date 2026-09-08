# Speech regression check

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

The reported Soldier phrase transcribes exactly after rejecting a collapsed vowel inside the previous screaming “you are” phrase. Its exact match is not evidence that arbitrary Soldier text is solved. Several other voices regress on particular prompts; duration heuristics alone cannot repair incorrect source transcripts. Medic and full Heavy are being rebuilt and must be evaluated separately before promotion.

The single-narrator comparison uses only the **16:47 first chapter, The Telltale Heart**, from *Six Creepy Stories* by Edgar Allan Poe, read by Phil Chenevert. [LibriVox catalog and reader credits](https://librivox.org/six-creepy-tales-by-edgar-allan-poe/). LibriVox identifies the recordings as public domain in the USA. The resulting pack contains 188 accepted clips, 2,153 words and 7,085 phones; it was built with unprompted small.en ASR and MFA fine-tuning. It was tested on the same unrelated text, with no special narrator selection rules. The complete two-hour book was not processed.

Machine-readable results with recognized text are in [cross-voice-results.json](cross-voice-results.json). Audio and voice assets remain in the local/deployed workspace. No independent human-labelled phone-boundary benchmark has been performed.
