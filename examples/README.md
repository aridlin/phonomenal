# Examples

## No-download format and planner demonstration

```sh
python examples/create_demo.py
./cpp/build/phonomenal_splicer_cli --bank examples/demo.vcpack \
  --text "hello there friend" --plan --output examples/demo.wav
```

The checked-in `demo.vcpack` contains synthetic tones with deliberately simple
labels. The planner should select the requested contiguous span as **one chunk**.
This tests the file format and selection mechanics, not voice quality. Its source
is fully reproducible in `create_demo.py` and does not need NumPy.

## Record your own real voice

Read [recording-script/script.txt](recording-script/script.txt), or use the FT
builder's **My own voice** preset. The 124 short takes have matching `.txt`
transcripts under `recording-script/`; save corresponding `take_001.wav`, etc.
The frontend saves each WAV/transcript pair itself. Build a pack from the saved
audio folder, then try sentences that rearrange words and introduce new ones.

## TF2 mercs

Supply local source recordings under `source/heavy/`, then run:

```sh
.venv-vcpack/bin/python scripts/builder.py build-mercs --merc heavy
./cpp/build/phonomenal_splicer_cli --bank data/packages/heavy.vcpack \
  --text "I need more time." --plan --output data/spliced/heavy-example.wav
```

Use `--merc all` for Heavy → Medic → Soldier → the remaining mercs. Game audio
is not distributed in the repository. The original reading script and synthetic
demo are MIT licensed.
