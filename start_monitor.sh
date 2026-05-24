#!/bin/bash
# Starter Stabæk Drakt Monitor i bakgrunnen og logger til en fil.
# Brukes av launchd-oppsettet for autostart.

cd "$(dirname "$0")"

# Finn python3 (fungerer med systeminstallasjon og Homebrew/pyenv)
PYTHON=$(command -v python3 || command -v python)

if [ -z "$PYTHON" ]; then
  echo "FEIL: Finner ikke python3. Installer Python fra https://www.python.org/downloads/"
  exit 1
fi

echo "Starter monitor med $PYTHON"
exec "$PYTHON" monitor.py
