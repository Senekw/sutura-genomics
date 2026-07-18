# Recommended pipeline

> Input: _3D organ mapping of human kidney, 10x Visium, 12 serial sections, want cell types and spatial domains_

## What we understood from your description

| Field | Value |
|---|---|
| Platform | 10x Visium (confidence: high) |
| Experiment type | 3D organ mapping (serial sections) (confidence: high) |
| Tissue | kidney |
| Serial sections | yes (12) |
| Samples/donors/conditions | not detected |
| Stated goals | alignment_3d, cell_typing, spatial_domains |
| Inferred goals | batch_correction |
| Single-cell reference | not stated |

## Pipeline at a glance

1. **Data loading & representation** → Scanpy
2. **Quality control & filtering** → Scanpy ⚠️
3. **Normalization & feature selection** → Scanpy
4. **Batch correction / integration** → Harmony (harmonypy) ⚠️
5. **Spatial alignment / 3D reconstruction** → PASTE / PASTE2 ⚠️
6. **Dimensionality reduction & clustering** → Scanpy
7. **Spot deconvolution** → cell2location ⚠️
8. **Spatial domain identification** → SpaGCN ⚠️
9. **Visualization & reporting** → Scanpy

## Detailed steps

### Step 1: Data loading & representation

_Purpose:_ Read raw platform output into a common in-memory representation (AnnData / SpatialData) so every downstream tool interoperates.
_Why here:_ Every pipeline starts by reading raw platform output into a common object.

**Recommended: Scanpy  (python, maturity: mature)**
  - Why: The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
  - Install: `pip install scanpy`
  - Run:

```python
import scanpy as sc
adata = sc.read_h5ad('data.h5ad')
sc.pp.calculate_qc_metrics(adata, inplace=True, percent_top=None)
adata = adata[adata.obs.n_genes_by_counts > 200]
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
sc.pp.pca(adata); sc.pp.neighbors(adata); sc.tl.leiden(adata)
```
  - Expected runtime: Seconds to a few minutes for <500k cells; minutes for millions.
  - Known limitations: QC thresholds are judgment calls, not defaults. Leiden resolution changes cluster count arbitrarily. Marker DE (rank_genes_groups) treats cells as independent replicates - do not use it for condition-level statistics.
  - Docs: https://scanpy.readthedocs.io

_Alternatives:_
**Alternative: Squidpy  (python, maturity: established)**
  - Scanpy's spatial companion: spatial neighbor graphs, Moran's I spatial autocorrelation, neighborhood enrichment, ligand-receptor (ligrec), and platform readers (Visium/Xenium/Vizgen/nanostring).
    Install: `pip install squidpy`
**Alternative: SpatialData / spatialdata-io  (python, maturity: established)**
  - Unified reader/representation across Visium, Visium HD, Xenium, MERSCOPE, CosMx, Stereo-seq. Keeps images, transcripts, shapes, and tables in one coordinate system - the cleanest way to start a multi-platform pipeline.
    Install: `pip install spatialdata spatialdata-io spatialdata-plot`

### Step 2: Quality control & filtering  [expert judgment required]

_Purpose:_ Remove low-quality cells/spots/bins and low-count genes; for imaging, filter by transcripts-per-cell, cell area, and negative-probe rate.
_Why here:_ Low-quality cells/spots and genes must be removed before any analysis.

> **HONESTY:** QC thresholds are tissue- and platform-specific. There is no universal cutoff; inspect distributions before choosing.

**Recommended: Scanpy  (python, maturity: mature)**
  - Why: The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
  - Install: `pip install scanpy`
  - Run:

