#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/verify_repository.sh [--quick]

Run repository checks that do not require private data or a running database.

Options:
  --quick  Skip the production frontend build (lint still runs).
  --help   Show this help message.
EOF
}

quick=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) quick=1 ;;
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

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd git
require_cmd npm
require_cmd docker

if [[ -x .venv/bin/python ]]; then
  orca_python=.venv/bin/python
else
  require_cmd python3
  orca_python=python3
fi

if [[ ! -d my-app/node_modules ]]; then
  echo "Frontend dependencies are missing. Run: npm --prefix my-app ci" >&2
  exit 1
fi

echo "[verify] secret scan"
"$orca_python" scripts/secret_scan.py

echo "[verify] Python compilation"
"$orca_python" -m compileall -q \
  data_platform \
  scripts \
  build_dashboard_snapshot.py \
  build_home_summary_snapshot.py \
  build_research_analytics_snapshot.py \
  bootstrap_db.py

echo "[verify] analytical data contract"
"$orca_python" data_platform/tests/analytical_data_contract_check.py

echo "[verify] research category normalization"
"$orca_python" data_platform/tests/research_category_normalization_check.py

echo "[verify] category validation sample"
"$orca_python" data_platform/tests/category_validation_sample_check.py

echo "[verify] Docker Compose configuration"
docker compose config --quiet

echo "[verify] frontend lint"
npm --prefix my-app run lint

if [[ "$quick" -eq 0 ]]; then
  echo "[verify] frontend production build"
  npm --prefix my-app run build
fi

echo "Repository verification passed. Database-backed checks remain in .github/workflows/smoke.yml."
