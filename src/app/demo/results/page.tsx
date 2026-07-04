"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Check, RotateCcw, Move3d, Layers2, Sparkles } from "lucide-react";

import { Logo } from "@/components/logo";
import { isAuthed } from "@/lib/demoAuth";
import { getDataset, currentDatasetId, type DemoDataset } from "@/lib/demoDatasets";
import { addRun, type Run } from "@/lib/demoRuns";
import { getSettings } from "@/lib/demoSettings";
import ReportDownload from "@/components/demo/ReportDownload";
import AnalysisAssistant from "@/components/demo/AnalysisAssistant";

// 3D viewer is client-only (three.js) — never server-render it.
const TissueStack3D = dynamic(() => import("./TissueStack3D"), { ssr: false });

const PITCH_PX = 137; // one Visium spot pitch
const MAXERR = 900;

const WHY = [
  "PASTE2 uses optimal transport, which assumes near-isometric preservation of within-slice distances. Tears violate this.",
  "STalign uses LDDMM diffeomorphic mapping. By construction, diffeomorphisms cannot change topology, so they cannot represent a tear.",
  "GPSA learns a globally smooth Gaussian-process warp. It averages over the discontinuity.",
  "Sutura uses a supervised graph cross-attention model with no smoothness prior. It handles tears directly by learning correspondences from data.",
];

