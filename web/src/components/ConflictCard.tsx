/** One verified conflict — values as chips, both clauses side by side, the
 * code-built reason, LLM explanation, and the one-click deterministic fix. */
import { useState } from "react";
import { useApp } from "../store/app";
import { t } from "../lib/strings";
import type { Conflict } from "../lib/types";
import { Badge, Button, Card, CompareChips, cx } from "./ui";

export function ConflictCard({
  conflict,
  canFix,
  onFix,
  fixing,
}: {
  conflict: Conflict;
  canFix?: boolean;
  onFix?: (c: Conflict) => void;
  fixing?: boolean;
}) {
  const lang = useApp((s) => s.lang);
  const [showExplain, setShowExplain] = useState(false);
  const m = conflict.meta ?? {};
  const sim = m.distance != null ? (1 - m.distance).toFixed(3) : null;

  return (
    <Card className="rise overflow-hidden border-l-4 border-l-maroon p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-bold text-maroon">
          ⚠ {t("conflicts", lang)} — GR <span className="font-mono text-sm">{m.gr_code ?? "?"}</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          {sim && <Badge tone="info">{t("similarity", lang)} {sim}</Badge>}
          {conflict.links?.portal && (
            <a className="text-navy underline" href={conflict.links.portal} target="_blank" rel="noreferrer">
              source PDF
            </a>
          )}
          {conflict.links?.archive && (
            <a className="text-navy underline" href={conflict.links.archive} target="_blank" rel="noreferrer">
              archived
            </a>
          )}
        </div>
      </div>

      {conflict.value1 && conflict.value2 && (
        <CompareChips left={conflict.value1} right={conflict.value2} note={conflict.benefit} />
      )}

      <div className="mt-2 grid gap-3 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-muted">{t("draftClause", lang)}</div>
          <div className="rounded-lg bg-warn-soft p-3 text-sm leading-7">{conflict.draft}</div>
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-muted">
            {t("existingGR", lang)} — {m.department?.split("(")[0] ?? "?"} · {m.date ?? "?"}
          </div>
          <div className="rounded-lg bg-navy/5 p-3 text-sm leading-7">{conflict.candidate}</div>
        </div>
      </div>

      <p className="mt-3 text-sm">
        <span className="font-semibold">{t("whyConflict", lang)}:</span> {conflict.reason}
      </p>

      {conflict.value1 && conflict.value2 && (
        <p className="mt-1 text-sm text-muted">
          <span className="font-semibold text-ink">{t("suggestedFix", lang)}:</span>{" "}
          {lang === "mr"
            ? `मसुदा ${conflict.value2} प्रमाणे जुळवा, किंवा ${conflict.value1} ठेवून जुना GR स्पष्टपणे अधिक्रमित करणारे कलम जोडा.`
            : `Align the draft to ${conflict.value2}, or keep ${conflict.value1} and add an explicit clause superseding the old GR.`}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {canFix && conflict.value1 && conflict.value2 && (
          <Button variant="gold" disabled={fixing} onClick={() => onFix?.(conflict)}>
            🔧 {t("applyFix", lang)} — {conflict.value2}
          </Button>
        )}
        <Button variant="ghost" onClick={() => setShowExplain((v) => !v)}>
          {showExplain ? "▲" : "▼"} {t("explanation", lang)}
        </Button>
      </div>
      <div
        className={cx(
          "grid transition-all duration-200",
          showExplain ? "mt-2 grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden">
          <div className="rounded-lg border border-line bg-paper p-3 text-sm leading-7">
            {conflict.explanation}
          </div>
        </div>
      </div>
    </Card>
  );
}