```python
import scanpy as sc
adata = sc.read_h5ad('data.h5ad')
sc.pp.calculate_qc_metrics(adata, inplace=True, percent_top=None)
adata = adata[adata.obs.n_genes_by_counts > 200]
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
sc.pp.pca(adata); sc.pp.neighbors(adata); sc.tl.leiden(adata)
```
  - Expected runtime: Seconds to a few minutes for <500k cells; minutes for millions.
  - Known limitations: QC thresholds are judgment calls, not defaults. Leiden resolution changes cluster count arbitrarily. Marker DE (rank_genes_groups) treats cells as independent replicates - do not use it for condition-level statistics.
  - Docs: https://scanpy.readthedocs.io

_Alternatives:_
**Alternative: Squidpy  (python, maturity: established)**
  - Scanpy's spatial companion: spatial neighbor graphs, Moran's I spatial autocorrelation, neighborhood enrichment, ligand-receptor (ligrec), and platform readers (Visium/Xenium/Vizgen/nanostring).
    Install: `pip install squidpy`

> ⚠️ Platform note: Not single-cell. Spot composition confounds spatial DE and cell-cell communication inference.

### Step 3: Normalization & feature selection

_Purpose:_ Correct for sequencing depth / total-count differences and select informative genes.
_Why here:_ Depth/total-count differences must be corrected and informative genes selected.

**Recommended: Scanpy  (python, maturity: mature)**
  - Why: The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
  - Install: `pip install scanpy`
  - Run:

```python
import scanpy as sc
adata = sc.read_h5ad('data.h5ad')
sc.pp.calculate_qc_metrics(adata, inplace=True, percent_top=None)
adata = adata[adata.obs.n_genes_by_counts > 200]
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
sc.pp.pca(adata); sc.pp.neighbors(adata); sc.tl.leiden(adata)
```
  - Expected runtime: Seconds to a few minutes for <500k cells; minutes for millions.
  - Known limitations: QC thresholds are judgment calls, not defaults. Leiden resolution changes cluster count arbitrarily. Marker DE (rank_genes_groups) treats cells as independent replicates - do not use it for condition-level statistics.
  - Docs: https://scanpy.readthedocs.io

_Alternatives:_
**Alternative: Seurat (RPCA / CCA integration)  (r, maturity: mature)**
  - The R-ecosystem standard: SCTransform normalization + anchor-based (RPCA/CCA) integration + Azimuth reference mapping. Choose if your lab lives in R.
    Install: `install.packages('Seurat')  # R`

### Step 4: Batch correction / integration  [expert judgment required]

_Purpose:_ Remove technical variation between sections, samples, donors, or runs while (ideally) preserving biology, producing a shared embedding.
_Why here:_ You have 12 sections/samples; multiple sections/samples must be integrated into a shared embedding so that differences are biology, not batch.

> **HONESTY:** NOT SOLVED reliably. Every method can over-correct (erase real biological differences) or under-correct. Always sanity-check with known markers and by confirming that expected biological differences survive. This is especially dangerous in disease-vs-control designs where the effect you care about can be 'corrected' away.

**Recommended: Harmony (harmonypy)  (python, maturity: mature)**
  - Why: Fast, embedding-level batch correction integrated into scanpy (sc.external.pp.harmony_integrate). A sensible default first attempt because it's fast, corrects the PCA embedding (not counts), and is easy to compare against no-correction.
  - Install: `pip install harmonypy`
  - Run:

```python
import scanpy as sc
sc.pp.pca(adata)
sc.external.pp.harmony_integrate(adata, key='batch')
sc.pp.neighbors(adata, use_rep='X_pca_harmony'); sc.tl.leiden(adata)
```
  - Expected runtime: Seconds to minutes for hundreds of thousands of cells.
  - Known limitations: Corrects an embedding, not expression - you cannot get 'corrected counts' for DE. Can over-integrate and merge genuinely distinct populations; ALWAYS verify known markers/conditions survive. Batch correction is not solved.
  - Docs: https://github.com/slowkow/harmonypy

