#!/usr/bin/env bash
#
# End-to-end orchestration script.
#
# Usage:
#   ./scripts/run_all.sh          # Run everything
#   ./scripts/run_all.sh etl      # Run only the ETL stage
#   ./scripts/run_all.sh feast    # Run only Feast apply + materialize
#   ./scripts/run_all.sh pipeline # Run only the ML pipeline
#
set -euo pipefail
cd "$(dirname "$0")/.."

STAGE="${1:-all}"

# ── Helper ──────────────────────────────────────────────────────────────
banner() { echo -e "\n═══════════════════════════════════════"; echo "  $1"; echo "═══════════════════════════════════════"; }

# ── 0. Generate sample data ─────────────────────────────────────────────
if [[ "$STAGE" == "all" || "$STAGE" == "data" ]]; then
    banner "STAGE 0 – Generate sample dataset"
    python data/generate_dataset.py
fi

# ── 1. ETL: MinIO → PostgreSQL ──────────────────────────────────────────
if [[ "$STAGE" == "all" || "$STAGE" == "etl" ]]; then
    banner "STAGE 1 – ETL (MinIO → PostgreSQL)"
    python -m src.etl.run_etl
fi

# ── 2. Feast: apply + materialize ───────────────────────────────────────
if [[ "$STAGE" == "all" || "$STAGE" == "feast" ]]; then
    banner "STAGE 2 – Feast apply"
    cd src/feature_store && feast apply && cd ../..

    banner "STAGE 2 – Feast materialize"
    python -m src.feature_store.feast_workflow materialize
fi

# ── 3. Pipeline: extract → validate → engineer → train → eval → register
if [[ "$STAGE" == "all" || "$STAGE" == "pipeline" ]]; then
    banner "STAGE 3 – ML Pipeline"
    python -m src.pipeline.run_pipeline
fi

# ── 4. Compile KFP pipeline YAML ────────────────────────────────────────
if [[ "$STAGE" == "all" || "$STAGE" == "kfp" ]]; then
    banner "STAGE 4 – Compile Kubeflow Pipeline"
    python -m src.pipeline.kfp_pipeline
fi

banner "DONE"
