/** Review page: paste / upload / scenario → SSE-streamed pipeline run →
 * KPI header + Conflicts | References | Scorecard | Glossary tabs. */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { t } from "../lib/strings";
import { useApp } from "../store/app";
import type { FullReview } from "../lib/types";
import { ConflictCard } from "../components/ConflictCard";
import { ExportBar } from "../components/Exports";
import { Funnel } from "../components/Funnel";
import { RefsPanel, ScorePanel, TermsPanel } from "../components/ReviewPanels";
import { Alert, Badge, Button, Card, Metric, Spinner, Tabs, Textarea } from "../components/ui";

export default function Review() {
  const lang = useApp((s) => s.lang);
  const [params] = useSearchParams();
  const [draft, setDraft] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [result, setResult] = useState<FullReview | null>(null);
  const [prevPct, setPrevPct] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState("conflicts");
  const [warning, setWarning] = useState<string | null>(null);
  const stepsEnd = useRef<HTMLDivElement>(null);

  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: () => api.get("/api/scenarios") });

  // deep-link: /review?scenario=1_fee_conflict_draft
  const scenarioParam = params.get("scenario");
  useEffect(() => {
    if (scenarioParam) {
      api.get(`/api/scenarios/${scenarioParam}`).then((d) => setDraft(d.text)).catch(() => {});
    }
  }, [scenarioParam]);

  useEffect(() => {
    stepsEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [steps]);

  async function run() {
    setRunning(true);
    setErr(null);
    setSteps([]);
    setPrevPct(result?.score?.pct ?? null);
    try {
      const { job_id } = await api.post("/api/review", { draft, top_k: 10 });
      const res = await api.job<FullReview>(job_id, (msg) => setSteps((s) => [...s, msg]));
      setResult(res);
      setTab("conflicts");
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setRunning(false);
    }
  }

  async function onUpload(file: File) {
    setErr(null);
    setWarning(null);
    try {
      const d = await api.upload("/api/drafts/extract-text", file);
      setDraft(d.text);
      if (d.warning) setWarning(d.warning);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    }
  }

  const r = result?.review;
  const conflicts = r && !r.error ? r.conflicts ?? [] : [];
  const warnCount = (result?.refs?.stale.length ?? 0) + (result?.refs?.newer_related.length ?? 0);

  return (
    <div className="grid gap-4">
      <Card className="grid gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-lg font-bold text-navy">🔍 {t("reviewDraft", lang)}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="rounded-lg border border-line bg-white px-2 py-1.5 text-sm"
              value={scenarioParam ?? ""}
              onChange={async (e) => {
                if (!e.target.value) return;
                const d = await api.get(`/api/scenarios/${e.target.value}`);
                setDraft(d.text);
              }}
            >
              <option value="">{t("scenarios", lang)}…</option>
              {(scenarios.data ?? []).map((s: any) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
            <label className="cursor-pointer rounded-lg border border-line bg-card px-3 py-1.5 text-sm font-semibold hover:border-navy/40">
              📎 {t("uploadDraft", lang)}
              <input
                type="file"
                accept=".txt,.md,.pdf"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
              />
            </label>
          </div>
        </div>
        <Textarea
          rows={9}
          value={draft}
          placeholder={t("pasteDraft", lang)}
          onChange={(e) => setDraft(e.target.value)}
        />
        {warning && <Alert tone="warn">{warning}</Alert>}
        <Button onClick={run} disabled={running || !draft.trim()} className="w-full">
          {running ? <Spinner /> : "🔍"} {t("reviewDraft", lang)}
        </Button>
        {running && (
          <div className="max-h-28 overflow-y-auto rounded-lg bg-navy/5 p-3 font-mono text-xs text-navy">
            {steps.map((s, i) => (
              <div key={i} className="rise">▸ {s}</div>
            ))}
            <div ref={stepsEnd} />
          </div>
        )}
        {err && <Alert tone="bad">{err}</Alert>}
      </Card>

      {result && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric
              label={t("verifiedConflicts", lang)}
              value={r?.error ? "n/a" : conflicts.length}
              tone={conflicts.length ? "bad" : "ok"}
            />
            <Metric label={t("citationWarnings", lang)} value={result.refs ? warnCount : "n/a"} tone={warnCount ? "warn" : "ok"} />
            <Metric
              label={t("compliance", lang)}
              value={`${result.score.pct}%`}
              delta={prevPct != null && prevPct !== result.score.pct ? `${result.score.pct - prevPct > 0 ? "+" : ""}${result.score.pct - prevPct}%` : null}
              tone={result.score.pct >= (prevPct ?? 0) ? "ok" : "bad"}
            />
            <Metric label={t("termFlags", lang)} value={result.terms.n_flags} tone={result.terms.n_flags ? "warn" : "ok"} />
          </div>

          {r && !r.error && <Funnel review={r} />}

          <Tabs
            active={tab}
            onSelect={setTab}
            tabs={[
              { id: "conflicts", label: `⚠️ ${t("conflicts", lang)}`, badge: conflicts.length },
              { id: "refs", label: `🔗 ${t("refsTab", lang)}`, badge: warnCount },
              { id: "score", label: `✅ ${t("scorecard", lang)}` },
              { id: "terms", label: `📖 ${t("glossary", lang)}`, badge: result.terms.n_flags },
            ]}
          />

          <div className="min-h-40">
            {tab === "conflicts" && (
              <div className="grid gap-3">
                {r?.error && (
                  <Alert tone="bad">
                    Conflict analysis unavailable: {r.error}
                  </Alert>
                )}
                {!r?.error && conflicts.length === 0 && <Alert tone="ok">✓ {t("noConflicts", lang)}</Alert>}
                {(r?.verdicts ?? []).filter((v) => v.label === "error").length > 0 && (
                  <Alert tone="warn">
                    {(r!.verdicts ?? []).filter((v) => v.label === "error").length} pair verification(s) failed — results may be incomplete.
                  </Alert>
                )}
                {conflicts.map((c, i) => (
                  <ConflictCard key={i} conflict={c} />
                ))}
              </div>
            )}
            {tab === "refs" && <RefsPanel refs={result.refs} />}
            {tab === "score" && <ScorePanel score={result.score} prevPct={prevPct} />}
            {tab === "terms" && <TermsPanel terms={result.terms} />}
          </div>

          <Card className="p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
              📤 Export {result.audit_ts && <Badge tone="gold">audit ✓ {result.audit_ts}</Badge>}
            </div>
            <ExportBar draft={draft} review={result} />
          </Card>
        </>
      )}
    </div>
  );
}
