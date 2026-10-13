#!/bin/sh
# Smoke test of the built wheel on a clean Linux: no system fonts, no browser,
# nothing but uv. Run it from the repo root after `uv build`:
#
#   docker run --rm -v "$PWD/dist:/dist:ro" -v "$PWD/examples:/examples:ro" \
#     -v "$PWD/scripts/smoke.sh:/smoke.sh:ro" \
#     ghcr.io/astral-sh/uv:python3.11-bookworm-slim /smoke.sh
#
# Add --platform linux/amd64 to try x86_64 on an ARM machine. Alpine is not
# supported: the typst package publishes no musllinux wheel.
set -eu
W=$(ls /dist/*.whl)
cd "$(mktemp -d)"
echo "== system: $(. /etc/os-release; echo $PRETTY_NAME) $(uname -m), python $(python3 -V 2>&1 | cut -d' ' -f2)"
echo "== system fonts: $(fc-list 2>/dev/null | wc -l || echo 0) (fc-list $(command -v fc-list >/dev/null && echo present || echo absent))"
hc() { uvx -q --from "$W" honest-cv "$@"; }
echo "== build"
hc build /examples/ada -l en -l es -o out
ls out
echo "== verify"
hc verify out/*.pdf
echo "== score"
hc score /examples/ada -k "Kubernetes,Terraform,Go" -p "Rust,Scala"
echo "== init a fresh profile"
hc init fresh >/dev/null && ls fresh
echo "== checklists"
hc checklist list | head -3
hc checklist new fresh backend-go engineering-lead >/dev/null && grep -c '^- \[' fresh/checklist.md
echo "== import (JSON Resume)"
cat > resume.json <<'JSON'
{"basics": {"name": "Smoke Test", "email": "smoke@example.com", "label": "Engineer",
            "summary": "Checks that a wheel works on a clean machine."},
 "work": [{"name": "Example Co", "position": "Engineer", "startDate": "2020-01",
           "highlights": ["Kept the build green."]}],
 "skills": [{"name": "Go"}]}
JSON
hc import imported resume.json | head -3
hc build imported -o imported-out | head -1
echo "== cover letter"
printf 'I am applying for the Platform Engineer role.\n\nI led a 40-service migration to Kubernetes.\n' > letter.txt
hc letter build /examples/ada letter.txt --company "Acme" --role "Platform Engineer" -o letter-out
echo "== MCP stdio handshake"
# Keep stdin open a moment: a real client does, and on EOF the server stops
# before answering requests still in flight.
{ printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 '{"jsonrpc":"2.0","id":3,"method":"prompts/list"}'; sleep 5; } \
 | timeout 60 uvx -q --from "$W" honest-cv serve --profile /examples/ada > mcp.out || true
python3 - mcp.out <<'PY'
import json, sys
msgs = {m.get("id"): m for m in map(json.loads, open(sys.argv[1]))}
print("server:", msgs[1]["result"]["serverInfo"]["name"], "| protocol", msgs[1]["result"]["protocolVersion"])
tools = [t["name"] for t in msgs[2]["result"]["tools"]]
prompts = [p["name"] for p in msgs[3]["result"]["prompts"]]
print(f"tools ({len(tools)}):", ", ".join(tools))
print(f"prompts ({len(prompts)}):", ", ".join(prompts))
PY
echo "== OK"
