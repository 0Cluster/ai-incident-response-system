import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export type InvestigationStatus =
  | "pending"
  | "in_progress"
  | "waiting_for_agent"
  | "waiting_for_approval"
  | "completed"
  | "failed";

export interface RemoteAction {
  job_id: number;
  action_id: string;
  parameters: Record<string, unknown>;
  description: string;
  risk_level: string;
}

export interface InvestigationState {
  investigation_id: number;
  incident_id: number;
  tenant_id: number;
  incident_title: string;
  incident_severity: string;
  workflow_status: InvestigationStatus;
  current_step: string;
  evidence_sufficient: boolean;
  risk_level: string;
  requires_approval: boolean;
  approved: boolean | null;
  remediation_plan: string | null;
  executed: boolean;
  verified: boolean;
  service_healthy: boolean;
  error: string | null;
  steps_completed: string[];
  mode: "local" | "remote";
  target_agent_id: number | null;
  investigation_round: number;
  pending_job_ids: number[];
  evidence: Array<{
    job_id: number;
    action_id: string;
    parameters: Record<string, unknown>;
    execution_type: string;
    status: string;
    exit_code: number | null;
    duration_ms: number | null;
    output: unknown;
  }>;
  planner_reasoning: string;
  remote_action: RemoteAction | null;
  remote_action_hash: string | null;
}

export interface InvestigationStartResponse {
  investigation_id: number;
  workflow_status: InvestigationStatus;
  current_step: string;
}

export interface InvestigationApproveRequest {
  approved: boolean;
  reason?: string;
}

export interface InvestigationApproveResponse {
  investigation_id: number;
  approved: boolean;
  workflow_status: InvestigationStatus;
  message: string;
}

export function useInvestigation(incidentId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["investigation", incidentId],
    queryFn: async () => {
      const { data } = await api.get<InvestigationState>(
        `/investigations/${incidentId}`,
      );
      return data;
    },
    enabled: enabled && incidentId !== null,
    refetchInterval: (query) => {
      const state = query.state.data as InvestigationState | undefined;
      // Poll while the workflow is running or waiting for approval
      if (
        state &&
        (state.workflow_status === "in_progress" ||
          state.workflow_status === "waiting_for_agent" ||
          state.workflow_status === "waiting_for_approval")
      ) {
        return 3000; // poll every 3 seconds
      }
      return false;
    },
  });
}

export function usePendingApprovals() {
  return useQuery({
    queryKey: ["investigations", "waiting_for_approval"],
    queryFn: async () => {
      const { data } = await api.get<InvestigationState[]>("/investigations", {
        params: { status: "waiting_for_approval" },
      });
      return data;
    },
    refetchInterval: 5000,
  });
}

export function useStartInvestigation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (incidentId: number) => {
      const { data } = await api.post<InvestigationStartResponse>(
        `/investigations/${incidentId}/start`,
      );
      return data;
    },
    onSuccess: (_data, incidentId) => {
      qc.invalidateQueries({ queryKey: ["investigation", incidentId] });
      qc.invalidateQueries({ queryKey: ["incident", incidentId] });
      qc.invalidateQueries({
        queryKey: ["investigations", "waiting_for_approval"],
      });
    },
  });
}

export function useApproveInvestigation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      incidentId,
      body,
    }: {
      incidentId: number;
      body: InvestigationApproveRequest;
    }) => {
      const { data } = await api.post<InvestigationApproveResponse>(
        `/investigations/${incidentId}/approve`,
        body,
      );
      return data;
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["investigation", vars.incidentId] });
      qc.invalidateQueries({ queryKey: ["incident", vars.incidentId] });
      qc.invalidateQueries({
        queryKey: ["investigations", "waiting_for_approval"],
      });
    },
  });
}
