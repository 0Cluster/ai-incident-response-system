import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface RunbookItem {
  name: string;
  chars: number;
  chunks: number;
}

export function useRunbooks() {
  return useQuery({
    queryKey: ["runbooks"],
    queryFn: async () => {
      const { data } = await api.get<{ items: RunbookItem[]; backend: string }>("/runbooks/");
      return data;
    },
  });
}

export function useRunbook(name: string | null) {
  return useQuery({
    queryKey: ["runbook", name],
    queryFn: async () => {
      const { data } = await api.get<{ name: string; content: string; chunks: number }>(`/runbooks/${name}`);
      return data;
    },
    enabled: !!name,
  });
}

export function useSaveRunbook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ name, content }: { name: string; content: string }) => {
      const { data } = await api.put(`/runbooks/${name}`, { content });
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["runbooks"] });
      qc.invalidateQueries({ queryKey: ["runbook"] });
    },
  });
}

export function useDeleteRunbook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      await api.delete(`/runbooks/${name}`);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["runbooks"] });
    },
  });
}

export function useReindex() {
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<{ task_id: string | null; status: string; backend: string }>("/runbooks/reindex");
      if (data.task_id) {
        for (let i = 0; i < 30; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const s = await api.get<{ status: string; ready: boolean }>(`/runbooks/reindex/${data.task_id}`);
          if (s.data.ready) return { ...data, status: s.data.status };
        }
        return { ...data, status: "unknown" };
      }
      return data;
    },
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data } = await api.get<{ status: string; checks: Record<string, string> }>("/health", {
        baseURL: (import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1").replace(/\/api\/v1$/, ""),
      });
      return data;
    },
    refetchInterval: 15000,
  });
}