_Alternatives:_
**Alternative: scvi-tools (scVI / scANVI)  (python, maturity: established)**
  - Deep generative integration (scVI) and semi-supervised label transfer (scANVI); also hosts DestVI (spatial deconvolution) and Stereoscope. Preferred when you need a probabilistic model, count-level batch correction, or reference label transfer in one framework.
    Install: `pip install scvi-tools`
**Alternative: Scanorama  (python, maturity: established)**
  - Panorama-stitching integration that also returns batch-corrected expression (not just an embedding), useful when a downstream tool needs corrected features. Good second method to cross-check Harmony/scVI.
    Install: `pip install scanorama`

> ⚠️ HONEST LIMIT: batch correction is not reliably solved. It can erase real biology (over-correction) or leave batch structure (under-correction). Run WITH and WITHOUT correction, and confirm known markers and expected biological differences survive.

### Step 5: Spatial alignment / 3D reconstruction  [expert judgment required]

_Purpose:_ Register serial sections into a common coordinate framework (2D pairwise alignment or full 3D stack reconstruction).
_Why here:_ You described 12 serial sections; they must be registered into a common coordinate frame before any 3D or cross-section spatial analysis.

> **HONESTY:** Hard and imperfect. Section-to-section distortion, tears, folds, and unknown z-spacing all degrade results. Alignment quality must be inspected visually; quantitative scores can look fine while anatomy is wrong.

**Recommended: PASTE / PASTE2  (python, maturity: established)**
  - Why: Optimal-transport alignment of serial sections using both spatial coordinates and expression. PASTE builds a consensus/stacked 3D reconstruction; PASTE2 handles partial overlap between adjacent sections (the common real case). The standard OT baseline for serial-section registration.
  - Install: `pip install paste-bio   # PASTE; PASTE2 from the raphael-group repo`
  - Run:

```python
import paste as pst
# pairwise alignment of adjacent slices
pi = pst.pairwise_align(sliceA, sliceB)
# or full stack -> common coordinates
center_slice, pis = pst.center_align(reference, [s1, s2, s3])
```
  - Expected runtime: Seconds to minutes per section pair; OT scales with spot count (subsample very large sections).
  - Known limitations: Assumes adjacent sections are similar; large biological change or big z-gaps break it. Partial-overlap fraction (PASTE2 s) must be set. Alignment can look numerically fine while anatomy is subtly wrong - inspect visually.
  - Docs: https://github.com/raphael-group/paste2

**Optional refinement: Sutura Align (this project)  (python, maturity: research)**
  - Scope: OPTIONAL, HONEST SCOPE: Sutura Align does not replace the aligner above. It (1) routes each section pair to the best-performing existing aligner for that data regime, and (2) applies a fit-residual-GATED refinement on top of the base alignment (usually PASTE2). The gate means it only refines when the base fit is trustworthy and otherwise returns the base mapping unchanged, to avoid making things worse. It measurably lowers alignment error in our internal benchmarks but is research-stage and does not fix tissue distortion, tears, or folds.

_Alternatives:_
**Alternative: STalign  (python, maturity: emerging)**
  - Diffeomorphic (LDDMM) alignment that models smooth nonlinear tissue deformation - better than affine/OT when sections are warped or distorted. Works from images or cell centroids, good for imaging platforms.
    Install: `pip install STalign`
**Alternative: moscot  (python, maturity: emerging)**
  - Scalable optimal-transport toolkit (from the scverse/Theis lab) covering spatial mapping and serial-section alignment with GPU-backed solvers that scale better than classic PASTE on large data. Also does mapping single cells to space.
    Install: `pip install moscot`
**Alternative: GPSA  (python, maturity: research)**
  - Gaussian-Process Spatial Alignment learns a common coordinate system across slices probabilistically, giving uncertainty on the mapping. Useful when you want a principled shared 3D frame with uncertainty rather than a point estimate.
    Install: `pip install gpsa`

