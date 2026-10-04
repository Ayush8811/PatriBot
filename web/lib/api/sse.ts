import type { ChatEvent } from "./types";

const KNOWN = new Set(["token", "itineraries", "done", "error"]);

/**
 * Incremental parser for text/event-stream. Feed it decoded chunks; it returns complete events.
 * Handles CRLF, multi-line `data:` fields, comments (`:`) and events split across chunks.
 */
export class SseParser {
  private buffer = "";

  push(chunk: string): ChatEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const out: ChatEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      const ev = parseBlock(block);
      if (ev) out.push(ev);
    }
    return out;
  }

  /** Flush a trailing event without the final blank line. */
  end(): ChatEvent[] {
    const rest = this.buffer.trim();
    this.buffer = "";
    const ev = rest ? parseBlock(rest) : null;
    return ev ? [ev] : [];
  }
}

function parseBlock(block: string): ChatEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!KNOWN.has(event) || data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) } as ChatEvent;
  } catch {
    return null;
  }
}

/** Serialise an event (used by the mock stream and tests). */
export function formatSse(ev: ChatEvent): string {
  return `event: ${ev.event}\ndata: ${JSON.stringify(ev.data)}\n\n`;
}
