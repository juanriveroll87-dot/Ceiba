#!/usr/bin/env bash
# Run visible + hidden tests against a scheduler implementation.
#   ./check.sh                         # reference solution
#   ./check.sh path/to/scheduler.py    # a candidate's submission
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
impl="$(realpath "${1:-$here/scheduler.py}")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$impl" "$work/scheduler.py"
cp "$here/../candidate/test_scheduler.py" "$here/test_hidden.py" "$work/"
cd "$work"
python3 -m unittest -v test_scheduler test_hidden
