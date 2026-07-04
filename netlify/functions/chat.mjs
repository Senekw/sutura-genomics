// POST /api/chat  (redirected from netlify.toml -> /.netlify/functions/chat)
//
// Grounded Q&A about an alignment result, powered by xAI Grok. The results page
// posts the REAL metrics + a question; Grok answers from those numbers.
//
// SECURITY: the API key is read from the XAI_API_KEY environment variable
// (Netlify env vars) — it is NEVER hardcoded or passed from the client. If it's
// unset, the endpoint returns 503 and the client falls back to a rule-based
// answer. Best-effort in-memory rate limiting guards against abuse.

const XAI_URL = "https://api.x.ai/v1/chat/completions";
const MODEL = "grok-4.3";
const MAX_TOKENS = 700;
const SPOT_PITCH_PX = 137;

// ---- best-effort rate limiting (per warm instance) ----
const WINDOW_MS = 60_000;
const PER_IP_MAX = 12;
const GLOBAL_MAX = 120;
const hits = new Map();
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
const str = (v, max = 200) => (typeof v === "string" ? v.slice(0, max) : "");
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);

function contextBlock(c) {
  const layers = Array.isArray(c.layers)
    ? c.layers.slice(0, 12).map((l) => ({
        label: str(l.label, 24),
        spots: str(l.spots, 16),
        accuracy: str(l.accuracy, 12),
        residualPx: num(l.residualPx),
      }))
    : [];
  return {
    dataset: str(c.dataset, 60),
    tissue: str(c.tissue, 80),
    sections: str(c.sections, 40),
    classLabel: str(c.classLabel, 24),
    spotPitchPx: SPOT_PITCH_PX,
    medianErrorPx: num(c.medianErrorPx),
    paste2MedianErrorPx: num(c.paste2Px),
    spotsRegistered: str(c.spotsRegistered, 16),
    footprintCoverage: str(c.coverage, 12),
    perClass: layers,
  };
}

export const handler = async (event) => {
  if (event.httpMethod !== "POST") return json(405, { error: "Method not allowed" });

  const ip =
    event.headers["x-nf-client-connection-ip"] ||
    (event.headers["x-forwarded-for"] || "").split(",")[0].trim() ||
    "unknown";
  if (rateLimited(ip, Date.now())) return json(429, { error: "Rate limit exceeded. Try again shortly." });

  let body;
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return json(400, { error: "Invalid JSON body." });
  }
  const question = str(body.question, 500).trim();
  if (!question || body.context == null || typeof body.context !== "object") {
    return json(400, { error: "Missing question or context." });
  }
  if (!process.env.XAI_API_KEY) return json(503, { error: "Chat is not configured." });

  const ctx = contextBlock(body.context);
  try {
    const res = await fetch(XAI_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${process.env.XAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: MAX_TOKENS,
        messages: [
          {
            role: "system",
            content:
              "You are a spatial-transcriptomics alignment QC assistant. Answer the user's " +
              "question about THIS alignment result using only the metrics provided as JSON. " +
              "Never invent numbers. Be concise (1-4 sentences), technical, and grounded. If the " +
              "question can't be answered from the metrics, say so briefly.",
          },
          { role: "user", content: "Metrics (JSON):\n" + JSON.stringify(ctx) + "\n\nQuestion: " + question },
        ],
      }),
    });
    if (!res.ok) {
      console.error("xai error", res.status);
      return json(502, { error: "Chat backend error." });
    }
    const data = await res.json();
    const answer = data?.choices?.[0]?.message?.content?.trim();
    if (!answer) return json(502, { error: "Empty answer." });
    return json(200, { answer, model: MODEL });
  } catch (err) {
    console.error("chat failed:", err?.message);
    return json(502, { error: "Chat failed." });
  }
};
