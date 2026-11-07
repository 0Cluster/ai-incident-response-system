import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export type UserRole = "VIEWER" | "RESPONDER" | "ADMIN";

const ROLE_RANK: Record<UserRole, number> = {
  VIEWER: 1,
  RESPONDER: 2,
  ADMIN: 3,
};

export function roleAtLeast(
  role: UserRole | undefined,
  minimum: UserRole,
): boolean {
  return role ? ROLE_RANK[role] >= ROLE_RANK[minimum] : false;
}

export interface Me {
  user_id: number | null;
  email: string;
  role: UserRole;
  auth_type: string;
  tenant_id: number;
  tenant_slug: string;
  is_superadmin: boolean;
}

export interface AuthUser {
  id: number;
  email: string;
  tenant_id: number;
  role: UserRole;
  is_active: boolean;
  is_superadmin: boolean;
  created_at: string;
  updated_at: string;
}

export interface TokenInfo {
  id: number;
  name: string;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface TokenCreated {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: AuthUser;
}

export interface CreateUserBody {
  email: string;
  password: string;
  role: UserRole;
  is_active: boolean;
  tenant_slug?: string;
  is_superadmin: boolean;
}

export interface UpdateUserBody {
  role?: UserRole;
  is_active?: boolean;
  password?: string;
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const { data } = await api.get<Me>("/auth/me");
      return data;
    },
    staleTime: 30_000,
    retry: false,
  });
}

export function useUsers(enabled: boolean) {
  return useQuery({
    queryKey: ["auth-users"],
    queryFn: async () => {
      const { data } = await api.get<AuthUser[]>("/auth/users");
      return data;
    },
    enabled,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateUserBody) => {
      const { data } = await api.post<AuthUser>("/auth/users", body);
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["auth-users"] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: number } & UpdateUserBody) => {
      const { data } = await api.patch<AuthUser>(`/auth/users/${id}`, body);
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["auth-users"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useTokens(enabled: boolean) {
  return useQuery({
    queryKey: ["auth-tokens"],
    queryFn: async () => {
      const { data } = await api.get<TokenInfo[]>("/auth/tokens");
      return data;
    },
    enabled,
  });
}

export function useCreateToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; expires_hours: number | null }) => {
      const { data } = await api.post<TokenCreated>("/auth/tokens", body);
      return data;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["auth-tokens"] }),
  });
}

export function useRevokeToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/auth/tokens/${id}`);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["auth-tokens"] }),
  });
}
