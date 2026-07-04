"use client";

import { Download, Loader2, CheckCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export type DownloadStatus = "idle" | "downloading" | "downloaded";

interface DownloadButtonProps {
  downloadStatus: DownloadStatus;
  progress: number;
  onClick: () => void;
  label?: string;
  className?: string;
}

// Presentational download button (adapted from the shadcn button-download
// pattern) styled to the demo's purple aesthetic.
export default function DownloadButton({
  downloadStatus,
  progress,
  onClick,
  label = "Download",
  className,
}: DownloadButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={downloadStatus !== "idle"}
      className={cn(
        "relative inline-flex h-10 w-40 items-center justify-center gap-2 overflow-hidden rounded-full",
        "bg-[#6633ee] text-[14px] font-normal text-white shadow-sm shadow-[#6633ee]/25",
        "transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0] disabled:pointer-events-none disabled:translate-y-0",
        className
      )}
    >
      {downloadStatus === "idle" && (
        <>
          <Download className="h-4 w-4" strokeWidth={2} />
          {label}
        </>
      )}
      {downloadStatus === "downloading" && (
        <span className="z-[5] inline-flex items-center gap-2 tabular-nums">
          <Loader2 className="h-4 w-4 animate-spin" />
          {progress}%
        </span>
      )}
      {downloadStatus === "downloaded" && (
        <>
          <CheckCircle className="h-4 w-4" strokeWidth={2} />
          Downloaded
        </>
      )}
      {downloadStatus === "downloading" && (
        <span
          className="absolute inset-0 bottom-0 left-0 z-[3] h-full bg-white/25 transition-all duration-150 ease-out"
          style={{ width: `${progress}%` }}
        />
      )}
    </button>
  );
}
