# ============================================================================
# Sutura — 2-PAIRS-PER-DONOR leave-one-out (expanded LODO).
#
# Tests RESUME.md lever (c): does giving each TRAINING donor a SECOND adjacent
# pair close the cross-donor generalization gap? The original 3-donor LOO
# (run_loo_3donor.ps1) trained on ONE pair per donor (2 training pairs/fold) and
# stayed 1080-1557 px on the unseen donor (1.9-3.0x PASTE2). Here each of the two
# training donors contributes BOTH its adjacent pairs (4 training pairs/fold).
#
# CONTROLLED COMPARISON. Per-pair supervision is held constant: the 1-pair run
# used 100 epochs x 24 steps = 2400 steps / 2 pairs = ~1200 steps/pair. With 4
# training pairs we use 100 epochs x 48 steps = 4800 steps / 4 pairs = ~1200
# steps/pair. So a change in the held-out curve reflects MORE PAIRS, not more
# gradient. The held-out TEST pair is each donor's canonical first pair, identical
# to the 1-pair run, so the new numbers drop straight onto the old comparison.
#
# 3 folds x 2 feature modes (global, perslice) = 6 training runs, then a 5-seed
# eval (validation/multiseed_lodo.py --stems ...) puts 95% CIs on every held-out
# curve. PASTE2 held-out baselines for all three canonical pairs already exist
# (sweep_deformation_cross_tear*.csv) -> no baseline recompute needed.
#
# Detached-safe (Set-Location $PSScriptRoot); per-run logging; failure-isolated;
# skips any checkpoint already on disk; writes lodo2_DONE.txt at the end.
#
# Usage (after approval):
#   .\run_lodo_2pair.ps1                                   # uses .\.venv
#   .\run_lodo_2pair.ps1 -Py C:\Users\karti\arca\.venv\Scripts\python.exe
# ============================================================================
param([string]$Py = ".\.venv\Scripts\python.exe")

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$log  = "results\lodo2_run.log"
$done = "results\lodo2_DONE.txt"
Remove-Item $done -ErrorAction SilentlyContinue

function Log($msg) {
    "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg |
        Tee-Object -FilePath $log -Append
}

# two adjacent pairs per donor (all 12 DLPFC slices)
$S1a = "151507/151508"; $S1b = "151509/151510"   # Br5292
$S2a = "151669/151670"; $S2b = "151671/151672"   # Br5595
$S3a = "151673/151674"; $S3b = "151675/151676"   # Br8100

# fold = (held-out tag, TEST pair = held donor's canonical pair, 4 TRAIN pairs)
$folds = @(
    @{ tag = "S1"; test = $S1a; train = "$S2a,$S2b,$S3a,$S3b" },
    @{ tag = "S2"; test = $S2a; train = "$S1a,$S1b,$S3a,$S3b" },
    @{ tag = "S3"; test = $S3a; train = "$S1a,$S1b,$S2a,$S2b" }
)
$modes = @("global", "perslice")

Log "=== Sutura 2-pair-per-donor LOO START (py=$Py) ==="
$failures = 0
$stems = @()

foreach ($mode in $modes) {
    foreach ($f in $folds) {
        $out = "lodo2_{0}_held{1}" -f $mode, $f.tag
        $stems += $out
        if (Test-Path "results\$out.pt") { Log "skip (exists) $out"; continue }
        Log "RUN mode=$mode fold=test$($f.tag)  train=[$($f.train)]  out=$out"
        # 4 training pairs -> 48 steps/epoch keeps ~1200 steps/pair (matches the
        # 1-pair run's per-pair supervision); eval grid + seed match the PASTE2 sweep.
        & $Py src\train_cross_loo.py --train `
            --train-pairs $f.train --test-pair $f.test `
            --feature-mode $mode --steps-per-epoch 48 --epochs 100 `
            --out $out *>> $log
        if ($LASTEXITCODE -ne 0) {
            Log "  !! FAILED (exit $LASTEXITCODE) mode=$mode fold=test$($f.tag)"; $failures++
        } else { Log "  ok mode=$mode fold=test$($f.tag)" }
    }
}

# 5-seed eval -> 95% CIs on every held-out curve (no retrain; re-fits the shared
# SVD basis per fold deterministically and re-evaluates each checkpoint).
$stemList = ($stems -join ",")
Log "RUN multiseed eval (5 seeds) over: $stemList"
& $Py validation\multiseed_lodo.py --stems $stemList `
    --out sutura_multiseed_lodo_2pair.csv *>> $log
if ($LASTEXITCODE -ne 0) { Log "  !! multiseed eval FAILED (exit $LASTEXITCODE)"; $failures++ }
else { Log "  ok multiseed eval -> results\sutura_multiseed_lodo_2pair.csv" }

Log "=== Sutura 2-pair-per-donor LOO COMPLETE ($failures failures) ==="
"2-pair LOO finished at {0} with {1} failures." -f (Get-Date -Format "u"), $failures |
    Out-File -FilePath $done -Encoding utf8
