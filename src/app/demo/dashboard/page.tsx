"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Database,
  Activity,
  Settings,
  LogOut,
  ArrowRight,
  Layers,
  CircleDot,
  Microscope,
  UploadCloud,
  FileCheck2,
  AlertCircle,
} from "lucide-react";

import { Logo } from "@/components/logo";
import { isAuthed, signOut } from "@/lib/demoAuth";
import { parseSpotCount, uploadH5ad, type UploadResult } from "@/lib/h5adUpload";

const NAV = [
  { key: "datasets", label: "Datasets", icon: Database },
  { key: "runs", label: "Runs", icon: Activity },
  { key: "settings", label: "Settings", icon: Settings },
];

const META = [
  { icon: Microscope, label: "Platform", value: "10x Visium" },
  { icon: CircleDot, label: "Spots", value: "4,384" },
  { icon: Layers, label: "Section", value: "Slice 151508" },
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

  useEffect(() => {
    if (!isAuthed()) {
      router.replace("/demo/login");
      return;
    }
    setReady(true);
  }, [router]);

  const onLogout = () => {
    signOut();
    router.replace("/demo/login");
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

  const onRun = () => router.push("/demo/processing");

  if (!ready) return <div className="min-h-screen bg-[#f7f6fb]" />;

  return (
    <div className="flex min-h-screen bg-[#f7f6fb] text-foreground">
      {/* ───────────── Sidebar ───────────── */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-white/70 px-4 py-6 backdrop-blur-sm sm:flex">
        <div className="px-2">
          <Logo size={30} withWordmark />
        </div>

        <nav className="mt-9 flex flex-col gap-1">
          {NAV.map((item) => {
            const active = item.key === "datasets";
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                aria-current={active ? "page" : undefined}
                className={
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-light transition-colors " +
                  (active
                    ? "bg-[#6633ee]/10 text-[#6633ee]"
                    : "text-muted-foreground hover:bg-secondary hover:text-foreground")
                }
              >
                <Icon className="h-[17px] w-[17px]" strokeWidth={active ? 2 : 1.6} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <button
          type="button"
          onClick={onLogout}
          className="mt-auto flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-light text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <LogOut className="h-[17px] w-[17px]" strokeWidth={1.6} />
          Sign out
        </button>
      </aside>

      {/* ───────────── Main ───────────── */}
      <main className="flex-1 px-6 py-8 sm:px-10 sm:py-12">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-light tracking-tight text-foreground">
                Datasets
              </h1>
              <p className="mt-1 text-sm font-light text-muted-foreground">
                Upload your own section, or run the reference dataset below.
              </p>
            </div>
            <span className="rounded-full border border-border bg-white px-3 py-1 text-[12px] font-light text-muted-foreground">
              1 dataset
            </span>
          </div>

          {/* ───────────── Upload drop zone ───────────── */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".h5ad"
            className="hidden"
            onChange={onInputChange}
          />

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
                  onClick={onRun}
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
                "mt-6 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors " +
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
                        (phase === "reading"
                          ? "w-2/5 animate-pulse"
                          : "transition-[width] duration-150 ease-linear")
                      }
                      style={phase === "uploading" ? { width: `${Math.round(progress * 100)}%` } : undefined}
                    />
                  </div>
                </div>
              ) : (
                <>
                  <div className="grid h-12 w-12 place-items-center rounded-xl bg-[#efeaff]">
                    <UploadCloud className="h-6 w-6 text-[#6633ee]" strokeWidth={1.6} />
                  </div>
                  <p className="mt-4 text-[15px] font-normal text-foreground">
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

          {/* ───────────── Reference dataset card ───────────── */}
          <div className="mt-8 overflow-hidden rounded-2xl border border-border bg-white shadow-sm shadow-black/[0.03]">
            <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-center sm:justify-between sm:p-7">
              <div className="flex items-start gap-4">
                <div className="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#efeaff] to-white ring-1 ring-[#e3dbff]">
                  <Layers className="h-6 w-6 text-[#6633ee]" strokeWidth={1.6} />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-normal tracking-tight text-foreground">
                      DLPFC Br5292 — Slice 151508
                    </h2>
                    <span className="rounded-full bg-[#efeaff] px-2 py-0.5 text-[11px] font-light uppercase tracking-wide text-[#6633ee]">
                      Reference
                    </span>
                  </div>
                  <p className="mt-1 text-sm font-light text-muted-foreground">
                    Human dorsolateral prefrontal cortex · layered reference section
                  </p>

                  <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
                    {META.map((m) => {
                      const Icon = m.icon;
                      return (
                        <div key={m.label} className="flex items-center gap-2">
                          <Icon className="h-4 w-4 text-muted-foreground" strokeWidth={1.6} />
                          <span className="text-[13px] font-light text-muted-foreground">
                            {m.label}
                          </span>
                          <span className="text-[13px] font-normal text-foreground">
                            {m.value}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-4 border-t border-border bg-secondary/40 px-6 py-4 sm:px-7">
              <span className="text-[13px] font-light text-muted-foreground">
                Aligns this section against its serial neighbours with the Sutura graph model.
              </span>
              <button
                type="button"
                onClick={onRun}
                className="group inline-flex shrink-0 items-center gap-2 rounded-full bg-[#6633ee] px-6 py-3 text-[15px] font-normal text-white shadow-sm shadow-[#6633ee]/25 transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0] hover:shadow-lg hover:shadow-[#6633ee]/30"
              >
                Run Alignment
                <ArrowRight
                  className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                  strokeWidth={2}
                />
              </button>
            </div>
          </div>

          <p className="mt-6 text-center text-[12px] font-light text-muted-foreground sm:text-left">
            Signed in as{" "}
            <span className="text-foreground/70">suturagenomics1010101</span>
          </p>
        </div>
      </main>
    </div>
  );
}
