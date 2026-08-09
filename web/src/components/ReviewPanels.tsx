/** References / Scorecard / Glossary panels of a completed review. */
import { useApp } from "../store/app";
import { t } from "../lib/strings";
import type { Refs, Score, Terms } from "../lib/types";
import { Alert, Badge, Card, CompareChips, Metric } from "./ui";

export function RefsPanel({ refs }: { refs?: Refs }) {
  const lang = useApp((s) => s.lang);
  if (!refs) return <Alert tone="info">{t("loading", lang)}</Alert>;
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label={lang === "mr" ? "आढळलेले संदर्भ" : "Citations found"} value={refs.n_citations} />
        <Metric label={lang === "mr" ? "संग्रहाशी जोडलेले" : "Linked to corpus"} value={refs.linked.length} />
        <Metric
          label={lang === "mr" ? "कालबाह्यता-इशारे" : "Currency warnings"}
          value={refs.newer_related.length}
          tone={refs.newer_related.length ? "warn" : "ok"}
        />
        <Metric
          label={lang === "mr" ? "स्पष्ट अधिक्रमणे" : "Explicit supersessions"}
          value={refs.stale.length}
          tone={refs.stale.length ? "bad" : "ok"}
        />
      </div>
      {refs.stale.map((s, i) => (
        <Alert key={i} tone="bad">
          ⚠ cites <b>{s.cited}</b> — superseded by <code>{s.superseded_by}</code>{" "}
          {s.successor_subject && <span className="text-muted">· {s.successor_subject}</span>}
        </Alert>
      ))}
      {refs.newer_related.map((a, i) => (
        <Card key={i} className="p-3 text-sm">
          <div className="font-semibold">
            🕐 {lang === "mr"
              ? `${a.cited_date} दिनांकाचा GR उद्धृत — त्याच विषयावर ${a.newer.length} नवीन GR अस्तित्वात`
              : `Cites a GR dated ${a.cited_date}, but ${a.newer.length} newer same-subject GR(s) exist`}
          </div>
          {a.newer.map((n, j) => (
            <div key={j} className="mt-1 text-xs text-muted">
              ↳ <code>{n.gr_code}</code> · {n.date} — {n.subject}
            </div>
          ))}
        </Card>
      ))}
      {refs.linked.length > 0 && (
        <div className="grid gap-2">
          <div className="text-sm font-semibold">{lang === "mr" ? "जोडलेले संदर्भ" : "Linked references"}</div>
          {refs.linked.map((l, i) => (
            <Card key={i} className="grid gap-1 p-3 text-sm md:grid-cols-[2fr_3fr]">
              <div>
                <code className="text-xs">{l.cited.slice(0, 70)}</code>
                <div className="text-xs text-muted">via {l.via}</div>
              </div>
              <div>
                <b>{l.match.department?.split("(")[0]}</b> · {l.match.date}
                <div className="text-xs text-muted">{(l.match.subject ?? "").slice(0, 110)}</div>
                {l.links?.portal && (
                  <a className="text-xs text-navy underline" href={l.links.portal} target="_blank" rel="noreferrer">
                    source PDF
                  </a>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      {refs.unknown.length > 0 && (
        <details className="text-sm text-muted">
          <summary className="cursor-pointer">Unmatched citations ({refs.unknown.length})</summary>
          {refs.unknown.map((u, i) => (
            <div key={i} className="mt-1 font-mono text-xs">{u.slice(0, 90)}</div>
          ))}
        </details>
      )}
    </div>
  );
}

export function ScorePanel({ score, prevPct }: { score?: Score; prevPct?: number | null }) {
  const lang = useApp((s) => s.lang);
  if (!score) return <Alert tone="info">{t("loading", lang)}</Alert>;
  const fails = score.checks.filter((c) => !c.passed);
  const passes = score.checks.filter((c) => c.passed);
  const delta = prevPct != null && prevPct !== score.pct ? `${score.pct - prevPct > 0 ? "+" : ""}${score.pct - prevPct}%` : null;
  return (
    <div className="grid gap-3">
      <div className="flex items-end gap-4">
        <div className="text-5xl font-bold text-navy">{score.pct}%</div>
        {delta && <Badge tone={score.pct >= (prevPct ?? 0) ? "ok" : "bad"}>{delta} vs previous</Badge>}
        <div className="text-sm text-muted">
          {score.score}/{score.max_score} · {score.checks.length} Manual-of-Office-Procedure checks
        </div>
      </div>
      <div className="h-3 overflow-hidden rounded-full bg-paper">
        <div className="barfill h-full rounded-full bg-gradient-to-r from-navy to-gold" style={{ width: `${score.pct}%` }} />
      </div>
      {fails.length > 0 ? (
        <div className="grid gap-1.5">
          <div className="text-sm font-semibold">{lang === "mr" ? "दुरुस्त करा:" : "Fix these:"}</div>
          {fails.map((c, i) => (
            <div key={i} className="rise rounded-lg bg-bad-soft px-3 py-2 text-sm">
              ✗ {c.desc} <span className="text-xs text-muted">(weight {c.weight})</span>
            </div>
          ))}
        </div>
      ) : (
        <Alert tone="ok">{lang === "mr" ? "प्रत्येक साचा-तपासणी उत्तीर्ण." : "Every template check passes."}</Alert>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted">✓ Passing checks ({passes.length})</summary>
        <div className="mt-2 grid gap-1">
          {passes.map((c, i) => (
            <div key={i} className="text-sm text-ok">✓ {c.desc} <span className="text-xs text-muted">({c.weight})</span></div>
          ))}
        </div>
      </details>
    </div>
  );
}

export function TermsPanel({ terms }: { terms?: Terms }) {
  const lang = useApp((s) => s.lang);
  if (!terms) return <Alert tone="info">{t("loading", lang)}</Alert>;
  return (
    <div className="grid gap-3">
      {terms.n_flags === 0 ? (
        <Alert tone="ok">
          {lang === "mr"
            ? "परिभाषेत एकही विसंगती नाही — प्रत्येक संज्ञा मान्य स्वरूपात."
            : "No terminology mismatches — every glossary term uses its approved form."}
        </Alert>
      ) : (
        terms.flags.map((f, i) => (
          <Card key={i} className="p-3">
            <CompareChips
              left={f.found}
              right={terms.primary_lang === "mr" ? f.approved_mr : f.approved_en}
              note={f.kind === "variant" ? "non-approved variant" : "wrong-language term"}
            />
            <div className="text-xs text-muted">…{f.context}…</div>
            {f.note && <div className="mt-1 text-xs text-muted">ℹ {f.note}</div>}
          </Card>
        ))
      )}
    </div>
  );
}
