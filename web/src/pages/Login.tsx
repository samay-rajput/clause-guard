import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { t } from "../lib/strings";
import { useApp } from "../store/app";
import { Alert, Button, Card, Input, Label, LangSwitch } from "../components/ui";

export default function Login() {
  const { lang, setUser, setLang } = useApp();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const user = await api.login(username, password);
      setUser(user);
      nav("/");
    } catch (e: any) {
      setErr(e?.status === 429 ? "Too many attempts — wait a minute." : "Wrong username or password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-gradient-to-b from-paper to-gold-soft/40 p-4">
      <Card className="rise w-full max-w-sm p-8">
        <div className="mb-6 text-center">
          <div className="text-4xl">📜</div>
          <h1 className="mt-2 text-2xl font-bold text-navy">{t("appName", lang)}</h1>
          <p className="mt-1 text-sm text-muted">{t("tagline", lang)}</p>
        </div>
        <form onSubmit={submit} className="grid gap-4">
          <div>
            <Label>{t("username", lang)}</Label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
          </div>
          <div>
            <Label>{t("password", lang)}</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </div>
          {err && <Alert tone="bad">{err}</Alert>}
          <Button type="submit" disabled={busy || !username || !password}>
            {t("login", lang)}
          </Button>
        </form>
        <div className="mt-5">
          <LangSwitch lang={lang} onChange={setLang} size="lg" />
        </div>
      </Card>
    </div>
  );
}
