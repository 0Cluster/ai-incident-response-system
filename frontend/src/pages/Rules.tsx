import { useState } from "react";
import {
  useActions,
  useCreateRule,
  useDeleteRule,
  useRules,
  useUpdateRule,
} from "../api/automation";
import type { AutomationRule } from "../api/types";
import { apiErrorMessage } from "../api/client";
import { roleAtLeast, useMe } from "../api/auth";

const SEVERITIES = ["UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"];
const inputCls = "rounded-md border px-2 py-1.5 text-sm";

function configHint(action: string): string {
  if (action === "webhook") return '{"url": "https://...", "headers": {"X-n8n-Key": "..."}}';
  if (action === "script") return '{"script_path": "/path/to/script.sh"}';
  if (action === "slack") return '{"url": "https://hooks.slack.com/..."}';
  return "{} (log needs no config)";
}

function RuleRow({
  rule,
  actions,
  canEdit,
}: {
  rule: AutomationRule;
  actions: string[];
  canEdit: boolean;
}) {
  const update = useUpdateRule();
  const remove = useDeleteRule();
  const [severity, setSeverity] = useState(rule.severity);
  const [action, setAction] = useState(rule.action_name);
  const [text, setText] = useState(() => JSON.stringify(rule.config ?? {}, null, 2));
  const [order, setOrder] = useState(String(rule.execution_order));
  const [enabled, setEnabled] = useState(rule.enabled);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const actionOptions = Array.from(new Set([...actions, rule.action_name])).filter(Boolean);

  if (!canEdit) {
    return (
      <tr className="border-t align-top">
        <td className="px-3 py-2">{rule.id}</td>
        <td className="px-3 py-2">{rule.severity}</td>
        <td className="px-3 py-2">{rule.action_name}</td>
        <td className="px-3 py-2">{rule.execution_order}</td>
        <td className="px-3 py-2">{String(rule.enabled)}</td>
        <td className="px-3 py-2">
          <pre className="max-w-80 overflow-x-auto text-xs">{JSON.stringify(rule.config ?? {}, null, 2)}</pre>
        </td>
        <td className="px-3 py-2 text-xs text-gray-400">read-only</td>
      </tr>
    );
  }

  const save = () => {
    try {
      const parsed = text.trim() ? JSON.parse(text) : {};
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("config must be a JSON object");
      }
      const n = Number(order);
      if (!Number.isInteger(n) || n < 1) throw new Error("order must be an integer >= 1");
      setError(null);
      setNotice(null);
      update.mutate(
        {
          id: rule.id,
          severity,
          action_name: action,
          enabled,
          execution_order: n,
          config: parsed,
        },
        {
          onSuccess: () => setNotice("Saved"),
          onError: (err) => setError(apiErrorMessage(err, "Could not save rule")),
        },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid input");
    }
  };

  return (
    <tr className="border-t align-top">
      <td className="px-3 py-2">{rule.id}</td>
      <td className="px-3 py-2">
        <select className={inputCls} value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
        </select>
      </td>
      <td className="px-3 py-2">
        <select className={inputCls} value={action} onChange={(e) => setAction(e.target.value)}>
          {actionOptions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </td>
      <td className="px-3 py-2">
        <input
          className={`${inputCls} w-16`}
          value={order}
          onChange={(e) => setOrder(e.target.value)}
          type="number"
          min={1}
        />
      </td>
      <td className="px-3 py-2">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
      </td>
      <td className="px-3 py-2">
        <textarea
          className="w-full min-w-64 rounded-md border px-2 py-1 font-mono text-xs"
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <p className="mt-1 text-xs text-gray-500">Expected: {configHint(action)}</p>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-col items-start gap-2">
          <button
            disabled={update.isPending}
            onClick={save}
            className="rounded-md bg-gray-900 px-2 py-1 text-xs text-white disabled:opacity-50"
          >
            {update.isPending ? "Saving…" : "Save"}
          </button>
          <button
            className="text-xs text-red-600 hover:underline"
            onClick={() => { if (confirm(`Delete rule #${rule.id}?`)) remove.mutate(rule.id); }}
          >
            Delete
          </button>
          {error && <p className="max-w-48 text-xs text-red-600">{error}</p>}
          {notice && <p className="text-xs text-green-700">{notice}</p>}
          {remove.isError && <p className="max-w-48 text-xs text-red-600">{apiErrorMessage(remove.error, "Delete failed")}</p>}
        </div>
      </td>
    </tr>
  );
}

export default function Rules() {
  const { data: rules, isLoading, error } = useRules();
  const { data: actions } = useActions();
  const { data: me } = useMe();
  const canAdmin = roleAtLeast(me?.role, "ADMIN");
  const create = useCreateRule();
  const [severity, setSeverity] = useState("HIGH");
  const [action, setAction] = useState("log");
  const [order, setOrder] = useState("1");
  const [enabled, setEnabled] = useState(true);
  const [url, setUrl] = useState("");
  const [headersText, setHeadersText] = useState("");
  const [scriptPath, setScriptPath] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (isLoading) return <p className="text-gray-500">Loading rules…</p>;

  const actionList = actions ?? ["log", "script", "webhook"];

  const buildConfig = (): Record<string, unknown> => {
    if (action === "webhook" || action === "slack") {
      const cfg: Record<string, unknown> = url.trim() ? { url: url.trim() } : {};
      if (headersText.trim()) {
        try {
          const h = JSON.parse(headersText);
          if (typeof h === "object" && h !== null && !Array.isArray(h)) cfg.headers = h;
        } catch {
          // validated in handleCreate
        }
      }
      return cfg;
    }
    if (action === "script") return scriptPath.trim() ? { script_path: scriptPath.trim() } : {};
    return {};
  };

  const handleCreate = () => {
    if (action === "webhook" && !url.trim()) {
      setCreateError("URL is required for webhook action");
      return;
    }
    if ((action === "webhook" || action === "slack") && headersText.trim()) {
      try {
        const h = JSON.parse(headersText);
        if (typeof h !== "object" || h === null || Array.isArray(h)) throw new Error();
      } catch {
        setCreateError('Headers must be a JSON object, e.g. {"X-n8n-Key": "..."}');
        return;
      }
    }
    if (action === "script" && !scriptPath.trim()) {
      setCreateError("script_path is required for script action");
      return;
    }
    const n = Number(order);
    if (!Number.isInteger(n) || n < 1) {
      setCreateError("order must be an integer >= 1");
      return;
    }
    setCreateError(null);
    setNotice(null);
    create.mutate(
      {
        severity,
        action_name: action,
        enabled,
        execution_order: n,
        config: buildConfig(),
      },
      {
        onSuccess: (rule) => {
          setNotice(`Created rule #${rule.id}`);
          setUrl("");
          setHeadersText("");
          setScriptPath("");
        },
        onError: (err) => setCreateError(apiErrorMessage(err, "Could not create rule")),
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold">Automation rules</h2>
        {!canAdmin && me && (
          <span className="text-xs text-gray-500">Read-only: ADMIN role required to change rules.</span>
        )}
      </div>
      <p className="text-sm text-gray-600">DB-driven: engine matches <code>severity</code> → enabled rules ordered by <code>execution_order</code>.</p>
      {error && <p className="text-sm text-red-600">{apiErrorMessage(error, "Could not load rules")}</p>}
      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr><th className="px-3 py-2">ID</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">Action</th><th className="px-3 py-2">Order</th><th className="px-3 py-2">Enabled</th><th className="px-3 py-2">Config</th><th className="px-3 py-2">Ops</th></tr>
          </thead>
          <tbody>
            {(rules ?? []).map((rule) => (
              <RuleRow
                key={`${rule.id}-${rule.severity}-${rule.action_name}-${rule.execution_order}-${rule.enabled}-${JSON.stringify(rule.config)}`}
                rule={rule}
                actions={actionList}
                canEdit={canAdmin}
              />
            ))}
            {(rules ?? []).length === 0 && (
              <tr><td className="px-3 py-3 text-gray-500" colSpan={7}>No rules yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {canAdmin && (
        <div className="rounded-lg border bg-white p-3">
          <h3 className="mb-2 text-sm font-semibold">Create rule</h3>
          <div className="flex flex-wrap gap-2">
            <select className={inputCls} value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <select className={inputCls} value={action} onChange={(e) => setAction(e.target.value)}>
              {actionList.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <input
              className={`${inputCls} w-24`}
              value={order}
              onChange={(e) => setOrder(e.target.value)}
              type="number"
              min={1}
              placeholder="order"
            />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              Enabled
            </label>
            {(action === "webhook" || action === "slack") && (
              <>
                <input className={`${inputCls} min-w-72`} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://n8n.../webhook/..." />
                <input className={`${inputCls} min-w-72`} value={headersText} onChange={(e) => setHeadersText(e.target.value)} placeholder='{"X-n8n-Key": "..."} (optional)' />
              </>
            )}
            {action === "script" && (
              <input className={`${inputCls} min-w-72`} value={scriptPath} onChange={(e) => setScriptPath(e.target.value)} placeholder="/opt/scripts/remediate.sh" />
            )}
            <button disabled={create.isPending} onClick={handleCreate}
              className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50">
              {create.isPending ? "Creating…" : "Create"}
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-500">Expected config: {configHint(action)}</p>
          {createError && <p className="mt-1 text-xs text-red-600">{createError}</p>}
          {notice && <p className="mt-1 text-xs text-green-700">{notice}</p>}
        </div>
      )}
    </div>
  );
}
