#!/bin/sh
cd "$(dirname "$0")" || exit 1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
exec .venv/bin/python captions.py "$@"
