#!/bin/bash
# Item 3: full leave-one-donor-out across all 3 subjects, both feature modes.
# Each fold: train on TWO donor pairs, test on the HELD-OUT donor pair.
#   Br5292=151507/151508  Br5595=151669/151670  Br8100=151673/151674
set -e
cd /Users/seangplee/biostartup-main
export PYTHONUTF8=1
PY=.venv/bin/python

run () {  # mode  train-pairs  test-pair  out
  echo "=== LODO mode=$1 held=$3 ==="
  $PY src/train_cross_loo.py --train --feature-mode "$1" \
      --train-pairs "$2" --test-pair "$3" --out "$4"
}

# Fold 1 — hold out Br5292 (151507/151508)
run global   151669/151670,151673/151674 151507/151508 lodo_global_heldBr5292
run perslice 151669/151670,151673/151674 151507/151508 lodo_perslice_heldBr5292
# Fold 2 — hold out Br5595 (151669/151670)
run global   151507/151508,151673/151674 151669/151670 lodo_global_heldBr5595
run perslice 151507/151508,151673/151674 151669/151670 lodo_perslice_heldBr5595
# Fold 3 — hold out Br8100 (151673/151674)
run global   151507/151508,151669/151670 151673/151674 lodo_global_heldBr8100
run perslice 151507/151508,151669/151670 151673/151674 lodo_perslice_heldBr8100

echo "##### LODO DONE #####"
