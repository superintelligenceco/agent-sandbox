#!/bin/bash
# The script behind docs/assets/demo.gif. It drives a running server with curl.
# Record it with asciinema and render the GIF with agg:
#
#   AGENT_SANDBOX_API_KEY=<key> asciinema rec --cols 118 --rows 26 -c scripts/demo.sh demo.cast
#   agg --font-size 14 --idle-time-limit 2 demo.cast docs/assets/demo.gif
API=${API:-http://localhost:8080/v1}
sb() { curl -s -H "Authorization: Bearer $AGENT_SANDBOX_API_KEY" -H "Content-Type: application/json" "$@"; }
run() { printf '\033[1;32m$\033[0m '; for ((i=0;i<${#1};i++)); do printf '%s' "${1:i:1}"; sleep 0.02; done; echo; sleep 0.3; eval "$1"; sleep 1.2; }
note() { printf '\033[2m# %s\033[0m\n' "$1"; sleep 0.6; }
note "Create a sandbox: no network, read-only rootfs, non-root user"
run 'SB=$(sb -X POST $API/sandboxes -d "{\"image\": \"python:3.12-slim\"}" | jq -r .id); echo $SB'
note "Write code and run it"
run 'sb -X PUT "$API/sandboxes/$SB/files?path=app.py" --data-binary "print(sum(range(10)))" | jq -c "{path, size}"'
run 'sb -X POST $API/sandboxes/$SB/exec -d "{\"command\": \"python3 app.py && id\"}" | jq -c "{stdout, exit_code}"'
note "Snapshot, break it, roll back"
run 'SNAP=$(sb -X POST $API/sandboxes/$SB/snapshots -d "{}" | jq -r .id); echo $SNAP'
run 'sb -X POST $API/sandboxes/$SB/exec -d "{\"command\": \"rm app.py; python3 app.py\"}" | jq -c "{stderr, exit_code}"'
run 'sb -X POST $API/sandboxes/$SB/rollback -d "{\"snapshot_id\": \"$SNAP\"}" | jq -c "{id, status}"'
run 'sb -X POST $API/sandboxes/$SB/exec/stream -d "{\"command\": \"python3 app.py\"}"'
note "Clean up"
run 'sb -X DELETE -o /dev/null -w "%{http_code}\n" $API/sandboxes/$SB'
sleep 1.5
