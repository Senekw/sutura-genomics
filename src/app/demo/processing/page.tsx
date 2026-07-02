"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";

import { Logo } from "@/components/logo";
import { isAuthed } from "@/lib/demoAuth";

// Pipeline steps. Durations (seconds) sum to ~15s of substantive-feeling work.
const STEPS = [
  {
    label: "Loading spatial data",
    detail: "Reading obsm[spatial] coordinates and obs[layer] annotations",
    seconds: 2,
  },
  {
    label: "Building kNN graph",
    detail: "k=6, symmetrized, edge features from spot pitch",
    seconds: 2,
  },
  {
    label: "Extracting graph embeddings",
    detail: "50-dim TruncatedSVD → 3-layer DeformConv encoder",
    seconds: 3,
  },
  {
    label: "Detecting tissue features",
    detail: "Per-spot embeddings zA, zB computed",
    seconds: 2,
  },
  {
    label: "Handling tear discontinuities",
    detail: "Cross-attention scoring correspondences",
    seconds: 3,
  },
  {
    label: "Cross-attention alignment",
    detail: "Softmax weights over reference spots",
    seconds: 2,
  },
  {
    label: "Refining spot coordinates",
    detail: "Barycentric combo + learned residual",
    seconds: 1,
  },
] as const;

const TOTAL = STEPS.reduce((s, x) => s + x.seconds, 0);
// Cumulative start offset of each step, in seconds.
const STARTS = STEPS.reduce<number[]>((acc, x, i) => {
  acc.push(i === 0 ? 0 : acc[i - 1] + STEPS[i - 1].seconds);
  return acc;
}, []);

const PALETTE = ["#8b7be8", "#6633ee", "#5a2ce0", "#9d7bff", "#b7a6ff"];

type Spot = { bx: number; by: number; band: number; nbr: number[] };