> ⚠️ HONEST LIMIT: serial-section alignment is hard and imperfect. Distortion, tears, folds, and unknown z-spacing degrade results, and a numerically good score can still hide wrong anatomy. Always overlay aligned sections and inspect landmarks visually.

### Step 6: Dimensionality reduction & clustering

_Purpose:_ PCA/latent embedding + neighbors graph + Leiden/Louvain clustering to define transcriptional groups prior to annotation.
_Why here:_ Needed to define transcriptional groups prior to annotation and domain analysis.

**Recommended: Scanpy  (python, maturity: mature)**
  - Why: The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
  - Install: `pip install scanpy`
  - Run:

```python
import scanpy as sc
adata = sc.read_h5ad('data.h5ad')
sc.pp.calculate_qc_metrics(adata, inplace=True, percent_top=None)
adata = adata[adata.obs.n_genes_by_counts > 200]
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
sc.pp.pca(adata); sc.pp.neighbors(adata); sc.tl.leiden(adata)
```
  - Expected runtime: Seconds to a few minutes for <500k cells; minutes for millions.
  - Known limitations: QC thresholds are judgment calls, not defaults. Leiden resolution changes cluster count arbitrarily. Marker DE (rank_genes_groups) treats cells as independent replicates - do not use it for condition-level statistics.
  - Docs: https://scanpy.readthedocs.io

### Step 7: Spot deconvolution  [expert judgment required]

_Purpose:_ For multi-cell spots (Visium) or coarse bins: estimate cell-type proportions per spot using a matched single-cell reference.
_Why here:_ This is a multi-cell spot platform, so per-spot cell identity means estimating cell-type PROPORTIONS (deconvolution), not single-cell labels.

> **HONESTY:** Results are only as good as the single-cell reference. A missing or mismatched cell type in the reference produces confident but wrong proportions. Validate against known anatomy.

**Recommended: cell2location  (python, maturity: established)**
  - Why: Bayesian spot deconvolution that estimates absolute cell-type abundance per spot from a matched single-cell reference. Well-validated on Visium; models technical variation explicitly. A default choice for Visium deconvolution.
  - Install: `pip install cell2location`
  - Run:

```python
import cell2location as c2l
# 1) estimate reference signatures from scRNA
# 2) map to spatial:
mod = c2l.models.Cell2location(adata_vis, cell_state_df=ref_sig, N_cells_per_location=8)
mod.train(max_epochs=30000)
adata_vis = mod.export_posterior(adata_vis)
```
  - Expected runtime: Tens of minutes to a few hours on GPU (long training); GPU strongly recommended.
  - Known limitations: Requires a matched scRNA reference; missing cell types produce wrong abundances. Long training. N_cells_per_location prior matters. Validate against known anatomy.
  - Docs: https://github.com/BayraktarLab/cell2location

_Alternatives:_
**Alternative: RCTD (spacexr)  (r, maturity: established)**
  - Robust Cell Type Decomposition; fast, well-validated, and handles platform effects between reference and spatial. 'doublet mode' is popular for near-single-cell spots. The R-side default for deconvolution.
    Install: `remotes::install_github('dmcable/spacexr')  # R`
**Alternative: scvi-tools (scVI / scANVI)  (python, maturity: established)**
  - Deep generative integration (scVI) and semi-supervised label transfer (scANVI); also hosts DestVI (spatial deconvolution) and Stereoscope. Preferred when you need a probabilistic model, count-level batch correction, or reference label transfer in one framework.
    Install: `pip install scvi-tools`

> ⚠️ Deconvolution REQUIRES a matched single-cell/nucleus reference for this tissue. No matched single-cell reference was mentioned. Obtain or generate one (matched organ + condition) first; a mismatched reference yields confident but wrong results.

### Step 8: Spatial domain identification  [expert judgment required]

_Purpose:_ Cluster cells/spots using expression AND spatial position into coherent tissue domains / niches.
_Why here:_ You want tissue domains/niches: cluster using expression AND spatial position.

