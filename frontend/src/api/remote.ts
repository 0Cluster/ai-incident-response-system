import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export type RemoteAgentStatus = "PENDING" | "ACTIVE" | "DISABLED" | "REVOKED";
export type RemoteJobStatus =
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "DISPATCHED"
  | "ACKNOWLEDGED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "TIMED_OUT"
  | "CANCELLED"
  | "EXPIRED"
  | "UNKNOWN";
export type RemoteExecutionType = "diagnostic" | "remediation" | "verification";

export interface RemoteAgent {
  id: number;
  tenant_id: number;
  agent_key: string;
  display_name: string;
  hostname: string;
  version: string;
  status: RemoteAgentStatus;
  capabilities: string[];
  last_seen_at: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RemoteAgentCredential {
  id: number;
  agent_id: number;
  name: string;
  expires_at: string | null;
  created_at: string;
}

export interface AgentProvision {
  agent: RemoteAgent;
  token: string;
  credential: RemoteAgentCredential;
}

export interface RemoteJobResult {
  id: number;
  job_id: number;
  tenant_id: number;
  agent_id: number;
  status: RemoteJobStatus;
  exit_code: number | null;
  stdout_redacted: string | null;
  stderr_redacted: string | null;
  structured_output: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface RemoteJob {
  id: number;
  tenant_id: number;
  incident_id: number;
  agent_id: number;
  investigation_run_id: string | null;
  round_number: number;
  action_id: string;
  action_parameters: Record<string, unknown>;
  execution_type: RemoteExecutionType;
  risk_level: string;
  status: RemoteJobStatus;
  attempt_count: number;
  timeout_seconds: number;
  description: string | null;
  expires_at: string;
  lease_expires_at: string | null;
  approved_at: string | null;
  dispatched_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  result: RemoteJobResult | null;
  approval: {
    id: number;
    status: string;
    action_hash: string;
    risk_level: string;
    approved_by: number | null;
    approved_by_email: string | null;
    approved_at: string | null;
    expires_at: string;
    reason: string;
  } | null;
}

export interface RemoteJobList {
  items: RemoteJob[];
  total: number;
  limit: number;
  offset: number;
}

export interface RemoteApprovalResponse {
  job_id: number;
  approved: boolean;
  status: RemoteJobStatus;
  action_hash: string;
  message: string;
}

export function useAgents(enabled = true) {
  return useQuery({
    queryKey: ["remote-agents"],
    queryFn: async () => {
      const { data } = await api.get<RemoteAgent[]>("/agents");
      return data;
    },
    enabled,
    refetchInterval: 15_000,
  });
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      display_name: string;
      hostname: string;
      agent_key?: string;
      notes?: string;
    }) => {
      const { data } = await api.post<AgentProvision>("/agents", body);
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["remote-agents"] }),
  });
}

export function useRotateAgentCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (agentId: number) => {
      const { data } = await api.post<AgentProvision>(
        `/agents/${agentId}/rotate-credential`,
      );
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["remote-agents"] }),
  });
}

export function useSetAgentStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      agentId,
      action,
    }: {
      agentId: number;
      action: "disable" | "enable" | "revoke";
    }) => {
      const { data } = await api.post<RemoteAgent>(`/agents/${agentId}/${action}`);
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["remote-agents"] }),
  });
}

export function useRemoteJobs(
  incidentId: number | null,
  enabled = true,
  status?: RemoteJobStatus,
) {
  return useQuery({
    queryKey: ["remote-jobs", incidentId, status ?? "all"],
    queryFn: async () => {
      const { data } = await api.get<RemoteJobList>("/remote-jobs", {
        params: {
          ...(incidentId !== null ? { incident_id: incidentId } : {}),
          ...(status ? { status } : {}),
          limit: 200,
        },
      });
      return data;
    },
    enabled,
    refetchInterval: (query) => {
      const jobs = query.state.data?.items ?? [];
      return jobs.some((job) =>
        [
          "PENDING_APPROVAL",
          "APPROVED",
          "DISPATCHED",
          "ACKNOWLEDGED",
          "RUNNING",
        ].includes(job.status),
      )
        ? 3000
        : false;
    },
  });
}

export function usePendingRemoteJobs(enabled = true) {
  return useQuery({
    queryKey: ["remote-jobs", "pending-approval"],
    queryFn: async () => {
      const { data } = await api.get<RemoteJobList>("/remote-jobs", {
        params: { status: "PENDING_APPROVAL", limit: 200 },
      });
      return data;
    },
    enabled,
    refetchInterval: 5000,
  });
}

export function useRemoteJobDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      jobId,
      approved,
      reason,
      actionHash,
    }: {
      jobId: number;
      approved: boolean;
      reason: string;
      actionHash?: string;
    }) => {
      const { data } = await api.post<RemoteApprovalResponse>(
        `/remote-jobs/${jobId}/${approved ? "approve" : "reject"}`,
        { approved, reason, action_hash: actionHash },
      );
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["remote-jobs"] });
      qc.invalidateQueries({ queryKey: ["investigation"] });
      qc.invalidateQueries({
        queryKey: ["investigations", "waiting_for_approval"],
      });
      qc.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}
