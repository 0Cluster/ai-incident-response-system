import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useCreateIncident, useDeleteIncident, useIncidents } from "../api/incidents";
import { apiErrorMessage } from "../api/client";
import { roleAtLeast, useMe } from "../api/auth";
import type { Incident } from "../api/types";

const inputCls = "rounded-md border px-2 py-1.5 text-sm";

function severityColor(s: string | null) {
  switch (s) {
    case "CRITICAL": return "bg-red-100 text-red-800";
    case "HIGH": return "bg-orange-100 text-orange-800";
    case "MEDIUM": return "bg-yellow-100 text-yellow-800";
    case "LOW": return "bg-green-100 text-green-800";
    default: return "bg-gray-100 text-gray-700";
  }
}

const PAGE_SIZE = 20;

export default function Incidents() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [severity, setSeverity] = useState("UNKNOWN");
  const [fingerprint, setFingerprint] = useState("");
  const [created, setCreated] = useState<Incident | null>(null);
  const page = Number(params.get("page") || "0");
  const filters = {
    status: params.get("status") || undefined,
    severity: params.get("severity") || undefined,
    source: params.get("source") || undefined,
    q: params.get("q") || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };
  const { data, isLoading, error } = useIncidents(filters);
  const { data: me } = useMe();
  const canRespond = roleAtLeast(me?.role, "RESPONDER");
  const create = useCreateIncident();
  const remove = useDeleteIncident();

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.delete("page");
    setParams(next);
  };

  const clearFilters = () => {
    setQ("");
    setParams(new URLSearchParams());
  };

  const submitCreate = () => {
    setCreated(null);
    create.mutate(
      {
        title,
        message,
        severity,
        fingerprint: fingerprint.trim() || undefined,
      },
      {
        onSuccess: (incident) => {
          setCreated(incident);
          setTitle("");
          setMessage("");
          setSeverity("UNKNOWN");
          setFingerprint("");
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold">Incidents</h2>
        {!canRespond && me && (
          <span className="text-xs text-gray-500">
            Read-only: RESPONDER or ADMIN role required to create, edit, or delete incidents.
          </span>
        )}
      </div>

      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => { e.preventDefault(); set("q", q); }}
      >
        <input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title/message" />
        <select className={inputCls} value={params.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
          <option value="">All statuses</option>
          <option>OPEN</option><option>ACKNOWLEDGED</option><option>RESOLVED</option><option>CLOSED</option>
        </select>
        <select className={inputCls} value={params.get("severity") ?? ""} onChange={(e) => set("severity", e.target.value)}>
          <option value="">All severities</option>
          <option>UNKNOWN</option><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option>
        </select>
        <select className={inputCls} value={params.get("source") ?? ""} onChange={(e) => set("source", e.target.value)}>
          <option value="">All sources</option>
          <option>MANUAL</option><option>CUSTOM</option><option>PROMETHEUS</option><option>GRAFANA</option><option>GITHUB</option>
        </select>
        <button type="submit" className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white">Search</button>
        <button type="button" onClick={clearFilters} className="rounded-md border px-3 py-1.5 text-sm">Clear</button>
      </form>

      {canRespond && (
        <div className="rounded-lg border bg-white p-3">
          <h3 className="mb-2 text-sm font-semibold">Create incident</h3>
          <div className="flex flex-wrap gap-2">
            <input className={`${inputCls} min-w-64`} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (min 3 chars)" />
            <input className={`${inputCls} min-w-64`} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Message" />
            <select className={inputCls} value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option>UNKNOWN</option><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option>
            </select>
            <input className={inputCls} value={fingerprint} onChange={(e) => setFingerprint(e.target.value)} placeholder="Fingerprint (dedup, optional)" />
            <button
              disabled={create.isPending || title.length < 3 || !message}
              onClick={submitCreate}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {create.isPending ? "Creating…" : "Create"}
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            A fingerprint prevents duplicate active incidents from the same source alert.
          </p>
          {create.isError && <p className="mt-2 text-sm text-red-600">{apiErrorMessage(create.error, "Could not create incident")}</p>}
          {created && (
            <p className="mt-2 text-sm text-green-700">
              Created <Link className="underline" to={`/incidents/${created.id}`}>#{created.id} {created.title}</Link>.
            </p>
          )}
        </div>
      )}

      {isLoading && <p className="text-gray-500">Loading…</p>}
      {error && <p className="text-red-600">Failed to load incidents.</p>}
      {!isLoading && (data?.items ?? []).length === 0 && <p className="text-gray-500">No incidents found.{data ? ` (${data.total} total)` : ""}</p>}
      {remove.isError && <p className="text-red-600">{apiErrorMessage(remove.error, "Could not delete incident")}</p>}
      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr><th className="px-3 py-2">ID</th><th className="px-3 py-2">Title</th><th className="px-3 py-2">Source</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">Analysis</th><th className="px-3 py-2">Automation</th><th className="px-3 py-2">Ops</th></tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((i) => (
              <tr key={i.id} className="border-t hover:bg-gray-50">
                <td className="px-3 py-2">{i.id}</td>
                <td className="px-3 py-2"><Link className="text-blue-600 hover:underline" to={`/incidents/${i.id}`}>{i.title}</Link></td>
                <td className="px-3 py-2 text-xs text-gray-500">{i.source}</td>
                <td className="px-3 py-2">{i.status}</td>
                <td className="px-3 py-2"><span className={`rounded px-2 py-0.5 text-xs font-medium ${severityColor(i.severity)}`}>{i.severity}</span></td>
                <td className="px-3 py-2">{i.analysis_status}</td>
                <td className="px-3 py-2">{i.automation_status}</td>
                <td className="px-3 py-2">
                  {canRespond ? (
                    <button
                      className="text-red-600 hover:underline"
                      onClick={() => { if (confirm(`Delete #${i.id}?`)) remove.mutate(i.id); }}
                    >
                      Delete
                    </button>
                  ) : (
                    <span className="text-xs text-gray-400">read-only</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2">
        <button disabled={page === 0} onClick={() => set("page", String(page - 1))} className="rounded-md border px-3 py-1 text-sm disabled:opacity-50">Prev</button>
        <span className="py-1 text-sm text-gray-500">Page {page + 1}{data ? ` of ${Math.max(1, Math.ceil(data.total / PAGE_SIZE))} (${data.total})` : ""}</span>
        <button disabled={!data || (page + 1) * PAGE_SIZE >= data.total} onClick={() => set("page", String(page + 1))} className="rounded-md border px-3 py-1 text-sm disabled:opacity-50">Next</button>
      </div>
    </div>
  );
}
