#!/bin/sh
# Build the standalone `agent-sandbox` executable for the current OS and CPU
# into dist-exe/. Run it from a virtual environment that has the package
# installed with the `server` extra and PyInstaller:
#
#   pip install ".[server]" pyinstaller==6.22.3
#   sh scripts/build_executable.sh
set -eu
python -m PyInstaller --onefile --noconfirm --clean --log-level WARN \
  --name agent-sandbox \
  --distpath dist-exe --workpath build/pyinstaller --specpath build/pyinstaller \
  --collect-submodules uvicorn \
  --collect-submodules agent_sandbox \
  scripts/pyinstaller_entry.py
