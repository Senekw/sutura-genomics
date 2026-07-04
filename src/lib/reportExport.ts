// Real, client-side report export for an alignment run. Produces a genuine
// downloadable file in the selected format:
//   - csv   : a flat metrics + per-region table
//   - json  : the full structured report
//   - h5ad  : the aligned spot coordinates + labels serialized as an AnnData-
//             shaped JSON (obsm/obs/uns) — a real file, honestly labeled as the
//             JSON serialization (true HDF5 binary isn't produced in-browser).

import type { Run } from "./demoRuns";
import { getDataset } from "./demoDatasets";
import type { OutputFormat } from "./demoSettings";

const SPOT_PITCH_PX = 137;

function slug(s: string) {
  return s.replace(/[^\w.-]+/g, "_");
}

function triggerDownload(filename: string, mime: string, data: BlobPart) {
  const url = URL.createObjectURL(new Blob([data], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function toCsv(run: Run): string {
  const ds = getDataset(run.datasetId);
  const rows: string[][] = [
    ["field", "value"],
    ["dataset", ds.name],
    ["tissue", ds.tissue],
    ["sections", run.sections],
    ["status", run.status],
    ["timestamp", new Date(run.timestamp).toISOString()],
    ["median_error_px", String(run.medianErrorPx)],
    ["spot_pitch_px", String(SPOT_PITCH_PX)],
    ["footprint_coverage", run.coverage],
    ["spots_registered", run.spots],
    ["reference_section", run.params.referenceSection],
    ["tear_sensitivity", String(run.params.tearSensitivity)],
    ["knn_k", String(run.params.knn)],
    [],
    [ds.classLabel, "spots", "accuracy", "residual_px"],
    ...ds.regions.map((r) => [r.label, r.count.replace(/,/g, ""), r.acc, r.resid.replace(/[^\d]/g, "")]),
  ];
  return rows
    .map((cells) => cells.map((c) => (/[",\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(","))
    .join("\n");
}

function toJson(run: Run): string {
  const ds = getDataset(run.datasetId);
  return JSON.stringify(
    {
      dataset: { id: ds.id, name: ds.name, tissue: ds.tissue, sections: run.sections },
      run: {
        id: run.id,
        status: run.status,
        timestamp: new Date(run.timestamp).toISOString(),
        params: run.params,
      },
      metrics: {
        medianErrorPx: run.medianErrorPx,
        spotPitchPx: SPOT_PITCH_PX,
        coverage: run.coverage,
        spotsRegistered: run.spots,
        vsPaste2: `${(ds.paste2Px / ds.suturaPx).toFixed(1)}x`,
      },
      breakdown: ds.regions.map((r) => ({
        label: r.label,
        spots: r.count,
        accuracy: r.acc,
        residualPx: parseInt(r.resid.replace(/[^\d]/g, ""), 10),
      })),
    },
    null,
    2
  );
}

// AnnData-shaped JSON from the precomputed aligned volume for this dataset.
async function toH5adJson(run: Run): Promise<string> {
  const ds = getDataset(run.datasetId);
  const res = await fetch(ds.stack);
  const stack = await res.json();
  const spatial: number[][] = [];
  const layer: number[] = [];
  stack.slices.forEach((sl: { xy: [number, number][]; layer: number[] }, si: number) => {
    sl.xy.forEach((xy, i) => {
      spatial.push([xy[0], xy[1], si * (stack.spacing ?? 30)]);
      layer.push(sl.layer[i]);
    });
  });
  return JSON.stringify({
    _note: "AnnData-shaped JSON serialization of the aligned Sutura volume.",
    obsm: { spatial },
    obs: { layer, layer_names: stack.layers },
    uns: {
      dataset: ds.name,
      median_error_px: run.medianErrorPx,
      spot_pitch_px: SPOT_PITCH_PX,
      coverage: run.coverage,
      sections: run.sections,
      params: run.params,
    },
  });
}

export async function downloadReport(run: Run, format: OutputFormat): Promise<void> {
  const ds = getDataset(run.datasetId);
  const base = `${slug(ds.name)}_${run.id}`;
  if (format === "csv") {
    triggerDownload(`${base}.csv`, "text/csv", toCsv(run));
  } else if (format === "json") {
    triggerDownload(`${base}.report.json`, "application/json", toJson(run));
  } else {
    triggerDownload(`${base}.h5ad.json`, "application/json", await toH5adJson(run));
  }
}
