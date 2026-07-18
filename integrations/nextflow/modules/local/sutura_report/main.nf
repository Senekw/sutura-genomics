process SUTURA_REPORT {
    label 'process_single'

    publishDir "${params.outdir}/report", mode: params.publish_dir_mode

    input:
    path metrics_files

    output:
    path 'sutura_report.html', emit: report
    path 'summary.csv',        emit: summary
    path 'versions.yml',       emit: versions

    script:
    """
    make_report.py \\
        --metrics-dir . \\
        --html sutura_report.html \\
        --summary summary.csv \\
        --run-name "${params.run_name ?: workflow.runName}"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
