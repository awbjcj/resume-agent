#!/bin/sh
set -e
python -m resume_agent.deploy
exec resume-agent serve --mode hosted --host 0.0.0.0 --port "${PORT:-8000}"
