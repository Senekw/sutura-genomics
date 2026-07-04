// Persistent demo settings (account, default alignment parameters, export
// format). localStorage-backed so they survive between sessions. The alignment
// parameters are recorded on each run and reflected in the pipeline labels.

export type OutputFormat = "csv" | "json" | "h5ad";

export type DemoSettings = {
  account: { name: string; email: string; organization: string };
  params: {
    referenceSection: string; // which section is held fixed
    tearSensitivity: number; // 0–8
    knn: number; // k for the kNN graph
  };
  outputFormat: OutputFormat;
};

const KEY = "sutura_demo_settings";

export const REFERENCE_OPTIONS = ["First section", "Middle section", "Last section"];
export const OUTPUT_OPTIONS: { value: OutputFormat; label: string }[] = [
  { value: "csv", label: "CSV" },
  { value: "h5ad", label: "h5ad (AnnData JSON)" },
  { value: "json", label: "JSON" },
];

export const DEFAULT_SETTINGS: DemoSettings = {
  account: {
    name: "Rushil Maniar",
    email: "suturagenomics@gmail.com",
    organization: "Sutura Genomics",
  },
  params: { referenceSection: "First section", tearSensitivity: 4, knn: 6 },
  outputFormat: "csv",
};

export function getSettings(): DemoSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw);
      // shallow-merge so new fields fall back to defaults
      return {
        account: { ...DEFAULT_SETTINGS.account, ...(s.account || {}) },
        params: { ...DEFAULT_SETTINGS.params, ...(s.params || {}) },
        outputFormat: s.outputFormat || DEFAULT_SETTINGS.outputFormat,
      };
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_SETTINGS;
}

export function saveSettings(s: DemoSettings): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}
