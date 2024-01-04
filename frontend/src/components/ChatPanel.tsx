"use client";

import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref } from "react";
import {
  ArrowUp,
  Cpu,
  Dices,
  FlaskConical,
  Layers,
  ListOrdered,
  Plug,
  Route,
  Sparkles,
  Square,
  SquarePen,
  TriangleAlert,
  Waves,
} from "lucide-react";
import { ToolCard } from "./cards/ToolCard";
import { Markdown } from "./Markdown";
import { Segmented } from "./ui";
import { API_URL, ApiError, streamChat } from "@/lib/api";
import { compact } from "@/lib/format";
import type { AgentEvent, ChatMessage, Engine, Part } from "@/lib/types";

type AssistantMessage = Extract<ChatMessage, { role: "assistant" }>;
export type ChatHandle = { ask: (text: string) => void };

let counter = 0;
const uid = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

function applyEvent(m: AssistantMessage, ev: AgentEvent): AssistantMessage {
  const parts = [...m.parts];
  switch (ev.type) {
    case "text": {
      const last = parts[parts.length - 1];
      if (last?.kind === "text") parts[parts.length - 1] = { ...last, text: last.text + ev.delta };
      else parts.push({ kind: "text", text: ev.delta });
      return { ...m, parts };
    }
    case "tool_start":
      if (!parts.some((p) => p.kind === "tool" && p.id === ev.id)) parts.push({ kind: "tool", id: ev.id, name: ev.name, status: "running" });
      return { ...m, parts };
    case "tool_result": {
      const done: Part = { kind: "tool", id: ev.id, name: ev.name, status: ev.ok ? "done" : "error", input: ev.input, ui: ev.ui, error: ev.error };
      const idx = parts.findIndex((p) => p.kind === "tool" && p.id === ev.id);
      if (idx >= 0) parts[idx] = done;
      else parts.push(done);
      return { ...m, parts };
    }
    case "error":
      return { ...m, parts: [...parts, { kind: "error", message: ev.message }] };
    case "done":
      return { ...m, usage: ev.usage, engine: ev.engine ?? m.engine };
  }
}

function toApi(m: ChatMessage) {
  if (m.role === "user") return { role: "user" as const, content: m.text };
  const text = m.parts
    .filter((p): p is Extract<Part, { kind: "text" }> => p.kind === "text")
    .map((p) => p.text)
    .join("\n\n");
  return { role: "assistant" as const, content: text };
}

const SUGGESTIONS = [
  { icon: ListOrdered, title: "Rank volatility", prompt: "Which index is calmest right now?" },
  { icon: FlaskConical, title: "Find a real edge", prompt: "Run a 2/5 SMA crossover with zero fees on MOMENTUM50 and VOL50. Which has a real edge?" },
  { icon: Layers, title: "Detect regimes", prompt: "Does REGIME have distinct volatility regimes?" },
  { icon: Route, title: "Catch overfitting", prompt: "Optimise a breakout strategy on VOL50 with walk-forward" },
  { icon: Waves, title: "Explain a spike", prompt: "Did JUMP50 jump recently? How big were the moves?" },
  { icon: Dices, title: "Ask for a prediction", prompt: "Will VOL75 go up over the next hour?" },
];

const ENGINE_LABEL: Record<Engine, { name: string; icon: typeof Cpu }> = {
  local: { name: "Local analyst", icon: Cpu },
  claude: { name: "Claude", icon: Sparkles },
};

