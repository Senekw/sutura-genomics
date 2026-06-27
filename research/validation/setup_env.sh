#!/bin/bash
# Sutura validation — environment build + DLPFC data download.
# Creates a Python 3.12 venv and downloads the spatialLIBD slices needed to
# independently reproduce the Sutura results. Idempotent: re-running skips done work.
set -e
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
VENV=$PROJ/.venv
LOG=/tmp/arca_setup.log
cd "$PROJ"

echo "=== [1/4] create venv (python 3.12) ==="
if [ ! -x "$VENV/bin/python" ]; then
  uv venv --python 3.12 "$VENV"
fi

echo "=== [2/4] install core scientific stack ==="
uv pip install --python "$VENV/bin/python" \
  "numpy<2" "scipy>=1.10" "scikit-learn>=1.3" "matplotlib>=3.7" \
  "anndata>=0.10" "h5py" "requests" "pandas"

echo "=== [3/4] install torch + torch_geometric (CPU) ==="
uv pip install --python "$VENV/bin/python" "torch>=2.2" "torch_geometric>=2.5"

echo "=== [4/4] download DLPFC slices (Figshare 22004273) ==="
"$VENV/bin/python" "$PROJ/validation/fetch_data.py"

echo "=== DONE setup ==="
"$VENV/bin/python" -c "import numpy,scipy,sklearn,anndata,torch,torch_geometric; print('imports OK; numpy',numpy.__version__,'torch',torch.__version__)"
