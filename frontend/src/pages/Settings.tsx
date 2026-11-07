import { useState } from "react";
import { Link } from "react-router-dom";
import { apiErrorMessage, errorStatus } from "../api/client";
import {
  roleAtLeast,
  useCreateToken,
  useCreateUser,
  useMe,
  useRevokeToken,
  useTokens,
  useUpdateUser,
  useUsers,
} from "../api/auth";
import type {
  AuthUser,
  Me,
  TokenCreated,
  TokenInfo,
  UserRole,
} from "../api/auth";
import {
  useCreateTenant,
  useTenants,
  useUpdateTenant,
} from "../api/tenants";
import type { Tenant, TenantCreated } from "../api/tenants";

const inputCls = "rounded-md border px-2 py-1.5 text-sm";

function fmtDate(value: string | null | undefined): string {
  if (!value) return "never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function RoleBadge({ role, superadmin }: { role: UserRole; superadmin?: boolean }) {
  const cls =
    role === "ADMIN"
      ? "bg-purple-100 text-purple-800"
      : role === "RESPONDER"
        ? "bg-blue-100 text-blue-800"
        : "bg-gray-100 text-gray-700";
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{role}</span>
      {superadmin && (
        <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
          superadmin
        </span>
      )}
    </span>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-white p-4 shadow-sm">
      <h3 className="text-lg font-semibold">{title}</h3>
      {description && <p className="mt-1 mb-3 text-sm text-gray-500">{description}</p>}
      <div className={description ? "" : "mt-3"}>{children}</div>
    </section>
  );
}

