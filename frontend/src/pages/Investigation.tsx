import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  useInvestigation,
  useStartInvestigation,
  useApproveInvestigation,
} from "../api/investigation";
import { roleAtLeast, useMe } from "../api/auth";
import { apiErrorMessage } from "../api/client";
import { useRemoteJobDecision, useRemoteJobs } from "../api/remote";
import type { RemoteJob } from "../api/remote";

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  in_progress: "bg-blue-100 text-blue-800",
  waiting_for_agent: "bg-indigo-100 text-indigo-800",
  waiting_for_approval: "bg-amber-100 text-amber-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

const JOB_COLOR: Record<string, string> = {
  PENDING_APPROVAL: "bg-amber-100 text-amber-800",
  APPROVED: "bg-blue-100 text-blue-800",
  DISPATCHED: "bg-indigo-100 text-indigo-800",
  ACKNOWLEDGED: "bg-indigo-100 text-indigo-800",
  RUNNING: "bg-indigo-100 text-indigo-800",
  SUCCEEDED: "bg-green-100 text-green-800",
  FAILED: "bg-red-100 text-red-800",
  TIMED_OUT: "bg-orange-100 text-orange-800",
  CANCELLED: "bg-gray-200 text-gray-700",
  EXPIRED: "bg-gray-200 text-gray-700",
  UNKNOWN: "bg-purple-100 text-purple-800",
};

