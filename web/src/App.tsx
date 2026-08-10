import { useEffect } from "react";
import { NavLink, Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { api, setSessionListener } from "./lib/api";
import { t } from "./lib/strings";
import { useApp } from "./store/app";
import { LangSwitch, Spinner, cx } from "./components/ui";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Studio from "./pages/Studio";
import Review from "./pages/Review";
import Audit from "./pages/Audit";

function Shell() {
  const { lang, user, setLang, setUser } = useApp();
  const nav = useNavigate();

  const links = [
    { to: "/", label: t("dashboard", lang), icon: "🏛️" },
    { to: "/studio", label: t("studio", lang), icon: "✍️" },
    { to: "/review", label: t("review", lang), icon: "🔍" },
    { to: "/audit", label: t("audit", lang), icon: "🗂️" },
  ];

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-card/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-2.5">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2 font-bold text-navy">
              <span className="text-xl">📜</span> ClauseGuard
              <span className="rounded bg-gold-soft px-1.5 text-[10px] font-bold text-gold">R3</span>
            </div>
            <nav className="flex gap-1">
              {links.map((l) => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  end={l.to === "/"}
                  className={({ isActive }) =>
                    cx(
                      "rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors",
                      isActive ? "bg-navy text-white" : "text-muted hover:bg-navy/5 hover:text-ink",
                    )
                  }
                >
                  <span className="mr-1">{l.icon}</span>
                  <span className="hidden sm:inline">{l.label}</span>
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <LangSwitch lang={lang} onChange={setLang} />
            <span className="hidden text-xs text-muted md:inline">
              {user?.username} · {user?.role}
            </span>
            <button
              onClick={async () => {
                await api.logout();
                setUser(null);
                nav("/login");
              }}
              className="cursor-pointer rounded-lg px-2.5 py-1 text-xs font-semibold text-maroon hover:bg-maroon/5"
            >
              {t("logout", lang)}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-5">
        <Outlet />
      </main>
    </div>
  );
}

function Protected() {
  const { user, sessionChecked } = useApp();
  if (!sessionChecked) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label="…" />
      </div>
    );
  }
  return user ? <Shell /> : <Navigate to="/login" replace />;
}

export default function App() {
  const { setUser, setSessionChecked, sessionChecked } = useApp();

  useEffect(() => {
    setSessionListener((u) => setUser(u));
    if (!sessionChecked) {
      api.tryResume().finally(() => setSessionChecked());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/studio" element={<Studio />} />
        <Route path="/review" element={<Review />} />
        <Route path="/audit" element={<Audit />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
