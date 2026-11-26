#!/usr/bin/env bash
# Verification command for this repository.
#
# The Stop hook (~/.claude/hooks/verify-before-stop.sh) looks for this file
# first, runs it as `bash .claude/verify.sh` from the repository root, and
# treats exit code 0 as "verified". Without it the hook found no test command
# it recognised here — there is no pyproject.toml, Makefile or package.json at
# the root — so it ran nothing and every change went unverified.
#
# The suite is safe to run on every turn: the tests use a throwaway SQLite file
# in a temp directory and stub the Instagram layer, so they touch neither
# data/instatracker.db nor the network.
#
# Run it by hand the same way the hook does:  bash .claude/verify.sh

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

# pytest is a development dependency (backend/requirements-dev.txt), so it may
# live in a virtual environment someone added, or in the Python 3.10 that
# start.bat uses. Take the first interpreter that can actually import it.
INTERPRETER=""
for candidate in \
  ".venv/Scripts/python.exe" \
  ".venv/bin/python" \
  "venv/Scripts/python.exe" \
  "venv/bin/python"
do
  if [ -x "$candidate" ] && "$candidate" -c "import pytest" >/dev/null 2>&1; then
    INTERPRETER="$candidate"
    break
  fi
done

if [ -z "$INTERPRETER" ]; then
  # The Windows launcher pins the same 3.10 the application runs on; plain
  # "python" on Windows can be the Store stub, so it comes last.
  if command -v py >/dev/null 2>&1 && py -3.10 -c "import pytest" >/dev/null 2>&1; then
    INTERPRETER="py -3.10"
  elif command -v python3 >/dev/null 2>&1 && python3 -c "import pytest" >/dev/null 2>&1; then
    INTERPRETER="python3"
  elif command -v python >/dev/null 2>&1 && python -c "import pytest" >/dev/null 2>&1; then
    INTERPRETER="python"
  fi
fi

if [ -z "$INTERPRETER" ]; then
  echo "pytest bulunamadı, bu yüzden hiçbir test çalıştırılmadı." >&2
  echo "Kur:  py -3.10 -m pip install -r backend/requirements-dev.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org" >&2
  exit 1
fi

# The tests add backend/ to sys.path themselves and import config, database and
# services by their bare names, so they have to run with backend/ as the
# working directory.
cd backend || exit 1
exec $INTERPRETER -m pytest tests -q
