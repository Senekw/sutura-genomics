# Recommended pipeline

> Input: _Stereo-seq whole mouse embryo, single large section, want cell types and spatial domains across the whole organism_

## What we understood from your description

| Field | Value |
|---|---|
| Platform | Stereo-seq (BGI STOMICS) (confidence: high) |
| Experiment type | Developmental time series (confidence: low) |
| Tissue | embryo |
| Serial sections | no |
| Samples/donors/conditions | not detected |
| Stated goals | cell_typing, spatial_domains |
| Inferred goals | batch_correction, spatial_de |
| Single-cell reference | not stated |

## Pipeline at a glance

1. **Data loading & representation** → Stereopy
2. **Quality control & filtering** → Stereopy ⚠️
3. **Cell segmentation** → Stereopy ⚠️
4. **Normalization & feature selection** → Stereopy
5. **Dimensionality reduction & clustering** → Stereopy
6. **Cell type annotation** → CellTypist ⚠️
7. **Spatial domain identification** → SpaGCN ⚠️
8. **Spatially variable genes & differential expression** → Scanpy ⚠️
9. **Visualization & reporting** → Scanpy

## Read this first

> ⚠️ Experiment type inferred as 'Developmental time series' with low confidence.

## Detailed steps

### Step 1: Data loading & representation

_Purpose:_ Read raw platform output into a common in-memory representation (AnnData / SpatialData) so every downstream tool interoperates.
_Why here:_ Every pipeline starts by reading raw platform output into a common object.

**Recommended: Stereopy  (python, maturity: emerging)**
  - Why: BGI's official toolkit for Stereo-seq: reads GEF/GEM, does binning (bin20/bin50), cell segmentation from the ssDNA image, and standard clustering at scale.
  - Install: `pip install stereopy`
  - Run:

```python
import stereo as st
data = st.io.read_gef('SN.gef', bin_size=50)
data.tl.cal_qc()
data.tl.raw_checkpoint()
data.tl.normalize_total(); data.tl.log1p()
data.tl.highly_variable_genes(); data.tl.pca(); data.tl.neighbors(); data.tl.leiden()
```
  - Expected runtime: Minutes to hours; Stereo-seq FOVs are huge (cm-scale), memory-bound.
  - Known limitations: Bin-based analysis is not single-cell. Cell segmentation from ssDNA is imperfect. API differs from scanpy; conversion to AnnData needed for many downstream tools.
  - Docs: https://stereopy.readthedocs.io

_Alternatives:_
**Alternative: Scanpy  (python, maturity: mature)**
  - The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
    Install: `pip install scanpy`
**Alternative: Squidpy  (python, maturity: established)**
  - Scanpy's spatial companion: spatial neighbor graphs, Moran's I spatial autocorrelation, neighborhood enrichment, ligand-receptor (ligrec), and platform readers (Visium/Xenium/Vizgen/nanostring).
    Install: `pip install squidpy`

### Step 2: Quality control & filtering  [expert judgment required]

_Purpose:_ Remove low-quality cells/spots/bins and low-count genes; for imaging, filter by transcripts-per-cell, cell area, and negative-probe rate.
_Why here:_ Low-quality cells/spots and genes must be removed before any analysis.

> **HONESTY:** QC thresholds are tissue- and platform-specific. There is no universal cutoff; inspect distributions before choosing.

**Recommended: Stereopy  (python, maturity: emerging)**
  - Why: BGI's official toolkit for Stereo-seq: reads GEF/GEM, does binning (bin20/bin50), cell segmentation from the ssDNA image, and standard clustering at scale.
  - Install: `pip install stereopy`
  - Run:

```python
import stereo as st
data = st.io.read_gef('SN.gef', bin_size=50)
data.tl.cal_qc()
data.tl.raw_checkpoint()
data.tl.normalize_total(); data.tl.log1p()
data.tl.highly_variable_genes(); data.tl.pca(); data.tl.neighbors(); data.tl.leiden()
```
  - Expected runtime: Minutes to hours; Stereo-seq FOVs are huge (cm-scale), memory-bound.
  - Known limitations: Bin-based analysis is not single-cell. Cell segmentation from ssDNA is imperfect. API differs from scanpy; conversion to AnnData needed for many downstream tools.
  - Docs: https://stereopy.readthedocs.io

_Alternatives:_
**Alternative: Scanpy  (python, maturity: mature)**
  - The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
    Install: `pip install scanpy`
**Alternative: Squidpy  (python, maturity: established)**
  - Scanpy's spatial companion: spatial neighbor graphs, Moran's I spatial autocorrelation, neighborhood enrichment, ligand-receptor (ligrec), and platform readers (Visium/Xenium/Vizgen/nanostring).
    Install: `pip install squidpy`

> ⚠️ Platform note: Enormous data volume (memory/compute). Cell segmentation from ssDNA is imperfect; bin-based analysis is a common compromise but is not single-cell.

