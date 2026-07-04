"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";

import Sidebar from "@/components/demo/Sidebar";
import { isAuthed } from "@/lib/demoAuth";
import {
  getSettings,
  saveSettings,
  DEFAULT_SETTINGS,
  REFERENCE_OPTIONS,
  OUTPUT_OPTIONS,
  type DemoSettings,
  type OutputFormat,
} from "@/lib/demoSettings";

const fieldCls =
  "h-11 w-full rounded-lg border border-input bg-white px-3.5 text-sm text-foreground outline-none transition-all hover:border-muted-foreground/40 focus:border-[#6633ee] focus:ring-2 focus:ring-[#6633ee]/15";
const labelCls = "text-[13px] text-muted-foreground";

function Select({
  id,
  value,
  onChange,
  children,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="relative">
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={fieldCls + " appearance-none pr-9"}
      >
        {children}
      </select>
      <svg
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden
      >
        <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );
}

export default function DemoSettingsPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [s, setS] = useState<DemoSettings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!isAuthed()) {
      router.replace("/demo/login");
      return;
    }
    setS(getSettings());
    setReady(true);
  }, [router]);

  const acc = (k: keyof DemoSettings["account"], v: string) => {
    setSaved(false);
    setS((p) => ({ ...p, account: { ...p.account, [k]: v } }));
  };
  const par = (k: keyof DemoSettings["params"], v: string | number) => {
    setSaved(false);
    setS((p) => ({ ...p, params: { ...p.params, [k]: v } }));
  };

  const onSave = () => {
    saveSettings(s);
    setSaved(true);
  };

  if (!ready) return <div className="min-h-screen bg-[#f7f6fb]" />;

  return (
    <div className="flex min-h-screen bg-[#f7f6fb] text-foreground">
      <Sidebar active="settings" />
      <main className="flex-1 px-6 py-8 sm:px-10 sm:py-12">
        <div className="mx-auto max-w-2xl">
          <h1 className="text-2xl font-light tracking-tight text-foreground">Settings</h1>
          <p className="mt-1 text-sm font-light text-muted-foreground">
            Your account and default alignment parameters. Saved to this browser.
          </p>

          {/* Account */}
          <section className="mt-8 rounded-2xl border border-border bg-white p-6 sm:p-7">
            <h2 className="text-[15px] font-normal text-foreground">Account</h2>
            <div className="mt-4 flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="name" className={labelCls}>Name</label>
                <input id="name" className={fieldCls} value={s.account.name} onChange={(e) => acc("name", e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="email" className={labelCls}>Email</label>
                <input id="email" type="email" className={fieldCls} value={s.account.email} onChange={(e) => acc("email", e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="org" className={labelCls}>Organization</label>
                <input id="org" className={fieldCls} value={s.account.organization} onChange={(e) => acc("organization", e.target.value)} />
              </div>
            </div>
          </section>

          {/* Alignment parameters */}
          <section className="mt-4 rounded-2xl border border-border bg-white p-6 sm:p-7">
            <h2 className="text-[15px] font-normal text-foreground">Default alignment parameters</h2>
            <p className="mt-1 text-[12.5px] font-light text-muted-foreground">
              Applied to new alignment runs and recorded on each run.
            </p>
            <div className="mt-4 flex flex-col gap-5">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="ref" className={labelCls}>Reference section</label>
                <Select id="ref" value={s.params.referenceSection} onChange={(v) => par("referenceSection", v)}>
                  {REFERENCE_OPTIONS.map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </Select>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <label htmlFor="tear" className={labelCls}>Tear sensitivity</label>
                  <span className="tabular-nums text-[13px] font-normal text-[#6633ee]">
                    {s.params.tearSensitivity.toFixed(1)}
                  </span>
                </div>
                <input
                  id="tear"
                  type="range"
                  min={0}
                  max={8}
                  step={0.5}
                  value={s.params.tearSensitivity}
                  onChange={(e) => par("tearSensitivity", parseFloat(e.target.value))}
                  className="h-1.5 w-full cursor-pointer accent-[#6633ee]"
                />
                <div className="flex justify-between text-[11px] font-light text-muted-foreground">
                  <span>0 · rigid</span>
                  <span>8 · large tears</span>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <label htmlFor="knn" className={labelCls}>k (kNN graph)</label>
                <input
                  id="knn"
                  type="number"
                  min={2}
                  max={20}
                  value={s.params.knn}
                  onChange={(e) => par("knn", Math.max(2, Math.min(20, parseInt(e.target.value || "6", 10))))}
                  className={fieldCls + " w-32"}
                />
              </div>
            </div>
          </section>

          {/* Output format */}
          <section className="mt-4 rounded-2xl border border-border bg-white p-6 sm:p-7">
            <h2 className="text-[15px] font-normal text-foreground">Output format</h2>
            <p className="mt-1 text-[12.5px] font-light text-muted-foreground">
              Default coordinate-export type for report downloads.
            </p>
            <div className="mt-4 max-w-xs">
              <Select id="fmt" value={s.outputFormat} onChange={(v) => { setSaved(false); setS((p) => ({ ...p, outputFormat: v as OutputFormat })); }}>
                {OUTPUT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </div>
          </section>

          <div className="mt-6 flex items-center gap-3">
            <button
              type="button"
              onClick={onSave}
              className="inline-flex items-center gap-2 rounded-full bg-[#6633ee] px-7 py-3 text-[15px] font-normal text-white shadow-sm shadow-[#6633ee]/25 transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0]"
            >
              Save settings
            </button>
            {saved && (
              <span className="inline-flex items-center gap-1.5 text-[13px] font-light text-[#6633ee]">
                <Check className="h-4 w-4" strokeWidth={2.5} /> Saved
              </span>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
