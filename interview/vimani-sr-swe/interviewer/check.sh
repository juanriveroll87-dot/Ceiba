#!/usr/bin/env bash
# Run visible + hidden tests against a budget.py implementation.
#   ./check.sh                      # reference solution
#   ./check.sh path/to/budget.py    # a candidate's submission
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
impl="$(realpath "${1:-$here/budget.py}")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$impl" "$work/budget.py"
cp "$here/../candidate/test_budget.py" "$here/test_hidden.py" "$work/"
cd "$work"
python3 -m unittest -v test_budget test_hidden
