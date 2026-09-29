#!/bin/bash
# PreToolUse (Bash): JSON を stdin で受け、拒否は stderr と exit 2。
exec python3 "$(dirname "$0")/gcloud-policy.py"
