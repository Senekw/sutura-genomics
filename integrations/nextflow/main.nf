#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Sutura Genomics  |  sutura-align
    Spatial-transcriptomics section alignment as a reproducible pipeline step
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Aligns pairs of spatial sections (Space Ranger dirs or AnnData .h5ad) using the
    distribution-routed Sutura orchestrator (shared-basis GNN in-distribution, PASTE2
    partial-OT off-distribution) with an optional training-free gate refinement, and
    emits aligned coordinates, per-pair metrics, and an aggregate HTML report.

    Docs:  integrations/nextflow/README.md
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

nextflow.enable.dsl = 2

include { SAMPLESHEET_CHECK } from './modules/local/samplesheet_check/main.nf'
include { SUTURA_ALIGN      } from './modules/local/sutura_align/main.nf'
include { SUTURA_REPORT     } from './modules/local/sutura_report/main.nf'


// --------------------------------------------------------------------------- //
//  help + parameter validation
// --------------------------------------------------------------------------- //
def helpMessage() {
    log.info """
    ==========================================================================
     sutura-align  -  spatial section alignment pipeline
    ==========================================================================

    Usage:
      nextflow run integrations/nextflow/main.nf \\
          --input samplesheet.csv \\
          --outdir results \\
          -profile docker

    Required:
      --input          Samplesheet CSV (columns: pair_id,reference,moving[,method,gate_refine])
      --outdir         Output directory

    Key options (defaults in nextflow.config, per-row values override these):
      --method         auto | sutura | paste2          (default: ${params.method})
      --gate_refine    apply the gate refinement         (default: ${params.gate_refine})
      --gate_order     rigid | affine | quadratic        (default: ${params.gate_order})
      --subsample      cap each section to N spots, 0=off (default: ${params.subsample})
      --output_format  h5ad | csv | both                 (default: ${params.output_format})
      --min_spots      minimum spots for QC               (default: ${params.min_spots})
      --strict         fail the pipeline on a bad pair    (default: ${params.strict})

    Profiles:
      -profile test              tiny built-in DLPFC run (proof of function)
      -profile docker            run every step in the Sutura container
      -profile singularity       run every step in an Apptainer/Singularity image
      -profile slurm             submit each pair as a SLURM job (HPC)
      -profile local             everything on the current machine (default)

    Resume an interrupted run by adding -resume.
    """.stripIndent()
}

if (params.help) {
    helpMessage()
    exit 0
}

if (!params.input) {
    log.error "ERROR: --input samplesheet is required. Run with --help for usage."
    exit 1
}
if (!params.outdir) {
    log.error "ERROR: --outdir is required."
    exit 1
}


// --------------------------------------------------------------------------- //
//  workflow
// --------------------------------------------------------------------------- //
workflow {

    ch_input = Channel.fromPath(params.input, checkIfExists: true)

    // 1. validate the samplesheet up front (fail fast on a malformed sheet)
    SAMPLESHEET_CHECK(ch_input)

    // 2. parse validated rows into per-pair channels of (meta, reference, moving).
    //    check_samplesheet.py has already guaranteed structure + path existence, so
    //    staging here is safe; file() lets Nextflow stage/mount for containers + HPC.
    ch_pairs = SAMPLESHEET_CHECK.out.csv
        .splitCsv(header: true, strip: true)
        .map { row ->
            def meta = validateRow(row)
            tuple(meta,
                  file(meta.reference, checkIfExists: true),
                  file(meta.moving,    checkIfExists: true))
        }

    // 3. align every pair (failures are isolated - see errorStrategy in the module)
    SUTURA_ALIGN(ch_pairs)

    // 4. aggregate all metrics - aligned pairs (ok/failed) AND skipped pairs (missing
    //    inputs) - into one report, so nothing silently disappears from the run.
    ch_metrics = SUTURA_ALIGN.out.metrics
        .mix(SAMPLESHEET_CHECK.out.skipped_metrics.flatten())
        .collect()
    SUTURA_REPORT(ch_metrics)

    SUTURA_REPORT.out.report.view { "Report written: ${it}" }
}


// --------------------------------------------------------------------------- //
//  per-row validation / defaulting (keeps bad rows from silently misbehaving)
// --------------------------------------------------------------------------- //
def validateRow(row) {
    def id = (row.pair_id ?: '').trim()
    if (!id) {
        error "Samplesheet row is missing 'pair_id': ${row}"
    }
    if (!row.reference?.trim()) {
        error "Row '${id}' is missing 'reference' path"
    }
    if (!row.moving?.trim()) {
        error "Row '${id}' is missing 'moving' path"
    }
    def method = (row.method ?: params.method).trim()
    if (!(method in ['auto', 'sutura', 'paste2'])) {
        error "Row '${id}' has invalid method '${method}' (expected auto|sutura|paste2)"
    }
    def gate = row.containsKey('gate_refine') && row.gate_refine?.trim() ?
        (row.gate_refine.trim().toLowerCase() in ['true', '1', 'yes', 'on']) :
        params.gate_refine
    return [
        pair_id     : id,
        reference   : row.reference.trim(),
        moving      : row.moving.trim(),
        method      : method,
        gate_refine : gate
    ]
}
