/** Small component kit in the shadcn idiom — hand-rolled, zero runtime deps. */
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

type BtnVariant = "primary" | "outline" | "ghost" | "gold" | "danger";
const btnStyles: Record<BtnVariant, string> = {
  primary: "bg-navy text-white hover:bg-navy-soft shadow-sm",
  gold: "bg-gold text-white hover:brightness-110 shadow-sm",
  outline: "border border-line bg-card hover:border-navy/40 text-ink",
  ghost: "text-navy hover:bg-navy/5",
  danger: "bg-maroon text-white hover:brightness-110",
};

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold",
        "transition-all duration-150 disabled:opacity-45 disabled:cursor-not-allowed cursor-pointer",
        btnStyles[variant],
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("rounded-xl border border-line bg-card shadow-card", className)}>
      {children}
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm",
        "focus:outline-none focus:ring-2 focus:ring-navy/25 focus:border-navy/50",
        props.className,
      )}
    />
  );
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm leading-7",
        "focus:outline-none focus:ring-2 focus:ring-navy/25 focus:border-navy/50",
        props.className,
      )}
    />
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <label className="mb-1 block text-xs font-semibold text-muted">{children}</label>;
}

type Tone = "ok" | "warn" | "bad" | "info" | "gold";
const toneStyles: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-navy/8 text-navy",
  gold: "bg-gold-soft text-gold",
};

export function Badge({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold", toneStyles[tone])}>
      {children}
    </span>
  );
}

export function Metric({
  label,
  value,
  delta,
  tone = "info",
}: {
  label: string;
  value: ReactNode;
  delta?: string | null;
  tone?: Tone;
}) {
  return (
    <Card className="rise px-4 py-3">
      <div className="text-xs font-semibold text-muted">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <div className="text-2xl font-bold text-ink">{value}</div>
        {delta && <Badge tone={tone}>{delta}</Badge>}
      </div>
    </Card>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-navy/30 border-t-navy" />
      {label}
    </span>
  );
}

export function Tabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: Array<{ id: string; label: ReactNode; badge?: number }>;
  active: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onSelect(tab.id)}
          className={cx(
            "cursor-pointer rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors",
            active === tab.id
              ? "border border-line border-b-card bg-card text-navy -mb-px"
              : "text-muted hover:text-ink",
          )}
        >
          {tab.label}
          {tab.badge != null && tab.badge > 0 && (
            <span className="ml-2 rounded-full bg-maroon px-1.5 text-xs font-bold text-white">{tab.badge}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Alert({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <div className={cx("rise rounded-lg px-4 py-3 text-sm", toneStyles[tone])}>{children}</div>
  );
}

/** Prominent language switcher — two complete interfaces, one click apart. */
export function LangSwitch({
  lang,
  onChange,
  size = "md",
}: {
  lang: "mr" | "en";
  onChange: (l: "mr" | "en") => void;
  size?: "md" | "lg";
}) {
  return (
    <div
      className={cx(
        "inline-flex rounded-full border border-line bg-paper p-0.5",
        size === "lg" && "w-full justify-center",
      )}
      title="भाषा · Language"
    >
      {([["mr", "मराठी"], ["en", "English"]] as const).map(([id, label]) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          className={cx(
            "cursor-pointer rounded-full font-semibold transition-all",
            size === "lg" ? "flex-1 px-4 py-1.5 text-sm" : "px-3 py-1 text-xs",
            lang === id ? "bg-navy text-white shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** red → green comparison chips (conflict values, terminology corrections) */
export function CompareChips({ left, right, note }: { left: string; right: string; note?: string }) {
  return (
    <div className="my-2 flex flex-wrap items-center gap-2">
      <span className="rounded-lg bg-bad-soft px-3 py-1.5 text-sm font-semibold text-bad line-through decoration-bad/40">
        {left}
      </span>
      <span className="text-muted">→</span>
      <span className="rounded-lg bg-ok-soft px-3 py-1.5 text-sm font-semibold text-ok">{right}</span>
      {note && <span className="text-xs text-muted">{note}</span>}
    </div>
  );
}
