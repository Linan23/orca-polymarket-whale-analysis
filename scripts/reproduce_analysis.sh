#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/reproduce_analysis.sh [--structural-only]

Validate the public, repository-contained analysis contract without requiring
private datasets. Full report reproduction will be added behind an explicit
data manifest once the approved analytical snapshot is frozen.

Options:
  --structural-only  Validate analysis entrypoints and configuration only (default).
  --help             Show this help message.
EOF
}

mode=structural
while [[ $# -gt 0 ]]; do
  case "$1" in
    --structural-only) mode=structural ;;
    --help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

if [[ -x .venv/bin/python ]]; then
  orca_python=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  orca_python=python3
else
  echo "Python 3 is required." >&2
  exit 1
fi

if [[ "$mode" != structural ]]; then
  echo "Unsupported reproduction mode: $mode" >&2
  exit 2
fi

entrypoints=(
  analysis/profile_historical_data.py
  analysis/profile_category_reconstruction.py
  data_platform/jobs/export_market_ml_dataset.py
  data_platform/jobs/train_market_model.py
  data_platform/jobs/compare_market_model_families.py
  data_platform/jobs/analyze_market_whale_signal.py
  data_platform/jobs/analyze_whale_feature_ablation.py
  data_platform/jobs/analyze_market_movement_residuals.py
  data_platform/jobs/tune_market_movement_models.py
)

for entrypoint in "${entrypoints[@]}"; do
  if [[ ! -f "$entrypoint" ]]; then
    echo "Missing analysis entrypoint: $entrypoint" >&2
    exit 1
  fi
  "$orca_python" "$entrypoint" --help >/dev/null
done

"$orca_python" -m compileall -q data_platform/ml data_platform/jobs
"$orca_python" data_platform/tests/analytical_data_contract_check.py >/dev/null
"$orca_python" data_platform/tests/research_category_normalization_check.py >/dev/null

echo "Structural analysis contract passed."
echo "Full reproduction is intentionally disabled until a versioned dataset manifest and approved snapshot exist."
