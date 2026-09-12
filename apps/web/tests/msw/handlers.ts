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
  http.get(`${APP_ORIGIN}/api/v1/projects`, () =>
    HttpResponse.json({
      items: [
        {
          id: "01960000-0000-7000-8000-000000000010",
          project_code: "WEB",
          name: "Website Redesign",
          description: null,
          status: "ACTIVE",
          health: "ON_TRACK",
          owner_id: "01960000-0000-7000-8000-000000000002",
          start_date: null,
          deadline: null,
          budget: null,
          currency: "USD",
          repository_url: null,
          production_url: null,
          staging_url: null,
          archived_at: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
    }),
  ),
  // Phase 8 Stage 5: default to "not scored yet" for every lead, so a
  // test that doesn't care about scoring (lead-detail.test.tsx, pipeline-
  // board.test.tsx) isn't forced to mock it just because LeadScorePanel/
  // PipelineLeadScoreBadge always fetch it — same reasoning as every
  // other default handler here, individual tests override with
  // server.use() when the score itself is what's being tested.
  http.get(`${APP_ORIGIN}/api/v1/leads/:leadId/score`, () =>
    HttpResponse.json(
      {
        error: {
          code: "NOT_FOUND",
          message: "This lead has not been scored yet",
          request_id: null,
          details: {},
        },
      },
      { status: 404 },
    ),
  ),
];