export default function DemoResultsPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [bars, setBars] = useState(false);
  // Start unaligned, then auto-heal to aligned shortly after load — the "wow".
  const [aligned, setAligned] = useState(false);
  const [ds, setDs] = useState<DemoDataset | null>(null);
  const [run, setRun] = useState<Run | null>(null);

  useEffect(() => {
    if (!isAuthed()) {
      router.replace("/demo/login");
      return;
    }
    const dataset = getDataset(currentDatasetId());
    setDs(dataset);

    // Build the Run for this view. If the dashboard flagged a fresh alignment,
    // persist it to the run history; otherwise this is a re-view — synthesize a
    // (non-persisted) run object just for the report download.
    let pend: { datasetId?: string; params?: Run["params"] } | null = null;
    try {
      const raw = window.sessionStorage.getItem("sutura_pending_run");
      if (raw) pend = JSON.parse(raw);
      window.sessionStorage.removeItem("sutura_pending_run");
    } catch {
      /* ignore */
    }
    const params = pend?.params ?? getSettings().params;
    const base = {
      datasetId: dataset.id,
      datasetName: dataset.name,
      sections: dataset.sections,
      medianErrorPx: dataset.suturaPx,
      spots: dataset.spotsRegistered,
      coverage: dataset.coverage,
      status: "Complete" as const,
      params,
    };
    if (pend && pend.datasetId === dataset.id) {
      setRun(addRun(base));
    } else {
      setRun({ ...base, id: "current", timestamp: Date.now() });
    }
    setReady(true);
  }, [router]);

  useEffect(() => {
    if (!ready) return;
    const t1 = window.setTimeout(() => setBars(true), 200);
    const t2 = window.setTimeout(() => setAligned(true), 1300);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [ready]);

  if (!ready || !ds) return <div className="min-h-screen bg-[#f7f6fb]" />;

  const ratio = (ds.paste2Px / ds.suturaPx).toFixed(1);

  return (
    <main className="relative flex min-h-screen flex-col items-center px-6 py-12">
      <div className="absolute inset-0 -z-10 h-full w-full bg-[#f7f6fb] [background:radial-gradient(125%_125%_at_50%_10%,#f7f6fb_45%,#cdc4f2_100%)]" />

      <div className="w-full max-w-4xl">
        <div className="flex flex-col items-center text-center">
          <Logo size={30} withWordmark className="mb-6" />
          <div className="inline-flex items-center gap-2 rounded-full bg-[#efeaff] px-3 py-1 text-[12px] font-normal text-[#6633ee]">
            <Check className="h-3.5 w-3.5" strokeWidth={3} />
            Alignment complete
          </div>
          <h1 className="mt-4 text-2xl font-light tracking-tight text-foreground sm:text-3xl">
            {ds.name} aligned volume
          </h1>
          <p className="mt-2 max-w-xl text-sm font-light leading-relaxed text-muted-foreground">
            {ds.sections} sections registered into a single 3D volume. Sutura recovers
            the true tissue geometry straight through the tear, staying below one
            spot pitch where optimal-transport pipelines drift.
          </p>
        </div>

        {/* 3D stacked tissue block + before/after toggle */}
        <div className="mt-8 overflow-hidden rounded-2xl border border-border bg-white">
          {/* Toggle */}
          <div className="flex flex-col items-center gap-2 border-b border-border px-4 py-4 sm:flex-row sm:justify-between">
            <div className="text-[13px] font-light text-muted-foreground">
              {aligned ? (
                <span className="inline-flex items-center gap-1.5 text-[#6633ee]">
                  <Sparkles className="h-3.5 w-3.5" strokeWidth={1.8} /> Sutura-aligned volume
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5">
                  <Layers2 className="h-3.5 w-3.5" strokeWidth={1.8} /> Raw input — misaligned at the tear
                </span>
              )}
            </div>
            <div className="inline-flex rounded-full border border-border bg-[#f7f6fb] p-1 text-[13.5px] font-normal">
              <button
                type="button"
                onClick={() => setAligned(false)}
                aria-pressed={!aligned}
                className={
                  "rounded-full px-4 py-1.5 transition-colors " +
                  (!aligned ? "bg-foreground text-white shadow-sm" : "text-muted-foreground hover:text-foreground")
                }
              >
                Unaligned
              </button>
              <button
                type="button"
                onClick={() => setAligned(true)}
                aria-pressed={aligned}
                className={
                  "rounded-full px-4 py-1.5 transition-colors " +
                  (aligned ? "bg-[#6633ee] text-white shadow-sm" : "text-muted-foreground hover:text-foreground")
                }
              >
                Sutura-aligned
              </button>
            </div>
          </div>

          <div className="relative h-[460px] w-full [background:radial-gradient(120%_120%_at_50%_0%,#faf9ff_0%,#ffffff_60%)]">
            <TissueStack3D src={ds.stack} aligned={aligned} />
            <div className="pointer-events-none absolute left-4 top-3.5 flex items-center gap-1.5 text-[11px] font-light uppercase tracking-[0.14em] text-[#6633ee]">
              <Move3d className="h-3.5 w-3.5" strokeWidth={1.8} />
              {ds.sections} · drag to rotate · scroll to zoom
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border px-4 py-3">
            <span className="text-[12px] font-light text-muted-foreground">{ds.classLabel}</span>
            {ds.regions.map((r) => (
              <span key={r.label} className="inline-flex items-center gap-1.5 text-[12px] font-light text-foreground">
                <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: r.color }} />
                {r.label}
              </span>
            ))}
          </div>
        </div>

        {/* Metrics */}
        <div className="mt-4 grid gap-4 sm:grid-cols-[1.4fr_1fr]">
          <div className="rounded-2xl border border-[#e3dbff] bg-gradient-to-b from-[#efeaff] to-white p-6">
            <div className="text-[13px] font-light tracking-wide text-muted-foreground">
              SUTURA · median registration error
            </div>
            <div className="mt-1 text-[44px] font-light leading-none text-[#6633ee]">
              {ds.suturaPx}
              <span className="ml-1.5 text-lg font-light text-muted-foreground">px</span>
            </div>
            <div className="mt-2 text-[12.5px] font-light text-muted-foreground">
              Below one spot pitch ({PITCH_PX} px) — sub-spot accuracy.
            </div>
            <div className="mt-5 space-y-2.5">
              <BarRow label="Sutura" value={ds.suturaPx} width={bars ? (ds.suturaPx / MAXERR) * 100 : 0} color="#6633ee" strong />
              <BarRow label="PASTE2" value={ds.paste2Px} width={bars ? (ds.paste2Px / MAXERR) * 100 : 0} color="#c9c9d2" />
            </div>
          </div>

          <div className="flex flex-col gap-4">
            <div className="rounded-2xl border border-border bg-white p-6">
              <div className="text-[13px] font-light text-muted-foreground">vs. PASTE2 (optimal transport)</div>
              <div className="mt-1 text-[44px] font-light leading-none text-foreground">
                {ratio}
                <span className="ml-1 text-lg font-light text-muted-foreground">×</span>
              </div>
              <div className="mt-2 text-[12.5px] font-light text-muted-foreground">
                more accurate at this tear ({ds.paste2Px} px).
              </div>
            </div>
            <div className="rounded-2xl border border-border bg-white p-6">
              <div className="text-[13px] font-light text-muted-foreground">Spots registered</div>
              <div className="mt-1 text-[44px] font-light leading-none text-foreground">{ds.spotsRegistered}</div>
            </div>
          </div>
        </div>

        {/* Benchmark comparison */}
        <div className="mt-4 overflow-hidden rounded-2xl border border-border bg-white">
          <div className="border-b border-border px-6 py-4">
            <h2 className="text-[15px] font-normal text-foreground">Benchmark comparison</h2>
            <p className="mt-0.5 text-[12.5px] font-light text-muted-foreground">
              {ds.name} · torn-warp regime, array-bridge ground truth.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-border text-[12px] font-light text-muted-foreground">
                  <th className="px-6 py-2.5 font-light">Method</th>
                  <th className="px-6 py-2.5 text-right font-light">Median error</th>
                  <th className="px-6 py-2.5 text-right font-light">90th %ile</th>
                  <th className="px-6 py-2.5 text-right font-light">{ds.classLabel} acc.</th>
                </tr>
              </thead>
              <tbody>
                {ds.benchmark.map((row) => (
                  <tr key={row.method} className={"border-b border-border/60 last:border-0 " + (row.strong ? "bg-[#efeaff]/50" : "")}>
                    <td className={"px-6 py-3 " + (row.strong ? "font-normal text-[#6633ee]" : "font-light text-foreground")}>{row.method}</td>
                    <td className={"px-6 py-3 text-right tabular-nums " + (row.strong ? "font-normal text-[#6633ee]" : "font-light text-foreground")}>{row.median}</td>
                    <td className="px-6 py-3 text-right tabular-nums font-light text-muted-foreground">{row.p90}</td>
                    <td className="px-6 py-3 text-right tabular-nums font-light text-muted-foreground">{row.acc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Why Sutura wins */}
        <div className="mt-4 rounded-2xl border border-border bg-white p-6 sm:p-7">
          <h2 className="text-[15px] font-normal text-foreground">Why Sutura succeeds where others fail</h2>
          <ul className="mt-4 space-y-3">
            {WHY.map((w, i) => (
              <li key={i} className="flex gap-3 text-[13.5px] font-light leading-relaxed text-muted-foreground">
                <span className={"mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full " + (i === WHY.length - 1 ? "bg-[#6633ee]" : "bg-[#c9c9d2]")} />
                <span className={i === WHY.length - 1 ? "text-foreground" : undefined}>{w}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Region / layer breakdown */}
        <div className="mt-4 rounded-2xl border border-border bg-white p-6 sm:p-7">
          <h2 className="text-[15px] font-normal text-foreground">{ds.classLabel} breakdown</h2>
          <div className="mt-4 divide-y divide-border/60">
            <div className="flex items-center gap-4 pb-2 text-[12px] font-light text-muted-foreground">
              <span className="flex-1">{ds.classLabel}</span>
              <span className="w-24 text-right">Spots</span>
              <span className="w-28 text-right">Accuracy</span>
            </div>
            {ds.regions.map((r) => (
              <div key={r.label} className="flex items-center gap-4 py-2.5 text-[13.5px]">
                <span className="flex flex-1 items-center gap-2.5">
                  <i className="inline-block h-3 w-3 rounded-full" style={{ background: r.color }} />
                  <span className="font-normal text-foreground">{r.label}</span>
                </span>
                <span className="w-24 text-right tabular-nums font-light text-muted-foreground">{r.count}</span>
                <span className="w-28 text-right tabular-nums font-normal text-foreground">{r.acc}</span>
              </div>
            ))}
          </div>
          <p className="mt-4 text-[12.5px] font-light leading-relaxed text-muted-foreground">
            Sutura preserves {ds.classLabel.toLowerCase()} boundaries better than any smoothness-based method.
          </p>
        </div>

        {/* Analysis assistant — grounded one-liner, full analysis, and Q&A */}
        {run && <AnalysisAssistant ds={ds} run={run} />}

        {/* Export report */}
        {run && (
          <div className="mt-4 flex flex-col items-start justify-between gap-3 rounded-2xl border border-border bg-white p-6 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-[15px] font-normal text-foreground">Export report</h2>
              <p className="mt-0.5 text-[12.5px] font-light text-muted-foreground">
                Metrics, per-{ds.classLabel.toLowerCase()} breakdown, and aligned coordinates.
              </p>
            </div>
            <ReportDownload run={run} />
          </div>
        )}

        {/* Actions */}
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <button
            type="button"
            onClick={() => router.push("/demo/dashboard")}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-white px-6 py-3 text-[15px] font-normal text-foreground transition-colors hover:bg-secondary"
          >
            <RotateCcw className="h-4 w-4" strokeWidth={1.8} />
            Back to datasets
          </button>
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 rounded-full bg-[#6633ee] px-7 py-3 text-[15px] font-normal text-white shadow-sm shadow-[#6633ee]/25 transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0] hover:shadow-lg hover:shadow-[#6633ee]/30"
          >
            Book a demo →
          </Link>
        </div>

        <p className="mt-6 text-center text-[12px] font-light leading-relaxed text-muted-foreground">
          Median error values for DLPFC are measured results from Sutura&rsquo;s internal
          benchmark (array-bridge ground truth, torn-warp regime). Breast and kidney
          datasets use synthetic demo data. One spot pitch = {PITCH_PX} px.
        </p>
        <p className="mx-auto mt-3 max-w-2xl text-center text-[11.5px] font-light leading-relaxed text-muted-foreground/80">
          Method described in: Maniar R, Lee S, Lee SS. Tissue tearing degrades
          optimal-transport and diffeomorphic registration of spatial
          transcriptomics. bioRxiv 2026 (under screening).
        </p>
      </div>
    </main>
  );
}

function BarRow({
  label,
  value,
  width,
  color,
  strong,
}: {
  label: string;
  value: number;
  width: number;
  color: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center gap-3 text-[12.5px]">
      <span className="w-14 shrink-0 font-light text-muted-foreground">{label}</span>
      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#f0f0f3]">
        <div className="h-full rounded-full transition-[width] duration-700 ease-out" style={{ width: `${width}%`, background: color }} />
      </div>
      <span className={"w-12 shrink-0 text-right tabular-nums " + (strong ? "font-normal text-[#6633ee]" : "font-light text-muted-foreground")}>
        {value} px
      </span>
    </div>
  );
}
