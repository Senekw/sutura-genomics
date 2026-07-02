"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Check, RotateCcw } from "lucide-react";

import { Logo } from "@/components/logo";
import { isAuthed } from "@/lib/demoAuth";

// Real medians from Sutura's internal DLPFC benchmark (see public/live-demo.html).
const SUTURA_PX = 103;
const PASTE2_PX = 729;
const PITCH_PX = 137; // one Visium spot pitch
const RATIO = (PASTE2_PX / SUTURA_PX).toFixed(1); // ~7.1×
const MAXERR = 900;

export default function DemoResultsPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const beforeRef = useRef<HTMLCanvasElement | null>(null);
  const afterRef = useRef<HTMLCanvasElement | null>(null);
  const [bars, setBars] = useState(false);

  useEffect(() => {
    if (!isAuthed()) {
      router.replace("/demo/login");
      return;
    }
    setReady(true);
  }, [router]);

  useEffect(() => {
    if (!ready) return;
    drawCloud(beforeRef.current, "torn");
    drawCloud(afterRef.current, "aligned");
    const id = window.setTimeout(() => setBars(true), 120);
    return () => window.clearTimeout(id);
  }, [ready]);

  if (!ready) return <div className="min-h-screen bg-[#f7f6fb]" />;

  return (
    <main className="relative flex min-h-screen flex-col items-center px-6 py-12">
      <div className="absolute inset-0 -z-10 h-full w-full bg-[#f7f6fb] [background:radial-gradient(125%_125%_at_50%_10%,#f7f6fb_45%,#cdc4f2_100%)]" />

      <div className="w-full max-w-4xl">
        <div className="flex flex-col items-center text-center">
          <Logo size={30} withWordmark className="mb-6" />
          <div className="inline-flex items-center gap-2 rounded-full bg-[#efeaff] px-3 py-1 text-[12px] font-normal text-[#6633ee]">
            <Check className="h-3.5 w-3.5" strokeWidth={3} />
            Alignment complete
          </div>
          <h1 className="mt-4 text-2xl font-light tracking-tight text-foreground sm:text-3xl">
            DLPFC Br5292 — Slice 151508 aligned
          </h1>
          <p className="mt-2 max-w-xl text-sm font-light leading-relaxed text-muted-foreground">
            4,384 spots registered across the serial sections in 14.8 s. Sutura
            recovers the true tissue geometry straight through the tear, staying
            below one spot pitch where optimal-transport pipelines drift.
          </p>
        </div>

        {/* Before / after */}
        <div className="mt-9 grid gap-4 sm:grid-cols-2">
          <figure className="overflow-hidden rounded-2xl border border-border bg-white">
            <canvas ref={beforeRef} className="block h-[220px] w-full" />
            <figcaption className="flex items-center justify-between border-t border-border px-4 py-3">
              <span className="text-[13px] font-normal text-foreground">Input · torn section</span>
              <span className="text-[12px] font-light text-muted-foreground">
                misaligned at the tear
              </span>
            </figcaption>
          </figure>

          <figure className="overflow-hidden rounded-2xl border border-[#e3dbff] bg-gradient-to-b from-[#faf8ff] to-white">
            <canvas ref={afterRef} className="block h-[220px] w-full" />
            <figcaption className="flex items-center justify-between border-t border-[#e3dbff] px-4 py-3">
              <span className="text-[13px] font-normal text-[#6633ee]">Sutura · aligned</span>
              <span className="text-[12px] font-light text-muted-foreground">
                sub-spot accuracy
              </span>
            </figcaption>
          </figure>
        </div>

        {/* Metrics */}
        <div className="mt-4 grid gap-4 sm:grid-cols-[1.4fr_1fr]">
          <div className="rounded-2xl border border-[#e3dbff] bg-gradient-to-b from-[#efeaff] to-white p-6">
            <div className="text-[13px] font-light tracking-wide text-muted-foreground">
              SUTURA · median registration error
            </div>
            <div className="mt-1 text-[44px] font-light leading-none text-[#6633ee]">
              {SUTURA_PX}
              <span className="ml-1.5 text-lg font-light text-muted-foreground">px</span>
            </div>
            <div className="mt-2 text-[12.5px] font-light text-muted-foreground">
              Below one spot pitch ({PITCH_PX} px) — sub-spot accuracy.
            </div>

            {/* Comparison bars */}
            <div className="mt-5 space-y-2.5">
              <BarRow
                label="Sutura"
                value={SUTURA_PX}
                width={bars ? (SUTURA_PX / MAXERR) * 100 : 0}
                color="#6633ee"
                strong
              />
              <BarRow
                label="PASTE2"
                value={PASTE2_PX}
                width={bars ? (PASTE2_PX / MAXERR) * 100 : 0}
                color="#c9c9d2"
              />
            </div>
          </div>

          <div className="flex flex-col gap-4">
            <div className="rounded-2xl border border-border bg-white p-6">
              <div className="text-[13px] font-light text-muted-foreground">vs. PASTE2 (optimal transport)</div>
              <div className="mt-1 text-[44px] font-light leading-none text-foreground">
                {RATIO}
                <span className="ml-1 text-lg font-light text-muted-foreground">×</span>
              </div>
              <div className="mt-2 text-[12.5px] font-light text-muted-foreground">
                more accurate at this tear ({PASTE2_PX} px).
              </div>
            </div>
            <div className="rounded-2xl border border-border bg-white p-6">
              <div className="text-[13px] font-light text-muted-foreground">Spots registered</div>
              <div className="mt-1 text-[44px] font-light leading-none text-foreground">
                4,384
              </div>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <button
            type="button"
            onClick={() => router.push("/demo/dashboard")}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-white px-6 py-3 text-[15px] font-normal text-foreground transition-colors hover:bg-secondary"
          >
            <RotateCcw className="h-4 w-4" strokeWidth={1.8} />
            Back to datasets
          </button>
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 rounded-full bg-[#6633ee] px-7 py-3 text-[15px] font-normal text-white shadow-sm shadow-[#6633ee]/25 transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0] hover:shadow-lg hover:shadow-[#6633ee]/30"
          >
            Book a demo →
          </Link>
        </div>

        <p className="mt-6 text-center text-[12px] font-light leading-relaxed text-muted-foreground">
          Median error values are measured results from Sutura&rsquo;s internal DLPFC
          benchmark (array-bridge ground truth, torn-warp regime). One spot pitch = {PITCH_PX} px.
        </p>
      </div>
    </main>
  );
}

