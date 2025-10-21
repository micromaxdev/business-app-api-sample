#!/bin/bash
# /home/dashdev/business-app-api-sample/start.sh
set -e

PROJECT_DIR="/home/dashdev/business-app-api-sample"
VENV_DIR="${PROJECT_DIR}/venv"

# activate venv
source "${VENV_DIR}/bin/activate"

# run uvicorn on LAN, port 2900
exec uvicorn main:app --host 0.0.0.0 --port 2900 --workers 1
