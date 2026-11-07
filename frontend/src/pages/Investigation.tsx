import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  useInvestigation,
  useStartInvestigation,
  useApproveInvestigation,
} from "../api/investigation";
import { roleAtLeast, useMe } from "../api/auth";
import { apiErrorMessage } from "../api/client";

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  in_progress: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  waiting_for_approval: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
};

export default function Investigation() {
  const { id } = useParams();
  const incidentId = id ? Number(id) : NaN;
  const { data: me } = useMe();
  const canRespond = roleAtLeast(me?.role, "RESPONDER");
  const canAdmin = roleAtLeast(me?.role, "ADMIN");

  const { data: inv, isLoading } = useInvestigation(
    incidentId,
    !Number.isNaN(incidentId),
  );
  const start = useStartInvestigation();
  const approve = useApproveInvestigation();
  const [startError, setStartError] = useState<string | null>(null);

  const startInvestigation = () => {
    setStartError(null);
    start.mutate(incidentId, {
      onError: (err) => setStartError(apiErrorMessage(err, "Could not start investigation")),
    });
  };

  const handleApprove = (approved: boolean) => {
    if (!incidentId) return;
    approve.mutate(
      { incidentId, body: { approved, reason: "" } },
      {
        onError: (err) =>
          setStartError(apiErrorMessage(err, `Could not ${approved ? "approve" : "reject"}`)),
      },
    );
  };

  if (isLoading) return <p className="text-gray-500">Loading investigation…</p>;

  // No investigation state exists yet — offer to start one
  if (!inv) {
    return (
      <div className="rounded-lg border bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link className="text-sm text-blue-600 hover:underline" to="/incidents">← Incidents</Link>
          <h2 className="text-2xl font-bold">Investigation #{incidentId}</h2>
        </div>
        <p className="mt-4 text-sm text-gray-600">
          No investigation has been started for this incident yet.
        </p>
        {startError && <p className="text-sm text-red-600">{startError}</p>}
        <button
          disabled={start.isPending}
          onClick={startInvestigation}
          className="mt-4 rounded-md bg-gray-900 px-4 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {start.isPending ? "Starting…" : "Start Investigation"}
        </button>
        <Link className="mt-2 inline-block text-blue-600 hover:underline" to="/incidents">
          Back to incidents
        </Link>
      </div>
    );
  }

  const isWaiting = inv.workflow_status === "waiting_for_approval";
  const isComplete = inv.workflow_status === "completed";
  const isFailed = inv.workflow_status === "failed";

  return (
    <div className="space-y-4">
      {startError && <p className="text-sm text-red-600">{startError}</p>}
      {inv.error && <p className="text-sm text-red-600">{inv.error}</p>}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-gray-500 uppercase">Status</h3>
          <span className={`inline-flex items-center gap-1 px-3 py-1 rounded-md text-xs font-medium ${STATUS_COLOR[inv.workflow_status ?? "pending"]}`}>
            {inv.workflow_status ?? "—"}
          </span>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-gray-500 uppercase">Risk Level</h3>
          <span className={`px-3 py-1 rounded-md text-xs font-medium ${inv.risk_level === "destructive" ? "bg-red-100 text-red-800" : inv.risk_level === "non_destructive" ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-700"}`}>
            {inv.risk_level ?? "—"}
          </span>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-gray-500 uppercase">Evidence</h3>
          <span className={`px-3 py-1 rounded-md text-xs font-medium ${inv.evidence_sufficient ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"}`}>
            {inv.evidence_sufficient ? "Sufficient" : "Insufficient"}
          </span>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold">Remediation Plan</h3>
        <pre className="whitespace-pre-wrap text-sm text-gray-700">{inv.remediation_plan ?? "No plan generated yet."}</pre>
      </div>

      {inv.steps_completed && inv.steps_completed.length > 0 && (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold">Steps Completed</h3>
          <ul className="space-y-1 text-sm">
            {inv.steps_completed.map((step) => (
              <li key={step} className="flex items-center gap-1">
                <span className="text-green-600">✓</span>
                <span className="text-gray-600">{step}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isWaiting && canRespond && (
        <div className="rounded-lg border bg-amber-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-amber-800">Pending Approval</h3>
          <p className="mb-3 text-sm text-amber-700">
            This investigation requires human approval before remediation actions can execute.
          </p>
          <div className="flex gap-2">
            <button
              disabled={approve.isPending}
              onClick={() => handleApprove(true)}
              className="rounded-md bg-green-600 px-4 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {approve.isPending ? "Approving…" : "Approve"}
            </button>
            <button
              disabled={approve.isPending}
              onClick={() => handleApprove(false)}
              className="rounded-md bg-red-600 px-4 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {approve.isPending ? "Rejecting…" : "Reject"}
            </button>
          </div>
        </div>
      )}

      {!isWaiting && canAdmin && !start.isPending && (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold">Start Investigation</h3>
          <p className="mb-3 text-sm text-gray-600">
            Run the LangGraph investigation workflow for this incident. Produces a
            remediation plan and risk assessment (shadow mode — no destructive actions).
          </p>
          <button
            disabled={start.isPending || inv.workflow_status === "in_progress"}
            onClick={startInvestigation}
            className="rounded-md bg-gray-900 px-4 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {start.isPending ? "Starting…" : "Start Investigation"}
          </button>
        </div>
      )}

      {isComplete && (
        <div className="rounded-lg border bg-green-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-green-800">Completed</h3>
          <p className="text-sm text-green-700">
            The investigation workflow has finished. Review the plan and evidence above.
          </p>
        </div>
      )}

      {isFailed && (
        <div className="rounded-lg border bg-red-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-red-800">Failed</h3>
          <p className="text-sm text-red-700">{inv.error ?? "The investigation workflow failed."}</p>
        </div>
      )}
    </div>
  );
}
