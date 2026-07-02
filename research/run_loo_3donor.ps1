# ============================================================================
# Sutura — 3-donor leave-one-out, run end-to-end and unattended.
#
# Fixes the single-donor LOO generalization failure (RESUME.md 2026-06-22) by
# training the shared encoder on TWO donors and evaluating on the held-out third,
# under two feature-standardization modes:
#   global   — training-pooled stats (the diagnosed failure mode; control)
#   perslice — per-slice standardization (batch-robust; the attempted fix)
#
# 3 folds x 2 modes = 6 training runs, + PASTE2 baseline on subj3 (subj1/subj2
# baselines already exist). Each step is logged; a DONE marker is written last so
# completion is detectable. Steps are isolated (one failure does not abort the
# rest). Sequential to avoid CPU/memory contention on this box.
# ============================================================================
$ErrorActionPreference = "Continue"
# Run from the script's own folder so relative paths (.venv, results\) resolve
# even when launched detached (Task Scheduler starts in system32).
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$py = ".\.venv\Scripts\python.exe"
$log = "results\loo3_run.log"
$done = "results\loo3_DONE.txt"
Remove-Item $done -ErrorAction SilentlyContinue

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

# one pair per donor
$S1 = "151507/151508"   # subject 1
$S2 = "151669/151670"   # subject 2
$S3 = "151673/151674"   # subject 3

# fold = (held-out tag, test pair, training pairs)
$folds = @(
    @{ tag = "S1"; test = $S1; train = "$S2,$S3" },
    @{ tag = "S2"; test = $S2; train = "$S1,$S3" },
    @{ tag = "S3"; test = $S3; train = "$S1,$S2" }
)
$modes = @("global", "perslice")

Log "=== Sutura 3-donor LOO START ==="
$failures = 0

foreach ($mode in $modes) {
    foreach ($f in $folds) {
        $out = "arca_loo3_{0}_test{1}" -f $mode, $f.tag
        Log "RUN mode=$mode fold=test$($f.tag)  train=[$($f.train)]  out=$out"
        # 2 training pairs -> 24 steps/epoch keeps ~1200 steps/pair (matches the
        # single-pair run's per-pair supervision); 100 epochs; eval grid + seed
        # match the PASTE2 sweep so curves overlay.
        & $py src\train_cross_loo.py --train `
            --train-pairs $f.train --test-pair $f.test `
            --feature-mode $mode --steps-per-epoch 24 --epochs 100 `
            --out $out *>> $log
        if ($LASTEXITCODE -ne 0) {
            Log "  !! FAILED (exit $LASTEXITCODE) mode=$mode fold=test$($f.tag)"
            $failures++
        } else {
            Log "  ok mode=$mode fold=test$($f.tag)"
        }
    }
}

# PASTE2 baseline on the subj3 held-out pair (subj1/subj2 already on disk).
Log "RUN PASTE2 baseline on subj3 ($S3), tear, pca/s0.99/alpha0.1"
& $py src\sweep_deformation.py --reference 151673 --sample 151674 --tear `
    --severities 0,1,2,3,4,6,8 --alpha 0.1 --dissimilarity pca --s 0.99 `
    --suffix cross_tear_subj3 *>> $log
if ($LASTEXITCODE -ne 0) { Log "  !! PASTE2 subj3 FAILED (exit $LASTEXITCODE)"; $failures++ }
else { Log "  ok PASTE2 subj3" }

Log "=== Sutura 3-donor LOO COMPLETE ($failures failures) ==="
"3-donor LOO finished at {0} with {1} failures." -f (Get-Date -Format "u"), $failures `
    | Out-File -FilePath $done -Encoding utf8
