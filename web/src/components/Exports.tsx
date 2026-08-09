/** Export buttons + inline PDF preview (iframe over a blob URL — the browser's
 * native viewer renders the embedded Devanagari fonts; no pdf.js). */
import { useState } from "react";
import { api } from "../lib/api";
import { t } from "../lib/strings";
import { useApp } from "../store/app";
import type { FullReview, GRForm } from "../lib/types";
import { Alert, Button, Card, Spinner } from "./ui";

function download(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}

export function ExportBar({
  form,
  draft,
  review,
}: {
  form?: GRForm | null;
  draft?: string;
  review?: FullReview | null;
}) {
  const lang = useApp((s) => s.lang);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [unresolved, setUnresolved] = useState<string[] | null>(null);

  const body = form ? { form } : { draft };

  async function grab(path: string, payload: unknown, key: string, save = true) {
    setBusy(key);
    setErr(null);
    try {
      const { url, filename } = await api.blob(path, payload);
      if (save) download(url, filename);
      setUnresolved(null);
      return url;
    } catch (e: any) {
      // the वाचा existence gate: offer the DRAFT-marked override
      if (e?.detail?.error === "unresolved_references") {
        setUnresolved(e.detail.unresolved ?? []);
      } else {
        setErr(String(e?.message ?? e));
      }
      return null;
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={busy !== null || (!form && !draft)}
          onClick={async () => {
            const url = await grab("/api/export/authentic?fmt=pdf", body, "pdf", false);
            if (url) setPreview(url);
          }}
        >
          {busy === "pdf" ? <Spinner /> : "📜"} {t("authenticPdf", lang)}
        </Button>
        <Button
          variant="outline"
          disabled={busy !== null || (!form && !draft)}
          onClick={() => grab("/api/export/authentic?fmt=docx", body, "docx")}
        >
          📜 {t("authenticDocx", lang)}
        </Button>
        {review?.score && (
          <Button
            variant="outline"
            disabled={busy !== null}
            onClick={() =>
              grab(
                "/api/export/report?fmt=pdf",
                { score: review.score, terms: review.terms, refs: review.refs, review: review.review },
                "report",
              )
            }
          >
            📋 {t("reportPdf", lang)}
          </Button>
        )}
      </div>
      {err && <Alert tone="bad">{err}</Alert>}
      {unresolved && (
        <Alert tone="warn">
          <div className="font-semibold">
            ⚠ {lang === "mr"
              ? "खालील वाचा-संदर्भ संग्रहात सापडले नाहीत — अस्सल स्वरूप रोखले."
              : "These वाचा references do not resolve against the corpus — authentic export blocked."}
          </div>
          {unresolved.map((u, i) => (
            <div key={i} className="mt-1 font-mono text-xs">{u.slice(0, 100)}</div>
          ))}
          <Button
            variant="outline"
            className="mt-2"
            disabled={busy !== null}
            onClick={async () => {
              const url = await grab("/api/export/authentic?fmt=pdf&allow_unverified=true", body, "pdf", false);
              if (url) setPreview(url);
            }}
          >
            {lang === "mr" ? "तरीही निर्यात करा — मसुदा-शिक्का लागेल" : "Export anyway — with DRAFT marker"}
          </Button>
        </Alert>
      )}
      {preview && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="text-sm font-semibold">{t("preview", lang)} — US Letter · अस्सल स्वरूप</span>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => download(preview, "clauseguard_gr.pdf")}>⬇ PDF</Button>
              <Button variant="ghost" onClick={() => setPreview(null)}>{t("close", lang)}</Button>
            </div>
          </div>
          <iframe title="GR preview" src={preview} className="h-[75vh] w-full bg-white" />
        </Card>
      )}
    </div>
  );
}
