#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
"$ROOT/scripts/setup_model.sh"
"$ROOT/scripts/bootstrap.sh"
cat <<'EOF'
Setup complete. Build the model with:
  JOBS=16 ./scripts/build_model.sh
Then run the smoke tests with:
  ./scripts/run_smoke.sh
EOF
