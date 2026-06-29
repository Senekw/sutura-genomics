"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, FileUp } from "lucide-react";

import { Background } from "@/components/ui/background-snippets";
import { Button } from "@/components/ui/button";

const ACCENT = "#6633ee";
const A_COLOR = "#c9c9d2"; // reference points (gray)
const B_RAW = "#e69f00"; // moving / misaligned (orange) — Figure 4 scheme
const B_ALN = "#0072b2"; // aligned (blue)        — Figure 4 scheme

// Deterministic point cloud (seeded LCG) so SSR and client render identically.
function makePoints(n: number, seed: number): [number, number][] {
  let s = seed >>> 0;
  const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const pts: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    const a = rnd() * Math.PI * 2;
    const r = Math.sqrt(rnd());
    pts.push([Math.cos(a) * r, Math.sin(a) * r * 0.82]);
  }
  return pts;
}

// ---------------------------------------------------------------- Step 1
function SectioningSVG() {
  return (
    <svg viewBox="0 0 320 200" className="h-full w-full">
      {/* tissue block */}
      <rect x="40" y="120" width="150" height="46" rx="8" fill="#efe9ff" stroke="#d8ccff" />
      <text x="115" y="148" textAnchor="middle" fontSize="11" fill="#7a6ab5">tissue block</text>
      {/* blade */}
      <motion.g
        initial={{ x: 120 }}
        animate={{ x: [120, -30, 120] }}
        transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
      >
        <polygon points="50,40 80,40 65,72" fill="#9aa0aa" />
        <rect x="58" y="36" width="14" height="10" rx="2" fill="#6b7280" />
      </motion.g>
      {/* thin section with a tear forming */}
      <motion.path
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5, duration: 0.8 }}
        d="M40 96 H150 a6 6 0 0 1 0 12 H112 l-8 -7 -8 7 H40 a6 6 0 0 1 0 -12 Z"
        fill="#fdf3e0"
        stroke={B_RAW}
        strokeWidth="1.5"
      />
      {/* tear highlight */}
      <motion.line
        x1="104" y1="96" x2="104" y2="108"
        stroke={B_RAW} strokeWidth="2" strokeDasharray="2 2"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.1 }}
      />
      <text x="95" y="90" fontSize="10" fill={B_RAW}>tear</text>
    </svg>
  );
}

