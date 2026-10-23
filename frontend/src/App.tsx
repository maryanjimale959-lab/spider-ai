import { useCallback, useEffect, useState } from "react";
import SpiderMark from "./components/SpiderMark";
import { api, onSessionChange, restoreToken, setToken } from "./lib/api";
import { useTheme } from "./lib/theme";
import AuthView from "./views/AuthView";
import LandingView from "./views/LandingView";
import InvestigationWorkspace from "./views/InvestigationWorkspace";
import type { TokenResponse, User } from "./lib/types";

/* ===========================================================================
   App shell - one account, one workspace. No roles, no classrooms.
   ========================================================================= */

function useSession() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    if (!restoreToken()) {
      setUser(null);
      setChecking(false);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return onSessionChange(() => void refresh());
  }, [refresh]);

  return { user, checking, refresh };
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

function Topbar({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="mark">
          <SpiderMark size={26} />
        </span>
        <span>
          SPIDER <b>AI</b>
        </span>
      </div>
      <span className="brand-sub">document investigation</span>
      <span className="topbar-spacer" />
      <span className="who" title={user.email}>
        <span className="avatar">{initials(user.full_name)}</span>
        <span className="name">{user.full_name}</span>
      </span>
      <button className="link-quiet" onClick={onSignOut}>
        Sign out
      </button>
    </header>
  );
}

export default function App() {
  const { user, checking } = useSession();
  const [theme, setTheme] = useTheme();
  const [entering, setEntering] = useState(false);

  if (checking) {
    return (
      <div className="app-shell">
        <div className="boot">
          <SpiderMark size={42} />
          <p className="dim">Opening your workspace</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="app-shell">
        {entering ? (
          <AuthView
            onSuccess={(payload: TokenResponse) => setToken(payload.access_token)}
            onBack={() => setEntering(false)}
          />
        ) : (
          <LandingView onEnter={() => setEntering(true)} />
        )}
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Topbar
        user={user}
        onSignOut={() => {
          setEntering(false);
          setToken(null);
          window.location.href = "/";
        }}
      />
      <InvestigationWorkspace theme={theme} onTheme={setTheme} />
    </div>
  );
}
