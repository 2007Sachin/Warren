#!/usr/bin/env bash
# Deploy latest main to the VPS. Run from your dev machine / CI.
set -euo pipefail
VPS=${VPS_HOST:?"set VPS_HOST=user@your.vps.ip"}
ssh "$VPS" 'cd /opt/mirror-trading-bot && git pull && pip3 install -r requirements.txt && echo deployed'
