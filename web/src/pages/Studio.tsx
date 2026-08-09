/** Draft Studio — the round-2 drafting rail as a single flowing page:
 * topic → live precedent preview → audited AI prefill → reviewed form →
 * deterministic render → inline conflict check → one-click fix → export. */
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { t } from "../lib/strings";
import { useApp } from "../store/app";
import type { Conflict, FullReview, GRForm, Generated, Precedent } from "../lib/types";
import { ConflictCard } from "../components/ConflictCard";
import { ExportBar } from "../components/Exports";
import { Alert, Badge, Button, Card, Input, Label, Spinner, Textarea } from "../components/ui";

interface PrefillMeta {
  ai_used?: boolean;
  ai_error?: string | null;
  scrubbed?: string[];
  scrubbed_entities?: string[];
  wording?: Array<{ idx: number; src: number; containment: number | null; verdict: string }> | null;
  needs_numbers?: string[];
}

const emptyFields = {
  subject: "", department: "", gr_number: "", date: new Date().toISOString().slice(0, 10),
  references: "", background: "", clauses: "", budget_head: "", signatory: "", designation: "",
};

export default function Studio() {
  const uiLang = useApp((s) => s.lang);
  const [draftLang, setDraftLang] = useState<"mr" | "en">("mr");
  const [topic, setTopic] = useState("");
  const [preview, setPreview] = useState<Precedent[]>([]);
  const [prefill, setPrefill] = useState<GRForm | null>(null);
  const [meta, setMeta] = useState<PrefillMeta | null>(null);
  const [fields, setFields] = useState(emptyFields);
  const [generated, setGenerated] = useState<Generated | null>(null);
  const [grForm, setGrForm] = useState<GRForm | null>(null);
  const [review, setReview] = useState<FullReview | null>(null);
  const [autoMeta, setAutoMeta] = useState<any | null>(null);
  const [fixApplied, setFixApplied] = useState<string | null>(null);
  const [useBrief, setUseBrief] = useState(false);
  const [brief, setBrief] = useState("");
  const [nClauses, setNClauses] = useState(3);
  const [busy, setBusy] = useState<string | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const debounceRef = useRef<number | null>(null);

  // instant precedent preview — retrieval only, no LLM, 350 ms debounce
  useEffect(() => {
    if (topic.trim().length < 4) { setPreview([]); return; }
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      try {
        const d = await api.post("/api/generate/preview", { topic, k: 4 });
        setPreview(d.precedents ?? []);
      } catch { /* preview is best-effort */ }
    }, 350);
    return () => { if (debounceRef.current) window.clearTimeout(debounceRef.current); };
  }, [topic]);

  function fillFromForm(f: GRForm) {
    setFields({
      subject: f.subject ?? "",
      department: f.department ?? "",
      gr_number: f.gr_number ?? "",
      date: (f.date ?? new Date().toISOString()).slice(0, 10),
      references: (f.references ?? []).map((r) => r.text).join("\n"),
      background: f.background ?? "",
      clauses: (f.clauses ?? []).join("\n"),
      budget_head: f.budget_head ?? "",
      signatory: f.signatory ?? "",
      designation: f.designation ?? "",
    });
  }

  async function doPrefill() {
    setBusy("prefill");
    setErr(null);
    setAutoMeta(null);
    try {
      const out = await api.post("/api/generate/prefill", { topic, lang: draftLang });
      setPrefill(out.form);
      setMeta({ ai_used: out.ai_used, ai_error: out.ai_error, scrubbed: out.scrubbed,
                scrubbed_entities: out.scrubbed_entities, wording: out.wording,
                needs_numbers: out.needs_numbers });
      fillFromForm(out.form);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setBusy(null);
    }
  }

  async function doAutodraft() {
    setBusy("auto");
    setErr(null);
    setSteps([]);
    setFixApplied(null);
    try {
      const { job_id } = await api.post("/api/generate/autodraft", { topic, lang: draftLang });
      const res = await api.job<any>(job_id, (m) => setSteps((s) => [...s, m]));
      if (!res.ok) throw new Error(res.error ?? "autodraft failed");
      setPrefill(res.form);
      setMeta({ ai_used: res.meta.ai_used, ai_error: res.meta.ai_error, scrubbed: res.meta.scrubbed, needs_numbers: res.meta.needs_numbers });
      fillFromForm(res.form);
      setGrForm(res.form);
      setGenerated({
        draft: res.draft, form: res.form, audit: res.audit,
        ai_used: res.meta.ai_used, ai_error: res.meta.ai_error,
        score: res.compliance, terms: res.terminology, short_clauses: [],
      });
      setAutoMeta(res.meta);
      setReview(null);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setBusy(null);
    }
  }

  function buildForm(): GRForm {
    const extras: Partial<GRForm> = {};
    for (const k of ["topic", "dept_code", "copy_to", "precedents"] as const) {
      if (prefill?.[k] != null) (extras as any)[k] = prefill[k];
    }
    return {
      ...extras,
      lang: draftLang,
      subject: fields.subject,
      department: fields.department,
      gr_number: fields.gr_number,
      date: fields.date,
      references: fields.references.split("\n").filter((r) => r.trim()).map((r) => ({ text: r })),
      background: fields.background,
      clauses: fields.clauses.split("\n").filter((c) => c.trim()),
      budget_head: fields.budget_head,
      signatory: fields.signatory,
      designation: fields.designation,
      ai_used: Boolean(meta?.ai_used),
      ai_error: meta?.ai_error ?? null,
    };
  }

  async function doGenerate(check: boolean) {
    setBusy(check ? "gen-check" : "gen");
    setErr(null);
    setSteps([]);
    setFixApplied(null);
    setAutoMeta(null);
    try {
      // brief mode = the legacy officer's-brief expansion: flat fields, AI may
      // write beyond the form, so no structured gr_form is claimed
      const payload = useBrief
        ? {
            form: {
              lang: draftLang, subject: fields.subject, department: fields.department,
              gr_number: fields.gr_number, date: fields.date,
              references: fields.references.split("\n").filter((r) => r.trim()),
              background: "", clauses: [], budget_head: fields.budget_head,
              signatory: fields.signatory, designation: fields.designation,
            },
            use_ai: true, brief, n_clauses: nClauses, record: !check,
          }
        : { form: buildForm(), use_ai: false, record: !check };
      const out: Generated = await api.post("/api/generate", payload);
      setGenerated(out);
      setGrForm(out.form ?? null);
      setReview(null);
      if (check) {
        const { job_id } = await api.post("/api/review", {
          draft: out.draft, top_k: 10, source: "generate+review",
        });
        const res = await api.job<FullReview>(job_id, (m) => setSteps((s) => [...s, m]));
        setReview(res);
      }
    } catch (e: any) {
      const blanks = e?.detail?.blanks;
      setErr(blanks?.length ? `____ ${uiLang === "mr" ? "रिकाम्या जागा आधी भरा" : "blanks must be filled first"}: ${blanks.join(", ")}` : String(e?.message ?? e));
    } finally {
      setBusy(null);
    }
  }

  async function doFix(c: Conflict) {
    if (!grForm || !c.value1 || !c.value2) return;
    setBusy("fix");
    setErr(null);
    try {
      const out = await api.post("/api/generate/apply-fix", { form: grForm, value1: c.value1, value2: c.value2 });
      setGrForm(out.form);
      setGenerated({ ...out.generated, score: out.score, terms: out.terms, short_clauses: [] });
      fillFromForm(out.form);
      setFixApplied(out.fix_applied);
    } catch (e: any) {
      setErr(uiLang === "mr" ? "दुरुस्ती आपोआप लागू करता आली नाही — फॉर्ममध्ये हाताने बदला." : String(e?.message ?? e));
    } finally {
      setBusy(null);
    }
  }

  async function doRecheck() {
    if (!generated) return;
    setBusy("gen-check");
    setSteps([]);
    setFixApplied(null);
    try {
      const { job_id } = await api.post("/api/review", {
        draft: generated.draft, top_k: 10, source: "generate+review",
      });
      const res = await api.job<FullReview>(job_id, (m) => setSteps((s) => [...s, m]));
      setReview(res);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setBusy(null);
    }
  }

  const conflicts = review?.review && !review.review.error ? review.review.conflicts ?? [] : [];
  const set = (k: keyof typeof emptyFields) => (e: any) => setFields((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="grid gap-4">
      {/* step 1: topic */}
      <Card className="grid gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-lg font-bold text-navy">✍️ {t("studio", uiLang)}</h1>
          <div className="flex gap-1 rounded-lg border border-line p-0.5 text-sm">
            {(["mr", "en"] as const).map((l) => (
              <button
                key={l}
                onClick={() => setDraftLang(l)}
                className={`cursor-pointer rounded-md px-3 py-1 font-semibold ${draftLang === l ? "bg-navy text-white" : "text-muted"}`}
              >
                {l === "mr" ? "मराठी" : "English"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <Label>{t("topicLabel", uiLang)}</Label>
          <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={t("topicPlaceholder", uiLang)} />
        </div>
        {preview.length > 0 && (
          <div className="grid gap-2 md:grid-cols-2">
            {preview.map((p) => (
              <div key={p.gr_code} className="rise rounded-lg border border-line bg-paper px-3 py-2 text-xs">
                <div className="flex items-center justify-between">
                  <code className="font-semibold text-navy">{p.gr_code}</code>
                  <Badge tone="gold">{t("similarity", uiLang)} {(1 - p.distance).toFixed(3)}</Badge>
                </div>
                <div className="mt-1 flex items-center justify-between gap-2">
                  <span className="truncate text-muted">{p.subject?.slice(0, 90) ?? "—"}</span>
                  {p.links?.portal && (
                    <a href={p.links.portal} target="_blank" rel="noreferrer" className="shrink-0 text-navy underline">PDF</a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="grid gap-2 md:grid-cols-2">
          <Button onClick={doPrefill} disabled={!topic.trim() || busy !== null}>
            {busy === "prefill" ? <Spinner /> : "🔎"} {t("findPrecedents", uiLang)}
          </Button>
          <Button variant="gold" onClick={doAutodraft} disabled={!topic.trim() || busy !== null}>
            {busy === "auto" ? <Spinner /> : "⚡"} {t("autonomous", uiLang)}
          </Button>
        </div>
        {busy === "auto" && steps.length > 0 && (
          <div className="max-h-24 overflow-y-auto rounded-lg bg-navy/5 p-2 font-mono text-xs text-navy">
            {steps.map((s, i) => <div key={i} className="rise">▸ {s}</div>)}
          </div>
        )}
      </Card>

      {/* prefill provenance */}
      {prefill && (
        <Card className="grid gap-2 p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">{t("precedents", uiLang)}</span>
            <Badge tone="info">{t("deptInferred", uiLang)}: {prefill.department} ({prefill.dept_code})</Badge>
            {meta?.ai_used && <Badge tone="gold">🤖 {t("aiWrote", uiLang)}</Badge>}
            {meta?.ai_error && <Badge tone="warn">AI unavailable — deterministic form</Badge>}
          </div>
          {(prefill.precedents ?? []).map((p) => (
            <div key={p.gr_code} className="flex flex-wrap items-center gap-2 text-xs text-muted">
              <code className="text-navy">{p.gr_code}</code> · {p.date_iso} ·
              <Badge tone="gold">{(1 - p.distance).toFixed(3)}</Badge>
              <span className="truncate">{p.subject?.slice(0, 100)}</span>
            </div>
          ))}
          {(meta?.needs_numbers ?? []).map((q, i) => (
            <Alert key={i} tone="warn">❓ {t("needsInfo", uiLang)}: {q}</Alert>
          ))}
          {meta?.scrubbed && meta.scrubbed.length > 0 && (
            <div className="text-xs text-muted">🧹 {t("scrubbed", uiLang)}: {meta.scrubbed.slice(0, 6).join(", ")}</div>
          )}
          {meta?.scrubbed_entities && meta.scrubbed_entities.length > 0 && (
            <div className="text-xs text-muted">
              🧹 {uiLang === "mr" ? "स्रोत नसलेली नावे ____ केली" : "Unsourced names blanked"}:{" "}
              {meta.scrubbed_entities.slice(0, 4).join(", ")}
            </div>
          )}
          {meta?.wording && meta.wording.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-semibold text-muted">
                {uiLang === "mr" ? "शब्दयोजना-पडताळणी" : "Wording fidelity"}:
              </span>
              {meta.wording.map((w) => (
                <Badge
                  key={w.idx}
                  tone={w.verdict === "grounded" ? "ok" : w.verdict === "unverified" ? "warn" : "info"}
                >
                  {uiLang === "mr" ? "कलम" : "clause"} {w.idx + 1}:{" "}
                  {w.verdict === "grounded" ? `✓ GR ${w.src + 1}` : w.verdict === "unverified" ? "⚠ unverified" : "—"}
                </Badge>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* step 2: the reviewed form */}
      <Card className="grid gap-3 p-4">
        <div className="grid gap-3 md:grid-cols-2">
          <div><Label>{t("subject", uiLang)}</Label><Input value={fields.subject} onChange={set("subject")} /></div>
          <div><Label>{t("department", uiLang)}</Label><Input value={fields.department} onChange={set("department")} /></div>
          <div><Label>{t("grNumber", uiLang)}</Label><Input value={fields.gr_number} onChange={set("gr_number")} /></div>
          <div><Label>{t("date", uiLang)}</Label><Input type="date" value={fields.date} onChange={set("date")} /></div>
        </div>
        <div><Label>{t("references", uiLang)}</Label><Textarea rows={3} value={fields.references} onChange={set("references")} /></div>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" checked={useBrief} onChange={(e) => setUseBrief(e.target.checked)} />
          <span>🤖 {uiLang === "mr"
            ? "AI-assist — थोडक्यात माहितीवरून प्रस्तावना व कलमे (अंक-लेखापरीक्षित)"
            : "AI-assist — draft preamble & clauses from a brief (digit-audited)"}</span>
        </label>
        {useBrief ? (
          <>
            <div>
              <Label>{uiLang === "mr" ? "अधिकाऱ्याची थोडक्यात माहिती" : "Officer's brief"}</Label>
              <Textarea rows={4} value={brief} onChange={(e) => setBrief(e.target.value)}
                placeholder="e.g. sanction a merit scholarship of Rs. 1,500 per month for the top 10% of polytechnic students, paid via MahaDBT, from academic year 2026-27" />
            </div>
            <div className="flex items-center gap-3 text-sm">
              <Label>{uiLang === "mr" ? "कलमे" : "Clauses"}</Label>
              <input type="range" min={2} max={6} value={nClauses}
                onChange={(e) => setNClauses(Number(e.target.value))} />
              <b>{nClauses}</b>
            </div>
          </>
        ) : (
          <>
            <div><Label>{t("background", uiLang)}</Label><Textarea rows={3} value={fields.background} onChange={set("background")} /></div>
            <div><Label>{t("opClauses", uiLang)}</Label><Textarea rows={5} value={fields.clauses} onChange={set("clauses")} /></div>
          </>
        )}
        <div className="grid gap-3 md:grid-cols-3">
          <div><Label>{t("budgetHead", uiLang)}</Label><Input value={fields.budget_head} onChange={set("budget_head")} /></div>
          <div><Label>{t("signatory", uiLang)}</Label><Input value={fields.signatory} onChange={set("signatory")} /></div>
          <div><Label>{t("designation", uiLang)}</Label><Input value={fields.designation} onChange={set("designation")} /></div>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          <Button onClick={() => doGenerate(true)} disabled={busy !== null || !fields.subject}>
            {busy === "gen-check" ? <Spinner /> : "✍️"} {t("generateCheck", uiLang)}
          </Button>
          <Button variant="outline" onClick={() => doGenerate(false)} disabled={busy !== null || !fields.subject}>
            📝 {t("draftOnly", uiLang)}
          </Button>
        </div>
        {busy === "gen-check" && steps.length > 0 && (
          <div className="max-h-24 overflow-y-auto rounded-lg bg-navy/5 p-2 font-mono text-xs text-navy">
            {steps.map((s, i) => <div key={i} className="rise">▸ {s}</div>)}
          </div>
        )}
        {err && <Alert tone="bad">{err}</Alert>}
      </Card>

      {/* step 3: the generated draft */}
      {generated && (
        <Card className="grid gap-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-navy">{t("generatedDraft", uiLang)}</h2>
            {generated.audit?.ok === true && <Badge tone="ok">🔒 {t("digitAuditOk", uiLang)}</Badge>}
            {generated.audit && !generated.audit.ok && (
              <Badge tone="bad">{t("digitAuditFail", uiLang)} — invented: {generated.audit.invented.join(", ") || "–"}</Badge>
            )}
            <Badge tone={generated.score.pct === 100 ? "ok" : "warn"}>{t("compliance", uiLang)} {generated.score.pct}%</Badge>
            <Badge tone={generated.terms.n_flags ? "warn" : "ok"}>{t("termFlags", uiLang)} {generated.terms.n_flags}</Badge>
          </div>

          {autoMeta && (
            <Alert tone="gold">
              ⚡ {uiLang === "mr"
                ? `विषय → ${autoMeta.precedents?.length ?? 0} पूर्वसंदर्भ → विभाग ${autoMeta.dept_code} → AI मजकूर → scrub → deterministic render, ${autoMeta.elapsed_s}s मध्ये — एकही फील्ड हाताने संपादित नाही.`
                : `Topic → ${autoMeta.precedents?.length ?? 0} precedents → dept ${autoMeta.dept_code} → AI prose → scrub → deterministic render in ${autoMeta.elapsed_s}s — no field was human-edited.`}
              {autoMeta.deferred_clauses?.length > 0 && ` · 🕐 ${autoMeta.deferred_clauses.length} clause(s) deferred to a separate order`}
            </Alert>
          )}

          {fixApplied && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-gold-soft px-3 py-2 text-sm">
              <span>🔧 {fixApplied} — {uiLang === "mr" ? "मसुदा पुन्हा तयार झाला; खालील निकाल जुन्या मसुद्याचे आहेत." : "draft regenerated; results below are for the previous draft."}</span>
              <Button variant="gold" onClick={doRecheck} disabled={busy !== null}>🔁 {t("recheck", uiLang)}</Button>
            </div>
          )}

          {review && !review.review?.error && (
            <div className="grid gap-3">
              {conflicts.length === 0 ? (
                <Alert tone="ok">✓ {t("noConflicts", uiLang)}</Alert>
              ) : (
                conflicts.map((c, i) => (
                  <ConflictCard
                    key={i}
                    conflict={c}
                    canFix={Boolean(grForm && !fixApplied)}
                    onFix={doFix}
                    fixing={busy === "fix"}
                  />
                ))
              )}
            </div>
          )}
          {review?.review?.error && <Alert tone="warn">Conflict check unavailable: {review.review.error}</Alert>}

          {generated.short_clauses.length > 0 && (
            <Alert tone="warn">
              ⚠ {generated.short_clauses.length} clause(s) below the screening floor — lengthen them for full conflict coverage.
            </Alert>
          )}

          <ExportBar form={grForm} draft={generated.draft} review={review} />
          <Textarea rows={14} readOnly value={generated.draft} className="font-mono text-xs leading-6" />
        </Card>
      )}
    </div>
  );
}
