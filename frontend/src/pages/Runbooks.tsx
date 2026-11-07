import { useState } from "react";
import {
  useDeleteRunbook,
  useReindex,
  useRunbook,
  useRunbooks,
  useSaveRunbook,
} from "../api/runbooks";
import { apiErrorMessage } from "../api/client";
import { roleAtLeast, useMe } from "../api/auth";

const inputCls = "rounded-md border px-2 py-1.5 text-sm";
const NEW_RUNBOOK = "# Title\n\n## Symptoms\n\n-\n\n## Recommended Actions\n\n- \n";

function RunbookEditor({
  initialName,
  initialContent,
  initialChunks,
  isNew,
  canAdmin,
  onSaved,
  onDeleted,
}: {
  initialName: string;
  initialContent: string;
  initialChunks: number;
  isNew: boolean;
  canAdmin: boolean;
  onSaved: (name: string) => void;
  onDeleted: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [content, setContent] = useState(initialContent);
  const [error, setError] = useState<string | null>(null);
  const save = useSaveRunbook();
  const remove = useDeleteRunbook();

  const handleSave = () => {
    const clean = name.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9_-]{1,60}$/.test(clean)) {
      setError("name must match [a-z0-9_-]{2,60}, e.g. 'kafka'");
      return;
    }
    if (!content.trim()) {
      setError("content must be non-empty markdown");
      return;
    }
    setError(null);
    save.mutate(
      { name: clean, content },
      {
        onSuccess: () => onSaved(clean),
        onError: (err) => setError(apiErrorMessage(err, "Save failed")),
      },
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          className={inputCls}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="name, e.g. kafka"
          disabled={!isNew || !canAdmin}
        />
        {!isNew && initialChunks > 0 && (
          <span className="text-xs text-gray-500">{initialChunks} indexed chunks</span>
        )}
      </div>
      {canAdmin ? (
        <textarea
          className="h-96 w-full rounded-md border px-2 py-1 font-mono text-xs"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      ) : (
        <pre className="h-96 w-full overflow-auto rounded-md border bg-gray-50 p-2 font-mono text-xs whitespace-pre-wrap">
          {content}
        </pre>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {canAdmin && (
          <button
            disabled={save.isPending}
            onClick={handleSave}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        )}
        {canAdmin && !isNew && (
          <button
            onClick={() => {
              if (!confirm(`Delete ${name}? Reindex after to drop its vectors.`)) return;
              setError(null);
              remove.mutate(name, {
                onSuccess: onDeleted,
                onError: (err) => setError(apiErrorMessage(err, "Delete failed")),
              });
            }}
            className="rounded-md border px-3 py-1.5 text-sm text-red-600"
          >
            Delete
          </button>
        )}
        {!canAdmin && (
          <span className="text-xs text-gray-500">Read-only: ADMIN role required to edit runbooks.</span>
        )}
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {!isNew && <p className="text-xs text-gray-500">Tip: press Reindex after save/delete to update retrieval.</p>}
    </div>
  );
}

export default function Runbooks() {
  const { data, isLoading, error } = useRunbooks();
  const { data: me } = useMe();
  const canAdmin = roleAtLeast(me?.role, "ADMIN");
  const [selected, setSelected] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const detail = useRunbook(!isNew ? selected : null);
  const reindex = useReindex();

  const startNew = () => {
    setIsNew(true);
    setSelected(null);
  };

  const open = (name: string) => {
    setIsNew(false);
    setSelected(name);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-bold">Runbooks</h2>
        <span className="text-sm text-gray-500">backend: {data?.backend ?? "?"}</span>
        {canAdmin && (
          <button
            disabled={reindex.isPending}
            onClick={() => reindex.mutate()}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {reindex.isPending ? "Indexing…" : "Reindex"}
          </button>
        )}
        {reindex.data && <span className="text-xs text-green-700">indexed ({reindex.data.backend})</span>}
        {reindex.isError && <span className="text-xs text-red-600">{apiErrorMessage(reindex.error, "Reindex failed")}</span>}
      </div>
      {error && <p className="text-sm text-red-600">{apiErrorMessage(error, "Could not load runbooks")}</p>}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border bg-white p-3">
          <div className="mb-2 flex justify-between">
            <h3 className="text-sm font-semibold">Knowledge base</h3>
            {canAdmin && <button onClick={startNew} className="text-sm text-blue-600 hover:underline">+ New</button>}
          </div>
          {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
          <ul className="space-y-1 text-sm">
            {(data?.items ?? []).map((r) => (
              <li key={r.name}>
                <button
                  onClick={() => open(r.name)}
                  className={`hover:underline ${selected === r.name && !isNew ? "font-bold" : "text-blue-600"}`}
                >
                  {r.name}
                </button>
                <span className="text-xs text-gray-500"> ({r.chunks} chunks, {r.chars} chars)</span>
              </li>
            ))}
            {(data?.items ?? []).length === 0 && !isLoading && <li className="text-gray-500">No runbooks yet.</li>}
          </ul>
        </div>

        <div className="rounded-lg border bg-white p-3 md:col-span-2">
          {!selected && !isNew && <p className="text-sm text-gray-500">Select a runbook or create one.</p>}
          {isNew && (
            <RunbookEditor
              key="new"
              initialName=""
              initialContent={NEW_RUNBOOK}
              initialChunks={0}
              isNew
              canAdmin={canAdmin}
              onSaved={(name) => { setIsNew(false); setSelected(name); }}
              onDeleted={() => { setSelected(null); setIsNew(false); }}
            />
          )}
          {selected && !isNew && detail.isLoading && <p className="text-sm text-gray-500">Loading…</p>}
          {selected && !isNew && detail.data && (
            <RunbookEditor
              key={`${detail.data.name}-${detail.dataUpdatedAt}`}
              initialName={detail.data.name}
              initialContent={detail.data.content}
              initialChunks={detail.data.chunks}
              isNew={false}
              canAdmin={canAdmin}
              onSaved={(name) => setSelected(name)}
              onDeleted={() => setSelected(null)}
            />
          )}
          {selected && !isNew && detail.isError && (
            <p className="text-sm text-red-600">{apiErrorMessage(detail.error, "Could not load runbook")}</p>
          )}
        </div>
      </div>
    </div>
  );
}
