#!/bin/bash
# Item 1b (PASTE2 multi-seed tear CIs) + Item 4 (magnitude-matched smooth control)
# + PASTE2 tear on the 3rd donor pair (for the 3-fold LODO head-to-head).
set -e
cd /Users/seangplee/biostartup-main
export PYTHONUTF8=1
PY=.venv/bin/python

echo "##### ITEM 1b: PASTE2 multi-seed cross-tear (151507/151508), seeds 0,9999,10000,10001,10002 #####"
for sd in 0 9999 10000 10001 10002; do
  echo "--- seed $sd ---"
  $PY src/sweep_deformation.py --mode cross --tear --severities 0,4,8 \
      --dissimilarity pca --seed $sd --suffix ms_tear_seed$sd
done

echo "##### ITEM 4: magnitude-matched SMOOTH at high severities (151507/151508) #####"
# tear sev8 mean displacement ~2027 px; smooth mean disp ~ severity*90.7 px,
# so severities 8..22 bracket/exceed the tear's magnitude. If smooth stays flat
# here, the tear degradation is the discontinuity, not displacement magnitude.
$PY src/sweep_deformation.py --mode cross --severities 8,12,16,20,22 \
    --dissimilarity pca --seed 0 --suffix magmatch_smooth

echo "##### PASTE2 cross-tear on 3rd donor pair 151673/151674 (for LODO head-to-head) #####"
$PY src/sweep_deformation.py --reference 151673 --sample 151674 --mode cross --tear \
    --severities 0,4,8 --dissimilarity pca --seed 0 --suffix tear_Br8100

echo "##### PASTE2 SWEEPS DONE #####"