export function ChatPanel({
  ref,
  selectedSymbol,
  onSymbol,
  engine,
  claudeReady,
  onEngineChange,
  onConnect,
}: {
  ref?: Ref<ChatHandle>;
  selectedSymbol: string;
  onSymbol: (symbol: string) => void;
  engine: Engine;
  claudeReady: boolean;
  onEngineChange: (engine: Engine) => void;
  onConnect: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const last = messages[messages.length - 1];
  const busy = last?.role === "assistant" && last.streaming;

  // Layout effect: pin to the bottom before paint, so no intermediate scroll event
  // (from content growing) can make us think the user scrolled away.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const updateAssistant = (id: string, fn: (m: AssistantMessage) => AssistantMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === id && m.role === "assistant" ? fn(m) : m)));

  async function send(raw: string) {
    const text = raw.trim();
    if (!text || busy) return;
    const user: ChatMessage = { id: uid(), role: "user", text };
    const assistant: AssistantMessage = { id: uid(), role: "assistant", parts: [], engine, streaming: true };
    const history = [...messages, user].map(toApi).filter((m) => m.content.trim());
    setMessages((ms) => [...ms, user, assistant]);
    setInput("");
    stickToBottom.current = true;

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamChat(
        { messages: history, engine, context: { symbol: selectedSymbol } },
        (ev) => updateAssistant(assistant.id, (m) => applyEvent(m, ev)),
        ctrl.signal,
      );
    } catch (err) {
      const message = ctrl.signal.aborted
        ? "Stopped."
        : err instanceof ApiError
          ? err.message
          : `Couldn't reach the backend at ${API_URL}. Is it running?`;
      updateAssistant(assistant.id, (m) => ({ ...m, parts: [...m.parts, { kind: "error", message }] }));
    } finally {
      updateAssistant(assistant.id, (m) => ({
        ...m,
        streaming: false,
        parts: m.parts.map((p) => (p.kind === "tool" && p.status === "running" ? { ...p, status: "error", error: "Interrupted" } : p)),
      }));
      abortRef.current = null;
    }
  }

  useImperativeHandle(ref, () => ({ ask: (text: string) => void send(text) }));

  return (
    <section className="panel flex min-h-[75vh] flex-col overflow-hidden lg:min-h-0" aria-label="Copilot chat">
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
            <Sparkles size={15} aria-hidden />
          </span>
          <h2 className="truncate text-sm font-semibold text-ink">Research copilot</h2>
        </div>
        <div className="flex items-center gap-1.5">
          <Segmented
            label="Copilot engine"
            value={engine}
            onChange={(v) => (v === "claude" && !claudeReady ? onConnect() : onEngineChange(v))}
            options={[
              { value: "local", label: <><Cpu size={13} aria-hidden /> Local</>, title: "Rule-based analyst. Runs offline, no API key." },
              {
                value: "claude",
                label: claudeReady ? <><Sparkles size={13} aria-hidden /> Claude</> : <><Plug size={13} aria-hidden /> Claude</>,
                title: claudeReady ? "Claude with tool use" : "Connect an Anthropic API key to use Claude",
              },
            ]}
          />
          {messages.length > 0 && !busy && (
            <button
              type="button"
              onClick={() => setMessages([])}
              title="New chat"
              aria-label="New chat"
              className="grid h-7 w-7 place-items-center rounded-lg text-ink-2 hover:bg-surface-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
            >
              <SquarePen size={15} aria-hidden />
            </button>
          )}
        </div>
      </header>

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4 [overflow-anchor:none]"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <div className="rise-in flex min-h-full flex-col justify-center gap-5 py-2">
            <div>
              <p className="text-base font-semibold text-ink">Ask the market anything</p>
              <p className="mt-1 text-sm leading-relaxed text-ink-2">
                I run real volatility, regime and backtest computations on the live simulated ticks, then tell you honestly whether
                anything beats random.
              </p>
              <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
                {engine === "local" ? (
                  <>
                    <Cpu size={12} aria-hidden /> Local analyst: works offline, no API key needed.
                    {!claudeReady && (
                      <button type="button" onClick={onConnect} className="font-medium text-accent hover:underline">
                        Connect Claude
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <Sparkles size={12} aria-hidden /> Claude with tool use.
                  </>
                )}
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
              {SUGGESTIONS.map(({ icon: Icon, title, prompt }) => (
                <button
                  key={title}
                  type="button"
                  onClick={() => send(prompt)}
                  className="group flex items-start gap-3 rounded-xl border border-line bg-surface p-3 text-left transition-colors hover:border-accent hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent"
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-ink-2 group-hover:text-accent">
                    <Icon size={14} aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-ink">{title}</span>
                    <span className="block text-xs leading-snug text-muted">{prompt}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="rise-in flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm text-accent-ink">{m.text}</p>
                </div>
              ) : (
                <AssistantBubble key={m.id} message={m} onSymbol={onSymbol} />
              ),
            )}
          </div>
        )}
      </div>

      <form
        className="border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <div className="flex items-end gap-2 rounded-xl border border-line bg-surface-2 p-1.5 transition-colors focus-within:border-accent">
          <label htmlFor="chat-input" className="sr-only">
            Message the copilot
          </label>
          <textarea
            id="chat-input"
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder={`Ask about ${selectedSymbol} or a strategy…`}
            className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              aria-label="Stop"
              title="Stop"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ink text-surface hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <Square size={12} fill="currentColor" aria-hidden />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              aria-label="Send"
              title="Send (Enter)"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-ink transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-35"
            >
              <ArrowUp size={16} strokeWidth={2.5} aria-hidden />
            </button>
          )}
        </div>
        <p className="mt-2 flex justify-between gap-2 px-1 text-[11px] text-muted">
          <span>Simulated market · research tool, not financial advice</span>
          <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line</span>
        </p>
      </form>
    </section>
  );
}

function AssistantBubble({ message: m, onSymbol }: { message: AssistantMessage; onSymbol: (s: string) => void }) {
  const { name, icon: Icon } = ENGINE_LABEL[m.engine];
  return (
    <div className="rise-in space-y-2.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-ink-2">
        <span className="grid h-5 w-5 place-items-center rounded-md bg-accent-soft text-accent">
          <Icon size={12} aria-hidden />
        </span>
        {name}
      </div>
      {m.parts.map((p, i) =>
        p.kind === "text" ? (
          <Markdown key={i} text={p.text} />
        ) : p.kind === "tool" ? (
          <ToolCard key={p.id} part={p} onSymbol={onSymbol} />
        ) : (
          <p key={i} className="flex gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink-2">
            <TriangleAlert size={15} className="mt-0.5 shrink-0 text-critical-text" aria-hidden />
            <span>{p.message}</span>
          </p>
        ),
      )}
      {m.streaming && m.parts.length === 0 && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <span className="live-dot inline-block h-2 w-2 rounded-full bg-accent" aria-hidden /> Thinking…
        </p>
      )}
      {!m.streaming && (m.usage || m.engine === "local") && (
        <p className="text-[11px] text-muted tabular">
          {m.usage
            ? `${m.usage.requests} model call${m.usage.requests === 1 ? "" : "s"} · ${compact(m.usage.input_tokens)} input tokens (${compact(m.usage.cache_read_input_tokens)} cached) · ${compact(m.usage.output_tokens)} output`
            : "Computed locally · no API calls"}
        </p>
      )}
    </div>
  );
}