### Step 3: Cell segmentation  [UNSOLVED — expert judgment required]

_Purpose:_ Assign transcripts/signal to individual cells. Required for imaging-based and high-resolution binned platforms; not applicable to multi-cell Visium spots.
_Why here:_ This platform resolves individual transcripts/signal, so cells must be segmented before counts exist. Segmentation error propagates into every downstream number.

> **HONESTY:** UNSOLVED in the general case. Segmentation is the single largest source of error in imaging-based spatial data and every downstream count depends on it. Always visually QC boundaries; no tool is reliable across all tissues.

**Recommended: Stereopy  (python, maturity: emerging)**
  - Why: BGI's official toolkit for Stereo-seq: reads GEF/GEM, does binning (bin20/bin50), cell segmentation from the ssDNA image, and standard clustering at scale.
  - Install: `pip install stereopy`
  - Run:

```python
import stereo as st
data = st.io.read_gef('SN.gef', bin_size=50)
data.tl.cal_qc()
data.tl.raw_checkpoint()
data.tl.normalize_total(); data.tl.log1p()
data.tl.highly_variable_genes(); data.tl.pca(); data.tl.neighbors(); data.tl.leiden()
```
  - Expected runtime: Minutes to hours; Stereo-seq FOVs are huge (cm-scale), memory-bound.
  - Known limitations: Bin-based analysis is not single-cell. Cell segmentation from ssDNA is imperfect. API differs from scanpy; conversion to AnnData needed for many downstream tools.
  - Docs: https://stereopy.readthedocs.io

_Alternatives:_
**Alternative: Cellpose  (python, maturity: established)**
  - General-purpose deep-learning cell/nucleus segmentation from images (DAPI, membrane, H&E). The most widely used image-based segmenter; strong pretrained models plus fine-tuning.
    Install: `pip install cellpose`
**Alternative: Sopa  (python, maturity: emerging)**
  - Technology-agnostic pipeline that orchestrates segmentation (Cellpose/Baysor/others) and QC on top of SpatialData, with tiling for memory-safe processing of large imaging datasets. Good glue when you want a reproducible imaging pipeline rather than hand-wiring tools.
    Install: `pip install sopa`
**Alternative: StarDist  (python, maturity: established)**
  - Star-convex polygon nucleus segmentation; excellent on DAPI nuclei and the default nucleus caller inside bin2cell for Visium HD.
    Install: `pip install stardist`

### Step 4: Normalization & feature selection

_Purpose:_ Correct for sequencing depth / total-count differences and select informative genes.
_Why here:_ Depth/total-count differences must be corrected and informative genes selected.

**Recommended: Stereopy  (python, maturity: emerging)**
  - Why: BGI's official toolkit for Stereo-seq: reads GEF/GEM, does binning (bin20/bin50), cell segmentation from the ssDNA image, and standard clustering at scale.
  - Install: `pip install stereopy`
  - Run:

```python
import stereo as st
data = st.io.read_gef('SN.gef', bin_size=50)
data.tl.cal_qc()
data.tl.raw_checkpoint()
data.tl.normalize_total(); data.tl.log1p()
data.tl.highly_variable_genes(); data.tl.pca(); data.tl.neighbors(); data.tl.leiden()
```
  - Expected runtime: Minutes to hours; Stereo-seq FOVs are huge (cm-scale), memory-bound.
  - Known limitations: Bin-based analysis is not single-cell. Cell segmentation from ssDNA is imperfect. API differs from scanpy; conversion to AnnData needed for many downstream tools.
  - Docs: https://stereopy.readthedocs.io

_Alternatives:_
**Alternative: Scanpy  (python, maturity: mature)**
  - The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
    Install: `pip install scanpy`
**Alternative: Seurat (RPCA / CCA integration)  (r, maturity: mature)**
  - The R-ecosystem standard: SCTransform normalization + anchor-based (RPCA/CCA) integration + Azimuth reference mapping. Choose if your lab lives in R.
    Install: `install.packages('Seurat')  # R`

### Step 5: Dimensionality reduction & clustering

_Purpose:_ PCA/latent embedding + neighbors graph + Leiden/Louvain clustering to define transcriptional groups prior to annotation.
_Why here:_ Needed to define transcriptional groups prior to annotation and domain analysis.

**Recommended: Stereopy  (python, maturity: emerging)**
  - Why: BGI's official toolkit for Stereo-seq: reads GEF/GEM, does binning (bin20/bin50), cell segmentation from the ssDNA image, and standard clustering at scale.
  - Install: `pip install stereopy`
  - Run:

```python
import stereo as st
data = st.io.read_gef('SN.gef', bin_size=50)
data.tl.cal_qc()
data.tl.raw_checkpoint()
data.tl.normalize_total(); data.tl.log1p()
data.tl.highly_variable_genes(); data.tl.pca(); data.tl.neighbors(); data.tl.leiden()
```
  - Expected runtime: Minutes to hours; Stereo-seq FOVs are huge (cm-scale), memory-bound.
  - Known limitations: Bin-based analysis is not single-cell. Cell segmentation from ssDNA is imperfect. API differs from scanpy; conversion to AnnData needed for many downstream tools.
  - Docs: https://stereopy.readthedocs.io

