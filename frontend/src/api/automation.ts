import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { AutomationRule } from "./types";

export function useRules() {
  return useQuery({
    queryKey: ["rules"],
    queryFn: async () => {
      const { data } = await api.get<AutomationRule[]>("/automation-rules/");
      return data;
    },
  });
}

export function useActions() {
  return useQuery({
    queryKey: ["actions"],
    queryFn: async () => {
      const { data } = await api.get<{ actions: string[] }>("/automation-rules/actions");
      return data.actions;
    },
  });
}

export function useCreateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Omit<AutomationRule, "id">) => {
      const { data } = await api.post<AutomationRule>("/automation-rules/", body);
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useToggleRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, enabled }: { id: number; enabled: boolean }) => {
      const { data } = await api.patch<AutomationRule>(`/automation-rules/${id}`, { enabled });
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useUpdateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...patch
    }: {
      id: number;
      severity?: string;
      action_name?: string;
      enabled?: boolean;
      execution_order?: number;
      config?: Record<string, unknown>;
    }) => {
      const { data } = await api.patch<AutomationRule>(`/automation-rules/${id}`, patch);
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useDeleteRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/automation-rules/${id}`);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}
