/** Chat with the draft: instructions become form OPERATIONS server-side,
 * applied under the digit/entity rails and re-rendered deterministically. */
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../store/app";
import { Badge, Button, Card, Input, Spinner, cx } from "./ui";

interface Msg {
  who: "user" | "bot";
  text: string;
  changes?: string[];
  scrubbed?: string[];
  blanks?: string[];
  error?: boolean;
}

const SUGGESTIONS: Record<string, string[]> = {
  mr: ["पहिल्या कलमातील रक्कम ____ लाख करा", "उपयोगिता प्रमाणपत्राबाबत कलम जोडा",
       "जिल्हानिहाय वाटपाचा तक्ता जोडा", "विषय अधिक औपचारिक करा"],
  en: ["Change the amount in clause 1 to ____", "Add a clause on utilization certificates",
       "Add a district-wise allocation table", "Make the subject more formal"],
};

export function ChatDock({
  buildForm,
  onApplied,
  disabled,
}: {
  buildForm: () => any;
  onApplied: (out: any) => void;
  disabled?: boolean;
}) {
  const lang = useApp((s) => s.lang);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [msgs, busy]);

  async function send(message: string) {
    if (!message.trim() || busy || disabled) return;
    setMsgs((m) => [...m, { who: "user", text: message }]);
    setText("");
    setBusy(true);
    try {
      const out = await api.post("/api/generate/chat-edit", {
        form: buildForm(), message,
      });
      setMsgs((m) => [...m, {
        who: "bot",
        text: out.reply || (lang === "mr" ? "बदल लागू केले." : "Changes applied."),
        changes: out.changes,
        scrubbed: [...(out.scrubbed ?? []), ...(out.scrubbed_entities ?? [])],
        blanks: out.blanks,
      }]);
      onApplied(out);
    } catch (e: any) {
      setMsgs((m) => [...m, {
        who: "bot", error: true,
        text: (lang === "mr" ? "बदल लागू करता आले नाहीत: " : "Could not apply: ")
          + String(e?.message ?? e).slice(0, 160),
      }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex max-h-[420px] flex-col">
      <div className="border-b border-line px-3 py-2 text-sm font-semibold">
        💬 {lang === "mr" ? "मसुद्याशी संवाद — बोलून GR बदला" : "Talk to the draft — edit the GR by chat"}
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {msgs.length === 0 && (
          <div className="grid gap-1.5">
            <div className="text-xs text-muted">
              {lang === "mr"
                ? "सूचना लिहा — प्रत्येक बदल फॉर्ममधून, अंक-लेखापरीक्षणासह लागू होतो. चॅट कधीही थेट मसुदा लिहित नाही."
                : "Type an instruction — every change flows through the form and the digit audit. The chat never writes the draft directly."}
            </div>
            {SUGGESTIONS[lang].map((s, i) => (
              <button key={i} onClick={() => setText(s)}
                className="cursor-pointer rounded-lg border border-line bg-paper px-2.5 py-1 text-left text-xs text-muted hover:border-navy/40 hover:text-ink">
                {s}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={cx("rise flex", m.who === "user" ? "justify-end" : "justify-start")}>
            <div className={cx(
              "max-w-[85%] rounded-xl px-3 py-1.5 text-sm leading-6",
              m.who === "user" ? "bg-navy text-white"
                : m.error ? "bg-bad-soft text-bad" : "bg-paper text-ink",
            )}>
              {m.text}
              {m.changes && m.changes.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {m.changes.map((c, j) => <Badge key={j} tone="ok">✓ {c}</Badge>)}
                </div>
              )}
              {m.scrubbed && m.scrubbed.length > 0 && (
                <div className="mt-1 text-xs opacity-80">
                  🧹 {lang === "mr" ? "स्रोत नसलेले ____ केले: " : "Unsourced blanked: "}
                  {m.scrubbed.slice(0, 4).join(", ")}
                </div>
              )}
              {m.blanks && m.blanks.length > 0 && (
                <div className="mt-1 text-xs opacity-80">
                  ❓ {lang === "mr" ? "भरावयाचे: " : "To fill: "}{m.blanks.join(", ")}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <Spinner label={lang === "mr" ? "बदल लागू होत आहेत…" : "Applying…"} />}
        <div ref={endRef} />
      </div>
      <form
        className="flex gap-2 border-t border-line p-2"
        onSubmit={(e) => { e.preventDefault(); send(text); }}
      >
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={disabled || busy}
          placeholder={lang === "mr" ? "उदा. दुसऱ्या कलमातील रक्कम ५ लाख करा" : "e.g. change clause 2's amount to 5 lakh"}
        />
        <Button type="submit" disabled={disabled || busy || !text.trim()}>➤</Button>
      </form>
    </Card>
  );
}