function JobRow({ job }: { job: RemoteJob }) {
  const output =
    job.result?.structured_output ??
    job.result?.stdout_redacted ??
    job.last_error ??
    null;
  return (
    <tr className="border-t align-top">
      <td className="px-3 py-2 text-xs text-gray-500">#{job.id}</td>
      <td className="px-3 py-2">
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            JOB_COLOR[job.status] ?? "bg-gray-100 text-gray-700"
          }`}
        >
          {job.status}
        </span>
      </td>
      <td className="px-3 py-2">
        <div className="font-medium">{job.action_id}</div>
        <div className="text-xs text-gray-500">
          {job.execution_type} · round {job.round_number} · attempt{" "}
          {job.attempt_count}
        </div>
      </td>
      <td className="px-3 py-2 text-xs text-gray-600">
        {job.result?.duration_ms !== null && job.result?.duration_ms !== undefined
          ? `${job.result.duration_ms}ms`
          : "—"}
      </td>
      <td className="max-w-md px-3 py-2">
        {output ? (
          <details>
            <summary className="cursor-pointer text-xs text-blue-600">
              View output
            </summary>
            <pre className="mt-2 max-h-64 overflow-auto rounded bg-gray-50 p-2 text-xs">
              {typeof output === "string"
                ? output
                : JSON.stringify(output, null, 2)}
            </pre>
          </details>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        )}
        {job.result?.error_message && (
          <p className="mt-1 text-xs text-red-600">
            {job.result.error_message}
          </p>
        )}
      </td>
    </tr>
  );
}

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
  const remoteJobs = useRemoteJobs(
    incidentId,
    !Number.isNaN(incidentId) && inv?.mode === "remote",
  );
  const start = useStartInvestigation();
  const approve = useApproveInvestigation();
  const decideRemote = useRemoteJobDecision();
  const [startError, setStartError] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const startInvestigation = () => {
    setStartError(null);
    start.mutate(incidentId, {
      onError: (err) =>
        setStartError(apiErrorMessage(err, "Could not start investigation")),
    });
  };

  const handleApprove = (approved: boolean) => {
    if (!incidentId) return;
    approve.mutate(
      { incidentId, body: { approved, reason } },
      {
        onError: (err) =>
          setStartError(
            apiErrorMessage(
              err,
              `Could not ${approved ? "approve" : "reject"}`,
            ),
          ),
      },
    );
  };

  const pendingRemoteJob = (remoteJobs.data?.items ?? []).find(
    (job) => job.status === "PENDING_APPROVAL",
  );

  const handleRemoteDecision = (approved: boolean) => {
    const jobId = pendingRemoteJob?.id ?? inv?.remote_action?.job_id;
    if (!jobId) return;
    if (!reason.trim()) {
      setStartError("A short approval reason is required.");
      return;
    }
    setStartError(null);
    decideRemote.mutate(
      {
        jobId,
        approved,
        reason: reason.trim(),
        actionHash:
          pendingRemoteJob?.approval?.action_hash ??
          inv?.remote_action_hash ??
          undefined,
      },
      {
        onSuccess: () => setReason(""),
        onError: (err) =>
          setStartError(
            apiErrorMessage(
              err,
              `Could not ${approved ? "approve" : "reject"} remote action`,
            ),
          ),
      },
    );
  };

  if (isLoading) return <p className="text-gray-500">Loading investigation…</p>;

  // No investigation state exists yet — offer to start one
  if (!inv) {
    return (
      <div className="rounded-lg border bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            className="text-sm text-blue-600 hover:underline"
            to="/incidents"
          >
            ← Incidents
          </Link>
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
        <Link
          className="mt-2 inline-block text-blue-600 hover:underline"
          to="/incidents"
        >
          Back to incidents
        </Link>
      </div>
    );
  }

  const isRemote = inv.mode === "remote";
  const isWaiting = inv.workflow_status === "waiting_for_approval";
  const isWaitingForAgent = inv.workflow_status === "waiting_for_agent";
  const isComplete = inv.workflow_status === "completed";
  const isFailed = inv.workflow_status === "failed";
  const jobs = remoteJobs.data?.items ?? [];

  return (
    <div className="space-y-4">
      {startError && <p className="text-sm text-red-600">{startError}</p>}
      {inv.error && <p className="text-sm text-red-600">{inv.error}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link
            className="text-sm text-blue-600 hover:underline"
            to={`/incidents/${incidentId}`}
          >
            ← Incident #{incidentId}
          </Link>
          <h2 className="mt-1 text-2xl font-bold">
            {inv.incident_title || `Investigation #${incidentId}`}
          </h2>
        </div>
        <span className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700">
          {isRemote ? "REMOTE AGENT" : "LOCAL SHADOW MODE"}
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase text-gray-500">
            Status
          </h3>
          <span
            className={`inline-flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium ${
              STATUS_COLOR[inv.workflow_status ?? "pending"]
            }`}
          >
            {inv.workflow_status ?? "—"}
          </span>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase text-gray-500">
            Risk Level
          </h3>
          <span
            className={`rounded-md px-3 py-1 text-xs font-medium ${
              inv.risk_level === "destructive"
                ? "bg-red-100 text-red-800"
                : inv.risk_level === "non_destructive"
                  ? "bg-green-100 text-green-800"
                  : "bg-gray-100 text-gray-700"
            }`}
          >
            {inv.risk_level ?? "—"}
          </span>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase text-gray-500">
            Evidence
          </h3>
          <span
            className={`rounded-md px-3 py-1 text-xs font-medium ${
              inv.evidence_sufficient
                ? "bg-green-100 text-green-800"
                : "bg-amber-100 text-amber-800"
            }`}
          >
            {inv.evidence_sufficient ? "Sufficient" : "Insufficient"}
          </span>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase text-gray-500">
            Round
          </h3>
          <span className="text-sm font-medium">
            {isRemote ? inv.investigation_round : "—"}
          </span>
          {isRemote && (
            <div className="mt-1 text-xs text-gray-500">
              Agent #{inv.target_agent_id}
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold">Remediation Plan</h3>
        <pre className="whitespace-pre-wrap text-sm text-gray-700">
          {inv.remediation_plan || "No plan generated yet."}
        </pre>
        {inv.planner_reasoning && (
          <p className="mt-2 text-xs text-gray-500">{inv.planner_reasoning}</p>
        )}
      </div>

      {isRemote && (
        <div className="rounded-lg border bg-white p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Remote Jobs</h3>
            {isWaitingForAgent && (
              <span className="text-xs text-indigo-700">
                Waiting for the agent to poll and return evidence…
              </span>
            )}
          </div>
          {remoteJobs.isLoading ? (
            <p className="text-sm text-gray-500">Loading jobs…</p>
          ) : remoteJobs.error ? (
            <p className="text-sm text-red-600">
              {apiErrorMessage(remoteJobs.error, "Could not load remote jobs")}
            </p>
          ) : jobs.length === 0 ? (
            <p className="text-sm text-gray-500">
              No remote jobs have been created yet.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-left text-sm">
                <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                  <tr>
                    <th className="px-3 py-2">Job</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Action</th>
                    <th className="px-3 py-2">Duration</th>
                    <th className="px-3 py-2">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <JobRow key={job.id} job={job} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {isWaiting && isRemote && pendingRemoteJob && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-amber-900">
            Remote remediation approval required
          </h3>
          <p className="text-sm text-amber-800">
            AIRS will send this exact action to agent #{pendingRemoteJob.agent_id}{" "}
            only after a responder approves it. The approval is bound to the
            job, target, parameters, risk, expiry, and your user/tenant.
          </p>
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase text-amber-700">Action</dt>
              <dd className="font-mono">{pendingRemoteJob.action_id}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-amber-700">Risk</dt>
              <dd className="font-mono">{pendingRemoteJob.risk_level}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-amber-700">Expires</dt>
              <dd>
                {new Date(
                  pendingRemoteJob.approval?.expires_at ??
                    pendingRemoteJob.expires_at,
                ).toLocaleString()}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs uppercase text-amber-700">Parameters</dt>
              <dd>
                <pre className="overflow-x-auto rounded bg-white/70 p-2 text-xs">
                  {JSON.stringify(pendingRemoteJob.action_parameters, null, 2)}
                </pre>
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs uppercase text-amber-700">
                Approval hash
              </dt>
              <dd className="break-all font-mono text-xs">
                {pendingRemoteJob.approval?.action_hash ??
                  inv.remote_action_hash ??
                  "—"}
              </dd>
            </div>
          </dl>
          {pendingRemoteJob.description && (
            <p className="mt-2 text-sm text-amber-800">
              {pendingRemoteJob.description}
            </p>
          )}
          {canRespond ? (
            <div className="mt-3 space-y-2">
              <input
                className="block w-full rounded-md border px-3 py-2 text-sm"
                placeholder="Approval reason (required)"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
              <div className="flex gap-2">
                <button
                  disabled={decideRemote.isPending}
                  onClick={() => handleRemoteDecision(true)}
                  className="rounded-md bg-green-600 px-4 py-1.5 text-sm text-white disabled:opacity-50"
                >
                  {decideRemote.isPending ? "Submitting…" : "Approve action"}
                </button>
                <button
                  disabled={decideRemote.isPending}
                  onClick={() => handleRemoteDecision(false)}
                  className="rounded-md bg-red-600 px-4 py-1.5 text-sm text-white disabled:opacity-50"
                >
                  {decideRemote.isPending ? "Submitting…" : "Reject action"}
                </button>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-amber-800">
              RESPONDER or ADMIN role required to approve remote remediation.
            </p>
          )}
        </div>
      )}

      {isWaiting && !isRemote && canRespond && (
        <div className="rounded-lg border bg-amber-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-amber-800">
            Pending Approval
          </h3>
          <p className="mb-3 text-sm text-amber-700">
            This investigation requires human approval before remediation
            actions can execute.
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

      {!isWaiting && !isWaitingForAgent && canAdmin && !start.isPending && (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold">Start Investigation</h3>
          <p className="mb-3 text-sm text-gray-600">
            {isRemote
              ? "Ask the remote agent for fresh diagnostic evidence. No destructive action runs without a separate per-job approval."
              : "Run the LangGraph investigation workflow for this incident. Produces a remediation plan and risk assessment (shadow mode — no destructive actions)."}
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

      {inv.evidence.length > 0 && (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold">Evidence Timeline</h3>
          <ol className="space-y-2">
            {inv.evidence.map((item) => (
              <li
                key={`${item.job_id}-${item.action_id}`}
                className="rounded border p-2 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-medium ${
                      JOB_COLOR[item.status] ?? "bg-gray-100 text-gray-700"
                    }`}
                  >
                    {item.status}
                  </span>
                  <span className="font-medium">{item.action_id}</span>
                  <span className="text-xs text-gray-500">
                    {item.execution_type} · job #{item.job_id}
                  </span>
                </div>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-gray-600">
                  {typeof item.output === "string"
                    ? item.output
                    : JSON.stringify(item.output, null, 2)}
                </pre>
              </li>
            ))}
          </ol>
        </div>
      )}

      {inv.steps_completed.length > 0 && (
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

      {isComplete && (
        <div className="rounded-lg border bg-green-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-green-800">
            Completed
          </h3>
          <p className="text-sm text-green-700">
            {isRemote
              ? "The remote investigation finished. Review the job results and verification evidence above."
              : "The investigation workflow has finished. Review the plan and evidence above."}
          </p>
        </div>
      )}

      {isFailed && (
        <div className="rounded-lg border bg-red-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-red-800">Failed</h3>
          <p className="text-sm text-red-700">
            {inv.error ?? "The investigation workflow failed."}
          </p>
        </div>
      )}
    </div>
  );
}
