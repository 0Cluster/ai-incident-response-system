import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface AuditLogEntry {
  id: number;
  actor_user_id: number | null;
  actor_email: string | null;
  actor_is_superadmin: boolean;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  tenant_id: number | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogList {
  items: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditLogCreate {
  action: string;
  resource_type?: string;
  resource_id?: string;
  details?: Record<string, unknown>;
}

export function useAuditLogs(
  tenantId: number | null,
  action: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["audit-logs", tenantId, action],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (tenantId !== null) params.tenant_id = String(tenantId);
      if (action !== null) params.action = action;
      const { data } = await api.get<AuditLogList>("/audit-log/", { params });
      return data;
    },
    enabled,
  });
}

export function useCreateAuditLog() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: AuditLogCreate) => {
      const { data } = await api.post<AuditLogEntry>("/audit-log/", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audit-logs"] });
    },
  });
}
