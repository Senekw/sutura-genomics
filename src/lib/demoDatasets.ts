// Registry for the demo's selectable datasets. The dashboard lists these; the
// processing + results views look up the selected one (by id, stored in
// sessionStorage) to drive labels, the 3D volume, and the breakdown/benchmark.
//
// DLPFC Br5292 is real (spatialLIBD). Breast + Kidney use plausible synthetic
// data (clearly marked) so the platform reads as multi-tissue.

export type Region = {
  label: string;
  color: string;
  count: string;
  acc: string;
  resid: string; // median residual displacement for this class, px
};
export type BenchRow = {
  method: string;
  median: string;
  p90: string;
  acc: string;
  strong?: boolean;
};

export type DemoDataset = {
  id: string;
  name: string;
  tissue: string;
  badge: string;
  real: boolean;
  cardSpots: string;
  spotsRegistered: string;
  sections: string;
  stack: string; // /demo/<file>.json
  classLabel: string; // "Cortical layer" | "Region" | "Compartment"
  suturaPx: number;
  paste2Px: number;
  coverage: string; // fraction of the reference footprint covered by the alignment
  meta: { label: string; value: string }[];
  detail: [string, string][];
  regions: Region[];
  benchmark: BenchRow[];
};

export const DATASETS: DemoDataset[] = [
  {
    id: "dlpfc",
    name: "DLPFC Br5292",
    tissue: "Human dorsolateral prefrontal cortex",
    badge: "Reference",
    real: true,
    cardSpots: "4,384",
    spotsRegistered: "17,127",
    sections: "4 adjacent (151507–151510)",
    stack: "/demo/br5292_stack.json",
    classLabel: "Cortical layer",
    suturaPx: 109,
    paste2Px: 732,
    coverage: "99.4%",
    meta: [
      { label: "Platform", value: "10x Visium" },
      { label: "Spots", value: "4,384" },
      { label: "Sections", value: "4 adjacent" },
    ],
    detail: [
      ["Species", "Human"],
      ["Tissue", "Dorsolateral prefrontal cortex"],
      ["Donor", "Br5292"],
      ["Platform", "10x Genomics Visium"],
      ["Sections", "4 adjacent (151507–151510)"],
      ["Total spots", "17,127 across all slices"],
      ["Gene panel", "33,538 genes"],
      ["Annotations", "L1–L6 + WM cortical layers"],
      ["Source", "spatialLIBD (Maynard et al. 2021)"],
    ],
    regions: [
      { label: "L1", color: "#5e4fa2", count: "3,859", acc: "60.4%", resid: "118 px" },
      { label: "L2", color: "#3a7ecf", count: "1,763", acc: "63.8%", resid: "104 px" },
      { label: "L3", color: "#66c2a5", count: "5,960", acc: "65.6%", resid: "98 px" },
      { label: "L4", color: "#a6d96a", count: "1,361", acc: "59.8%", resid: "131 px" },
      { label: "L5", color: "#fee08b", count: "1,985", acc: "65.0%", resid: "101 px" },
      { label: "L6", color: "#fdae61", count: "1,338", acc: "63.6%", resid: "108 px" },
      { label: "WM", color: "#d53e4f", count: "861", acc: "67.0%", resid: "96 px" },
    ],
    benchmark: [
      { method: "Sutura", median: "109 px", p90: "187 px", acc: "63.8%", strong: true },
      { method: "PASTE2", median: "732 px", p90: "1,204 px", acc: "60.2%" },
      { method: "STalign", median: "866 px", p90: "1,442 px", acc: "58.1%" },
      { method: "GPSA", median: "931 px", p90: "1,523 px", acc: "57.4%" },
      { method: "Random baseline", median: "2,532 px", p90: "3,891 px", acc: "18.7%" },
    ],
  },
  {
    id: "breast",
    name: "Breast Tumor HTAN",
    tissue: "Human breast (invasive carcinoma)",
    badge: "Demo",
    real: false,
    cardSpots: "~6,000",
    spotsRegistered: "6,000",
    sections: "4 adjacent",
    stack: "/demo/breast_htan_stack.json",
    classLabel: "Region",
    suturaPx: 124,
    paste2Px: 803,
    coverage: "98.1%",
    meta: [
      { label: "Platform", value: "10x Visium" },
      { label: "Spots", value: "~6,000" },
      { label: "Sections", value: "4 adjacent" },
    ],
    detail: [
      ["Species", "Human"],
      ["Tissue", "Breast, invasive carcinoma"],
      ["Donor", "HTAN-BR-01"],
      ["Platform", "10x Genomics Visium"],
      ["Sections", "4 adjacent"],
      ["Total spots", "~6,000 across all slices"],
      ["Gene panel", "18,085 genes"],
      ["Annotations", "Tumor / stroma / immune / necrosis / duct / vessel"],
      ["Source", "HTAN-style (synthetic demo data)"],
    ],
    regions: [
      { label: "Tumor", color: "#d6336c", count: "2,530", acc: "61.2%", resid: "121 px" },
      { label: "Stroma", color: "#7048e8", count: "2,835", acc: "58.4%", resid: "128 px" },
      { label: "Immune", color: "#1c7ed6", count: "317", acc: "57.1%", resid: "139 px" },
      { label: "Necrosis", color: "#495057", count: "82", acc: "62.8%", resid: "118 px" },
      { label: "Duct", color: "#37b24d", count: "83", acc: "60.3%", resid: "126 px" },
      { label: "Vessel", color: "#f08c00", count: "153", acc: "55.9%", resid: "145 px" },
    ],
    benchmark: [
      { method: "Sutura", median: "124 px", p90: "214 px", acc: "59.6%", strong: true },
      { method: "PASTE2", median: "803 px", p90: "1,345 px", acc: "54.1%" },
      { method: "STalign", median: "902 px", p90: "1,511 px", acc: "52.7%" },
      { method: "GPSA", median: "977 px", p90: "1,602 px", acc: "51.9%" },
      { method: "Random baseline", median: "2,744 px", p90: "4,118 px", acc: "16.2%" },
    ],
  },
  {
    id: "kidney",
    name: "Kidney PCEN",
    tissue: "Human kidney",
    badge: "Demo",
    real: false,
    cardSpots: "~3,500",
    spotsRegistered: "3,501",
    sections: "3 adjacent",
    stack: "/demo/kidney_pcen_stack.json",
    classLabel: "Compartment",
    suturaPx: 131,
    paste2Px: 771,
    coverage: "97.6%",
    meta: [
      { label: "Platform", value: "10x Visium" },
      { label: "Spots", value: "~3,500" },
      { label: "Sections", value: "3 adjacent" },
    ],
    detail: [
      ["Species", "Human"],
      ["Tissue", "Kidney"],
      ["Donor", "PCEN-K3"],
      ["Platform", "10x Genomics Visium"],
      ["Sections", "3 adjacent"],
      ["Total spots", "~3,500 across all slices"],
      ["Gene panel", "21,412 genes"],
      ["Annotations", "Cortex / medulla / glomeruli / tubules / vessel"],
      ["Source", "PCEN-style (synthetic demo data)"],
    ],
    regions: [
      { label: "Cortex", color: "#4263eb", count: "1,238", acc: "58.9%", resid: "128 px" },
      { label: "Medulla", color: "#ae3ec9", count: "918", acc: "60.2%", resid: "124 px" },
      { label: "Glomeruli", color: "#e8590c", count: "229", acc: "55.4%", resid: "148 px" },
      { label: "Prox tubule", color: "#2f9e44", count: "464", acc: "56.1%", resid: "137 px" },
      { label: "Dist tubule", color: "#66a80f", count: "516", acc: "55.8%", resid: "139 px" },
      { label: "Vessel", color: "#f03e3e", count: "136", acc: "54.6%", resid: "151 px" },
    ],
    benchmark: [
      { method: "Sutura", median: "131 px", p90: "226 px", acc: "57.3%", strong: true },
      { method: "PASTE2", median: "771 px", p90: "1,288 px", acc: "55.4%" },
      { method: "STalign", median: "889 px", p90: "1,477 px", acc: "53.0%" },
      { method: "GPSA", median: "948 px", p90: "1,566 px", acc: "52.1%" },
      { method: "Random baseline", median: "2,610 px", p90: "3,977 px", acc: "17.1%" },
    ],
  },
];

const STORAGE_KEY = "sutura_demo_dataset";

export function getDataset(id: string | null | undefined): DemoDataset {
  return DATASETS.find((d) => d.id === id) ?? DATASETS[0];
}

export function selectDataset(id: string): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(STORAGE_KEY, id);
  }
}

export function currentDatasetId(): string {
  if (typeof window === "undefined") return DATASETS[0].id;
  return window.sessionStorage.getItem(STORAGE_KEY) ?? DATASETS[0].id;
}
