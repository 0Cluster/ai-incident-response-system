import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import Dashboard from "./pages/Dashboard";
import Incidents from "./pages/Incidents";
import IncidentDetail from "./pages/IncidentDetail";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Register from "./pages/Register";
import Rules from "./pages/Rules";
import Runbooks from "./pages/Runbooks";
import Settings from "./pages/Settings";
import WebhookTester from "./pages/WebhookTester";
import Investigation from "./pages/Investigation";
import Approvals from "./pages/Approvals";
import { useHealth } from "./api/runbooks";
import { clearToken, errorStatus, getToken } from "./api/client";
import { useMe } from "./api/auth";

const linkCls = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-md text-sm font-medium ${isActive ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-100"}`;

function HealthBadge() {
  const { data } = useHealth();
  if (!data) return null;
  const ok = data.status === "healthy";
  return (
    <span
      title={Object.entries(data.checks ?? {}).map(([k, v]) => `${k}: ${v}`).join(", ")}
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${ok ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}
    >
      {ok ? "● healthy" : "● degraded"}
    </span>
  );
}

export default function App() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(Boolean(getToken()));
  const { data: me, error: meError } = useMe();
  const authError = errorStatus(meError) === 401;

  useEffect(() => {
    const update = () => setSignedIn(Boolean(getToken()));
    window.addEventListener("airs-auth-changed", update);
    return () => window.removeEventListener("airs-auth-changed", update);
  }, []);

  useEffect(() => {
    if (signedIn && authError) {
      clearToken();
      qc.clear();
      navigate("/login");
    }
  }, [signedIn, authError, qc, navigate]);

  const signOut = () => {
    clearToken();
    qc.clear();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link to="/" className="text-lg font-bold">AI Incident Response</Link>
          <nav className="flex flex-wrap gap-1">
            <NavLink to="/" end className={linkCls}>Dashboard</NavLink>
            <NavLink to="/incidents" className={linkCls}>Incidents</NavLink>
            <NavLink to="/rules" className={linkCls}>Automation</NavLink>
            <NavLink to="/runbooks" className={linkCls}>Runbooks</NavLink>
            <NavLink to="/webhooks" className={linkCls}>Webhooks</NavLink>
            {me?.auth_type === "bearer" && me?.user_id !== null && (
              <>
                <NavLink to="/approvals" className={linkCls}>Approvals</NavLink>
                <NavLink to="/settings" className={linkCls}>Settings</NavLink>
              </>
            )}
            {!me || me.auth_type !== "bearer" && (
              <NavLink to="/settings" className={linkCls}>Settings</NavLink>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <HealthBadge />
            {signedIn && me?.auth_type === "bearer" && (
              <span className="hidden text-xs text-gray-500 lg:inline">
                {me.email} · {me.role}
              </span>
            )}
            {signedIn ? (
              <button className="text-sm text-gray-600 underline" onClick={signOut}>
                Sign out
              </button>
            ) : (
              <>
                <NavLink to="/login" className={linkCls}>Sign in</NavLink>
                <NavLink to="/register" className={linkCls}>Register</NavLink>
              </>
            )}
          </div>
        </div>
      </header>
      {authError && !signedIn && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
          Authentication is required. <Link className="underline" to="/login">Sign in</Link> to continue.
        </div>
      )}
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/incidents/:id" element={<IncidentDetail />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/runbooks" element={<Runbooks />} />
          <Route path="/webhooks" element={<WebhookTester />} />
          <Route path="/incidents/:id/investigation" element={<Investigation />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}
