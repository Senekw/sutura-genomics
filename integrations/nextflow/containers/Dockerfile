# syntax=docker/dockerfile:1
#############################################################################
# sutura-align  -  self-contained alignment engine + Nextflow, for HPC/cloud
#############################################################################
# Build from the module directory (this is the build context):
#
#     cd integrations/nextflow
#     docker build -f containers/Dockerfile -t suturagenomics/sutura-align:1.0.0 .
#
# The image bundles: the pinned Python engine, the frozen model + basis assets, the
# vendored engine code, the pipeline itself, AND Nextflow + a JRE - so the same image
# can either (a) run a single alignment directly, or (b) run the whole pipeline
# in-container on a machine that only has Docker/Apptainer.
#############################################################################
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="sutura-align" \
      org.opencontainers.image.description="Distribution-routed spatial section alignment (engine + Nextflow)" \
      org.opencontainers.image.vendor="Sutura Genomics" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/Senekw/sutura-genomics"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    SUTURA_ENGINE_ROOT=/opt/sutura

# --- system deps: JRE for Nextflow, procps (`ps`) required by Nextflow, curl, git ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        procps \
        curl \
        ca-certificates \
        bash \
    && rm -rf /var/lib/apt/lists/*

# --- Python engine dependencies (pinned; CPU torch) ---
COPY containers/requirements-container.txt /tmp/requirements-container.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/requirements-container.txt

# --- Nextflow (pinned) so the pipeline can run entirely inside this image ---
ENV NXF_VER=24.10.4 \
    NXF_HOME=/opt/nextflow \
    NXF_OFFLINE=false
RUN mkdir -p /opt/nextflow \
    && curl -fsSL https://github.com/nextflow-io/nextflow/releases/download/v24.10.4/nextflow-24.10.4-dist \
        -o /usr/local/bin/nextflow \
    && chmod +x /usr/local/bin/nextflow

# --- engine code (vendored) + frozen assets ---
# vendored src closure -> importable as the engine's src/
COPY engine/ /opt/sutura/src/
# frozen model, basis and distribution reference -> results/ (src default paths)
RUN mkdir -p /opt/sutura/results
COPY assets/shared_basis.npz assets/arca_shared_basis.pt assets/dist_reference.npz \
     /opt/sutura/results/

# --- the pipeline module itself (bin/, main.nf, modules/, conf/, assets/) ---
COPY . /opt/sutura/integrations/nextflow/
RUN chmod +x /opt/sutura/integrations/nextflow/bin/*.py

# put the CLI tools on PATH so `docker run <img> sutura_align.py ...` works directly
ENV PATH=/opt/sutura/integrations/nextflow/bin:$PATH

WORKDIR /work

# default: print the aligner help
CMD ["sutura_align.py", "--help"]
