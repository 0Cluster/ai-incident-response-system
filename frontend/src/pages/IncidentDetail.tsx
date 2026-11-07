import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useDeleteIncident,
  useIncident,
  useIncidentRuns,
  useUpdateIncident,
} from "../api/incidents";
import { useAuditLogs } from "../api/audit";
import { apiErrorMessage } from "../api/client";
import { roleAtLeast, useMe } from "../api/auth";
import type { Incident } from "../api/types";

export default function IncidentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const numericId = Number(id);
  const { data: inc, isLoading, error } = useIncident(numericId);
  const active = Boolean(
    inc &&
      (["PENDING", "RUNNING"].includes(inc.analysis_status) ||
        ["PENDING", "RUNNING"].includes(inc.automation_status)),
  );
  const { data: runs, refetch: refetchRuns, isFetching: runsFetching } = useIncidentRuns(numericId, active);
  const update = useUpdateIncident(numericId);
  const remove = useDeleteIncident();
  const { data: me } = useMe();
  const canRespond = roleAtLeast(me?.role, "RESPONDER");
  const { data: allAuditLogs } = useAuditLogs(
    me?.tenant_id ?? null,
    null,
    Boolean(me?.auth_type === "bearer" && me?.user_id !== null),
  );
  const auditLogs =
    allAuditLogs?.items.filter(
      (entry) => entry.resource_id === String(numericId),
    ) ?? [];
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");

  if (isLoading) return <p className="text-gray-500">Loading incident…</p>;
  if (error || !inc) {
    return (
      <div className="rounded-lg border bg-white p-4">
        <p className="text-sm text-red-600">{apiErrorMessage(error, "Incident not found.")}</p>
        <Link className="mt-2 inline-block text-blue-600 hover:underline" to="/incidents">Back to incidents</Link>
      </div>
    );
  }

  const startEdit = () => {
    setTitle(inc.title);
    setMessage(inc.message);
    setEditing(true);
  };

  const save = () => {
    update.mutate({ title, message }, { onSuccess: () => setEditing(false) });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Link className="text-sm text-blue-600 hover:underline" to="/incidents">← Incidents</Link>
          <h2 className="mt-1 text-2xl font-bold">#{inc.id} {inc.title}</h2>
          <p className="text-sm text-gray-600">
            {inc.status} · {inc.severity} · {inc.source} · analysis {inc.analysis_status} · automation {inc.automation_status}
          </p>
          {inc.fingerprint && <p className="text-xs text-gray-500">fingerprint: {inc.fingerprint}</p>}
        </div>
        {canRespond && (
          <div className="flex flex-wrap gap-2">
            <Link
              className="text-sm text-blue-600 hover:underline"
              to={`/incidents/${inc.id}/investigation`}
            >
              Investigation
            </Link>
            {!editing && (
              <button onClick={startEdit} className="rounded-md border px-3 py-1.5 text-sm">Edit title/message</button>
            )}
            <button
              disabled={remove.isPending}
              onClick={() => {
                if (!confirm(`Delete incident #${inc.id}?`)) return;
                remove.mutate(inc.id, { onSuccess: () => navigate("/incidents") });
              }}
              className="rounded-md border px-3 py-1.5 text-sm text-red-600 disabled:opacity-50"
            >
              Delete
            </button>
          </div>
        )}
      </div>

      {!canRespond && me && (
        <p className="text-xs text-gray-500">
          Read-only: RESPONDER or ADMIN role required to edit this incident.
        </p>
      )}
      {update.isError && <p className="text-sm text-red-600">{apiErrorMessage(update.error, "Could not update incident")}</p>}
      {remove.isError && <p className="text-sm text-red-600">{apiErrorMessage(remove.error, "Could not delete incident")}</p>}

      {!editing ? (
        <div className="rounded-lg border bg-white p-4 text-sm whitespace-pre-wrap">{inc.message}</div>
      ) : (
        <div className="space-y-2 rounded-lg border bg-white p-4">
          <input className="w-full rounded-md border px-2 py-1.5 text-sm" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea className="w-full rounded-md border px-2 py-1.5 text-sm" rows={6} value={message} onChange={(e) => setMessage(e.target.value)} />
          <div className="flex gap-2">
            <button
              disabled={update.isPending || title.length < 3 || !message}
              onClick={save}
              className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {update.isPending ? "Saving…" : "Save"}
            </button>
            <button onClick={() => setEditing(false)} className="rounded-md border px-3 py-1.5 text-sm">Cancel</button>
          </div>
        </div>
      )}

      {canRespond && (
        <div className="flex flex-wrap gap-3 rounded-lg border bg-white p-3 text-sm">
          <label className="flex items-center gap-2">
            Status
            <select
              className="rounded-md border px-2 py-1.5 text-sm"
              value={inc.status}
              disabled={update.isPending}
              onChange={(e) => update.mutate({ status: e.target.value as Incident["status"] })}
            >
              <option>OPEN</option><option>ACKNOWLEDGED</option><option>RESOLVED</option><option>CLOSED</option>
            </select>
          </label>
          <label className="flex items-center gap-2">
            Severity
            <select
              className="rounded-md border px-2 py-1.5 text-sm"
              value={inc.severity ?? "UNKNOWN"}
              disabled={update.isPending}
              onChange={(e) => update.mutate({ severity: e.target.value as Incident["severity"] })}
            >
              <option>UNKNOWN</option><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option>
            </select>
          </label>
        </div>
      )}

      {inc.ai_summary && (
        <div className="rounded-lg border bg-white p-4"><h3 className="mb-1 font-semibold">AI summary</h3><p className="text-sm whitespace-pre-wrap">{inc.ai_summary}</p></div>
      )}
      {inc.recommendation && (
        <div className="rounded-lg border bg-white p-4"><h3 className="mb-1 font-semibold">Recommendation</h3><p className="text-sm whitespace-pre-wrap">{inc.recommendation}</p></div>
      )}
      {inc.rag_sources && inc.rag_sources.length > 0 && (
        <p className="text-xs text-gray-500">Sources: {inc.rag_sources.join(", ")}</p>
      )}

      <div className="rounded-lg border bg-white p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="font-semibold">Automation runs</h3>
          <button
            onClick={() => refetchRuns()}
            disabled={runsFetching}
            className="rounded-md border px-2 py-1 text-xs disabled:opacity-50"
          >
            {runsFetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <ul className="space-y-1 text-sm">
          {(runs ?? []).map((r) => (
            <li key={r.id} className="border-b py-1 last:border-0">
              <span className="font-medium">{r.action_name}</span> — {r.status} — {r.message}
              <span className="text-gray-500"> ({new Date(r.executed_at).toLocaleString()})</span>
            </li>
          ))}
          {(runs ?? []).length === 0 && <li className="text-gray-500">No runs yet.</li>}
        </ul>
      </div>

      {auditLogs.length > 0 && (
        <div className="rounded-lg border bg-white p-4 mt-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="font-semibold">Audit History</h3>
            <span className="text-xs text-gray-500">{auditLogs.length} event(s)</span>
          </div>
          <div className="space-y-2 text-sm">
            {auditLogs
              .slice()
              .reverse()
              .map((entry) => (
                <div key={entry.id} className="flex gap-3 border-b py-2 last:border-0">
                  <span className="w-20 text-xs text-gray-500">
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                  <span className="w-32 text-xs font-mono text-gray-600 truncate">
                    {entry.action}
                  </span>
                  <span className="text-xs text-gray-600">
                    {entry.actor_email ?? "system"}
                    {entry.actor_is_superadmin && " (superadmin)"}
                  </span>
                  {entry.details && (
                    <span className="ml-2 text-xs text-gray-400 truncate max-w-xs">
                      {JSON.stringify(entry.details)}
                    </span>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
