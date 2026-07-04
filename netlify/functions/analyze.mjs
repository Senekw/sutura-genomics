// POST /api/analyze  (redirected from netlify.toml -> /.netlify/functions/analyze)
//
// One-shot "AI Analysis" of an alignment result. The demo results page posts the
// REAL alignment metrics; this function asks Claude to write a short, grounded
// technical read for a spatial-biology researcher. It is NOT a chatbot — single
// request, single response, no conversation state.
//
// Key design points:
//  * The API key is never passed by the client — `new Anthropic()` reads
//    ANTHROPIC_API_KEY from the environment (set in Netlify env vars).
//  * The prompt is built SERVER-SIDE from validated numeric fields, so the
//    endpoint can't be used to run arbitrary prompts.
//  * Best-effort in-memory rate limiting (per client IP + a global cap) guards
//    against abuse. It resets on cold start — a hard limit would need a store.

import Anthropic from "@anthropic-ai/sdk";

const MODEL = "claude-sonnet-4-6";
const MAX_TOKENS = 1000;
const SPOT_PITCH_PX = 137;

// ---- best-effort rate limiting (per warm instance) ----
const WINDOW_MS = 60_000;
const PER_IP_MAX = 6; // requests / minute / IP
const GLOBAL_MAX = 60; // requests / minute across this instance
const hits = new Map(); // ip -> number[] (timestamps)
let globalHits = [];

function rateLimited(ip, now) {
  globalHits = globalHits.filter((t) => now - t < WINDOW_MS);
  if (globalHits.length >= GLOBAL_MAX) return true;
  const arr = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  if (arr.length >= PER_IP_MAX) return true;
  arr.push(now);
  hits.set(ip, arr);
  globalHits.push(now);
  return false;
}

const json = (statusCode, body) => ({
  statusCode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const str = (v, max = 120) =>
  typeof v === "string" ? v.slice(0, max) : "";
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);

// Build the analysis prompt from validated fields only (no free-form passthrough).
function buildUserPrompt(m) {
  const layers = Array.isArray(m.layers)
    ? m.layers.slice(0, 12).map((l) => ({
        label: str(l.label, 24),
        spots: str(l.spots, 16),
        accuracy: str(l.accuracy, 12),
        residualPx: num(l.residualPx),
      }))
    : [];
  const metrics = {
    dataset: str(m.dataset, 60),
    tissue: str(m.tissue, 80),
    sections: str(m.sections, 40),
    classLabel: str(m.classLabel, 24),
    spotPitchPx: SPOT_PITCH_PX,
    medianRegistrationErrorPx: num(m.medianErrorPx),
    paste2MedianErrorPx: num(m.paste2Px),
    spotsRegistered: str(m.spotsRegistered, 16),
    footprintCoverage: str(m.coverage, 12),
    tearLocation: str(m.tear, 160),
    perClass: layers,
  };
  return (
    "Alignment metrics (JSON):\n" +
    JSON.stringify(metrics, null, 2) +
    "\n\nWrite a 3-4 sentence technical analysis for a spatial-transcriptomics " +
    "researcher. Cover: (1) overall alignment quality relative to the Visium " +
    `spot pitch of ${SPOT_PITCH_PX} px; (2) which ${metrics.classLabel.toLowerCase()}s ` +
    "aligned best and worst by residual error; (3) whether the tear region was " +
    "resolved; (4) any regions to flag for manual review. Use ONLY the numbers " +
    "above — never invent values. Plain prose, no preamble, no bullet points, no markdown."
  );
}

export const handler = async (event) => {
  if (event.httpMethod !== "POST") return json(405, { error: "Method not allowed" });

  const ip =
    event.headers["x-nf-client-connection-ip"] ||
    (event.headers["x-forwarded-for"] || "").split(",")[0].trim() ||
    "unknown";
  if (rateLimited(ip, Date.now())) {
    return json(429, { error: "Rate limit exceeded. Try again shortly." });
  }

  let metrics;
  try {
    metrics = JSON.parse(event.body || "{}");
  } catch {
    return json(400, { error: "Invalid JSON body." });
  }
  if (metrics == null || typeof metrics !== "object" || num(metrics.medianErrorPx) == null) {
    return json(400, { error: "Missing alignment metrics." });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    // Key not configured in this environment — client shows its fallback.
    return json(503, { error: "Analysis service is not configured." });
  }

  try {
    const client = new Anthropic(); // reads ANTHROPIC_API_KEY from the env
    const msg = await client.messages.create({
      model: MODEL,
      max_tokens: MAX_TOKENS,
      system:
        "You are an alignment quality-control assistant for spatial transcriptomics. " +
        "You write concise, grounded technical read-outs for researchers. Base every " +
        "statement strictly on the metrics provided; never invent or extrapolate numbers.",
      messages: [{ role: "user", content: buildUserPrompt(metrics) }],
    });

    const text = (msg.content || [])
      .filter((b) => b.type === "text")
      .map((b) => b.text)
      .join("")
      .trim();

    if (!text) return json(502, { error: "Empty analysis." });
    return json(200, { analysis: text, model: MODEL });
  } catch (err) {
    console.error("analyze failed:", err?.status, err?.message);
    return json(502, { error: "Analysis failed." });
  }
};
