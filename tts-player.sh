#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
exec ./cpp/build/phonomenal_splicer_frontend --player "$@"
