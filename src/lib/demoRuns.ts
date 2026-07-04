// Persistent alignment-run history for the demo (localStorage-backed, same
// pattern as demoAuth/demoDatasets). A run is created when an alignment
// completes; the Runs page lists them and opens each run's results view.

import { DATASETS } from "./demoDatasets";

export type RunStatus = "Complete" | "Running" | "Failed";

export type Run = {
  id: string;
  datasetId: string;
  datasetName: string;
  sections: string;
  timestamp: number; // ms epoch
  medianErrorPx: number;
  spots: string;
  coverage: string;
  status: RunStatus;
  params: { referenceSection: string; tearSensitivity: number; knn: number };
};

const KEY = "sutura_demo_runs";
const SPOT_PITCH_PX = 137;

function read(): Run[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Run[];
  } catch {
    /* ignore */
  }
  const seeded = seed();
  write(seeded);
  return seeded;
}

function write(runs: Run[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(runs));
  } catch {
    /* ignore */
  }
}

// A little history so the page isn't empty on first visit.
function seed(): Run[] {
  const now = Date.now();
  const hr = 3_600_000;
  const dlpfc = DATASETS[0];
  const breast = DATASETS[1];
  const kidney = DATASETS[2];
  const p = (knn: number, tear: number) => ({
    referenceSection: "First section",
    tearSensitivity: tear,
    knn,
  });
  return [
    {
      id: "seed-3",
      datasetId: kidney.id,
      datasetName: kidney.name,
      sections: kidney.sections,
      timestamp: now - 60 * hr,
      medianErrorPx: kidney.suturaPx,
      spots: kidney.spotsRegistered,
      coverage: kidney.coverage,
      status: "Complete",
      params: p(6, 4),
    },
    {
      id: "seed-fail",
      datasetId: breast.id,
      datasetName: breast.name,
      sections: breast.sections,
      timestamp: now - 28 * hr,
      medianErrorPx: 1840,
      spots: breast.spotsRegistered,
      coverage: "41.0%",
      status: "Failed",
      params: p(6, 8),
    },
    {
      id: "seed-2",
      datasetId: breast.id,
      datasetName: breast.name,
      sections: breast.sections,
      timestamp: now - 20 * hr,
      medianErrorPx: breast.suturaPx,
      spots: breast.spotsRegistered,
      coverage: breast.coverage,
      status: "Complete",
      params: p(6, 4),
    },
    {
      id: "seed-1",
      datasetId: dlpfc.id,
      datasetName: dlpfc.name,
      sections: dlpfc.sections,
      timestamp: now - 2 * hr,
      medianErrorPx: dlpfc.suturaPx,
      spots: dlpfc.spotsRegistered,
      coverage: dlpfc.coverage,
      status: "Complete",
      params: p(6, 4),
    },
  ];
}

export function getRuns(): Run[] {
  return read().sort((a, b) => b.timestamp - a.timestamp);
}

export function getRun(id: string): Run | undefined {
  return read().find((r) => r.id === id);
}

export function addRun(run: Omit<Run, "id" | "timestamp">): Run {
  const full: Run = { ...run, id: `run-${Date.now()}-${Math.floor(Math.random() * 1e4)}`, timestamp: Date.now() };
  const runs = read();
  runs.push(full);
  write(runs);
  return full;
}

// Rule-based, no-AI quality read from the run's real numbers.
export function analyzeRun(run: Run): string {
  if (run.status === "Failed") {
    return "Alignment failed — the tear could not be resolved and coverage collapsed. Lower the tear sensitivity and re-run.";
  }
  if (run.status === "Running") return "Alignment in progress…";
  const px = run.medianErrorPx;
  const ratio = (px / SPOT_PITCH_PX).toFixed(1);
  if (px < SPOT_PITCH_PX) {
    return `Median error ${px} px is below one spot pitch (${SPOT_PITCH_PX} px) — sub-spot accuracy, layers preserved across the tear.`;
  }
  if (px < 1.5 * SPOT_PITCH_PX) {
    return `Median error ${px} px is near one spot pitch (${ratio}×) — spot-level accuracy with minor residual at the tear.`;
  }
  return `Elevated residual (${px} px, ${ratio}× spot pitch) — manual review recommended before downstream analysis.`;
}

export function formatWhen(ts: number): string {
  const diff = Date.now() - ts;
  const min = Math.round(diff / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? "" : "s"} ago`;
  const day = Math.round(hr / 24);
  return `${day} day${day === 1 ? "" : "s"} ago`;
}
