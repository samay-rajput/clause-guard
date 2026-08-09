import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { t } from "../lib/strings";
import { useApp } from "../store/app";
import type { Health } from "../lib/types";
import { Alert, Badge, Card, Metric, Spinner } from "../components/ui";

export default function Dashboard() {
  const lang = useApp((s) => s.lang);
  const health = useQuery<Health>({
    queryKey: ["health"],
    queryFn: () => api.get("/api/health"),
    refetchInterval: (q) => (q.state.data?.status === "ready" ? false : 2500),
  });
  const stats = useQuery({
    queryKey: ["corpus-stats"],
    queryFn: () => api.get("/api/corpus/stats"),
    enabled: health.data?.status === "ready",
  });
  const scenarios = useQuery({
    queryKey: ["scenarios"],
    queryFn: () => api.get("/api/scenarios"),
  });

  const h = health.data;
  const s = stats.data;

  return (
    <div className="grid gap-5">
      <div className="rise rounded-2xl bg-gradient-to-r from-navy via-navy-soft to-navy p-6 text-white shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">📜 {t("appName", lang)}</h1>
            <p className="mt-1 text-sm text-white/75">{t("tagline", lang)}</p>
          </div>
          <div className="grid gap-1.5 text-right text-xs">
            <span className="rounded-full border border-white/25 bg-white/10 px-3 py-1">
              {h?.llm_mode === "ollama" ? `🖥️ local · Ollama ${h?.models.ollama}` : `☁️ cloud · ${h?.models.groq} + ${h?.models.gemini}`}
            </span>
            <span className="rounded-full border border-white/25 bg-white/10 px-3 py-1">
              {h?.muril_on ? "🧠 MuRIL screening ON · ~130 ms/pair" : "MuRIL off — LLM verifies all pairs"}
            </span>
          </div>
        </div>
      </div>

      {h && h.status !== "ready" && (
        <Alert tone="warn">
          <Spinner label={t("warming", lang)} />{" "}
          <span className="text-xs">
            {Object.entries(h.warm ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}
          </span>
        </Alert>
      )}
      {s?.index_mismatch && <Alert tone="bad">⚠ {s.index_mismatch}</Alert>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Metric label={t("realGRs", lang)} value={s ? s.n_grs.toLocaleString() : "…"} />
        <Metric label={t("clauses", lang)} value={s ? s.n_clauses.toLocaleString() : "…"} />
        <Metric label={t("departments", lang)} value={s ? Object.keys(s.departments).length : "…"} />
      </div>

      {s && (
        <Card className="p-4">
          <div className="mb-2 text-sm font-semibold">{t("departments", lang)}</div>
          <div className="grid gap-1.5">
            {Object.entries(s.departments as Record<string, number>)
              .slice(0, 10)
              .map(([dept, n]) => {
                const max = Math.max(...Object.values(s.departments as Record<string, number>));
                return (
                  <div key={dept} className="grid grid-cols-[minmax(0,16rem)_1fr_3.5rem] items-center gap-2 text-xs">
                    <div className="truncate text-muted">{dept.split("(")[0]}</div>
                    <div className="h-3 rounded bg-paper">
                      <div className="barfill h-full rounded bg-navy/60" style={{ width: `${(n / max) * 100}%` }} />
                    </div>
                    <div className="text-right font-semibold">{n.toLocaleString()}</div>
                  </div>
                );
              })}
          </div>
        </Card>
      )}

      <Card className="p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
          🎬 {t("scenarios", lang)} <Badge tone="gold">cached · zero-cost</Badge>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {(scenarios.data ?? []).map((sc: any) => (
            <Link key={sc.id} to={`/review?scenario=${sc.id}`} className="group">
              <Card className="p-3 transition-all group-hover:border-navy/40 group-hover:shadow-lg">
                <div className="text-sm font-semibold text-navy">{sc.label}</div>
                <div className="mt-0.5 text-xs text-muted">{sc.desc}</div>
              </Card>
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}
