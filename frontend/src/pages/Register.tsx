import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, apiErrorMessage, setToken } from "../api/client";

export default function Register() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const response = await api.post("/auth/register", { email, password });
      setToken(response.data.access_token);
      qc.clear();
      navigate("/");
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Registration failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-sm rounded-lg border bg-white p-6 shadow-sm">
      <h2 className="mb-1 text-2xl font-bold">Create account</h2>
      <p className="mb-5 text-sm text-gray-500">
        The first account in an empty workspace becomes an administrator. Later
        accounts start as viewers.
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
            autoComplete="new-password"
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        <label className="block text-sm font-medium">
          Confirm password
          <input
            className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          className="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          type="submit"
          disabled={busy}
        >
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="mt-4 text-center text-sm text-gray-500">
        Already have an account?{" "}
        <Link className="underline" to="/login">
          Sign in
        </Link>
      </p>
      <p className="mt-2 text-center text-sm text-gray-500">
        <Link className="underline" to="/">
          Continue without signing in
        </Link>
      </p>
    </div>
  );
}
