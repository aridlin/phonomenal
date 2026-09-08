#!/bin/sh
# Install only into this project; no root access or system Python modifications.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname "$script_dir")
cd "$project_dir"
command -v uv >/dev/null || { echo 'Install uv, then run this script again.' >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo 'Install ffmpeg, then run this script again.' >&2; exit 1; }
uv venv --python 3.11 .venv-vcpack
uv pip install --python .venv-vcpack/bin/python -e '.[builder]'
mkdir -p .tools/micromamba
if [ ! -x .tools/micromamba/bin/micromamba ]; then
    curl -fL https://micro.mamba.pm/api/micromamba/linux-64/2.9.0 -o .tools/micromamba.tar.bz2
    tar -xjf .tools/micromamba.tar.bz2 -C .tools/micromamba bin/micromamba
fi
.tools/micromamba/bin/micromamba create -y -r "$project_dir/.tools/mamba" -p "$project_dir/.tools/aligner" -c conda-forge python=3.11 montreal-forced-aligner=3.3.9
for kind in acoustic dictionary g2p; do
    scripts/mfa-local model download "$kind" english_us_arpa
done
printf 'Ready. Launch the frontend or run .venv-vcpack/bin/python scripts/builder.py --help\n'
