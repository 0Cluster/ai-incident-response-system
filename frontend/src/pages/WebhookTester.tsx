import { useState } from "react";
import { Link } from "react-router-dom";
import { api, apiErrorMessage } from "../api/client";
import type { Incident } from "../api/types";
import { roleAtLeast, useMe } from "../api/auth";

type Provider = "custom" | "grafana";

export default function WebhookTester() {
  const { data: me } = useMe();
  const canRespond = roleAtLeast(me?.role, "RESPONDER");
  const [provider, setProvider] = useState<Provider>("custom");
  const [title, setTitle] = useState("High CPU test");
  const [message, setMessage] = useState("CPU 95% for 5m on test-host");
  const [severity, setSeverity] = useState("HIGH");
  const [instance, setInstance] = useState("test-host");
  const [fingerprint, setFingerprint] = useState("test-fp-1");
  const [result, setResult] = useState<string>("");
  const [created, setCreated] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const send = async () => {
    if (!canRespond) {
      setError("RESPONDER or ADMIN role is required to send test webhooks.");
      return;
    }
    if (title.length < 3 || !message) {
      setError("Title needs at least 3 characters and a message is required.");
      return;
    }
    setSending(true);
    setResult("");
    setCreated([]);
    setError(null);
    try {
      let payload: unknown;
      if (provider === "custom") {
        payload = {
          title,
          message,
          severity,
          fingerprint: fingerprint.trim() || undefined,
        };
      } else {
        payload = {
          receiver: "tester",
          status: "firing",
          alerts: [
            {
              status: "firing",
              fingerprint: fingerprint.trim() || "test-fp-1",
              labels: {
                alertname: title,
                severity: severity.toLowerCase(),
                instance: instance.trim() || "test-host",
              },
              annotations: { summary: message },
            },
          ],
        };
      }
      // Server-side proxy: no webhook secret in the browser bundle.
      const { data } = await api.post<Incident[]>("/webhooks/test", { provider, payload });
      setCreated(data);
      setResult(JSON.stringify(data, null, 2));
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Could not send webhook"));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold">Webhook tester</h2>
        {!canRespond && me && (
          <span className="text-xs text-gray-500">
            Read-only: RESPONDER or ADMIN role required to send test webhooks.
          </span>
        )}
      </div>
      <p className="text-sm text-gray-600">
        Uses the server-side <code>/webhooks/test</code> proxy, so the browser never
        needs the real webhook secret. The real ingest endpoints still require
        <code> X-Webhook-Secret</code>.
      </p>

      <div className="grid gap-3 rounded-lg border bg-white p-4 md:grid-cols-2">
        <label className="block text-sm font-medium">
          Provider
          <select
            className="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
            value={provider}
            onChange={(e) => setProvider(e.target.value as Provider)}
            disabled={!canRespond}
          >
            <option value="custom">custom</option>
            <option value="grafana">grafana</option>
          </select>
        </label>
        <label className="block text-sm font-medium">
          Severity
          <select
            className="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            disabled={!canRespond}
          >
            <option>UNKNOWN</option><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option>
          </select>
        </label>
        <label className="block text-sm font-medium md:col-span-2">
          Title / alertname
          <input
            className="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="High CPU test"
            disabled={!canRespond}
          />
        </label>
        <label className="block text-sm font-medium md:col-span-2">
          Message / summary
          <textarea
            className="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
            rows={3}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="CPU 95% for 5m on test-host"
            disabled={!canRespond}
          />
        </label>
        <label className="block text-sm font-medium">
          Fingerprint (dedup key)
          <input
            className="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
            value={fingerprint}
            onChange={(e) => setFingerprint(e.target.value)}
            placeholder="test-fp-1"
            disabled={!canRespond}
          />
        </label>
        <label className="block text-sm font-medium">
          Instance (Grafana only)
          <input
            className="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
            value={instance}
            onChange={(e) => setInstance(e.target.value)}
            placeholder="test-host"
            disabled={!canRespond}
          />
        </label>
        <div className="md:col-span-2">
          <button
            disabled={sending || !canRespond || title.length < 3 || !message}
            onClick={send}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {sending ? "Sending…" : `Send ${provider} webhook`}
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {created.length > 0 && (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 font-semibold">Created incidents</h3>
          <ul className="space-y-1 text-sm">
            {created.map((incident) => (
              <li key={incident.id}>
                <Link className="text-blue-600 hover:underline" to={`/incidents/${incident.id}`}>
                  #{incident.id} {incident.title}
                </Link>
                <span className="ml-2 text-gray-500">{incident.severity} · {incident.analysis_status}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {result && <pre className="overflow-x-auto rounded-lg border bg-white p-3 text-xs">{result}</pre>}
    </div>
  );
}
