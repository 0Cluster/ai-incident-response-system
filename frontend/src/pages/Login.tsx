import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, apiErrorMessage, setToken } from "../api/client";

export default function Login() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await api.post("/auth/login", { email, password });
      setToken(response.data.access_token);
      qc.clear();
      navigate("/");
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Login failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-sm rounded-lg border bg-white p-6 shadow-sm">
      <h2 className="mb-1 text-2xl font-bold">Sign in</h2>
      <p className="mb-5 text-sm text-gray-500">
        Use your account, or create one below. The demo stays open when
        authentication is not enabled.
      </p>
      <form className="space-y-3" onSubmit={submit}>
        <label className="block text-sm font-medium">
          Email
          <input
            className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label className="block text-sm font-medium">
          Password
          <input
            className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          className="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          type="submit"
          disabled={busy}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="mt-4 text-center text-sm text-gray-500">
        New here?{" "}
        <Link className="underline" to="/register">
          Create an account
        </Link>
      </p>
      <p className="mt-2 text-center text-sm text-gray-500">
        <Link className="underline" to="/">Continue without signing in</Link>
      </p>
    </div>
  );
}