export default function DemoProcessingPage() {
  const router = useRouter();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const spotsRef = useRef<Spot[] | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [ready, setReady] = useState(false);

  // Gate on the demo session, like the dashboard.
  useEffect(() => {
    if (!isAuthed()) {
      router.replace("/demo/login");
      return;
    }
    setReady(true);
  }, [router]);

  // Build the point cloud once (deterministic — seeded LCG).
  useEffect(() => {
    if (spotsRef.current) return;
    let seed = 987654321;
    const rnd = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };
    const N = 460;
    const raw: Spot[] = [];
    for (let i = 0; i < N; i++) {
      const a = rnd() * Math.PI * 2;
      const r = Math.sqrt(rnd());
      // Oval tissue footprint in normalized [-1,1] space.
      const bx = Math.cos(a) * r * 0.92;
      const by = Math.sin(a) * r * 0.8 * (0.9 + 0.18 * Math.sin(a * 2));
      const band = Math.min(PALETTE.length - 1, Math.floor(((by + 0.85) / 1.7) * PALETTE.length));
      raw.push({ bx, by, band, nbr: [] });
    }
    // kNN (k = 3) for the graph-edge overlay.
    for (let i = 0; i < N; i++) {
      const dists = raw
        .map((p, j) => ({ j, d: (p.bx - raw[i].bx) ** 2 + (p.by - raw[i].by) ** 2 }))
        .filter((o) => o.j !== i)
        .sort((a, b) => a.d - b.d)
        .slice(0, 3)
        .map((o) => o.j);
      raw[i].nbr = dists;
    }
    spotsRef.current = raw;
  }, []);

  // Single animation loop: draws the canvas AND advances the step timeline.
  useEffect(() => {
    if (!ready) return;
    let raf = 0;
    let start = 0;
    let done = false;

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");

    const sizeCanvas = () => {
      if (!canvas || !ctx) return;
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    sizeCanvas();
    window.addEventListener("resize", sizeCanvas);

    const draw = (t: number) => {
      const spots = spotsRef.current;
      if (!canvas || !ctx || !spots) return;
      const w = canvas.getBoundingClientRect().width;
      const h = canvas.getBoundingClientRect().height;
      const cx = w / 2;
      const cy = h / 2;
      const scale = Math.min(w, h) * 0.4;

      ctx.clearRect(0, 0, w, h);

      // Reveal fractions tied to the timeline.
      const appear = clamp(t / 1.6, 0, 1); // spots fade in (step 1)
      const edgeReveal = clamp((t - 2) / 2.2, 0, 1); // kNN edges (step 2→3)
      const emphasis = clamp((t - 4) / 3, 0, 1); // embeddings color-up
      // Tear opens through the first 9s, then heals over the final 6s.
      const tear = (t < 9 ? t / 9 : Math.max(0, 1 - (t - 9) / 6)) * 0.42;

      const sway = 0.04 * Math.sin(t * 0.9);

      const project = (p: Spot) => {
        let x = p.bx;
        const y = p.by;
        // Torn flap: right half slides out and down, then heals.
        if (x > 0) {
          x += tear * 0.9;
        }
        // Gentle whole-field sway for a sense of live computation.
        const rx = x * Math.cos(sway) - y * Math.sin(sway);
        const ry = x * Math.sin(sway) + y * Math.cos(sway);
        return {
          px: cx + rx * scale,
          py: cy + (x > 0 ? ry + tear * 0.16 : ry) * scale,
        };
      };

      const pts = spots.map(project);

      // Edges (kNN graph).
      if (edgeReveal > 0) {
        ctx.lineWidth = 1;
        for (let i = 0; i < spots.length; i++) {
          if (i / spots.length > edgeReveal) continue;
          const a = pts[i];
          for (const j of spots[i].nbr) {
            const b = pts[j];
            ctx.strokeStyle = `rgba(102,51,238,${0.05 + 0.06 * edgeReveal})`;
            ctx.beginPath();
            ctx.moveTo(a.px, a.py);
            ctx.lineTo(b.px, b.py);
            ctx.stroke();
          }
        }
      }

      // Spots.
      for (let i = 0; i < spots.length; i++) {
        if (i / spots.length > appear) continue;
        const p = pts[i];
        const s = spots[i];
        const baseColor = emphasis > 0.02 ? PALETTE[s.band] : "#c3bee0";
        const pulse = 1 + 0.18 * Math.sin(t * 3 + i * 0.5) * emphasis;
        ctx.globalAlpha = 0.35 + 0.55 * appear;
        ctx.fillStyle = baseColor;
        ctx.beginPath();
        ctx.arc(p.px, p.py, 2.3 * pulse, 0, 7);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };

    const frame = (now: number) => {
      if (!start) start = now;
      const t = (now - start) / 1000;
      draw(t);
      setElapsed(Math.min(t, TOTAL));
      if (t >= TOTAL) {
        if (!done) {
          done = true;
          // Brief hold at 100%, then reveal results.
          window.setTimeout(() => router.push("/demo/results"), 550);
        }
        return;
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", sizeCanvas);
    };
  }, [ready, router]);

  if (!ready) return <div className="min-h-screen bg-[#f7f6fb]" />;

  const activeIdx = Math.min(
    STEPS.length - 1,
    STARTS.reduce((acc, s, i) => (elapsed >= s ? i : acc), 0)
  );
  const overall = Math.round((elapsed / TOTAL) * 100);

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#f7f6fb] px-6 py-12">
      <div className="absolute inset-0 -z-10 h-full w-full [background:radial-gradient(125%_125%_at_50%_0%,#f7f6fb_45%,#e4dcff_100%)]" />

      <div className="flex w-full max-w-lg flex-col items-center">
        <Logo size={30} withWordmark className="mb-8" />

        {/* Live visualization */}
        <div className="relative w-full overflow-hidden rounded-2xl border border-border bg-white/70 backdrop-blur-sm">
          <canvas ref={canvasRef} className="block h-[280px] w-full" />
          {/* Scanning shimmer */}
          <div className="pointer-events-none absolute inset-0 animate-[scan_2.6s_ease-in-out_infinite] bg-gradient-to-b from-transparent via-[#6633ee]/[0.06] to-transparent" />
          <div className="absolute left-4 top-3.5 text-[11px] font-light uppercase tracking-[0.14em] text-[#6633ee]">
            Aligning · DLPFC Br5292 151508
          </div>
        </div>

        {/* Demo-mode disclosure: the model isn't run on arbitrary uploads yet. */}
        <p className="mt-4 w-full rounded-lg border border-[#e7e1ff] bg-[#faf8ff] px-3.5 py-2.5 text-center text-[12px] font-light leading-relaxed text-muted-foreground">
          Demo mode: showing precomputed alignment on reference dataset.
        </p>

        {/* Overall progress */}
        <div className="mt-7 w-full">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-normal text-foreground">
              {STEPS[activeIdx].label}
              <span className="animate-pulse text-[#6633ee]">…</span>
            </span>
            <span className="tabular-nums text-[13px] font-light text-muted-foreground">
              {overall}%
            </span>
          </div>
          <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-[#e7e1ff]">
            <div
              className="h-full rounded-full bg-[#6633ee] transition-[width] duration-150 ease-linear"
              style={{ width: `${overall}%` }}
            />
          </div>
        </div>

        {/* Step list */}
        <ol className="mt-7 w-full space-y-1">
          {STEPS.map((step, i) => {
            const stepStart = STARTS[i];
            const stepEnd = stepStart + step.seconds;
            const isDone = elapsed >= stepEnd;
            const isActive = i === activeIdx && !isDone;
            const stepProgress = isDone
              ? 1
              : isActive
                ? clamp((elapsed - stepStart) / step.seconds, 0, 1)
                : 0;

            return (
              <li
                key={step.label}
                className={
                  "flex items-center gap-3 rounded-lg px-3 py-2 transition-colors " +
                  (isActive ? "bg-white/80" : "")
                }
              >
                <span className="grid h-5 w-5 shrink-0 place-items-center">
                  {isDone ? (
                    <span className="grid h-5 w-5 place-items-center rounded-full bg-[#6633ee]">
                      <Check className="h-3 w-3 text-white" strokeWidth={3} />
                    </span>
                  ) : isActive ? (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#e7e1ff] border-t-[#6633ee]" />
                  ) : (
                    <span className="h-2 w-2 rounded-full bg-[#d3cdea]" />
                  )}
                </span>

                <div className="min-w-0 flex-1">
                  <span
                    className={
                      "text-[13.5px] " +
                      (isDone
                        ? "font-light text-muted-foreground"
                        : isActive
                          ? "font-normal text-foreground"
                          : "font-light text-muted-foreground/60")
                    }
                  >
                    {step.label}
                  </span>
                  {(isActive || isDone) && (
                    <p
                      className={
                        "mt-0.5 font-mono text-[11px] leading-relaxed " +
                        (isActive ? "text-[#6633ee]" : "text-muted-foreground/50")
                      }
                    >
                      {step.detail}
                    </p>
                  )}
                  {isActive && (
                    <div className="mt-1.5 h-[3px] w-full overflow-hidden rounded-full bg-[#ece7fb]">
                      <div
                        className="h-full rounded-full bg-[#6633ee]/70 transition-[width] duration-150 ease-linear"
                        style={{ width: `${Math.round(stepProgress * 100)}%` }}
                      />
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <style jsx>{`
        @keyframes scan {
          0% {
            transform: translateY(-100%);
          }
          100% {
            transform: translateY(100%);
          }
        }
      `}</style>
    </main>
  );
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}