// ---------------------------------------------------------------- Step 2
function VisiumSVG() {
  const dots = useMemo(() => {
    const out: [number, number][] = [];
    for (let r = 0; r < 9; r++)
      for (let c = 0; c < 14; c++) {
        if (Math.hypot(c - 6.5, (r - 4) * 1.4) < 7.2)
          out.push([40 + c * 17, 40 + r * 16]);
      }
    return out;
  }, []);
  return (
    <svg viewBox="0 0 320 200" className="h-full w-full">
      <rect x="24" y="24" width="272" height="152" rx="10" fill="#f7f6fb" stroke="#e6e1f5" />
      <text x="160" y="190" textAnchor="middle" fontSize="10" fill="#9aa0aa">Visium slide</text>
      {dots.map(([x, y], i) => (
        <motion.circle
          key={i}
          cx={x}
          cy={y}
          r="3.2"
          fill={ACCENT}
          initial={{ opacity: 0, scale: 0 }}
          animate={{ opacity: 0.85, scale: 1 }}
          transition={{ delay: 0.15 + i * 0.006, duration: 0.25 }}
        />
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------- Step 3
function UploadSVG() {
  return (
    <svg viewBox="0 0 320 200" className="h-full w-full">
      {/* dashboard window */}
      <rect x="28" y="26" width="264" height="148" rx="10" fill="#ffffff" stroke="#e6e1f5" />
      <rect x="28" y="26" width="264" height="22" rx="10" fill="#f3f0fb" />
      <circle cx="42" cy="37" r="3" fill="#e0b0b0" />
      <circle cx="54" cy="37" r="3" fill="#e6d3a0" />
      <circle cx="66" cy="37" r="3" fill="#b6dcb6" />
      {/* dropzone */}
      <rect x="56" y="64" width="208" height="92" rx="10" fill="#faf8ff"
        stroke={ACCENT} strokeWidth="1.5" strokeDasharray="6 5" />
      {/* dropped file chip */}
      <motion.g
        initial={{ y: -34, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.4, duration: 0.7, type: "spring", bounce: 0.35 }}
      >
        <rect x="118" y="92" width="84" height="26" rx="6" fill="#efe9ff" stroke="#d8ccff" />
        <text x="160" y="109" textAnchor="middle" fontSize="11" fill="#5b4bb0" fontFamily="monospace">
          data.h5ad
        </text>
      </motion.g>
      <text x="160" y="146" textAnchor="middle" fontSize="10" fill="#9aa0aa">
        drag &amp; drop your sections
      </text>
    </svg>
  );
}

// ---------------------------------------------------------------- Step 4
function PointPanel({
  label,
  movingColor,
  aligned,
}: {
  label: string;
  movingColor: string;
  aligned: boolean;
}) {
  const base = useMemo(() => makePoints(90, 7), []);
  // map normalized [-1,1] to panel coords
  const W = 150, H = 150, cx = W / 2, cy = H / 2, sx = 56, sy = 56;
  const toXY = (p: [number, number]) => [cx + p[0] * sx, cy + p[1] * sy] as const;
  return (
    <div className="flex flex-1 flex-col items-center">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[180px]">
        {/* reference A (gray) */}
        {base.map((p, i) => {
          const [x, y] = toXY(p);
          return <circle key={`a${i}`} cx={x} cy={y} r="2.1" fill={A_COLOR} />;
        })}
        {/* moving B */}
        {base.map((p, i) => {
          const [ax, ay] = toXY(p);
          // misaligned: rotate + offset, and a tear on the right half
          const torn = p[0] > 0.1;
          const rawX = ax + 14 + (torn ? 16 : 0);
          const rawY = ay + 9 + (torn ? 8 : 0);
          return (
            <motion.circle
              key={`b${i}`}
              r="2.1"
              fill={movingColor}
              initial={{ cx: rawX, cy: rawY }}
              animate={aligned ? { cx: ax + 0.6, cy: ay + 0.6 } : { cx: rawX, cy: rawY }}
              transition={{ duration: 1.1, delay: 0.2 + (i % 12) * 0.015, ease: "easeInOut" }}
            />
          );
        })}
      </svg>
      <span className="mt-1 text-[11px] text-muted-foreground">{label}</span>
    </div>
  );
}

function AlignmentSVG() {
  return (
    <div className="flex w-full items-center justify-center gap-4">
      <PointPanel label="Before: A + B misaligned (tear)" movingColor={B_RAW} aligned={false} />
      <ArrowRight className="h-5 w-5 shrink-0 text-muted-foreground" />
      <PointPanel label="After: Sutura aligns B onto A" movingColor={B_ALN} aligned={true} />
    </div>
  );
}

// ---------------------------------------------------------------- Steps data
const STEPS = [
  {
    title: "Serial sectioning",
    illo: <SectioningSVG />,
    caption:
      "Step 1: Serial sectioning. Physical cutting introduces tears — present in ~70% of real samples.",
  },
  {
    title: "Spatial capture",
    illo: <VisiumSVG />,
    caption:
      "Step 2: Spatial capture. 10x Visium captures gene expression at ~5,000 spots per section.",
  },
  {
    title: "Upload your data",
    illo: <UploadSVG />,
    caption:
      "Step 3: Upload your data. Drag and drop .h5ad files into the Sutura dashboard.",
  },
  {
    title: "Sutura alignment",
    illo: <AlignmentSVG />,
    caption:
      "Step 4: Get aligned coordinates. Sutura returns per-spot A-frame coordinates in under 24 hours, with comparison metrics vs PASTE2.",
  },
];

export default function SneakPeekPage() {
  const [step, setStep] = useState(0);
  const last = STEPS.length - 1;

  return (
    <main className="relative flex min-h-screen flex-col items-center px-6 py-14">
      <Background />

      <Link
        href="/"
        className="absolute left-6 top-6 flex items-center gap-1.5 text-sm font-light text-foreground/60 transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>

      {/* header */}
      <div className="mt-4 flex flex-col items-center text-center">
        <Image src="/sutura-logo.png" alt="" width={38} height={38}
          style={{ width: 38, height: 38 }} className="mb-3" priority />
        <h1 className="text-2xl font-light tracking-tight text-foreground">
          How Sutura works
        </h1>
        <p className="mt-1.5 max-w-md text-sm font-light text-muted-foreground">
          A 60-second look at the path from a torn tissue section to aligned,
          analysis-ready coordinates.
        </p>
      </div>

      {/* step indicators */}
      <div className="mt-8 flex items-center gap-2" aria-hidden="true">
        {STEPS.map((_, i) => (
          <button
            key={i}
            onClick={() => setStep(i)}
            className={`h-2 rounded-full transition-all ${
              i === step ? "w-7" : "w-2"
            }`}
            style={{ background: i <= step ? ACCENT : "#dcd6f0" }}
            aria-label={`Go to step ${i + 1}`}
          />
        ))}
      </div>

      {/* card */}
      <div className="mt-6 w-full max-w-xl">
        <div className="rounded-2xl border border-border bg-white/85 p-6 backdrop-blur-sm sm:p-8">
          <div className="mb-2 text-xs font-medium uppercase tracking-wider"
            style={{ color: ACCENT }}>
            Step {step + 1} of {STEPS.length} · {STEPS[step].title}
          </div>
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.35 }}
            >
              <div className="flex h-48 items-center justify-center">
                {STEPS[step].illo}
              </div>
              <p className="mt-4 text-center text-sm font-light leading-relaxed text-foreground">
                {STEPS[step].caption}
              </p>
            </motion.div>
          </AnimatePresence>

          {/* nav */}
          <div className="mt-6 flex items-center justify-between">
            <Button
              variant="outline"
              size="sm"
              className="rounded-full"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
            >
              <ArrowLeft className="mr-1 h-4 w-4" /> Previous
            </Button>
            {step < last ? (
              <Button
                size="sm"
                className="rounded-full text-white"
                style={{ background: ACCENT }}
                onClick={() => setStep((s) => Math.min(last, s + 1))}
              >
                Next <ArrowRight className="ml-1 h-4 w-4" />
              </Button>
            ) : (
              <span className="text-xs font-light text-muted-foreground">
                That&rsquo;s the workflow.
              </span>
            )}
          </div>
        </div>

        {/* bottom: confirmation + CTAs */}
        <div className="mt-6 flex flex-col items-center gap-4 text-center">
          <div className="flex items-center gap-2 rounded-full border border-[#6633ee]/20 bg-[#6633ee]/5 px-4 py-2">
            <Check className="h-4 w-4 text-[#6633ee]" />
            <span className="text-sm font-light text-foreground">
              We&rsquo;ll be in touch within 24 hours.
            </span>
          </div>
          <div className="flex flex-col items-center gap-3 sm:flex-row">
            <a
              href="https://www.biorxiv.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-light text-[#6633ee] underline-offset-4 hover:underline"
            >
              <FileUp className="h-4 w-4" /> Read the technical preprint &rarr;
            </a>
            <Link href="/">
              <Button variant="outline" size="sm" className="rounded-full">
                Back to home
              </Button>
            </Link>
          </div>
          <p className="text-[11px] font-light text-muted-foreground">
            Preprint link is a placeholder until the bioRxiv DOI is live.
          </p>
        </div>
      </div>
    </main>
  );
}
