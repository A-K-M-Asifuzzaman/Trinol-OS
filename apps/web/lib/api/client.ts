import type { components } from "./types.gen";

// ARCHITECTURE.md §6: {"error": {code, message, request_id, details}}.
export interface ErrorEnvelope {
  code: string;
  message: string;
  request_id: string | null;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;
  details: Record<string, unknown>;

  constructor(status: number, envelope: ErrorEnvelope) {
    super(envelope.message);
    this.status = status;
    this.code = envelope.code;
    this.requestId = envelope.request_id;
    this.details = envelope.details;
  }
}

// ARCHITECTURE.md §1: "Web and API are served from one origin ... That is
// what makes a SameSite=Lax session cookie work without CORS credentials or
// a token in JavaScript." CORS is deliberately disabled server-side
// (SECURITY.md §3), so the browser must never call the API cross-origin —
// a relative path is same-origin by construction, and next.config.mjs's
// /api/* rewrite proxies it to FastAPI.
//
// Server components have no browser origin to be relative to (Node's fetch
// requires an absolute URL) and run outside next.config.mjs's rewrite
// entirely, so they need a real address: INTERNAL_API_URL, a server-only
// env var (never NEXT_PUBLIC_, so it's never bundled to the client) — the
// container hostname inside Docker (docker-compose.yml sets it to
// http://api:8000), or localhost:8000 for host-side `pnpm dev`.
const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

function resolveUrl(path: string): string {
  return typeof window === "undefined" ? `${INTERNAL_API_URL}${path}` : path;
}

// In-memory only, per ARCHITECTURE.md §5/AUTH.md §6 — never persisted, reset
// on every page load. Set from GET /auth/session's csrf_token field.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

const UNSAFE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

interface ApiFetchOptions {
  method?: string;
  body?: unknown;
  /** Server components forward the incoming request's Cookie header
   * manually (AUTH.md §10) — the browser attaches its own automatically via
   * credentials: "include", so client components never pass this. */
  cookie?: string;
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (options.cookie) headers.Cookie = options.cookie;
  if (UNSAFE_METHODS.has(method) && csrfToken)
    headers["X-CSRF-Token"] = csrfToken;

