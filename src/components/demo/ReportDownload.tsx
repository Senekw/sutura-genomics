"use client";

import { useState } from "react";
import DownloadButton, { type DownloadStatus } from "@/components/ui/button-download";
import type { Run } from "@/lib/demoRuns";
import { downloadReport } from "@/lib/reportExport";
import { getSettings, OUTPUT_OPTIONS, type OutputFormat } from "@/lib/demoSettings";

// Real report download: a format picker (defaults to the saved output format)
// + an animated button that generates and downloads the file for `run`.
export default function ReportDownload({ run, className }: { run: Run; className?: string }) {
  const [format, setFormat] = useState<OutputFormat>(() => getSettings().outputFormat);
  const [status, setStatus] = useState<DownloadStatus>("idle");
  const [progress, setProgress] = useState(0);

  const onClick = async () => {
    if (status !== "idle") return;
    setStatus("downloading");
    setProgress(0);
    // brief progress animation for feedback, then the real file download
    const started = performance.now();
    const tick = () => {
      const p = Math.min(100, Math.round(((performance.now() - started) / 700) * 100));
      setProgress(p);
      if (p < 100) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    try {
      await downloadReport(run, format);
    } catch {
      /* ignore — file just won't download */
    }
    window.setTimeout(() => {
      setStatus("downloaded");
      window.setTimeout(() => setStatus("idle"), 1600);
    }, 720);
  };

  return (
    <div className={"flex items-center gap-2 " + (className ?? "")}>
      <label className="sr-only" htmlFor={`fmt-${run.id}`}>
        Export format
      </label>
      <div className="relative">
        <select
          id={`fmt-${run.id}`}
          value={format}
          onChange={(e) => setFormat(e.target.value as OutputFormat)}
          disabled={status !== "idle"}
          className="h-10 appearance-none rounded-full border border-border bg-white pl-3.5 pr-8 text-[13px] font-light text-foreground outline-none transition-colors hover:border-muted-foreground/40 focus:border-[#6633ee] disabled:opacity-60"
        >
          {OUTPUT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <svg
          className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden
        >
          <path d="M3 4.5 6 7.5 9 4.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </div>
      <DownloadButton downloadStatus={status} progress={progress} onClick={onClick} label="Download" />
    </div>
  );
}
