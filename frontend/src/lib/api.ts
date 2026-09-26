import type { AgentEvent, Engine, SnapshotRow, SymbolInfo } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws");

export type Health = {
  status: string;
  copilot_ready: boolean;
  claude_ready: boolean;
  default_engine: Engine;
  model: string;
  symbols: number;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res));
  return res.json() as Promise<T>;
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg;
  } catch {
    /* fall through to the status text */
  }
  return `${res.status} ${res.statusText}`;
}

export const fetchHealth = (signal?: AbortSignal) => request<Health>("/api/health", { signal });
export const fetchSymbols = (signal?: AbortSignal) => request<SymbolInfo[]>("/api/symbols", { signal });
export const fetchSnapshot = (signal?: AbortSignal) =>
  request<{ window_minutes: number; rows: SnapshotRow[] }>("/api/snapshot", { signal });

export type TickHistory = { symbol: string; decimals: number; points: { t: number; v: number }[] };
export type CandleHistory = {
  symbol: string;
  decimals: number;
  points: { t: number; o: number; h: number; l: number; c: number }[];
};

export const fetchHistory = (symbol: string, count: number, signal?: AbortSignal) =>
  request<TickHistory>(`/api/history/${encodeURIComponent(symbol)}?count=${count}`, { signal });
export const fetchCandles = (symbol: string, granularity: number, count: number, signal?: AbortSignal) =>
  request<CandleHistory>(`/api/history/${encodeURIComponent(symbol)}?count=${count}&granularity=${granularity}`, { signal });

export const connectClaude = (apiKey: string, remember: boolean) =>
  request<{ claude_ready: boolean; saved: boolean }>("/api/copilot/key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey, remember }),
  });

export const disconnectClaude = () => request<{ claude_ready: boolean }>("/api/copilot/key", { method: "DELETE" });

/** POST the conversation and invoke `onEvent` for every server-sent event until the stream ends. */
export async function streamChat(
  body: {
    messages: { role: "user" | "assistant"; content: string }[];
    engine: Engine;
    context: { symbol: string | null };
  },
  onEvent: (event: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await errorDetail(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    // SSE allows CRLF line endings; normalise so event boundaries are always "\n\n".
    buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as AgentEvent);
      }
    }
  }
}
