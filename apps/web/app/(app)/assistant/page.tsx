"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { ApiError, askAssistant } from "@/lib/api/client";

// Phase 8 Stage 4: the chat UI is built directly on retrieval_service's
// permission-safe search (ADR-0014) via POST /ai/assistant/ask — there is
// no separate "semantic search" page, matching the plan's own decision
// that Company assistant and semantic search are one capability with two
// entry points, not two features.

interface Message {
  role: "user" | "assistant";
  text: string;
  sourceCount?: number;
}

export default function AssistantPage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    setError(null);
    setAsking(true);
    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setQuestion("");
    try {
      const result = await askAssistant({ question: trimmed });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: result.answer,
          sourceCount: result.source_count,
        },
      ]);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong asking the assistant.",
      );
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] max-w-3xl flex-col gap-5">
      <div className="border-b border-border pb-6">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-[hsl(var(--signal))] ring-4 ring-[hsl(var(--signal)/0.18)]" />
          <span className="eyebrow">Knowledge assistant</span>
        </div>
        <h1 className="text-3xl font-bold sm:text-4xl">Ask Trinol</h1>
        <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
          Ask about meetings, leads, projects, and tasks. Answers only use what
          you can already see elsewhere in Trinol OS.
        </p>
      </div>

      {messages.length === 0 ? (
        <div className="surface flex flex-1 flex-col items-center justify-center border-dashed px-6 py-16 text-center">
          <span className="mb-4 grid h-12 w-12 place-items-center rounded-full bg-[#111214] text-sm font-black text-[hsl(var(--signal))]">
            AI
          </span>
          <p className="font-semibold text-foreground">
            What do you need to know?
          </p>
          <p className="mt-1 max-w-sm text-sm leading-6 text-muted-foreground">
            No messages yet. Try asking for a project update, a meeting
            decision, or a lead summary.
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {messages.map((message, index) => (
            <li
              key={index}
              className={`rounded border border-border p-4 text-sm leading-6 shadow-sm ${
                message.role === "user" ? "ml-10 bg-muted" : "mr-10 bg-white"
              }`}
            >
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                {message.role === "user" ? "You" : "Assistant"}
              </p>
              <p className="whitespace-pre-wrap">{message.text}</p>
              {message.role === "assistant" &&
              message.sourceCount !== undefined ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Based on {message.sourceCount} source
                  {message.sourceCount === 1 ? "" : "s"}.
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <form
        onSubmit={handleSubmit}
        className="surface sticky bottom-4 flex items-end gap-2 p-3"
      >
        <div className="flex-1">
          <label htmlFor="assistant-question" className="text-sm font-medium">
            Ask a question
          </label>
          <input
            id="assistant-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about your company…"
            className="mt-1 h-11 w-full rounded border border-border px-3 text-sm"
          />
        </div>
        <Button type="submit" disabled={asking}>
          {asking ? "Asking..." : "Ask"}
        </Button>
      </form>
    </div>
  );
}
