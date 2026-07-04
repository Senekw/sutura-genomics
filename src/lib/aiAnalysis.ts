// Client side of the "AI Analysis" panel. Posts the REAL alignment metrics for
// the selected dataset to /api/analyze (a Netlify Function that calls Claude
// server-side), and returns a grounded technical read-out. One-shot, not a chat.
//
// Guards: results are cached per dataset in sessionStorage (a revisit doesn't
// re-call), and a localStorage sliding-window limit caps calls per browser so a
// user clearing the cache can't hammer the endpoint. On any failure we return a
// grounded fallback built from the same numbers, so the panel is never broken.

import type { DemoDataset } from "./demoDatasets";

export type AnalysisResult = { text: string; source: "claude" | "fallback" };

const CACHE_PREFIX = "sutura_ai_analysis_";
const RATE_KEY = "sutura_ai_calls";
const RATE_WINDOW_MS = 10 * 60_000; // 10 minutes
const RATE_MAX = 8; // analyze calls per window per browser

function residNum(s: string): number | null {
  const n = parseInt(s.replace(/[^\d]/g, ""), 10);
  return Number.isFinite(n) ? n : null;
}

function metricsPayload(ds: DemoDataset) {
  return {
    dataset: ds.name,
    tissue: ds.tissue,
    sections: ds.sections,
    classLabel: ds.classLabel,
    medianErrorPx: ds.suturaPx,
    paste2Px: ds.paste2Px,
    spotsRegistered: ds.spotsRegistered,
    coverage: ds.coverage,
    tear: ds.tear,
    layers: ds.regions.map((r) => ({
      label: r.label,
      spots: r.count,
      accuracy: r.acc,
      residualPx: residNum(r.resid),
    })),
  };
}

// Grounded, no-API fallback — real numbers, so the panel stays useful offline.
function fallbackText(ds: DemoDataset): string {
  const worst = [...ds.regions].sort(
    (a, b) => (residNum(b.resid) ?? 0) - (residNum(a.resid) ?? 0)
  )[0];
  const best = [...ds.regions].sort(
    (a, b) => (residNum(a.resid) ?? 0) - (residNum(b.resid) ?? 0)
  )[0];
  const sub = ds.suturaPx < 137 ? "below the 137 px Visium spot pitch" : "near one Visium spot pitch (137 px)";
  return (
    `Sutura registered ${ds.spotsRegistered} spots at a median error of ${ds.suturaPx} px (${sub}), ` +
    `with ${ds.coverage} footprint coverage. ${best.label} aligned tightest (${best.resid}) while ` +
    `${worst.label} shows the largest residual (${worst.resid}) — flag it for manual review near ${ds.tear}.`
  );
}

function rateOk(): boolean {
  try {
    const now = Date.now();
    const arr: number[] = JSON.parse(localStorage.getItem(RATE_KEY) || "[]").filter(
      (t: number) => now - t < RATE_WINDOW_MS
    );
    if (arr.length >= RATE_MAX) return false;
    arr.push(now);
    localStorage.setItem(RATE_KEY, JSON.stringify(arr));
    return true;
  } catch {
    return true;
  }
}

export async function fetchAnalysis(ds: DemoDataset): Promise<AnalysisResult> {
  const cacheKey = CACHE_PREFIX + ds.id;
  try {
    const cached = sessionStorage.getItem(cacheKey);
    if (cached) return JSON.parse(cached) as AnalysisResult;
  } catch {
    /* ignore */
  }

  if (!rateOk()) return { text: fallbackText(ds), source: "fallback" };

  let result: AnalysisResult;
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metricsPayload(ds)),
    });
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    const text = typeof data.analysis === "string" ? data.analysis.trim() : "";
    result = text ? { text, source: "claude" } : { text: fallbackText(ds), source: "fallback" };
  } catch {
    result = { text: fallbackText(ds), source: "fallback" };
  }

  try {
    sessionStorage.setItem(cacheKey, JSON.stringify(result));
  } catch {
    /* ignore */
  }
  return result;
}
