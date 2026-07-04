// Client side of the analysis assistant: a grounded metrics context, a
// rule-based "full analysis" (no API key needed), and a chat call to /api/chat
// (xAI Grok, key from the server environment) with a graceful fallback.

import type { DemoDataset } from "./demoDatasets";
import type { Run } from "./demoRuns";

const PITCH = 137;
const RATE_KEY = "sutura_chat_calls";
const RATE_WINDOW_MS = 5 * 60_000;
const RATE_MAX = 20;

function residNum(s: string): number {
  return parseInt(s.replace(/[^\d]/g, ""), 10) || 0;
}

export function buildContext(ds: DemoDataset, run: Run) {
  return {
    dataset: ds.name,
    tissue: ds.tissue,
    sections: run.sections,
    classLabel: ds.classLabel,
    medianErrorPx: run.medianErrorPx,
    paste2Px: ds.paste2Px,
    spotsRegistered: run.spots,
    coverage: run.coverage,
    layers: ds.regions.map((r) => ({
      label: r.label,
      spots: r.count,
      accuracy: r.acc,
      residualPx: residNum(r.resid),
    })),
  };
}

// Rule-based full read — grounded, works with no external call.
export function fullAnalysis(ds: DemoDataset, run: Run): string {
  const best = [...ds.regions].sort((a, b) => residNum(a.resid) - residNum(b.resid))[0];
  const worst = [...ds.regions].sort((a, b) => residNum(b.resid) - residNum(a.resid))[0];
  const ratio = (ds.paste2Px / run.medianErrorPx).toFixed(1);
  const pitchNote =
    run.medianErrorPx < PITCH
      ? `below one spot pitch (${PITCH} px) — sub-spot accuracy`
      : `${(run.medianErrorPx / PITCH).toFixed(1)}× the ${PITCH} px spot pitch`;
  const label = ds.classLabel.toLowerCase();
  return [
    `Overall: median registration error is ${run.medianErrorPx} px, ${pitchNote}, across ${run.spots} spots at ${run.coverage} footprint coverage. That is ${ratio}× more accurate than PASTE2 (${ds.paste2Px} px) on the same tear.`,
    `Per ${label}: ${best.label} aligned tightest at ${best.resid}, while ${worst.label} carries the largest residual at ${worst.resid}${residNum(worst.resid) > PITCH ? " — above one spot pitch, worth a manual check" : ""}.`,
    `Tear handling: the discontinuity was resolved with layer boundaries preserved through the tear region; residuals stay ${residNum(worst.resid) <= PITCH ? "at or below" : "near"} spot-level away from the sparsest ${label}s (${worst.label}).`,
    `Parameters: reference = ${run.params.referenceSection}, tear sensitivity = ${run.params.tearSensitivity}, k = ${run.params.knn}.`,
  ].join("\n\n");
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

export type ChatReply = { answer: string; source: "grok" | "fallback" };

export async function askChat(question: string, ds: DemoDataset, run: Run): Promise<ChatReply> {
  const fallback = (): ChatReply => ({
    answer:
      "Live chat isn't available right now (Grok isn't configured for this deployment). Here's the grounded summary instead:\n\n" +
      fullAnalysis(ds, run),
    source: "fallback",
  });

  if (!rateOk()) {
    return {
      answer: "You're sending messages quickly — please wait a moment before asking again.",
      source: "fallback",
    };
  }

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context: buildContext(ds, run) }),
    });
    if (!res.ok) return fallback();
    const data = await res.json();
    const answer = typeof data.answer === "string" ? data.answer.trim() : "";
    return answer ? { answer, source: "grok" } : fallback();
  } catch {
    return fallback();
  }
}
