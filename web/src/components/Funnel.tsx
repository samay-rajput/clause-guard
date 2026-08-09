/** The detection funnel: clauses → pairs → MuRIL flags → verified conflicts.
 * Bars animate as the numbers arrive — driven by real pipeline progress. */
import { useApp } from "../store/app";
import { t } from "../lib/strings";
import type { ReviewResult } from "../lib/types";
import { Card } from "./ui";

export function Funnel({ review }: { review: ReviewResult }) {
  const lang = useApp((s) => s.lang);
  const stages = [
    { label: t("draftClauses", lang), value: review.n_clauses ?? 0, color: "bg-navy/70" },
    { label: t("candidatePairs", lang), value: review.n_pairs ?? 0, color: "bg-navy/50" },
    {
      label: t("murilFlags", lang),
      value: review.n_muril_flagged ?? 0,
      color: "bg-gold/70",
      note: review.n_muril_flagged == null ? "off" : undefined,
    },
    {
      label: t("verifiedConflicts", lang),
      value: review.conflicts?.length ?? 0,
      color: (review.conflicts?.length ?? 0) > 0 ? "bg-maroon" : "bg-ok",
    },
  ];
  const max = Math.max(1, ...stages.map((s) => s.value));
  return (
    <Card className="p-4">
      <div className="grid gap-3">
        {stages.map((s, i) => (
          <div key={i} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-3">
            <div className="text-xs font-semibold text-muted">{s.label}</div>
            <div className="h-5 overflow-hidden rounded bg-paper">
              <div
                className={`barfill h-full rounded ${s.color}`}
                style={{ width: `${Math.max(2, (s.value / max) * 100)}%`, animationDelay: `${i * 0.12}s` }}
              />
            </div>
            <div className="text-right text-sm font-bold">{s.note ?? s.value}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}
