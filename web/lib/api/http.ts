import { API_BASE_URL } from "@/lib/config";
import { SseParser } from "./sse";
import type {
  ChatEvent,
  ChatRequest,
  ErrorBody,
  HealthResponse,
  PerformanceResponse,
  PlacesSearchResponse,
  PlanRequest,
  PlanResponse,
  TrainResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: ErrorBody["detail"] | string,
  ) {
    super(typeof detail === "string" ? detail : detail.map((d) => d.msg).join("; "));
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
}

/** The API surface the UI uses. Implemented by the HTTP client and the fixtures mock. */
export interface PatriBotApi {
  health(opts?: RequestOptions): Promise<HealthResponse>;
  searchPlaces(q: string, limit?: number, opts?: RequestOptions): Promise<PlacesSearchResponse>;
  plan(req: PlanRequest, opts?: RequestOptions): Promise<PlanResponse>;
  train(trainNo: string, opts?: RequestOptions): Promise<TrainResponse>;
  performance(trainNo: string, months?: number, opts?: RequestOptions): Promise<PerformanceResponse>;
  chat(req: ChatRequest, opts?: RequestOptions): AsyncIterable<ChatEvent>;
}

/** The session expired (the proxy answered 401): send the viewer to the login page, then back here. */
function handleUnauthenticated(res: Response): boolean {
  if (res.status !== 401 || res.headers.get("x-patribot-auth") !== "required") return false;
  if (typeof window !== "undefined") {
    const here = `${window.location.pathname}${window.location.search}`;
    // A full page load on purpose: the session is gone, so no client state is worth keeping.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/login?${new URLSearchParams({ next: here })}`);
  }
  return true;
}

const UNREACHABLE = "Could not reach the PatriBot server. Check your connection and try again.";

async function request<T>(path: string, init: RequestInit & RequestOptions = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, UNREACHABLE);
  }
  if (handleUnauthenticated(res)) throw new ApiError(401, "Your session has expired. Please sign in again.");
  if (!res.ok) {
    let detail: ErrorBody["detail"] | string = res.statusText || `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as Partial<ErrorBody>;
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const httpApi: PatriBotApi = {
  health: (opts) => request("/health", { signal: opts?.signal }),

  searchPlaces: (q, limit = 10, opts) =>
    request(`/places/search?${new URLSearchParams({ q, limit: String(limit) })}`, { signal: opts?.signal }),

  plan: (req, opts) => request("/plan", { method: "POST", body: JSON.stringify(req), signal: opts?.signal }),

  train: (trainNo, opts) => request(`/trains/${encodeURIComponent(trainNo)}`, { signal: opts?.signal }),

  performance: (trainNo, months = 3, opts) =>
    request(`/trains/${encodeURIComponent(trainNo)}/performance?months=${months}`, { signal: opts?.signal }),

  async *chat(req, opts) {
    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(req),
        signal: opts?.signal,
      });
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      yield { event: "error", data: { detail: UNREACHABLE } };
      return;
    }
    if (handleUnauthenticated(res)) {
      yield { event: "error", data: { detail: "Your session has expired. Please sign in again." } };
      return;
    }
    if (!res.ok || !res.body) {
      let detail = `Chat failed (HTTP ${res.status})`;
      try {
        const body = (await res.json()) as Partial<ErrorBody>;
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        /* ignore */
      }
      yield { event: "error", data: { detail } };
      return;
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    const parser = new SseParser();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      yield* parser.push(value);
    }
    yield* parser.end();
  },
};