_Alternatives:_
**Alternative: Scanpy  (python, maturity: mature)**
  - The backbone AnnData ecosystem. Nearly every other tool reads/writes its objects. Standard for QC, normalization, PCA, neighbors, Leiden clustering, and marker DE.
    Install: `pip install scanpy`

### Step 6: Cell type annotation  [expert judgment required]

_Purpose:_ Assign biological cell-type labels to single cells (imaging / HD) via reference mapping or marker-based manual annotation.
_Why here:_ Single-cell-resolution data supports per-cell annotation via reference mapping or marker-based labeling.

> **HONESTY:** Automated labels are a starting point, not ground truth. References rarely match your exact tissue/condition; marker-based confirmation and expert review are mandatory. Ambiguous or novel states will be mislabeled.

**Recommended: CellTypist  (python, maturity: established)**
  - Why: Fast logistic-regression cell-type classifier with many prebuilt immune/tissue models; great first-pass automated annotation for single-cell-resolution spatial data. You can also train on your own reference.
  - Install: `pip install celltypist`
  - Run:

```python
import celltypist
pred = celltypist.annotate(adata, model='Immune_All_Low.pkl', majority_voting=True)
adata = pred.to_adata()
```
  - Expected runtime: Seconds to minutes.
  - Known limitations: Prebuilt models are trained on scRNA and may not match a targeted spatial panel or your tissue/disease state. Confident labels can be wrong for novel states - confirm with markers.
  - Docs: https://www.celltypist.org

_Alternatives:_
**Alternative: scvi-tools (scVI / scANVI)  (python, maturity: established)**
  - Deep generative integration (scVI) and semi-supervised label transfer (scANVI); also hosts DestVI (spatial deconvolution) and Stereoscope. Preferred when you need a probabilistic model, count-level batch correction, or reference label transfer in one framework.
    Install: `pip install scvi-tools`
**Alternative: Tangram  (python, maturity: established)**
  - Maps a single-cell reference onto spatial data by learning a cell-to-spot probability matrix; used for label transfer (imaging) and deconvolution (spots), and to impute genes outside a targeted panel.
    Install: `pip install tangram-sc`

> ⚠️ Automated labels are a starting point, not truth. Confirm with canonical markers and expert review; novel/ambiguous states will be mislabeled.

### Step 7: Spatial domain identification  [expert judgment required]

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

### Step 8: Spatially variable genes & differential expression  [expert judgment required]

_Purpose:_ Identify genes that vary across space (SVG) and genes differentially expressed between conditions, domains, or cell types.
_Why here:_ You want spatially variable genes and/or differential expression.

> **HONESTY:** Spot-level DE is confounded by cell-type composition. For condition comparisons, pseudobulk per sample (not per cell/spot) to avoid pseudo-replication and false positives.

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
**Alternative: PyDESeq2 (pseudobulk DE)  (python, maturity: established)**
  - For disease-vs-control (or any condition) comparisons, the statistically correct approach is PSEUDOBULK: sum counts per sample x cell-type, then run DESeq2-style negative-binomial DE across samples. PyDESeq2 does this in Python; decoupler builds the pseudobulk matrix. This avoids the pseudo-replication that inflates per-cell DE false positives.
    Install: `pip install pydeseq2 decoupler`
**Alternative: SPARK / SPARK-X  (r, maturity: established)**
  - SPARK-X is a fast, scalable non-parametric test for spatially variable genes designed for large datasets (hundreds of thousands of cells). The go-to when SpatialDE is too slow.
    Install: `devtools::install_github('xzhoulab/SPARK')  # R`

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

_Alternatives:_
**Alternative: Squidpy  (python, maturity: established)**
  - Scanpy's spatial companion: spatial neighbor graphs, Moran's I spatial autocorrelation, neighborhood enrichment, ligand-receptor (ligrec), and platform readers (Visium/Xenium/Vizgen/nanostring).
    Install: `pip install squidpy`
**Alternative: SpatialData / spatialdata-io  (python, maturity: established)**
  - Unified reader/representation across Visium, Visium HD, Xenium, MERSCOPE, CosMx, Stereo-seq. Keeps images, transcripts, shapes, and tables in one coordinate system - the cleanest way to start a multi-platform pipeline.
    Install: `pip install spatialdata spatialdata-io spatialdata-plot`

---
_This recommendation orchestrates existing, real tools; it does not replace them or guarantee their output. Segmentation, batch correction, alignment, annotation, and deconvolution all have failure modes flagged above and require expert visual QC. Treat this as a starting scaffold, validate each step against your biology, and confirm tool versions/APIs before running._
