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
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Assistant</h1>
      <p className="text-sm text-muted-foreground">
        Ask about meetings, leads, projects, and tasks. Answers only use what
        you can already see elsewhere in Trinol OS.
      </p>

      {messages.length === 0 ? (
        <p className="rounded border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          No messages yet — ask something below.
        </p>
      ) : (
        <ul className="space-y-3">
          {messages.map((message, index) => (
            <li
              key={index}
              className={`rounded border border-border p-3 text-sm ${
                message.role === "user" ? "bg-muted" : ""
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

      <form onSubmit={handleSubmit} className="flex items-end gap-2">
        <div className="flex-1">
          <label htmlFor="assistant-question" className="text-sm font-medium">
            Ask a question
          </label>
          <input
            id="assistant-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-1.5 text-sm"
          />
        </div>
        <Button type="submit" disabled={asking}>
          {asking ? "Asking..." : "Ask"}
        </Button>
      </form>
    </div>
  );
}
