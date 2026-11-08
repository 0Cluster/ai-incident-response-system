import { useState } from "react";
import { roleAtLeast, useMe } from "../api/auth";
import { apiErrorMessage } from "../api/client";
import {
  useAgents,
  useCreateAgent,
  useRotateAgentCredential,
  useSetAgentStatus,
} from "../api/remote";
import type { AgentProvision, RemoteAgent } from "../api/remote";

const inputCls = "rounded-md border px-2 py-1.5 text-sm";

function fmtDate(value: string | null): string {
  if (!value) return "never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function relative(value: string | null): string {
  if (!value) return "never";
  const ms = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(ms)) return "unknown";
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function online(agent: RemoteAgent): boolean {
  if (!agent.last_seen_at || agent.status !== "ACTIVE") return false;
  return Date.now() - new Date(agent.last_seen_at).getTime() < 90_000;
}

function statusClass(agent: RemoteAgent): string {
  if (agent.status === "REVOKED") return "bg-red-100 text-red-800";
  if (agent.status === "DISABLED") return "bg-gray-200 text-gray-700";
  return online(agent)
    ? "bg-green-100 text-green-800"
    : "bg-amber-100 text-amber-800";
}

function statusLabel(agent: RemoteAgent): string {
  if (agent.status !== "ACTIVE") return agent.status;
  return online(agent) ? "ONLINE" : "OFFLINE";
}

