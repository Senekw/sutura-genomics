# ============================================================================
# Sutura - 2-pair LODO PHASE 2: recover the watchdog-killed global_heldS3 fold,
# then run the full 5-seed eval over all 6 checkpoints.
#
# global_heldS3 was killed by the 90-min watchdog (it ran long because a
# visualization job overlapped its window). This script:
#   1. WAITS (light polling) for the main run to finish - never runs training in
#      parallel with it (that contention is what killed the fold in the first place).
#   2. Re-runs global_heldS3 SOLO (same args/seeds as the other global folds).
#   3. Runs validation/multiseed_lodo.py over ALL 6 stems -> the CSV with 95% CIs.
#
# Detached-safe scheduled task; thread-pinned to 6 (matches the other folds for
# determinism); writes lodo2_phase2_DONE.txt at the end.
# ============================================================================
param([string]$Py = "C:\Users\karti\arca\.venv\Scripts\python.exe")

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:OMP_NUM_THREADS = "6"; $env:MKL_NUM_THREADS = "6"
$env:OPENBLAS_NUM_THREADS = "6"; $env:NUMEXPR_NUM_THREADS = "6"

$log = "results\lodo2_phase2.log"
$done = "results\lodo2_phase2_DONE.txt"
Remove-Item $done -ErrorAction SilentlyContinue

function Log($m) {
    "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m |
        Tee-Object -FilePath $log -Append
}

function Invoke-Watched($argList, $timeoutMs, $tag) {
    $fo = "results\_p2.out"; $fe = "results\_p2.err"
    $p = Start-Process -FilePath $Py -ArgumentList $argList -PassThru -NoNewWindow `
             -RedirectStandardOutput $fo -RedirectStandardError $fe
    if ($p.WaitForExit($timeoutMs)) { $code = $p.ExitCode }
    else {
        & taskkill /F /T /PID $p.Id 2>$null | Out-Null
        try { $p.WaitForExit() } catch {}
        $code = 124
        Log ("  !! WATCHDOG: killed {0} after {1} min (exit 124)" -f $tag, [int]($timeoutMs / 60000))
    }
    if (Test-Path $fo) { Get-Content $fo | Add-Content $log; Remove-Item $fo -ErrorAction SilentlyContinue }
    if (Test-Path $fe) { Get-Content $fe | Add-Content $log; Remove-Item $fe -ErrorAction SilentlyContinue }
    return $code
}

Log "=== PHASE 2 START ==="

# 1) WAIT for the main run to finish (DONE marker, or main task no longer Running).
#    Light polling only - no training runs while the main task is active.
$waited = 0
while ($true) {
    if (Test-Path "results\lodo2_DONE.txt") { Log "main run DONE marker seen"; break }
    $st = (Get-ScheduledTask -TaskName Sutura_LODO2pair -ErrorAction SilentlyContinue).State
    if ($st -ne "Running") { Log "main task state=$st, no DONE - grace wait then proceed"; Start-Sleep -Seconds 60; break }
    Start-Sleep -Seconds 120; $waited += 2
    if ($waited -ge 300) { Log "wait cap (5h) hit - proceeding"; break }
}
# Belt-and-suspenders: make sure no training worker is still alive before we start.
$guard = 0
while ($guard -lt 20) {
    $busy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
              Where-Object { $_.CommandLine -like '*train_cross_loo*' })
    if ($busy.Count -eq 0) { break }
    Log "  waiting for $($busy.Count) training worker(s) to exit before phase 2 ..."
    Start-Sleep -Seconds 60; $guard++
}
$have = (Get-ChildItem "results\lodo2_*.pt" -ErrorAction SilentlyContinue).Count
Log "main run finished; checkpoints present: $have of 6"

# 2) Re-run global_heldS3 SOLO (skip if it somehow exists).
if (Test-Path "results\lodo2_global_heldS3.pt") {
    Log "global_heldS3 already present - skipping rerun"
} else {
    Log "RUN rerun global_heldS3 SOLO (watchdog 90min)"
    $argList = @(
        "src\train_cross_loo.py", "--train",
        "--train-pairs", "151507/151508,151509/151510,151669/151670,151671/151672",
        "--test-pair", "151673/151674",
        "--feature-mode", "global", "--steps-per-epoch", "48", "--epochs", "100",
        "--out", "lodo2_global_heldS3"
    )
    $code = Invoke-Watched $argList (90 * 60 * 1000) "rerun-global-heldS3"
    Log "rerun exit=$code; checkpoint present: $(Test-Path 'results\lodo2_global_heldS3.pt')"
}

# 3) Full 5-seed eval over ALL 6 stems -> the CSV with 95% CIs.
$stems = "lodo2_global_heldS1,lodo2_perslice_heldS1,lodo2_global_heldS2,lodo2_perslice_heldS2,lodo2_global_heldS3,lodo2_perslice_heldS3"
$present = (Get-ChildItem "results\lodo2_*.pt" -ErrorAction SilentlyContinue).Count
Log "RUN full 5-seed eval over all 6 stems; checkpoints on disk: $present; watchdog 30min"
$evalArgs = @("validation\multiseed_lodo.py", "--stems", $stems, "--out", "sutura_multiseed_lodo_2pair.csv")
$code = Invoke-Watched $evalArgs (30 * 60 * 1000) "eval-6"
Log "eval exit=$code; CSV present: $(Test-Path 'results\sutura_multiseed_lodo_2pair.csv')"

Log "=== PHASE 2 COMPLETE ==="
$nck = (Get-ChildItem "results\lodo2_*.pt" -ErrorAction SilentlyContinue).Count
$csvOk = Test-Path "results\sutura_multiseed_lodo_2pair.csv"
$stamp = Get-Date -Format "u"
"phase2 finished at $stamp; checkpoints=$nck/6; csv=$csvOk" | Out-File -FilePath $done -Encoding utf8
