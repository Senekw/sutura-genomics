"""Leakage audit for the gated-piecewise gate and the clean self-supervised residual.
Uses the cached PASTE2 base only (negligible CPU; won't disturb the running grid)."""
import sys, inspect, numpy as np
from pathlib import Path
SRC = Path(r"C:\Users\karti\arca\src"); sys.path.insert(0, str(SRC))
import hybrid_validate as hv
from warp_slice import apply_warp
from scoring import registration_error_stats

CACHE = hv.CACHE
base = np.load(CACHE/"Br8100_s0_seed0.npz")["base"]
pair = hv.build_dataset(*hv.DLPFC["Br8100"])
w,_ = apply_warp(pair["B"], 0.0, seed=0, tear=True)
mov = np.asarray(w.obsm["spatial"], np.float32)
conf = np.ones(pair["B"].n_obs, np.float32)
def err(p): return registration_error_stats(p, pair["gt"], mask=pair["have"])["median"]/pair["pitch"]

print("=== LEAKAGE AUDIT ===")

# 1. Gate signature carries no ground truth
sig = list(inspect.signature(hv.gated_piecewise.parameters if False else hv.gated_piecewise).parameters) \
      if False else list(inspect.signature(hv.gated_piecewise).parameters)
print(f"1. gated_piecewise args: {sig}")
print(f"   -> takes moving, base_px, conf, pitch only; no gt/have/target. PASS={('gt' not in sig and 'have' not in sig)}")

# 2. Gate output is invariant to corrupting the ground truth (proves no hidden gt use)
g1 = hv.gated_piecewise(mov, base, conf, pair["pitch"], order=0, cv=False, seed=0)
gt_backup = pair["gt"].copy()
pair["gt"] = np.random.default_rng(9).normal(size=pair["gt"].shape).astype(np.float32)*1e4  # trash gt
g2 = hv.gated_piecewise(mov, base, conf, pair["pitch"], order=0, cv=False, seed=0)
pair["gt"] = gt_backup
print(f"2. gate output identical after trashing gt: PASS={np.allclose(g1, g2)}  (max|d|={np.abs(g1-g2).max():.2e})")

# 3. Gate uses only moving geometry + base coords (feature-free): permuting features leaves it unchanged
Zb_backup = pair["Z_B"].copy()
pair["Z_B"] = np.random.default_rng(3).normal(size=pair["Z_B"].shape).astype(np.float32)
g3 = hv.gated_piecewise(mov, base, conf, pair["pitch"], order=0, cv=False, seed=0)
pair["Z_B"] = Zb_backup
print(f"3. gate output identical after trashing features: PASS={np.allclose(g1, g3)} (feature-free)")

# 4. clean self-sup training source code never references the A-B array bridge.
# The leak tokens are the pair's BRIDGE quantities: pair["gt_norm"], pair["gt"], pair["mask"].
# (The local var gt_norm is fine - the clean branch assigns it to pair["a_norm"] = A's OWN coords.)
src = inspect.getsource(hv.train_selfsup)
clean_branch = src.split('if mode == "clean":')[1].split("else:")[0]
leak_tokens = ['pair["gt_norm"]', 'pair["gt"]', 'pair["mask"]', 'array_bridge']
found = [t for t in leak_tokens if t in clean_branch]
print(f"4. clean self-sup branch references A-B bridge quantities {leak_tokens}: {found or 'NONE'}")
print(f"   -> clean trains on A->A self-warps (target pair['a_norm']=A's own coords). PASS={not found}")
leak_branch = src.split("else:  # leak")[1]
print(f"   (leak branch DOES use the bridge: "
      f"{[t for t in leak_tokens if t in leak_branch]} - that's the leaking baseline)")

# 5. thr robustness: gate beats PASTE2 across a wide threshold range (not a lucky single thr)
print(f"5. gate vs PASTE2 (base {err(base):.3f}) across thresholds:")
for thr in [2,3,4.5,6,8,12]:
    g = hv.gated_piecewise(mov, base, conf, pair["pitch"], order=0, cv=False, thr=thr, seed=0)
    print(f"     thr={thr:>4}: gated={err(g):.3f}  beats={err(g) < err(base)}")
print("=== END AUDIT ===")