> **HONESTY:** The number of domains is a user choice with no objective ground truth; different tools/resolutions give different domains. Interpret anatomically.

**Recommended: SpaGCN  (python, maturity: established)**
  - Why: Graph convolutional network that integrates expression, spatial location, and (optionally) histology into spatial domains. Widely cited, works across platforms, relatively light.
  - Install: `pip install SpaGCN`
  - Run:

```python
import SpaGCN as spg
adj = spg.calculate_adj_matrix(x=x, y=y, histology=False)
clf = spg.SpaGCN(); clf.set_l(l)
clf.train(adata, adj, num_pcs=50, n_clusters=7)
domains = clf.predict()
```
  - Expected runtime: Minutes; GPU optional.
  - Known limitations: Number of domains is user-specified. Histology integration needs a registered image. Sensitive to the smoothing parameter l.
  - Docs: https://github.com/jianhuupenn/SpaGCN

_Alternatives:_
**Alternative: BANKSY  (python, maturity: emerging)**
  - Augments each cell's expression with its neighborhood mean and azimuthal gradient, then clusters. One knob (lambda) smoothly trades off cell typing vs domain segmentation; very fast and scales to millions of cells. Increasingly a default for large imaging data.
    Install: `pip install banksy_py   # (R version: Banksy)`
**Alternative: BayesSpace  (r, maturity: established)**
  - Bayesian spatial clustering with a neighbor-smoothing prior; also does sub-spot resolution enhancement for Visium. A well-validated domain caller for spot data.
    Install: `BiocManager::install('BayesSpace')  # R`

### Step 9: Visualization & reporting

_Purpose:_ Interactive and publication-quality spatial visualization, including 3D viewing of reconstructed stacks.
_Why here:_ Inspect QC, segmentation, domains, and (if 3D) the reconstructed stack.

**Recommended: Scanpy  (python, maturity: mature)**
  - Why: The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
  - Install: `pip install scanpy`
  - Run:

```python
import scanpy as sc
adata = sc.read_h5ad('data.h5ad')
sc.pp.calculate_qc_metrics(adata, inplace=True, percent_top=None)
adata = adata[adata.obs.n_genes_by_counts > 200]
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
sc.pp.pca(adata); sc.pp.neighbors(adata); sc.tl.leiden(adata)
```
  - Expected runtime: Seconds to a few minutes for <500k cells; minutes for millions.
  - Known limitations: QC thresholds are judgment calls, not defaults. Leiden resolution changes cluster count arbitrarily. Marker DE (rank_genes_groups) treats cells as independent replicates - do not use it for condition-level statistics.
  - Docs: https://scanpy.readthedocs.io

**Optional refinement: napari (+ napari-spatialdata)  (python, maturity: established)**
  - Scope: Use napari to view the aligned 3D stack volumetrically and to QC segmentation masks.

_Alternatives:_
**Alternative: Squidpy  (python, maturity: established)**
  - Scanpy's spatial companion: spatial neighbor graphs, Moran's I spatial autocorrelation, neighborhood enrichment, ligand-receptor (ligrec), and platform readers (Visium/Xenium/Vizgen/nanostring).
    Install: `pip install squidpy`
**Alternative: SpatialData / spatialdata-io  (python, maturity: established)**
  - Unified reader/representation across Visium, Visium HD, Xenium, MERSCOPE, CosMx, Stereo-seq. Keeps images, transcripts, shapes, and tables in one coordinate system - the cleanest way to start a multi-platform pipeline.
    Install: `pip install spatialdata spatialdata-io spatialdata-plot`

---
_This recommendation orchestrates existing, real tools; it does not replace them or guarantee their output. Segmentation, batch correction, alignment, annotation, and deconvolution all have failure modes flagged above and require expert visual QC. Treat this as a starting scaffold, validate each step against your biology, and confirm tool versions/APIs before running._
