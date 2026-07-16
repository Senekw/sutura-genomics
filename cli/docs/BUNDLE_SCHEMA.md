# Sutura result-bundle schema

**Schema version: `1.0`**

The CLI writes one *result bundle* per job to the shared local store:

```
~/.sutura/results/<job_id>/
```

The viewer app reads these bundles; it never runs reconstruction itself. Nothing
here leaves the machine. `job_id` looks like `job-20260716-142530-a1b2c3`.

A bundle is **fully written** once `metadata.json` exists (it is written last).
Readers should treat a bundle without `metadata.json` as still in progress.

## Files

```
<job_id>/
  metadata.json         manifest + index (write-last; presence => complete)
  qc.json               per-section input QC
  routing.json          per-pair distribution-check / routing decision
  metrics.json          per-pair method used + metric/score (honest labels)
  reconstruction.json   3D serial-section point cloud
  report.md             human-readable summary
  alignment/
    pair_00__<ref>__to__<mov>/
      aligned.h5ad       AnnData of the moving section, with the alignment
```

### `metadata.json`
```jsonc
{
  "schema_version": "1.0",
  "sutura_version": "0.1.0",
  "job_id": "job-...",
  "created_utc": "2026-07-16T14:25:30+00:00",
  "status": "complete",            // running | complete | failed
  "backend": "rule",               // agent LLM backend: rule | cloud | ollama
  "engine": { "repo_root": "...", "checkpoint": "...", "scanpy": "...", "torch": "..." },
  "instruction": "align the sections in ./data and reconstruct in 3D",
  "inputs":   [ { "path": "...", "format": "h5ad", "n_spots": 3639, "n_genes": 33538 } ],
  "sections": [ { "id": "s1", "name": "DLPFC_151507", "format": "h5ad",
                  "n_spots": 3639, "n_genes": 33538,
                  "has_spatial": true, "has_layers": true, "source": "..." } ],
  "n_pairs": 1,
  "pairs": [ { "index": 0, "ref": "DLPFC_151507", "mov": "DLPFC_151508",
               "method": "sutura", "method_label": "Sutura (graph model)",
               "metric": "median_error_pitch", "score": 3.0,
               "has_ground_truth": true,
               "aligned_file": "alignment/pair_00__.../aligned.h5ad" } ],
  "artifacts": { "qc": "qc.json", "routing": "routing.json",
                 "metrics": "metrics.json", "reconstruction": "reconstruction.json",
                 "report": "report.md" },
  "warnings": []
}
```

### `qc.json`
```jsonc
{ "schema_version": "1.0",
  "sections": [ { "id": "s1", "name": "...", "pass": true, "n_spots": 3639,
                  "n_genes": 33538, "has_layers": true, "issue": null } ] }
```

### `routing.json`
Per pair, the distribution-check that decided the method:
```jsonc
{ "schema_version": "1.0",
  "pairs": [ { "ref": "s1", "mov": "s2", "ref_name": "...", "mov_name": "...",
               "routed_method": "Sutura (graph model)",
               "in_distribution": true, "confidence": 0.98,
               "maha": 1.1, "gene_overlap": 1.0, "reason": "..." } ] }
```

### `metrics.json`
Per pair, the method that actually produced the result and its score. Honest
labelling: `method_label` is exactly what ran; `reason` explains the routing;
`retry` flags a post-QC method switch.
```jsonc
{ "schema_version": "1.0",
  "pairs": [ { "index": 0, "ref": "...", "mov": "...",
               "method": "sutura", "method_label": "Sutura (graph model)",
               "reason": "in-distribution (Mahalanobis 1.10 < 2.5)",
               "metric": "median_error_pitch", "score": 3.0,
               "has_ground_truth": true, "in_distribution": true,
               "in_dist_confidence": 0.98, "mahalanobis": 1.1, "gene_overlap": 1.0,
               "footprint_coverage": 0.97, "retry": false, "runtime_seconds": 4.2,
               "candidates": [["sutura", 3.0]],
               "aligned_file": "alignment/pair_00__.../aligned.h5ad",
               "post_qc": { "verdict": "pass", "neighbor_consistency": 0.86,
                            "footprint_coverage": 0.97, "basis": "..." } } ] }
```
`metric` is either `median_error_pitch` (lower is better; requires ground truth,
e.g. Visium array coordinates) or `footprint_coverage` (0-1, higher is better;
used when no ground truth is derivable).

### `reconstruction.json`
A serial-section z-stack. `z` encodes section order (in-plane alignment is the
orchestrator's output); it is not measured depth.
```jsonc
{ "kind": "serial_section_zstack",
  "note": "z encodes section order (pairwise-to-neighbour alignment); ...",
  "z_spacing": 137.0, "pitch": 137.0,
  "n_sections": 2, "n_points": 7278,
  "bounds": { "min": [x,y,z], "max": [x,y,z] },
  "sections": [ { "index": 0, "name": "DLPFC_151507", "z": 0.0,
                  "n_points": 3639, "method": "reference" },
                { "index": 1, "name": "DLPFC_151508", "z": 137.0,
                  "n_points": 3639, "method": "Sutura (graph model)" } ],
  "point_fields": ["x", "y", "z", "section_index", "layer"],
  "points": [ [ 1234.5, 987.6, 0.0, 0, "Layer3" ], ... ] }
```

### `alignment/<pair>/aligned.h5ad`
The moving section as AnnData. Alignment lives in:
- `obsm["spatial_aligned"]` - aligned (x, y) coordinates in the reference frame.
- `obsm["spatial"]` - original coordinates (unchanged).
- `uns["sutura_alignment"]` - `{ method, reason, metric, score, ... }`.

## Honesty contract
Every pair is labelled with the method that produced it. Sutura's graph model is
used in-distribution; PASTE2 off-distribution. The bundle records the routing
reason and any post-QC method switch. This makes *best-available* alignment
automatic; it is not a claim to beat every method on every tissue.
