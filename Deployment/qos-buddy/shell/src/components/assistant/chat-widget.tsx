"use client";

import { FormEvent, useRef, useState } from "react";
import { Bot, MessageCircle, Send, X } from "lucide-react";
import { askNetworkChat, type NetworkChatSource } from "@/lib/ai";

interface ChatMessage {
  role: "assistant" | "user";
  text: string;
  sources?: NetworkChatSource[];
}

const starter: ChatMessage = {
  role: "assistant",
  text: "Ask me about the current network, incidents, diagnostics, reports, or suggested next checks.",
};

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([starter]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  function toggle() {
    setOpen((value) => !value);
    window.setTimeout(() => inputRef.current?.focus(), 80);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    setMessages((items) => [...items, { role: "user", text: question }]);
    const response = await askNetworkChat(question);
    setMessages((items) => [
      ...items,
      { role: "assistant", text: response.answer, sources: response.sources },
    ]);
    setBusy(false);
    window.setTimeout(() => inputRef.current?.focus(), 50);
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-3">
      {open ? (
        <section className="flex h-[520px] w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--bg-1))] shadow-2xl">
          <header className="flex h-14 items-center justify-between border-b border-[hsl(var(--line-subtle))] px-4">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[hsl(var(--cy-soft))] text-[hsl(var(--cy))]">
                <Bot className="h-4 w-4" />
              </span>
              <div>
                <div className="text-sm font-semibold text-[hsl(var(--ink-0))]">QoS Assistant</div>
                <div className="text-xs text-[hsl(var(--ink-2))]">Live network + memory</div>
              </div>
            </div>
            <button
              type="button"
              aria-label="Close assistant"
              onClick={toggle}
              className="flex h-9 w-9 items-center justify-center rounded-md text-[hsl(var(--ink-2))] transition hover:bg-[hsl(var(--bg-2))] hover:text-[hsl(var(--ink-0))]"
            >
              <X className="h-4 w-4" />
            </button>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
              >
                <div
                  className={[
                    "max-w-[85%] rounded-lg px-3 py-2 text-sm leading-5",
                    message.role === "user"
                      ? "bg-[hsl(var(--cy))] text-white"
                      : "bg-[hsl(var(--bg-2))] text-[hsl(var(--ink-0))]",
                  ].join(" ")}
                >
                  <p>{message.text}</p>
                  {message.sources && message.sources.length > 0 ? (
                    <div className="mt-2 border-t border-[hsl(var(--line-subtle))] pt-2 text-xs text-[hsl(var(--ink-2))]">
                      {message.sources.slice(0, 2).map((source) => (
                        <div key={`${source.collection}-${source.id}`} className="truncate">
                          {source.collection}: {source.snippet}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
            {busy ? (
              <div className="w-fit rounded-lg bg-[hsl(var(--bg-2))] px-3 py-2 text-sm text-[hsl(var(--ink-2))]">
                Checking live network...
              </div>
            ) : null}
          </div>

          <form onSubmit={submit} className="flex gap-2 border-t border-[hsl(var(--line-subtle))] p-3">
            <input
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about the network"
              className="min-w-0 flex-1 rounded-md border border-[hsl(var(--line))] bg-[hsl(var(--bg-0))] px-3 py-2 text-sm text-[hsl(var(--ink-0))] outline-none transition placeholder:text-[hsl(var(--ink-3))] focus:border-[hsl(var(--cy))]"
            />
            <button
              type="submit"
              aria-label="Send message"
              disabled={busy || !input.trim()}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--cy))] text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </section>
      ) : null}

      <button
        type="button"
        aria-label="Open QoS assistant"
        onClick={toggle}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-[hsl(var(--cy))] text-white shadow-xl ring-1 ring-white/20 transition hover:scale-105 hover:brightness-105"
      >
        {open ? <X className="h-6 w-6" /> : <MessageCircle className="h-6 w-6" />}
      </button>
    </div>
  );
}
