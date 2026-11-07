import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { Incident, StatsSummary, AutomationRun } from "./types";

export interface IncidentFilters {
  status?: string;
  severity?: string;
  source?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface PaginatedIncidents {
  items: Incident[];
  total: number;
  limit: number;
  offset: number;
}

export function useIncidents(filters: IncidentFilters) {
  return useQuery({
    queryKey: ["incidents", filters],
    queryFn: async () => {
      const { data } = await api.get<PaginatedIncidents | Incident[]>("/incidents/", {
        params: filters,
      });
      // Backward compat: older API returns bare list
      const page: PaginatedIncidents = Array.isArray(data)
        ? { items: data, total: data.length, limit: filters.limit ?? 50, offset: filters.offset ?? 0 }
        : data;
      return page;
    },
    // Poll while analysis or automation is still in flight
    refetchInterval: (query) => {
      const page = query.state.data as PaginatedIncidents | undefined;
      if (page?.items.some((i) =>
        ["PENDING", "RUNNING"].includes(i.analysis_status) ||
        ["PENDING", "RUNNING"].includes(i.automation_status)
      )) {
        return 5000;
      }
      return false;
    },
  });
}

export function useIncident(id: number) {
  return useQuery({
    queryKey: ["incident", id],
    queryFn: async () => {
      const { data } = await api.get<Incident>(`/incidents/${id}`);
      return data;
    },
    refetchInterval: (query) => {
      const inc = query.state.data as Incident | undefined;
      if (inc && (
        ["PENDING", "RUNNING"].includes(inc.analysis_status) ||
        ["PENDING", "RUNNING"].includes(inc.automation_status)
      )) {
        return 3000;
      }
      return false;
    },
    enabled: Number.isFinite(id),
  });
}

export function useIncidentRuns(id: number, active = false) {
  return useQuery({
    queryKey: ["incident-runs", id],
    queryFn: async () => {
      const { data } = await api.get<AutomationRun[]>(`/incidents/${id}/runs`);
      return data;
    },
    enabled: Number.isFinite(id),
    refetchInterval: active ? 5000 : false,
  });
}

export function useStats(filters?: { status?: string; severity?: string; source?: string; q?: string }) {
  return useQuery({
    queryKey: ["stats", filters],
    queryFn: async () => {
      const { data } = await api.get<StatsSummary>("/incidents/stats/summary", {
        params: filters,
      });
      return data;
    },
    refetchInterval: 10000,
  });
}

export function useUpdateIncident(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: Partial<Incident>) => {
      const { data } = await api.patch<Incident>(`/incidents/${id}`, patch);
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["incident", id] });
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useCreateIncident() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      title: string;
      message: string;
      severity?: string;
      fingerprint?: string;
    }) => {
      const { data } = await api.post<Incident>("/incidents/", body);
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useDeleteIncident() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/incidents/${id}`);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
