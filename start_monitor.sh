#!/bin/bash
# Starter Stabæk Drakt Monitor. Brukes av launchd-oppsettet for autostart.
# Kjører i ekte shell-kontekst med riktig PATH/miljø.

cd "$(dirname "$0")"

# Unbuffered output + ikke skriv .pyc (unngår race på __pycache__ ved
# samtidige oppstarter, som kunne blokkere import).
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
# Hindrer macOS objc-fork-safety-hang (STAT=U) når prosesser med
# nettverks-/krypto-biblioteker forkes i launchd-kontekst.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

PYTHON=/usr/local/bin/python3
[ -x "$PYTHON" ] || PYTHON=$(command -v python3 || command -v python)

if [ -z "$PYTHON" ]; then
  echo "FEIL: Finner ikke python3."
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starter monitor med $PYTHON"
exec "$PYTHON" monitor.py
