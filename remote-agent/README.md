# AIRS Remote Agent

This is the outbound-only agent that lets AIRS investigate and remediate a
Linux host without inbound SSH. The agent polls the AIRS API, executes one
allowlisted action, and posts a bounded/redacted result.

## Safety model

- No shell execution. Every action is a fixed function in `app/actions.py`.
- The server validates action IDs and parameters against its own catalog.
- Destructive actions also require server-side approval bound to the exact
  incident, target agent, action, parameters, risk, expiry, and approver.
- `AIRS_ENABLE_REMEDIATION=false` by default, so a diagnostic-only agent cannot
  restart services or terminate processes even if it receives such a job.
- Service names must be listed in `AIRS_ALLOWED_SERVICES` (the `.service`
  suffix is optional in the allowlist).
- Disk inspection is restricted to `AIRS_ALLOWED_DISK_ROOTS`.
- `terminate_process` refuses PID 1, the agent itself, root-owned processes,
  critical process names, and any process whose start time, owner, or command
  no longer matches the evidence the operator approved.
- Output is size-bounded and redacted before it is posted to the server.
- Results are stored locally first, so a failed HTTP post can be retried after
  a restart. A remediation that started before a crash is never replayed
  automatically; it is reported as `UNKNOWN` for human reconciliation.

This is a constrained remote-operations daemon, not a sandbox. Run it on a
dedicated VM or host with the minimum privileges needed, keep the token secret,
and use TLS outside a local lab.

## Install

```bash
cd remote-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# edit .env
```

The state directory must be writable:

```bash
sudo install -d -m 0700 /var/lib/airs-agent
```

Run interactively:

```bash
set -a
. ./.env
set +a
.venv/bin/python -m app.main
```

## systemd

`install.sh` copies the unit but does not enable it automatically:

```bash
sudo ./install.sh
sudo editor /etc/airs-agent/agent.env
sudo systemctl enable --now airs-agent
journalctl -u airs-agent -f
```

The example unit runs as root because restarting arbitrary systemd services
requires the system bus. If you only need diagnostics, create a less
privileged account and omit `AIRS_ENABLE_REMEDIATION`. For remediation, a
dedicated host is safer than sharing a general-purpose server.

## Local lab

1. Start AIRS locally.
2. As an ADMIN, create an agent in the AIRS UI or with:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/agents \
  -H "Authorization: Bearer $AIRS_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"display_name":"lab-target-1","hostname":"lab-target-1","agent_key":"lab-target-1"}'
```

3. Put the returned token (shown once) in `remote-agent/.env`.
4. Set `AIRS_ALLOWED_SERVICES` to a disposable test service.
5. Start the agent and send a Grafana webhook whose `labels.agent_id` is
   `lab-target-1` (or whose `instance` matches the registered hostname).
6. Start the investigation from the incident page. Diagnostic jobs appear in
   the investigation timeline; a destructive proposal waits for RESPONDER+
   approval.

## Development checks

```bash
python -m compileall app
uv run --no-project --with pytest --with httpx python -m pytest -q
AIRS_BASE_URL=http://127.0.0.1:8000 AIRS_AGENT_TOKEN=x \
  python -c "from app.config import AgentConfig; print(AgentConfig.from_env())"
```
