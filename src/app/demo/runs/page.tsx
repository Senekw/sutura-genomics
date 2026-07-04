"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, CircleDot } from "lucide-react";

import Sidebar from "@/components/demo/Sidebar";
import ReportDownload from "@/components/demo/ReportDownload";
import { isAuthed } from "@/lib/demoAuth";
import { selectDataset } from "@/lib/demoDatasets";
import { getRuns, analyzeRun, formatWhen, type Run, type RunStatus } from "@/lib/demoRuns";

const STATUS_STYLE: Record<RunStatus, string> = {
  Complete: "bg-[#efeaff] text-[#6633ee]",
  Running: "bg-amber-100 text-amber-700",
  Failed: "bg-red-100 text-red-600",
};

export default function DemoRunsPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [runs, setRuns] = useState<Run[]>([]);

  useEffect(() => {
    if (!isAuthed()) {
      router.replace("/demo/login");
      return;
    }
    setRuns(getRuns());
    setReady(true);
  }, [router]);

  const openRun = (run: Run) => {
    if (run.status !== "Complete") return;
    selectDataset(run.datasetId);
    router.push("/demo/results");
  };

  if (!ready) return <div className="min-h-screen bg-[#f7f6fb]" />;

  return (
    <div className="flex min-h-screen bg-[#f7f6fb] text-foreground">
      <Sidebar active="runs" />
      <main className="flex-1 px-6 py-8 sm:px-10 sm:py-12">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-light tracking-tight text-foreground">Runs</h1>
              <p className="mt-1 text-sm font-light text-muted-foreground">
                Past alignment runs. Open a completed run to review its 3D volume and metrics.
              </p>
            </div>
            <span className="rounded-full border border-border bg-white px-3 py-1 text-[12px] font-light text-muted-foreground">
              {runs.length} run{runs.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="mt-6 flex flex-col gap-3">
            {runs.map((run) => (
              <div
                key={run.id}
                className="overflow-hidden rounded-2xl border border-border bg-white shadow-sm shadow-black/[0.03]"
              >
                <button
                  type="button"
                  onClick={() => openRun(run)}
                  disabled={run.status !== "Complete"}
                  className={
                    "group flex w-full items-start justify-between gap-4 px-5 py-4 text-left transition-colors " +
                    (run.status === "Complete" ? "hover:bg-[#faf8ff]" : "cursor-default")
                  }
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[15px] font-normal text-foreground">{run.datasetName}</span>
                      <span
                        className={
                          "rounded-full px-2 py-0.5 text-[11px] font-light uppercase tracking-wide " +
                          STATUS_STYLE[run.status]
                        }
                      >
                        {run.status}
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12.5px] font-light text-muted-foreground">
                      <span>{formatWhen(run.timestamp)}</span>
                      <span className="inline-flex items-center gap-1.5">
                        <CircleDot className="h-3.5 w-3.5" strokeWidth={1.6} />
                        {run.spots} spots
                      </span>
                      <span className="tabular-nums">
                        median{" "}
                        <span className={run.status === "Failed" ? "text-red-600" : "text-foreground"}>
                          {run.medianErrorPx} px
                        </span>
                      </span>
                      <span>{run.sections}</span>
                    </div>
                    <p className="mt-2 text-[12.5px] font-light leading-relaxed text-muted-foreground">
                      <span className="text-foreground/70">Analysis · </span>
                      {analyzeRun(run)}
                    </p>
                  </div>
                  {run.status === "Complete" && (
                    <ArrowRight
                      className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-[#6633ee]"
                      strokeWidth={1.8}
                    />
                  )}
                </button>
                {run.status !== "Running" && (
                  <div className="flex items-center justify-between gap-3 border-t border-border bg-secondary/30 px-5 py-3">
                    <span className="text-[12px] font-light text-muted-foreground">
                      Export this run&rsquo;s report
                    </span>
                    <ReportDownload run={run} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
