import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import AssistantPage from "@/app/(app)/assistant/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

describe("AssistantPage", () => {
  it("shows an empty state before any question is asked", () => {
    render(<AssistantPage />);
    expect(screen.getByText(/no messages yet/i)).toBeInTheDocument();
  });

  it("asks a question and renders the answer with its source count", async () => {
    server.use(
      http.post(`${APP_ORIGIN}/api/v1/ai/assistant/ask`, () =>
        HttpResponse.json({
          answer: "The billing rewrite is the current priority.",
          source_count: 3,
        }),
      ),
    );
    render(<AssistantPage />);

    fireEvent.change(screen.getByLabelText("Ask a question"), {
      target: { value: "What is the current priority?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      screen.getByText("What is the current priority?"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText("The billing rewrite is the current priority."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Based on 3 sources.")).toBeInTheDocument();
  });

  it("shows an error message when the request fails, rather than failing silently", async () => {
    server.use(
      http.post(`${APP_ORIGIN}/api/v1/ai/assistant/ask`, () =>
        HttpResponse.json(
          {
            error: {
              code: "FORBIDDEN",
              message: "Missing required permission: AI_ASSISTANT_USE",
              request_id: null,
              details: {},
            },
          },
          { status: 403 },
        ),
      ),
    );
    render(<AssistantPage />);

    fireEvent.change(screen.getByLabelText("Ask a question"), {
      target: { value: "Anything interesting?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Missing required permission: AI_ASSISTANT_USE",
      ),
    );
  });
});
