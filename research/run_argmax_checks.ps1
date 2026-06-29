# Sutura argmax acceptance check + alpha=0.5 confirmatory (full spots, pca).
# 3 invocations x 2 severities (0,8) = 6 PASTE2 runs. Persists transport matrices.
$py = "$PSScriptRoot\.venv\Scripts\python.exe"
$sweep = "$PSScriptRoot\src\sweep_deformation.py"

Write-Output "=== [1/3] cross-TEAR sev 0,8 @ alpha=0.1 (load-bearing argmax) ==="
& $py $sweep --mode cross --tear --severities 0,8 --alpha 0.1 --dissimilarity pca --suffix argmax_tear

Write-Output "=== [2/3] cross-SMOOTH sev 0,8 @ alpha=0.1 (floor check) ==="
& $py $sweep --mode cross --severities 0,8 --alpha 0.1 --dissimilarity pca --suffix argmax_smooth

Write-Output "=== [3/3] cross-TEAR sev 0,8 @ alpha=0.5 (confirmatory) ==="
& $py $sweep --mode cross --tear --severities 0,8 --alpha 0.5 --dissimilarity pca --suffix tear_a0p5

Write-Output "=== argmax checks complete ==="