function AccountCard({ me }: { me: Me }) {
  return (
    <Section title="Account">
      <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-xs uppercase text-gray-500">Email</dt>
          <dd className="font-medium">
            {me.email}
            {me.auth_type === "anonymous" && (
              <span className="ml-2 text-xs text-gray-500">(demo access)</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-gray-500">Role</dt>
          <dd className="mt-0.5">
            <RoleBadge role={me.role} superadmin={me.is_superadmin} />
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-gray-500">Tenant</dt>
          <dd className="font-medium">
            {me.tenant_slug} <span className="text-xs text-gray-500">#{me.tenant_id}</span>
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-gray-500">Auth type</dt>
          <dd className="font-medium">{me.auth_type}</dd>
        </div>
      </dl>
      {me.auth_type !== "bearer" && (
        <p className="mt-3 text-xs text-gray-500">
          Personal API tokens require a signed-in account.{" "}
          <Link className="underline" to="/login">Sign in</Link> or{" "}
          <Link className="underline" to="/register">create an account</Link>.
        </p>
      )}
    </Section>
  );
}

function TokensSection({ me }: { me: Me }) {
  const enabled = me.auth_type === "bearer" && me.user_id !== null;
  const { data: tokens, isLoading, error } = useTokens(enabled);
  const create = useCreateToken();
  const revoke = useRevokeToken();
  const [name, setName] = useState("frontend");
  const [expires, setExpires] = useState("");
  const [created, setCreated] = useState<TokenCreated | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const submit = () => {
    setFormError(null);
    const hours = expires.trim() ? Number(expires) : null;
    if (hours !== null && (!Number.isInteger(hours) || hours < 1 || hours > 8760)) {
      setFormError("Expiry must be a whole number of hours between 1 and 8760.");
      return;
    }
    create.mutate(
      { name: name.trim() || "default", expires_hours: hours },
      {
        onSuccess: (data) => {
          setCreated(data);
          setName("frontend");
          setExpires("");
        },
        onError: (err) => setFormError(apiErrorMessage(err, "Could not create token")),
      },
    );
  };

  return (
    <Section
      title="API tokens"
      description="Tokens authenticate scripts and integrations. The raw value is shown only once."
    >
      {!enabled ? (
        <p className="text-sm text-gray-600">
          Sign in with a user account to list and issue personal API tokens.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-gray-500">
              Name
              <input
                className={`${inputCls} mt-1 block`}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ci-runner"
              />
            </label>
            <label className="text-xs text-gray-500">
              Expires in hours (blank = default TTL)
              <input
                className={`${inputCls} mt-1 block w-40`}
                value={expires}
                onChange={(e) => setExpires(e.target.value)}
                type="number"
                min={1}
                max={8760}
                placeholder="24"
              />
            </label>
            <button
              disabled={create.isPending}
              onClick={submit}
              className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {create.isPending ? "Creating…" : "Create token"}
            </button>
          </div>
          {formError && <p className="text-sm text-red-600">{formError}</p>}
          {created && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3">
              <p className="text-sm font-medium text-amber-900">
                New token created — copy it now. It will not be shown again.
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <code className="max-w-full overflow-x-auto rounded bg-white px-2 py-1 text-xs">
                  {created.access_token}
                </code>
                <CopyButton value={created.access_token} />
              </div>
              <p className="mt-1 text-xs text-amber-800">
                Expires {fmtDate(created.expires_at)}.
              </p>
            </div>
          )}

          {isLoading && <p className="text-sm text-gray-500">Loading tokens…</p>}
          {error && <p className="text-sm text-red-600">{apiErrorMessage(error, "Could not load tokens")}</p>}
          {revokeError && <p className="text-sm text-red-600">{revokeError}</p>}
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Created</th>
                  <th className="px-3 py-2">Expires</th>
                  <th className="px-3 py-2">Last used</th>
                  <th className="px-3 py-2">Ops</th>
                </tr>
              </thead>
              <tbody>
                {(tokens ?? []).map((token: TokenInfo) => (
                  <tr key={token.id} className="border-t">
                    <td className="px-3 py-2">{token.name}</td>
                    <td className="px-3 py-2 text-gray-500">{fmtDate(token.created_at)}</td>
                    <td className="px-3 py-2 text-gray-500">{fmtDate(token.expires_at)}</td>
                    <td className="px-3 py-2 text-gray-500">{fmtDate(token.last_used_at)}</td>
                    <td className="px-3 py-2">
                      <button
                        className="text-red-600 hover:underline"
                        onClick={() => {
                          if (!confirm(`Revoke token "${token.name}"?`)) return;
                          setRevokeError(null);
                          revoke.mutate(token.id, {
                            onError: (err) => setRevokeError(apiErrorMessage(err, "Could not revoke token")),
                          });
                        }}
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
                {(tokens ?? []).length === 0 && (
                  <tr>
                    <td className="px-3 py-3 text-gray-500" colSpan={5}>No tokens yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Section>
  );
}

function UserRow({
  user,
  me,
}: {
  user: AuthUser;
  me: Me;
}) {
  const update = useUpdateUser();
  const [role, setRole] = useState<UserRole>(user.role);
  const [active, setActive] = useState(user.is_active);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const isSelf = user.id === me.user_id;
  const locked = isSelf || (!me.is_superadmin && user.is_superadmin);
  const dirty = role !== user.role || active !== user.is_active;

  const save = () => {
    setError(null);
    setNotice(null);
    update.mutate(
      { id: user.id, role, is_active: active },
      {
        onSuccess: () => setNotice("Saved"),
        onError: (err) => setError(apiErrorMessage(err, "Could not update user")),
      },
    );
  };

  const resetPassword = () => {
    const password = window.prompt(`New password for ${user.email} (minimum 8 characters)`);
    if (password === null) return;
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setError(null);
    setNotice(null);
    update.mutate(
      { id: user.id, password },
      {
        onSuccess: () => setNotice("Password updated"),
        onError: (err) => setError(apiErrorMessage(err, "Could not reset password")),
      },
    );
  };

  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {user.email}
            {isSelf && <span className="ml-2 text-xs text-gray-500">(you)</span>}
          </p>
          <p className="mt-1 text-xs text-gray-500">
            tenant #{user.tenant_id} · created {fmtDate(user.created_at)}
          </p>
        </div>
        <RoleBadge role={user.role} superadmin={user.is_superadmin} />
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-gray-500">
          Role
          <select
            className={`${inputCls} mt-1 block`}
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
            disabled={locked}
          >
            <option value="VIEWER">VIEWER</option>
            <option value="RESPONDER">RESPONDER</option>
            <option value="ADMIN">ADMIN</option>
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
            disabled={locked}
          />
          Active
        </label>
        <button
          disabled={locked || !dirty || update.isPending}
          onClick={save}
          className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          Save
        </button>
        <button
          disabled={!me.is_superadmin && user.is_superadmin}
          onClick={resetPassword}
          className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
        >
          Reset password
        </button>
        {locked && (
          <span className="text-xs text-gray-500">
            {isSelf ? "You cannot change your own role or active state." : "Superadmin is read-only."}
          </span>
        )}
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      {notice && <p className="mt-2 text-xs text-green-700">{notice}</p>}
    </div>
  );
}

function UsersSection({ me }: { me: Me }) {
  const { data: users, isLoading, error } = useUsers(true);
  const create = useCreateUser();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("VIEWER");
  const [active, setActive] = useState(true);
  const [tenantSlug, setTenantSlug] = useState("");
  const [superadmin, setSuperadmin] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = () => {
    setFormError(null);
    setNotice(null);
    if (password.length < 8) {
      setFormError("Password must be at least 8 characters.");
      return;
    }
    create.mutate(
      {
        email,
        password,
        role,
        is_active: active,
        tenant_slug: me.is_superadmin && tenantSlug.trim() ? tenantSlug.trim() : undefined,
        is_superadmin: me.is_superadmin && superadmin,
      },
      {
        onSuccess: (user) => {
          setNotice(`Created ${user.email}`);
          setEmail("");
          setPassword("");
          setRole("VIEWER");
          setActive(true);
          setTenantSlug("");
          setSuperadmin(false);
        },
        onError: (err) => setFormError(apiErrorMessage(err, "Could not create user")),
      },
    );
  };

  return (
    <Section
      title="Users"
      description="Admins manage users in their tenant. Superadmins can create users in any tenant."
    >
      <div className="space-y-4">
        <div className="grid gap-2 rounded-md border bg-gray-50 p-3 sm:grid-cols-2 lg:grid-cols-6">
          <label className="text-xs text-gray-500 sm:col-span-2">
            Email
            <input
              className={`${inputCls} mt-1 block w-full`}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              placeholder="user@example.com"
            />
          </label>
          <label className="text-xs text-gray-500">
            Password
            <input
              className={`${inputCls} mt-1 block w-full`}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              minLength={8}
              placeholder="min 8 chars"
            />
          </label>
          <label className="text-xs text-gray-500">
            Role
            <select
              className={`${inputCls} mt-1 block w-full`}
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
            >
              <option value="VIEWER">VIEWER</option>
              <option value="RESPONDER">RESPONDER</option>
              <option value="ADMIN">ADMIN</option>
            </select>
          </label>
          {me.is_superadmin && (
            <label className="text-xs text-gray-500">
              Tenant slug
              <input
                className={`${inputCls} mt-1 block w-full`}
                value={tenantSlug}
                onChange={(e) => setTenantSlug(e.target.value)}
                placeholder="default"
              />
            </label>
          )}
          <div className="flex flex-col justify-end gap-1 pb-1 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
              Active
            </label>
            {me.is_superadmin && (
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={superadmin} onChange={(e) => setSuperadmin(e.target.checked)} />
                Superadmin
              </label>
            )}
          </div>
          <div className="flex items-end">
            <button
              disabled={create.isPending || !email || password.length < 8}
              onClick={submit}
              className="w-full rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {create.isPending ? "Creating…" : "Create user"}
            </button>
          </div>
        </div>
        {formError && <p className="text-sm text-red-600">{formError}</p>}
        {notice && <p className="text-sm text-green-700">{notice}</p>}

        {isLoading && <p className="text-sm text-gray-500">Loading users…</p>}
        {error && <p className="text-sm text-red-600">{apiErrorMessage(error, "Could not load users")}</p>}
        <div className="space-y-2">
          {(users ?? []).map((user) => (
            <UserRow key={`${user.id}-${user.updated_at}`} user={user} me={me} />
          ))}
          {(users ?? []).length === 0 && <p className="text-sm text-gray-500">No users yet.</p>}
        </div>
      </div>
    </Section>
  );
}

function TenantRow({ tenant }: { tenant: Tenant }) {
  const update = useUpdateTenant();
  const [name, setName] = useState(tenant.name);
  const [active, setActive] = useState(tenant.is_active);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const isDefault = tenant.slug === "default";
  const dirty = name !== tenant.name || active !== tenant.is_active;

  const save = () => {
    setError(null);
    setNotice(null);
    update.mutate(
      { id: tenant.id, name, is_active: active },
      {
        onSuccess: () => setNotice("Saved"),
        onError: (err) => setError(apiErrorMessage(err, "Could not update tenant")),
      },
    );
  };

  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">{tenant.name}</p>
          <p className="mt-1 text-xs text-gray-500">
            {tenant.slug} · tenant #{tenant.id} · created {fmtDate(tenant.created_at)}
          </p>
        </div>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${tenant.is_active ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>
          {tenant.is_active ? "active" : "inactive"}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-gray-500">
          Name
          <input className={`${inputCls} mt-1 block`} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
            disabled={isDefault}
          />
          Active
        </label>
        <button
          disabled={!dirty || update.isPending}
          onClick={save}
          className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          Save
        </button>
        {isDefault && <span className="text-xs text-gray-500">The default tenant cannot be deactivated.</span>}
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      {notice && <p className="mt-2 text-xs text-green-700">{notice}</p>}
    </div>
  );
}

function TenantsSection() {
  const { data: tenants, isLoading, error } = useTenants(true);
  const create = useCreateTenant();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [active, setActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<TenantCreated | null>(null);

  const submit = () => {
    setFormError(null);
    create.mutate(
      { slug: slug.trim().toLowerCase(), name: name.trim(), is_active: active },
      {
        onSuccess: (tenant) => {
          setCreated(tenant);
          setSlug("");
          setName("");
          setActive(true);
        },
        onError: (err) => setFormError(apiErrorMessage(err, "Could not create tenant")),
      },
    );
  };

  return (
    <Section
      title="Tenants"
      description="Tenants isolate incidents, rules, runbooks, users, and automation data. Only superadmins can manage tenants."
    >
      <div className="space-y-4">
        <div className="grid gap-2 rounded-md border bg-gray-50 p-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="text-xs text-gray-500">
            Slug
            <input
              className={`${inputCls} mt-1 block w-full`}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="acme"
            />
          </label>
          <label className="text-xs text-gray-500 sm:col-span-2">
            Name
            <input
              className={`${inputCls} mt-1 block w-full`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Corp"
            />
          </label>
          <label className="flex items-center gap-2 pt-5 text-sm">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active
          </label>
          <div className="flex items-end">
            <button
              disabled={create.isPending || !slug.trim() || !name.trim()}
              onClick={submit}
              className="w-full rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {create.isPending ? "Creating…" : "Create tenant"}
            </button>
          </div>
        </div>
        {formError && <p className="text-sm text-red-600">{formError}</p>}
        {created && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3">
            <p className="text-sm font-medium text-amber-900">
              Tenant “{created.name}” created. Store its bootstrap webhook secret now.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <code className="max-w-full overflow-x-auto rounded bg-white px-2 py-1 text-xs">
                {created.webhook_secret}
              </code>
              <CopyButton value={created.webhook_secret} />
            </div>
            <p className="mt-1 text-xs text-amber-800">
              Per-tenant webhook routing is reserved for a future release; the global
              WEBHOOK_SECRET is still used by the ingest endpoints.
            </p>
          </div>
        )}

        {isLoading && <p className="text-sm text-gray-500">Loading tenants…</p>}
        {error && <p className="text-sm text-red-600">{apiErrorMessage(error, "Could not load tenants")}</p>}
        <div className="space-y-2">
          {(tenants ?? []).map((tenant) => (
            <TenantRow key={`${tenant.id}-${tenant.updated_at}`} tenant={tenant} />
          ))}
          {(tenants ?? []).length === 0 && <p className="text-sm text-gray-500">No tenants found.</p>}
        </div>
      </div>
    </Section>
  );
}

export default function Settings() {
  const { data: me, isLoading, error } = useMe();

  if (isLoading) return <p className="text-gray-500">Loading account…</p>;
  if (!me) {
    const status = errorStatus(error);
    return (
      <div className="mx-auto max-w-lg rounded-lg border bg-white p-6">
        <h2 className="mb-2 text-2xl font-bold">Settings</h2>
        <p className="text-sm text-gray-600">
          {status === 401
            ? "Sign in to view account and administration settings."
            : apiErrorMessage(error, "Could not load account settings")}
        </p>
        {status === 401 && (
          <Link className="mt-3 inline-block text-blue-600 hover:underline" to="/login">
            Sign in
          </Link>
        )}
      </div>
    );
  }

  const isAdmin = roleAtLeast(me.role, "ADMIN");
  const isSuperadmin = isAdmin && me.is_superadmin;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold">Settings</h2>
        <span className="text-sm text-gray-500">
          {isAdmin ? "Administrator view" : "Account view"}
        </span>
      </div>
      <AccountCard me={me} />
      <TokensSection me={me} />
      {isAdmin && <UsersSection me={me} />}
      {isSuperadmin && <TenantsSection />}
      {!isAdmin && (
        <Section title="Administration">
          <p className="text-sm text-gray-600">
            User, tenant, automation-rule, runbook, and reindex administration require
            the ADMIN role. Your current role is {me.role}.
          </p>
        </Section>
      )}
    </div>
  );
}
