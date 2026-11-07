import { useState } from "react";
import { Link } from "react-router-dom";
import { useIncidents, useStats } from "../api/incidents";
import { useHealth } from "../api/runbooks";

function Card({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </div>
  );
}

function StatCard({ label, value, href, tone }: { label: string; value: number; href: string; tone: string }) {
  return (
    <Link to={href} className="rounded-lg border bg-white p-4 shadow-sm transition hover:border-gray-300">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-3xl font-bold ${tone}`}>{value}</p>
    </Link>
  );
}

const inputCls = "rounded-md border px-2 py-1.5 text-sm";

export default function Dashboard() {
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [source, setSource] = useState("");
  const [q, setQ] = useState("");
  const [appliedQ, setAppliedQ] = useState<string | undefined>(undefined);
  const filters = {
    status: status || undefined,
    severity: severity || undefined,
    source: source || undefined,
    q: appliedQ,
  };
  const { data, isLoading, error } = useStats(filters);
  const { data: recent } = useIncidents({ limit: 5, offset: 0 });
  const { data: health } = useHealth();

  const clear = () => {
    setStatus("");
    setSeverity("");
    setSource("");
    setQ("");
    setAppliedQ(undefined);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-bold">Dashboard</h2>
        {data && <span className="text-sm text-gray-500">Total: <strong>{data.total}</strong></span>}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Total incidents" value={data?.total ?? 0} href="/incidents" tone="text-gray-900" />
        <StatCard
          label="Open"
          value={data?.by_status.OPEN ?? 0}
          href="/incidents?status=OPEN"
          tone="text-blue-700"
        />
        <StatCard
          label="Critical"
          value={data?.by_severity.CRITICAL ?? 0}
          href="/incidents?severity=CRITICAL"
          tone="text-red-700"
        />
      </div>

      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => { e.preventDefault(); setAppliedQ(q || undefined); }}
      >
        <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option>OPEN</option><option>ACKNOWLEDGED</option><option>RESOLVED</option><option>CLOSED</option>
        </select>
        <select className={inputCls} value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All severities</option>
          <option>UNKNOWN</option><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option>
        </select>
        <select className={inputCls} value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          <option>MANUAL</option><option>CUSTOM</option><option>PROMETHEUS</option><option>GRAFANA</option><option>GITHUB</option>
        </select>
        <input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter text" />
        <button type="submit" className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white">Apply</button>
        <button type="button" onClick={clear} className="rounded-md border px-3 py-1.5 text-sm">Clear</button>
      </form>

      {isLoading && <p className="text-gray-500">Loading stats…</p>}
      {error && <p className="text-red-600">Failed to load stats. Is the API running?</p>}
      {data && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="By status">
            <ul className="space-y-1">
              {Object.entries(data.by_status).map(([k, v]) => (
                <li key={k} className="flex justify-between border-b py-1 text-sm last:border-0">
                  <Link className="text-blue-600 hover:underline" to={`/incidents?status=${k}`}>{k}</Link>
                  <span className="font-medium">{v}</span>
                </li>
              ))}
              {Object.keys(data.by_status).length === 0 && <li className="text-sm text-gray-500">No data.</li>}
            </ul>
          </Card>
          <Card title="By severity">
            <ul className="space-y-1">
              {Object.entries(data.by_severity).map(([k, v]) => (
                <li key={k} className="flex justify-between border-b py-1 text-sm last:border-0">
                  <Link className="text-blue-600 hover:underline" to={`/incidents?severity=${k}`}>{k}</Link>
                  <span className="font-medium">{v}</span>
                </li>
              ))}
              {Object.keys(data.by_severity).length === 0 && <li className="text-sm text-gray-500">No data.</li>}
            </ul>
          </Card>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card
          title="Recent incidents"
          action={<Link className="text-sm text-blue-600 hover:underline" to="/incidents">View all</Link>}
        >
          <ul className="space-y-1 text-sm">
            {(recent?.items ?? []).map((incident) => (
              <li key={incident.id} className="flex items-center justify-between gap-2 border-b py-1 last:border-0">
                <Link className="truncate text-blue-600 hover:underline" to={`/incidents/${incident.id}`}>
                  #{incident.id} {incident.title}
                </Link>
                <span className="shrink-0 text-xs text-gray-500">{incident.severity} · {incident.status}</span>
              </li>
            ))}
            {(recent?.items ?? []).length === 0 && <li className="text-gray-500">No incidents yet.</li>}
          </ul>
        </Card>

        <Card title="System health">
          {!health ? (
            <p className="text-sm text-gray-500">Checking dependencies…</p>
          ) : (
            <div className="space-y-2 text-sm">
              <p className={health.status === "healthy" ? "text-green-700" : "text-red-700"}>
                {health.status === "healthy" ? "All dependencies healthy." : "One or more dependencies degraded."}
              </p>
              <ul className="space-y-1">
                {Object.entries(health.checks ?? {}).map(([name, value]) => (
                  <li key={name} className="flex justify-between border-b py-1 last:border-0">
                    <span className="capitalize text-gray-600">{name}</span>
                    <span className={value === "ok" ? "font-medium text-green-700" : "font-medium text-red-700"}>{value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>

      <div className="flex flex-wrap gap-2">
        <Link className="rounded-md border bg-white px-3 py-1.5 text-sm hover:bg-gray-50" to="/incidents">Create incident</Link>
        <Link className="rounded-md border bg-white px-3 py-1.5 text-sm hover:bg-gray-50" to="/webhooks">Test webhook</Link>
        <Link className="rounded-md border bg-white px-3 py-1.5 text-sm hover:bg-gray-50" to="/runbooks">Manage runbooks</Link>
        <Link className="rounded-md border bg-white px-3 py-1.5 text-sm hover:bg-gray-50" to="/settings">Account & access</Link>
      </div>
    </div>
  );
}