function BarRow({
  label,
  value,
  width,
  color,
  strong,
}: {
  label: string;
  value: number;
  width: number;
  color: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center gap-3 text-[12.5px]">
      <span className="w-14 shrink-0 font-light text-muted-foreground">{label}</span>
      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#f0f0f3]">
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${width}%`, background: color }}
        />
      </div>
      <span
        className={
          "w-12 shrink-0 text-right tabular-nums " +
          (strong ? "font-normal text-[#6633ee]" : "font-light text-muted-foreground")
        }
      >
        {value} px
      </span>
    </div>
  );
}

// Draws a reference (gray) + moving (purple) point cloud, either torn/misaligned
// or cleanly aligned. Deterministic — seeded so both canvases look consistent.
function drawCloud(canvas: HTMLCanvasElement | null, mode: "torn" | "aligned") {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const w = rect.width;
  const h = rect.height;
  const cx = w / 2;
  const cy = h / 2;
  const scale = Math.min(w, h) * 0.42;

  let seed = 20260702;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };

  const N = 380;
  const base: { x: number; y: number }[] = [];
  for (let i = 0; i < N; i++) {
    const a = rnd() * Math.PI * 2;
    const r = Math.sqrt(rnd());
    base.push({
      x: Math.cos(a) * r * 0.92,
      y: Math.sin(a) * r * 0.78 * (0.9 + 0.18 * Math.sin(a * 2)),
    });
  }

  ctx.clearRect(0, 0, w, h);

  // Reference section (ground truth) — faint gray.
  ctx.fillStyle = "#c9c9d2";
  for (const p of base) {
    ctx.beginPath();
    ctx.arc(cx + p.x * scale, cy + p.y * scale, 2, 0, 7);
    ctx.fill();
  }

  // Moving section — purple.
  ctx.fillStyle = "#6633ee";
  for (const p of base) {
    let x = p.x;
    let y = p.y;
    if (mode === "torn") {
      // Torn flap on the right slides out + global misalignment.
      if (x > 0) {
        x += 0.34;
        y += 0.08;
      }
      const rot = 0.09;
      const dx = x;
      const dy = y;
      x = dx * Math.cos(rot) - dy * Math.sin(rot) + 0.05;
      y = dx * Math.sin(rot) + dy * Math.cos(rot) + 0.03;
    } else {
      // Aligned — tiny sub-pitch jitter only.
      x += (rnd() - 0.5) * 0.02;
      y += (rnd() - 0.5) * 0.02;
    }
    ctx.beginPath();
    ctx.arc(cx + x * scale, cy + y * scale, 2, 0, 7);
    ctx.fill();
  }
}
