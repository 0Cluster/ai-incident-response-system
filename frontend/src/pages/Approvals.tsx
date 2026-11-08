import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  useApproveInvestigation,
  usePendingApprovals,
  useStartInvestigation,
} from "../api/investigation";
import { useIncidents } from "../api/incidents";
import { roleAtLeast, useMe } from "../api/auth";
import { apiErrorMessage } from "../api/client";
import { usePendingRemoteJobs, useRemoteJobDecision } from "../api/remote";

export default function Approvals() {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const canRespond = roleAtLeast(me?.role, "RESPONDER");

  const {
    data: approvals,
    isLoading: approvalsLoading,
    error: approvalsError,
  } = usePendingApprovals();
  const {
    data: incidents,
    isLoading: incidentsLoading,
    error: incidentsError,
  } = useIncidents({ limit: 100, offset: 0 });
  const remoteJobs = usePendingRemoteJobs();
  const start = useStartInvestigation();
  const approve = useApproveInvestigation();
  const decideRemote = useRemoteJobDecision();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [starting, setStarting] = useState<Set<number>>(new Set());

  if (approvalsLoading || incidentsLoading) {
    return <p className="text-gray-500">Loading…</p>;
  }

  const loadError = approvalsError || incidentsError || remoteJobs.error;
  if (loadError) {
    return (
      <div className="rounded-lg border bg-white p-4">
        <p className="text-sm text-red-600">
          {apiErrorMessage(loadError, "Could not load approvals.")}
        </p>
      </div>
    );
  }

  const handleStart = async (incidentId: number) => {
    setErrorMsg(null);
    setStarting((prev) => new Set([...prev, incidentId]));
    try {
      await start.mutateAsync(incidentId);
      navigate(`/incidents/${incidentId}/investigation`);
    } catch (err: unknown) {
      setErrorMsg(apiErrorMessage(err, "Could not start investigation"));
    } finally {
      setStarting((prev) => {
        const next = new Set(prev);
        next.delete(incidentId);
        return next;
      });
    }
  };

  const handleApprove = (incidentId: number, approved: boolean) => {
    setErrorMsg(null);
    approve.mutate(
      { incidentId, body: { approved, reason: "" } },
      {
        onError: (err) =>
          setErrorMsg(
            apiErrorMessage(err, `Could not ${approved ? "approve" : "reject"}`),
          ),
      },
    );
  };

  const handleRemoteDecision = (
    jobId: number,
    actionHash: string | undefined,
    approved: boolean,
  ) => {
    const reason = window.prompt(
      `${approved ? "Approve" : "Reject"} remote action #${jobId}. Enter a reason:`,
    );
    if (reason === null) return;
    if (!reason.trim()) {
      setErrorMsg("A short approval reason is required.");
      return;
    }
    setErrorMsg(null);
    decideRemote.mutate(
      { jobId, approved, reason: reason.trim(), actionHash },
      {
        onError: (err) =>
          setErrorMsg(
            apiErrorMessage(err, `Could not ${approved ? "approve" : "reject"}`),
          ),
      },
    );
  };

  const pending = approvals ?? [];
  const pendingRemote = remoteJobs.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold">Approvals</h2>
        <Link className="text-sm text-blue-600 hover:underline" to="/incidents">
          Back to incidents
        </Link>
      </div>

      {errorMsg && <p className="text-sm text-red-600">{errorMsg}</p>}

      {!canRespond && me && (
        <p className="text-sm text-gray-500">
          Read-only: RESPONDER or ADMIN role required to approve remediations.
        </p>
      )}

      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold">
          Pending Remote Actions
        </h3>
        {pendingRemote.length === 0 ? (
          <p className="text-sm text-gray-500">
            No remote jobs are awaiting approval.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">Job</th>
                  <th className="px-3 py-2">Incident</th>
                  <th className="px-3 py-2">Agent</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Risk</th>
                  <th className="px-3 py-2">Approval hash</th>
                  <th className="px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingRemote.map((job) => (
                  <tr key={job.id} className="border-t align-top">
                    <td className="px-3 py-2">#{job.id}</td>
                    <td className="px-3 py-2">
                      <Link
                        className="text-blue-600 hover:underline"
                        to={`/incidents/${job.incident_id}/investigation`}
                      >
                        Incident #{job.incident_id}
                      </Link>
                    </td>
                    <td className="px-3 py-2">#{job.agent_id}</td>
                    <td className="px-3 py-2">
                      <div className="font-mono text-xs">{job.action_id}</div>
                      <pre className="mt-1 max-w-xs overflow-x-auto text-xs text-gray-500">
                        {JSON.stringify(job.action_parameters)}
                      </pre>
                    </td>
                    <td className="px-3 py-2">{job.risk_level}</td>
                    <td className="px-3 py-2">
                      <code className="break-all text-xs">
                        {job.approval?.action_hash
                          ? `${job.approval.action_hash.slice(0, 12)}…`
                          : "—"}
                      </code>
                    </td>
                    <td className="px-3 py-2">
                      {canRespond ? (
                        <div className="flex gap-1">
                          <button
                            disabled={decideRemote.isPending}
                            onClick={() =>
                              handleRemoteDecision(
                                job.id,
                                job.approval?.action_hash,
                                true,
                              )
                            }
                            className="rounded-md bg-green-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                          >
                            Approve
                          </button>
                          <button
                            disabled={decideRemote.isPending}
                            onClick={() =>
                              handleRemoteDecision(
                                job.id,
                                job.approval?.action_hash,
                                false,
                              )
                            }
                            className="rounded-md bg-red-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                          >
                            Reject
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-400">read-only</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold">Pending Approvals</h3>
        {pending.length === 0 ? (
          <p className="text-sm text-gray-500">No investigations awaiting approval.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">Title</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Risk</th>
                <th className="px-3 py-2">Step</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((investigation) => (
                <tr key={investigation.incident_id} className="border-t">
                  <td className="px-3 py-2">{investigation.incident_id}</td>
                  <td className="px-3 py-2">
                    <Link
                      className="text-blue-600 hover:underline"
                      to={`/incidents/${investigation.incident_id}/investigation`}
                    >
                      {investigation.incident_title ||
                        `Incident #${investigation.incident_id}`}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${investigation.incident_severity === "CRITICAL" ? "bg-red-100 text-red-800" : investigation.incident_severity === "HIGH" ? "bg-orange-100 text-orange-800" : "bg-gray-100 text-gray-700"}`}>
                      {investigation.incident_severity || "UNKNOWN"}
                    </span>
                  </td>
                  <td className="px-3 py-2">{investigation.risk_level}</td>
                  <td className="px-3 py-2">{investigation.current_step}</td>
                  <td className="px-3 py-2">
                    {investigation.mode === "remote" ? (
                      <Link
                        className="text-xs text-blue-600 hover:underline"
                        to={`/incidents/${investigation.incident_id}/investigation`}
                      >
                        Review remote action
                      </Link>
                    ) : canRespond ? (
                      <div className="flex gap-1">
                        <button
                          disabled={approve.isPending}
                          onClick={() =>
                            handleApprove(investigation.incident_id, true)
                          }
                          className="rounded-md bg-green-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          disabled={approve.isPending}
                          onClick={() =>
                            handleApprove(investigation.incident_id, false)
                          }
                          className="rounded-md bg-red-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-gray-400">read-only</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold">Start Investigation</h3>
        <p className="mb-3 text-sm text-gray-600">
          Select an incident to start an investigation. Local incidents use the
          LangGraph workflow; incidents with a target agent use durable remote
          jobs. Neither executes destructive actions without approval.
        </p>
        <div className="flex flex-wrap gap-2">
          {(incidents?.items ?? []).map((incident) => (
            <button
              key={incident.id}
              disabled={starting.has(incident.id)}
              onClick={() => handleStart(incident.id)}
              className="rounded-md border bg-white px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {starting.has(incident.id) ? "Starting…" : (
                <>
                  #{incident.id} {incident.title}
                </>
              )}
            </button>
          ))}
          {(incidents?.items ?? []).length === 0 && (
            <span className="text-sm text-gray-500">No incidents available.</span>
          )}
        </div>
      </div>
    </div>
  );
}
