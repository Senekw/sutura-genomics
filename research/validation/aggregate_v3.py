"""Aggregate items 1b/3/4 into the v3 numbers. Run with the venv python.
Output is the source of every figure in ABSTRACT_v3.md."""
import csv, numpy as np
from pathlib import Path
R = Path("/Users/seangplee/biostartup-main/results")
def rd(f): return {float(r['severity']): r for r in csv.DictReader(open(R/f))}

print("ITEM 1b — PASTE2 multi-seed cross-tear (151507/151508), seeds 0/9999/10000/10001/10002")
seeds=[0,9999,10000,10001,10002]
for sev in [0.0,4.0,8.0]:
    b=[float(rd(f"sweep_deformation_ms_tear_seed{s}.csv")[sev]['reg_err_median']) for s in seeds]
    a=[float(rd(f"sweep_deformation_ms_tear_seed{s}.csv")[sev]['reg_err_median_argmax']) for s in seeds]
    c=[float(rd(f"sweep_deformation_ms_tear_seed{s}.csv")[sev]['paste2_acc']) for s in seeds]
    f=lambda x:(np.mean(x),1.96*np.std(x,ddof=1)/np.sqrt(len(x)))
    print(f"  sev{sev:.0f}: bary {f(b)[0]:.1f}+/-{f(b)[1]:.1f}  argmax {f(a)[0]:.1f}+/-{f(a)[1]:.1f}  acc {f(c)[0]*100:.1f}+/-{f(c)[1]*100:.1f}%")

print("\nITEM 3 — leave-one-donor-out (Sutura held-out median px, tear sev0->sev8)")
folds={"Br5292":"heldBr5292","Br5595":"heldBr5595","Br8100":"heldBr8100"}
paste={"Br5292":("sweep_deformation_cross_tear.csv","sweep_deformation_argmax_tear.csv"),
       "Br5595":("sweep_deformation_cross_tear_loo.csv",None),
       "Br8100":("sweep_deformation_tear_Br8100.csv",None)}
for name,tag in folds.items():
    g=rd(f"lodo_global_{tag}_test_curve.csv"); p=rd(f"lodo_perslice_{tag}_test_curve.csv")
    pf,af=paste[name]; pb=rd(pf)
    pa=pb if 'reg_err_median_argmax' in pb[0.0] else rd(af)
    print(f"  {name}: global {float(g[0.0]['reg_err_median']):.0f}->{float(g[8.0]['reg_err_median']):.0f}  "
          f"perslice {float(p[0.0]['reg_err_median']):.0f}->{float(p[8.0]['reg_err_median']):.0f}  | "
          f"PASTE2 bary {float(pb[0.0]['reg_err_median']):.0f}->{float(pb[8.0]['reg_err_median']):.0f}  "
          f"argmax {float(pa[0.0]['reg_err_median_argmax']):.0f}->{float(pa[8.0]['reg_err_median_argmax']):.0f}")

print("\nITEM 4 — magnitude-matched smooth control (151507/151508)")
m=rd("sweep_deformation_magmatch_smooth.csv")
for sev in sorted(m):
    d=m[sev]
    print(f"  smooth sev{sev:.0f}: mean_disp {float(d['mean_disp_px']):.0f}px  bary {float(d['reg_err_median']):.0f}  "
          f"argmax {float(d['reg_err_median_argmax']):.0f}  acc {float(d['paste2_acc'])*100:.1f}%")
t=rd("sweep_deformation_ms_tear_seed0.csv")[8.0]
print(f"  TEAR sev8 (ref): mean_disp {float(t['mean_disp_px']):.0f}px  bary {float(t['reg_err_median']):.0f}  "
      f"argmax {float(t['reg_err_median_argmax']):.0f}  acc {float(t['paste2_acc'])*100:.1f}%")