function TokenCard({ provision }: { provision: AgentProvision }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-3">
      <p className="text-sm font-medium text-amber-900">
        Agent credential created — copy it now. It is shown only once.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <code className="max-w-full overflow-x-auto rounded bg-white px-2 py-1 text-xs">
          {provision.token}
        </code>
        <button
          className="rounded-md border bg-white px-2 py-1 text-xs"
          onClick={async () => {
            await navigator.clipboard.writeText(provision.token);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="mt-2 text-xs text-amber-800">
        Set it as <code>AIRS_AGENT_TOKEN</code> in{" "}
        <code>/etc/airs-agent/agent.env</code> (systemd) or the container
        environment. Expires {fmtDate(provision.credential.expires_at)}.
      </p>
    </div>
  );
}

export default function Agents() {
  const { data: me } = useMe();
  const canAdmin = roleAtLeast(me?.role, "ADMIN");
  const agents = useAgents();
  const create = useCreateAgent();
  const rotate = useRotateAgentCredential();
  const setStatus = useSetAgentStatus();

  const [displayName, setDisplayName] = useState("");
  const [hostname, setHostname] = useState("");
  const [agentKey, setAgentKey] = useState("");
  const [notes, setNotes] = useState("");
  const [provision, setProvision] = useState<AgentProvision | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const submit = () => {
    setErrorMsg(null);
    if (!displayName.trim() || !hostname.trim()) {
      setErrorMsg("Display name and hostname are required.");
      return;
    }
    create.mutate(
      {
        display_name: displayName.trim(),
        hostname: hostname.trim(),
        agent_key: agentKey.trim() || undefined,
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: (data) => {
          setProvision(data);
          setDisplayName("");
          setHostname("");
          setAgentKey("");
          setNotes("");
        },
        onError: (err) => setErrorMsg(apiErrorMessage(err, "Could not create agent")),
      },
    );
  };

  const decide = (agent: RemoteAgent, action: "disable" | "enable" | "revoke") => {
    if (
      !confirm(
        `${
          action === "revoke"
            ? "Revoke"
            : action === "enable"
              ? "Enable"
              : "Disable"
        } ${agent.display_name}?`,
      )
    ) {
      return;
    }
    setErrorMsg(null);
    setStatus.mutate(
      { agentId: agent.id, action },
      {
        onError: (err) => setErrorMsg(apiErrorMessage(err, "Could not update agent")),
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-2xl font-bold">Remote Agents</h2>
          <p className="mt-1 text-sm text-gray-500">
            Outbound-only Linux agents. Alerts route to an agent by{" "}
            <code>agent_id</code>, hostname, or instance label.
          </p>
        </div>
      </div>

      {errorMsg && <p className="text-sm text-red-600">{errorMsg}</p>}
      {provision && <TokenCard provision={provision} />}

      {canAdmin && (
        <section className="rounded-lg border bg-white p-4">
          <h3 className="text-lg font-semibold">Register agent</h3>
          <p className="mb-3 mt-1 text-sm text-gray-500">
            The agent key is used in alert labels. If omitted, AIRS generates one.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-gray-500">
              Display name
              <input
                className={`${inputCls} mt-1 block w-full`}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="lab-target-1"
              />
            </label>
            <label className="text-xs text-gray-500">
              Hostname / instance
              <input
                className={`${inputCls} mt-1 block w-full`}
                value={hostname}
                onChange={(event) => setHostname(event.target.value)}
                placeholder="lab-target-1"
              />
            </label>
            <label className="text-xs text-gray-500">
              Agent key (optional)
              <input
                className={`${inputCls} mt-1 block w-full`}
                value={agentKey}
                onChange={(event) => setAgentKey(event.target.value)}
                placeholder="lab-target-1"
              />
            </label>
            <label className="text-xs text-gray-500">
              Notes (optional)
              <input
                className={`${inputCls} mt-1 block w-full`}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="disposable lab VM"
              />
            </label>
          </div>
          <button
            disabled={create.isPending}
            onClick={submit}
            className="mt-3 rounded-md bg-gray-900 px-4 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {create.isPending ? "Creating…" : "Create agent"}
          </button>
        </section>
      )}

      <section className="rounded-lg border bg-white p-4">
        <h3 className="mb-3 text-lg font-semibold">Registered agents</h3>
        {agents.isLoading && <p className="text-sm text-gray-500">Loading agents…</p>}
        {agents.error && (
          <p className="text-sm text-red-600">
            {apiErrorMessage(agents.error, "Could not load agents")}
          </p>
        )}
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Agent</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Last seen</th>
                <th className="px-3 py-2">Version</th>
                <th className="px-3 py-2">Capabilities</th>
                {canAdmin && <th className="px-3 py-2">Ops</th>}
              </tr>
            </thead>
            <tbody>
              {(agents.data ?? []).map((agent) => (
                <tr key={agent.id} className="border-t align-top">
                  <td className="px-3 py-2">
                    <div className="font-medium">{agent.display_name}</div>
                    <div className="text-xs text-gray-500">
                      {agent.hostname} · key <code>{agent.agent_key}</code>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${statusClass(agent)}`}
                    >
                      {statusLabel(agent)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-500">
                    {relative(agent.last_seen_at)}
                  </td>
                  <td className="px-3 py-2 text-gray-500">{agent.version}</td>
                  <td className="px-3 py-2 text-xs text-gray-500">
                    {agent.capabilities.length} actions
                  </td>
                  {canAdmin && (
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-2 text-xs">
                        <button
                          disabled={rotate.isPending || agent.status === "REVOKED"}
                          className="text-blue-600 hover:underline disabled:opacity-40"
                          onClick={() => {
                            if (!confirm(`Rotate credential for ${agent.display_name}?`)) {
                              return;
                            }
                            setErrorMsg(null);
                            rotate.mutate(agent.id, {
                              onSuccess: setProvision,
                              onError: (err) =>
                                setErrorMsg(
                                  apiErrorMessage(err, "Could not rotate credential"),
                                ),
                            });
                          }}
                        >
                          Rotate
                        </button>
                        {agent.status === "ACTIVE" && (
                          <button
                            className="text-amber-700 hover:underline"
                            onClick={() => decide(agent, "disable")}
                          >
                            Disable
                          </button>
                        )}
                        {agent.status === "DISABLED" && (
                          <button
                            className="text-green-700 hover:underline"
                            onClick={() => decide(agent, "enable")}
                          >
                            Enable
                          </button>
                        )}
                        {agent.status !== "REVOKED" && (
                          <button
                            className="text-red-600 hover:underline"
                            onClick={() => decide(agent, "revoke")}
                          >
                            Revoke
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
              {(agents.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={canAdmin ? 6 : 5} className="px-3 py-4 text-gray-500">
                    No remote agents registered.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border bg-white p-4 text-sm text-gray-600">
        <h3 className="mb-2 text-lg font-semibold text-gray-900">Agent setup</h3>
        <p>
          Install the agent from <code>remote-agent/</code>, set{" "}
          <code>AIRS_BASE_URL</code> and the token above, then run{" "}
          <code>python -m app.main</code>. Diagnostics work by default; set{" "}
          <code>AIRS_ENABLE_REMEDIATION=true</code> and an explicit{" "}
          <code>AIRS_ALLOWED_SERVICES</code> list only on a disposable lab host.
        </p>
      </section>
    </div>
  );
}
