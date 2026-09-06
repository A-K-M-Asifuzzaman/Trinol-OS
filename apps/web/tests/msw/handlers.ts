import { http, HttpResponse } from "msw";

// Matches lib/api/client.ts's fallback NEXT_PUBLIC_API_BASE_URL — tests
// never set that env var, so this is always the base MSW intercepts.
export const API_BASE_URL = "http://localhost:8000";

export const handlers = [
  http.get(`${API_BASE_URL}/api/v1/memberships`, () =>
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
