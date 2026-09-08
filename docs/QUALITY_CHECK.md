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
