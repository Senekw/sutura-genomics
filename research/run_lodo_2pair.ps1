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
# DETERMINISM. Thread counts are pinned to 6 (OMP + the BLAS backends) so the run
# is reproducible run-to-run and leaves 2 of 8 cores free (box stays responsive).
# Fixed seeds live in train_cross_loo.py (seed 0); CPU torch is not bit-exact, but
# pinned threads + fixed seeds give stable, reproducible curves.
#
# WATCHDOG. Each fold's training run is wrapped in a 45-min watchdog (est. ~30 min
# each): if one hangs it is force-killed (process tree) with exit 124 and the batch
# moves on, so a stuck run cannot trap the machine overnight. The 5-seed eval is
# similarly capped at 20 min.
#
# 3 folds x 2 feature modes (global, perslice) = 6 training runs, then a 5-seed
# eval puts 95% CIs on every held-out curve. PASTE2 held-out baselines for all
# three canonical pairs already exist -> no baseline recompute needed.
#
# Detached-safe (Set-Location $PSScriptRoot); per-run logging; failure-isolated;
# skips any checkpoint already on disk; writes lodo2_DONE.txt at the end.
#
# Usage (after approval):
#   .\run_lodo_2pair.ps1 -Py C:\Users\karti\arca\.venv\Scripts\python.exe
# ============================================================================
param([string]$Py = ".\.venv\Scripts\python.exe")

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
# Pin threads to 6 for determinism + 2 free cores (cap every backend, not just OMP,
# so the SVD basis-fit doesn't silently grab all 8 cores).
$env:PYTHONUTF8           = "1"
$env:OMP_NUM_THREADS      = "6"
$env:MKL_NUM_THREADS      = "6"
$env:OPENBLAS_NUM_THREADS = "6"
$env:NUMEXPR_NUM_THREADS  = "6"

$log  = "results\lodo2_run.log"
$done = "results\lodo2_DONE.txt"
Remove-Item $done -ErrorAction SilentlyContinue

function Log($msg) {
    "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg |
        Tee-Object -FilePath $log -Append
}

# Run $Py with $argList under a watchdog; fold child stdout/stderr into $log.
# Returns the child exit code, or 124 if the watchdog fired.
function Invoke-Watched($argList, $timeoutMs, $tag) {
    $fo = "results\_run.out"; $fe = "results\_run.err"
    $p = Start-Process -FilePath $Py -ArgumentList $argList -PassThru -NoNewWindow `
             -RedirectStandardOutput $fo -RedirectStandardError $fe
    if ($p.WaitForExit($timeoutMs)) {
        $code = $p.ExitCode
    } else {
        & taskkill /F /T /PID $p.Id 2>$null | Out-Null
        try { $p.WaitForExit() } catch {}
        $code = 124
        Log ("  !! WATCHDOG: killed {0} after {1} min (exit 124)" -f $tag, [int]($timeoutMs / 60000))
    }
    if (Test-Path $fo) { Get-Content $fo | Add-Content $log; Remove-Item $fo -ErrorAction SilentlyContinue }
    if (Test-Path $fe) { Get-Content $fe | Add-Content $log; Remove-Item $fe -ErrorAction SilentlyContinue }
    return $code
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

Log "=== Sutura 2-pair-per-donor LOO START (py=$Py, threads=6) ==="
$failures = 0
$stems = @()

foreach ($mode in $modes) {
    foreach ($f in $folds) {
        $out = "lodo2_{0}_held{1}" -f $mode, $f.tag
        $stems += $out
        if (Test-Path "results\$out.pt") { Log "skip (exists) $out"; continue }
        Log "RUN mode=$mode fold=test$($f.tag)  train=[$($f.train)]  out=$out (watchdog 45min)"
        # 4 training pairs -> 48 steps/epoch keeps ~1200 steps/pair (matches the
        # 1-pair run's per-pair supervision); eval grid + seed match the PASTE2 sweep.
        $argList = @(
            "src\train_cross_loo.py", "--train",
            "--train-pairs", $f.train, "--test-pair", $f.test,
            "--feature-mode", $mode, "--steps-per-epoch", "48", "--epochs", "100",
            "--out", $out
        )
        $code = Invoke-Watched $argList (45 * 60 * 1000) ("fold test$($f.tag)/$mode")
        if ($code -ne 0) {
            Log "  !! FAILED (exit $code) mode=$mode fold=test$($f.tag)"; $failures++
        } else { Log "  ok mode=$mode fold=test$($f.tag)" }
    }
}

# 5-seed eval -> 95% CIs on every held-out curve (no retrain; re-fits the shared
# SVD basis per fold deterministically and re-evaluates each checkpoint).
$stemList = ($stems -join ",")
Log "RUN multiseed eval (5 seeds) over: $stemList (watchdog 20min)"
$evalArgs = @(
    "validation\multiseed_lodo.py", "--stems", $stemList,
    "--out", "sutura_multiseed_lodo_2pair.csv"
)
$code = Invoke-Watched $evalArgs (20 * 60 * 1000) "multiseed-eval"
if ($code -ne 0) { Log "  !! multiseed eval FAILED (exit $code)"; $failures++ }
else { Log "  ok multiseed eval -> results\sutura_multiseed_lodo_2pair.csv" }

Log "=== Sutura 2-pair-per-donor LOO COMPLETE ($failures failures) ==="
"2-pair LOO finished at {0} with {1} failures." -f (Get-Date -Format "u"), $failures |
    Out-File -FilePath $done -Encoding utf8
