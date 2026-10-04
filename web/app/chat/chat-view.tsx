"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUp, Bot, CircleAlert, Sparkles, Square, User } from "lucide-react";

import { ItineraryCard } from "@/components/itinerary/itinerary-card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Itinerary } from "@/lib/api/types";
import { getSession } from "@/lib/auth";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  itineraries?: Itinerary[];
  error?: string;
  streaming?: boolean;
}

const SUGGESTIONS = [
  "Overnight train Kolkata to Delhi next weekend, least travel time",
  "I must reach New Delhi by 9 AM. What should I take from Howrah?",
  "How late does 12301 Rajdhani usually run?",
];

let counter = 0;
const uid = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

export function ChatView() {
  const session = getSession();
  const [sessionId] = React.useState(() =>
    typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : uid(),
  );
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [queriesLeft, setQueriesLeft] = React.useState<number | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const endRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [messages]);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const update = (id: string, fn: (m: Message) => Message) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    const aid = uid();
    setMessages((ms) => [
      ...ms,
      { id: uid(), role: "user", text: message },
      { id: aid, role: "assistant", text: "", streaming: true },
    ]);
    setInput("");
    setBusy(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      for await (const ev of api.chat({ session_id: sessionId, message }, { signal: ctrl.signal })) {
        if (ev.event === "token") update(aid, (m) => ({ ...m, text: m.text + ev.data.text }));
        else if (ev.event === "itineraries") update(aid, (m) => ({ ...m, itineraries: ev.data }));
        else if (ev.event === "done") setQueriesLeft(ev.data.usage.queries_left_today);
        else if (ev.event === "error") update(aid, (m) => ({ ...m, error: ev.data.detail }));
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError")
        update(aid, (m) => ({ ...m, error: (err as Error).message || "Something went wrong" }));
    } finally {
      update(aid, (m) => ({ ...m, streaming: false }));
      setBusy(false);
      abortRef.current = null;
      inputRef.current?.focus();
    }
  }

  const left = queriesLeft ?? session.dailyAiQueries;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b py-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Sparkles className="text-saffron size-4.5" aria-hidden /> Ask PatriBot
          </h1>
          <p className="text-muted-foreground text-xs">
            Answers use our planner&apos;s data only. The{" "}
            <Link href="/" className="underline underline-offset-2">
              search form
            </Link>{" "}
            is free and unlimited.
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-2.5 py-1 text-xs font-medium tabular-nums",
            left === 0 ? "border-bad/40 text-bad" : "text-muted-foreground",
          )}
          data-testid="queries-left"
          aria-live="polite"
        >
          {queriesLeft == null
            ? `${session.dailyAiQueries} free AI queries / day`
            : `${queriesLeft} AI quer${queriesLeft === 1 ? "y" : "ies"} left today`}
        </span>
      </div>

      <div role="log" aria-label="Conversation" aria-busy={busy} className="flex-1 space-y-6 py-6">
        {messages.length === 0 && (
          <div className="py-8 text-center">
            <div className="bg-primary/10 text-primary mx-auto mb-3 grid size-12 place-items-center rounded-full">
              <Bot className="size-6" aria-hidden />
            </div>
            <h2 className="text-lg font-semibold">Where are you headed?</h2>
            <p className="text-muted-foreground mx-auto mt-1 max-w-md text-sm">
              Describe your trip in your own words: cities, dates, overnight, a time you must arrive by.
            </p>
            <div className="mt-5 flex flex-col items-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="hover:bg-accent max-w-full rounded-full border px-3 py-1.5 text-sm transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <ChatMessage key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>

      <form
        className="bg-background/95 sticky bottom-0 border-t py-3 backdrop-blur"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <div className="bg-card focus-within:ring-ring/50 focus-within:border-ring flex items-end gap-2 rounded-2xl border p-2 shadow-sm focus-within:ring-[3px]">
          <label htmlFor="chat-input" className="sr-only">
            Message PatriBot
          </label>
          <textarea
            id="chat-input"
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(input);
              }
            }}
            placeholder="e.g. overnight train Kolkata to Delhi next weekend"
            className="placeholder:text-muted-foreground max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-base outline-none md:text-sm"
          />
          {busy ? (
            <Button type="button" size="icon" variant="secondary" aria-label="Stop" onClick={() => abortRef.current?.abort()}>
              <Square aria-hidden />
            </Button>
          ) : (
            <Button type="submit" size="icon" aria-label="Send" disabled={!input.trim()}>
              <ArrowUp aria-hidden />
            </Button>
          )}
        </div>
        <p className="text-muted-foreground mt-1.5 text-center text-[11px]">
          Each message uses 1 AI query. Predictions are estimates; always confirm on IRCTC.
        </p>
      </form>
    </div>
  );
}

function ChatMessage({ message: m }: { message: Message }) {
  const isUser = m.role === "user";
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")} data-testid={`msg-${m.role}`}>
      <span
        className={cn(
          "grid size-8 shrink-0 place-items-center rounded-full",
          isUser ? "bg-secondary text-secondary-foreground" : "bg-primary text-primary-foreground",
        )}
        aria-hidden
      >
        {isUser ? <User className="size-4" /> : <Bot className="size-4" />}
      </span>
      <div className={cn("min-w-0 space-y-3", isUser ? "max-w-[85%]" : "flex-1")}>
        <span className="sr-only">{isUser ? "You said:" : "PatriBot said:"}</span>
        {(m.text || m.streaming) && (
          <div
            className={cn(
              "rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
              isUser ? "bg-primary text-primary-foreground rounded-tr-sm" : "bg-card rounded-tl-sm border",
            )}
            data-testid={isUser ? undefined : "assistant-text"}
          >
            {m.text}
            {m.streaming && (
              <span className="bg-primary ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm align-text-bottom" aria-hidden />
            )}
          </div>
        )}
        {m.error && (
          <div role="alert" className="border-bad/30 bg-bad-soft text-bad flex items-start gap-2 rounded-xl border px-3 py-2 text-sm">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {m.error}
          </div>
        )}
        {m.itineraries?.map((it) => (
          <ItineraryCard key={it.id} itinerary={it} />
        ))}
      </div>
    </div>
  );
}
