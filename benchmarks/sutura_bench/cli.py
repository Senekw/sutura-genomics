"""
Command-line entry point for the benchmark harness.

    python -m sutura_bench <command> [options]

Commands:
    list                    catalogue datasets (and methods) with metadata
    run                     run methods x datasets x severities x seeds -> CSV
    report                  leaderboard + plots from a results CSV
    save-reference          snapshot a run as the regression reference
    check                   compare a run against the stored reference
    reproduce               reproduce the headline PASTE2/gate/Sutura numbers

Run ``python -m sutura_bench <command> -h`` for per-command options. See
benchmarks/README.md for the full guide.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, datasets, methods, harness, report, regression
from .harness import RunConfig


# --------------------------------------------------------------------------- #
def _cmd_list(args):
    if args.methods:
        print("Methods:")
        for m in methods.all_methods():
            print(f"  {m.name:14s} [{m.kind:8s}] {m.description}")
        return
    cat = datasets.catalogue(refresh=args.refresh)
    print(f"{'dataset':16s} {'group':10s} {'regime':12s} {'avail':6s} "
          f"{'spots(ref/mov)':16s} {'bridge':7s} tissue")
    print("-" * 100)
    for r in cat:
        avail = "yes" if r.get("available") else "NO"
        spots = (f"{r.get('n_spots_ref','?')}/{r.get('n_spots_mov','?')}"
                 if r.get("available") else "-")
        bridge = (f"{r.get('bridge_coverage','?')}" if r.get("available") else "-")
        deg = " [DEGENERATE self-warp]" if r["regime"] == "self_warp" else ""
        print(f"{r['id']:16s} {r['group']:10s} {r['regime']:12s} {avail:6s} "
              f"{spots:16s} {bridge:7s} {r['tissue']}{deg}")
    print("\nreal_serial = honest cross-section (array-bridge GT); "
          "self_warp = degenerate (reported separately).")


def _resolve_datasets(arg: str) -> list[str]:
    if arg in ("suite", "", None):
        return [d.id for d in datasets.default_suite()]
    if arg == "dlpfc":
        return [d.id for d in datasets.available_specs(group="dlpfc")]
    if arg == "ood":
        return [d.id for d in datasets.available_specs(group="ood")]
    if arg == "self":
        return [d.id for d in datasets.available_specs(regime="self_warp")]
    if arg == "all":
        return [d.id for d in datasets.available_specs()]
    return [d.strip() for d in arg.split(",") if d.strip()]


def _cmd_run(args):
    ds = _resolve_datasets(args.datasets)
    ms = methods.names() if args.methods == "all" else \
        [m.strip() for m in args.methods.split(",") if m.strip()]
    seeds = [int(s) for s in str(args.seeds).split(",") if str(s).strip()]
    sevs = ([float(s) for s in args.severities.split(",")]
            if args.severities else None)
    cfg = RunConfig(datasets=ds, methods=ms, seeds=seeds, severities=sevs,
                    run_tag=args.tag, resume=not args.no_resume,
                    out_csv=Path(args.out) if args.out else None)
    out = harness.run(cfg)
    if not args.no_report:
        md = report.write_leaderboard(out, title=f"Benchmark: {args.tag}")
        png = report.plot_run(out)
        print(f"\nleaderboard -> {md}")
        if png:
            print(f"plots       -> {png}")


def _cmd_report(args):
    md = report.write_leaderboard(args.csv, out_md=args.out,
                                  title=args.title or f"Benchmark: {Path(args.csv).stem}")
    png = report.plot_run(args.csv)
    print(report.leaderboard_markdown(args.csv))
    print(f"leaderboard -> {md}")
    if png:
        print(f"plots       -> {png}")


def _cmd_save_reference(args):
    out = regression.save_reference(args.csv, out_json=args.out, note=args.note)
    ref = json.loads(Path(out).read_text())
    print(f"saved reference ({ref['n_cells']} cells) -> {out}")
    if ref["dlpfc_lodo"]:
        print("DLPFC-LODO means:")
        for m, v in sorted(ref["dlpfc_lodo"].items(), key=lambda kv: kv[1]):
            print(f"  {m:14s} {v:.3f}")


def _cmd_check(args):
    rep = regression.check(args.csv, ref_json=args.reference,
                           abs_tol=args.abs_tol, rel_tol=args.rel_tol)
    text = regression.format_report(rep)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.exit(0 if rep["passed"] else 1)


def _cmd_reproduce(args):
    from . import reproduce
    reproduce.main(quick=args.quick)


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sutura_bench",
                                description="Unified spatial-alignment benchmark harness.")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("list", help="catalogue datasets/methods")
    pl.add_argument("--methods", action="store_true", help="list methods instead of datasets")
    pl.add_argument("--refresh", action="store_true", help="re-introspect dataset files")
    pl.set_defaults(func=_cmd_list)

    pr = sub.add_parser("run", help="run the benchmark")
    pr.add_argument("--datasets", default="suite",
                    help="'suite'(default real-serial) | dlpfc | ood | self | all | comma list")
    pr.add_argument("--methods", default="paste2,gate_rigid,gate_affine",
                    help="'all' or comma list of method names")
    pr.add_argument("--seeds", default="0")
    pr.add_argument("--severities", default="", help="comma list; default per-dataset grid")
    pr.add_argument("--tag", default="run")
    pr.add_argument("--out", default="")
    pr.add_argument("--no-resume", action="store_true")
    pr.add_argument("--no-report", action="store_true")
    pr.set_defaults(func=_cmd_run)

    pp = sub.add_parser("report", help="leaderboard + plots from a CSV")
    pp.add_argument("csv")
    pp.add_argument("--out", default="")
    pp.add_argument("--title", default="")
    pp.set_defaults(func=_cmd_report)

    ps = sub.add_parser("save-reference", help="snapshot a run as the regression reference")
    ps.add_argument("csv")
    ps.add_argument("--out", default="")
    ps.add_argument("--note", default="")
    ps.set_defaults(func=_cmd_save_reference)

    pc = sub.add_parser("check", help="check a run against the stored reference")
    pc.add_argument("csv")
    pc.add_argument("--reference", default="")
    pc.add_argument("--abs-tol", type=float, default=regression.DEFAULT_ABS_TOL)
    pc.add_argument("--rel-tol", type=float, default=regression.DEFAULT_REL_TOL)
    pc.add_argument("--out", default="")
    pc.set_defaults(func=_cmd_check)

    pd_ = sub.add_parser("reproduce", help="reproduce the headline baseline numbers")
    pd_.add_argument("--quick", action="store_true", help="cached cells only (no PASTE2 solves)")
    pd_.set_defaults(func=_cmd_reproduce)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    # normalize empty-string optionals to None
    for k in ("out", "reference", "title"):
        if getattr(args, k, None) == "":
            setattr(args, k, None)
    args.func(args)


if __name__ == "__main__":
    main()
