import { useState } from "react";
import { api } from "../lib/api";
import SpiderMark from "../components/SpiderMark";
import type { TokenResponse } from "../lib/types";

/* ===========================================================================
   AuthView - one workspace, one person.

   Nothing is filled in for you: no shared account, no preset password. The
   copy sticks to what the tool actually does, so it stays true once this is
   published.
   ========================================================================= */

interface Props {
  onSuccess: (payload: TokenResponse) => void;
  onBack: () => void;
}

const POINTS: { head: string; body: string }[] = [
  {
    head: "It reads line by line",
    body: "The spider stands on the line it is examining, using the position that line held in the original file.",
  },
  {
    head: "Every result carries a quotation",
    body: "A finding is kept only while its quotation can still be located in the passage it cites.",
  },
  {
    head: "Six readings of one document",
    body: "Subject, figures, vocabulary, language, reasoning and revisions - then drawn as a web of connections.",
  },
  {
    head: "You can ask it back",
    body: "Questions are answered from the document itself and returned with the passages they came from.",
  },
];

export default function AuthView({ onSuccess, onBack }: Props) {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload =
        mode === "up"
          ? await api.register({ email, full_name: name.trim() || email.split("@")[0], password })
          : await api.login(email, password);
      onSuccess(payload);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-view">
      <button className="btn ghost sm auth-back" type="button" onClick={onBack}>
        Back to the page
      </button>

      <div className="auth-copy">
        <p className="lp-eyebrow">Your workspace</p>
        <h1>
          A spider reads your documents and <em>quotes what it finds</em>
        </h1>
        <p className="lede">
          Upload a PDF, a Word file, text, Markdown, HTML or a spreadsheet. The document is parsed into passages that
          keep their real positions, read from first line to last, and reported back with the wording of the page.
        </p>
        <ul className="auth-points">
          {POINTS.map((point, index) => (
            <li key={point.head} style={{ animationDelay: `${120 + index * 70}ms` }}>
              <span className="k">{index + 1}</span>
              <p>
                <strong>{point.head}. </strong>
                {point.body}
              </p>
            </li>
          ))}
        </ul>
      </div>

      <div className="panel auth-card">
        <div className="panel-head">
          <h3>{mode === "up" ? "Create a workspace" : "Sign in"}</h3>
          <span className="grow" />
          <span className="mark" aria-hidden="true">
            <SpiderMark size={22} />
          </span>
        </div>
        <form onSubmit={submit}>
          <div className="auth-fields">
            <div>
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                className="input"
                type="email"
                value={email}
                placeholder="you@example.com"
                autoComplete="username"
                autoFocus
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            {mode === "up" && (
              <div>
                <label className="label" htmlFor="name">
                  Name shown on your work
                </label>
                <input
                  id="name"
                  className="input"
                  value={name}
                  placeholder="Mariam Xasan Jimcaale"
                  autoComplete="name"
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            )}
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className="input"
                type="password"
                value={password}
                placeholder={mode === "up" ? "At least eight characters" : "Your password"}
                autoComplete={mode === "up" ? "new-password" : "current-password"}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={mode === "up" ? 8 : 1}
              />
            </div>
            {error && <p className="error-text">{error}</p>}
            <button className="btn primary block" type="submit" disabled={busy}>
              {busy ? "One moment" : mode === "up" ? "Create workspace" : "Enter workspace"}
            </button>
            <p className="auth-switch">
              {mode === "up" ? (
                <>
                  Already have a workspace?{" "}
                  <button type="button" onClick={() => { setMode("in"); setError(null); }}>
                    Sign in
                  </button>
                </>
              ) : (
                <>
                  First time here?{" "}
                  <button type="button" onClick={() => { setMode("up"); setError(null); }}>
                    Create one
                  </button>
                </>
              )}
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
