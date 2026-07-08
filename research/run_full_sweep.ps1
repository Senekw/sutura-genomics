# Sutura full deformation sweep — runs the three approved regimes sequentially
# (pca dissimilarity, full spots). Run AFTER the baseline finishes to avoid
# memory contention. Logs to results/.
$py = "$PSScriptRoot\.venv\Scripts\python.exe"
$sweep = "$PSScriptRoot\src\sweep_deformation.py"
$sev = "0,1,2,3,4,6,8"

Write-Output "=== [1/3] cross-mode smooth warp ==="
& $py $sweep --mode cross --severities $sev --dissimilarity pca --suffix cross

Write-Output "=== [2/3] cross-mode tear ==="
& $py $sweep --mode cross --severities $sev --dissimilarity pca --tear --suffix cross_tear

Write-Output "=== [3/3] self-mode smooth warp (control) ==="
& $py $sweep --mode self --severities $sev --dissimilarity pca --suffix self

Write-Output "=== full sweep complete ==="
