"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Check, RotateCcw, Move3d } from "lucide-react";

import { Logo } from "@/components/logo";
import { isAuthed } from "@/lib/demoAuth";

// 3D viewer is client-only (three.js) — never server-render it.
const TissueStack3D = dynamic(() => import("./TissueStack3D"), { ssr: false });

// Real medians from Sutura's internal DLPFC benchmark (see public/live-demo.html).
const SUTURA_PX = 103;
const PASTE2_PX = 729;
const PITCH_PX = 137; // one Visium spot pitch
const RATIO = (PASTE2_PX / SUTURA_PX).toFixed(1); // ~7.1×
const MAXERR = 900;

// Cortical-layer legend — palette matches research/src/make_stack_json.py.
const LEGEND = [
  ["L1", "#5e4fa2"],
  ["L2", "#3a7ecf"],
  ["L3", "#66c2a5"],
  ["L4", "#a6d96a"],
  ["L5", "#fee08b"],
  ["L6", "#fdae61"],
  ["WM", "#d53e4f"],
] as const;

export default function DemoResultsPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
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
    const id = window.setTimeout(() => setBars(true), 200);
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
            DLPFC Br5292 aligned volume
          </h1>
          <p className="mt-2 max-w-xl text-sm font-light leading-relaxed text-muted-foreground">
            Four serial sections (151507–151510) registered into a single 3D
            volume. Sutura recovers the true tissue geometry straight through the
            tear, staying below one spot pitch where optimal-transport pipelines
            drift.
          </p>
        </div>

        {/* 3D stacked tissue block */}
        <div className="mt-8 overflow-hidden rounded-2xl border border-border bg-white">
          <div className="relative h-[440px] w-full [background:radial-gradient(120%_120%_at_50%_0%,#faf9ff_0%,#ffffff_60%)]">
            <TissueStack3D />
            <div className="pointer-events-none absolute left-4 top-3.5 flex items-center gap-1.5 text-[11px] font-light uppercase tracking-[0.14em] text-[#6633ee]">
              <Move3d className="h-3.5 w-3.5" strokeWidth={1.8} />
              4 slices · drag to rotate · scroll to zoom
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border px-4 py-3">
            <span className="text-[12px] font-light text-muted-foreground">Cortical layer</span>
            {LEGEND.map(([label, color]) => (
              <span key={label} className="inline-flex items-center gap-1.5 text-[12px] font-light text-foreground">
                <i
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: color }}
                />
                {label}
              </span>
            ))}
          </div>
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
                17,536
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