  const response = await fetch(resolveUrl(path), {
    method,
    headers,
    credentials: "include",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: ErrorEnvelope;
    } | null;
    if (payload?.error) {
      throw new ApiError(response.status, payload.error);
    }
    throw new ApiError(response.status, {
      code: "UNKNOWN_ERROR",
      message: response.statusText || "Request failed",
      request_id: null,
      details: {},
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type SessionInfo = components["schemas"]["SessionInfoResponse"];
export type SessionExchangeResponse =
  components["schemas"]["SessionExchangeResponse"];
export type Membership = components["schemas"]["MembershipResponse"];
export type MembershipList = components["schemas"]["MembershipListResponse"];

export async function fetchSessionInfo(cookie?: string): Promise<SessionInfo> {
  return apiFetch<SessionInfo>("/api/v1/auth/session", { cookie });
}

export async function exchangeSession(
  idToken: string,
): Promise<SessionExchangeResponse> {
  return apiFetch<SessionExchangeResponse>("/api/v1/auth/session", {
    method: "POST",
    body: { id_token: idToken },
  });
}

export async function fetchTeamMembers(
  options: { limit?: number; offset?: number; cookie?: string } = {},
): Promise<MembershipList> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<MembershipList>(
    `/api/v1/memberships${query ? `?${query}` : ""}`,
    {
      cookie: options.cookie,
    },
  );
}

export type Project = components["schemas"]["ProjectResponse"];
export type ProjectList = components["schemas"]["ProjectListResponse"];
export type ProjectCreateRequest =
  components["schemas"]["ProjectCreateRequest"];
export type ProjectUpdateRequest =
  components["schemas"]["ProjectUpdateRequest"];
export type ProjectBoard = components["schemas"]["ProjectBoardResponse"];
export type BoardColumn = components["schemas"]["BoardColumn"];
export type Task = components["schemas"]["TaskResponse"];
export type TaskList = components["schemas"]["TaskListResponse"];
export type TaskCreateRequest = components["schemas"]["TaskCreateRequest"];
export type TaskUpdateRequest = components["schemas"]["TaskUpdateRequest"];
export type TaskStatus = components["schemas"]["TaskStatus"];

export async function fetchProjects(
  options: { limit?: number; offset?: number; cookie?: string } = {},
): Promise<ProjectList> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<ProjectList>(`/api/v1/projects${query ? `?${query}` : ""}`, {
    cookie: options.cookie,
  });
}

export async function fetchProject(
  projectId: string,
  cookie?: string,
): Promise<Project> {
  return apiFetch<Project>(`/api/v1/projects/${projectId}`, { cookie });
}

export async function createProject(
  body: ProjectCreateRequest,
): Promise<Project> {
  return apiFetch<Project>("/api/v1/projects", { method: "POST", body });
}

export async function updateProject(
  projectId: string,
  body: ProjectUpdateRequest,
): Promise<Project> {
  return apiFetch<Project>(`/api/v1/projects/${projectId}`, {
    method: "PATCH",
    body,
  });
}

export async function fetchProjectBoard(
  projectId: string,
  cookie?: string,
): Promise<ProjectBoard> {
  return apiFetch<ProjectBoard>(`/api/v1/projects/${projectId}/board`, {
    cookie,
  });
}

export async function fetchTasks(
  options: {
    projectId?: string;
    assigneeId?: string;
    status?: TaskStatus;
    limit?: number;
    offset?: number;
    cookie?: string;
  } = {},
): Promise<TaskList> {
  const params = new URLSearchParams();
  if (options.projectId) params.set("project_id", options.projectId);
  if (options.assigneeId) params.set("assignee_id", options.assigneeId);
  if (options.status) params.set("status", options.status);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<TaskList>(`/api/v1/tasks${query ? `?${query}` : ""}`, {
    cookie: options.cookie,
  });
}

export async function fetchTask(
  taskId: string,
  cookie?: string,
): Promise<Task> {
  return apiFetch<Task>(`/api/v1/tasks/${taskId}`, { cookie });
}

export async function createTask(body: TaskCreateRequest): Promise<Task> {
  return apiFetch<Task>("/api/v1/tasks", { method: "POST", body });
}

export async function updateTask(
  taskId: string,
  body: TaskUpdateRequest,
): Promise<Task> {
  return apiFetch<Task>(`/api/v1/tasks/${taskId}`, {
    method: "PATCH",
    body,
  });
}

export async function deleteTask(taskId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/tasks/${taskId}`, { method: "DELETE" });
}

export type Lead = components["schemas"]["LeadResponse"];
export type LeadList = components["schemas"]["LeadListResponse"];
export type LeadCreateRequest = components["schemas"]["LeadCreateRequest"];
export type LeadUpdateRequest = components["schemas"]["LeadUpdateRequest"];
export type LeadStage = components["schemas"]["LeadStage"];
export type LeadSource = components["schemas"]["LeadSource"];
export type LeadStats = components["schemas"]["LeadStatsResponse"];
export type LeadConversion = components["schemas"]["LeadConversionResponse"];
export type Client = components["schemas"]["ClientResponse"];
export type ClientList = components["schemas"]["ClientListResponse"];
export type ClientCreateRequest = components["schemas"]["ClientCreateRequest"];
export type ClientUpdateRequest = components["schemas"]["ClientUpdateRequest"];
export type PipelineBoard = components["schemas"]["PipelineBoardResponse"];
export type PipelineColumn = components["schemas"]["PipelineColumn"];

export async function fetchLeads(
  options: {
    stage?: LeadStage;
    assignedTo?: string;
    limit?: number;
    offset?: number;
    cookie?: string;
  } = {},
): Promise<LeadList> {
  const params = new URLSearchParams();
  if (options.stage) params.set("stage", options.stage);
  if (options.assignedTo) params.set("assigned_to", options.assignedTo);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<LeadList>(`/api/v1/leads${query ? `?${query}` : ""}`, {
    cookie: options.cookie,
  });
}

export async function fetchLeadStats(cookie?: string): Promise<LeadStats> {
  return apiFetch<LeadStats>("/api/v1/leads/stats", { cookie });
}

export async function fetchLead(
  leadId: string,
  cookie?: string,
): Promise<Lead> {
  return apiFetch<Lead>(`/api/v1/leads/${leadId}`, { cookie });
}

export async function createLead(body: LeadCreateRequest): Promise<Lead> {
  return apiFetch<Lead>("/api/v1/leads", { method: "POST", body });
}

export async function updateLead(
  leadId: string,
  body: LeadUpdateRequest,
): Promise<Lead> {
  return apiFetch<Lead>(`/api/v1/leads/${leadId}`, { method: "PATCH", body });
}

export async function archiveLead(leadId: string): Promise<Lead> {
  return apiFetch<Lead>(`/api/v1/leads/${leadId}`, { method: "DELETE" });
}

export async function convertLead(leadId: string): Promise<LeadConversion> {
  return apiFetch<LeadConversion>(`/api/v1/leads/${leadId}/convert`, {
    method: "POST",
  });
}

export async function fetchClients(
  options: { limit?: number; offset?: number; cookie?: string } = {},
): Promise<ClientList> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<ClientList>(`/api/v1/clients${query ? `?${query}` : ""}`, {
    cookie: options.cookie,
  });
}

export async function fetchClient(
  clientId: string,
  cookie?: string,
): Promise<Client> {
  return apiFetch<Client>(`/api/v1/clients/${clientId}`, { cookie });
}

export async function createClient(body: ClientCreateRequest): Promise<Client> {
  return apiFetch<Client>("/api/v1/clients", { method: "POST", body });
}

export async function updateClient(
  clientId: string,
  body: ClientUpdateRequest,
): Promise<Client> {
  return apiFetch<Client>(`/api/v1/clients/${clientId}`, {
    method: "PATCH",
    body,
  });
}

export async function archiveClient(clientId: string): Promise<Client> {
  return apiFetch<Client>(`/api/v1/clients/${clientId}`, { method: "DELETE" });
}

export async function fetchPipeline(cookie?: string): Promise<PipelineBoard> {
  return apiFetch<PipelineBoard>("/api/v1/pipeline", { cookie });
}

export type Meeting = components["schemas"]["MeetingResponse"];
export type MeetingList = components["schemas"]["MeetingListResponse"];
export type MeetingCreateRequest =
  components["schemas"]["MeetingCreateRequest"];
export type MeetingUpdateRequest =
  components["schemas"]["MeetingUpdateRequest"];
// Generated name is mangled — it collided with the model's own RSVP-status
// enum (models.MeetingParticipantResponse), so openapi-typescript qualified
// both by their Python module path instead of picking one.
export type MeetingParticipant =
  components["schemas"]["trinol__modules__meetings__schemas__MeetingParticipantResponse"];
export type MeetingParticipantList =
  components["schemas"]["MeetingParticipantListResponse"];
export type MeetingParticipantAddRequest =
  components["schemas"]["MeetingParticipantAddRequest"];
export type MeetingParticipantResponseUpdateRequest =
  components["schemas"]["MeetingParticipantResponseUpdateRequest"];
export type MeetingDecision = components["schemas"]["MeetingDecisionResponse"];
export type MeetingDecisionList =
  components["schemas"]["MeetingDecisionListResponse"];
export type MeetingDecisionCreateRequest =
  components["schemas"]["MeetingDecisionCreateRequest"];
export type MeetingAction = components["schemas"]["MeetingActionResponse"];
export type MeetingActionList =
  components["schemas"]["MeetingActionListResponse"];
export type MeetingActionCreateRequest =
  components["schemas"]["MeetingActionCreateRequest"];
export type MeetingActionUpdateRequest =
  components["schemas"]["MeetingActionUpdateRequest"];

export async function fetchMeetings(
  options: { limit?: number; offset?: number; cookie?: string } = {},
): Promise<MeetingList> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<MeetingList>(`/api/v1/meetings${query ? `?${query}` : ""}`, {
    cookie: options.cookie,
  });
}

export async function fetchMeeting(
  meetingId: string,
  cookie?: string,
): Promise<Meeting> {
  return apiFetch<Meeting>(`/api/v1/meetings/${meetingId}`, { cookie });
}

export async function createMeeting(
  body: MeetingCreateRequest,
): Promise<Meeting> {
  return apiFetch<Meeting>("/api/v1/meetings", { method: "POST", body });
}

export async function updateMeeting(
  meetingId: string,
  body: MeetingUpdateRequest,
): Promise<Meeting> {
  return apiFetch<Meeting>(`/api/v1/meetings/${meetingId}`, {
    method: "PATCH",
    body,
  });
}

export async function deleteMeeting(meetingId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/meetings/${meetingId}`, { method: "DELETE" });
}

export async function fetchMeetingParticipants(
  meetingId: string,
  cookie?: string,
): Promise<MeetingParticipantList> {
  return apiFetch<MeetingParticipantList>(
    `/api/v1/meetings/${meetingId}/participants`,
    { cookie },
  );
}

export async function addMeetingParticipant(
  meetingId: string,
  body: MeetingParticipantAddRequest,
): Promise<MeetingParticipant> {
  return apiFetch<MeetingParticipant>(
    `/api/v1/meetings/${meetingId}/participants`,
    { method: "POST", body },
  );
}

export async function removeMeetingParticipant(
  meetingId: string,
  participantId: string,
): Promise<void> {
  return apiFetch<void>(
    `/api/v1/meetings/${meetingId}/participants/${participantId}`,
    { method: "DELETE" },
  );
}

export async function updateMeetingParticipantResponse(
  meetingId: string,
  participantId: string,
  body: MeetingParticipantResponseUpdateRequest,
): Promise<MeetingParticipant> {
  return apiFetch<MeetingParticipant>(
    `/api/v1/meetings/${meetingId}/participants/${participantId}`,
    { method: "PATCH", body },
  );
}

export async function fetchMeetingDecisions(
  meetingId: string,
  cookie?: string,
): Promise<MeetingDecisionList> {
  return apiFetch<MeetingDecisionList>(
    `/api/v1/meetings/${meetingId}/decisions`,
    { cookie },
  );
}

export async function createMeetingDecision(
  meetingId: string,
  body: MeetingDecisionCreateRequest,
): Promise<MeetingDecision> {
  return apiFetch<MeetingDecision>(`/api/v1/meetings/${meetingId}/decisions`, {
    method: "POST",
    body,
  });
}

export async function deleteMeetingDecision(
  meetingId: string,
  decisionId: string,
): Promise<void> {
  return apiFetch<void>(
    `/api/v1/meetings/${meetingId}/decisions/${decisionId}`,
    { method: "DELETE" },
  );
}

export async function fetchMeetingActions(
  meetingId: string,
  cookie?: string,
): Promise<MeetingActionList> {
  return apiFetch<MeetingActionList>(`/api/v1/meetings/${meetingId}/actions`, {
    cookie,
  });
}

export async function createMeetingAction(
  meetingId: string,
  body: MeetingActionCreateRequest,
): Promise<MeetingAction> {
  return apiFetch<MeetingAction>(`/api/v1/meetings/${meetingId}/actions`, {
    method: "POST",
    body,
  });
}

export async function updateMeetingAction(
  meetingId: string,
  actionId: string,
  body: MeetingActionUpdateRequest,
): Promise<MeetingAction> {
  return apiFetch<MeetingAction>(
    `/api/v1/meetings/${meetingId}/actions/${actionId}`,
    { method: "PATCH", body },
  );
}

export async function deleteMeetingAction(
  meetingId: string,
  actionId: string,
): Promise<void> {
  return apiFetch<void>(`/api/v1/meetings/${meetingId}/actions/${actionId}`, {
    method: "DELETE",
  });
}

// Returns the newly created Task, not a MeetingAction — promote_action's
// own response_model is TaskResponse (ROADMAP.md Phase 4 Stage 5).
export async function promoteMeetingAction(
  meetingId: string,
  actionId: string,
): Promise<Task> {
  return apiFetch<Task>(
    `/api/v1/meetings/${meetingId}/actions/${actionId}/promote`,
    { method: "POST" },
  );
}
