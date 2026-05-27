#!/bin/bash
# Railway startup-script
# Kopier template-config til config.yaml hvis den ikke finnes
if [ ! -f config.yaml ]; then
    echo "Kopierer config.template.yaml → config.yaml"
    cp config.template.yaml config.yaml
fi
exec python monitor.py
