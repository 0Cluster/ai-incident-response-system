import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface Tenant {
  id: number;
  slug: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TenantCreated extends Tenant {
  webhook_secret: string;
}

export interface CreateTenantBody {
  slug: string;
  name: string;
  is_active: boolean;
}

export function useMyTenant() {
  return useQuery({
    queryKey: ["tenant-me"],
    queryFn: async () => {
      const { data } = await api.get<Tenant>("/tenants/me");
      return data;
    },
    staleTime: 30_000,
  });
}

export function useTenants(enabled: boolean) {
  return useQuery({
    queryKey: ["tenants"],
    queryFn: async () => {
      const { data } = await api.get<Tenant[]>("/tenants/");
      return data;
    },
    enabled,
  });
}

export function useCreateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateTenantBody) => {
      const { data } = await api.post<TenantCreated>("/tenants/", body);
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["tenants"] }),
  });
}

export function useUpdateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: { id: number; name?: string; is_active?: boolean }) => {
      const { data } = await api.patch<Tenant>(`/tenants/${id}`, body);
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["tenant-me"] });
    },
  });
}
