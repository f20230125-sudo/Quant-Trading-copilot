"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Eye, EyeOff, KeyRound, LoaderCircle, Sparkles, Unplug, X } from "lucide-react";
import { ApiError, connectClaude, disconnectClaude } from "@/lib/api";

export function ConnectClaudeDialog({
  open,
  onClose,
  claudeReady,
  model,
  onChange,
}: {
  open: boolean;
  onClose: () => void;
  claudeReady: boolean;
  model: string | undefined;
  onChange: (connected: boolean) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [key, setKey] = useState("");
  const [show, setShow] = useState(false);
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await connectClaude(key.trim(), remember);
      setKey("");
      onChange(true);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the backend.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await disconnectClaude();
      onChange(false);
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      aria-labelledby="connect-title"
      className="m-auto w-[min(440px,calc(100vw-2rem))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-2xl"
    >
      <div className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent-soft text-accent">
              {claudeReady ? <Sparkles size={18} aria-hidden /> : <KeyRound size={18} aria-hidden />}
            </span>
            <div>
              <h2 id="connect-title" className="text-base font-semibold">
                {claudeReady ? "Claude is connected" : "Connect Claude"}
              </h2>
              <p className="text-xs text-muted">Optional. The local analyst works without it.</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-2 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
          >
            <X size={16} aria-hidden />
          </button>
        </div>

        {claudeReady ? (
          <div className="mt-4 space-y-4">
            <p className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-sm text-ink-2">
              <Check size={15} className="text-good-text" aria-hidden />
              Using <span className="font-medium text-ink">{model}</span> for open-ended questions and follow-ups.
            </p>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={disconnect}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm font-medium text-ink-2 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
              >
                <Unplug size={14} aria-hidden /> Disconnect for this session
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={connect} className="mt-4 space-y-4">
            <p className="text-sm leading-relaxed text-ink-2">
              The local analyst answers the questions this app is built for. Claude adds open-ended reasoning, richer explanations
              and free-form follow-ups. Your key is sent only to your own backend and never back to the browser.
            </p>
            <div>
              <label htmlFor="api-key" className="mb-1.5 block text-xs font-medium text-ink-2">
                Anthropic API key
              </label>
              <div className="flex items-center rounded-lg border border-line bg-surface-2 focus-within:border-accent">
                <input
                  id="api-key"
                  type={show ? "text" : "password"}
                  autoComplete="off"
                  spellCheck={false}
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder="sk-ant-…"
                  className="min-w-0 flex-1 bg-transparent px-3 py-2 font-mono text-sm text-ink placeholder:text-muted focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? "Hide key" : "Show key"}
                  className="grid h-9 w-9 place-items-center text-muted hover:text-ink"
                >
                  {show ? <EyeOff size={15} aria-hidden /> : <Eye size={15} aria-hidden />}
                </button>
              </div>
              <p className="mt-1.5 text-xs text-muted">
                Create one at{" "}
                <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                  console.anthropic.com
                </a>
                .
              </p>
            </div>
            <label className="flex cursor-pointer items-start gap-2 text-sm text-ink-2">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="mt-0.5 accent-[var(--accent)]" />
              <span>
                Remember on this computer
                <span className="block text-xs text-muted">Saves it to backend/.env. Otherwise it lasts until the backend restarts.</span>
              </span>
            </label>
            {error && (
              <p role="alert" className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-critical-text">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg px-3 py-2 text-sm font-medium text-ink-2 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy || key.trim().length < 20}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-accent-ink hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy && <LoaderCircle size={14} className="animate-spin" aria-hidden />}
                {busy ? "Verifying…" : "Connect"}
              </button>
            </div>
          </form>
        )}
      </div>
    </dialog>
  );
}
