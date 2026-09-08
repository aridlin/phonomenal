# Independent recognition and timing evidence

Choose **Thorough: compare independent word and phone detectors** in the FT
builder/player, or run:

```sh
python scripts/builder.py analyze-pack medic.vcpack --output medic-reviewed.vcpack
python scripts/builder.py build-pack recordings --voice mine --output mine.vcpack --thorough
```

The ordinary acoustic analysis remains available without extra models. Thorough
analysis uses unprompted Whisper and Vosk word recognition, and Allosaurus phone
recognition. MFA supplies the original fine-tuned forced alignment. Each detector
runs in its own process and releases its model before the next detector loads.
Results are cached per audio content, sample rate, detector, model and package
version. Interrupted jobs resume completed recordings. `--limit 3` makes a small
pilot; the report explicitly identifies the remaining unmeasured recordings.

Install the optional tools into the same Python environment as the builder:

```sh
uv pip install --python .venv-vcpack/bin/python '.[builder,detectors]'
.venv-vcpack/bin/python -m allosaurus.bin.download_model -m eng2102
mkdir -p .tools/models
curl -fL https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip -o .tools/models/vosk.zip
python -m zipfile -e .tools/models/vosk.zip .tools/models
```

For a CPU-only PyTorch installation use its official CPU wheel index. The default
Vosk model directory is `.tools/models/vosk-model-small-en-us-0.15`; the CLI accepts
`--vosk-model`. Whisper shares the existing `data/cache/asr` model cache.

Matching islands are retained when preceding words disagree. Word timestamps
contribute disagreement ranges with their native frame granularity. Allosaurus
emissions are approximate positions *inside* phones and never automatically
replace splice cuts. IPA labels lacking a known ARPABET mapping remain unknown.
Recognizer scores are retained separately; they are not averaged into a fake
probability. A disagreement penalizes selection; it cannot certify a wrong
label, repair a missing phone, or prove a listener will understand the result.

`TRST` stores the small C++ selection summary. `EVID` preserves detector outputs,
alternatives and provenance. `PROS` stores stress/context, observed pronunciation
variants, per-phone duration distributions, pitch contours, boundary spectra and
coverage. Manual editor saves invalidate those derived sections. Original packs
remain available, and all sections are optional for older readers. The complete
binary and JSON field specification remains raw ASCII at the end of every pack.

Model/software sources: [Vosk models and licenses](https://alphacephei.com/vosk/models),
[Allosaurus](https://github.com/xinjli/allosaurus),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper).
Allosaurus is GPL-3.0 and is an optional separately installed generator dependency;
its source and license must accompany redistribution under the applicable terms.
Vosk's small English model is Apache-2.0. Model weights are downloaded locally and
are not bundled into the player or project releases.

To get extra recording material for scarce phones in an existing pack:

```sh
python scripts/builder.py coverage-script mine.vcpack --output extra-takes --takes 16
```

This reorders original script sentences by the pack's trusted coverage where
available, and reports when it must use unverified labels instead. The full
124-take starter script remains available in the generator.

Short recordings share bounded 25-second Whisper windows separated by 400 ms of
silence. Word coordinates are mapped back to each file; words crossing a file
boundary are excluded from support counts. Cache keys include batch composition.
The manual editor exposes historical detector observations in recording JSON.
Phone `review.state` accepts `unreviewed`, `accepted` or `rejected`. A review's
label/start/end must match the current phone; otherwise it is invalidated. A
master-audio replacement clears reviews. `QREV` preserves accepted/rejected
decisions separately from derived analysis; rejected phones are never selected.
