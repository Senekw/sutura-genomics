process SAMPLESHEET_CHECK {
    tag "$samplesheet.name"
    label 'process_single'

    input:
    path samplesheet

    output:
    path 'validated.csv',                          emit: csv
    path '*.skipped.metrics.json', optional: true, emit: skipped_metrics
    path 'skipped.csv',            optional: true, emit: skipped
    path 'versions.yml',                           emit: versions

    script:
    def on_missing = params.on_missing ?: 'skip'
    """
    check_samplesheet.py \\
        --input ${samplesheet} \\
        --output validated.csv \\
        --skipped skipped.csv \\
        --launch-dir "${workflow.launchDir}" \\
        --on-missing ${on_missing}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
