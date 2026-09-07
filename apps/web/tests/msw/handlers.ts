import { http, HttpResponse } from "msw";

// Same-origin, relative paths — lib/api/client.ts calls the API this way
// from the browser (ARCHITECTURE.md §1's /api/* rewrite), and
// vitest.config.ts's jsdom url gives "relative" a concrete origin to
// resolve against here, same as it resolves in the real app.
export const APP_ORIGIN = "http://localhost:3000";

export const handlers = [
  http.get(`${APP_ORIGIN}/api/v1/memberships`, () =>
    HttpResponse.json({
      items: [
        {
          id: "01960000-0000-7000-8000-000000000001",
          user_id: "01960000-0000-7000-8000-000000000002",
          full_name: "Ada Lovelace",
          email: "ada@trinolit.com",
          avatar_url: null,
          role: "OWNER",
          job_title: "Founder",
          status: "ACTIVE",
          joined_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
    }),
  ),
];
