/** FR-15 audit trail — per-user records, human-edit diffs, JSONL/CSV export. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { t } from "../lib/strings";
import { useApp } from "../store/app";
import { Alert, Badge, Button, Metric } from "../components/ui";

function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-lg bg-navy/95 p-3 text-xs leading-5 text-white/90">
      {diff.split("\n").map((line, i) => (
        <div
          key={i}
          className={
            line.startsWith("+") && !line.startsWith("+++") ? "text-emerald-300"
            : line.startsWith("-") && !line.startsWith("---") ? "text-rose-300"
            : line.startsWith("@@") ? "text-sky-300"
            : undefined
          }
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

export default function Audit() {
  const { lang, user } = useApp();
  const [forUser, setForUser] = useState<string>("");
  const suffix = forUser ? `?for_user=${encodeURIComponent(forUser)}` : "";
  const q = useQuery({
    queryKey: ["audit", forUser],
    queryFn: () => api.get(`/api/audit/runs${suffix}`),
  });

  const data = q.data;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-bold text-navy">🗂️ {t("auditTrail", lang)}</h1>
        <div className="flex items-center gap-2">
          {user?.role === "reviewer" && (
            <select
              className="rounded-lg border border-line bg-white px-2 py-1.5 text-sm"
              value={forUser}
              onChange={(e) => setForUser(e.target.value)}
            >
              <option value="">my trail</option>
              <option value="drafter">drafter</option>
              <option value="reviewer">reviewer</option>
            </select>
          )}
          <ExportButtons forUser={forUser} />
        </div>
      </div>

      {q.isLoading && <Alert tone="info">{t("loading", lang)}</Alert>}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:w-96">
            <Metric label={t("recordedRuns", lang)} value={data.total} />
            <Metric label={t("withEdits", lang)} value={data.with_edits} />
          </div>
          <div className="grid gap-2">
            {data.runs.map((rec: any, i: number) => {
              const sug = rec.ai_suggestions ?? {};
              const det = rec.deterministic ?? {};
              const nSug = Object.values(sug).reduce((n: number, v: any) => n + (v?.length ?? 0), 0);
              return (
                <details key={i} className="rise rounded-xl border border-line bg-card shadow-card">
                  <summary className="cursor-pointer px-4 py-3 text-sm">
                    <span className="font-mono text-xs text-muted">{rec.ts}</span>{" "}
                    <Badge tone="info">{rec.source ?? "review"}</Badge>{" "}
                    <b>{det.compliance_pct != null ? `${det.compliance_pct}%` : "—"}</b> compliance ·{" "}
                    {nSug} suggestion(s) · <span className="font-mono text-xs">{rec.draft_sha256?.slice(0, 10)}</span>
                  </summary>
                  <div className="grid gap-2 border-t border-line px-4 py-3 text-sm">
                    {det.funnel && (
                      <div className="text-xs text-muted">
                        funnel: {det.funnel.n_clauses} clauses → {det.funnel.n_pairs} pairs →{" "}
                        {det.funnel.n_muril_flagged ?? "–"} MuRIL flags → {det.funnel.n_conflicts} verified
                      </div>
                    )}
                    {(sug.conflicts ?? []).map((c: any, j: number) => (
                      <div key={j} className="rounded-lg bg-bad-soft px-3 py-2 text-xs">
                        🔴 <b>vs {c.gr_code}</b> — {c.reason}
                        {c.suggested_fix && <div className="mt-1 text-muted">fix: {c.suggested_fix}</div>}
                      </div>
                    ))}
                    {(sug.citation_warnings ?? []).map((w: any, j: number) => (
                      <div key={j} className="rounded-lg bg-warn-soft px-3 py-2 text-xs">
                        {w.kind === "superseded"
                          ? <>⚠ cites <b>{w.cited}</b>, superseded by <code>{w.superseded_by}</code></>
                          : <>🕐 cited GR dated <b>{w.cited_date}</b> has {w.n_newer} newer same-subject GR(s)</>}
                      </div>
                    ))}
                    {det.failed_checks?.length > 0 && (
                      <div className="text-xs text-muted">failed checks: {det.failed_checks.join(", ")}</div>
                    )}
                    {rec.human_edit ? (
                      <div>
                        <div className="mb-1 text-xs font-semibold">
                          {t("humanEdits", lang)} (+{rec.human_edit.lines_added} / −{rec.human_edit.lines_removed})
                        </div>
                        <DiffView diff={rec.human_edit.diff || "(no line changes)"} />
                      </div>
                    ) : (
                      <div className="text-xs text-muted">first recorded version — nothing to diff against</div>
                    )}
                  </div>
                </details>
              );
            })}
          </div>
        </>
      )}
      <p className="text-xs text-muted">Local file only — the trail never leaves this machine (NFR-2).</p>
    </div>
  );
}

function ExportButtons({ forUser }: { forUser: string }) {
  const [busy, setBusy] = useState(false);
  async function grab(fmt: "jsonl" | "csv") {
    setBusy(true);
    try {
      const qs = `fmt=${fmt}${forUser ? `&for_user=${encodeURIComponent(forUser)}` : ""}`;
      const { url, filename } = await api.blobGet(`/api/audit/export?${qs}`);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex gap-2">
      <Button variant="outline" disabled={busy} onClick={() => grab("jsonl")}>⬇ JSONL</Button>
      <Button variant="outline" disabled={busy} onClick={() => grab("csv")}>⬇ CSV</Button>
    </div>
  );
}
