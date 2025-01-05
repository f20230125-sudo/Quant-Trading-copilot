"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Cpu, Plug, Sparkles } from "lucide-react";
import { ChatPanel, type ChatHandle } from "./ChatPanel";
import { ConnectClaudeDialog } from "./ConnectClaudeDialog";
import { MarketPanel } from "./MarketPanel";
import { ThemeToggle } from "./ThemeToggle";
import { WatchlistRail, WatchlistStrip } from "./Watchlist";
import { API_URL, fetchHealth, fetchSnapshot, fetchSymbols, type Health } from "@/lib/api";
import type { Engine, SnapshotRow, SymbolInfo } from "@/lib/types";

const SNAPSHOT_MS = 2000;

export function Workspace() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [snapshot, setSnapshot] = useState<{ window: number; rows: SnapshotRow[] } | null>(null);
  const [selected, setSelected] = useState("VOL75");
  const [offline, setOffline] = useState(false);
  const [chosenEngine, setChosenEngine] = useState<Engine | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const chatRef = useRef<ChatHandle>(null);

  const claudeReady = health?.claude_ready ?? false;
  // Follow the backend's default until the user picks; never use Claude when it isn't connected.
  const engine: Engine = claudeReady ? (chosenEngine ?? health?.default_engine ?? "local") : "local";

  const load = useCallback(async () => {
    try {
      const [h, s, snap] = await Promise.all([fetchHealth(), fetchSymbols(), fetchSnapshot()]);
      setHealth(h);
      setSymbols(s);
      setSnapshot({ window: snap.window_minutes, rows: snap.rows });
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    const initial = setTimeout(load, 0);
    const id = setInterval(() => {
      if (offline) {
        load();
        return;
      }
      fetchSnapshot()
        .then((snap) => setSnapshot({ window: snap.window_minutes, rows: snap.rows }))
        .catch(() => setOffline(true));
    }, SNAPSHOT_MS);
    return () => {
      clearTimeout(initial);
      clearInterval(id);
    };
  }, [load, offline]);

  const select = useCallback(
    (symbol: string) => {
      const match = symbols.find((s) => s.symbol === symbol.toUpperCase());
      if (match) setSelected(match.symbol);
    },
    [symbols],
  );

  const onClaudeChange = (connected: boolean) => {
    setChosenEngine(connected ? "claude" : "local");
    fetchHealth().then(setHealth).catch(() => {});
  };

  const info = symbols.find((s) => s.symbol === selected);
  const row = snapshot?.rows.find((r) => r.symbol === selected);

  return (
    <div className="flex min-h-full flex-col lg:h-full">
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface/80 px-4 py-2.5 backdrop-blur">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-ink" aria-hidden>
            <Activity size={17} strokeWidth={2.5} />
          </span>
          <div className="min-w-0">
            <h1 className="text-[15px] font-semibold leading-tight text-ink">Quant Copilot</h1>
            <p className="truncate text-[11px] text-muted">AI research desk for a simulated market</p>
          </div>
          {health && (
            <span className="ml-2 hidden items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[11px] font-medium text-ink-2 md:inline-flex">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-good" aria-hidden />
              {health.symbols} indices live
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {health && (
            <button
              type="button"
              onClick={() => setDialogOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
            >
              {claudeReady ? (
                <>
                  <Sparkles size={13} className="text-accent" aria-hidden />
                  <span className="hidden sm:inline">{health.model}</span>
                  <span className="sm:hidden">Claude</span>
                </>
              ) : (
                <>
                  <Cpu size={13} aria-hidden />
                  <span className="hidden sm:inline">Local analyst</span>
                  <span className="mx-0.5 hidden h-3 w-px bg-line sm:inline-block" aria-hidden />
                  <Plug size={13} aria-hidden />
                  <span>Connect Claude</span>
                </>
              )}
            </button>
          )}
          <ThemeToggle />
        </div>
      </header>

      {offline ? (
        <main className="grid flex-1 place-items-center p-6">
          <div className="panel max-w-md p-6 text-sm text-ink-2">
            <p className="text-base font-semibold text-ink">Can&apos;t reach the backend</p>
            <p className="mt-1">
              Expected it at <code className="font-mono text-xs">{API_URL}</code>. Start it with:
            </p>
            <pre className="mt-3 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-ink">
              cd backend{"\n"}.venv\Scripts\python -m uvicorn app.main:app --port 8000
            </pre>
            <p className="mt-3 flex items-center gap-2 text-xs text-muted">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-warning" aria-hidden /> Retrying every few seconds…
            </p>
          </div>
        </main>
      ) : (
        <main className="grid flex-1 grid-cols-[minmax(0,1fr)] gap-3 p-3 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(380px,440px)] xl:grid-cols-[272px_minmax(0,1fr)_minmax(400px,460px)]">
          <div className="hidden min-h-0 xl:flex xl:flex-col">
            <WatchlistRail rows={snapshot?.rows ?? null} selected={selected} onSelect={setSelected} windowMinutes={snapshot?.window ?? 30} />
          </div>
          <div className="flex min-h-0 min-w-0 flex-col gap-3">
            <div className="min-w-0 xl:hidden">
              <WatchlistStrip rows={snapshot?.rows ?? null} selected={selected} onSelect={setSelected} windowMinutes={snapshot?.window ?? 30} />
            </div>
            <MarketPanel info={info} snapshot={row} onAsk={(prompt) => chatRef.current?.ask(prompt)} />
          </div>
          <ChatPanel
            ref={chatRef}
            selectedSymbol={selected}
            onSymbol={select}
            engine={engine}
            claudeReady={claudeReady}
            onEngineChange={setChosenEngine}
            onConnect={() => setDialogOpen(true)}
          />
        </main>
      )}

      <ConnectClaudeDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        claudeReady={claudeReady}
        model={health?.model}
        onChange={onClaudeChange}
      />
    </div>
  );
}
