process SUTURA_ALIGN {
    tag "$meta.pair_id"
    label 'process_medium'

    // A single bad pair must not kill the run. A handled failure exits 0 (a metrics
    // record with status=failed is still produced); a hard crash (OOM, etc.) is
    // isolated by the error strategy so the remaining pairs still complete.
    errorStrategy { params.strict ? 'terminate' : (task.attempt <= 1 ? 'retry' : 'ignore') }
    maxRetries 1

    publishDir "${params.outdir}/aligned", mode: params.publish_dir_mode,
        pattern: "*.{aligned.h5ad,coords.csv}"
    publishDir "${params.outdir}/metrics", mode: params.publish_dir_mode,
        pattern: "*.metrics.json"

    input:
    tuple val(meta), path(reference), path(moving)

    output:
    path "*.metrics.json",                        emit: metrics
    path "*.aligned.h5ad", optional: true,        emit: h5ad
    path "*.coords.csv",   optional: true,        emit: coords

    script:
    def gate    = meta.gate_refine ? '--gate-refine' : ''
    def gate_o  = params.gate_order ? "--gate-order ${params.gate_order}" : ''
    def sub     = params.subsample  ? "--subsample ${params.subsample}"   : ''
    def knn     = params.knn        ? "--knn ${params.knn}"               : ''
    def strict  = params.strict     ? '--strict'                          : ''
    def eroot   = params.engine_root ? "--engine-root ${params.engine_root}" : ''
    """
    sutura_align.py \\
        --reference ${reference} \\
        --moving    ${moving} \\
        --pair-id   ${meta.pair_id} \\
        --method    ${meta.method} \\
        --output-format ${params.output_format} \\
        --min-spots ${params.min_spots} \\
        --seed      ${params.seed} \\
        --outdir    . \\
        ${gate} ${gate_o} ${sub} ${knn} ${strict} ${eroot}
    """

    stub:
    """
    echo '{"pair_id":"${meta.pair_id}","status":"ok","method":"stub","metrics":{}}' > ${meta.pair_id}.metrics.json
    """
}
