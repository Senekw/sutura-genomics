"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Layers,
  UploadCloud,
  FileCheck2,
  AlertCircle,
  ChevronDown,
  Clock,
  CheckCircle2,
} from "lucide-react";

import Sidebar from "@/components/demo/Sidebar";
import { isAuthed } from "@/lib/demoAuth";
import { parseSpotCount, uploadH5ad, type UploadResult } from "@/lib/h5adUpload";
import { DATASETS, selectDataset, type DemoDataset } from "@/lib/demoDatasets";
import { getSettings } from "@/lib/demoSettings";
import { getRuns, formatWhen, type Run } from "@/lib/demoRuns";

const TOP_STATS = [
  ["12", "alignments run today"],
  ["4,384", "avg spots"],
  ["108 px", "avg error"],
];

type UploadPhase = "idle" | "reading" | "uploading" | "done" | "error";

export default function DemoDashboardPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [hoverId, setHoverId] = useState<string | null>(null);
  const [pinId, setPinId] = useState<string | null>(null);
  const [recent, setRecent] = useState<Run[]>([]);

  useEffect(() => {
    if (!isAuthed()) {
      router.replace("/demo/login");
      return;
    }
    setRecent(getRuns().slice(0, 3));
    setReady(true);
  }, [router]);

  const runDataset = (id: string) => {
    selectDataset(id);
    try {
      window.sessionStorage.setItem(
        "sutura_pending_run",
        JSON.stringify({ datasetId: id, params: getSettings().params })
      );
    } catch {
      /* ignore */
    }
    router.push("/demo/processing");
  };

  const openRun = (run: Run) => {
    if (run.status !== "Complete") return;
    selectDataset(run.datasetId);
    router.push("/demo/results");
  };

  const handleFile = async (file: File) => {
    setErrorMsg(null);
    if (!/\.h5ad$/i.test(file.name)) {
      setPhase("error");
      setErrorMsg("Please choose a .h5ad file.");
      return;
    }
    setResult(null);
    setPhase("reading");
    setProgress(0);
    const spots = await parseSpotCount(file);
    setPhase("uploading");
    const res = await uploadH5ad(file, spots, setProgress);
    try {
      window.sessionStorage.setItem(
        "sutura_demo_upload",
        JSON.stringify({ filename: res.filename, spots: res.spots })
      );
    } catch {
      /* ignore */
    }
    setResult(res);
    setPhase("done");
  };

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  };

  if (!ready) return <div className="min-h-screen bg-[#f7f6fb]" />;

  return (
    <div className="flex min-h-screen bg-[#f7f6fb] text-foreground">
      <Sidebar active="datasets" />

      {/* ───────────── Main ───────────── */}
      <main className="flex-1 px-6 py-8 sm:px-10 sm:py-12">
        <div className="mx-auto max-w-3xl">
          {/* Stats bar */}
          <div className="mb-8 flex flex-wrap items-center gap-x-8 gap-y-3 rounded-xl border border-border bg-white/70 px-5 py-3.5 backdrop-blur-sm">
            {TOP_STATS.map(([value, label], i) => (
              <div key={label} className="flex items-center gap-8">
                {i > 0 && <span className="hidden h-6 w-px bg-border sm:block" />}
                <div>
                  <span className="text-lg font-normal tracking-tight text-foreground">{value}</span>{" "}
                  <span className="text-[13px] font-light text-muted-foreground">{label}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-light tracking-tight text-foreground">Datasets</h1>
              <p className="mt-1 text-sm font-light text-muted-foreground">
                Upload your own section, or pick a dataset to align.
              </p>
            </div>
            <span className="rounded-full border border-border bg-white px-3 py-1 text-[12px] font-light text-muted-foreground">
              {DATASETS.length} datasets
            </span>
          </div>

          {/* Upload drop zone */}
          <input ref={fileInputRef} type="file" accept=".h5ad" className="hidden" onChange={onInputChange} />

          {phase === "done" && result ? (
            <div className="mt-6 flex flex-col gap-4 rounded-2xl border border-[#e3dbff] bg-gradient-to-b from-[#faf8ff] to-white p-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3.5">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-[#efeaff]">
                  <FileCheck2 className="h-5 w-5 text-[#6633ee]" strokeWidth={1.8} />
                </div>
                <div>
                  <p className="text-[15px] font-normal text-foreground">
                    File received: {result.filename}
                    {result.spots != null && (
                      <>
                        , <span className="text-[#6633ee]">{result.spots.toLocaleString()}</span> spots detected
                      </>
                    )}
                  </p>
                  <p className="mt-0.5 text-[12.5px] font-light text-muted-foreground">
                    {result.backendConfirmed
                      ? result.truncated
                        ? "Header validated and received by the backend (large file — full upload is disabled in the demo)."
                        : "Uploaded and validated by the backend."
                      : "Read and validated locally (backend endpoint not reachable in this environment)."}
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setPhase("idle");
                    setResult(null);
                  }}
                  className="rounded-full border border-border bg-white px-4 py-2.5 text-[14px] font-normal text-foreground transition-colors hover:bg-secondary"
                >
                  Replace
                </button>
                <button
                  type="button"
                  onClick={() => runDataset("dlpfc")}
                  className="group inline-flex items-center gap-2 rounded-full bg-[#6633ee] px-5 py-2.5 text-[14px] font-normal text-white shadow-sm shadow-[#6633ee]/25 transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0]"
                >
                  Align
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" strokeWidth={2} />
                </button>
              </div>
            </div>
          ) : (
            <div
              role="button"
              tabIndex={0}
              onClick={() => phase !== "reading" && phase !== "uploading" && fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if ((e.key === "Enter" || e.key === " ") && phase === "idle") fileInputRef.current?.click();
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={
                "mt-6 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-8 text-center transition-colors " +
                (dragging
                  ? "border-[#6633ee] bg-[#efeaff]/60"
                  : "border-[#d7cff5] bg-white/70 hover:border-[#6633ee]/60 hover:bg-[#faf8ff]")
              }
            >
              {phase === "reading" || phase === "uploading" ? (
                <div className="w-full max-w-sm">
                  <div className="flex items-center justify-center gap-2 text-[14px] font-normal text-foreground">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#e7e1ff] border-t-[#6633ee]" />
                    {phase === "reading" ? "Reading .h5ad and detecting spots…" : "Uploading to backend…"}
                  </div>
                  <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-[#e7e1ff]">
                    <div
                      className={
                        "h-full rounded-full bg-[#6633ee] " +
                        (phase === "reading" ? "w-2/5 animate-pulse" : "transition-[width] duration-150 ease-linear")
                      }
                      style={phase === "uploading" ? { width: `${Math.round(progress * 100)}%` } : undefined}
                    />
                  </div>
                </div>
              ) : (
                <>
                  <div className="grid h-11 w-11 place-items-center rounded-xl bg-[#efeaff]">
                    <UploadCloud className="h-6 w-6 text-[#6633ee]" strokeWidth={1.6} />
                  </div>
                  <p className="mt-3 text-[15px] font-normal text-foreground">
                    Drop <span className="text-[#6633ee]">.h5ad</span> file to align your data
                  </p>
                  <p className="mt-1 text-[13px] font-light text-muted-foreground">
                    or click to browse · 10x Visium / spatial AnnData
                  </p>
                  {phase === "error" && errorMsg && (
                    <p className="mt-3 inline-flex items-center gap-1.5 text-[12.5px] font-light text-destructive">
                      <AlertCircle className="h-3.5 w-3.5" /> {errorMsg}
                    </p>
                  )}
                </>
              )}
            </div>
          )}

          {/* ───────────── Dataset cards ───────────── */}
          <div className="mt-6 flex flex-col gap-4">
            {DATASETS.map((d) => (
              <DatasetCard
                key={d.id}
                d={d}
                open={hoverId === d.id || pinId === d.id}
                onEnter={() => setHoverId(d.id)}
                onLeave={() => setHoverId(null)}
                onTogglePin={() => setPinId((p) => (p === d.id ? null : d.id))}
                onRun={() => runDataset(d.id)}
              />
            ))}
          </div>

          {/* ───────────── Recent runs ───────────── */}
          <div className="mt-10">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-normal tracking-tight text-foreground">Recent runs</h2>
              <button
                type="button"
                onClick={() => router.push("/demo/runs")}
                className="text-[12px] font-light text-[#6633ee] transition-colors hover:text-[#5a2ce0]"
              >
                View all →
              </button>
            </div>
            <div className="mt-3 overflow-hidden rounded-2xl border border-border bg-white">
              {recent.map((r, i) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => openRun(r)}
                  disabled={r.status !== "Complete"}
                  className={
                    "flex w-full items-center justify-between gap-4 px-5 py-3.5 text-left " +
                    (i > 0 ? "border-t border-border " : "") +
                    (r.status === "Complete" ? "transition-colors hover:bg-[#faf8ff]" : "cursor-default")
                  }
                >
                  <div className="flex items-center gap-3">
                    <CheckCircle2
                      className={"h-4 w-4 shrink-0 " + (r.status === "Failed" ? "text-red-500" : "text-[#6633ee]")}
                      strokeWidth={1.8}
                    />
                    <div>
                      <p className="text-[13.5px] font-normal text-foreground">
                        {r.datasetName} · {r.sections}
                      </p>
                      <p className="mt-0.5 flex items-center gap-1 text-[12px] font-light text-muted-foreground">
                        <Clock className="h-3 w-3" strokeWidth={1.6} />
                        {formatWhen(r.timestamp)} · {r.status}
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="tabular-nums text-[13.5px] font-normal text-foreground">{r.medianErrorPx} px</p>
                    <p className="text-[12px] font-light text-muted-foreground">median error</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <p className="mt-8 text-center text-[12px] font-light text-muted-foreground sm:text-left">
            Signed in as <span className="text-foreground/70">suturagenomics1010101</span>
          </p>
        </div>
      </main>
    </div>
  );
}

function DatasetCard({
  d,
  open,
  onEnter,
  onLeave,
  onTogglePin,
  onRun,
}: {
  d: DemoDataset;
  open: boolean;
  onEnter: () => void;
  onLeave: () => void;
  onTogglePin: () => void;
  onRun: () => void;
}) {
  return (
    <div
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      className="group overflow-hidden rounded-2xl border border-border bg-white shadow-sm shadow-black/[0.03] transition-colors hover:border-[#c9bdf3]"
    >
      <div className="flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:justify-between sm:p-7">
        <div className="flex items-start gap-4">
          <div className="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#efeaff] to-white ring-1 ring-[#e3dbff]">
            <Layers className="h-6 w-6 text-[#6633ee]" strokeWidth={1.6} />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-normal tracking-tight text-foreground">{d.name}</h2>
              <span
                className={
                  "rounded-full px-2 py-0.5 text-[11px] font-light uppercase tracking-wide " +
                  (d.real ? "bg-[#efeaff] text-[#6633ee]" : "bg-secondary text-muted-foreground")
                }
              >
                {d.badge}
              </span>
              <button
                type="button"
                onClick={onTogglePin}
                className="ml-1 inline-flex items-center gap-1 text-[12px] font-light text-muted-foreground transition-colors hover:text-[#6633ee]"
              >
                Details
                <ChevronDown className={"h-3.5 w-3.5 transition-transform " + (open ? "rotate-180" : "")} strokeWidth={1.8} />
              </button>
            </div>
            <p className="mt-1 text-sm font-light text-muted-foreground">{d.tissue}</p>
            <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
              {d.meta.map((m) => (
                <div key={m.label} className="flex items-center gap-2">
                  <span className="text-[13px] font-light text-muted-foreground">{m.label}</span>
                  <span className="text-[13px] font-normal text-foreground">{m.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Expandable detail */}
      <div
        className={
          "grid overflow-hidden border-t border-border transition-all duration-300 ease-out " +
          (open ? "max-h-[30rem] opacity-100" : "max-h-0 opacity-0")
        }
      >
        <dl className="grid grid-cols-1 gap-x-10 px-6 py-2 sm:grid-cols-2 sm:px-7">
          {d.detail.map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-4 border-b border-border/60 py-2.5 text-[13px]">
              <dt className="shrink-0 font-light text-muted-foreground">{k}</dt>
              <dd className="text-right font-normal text-foreground">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="flex items-center justify-between gap-4 border-t border-border bg-secondary/40 px-6 py-4 sm:px-7">
        <span className="text-[13px] font-light text-muted-foreground">
          Align this section against its serial neighbours with the Sutura graph model.
        </span>
        <button
          type="button"
          onClick={onRun}
          className="group/btn inline-flex shrink-0 items-center gap-2 rounded-full bg-[#6633ee] px-6 py-3 text-[15px] font-normal text-white shadow-sm shadow-[#6633ee]/25 transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0] hover:shadow-lg hover:shadow-[#6633ee]/30"
        >
          Run Alignment
          <ArrowRight className="h-4 w-4 transition-transform group-hover/btn:translate-x-0.5" strokeWidth={2} />
        </button>
      </div>
    </div>
  );
}
