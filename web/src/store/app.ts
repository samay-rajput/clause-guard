import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "../lib/api";
import type { Lang } from "../lib/strings";

interface AppState {
  user: User | null;
  lang: Lang;
  sessionChecked: boolean;
  setUser: (u: User | null) => void;
  setLang: (l: Lang) => void;
  setSessionChecked: () => void;
}

export const useApp = create<AppState>()(
  persist(
    (set) => ({
      user: null,
      lang: "mr",
      sessionChecked: false,
      setUser: (user) => set({ user }),
      setLang: (lang) => set({ lang }),
      setSessionChecked: () => set({ sessionChecked: true }),
    }),
    {
      name: "clauseguard-ui-v2",   // v2: three-state language (both is default)
      partialize: (s) => ({ lang: s.lang }), // only the language survives reloads
    },
  ),
);
