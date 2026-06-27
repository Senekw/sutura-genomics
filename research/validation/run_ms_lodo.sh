#!/bin/bash
# Multi-seed error bars on the HELD-OUT folds S2 (151669/151670) and S3 (151673/151674).
# Brings the two held-out donors up to the in-sample fold's 5-seed rigor.
#
#   PASTE2  : 5 seeds (0,9999,10000,10001,10002) x {S2,S3}, tear, sev 0,4,8   = 10 runs
#   STalign : seed 0 x {S2,S3}, tear, sev 0,4,8, niter 2000                   =  2 runs
#   Sutura  : multi-seed held-out eval from trained lodo_*.pt (both modes)    =  1 step
#
# Sequential within waves of 4 (thread-capped) so 10 cores aren't oversubscribed.
# Idempotent: re-running overwrites the same result files. DONE marker written last.
set -u
cd /Users/seangplee/biostartup-main
export PYTHONUTF8=1
# cap per-process BLAS threads so 4 parallel jobs share 10 cores cleanly
export OMP_NUM_THREADS=3 OPENBLAS_NUM_THREADS=3 MKL_NUM_THREADS=3 NUMEXPR_NUM_THREADS=3
PY=.venv/bin/python
LOG=results/ms_lodo_run.log
DONE=results/ms_lodo_DONE.txt
rm -f "$DONE"; : > "$LOG"
log(){ echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

paste2(){ # ref smp seed suffix
  log "START PASTE2 $1/$2 seed=$3 -> $4"
  if $PY src/sweep_deformation.py --reference "$1" --sample "$2" --mode cross --tear \
        --severities 0,4,8 --alpha 0.1 --s 0.99 --dissimilarity pca --seed "$3" \
        --suffix "$4" >> "$LOG" 2>&1; then log "OK   PASTE2 $4"; else log "FAIL PASTE2 $4 (exit $?)"; fi
}
stalign(){ # ref smp suffix
  log "START STalign $1/$2 -> $3"
  if $PY validation/run_stalign.py --reference "$1" --sample "$2" \
        --severities 0,4,8 --niter 2000 --suffix "$3" >> "$LOG" 2>&1; then log "OK   STalign $3"; else log "FAIL STalign $3 (exit $?)"; fi
}

log "=== MS-LODO batch START (folds S2,S3) ==="

# --- PASTE2: 10 runs in 3 waves of <=4 ---
paste2 151669 151670 0     ms_tear_S2_seed0     &
paste2 151673 151674 0     ms_tear_S3_seed0     &
paste2 151669 151670 9999  ms_tear_S2_seed9999  &
paste2 151673 151674 9999  ms_tear_S3_seed9999  &
wait
paste2 151669 151670 10000 ms_tear_S2_seed10000 &
paste2 151673 151674 10000 ms_tear_S3_seed10000 &
paste2 151669 151670 10001 ms_tear_S2_seed10001 &
paste2 151673 151674 10001 ms_tear_S3_seed10001 &
wait
paste2 151669 151670 10002 ms_tear_S2_seed10002 &
paste2 151673 151674 10002 ms_tear_S3_seed10002 &
wait

# --- STalign: 2 runs in parallel (niter 2000) ---
stalign 151669 151670 _S2 &
stalign 151673 151674 _S3 &
wait

# --- Sutura multi-seed held-out eval (eval-only, reuses trained checkpoints) ---
log "=== running Sutura multi-seed held-out eval ==="
if $PY validation/multiseed_lodo.py >> "$LOG" 2>&1; then log "OK   sutura_multiseed_lodo"; else log "FAIL sutura eval (exit $?)"; fi

FAILS=$(grep -c "FAIL" "$LOG")
log "=== MS-LODO batch COMPLETE ($FAILS failures) ==="
echo "ms-lodo finished $(date -u) with $FAILS failures" > "$DONE"
