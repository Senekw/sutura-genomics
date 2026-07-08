# ============================================================================
# Sutura — contrastive correspondence loss, 3-donor LOO matrix (option a).
#
# Tests whether a donor-invariant InfoNCE-style match loss makes correspondence
# transfer to unseen donors. Matrix (feature mode = global, fixed):
#   lambda 0    : 3 folds x 1 readout  (baseline; training is readout-independent
#                 at lambda=0, but we still log held-out match_top1 as the control)
#   lambda 0.5  : 3 folds x {cosine, attn}
#   lambda 2.0  : 3 folds x {cosine, attn}
#   = 15 training runs. PASTE2 baselines (subj1/2/3) already on disk.
#
# Detached-safe (Set-Location $PSScriptRoot); per-run logging; failure-isolated;
# writes loo_ctr_DONE.txt at the end so completion is detectable.
# ============================================================================
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$py = ".\.venv\Scripts\python.exe"
$log = "results\loo_ctr_run.log"
$done = "results\loo_ctr_DONE.txt"
Remove-Item $done -ErrorAction SilentlyContinue

function Log($m) {
    "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m |
        Tee-Object -FilePath $log -Append
}

$S1 = "151507/151508"; $S2 = "151669/151670"; $S3 = "151673/151674"
$folds = @(
    @{ tag = "S1"; test = $S1; train = "$S2,$S3" },
    @{ tag = "S2"; test = $S2; train = "$S1,$S3" },
    @{ tag = "S3"; test = $S3; train = "$S1,$S2" }
)
# (lambda, lamtag, readouts) — lambda 0 needs only one readout (no contrastive grad)
$sweep = @(
    @{ lam = 0.0; tag = "0";   ros = @("cosine") },
    @{ lam = 0.5; tag = "0p5"; ros = @("cosine", "attn") },
    @{ lam = 2.0; tag = "2p0"; ros = @("cosine", "attn") }
)

Log "=== Sutura contrastive LOO matrix START ==="
$fail = 0; $n = 0
foreach ($f in $folds) {
    foreach ($s in $sweep) {
        foreach ($ro in $s.ros) {
            $out = "arca_ctr_{0}_l{1}_test{2}" -f $ro, $s.tag, $f.tag
            $n++
            if (Test-Path "results\$out.pt") { Log "RUN $n/15  skip (exists) $out"; continue }
            Log "RUN $n/15  fold=test$($f.tag)  readout=$ro  lambda=$($s.lam)  out=$out"
            & $py src\train_cross_contrastive.py --train `
                --train-pairs $f.train --test-pair $f.test `
                --feature-mode global --readout $ro --lambda-contrastive $s.lam `
                --temp 0.07 --target-sigma 1.0 --epochs 100 --steps-per-epoch 24 `
                --out $out *>> $log
            if ($LASTEXITCODE -ne 0) { Log "  !! FAILED ($out) exit $LASTEXITCODE"; $fail++ }
            else { Log "  ok $out" }
        }
    }
}
Log "=== Sutura contrastive LOO matrix COMPLETE ($fail failures) ==="
"contrastive LOO matrix finished {0} with {1} failures." -f (Get-Date -Format "u"), $fail |
    Out-File -FilePath $done -Encoding utf8
