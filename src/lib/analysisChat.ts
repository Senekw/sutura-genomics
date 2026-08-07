// Client side of the analysis assistant: a grounded metrics context, a
// rule-based "full analysis" (no API key needed), and a chat call to /api/chat
// (Google Gemini, key held server-side) with a graceful fallback.

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
    // Breast/kidney are illustrative demo data (demoDatasets.ts). Pass the flag
    // so the assistant discloses that instead of presenting them as findings.
    dataIsSynthetic: !ds.real,
    runStatus: run.status,
    medianErrorPx: run.medianErrorPx,
    // Only PASTE2 is carried as a comparison: it is the one baseline actually
    // run end-to-end on this benchmark. The other rows in ds.benchmark are not
    // grounded the same way, so they are deliberately not given to the model.
    paste2Px: ds.paste2Px,
    spotsRegistered: run.spots,
    coverage: run.coverage,
    parameters: run.params,
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

// Starter questions that name what actually happened in this run, so the
// prompts read as being about the result on screen rather than as generic
// chatbot filler.
export function suggestedQuestions(ds: DemoDataset, run: Run): string[] {
  const worst = [...ds.regions].sort((a, b) => residNum(b.resid) - residNum(a.resid))[0];
  const label = ds.classLabel.toLowerCase();
  return [
    worst ? `Why did ${worst.label} carry the largest residual?` : `Which ${label} aligned worst?`,
    run.medianErrorPx < PITCH ? "Is this accurate enough to trust?" : "Why is the error above one spot pitch?",
    "How does this compare to PASTE2?",
    `What did tear sensitivity ${run.params.tearSensitivity} change?`,
  ];
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

export type ChatTurn = { role: "user" | "assistant"; text: string };
export type ChatReply = { answer: string; source: "gemini" | "fallback" | "notice" };

// A failure should never expose deployment state to a visitor. Each case gets
// copy that says what happened and what to do, and anything that leaves the
// assistant unable to answer still hands back the grounded summary.
function unavailable(ds: DemoDataset, run: Run, lead: string): ChatReply {
  return {
    answer: `${lead}\n\nHere's the grounded summary of this run in the meantime:\n\n${fullAnalysis(ds, run)}`,
    source: "fallback",
  };
}

export async function askChat(
  question: string,
  ds: DemoDataset,
  run: Run,
  history: ChatTurn[] = [],
): Promise<ChatReply> {
  if (!rateOk()) {
    return {
      answer: "You're sending questions faster than the assistant can take them. Give it a few seconds and try again.",
      source: "notice",
    };
  }

  let res: Response;
  try {
    res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context: buildContext(ds, run), history }),
    });
  } catch {
    return unavailable(ds, run, "The assistant couldn't be reached — that's usually a network drop on this end.");
  }

  if (res.status === 429) {
    return {
      answer: "The assistant is handling a lot of questions right now. Try again in a moment.",
      source: "notice",
    };
  }
  if (!res.ok) {
    return unavailable(ds, run, "The assistant isn't available right now.");
  }

  try {
    const data = await res.json();
    const answer = typeof data.answer === "string" ? data.answer.trim() : "";
    if (answer) return { answer, source: "gemini" };
  } catch {
    /* fall through to the grounded summary */
  }
  return unavailable(ds, run, "The assistant didn't return an answer to that one.");
}
