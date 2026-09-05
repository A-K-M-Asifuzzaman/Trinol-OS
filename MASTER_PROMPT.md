# TRINOL OS — MASTER BUILD SPECIFICATION

You are responsible for helping build Trinol OS, TrinolIT's internal company operating system.

## 1. Product Identity

Product Name: Trinol OS  
Company: TrinolIT  
Website: https://www.trinolit.com  
Primary Email: hello@trinolit.com

Initial customer: TrinolIT itself.

Long-term direction: a SaaS operating system for software agencies, startups, service companies, and SMEs.

Core idea:

> One place to run the company.

The system should eventually connect:
- leads
- clients
- sales
- projects
- tasks
- meetings
- documents
- team
- finance
- communication
- analytics
- automation
- AI

Do not build an enormous ERP in V1.

## 2. Primary Goals

TrinolIT should be able to open Trinol OS and immediately understand:

1. What needs attention today?
2. Which projects are active?
3. Who owns each task?
4. Which deadlines are approaching?
5. Which leads require follow-up?
6. Which clients require attention?
7. What meetings are coming?
8. What is the pipeline value?
9. What are current revenue and expenses?
10. Which projects are at risk?
11. What happened recently?

## 3. Product Strategy

V1 — Internal company operating system  
V2 — Integrations and automation  
V3 — AI intelligence  
V4 — Commercial multi-tenant SaaS

Design for future multi-tenancy, but do not overengineer V1.

## 4. Preferred Stack

Frontend:
- Next.js latest stable
- TypeScript
- App Router
- Tailwind CSS
- shadcn/ui
- React Hook Form
- Zod
- TanStack Query where appropriate

Backend:
- FastAPI
- Python 3.12+
- Pydantic v2
- SQLAlchemy 2
- Alembic

Database:
- PostgreSQL

Other:
- Redis only where needed
- Docker
- Docker Compose
- pytest
- Vitest
- React Testing Library
- Playwright
- Ruff
- mypy/pyright
- ESLint
- Prettier

## 5. Monorepo

Preferred structure:

trinol-os/
├── apps/
│   ├── web/
│   └── api/
├── packages/
│   └── shared/
├── infrastructure/
├── docs/
│   ├── architecture/
│   ├── product/
│   └── adr/
├── scripts/
├── docker-compose.yml
├── .env.example
├── README.md
├── AGENTS.md
├── CLAUDE.md
├── CODEX.md
└── ROADMAP.md

## 6. UX / Design Direction

The app must feel premium and production-grade.

References for quality only:
- Linear
- Stripe
- Vercel
- Notion
- Attio

Avoid:
- generic admin-template look
- excessive gradients
- random glow
- excessive glassmorphism
- childish animation
- huge empty cards
- unnecessary whitespace

## 7. App Navigation

Overview

WORK
- My Work
- Projects
- Tasks
- Calendar

SALES
- Leads
- Clients
- Pipeline

COMPANY
- Team
- Meetings
- Documents

FINANCE
- Overview
- Income
- Expenses
- Invoices

INSIGHTS
- Reports
- Activity

SETTINGS

## 8. Dashboard

Route: /dashboard

Required:
- Active Projects
- Open Tasks
- Tasks Due Today
- Active Leads
- Pipeline Value
- Monthly Revenue
- Monthly Expenses
- Today's tasks
- Overdue tasks
- Today's meetings
- Follow-ups due
- Project health
- Sales pipeline
- Recent activity
- Quick actions

Quick actions:
- New Lead
- New Client
- New Project
- New Task
- Add Expense
- Create Invoice

## 9. Tasks

Routes:
- /tasks
- /tasks/my
- /tasks/[id]

Statuses:
- TODO
- IN_PROGRESS
- REVIEW
- DONE
- CANCELLED

Priorities:
- LOW
- MEDIUM
- HIGH
- URGENT

Fields:
- id
- title
- description
- status
- priority
- project_id
- assignee_id
- created_by
- due_date
- start_date
- estimated_hours
- actual_hours
- tags
- timestamps

Features:
- list
- Kanban
- drag-and-drop
- comments
- attachments
- checklist/subtasks
- filters
- activity

## 10. Projects

Routes:
- /projects
- /projects/[id]

Fields:
- name
- project_code
- description
- client
- status
- owner
- team
- start_date
- deadline
- budget
- progress
- health
- repository_url
- production_url
- staging_url

Statuses:
- PLANNING
- ACTIVE
- ON_HOLD
- COMPLETED
- CANCELLED

Tabs:
- Overview
- Tasks
- Milestones
- Files
- Meetings
- Activity
- Financials

Health:
- On Track
- At Risk
- Delayed

## 11. CRM Leads

Routes:
- /leads
- /leads/[id]
- /pipeline

Lead fields:
- name
- company
- email
- phone
- source
- service
- estimated_value
- stage
- assigned_to
- next_follow_up
- notes

Sources:
- Website
- Facebook
- LinkedIn
- Referral
- Email
- Phone
- Other

Stages:
- NEW
- CONTACTED
- MEETING
- PROPOSAL
- NEGOTIATION
- WON
- LOST

Pipeline should support drag-and-drop and stage-history events.

## 12. Clients

Routes:
- /clients
- /clients/[id]

Client profile:
- overview
- projects
- invoices
- payments
- meetings
- documents
- activity

Show:
- lifetime revenue
- active projects
- outstanding invoices
- last interaction
- next meeting

## 13. Website Contact Integration

Flow:

trinolit.com contact form
→ secure API
→ create Lead
→ notify TrinolIT
→ send customer confirmation
→ show lead in CRM

Endpoint:
POST /api/public/contact

Fields:
- name
- email
- phone optional
- company optional
- service
- budget
- message

Security:
- rate limiting
- validation
- sanitization
- spam protection
- logging

Notification email:
To: hello@trinolit.com

Customer confirmation:
From: TrinolIT <hello@trinolit.com>

Use responsive HTML email with logo, reference number, message, website link, and contact details.

Never expose SMTP credentials to browser code.

## 14. Meetings

Routes:
- /meetings
- /meetings/[id]

Fields:
- title
- description
- date
- start_time
- end_time
- participants
- related_client
- related_project
- meeting_url
- location
- notes

Tabs/sections:
- Agenda
- Attendees
- Notes
- Decisions
- Action Items

Critical:
Meeting action items can become tasks.

## 15. Google Calendar — V2

Prepare architecture for secure OAuth.

Future flow:
Trinol OS meeting
→ Google Calendar event
→ Google Meet URL
→ external event ID stored

Do not use insecure shortcuts.

## 16. Google Drive / Docs — V2

Initially allow external document links.

Later integrate:
- requirements docs
- proposals
- contracts
- meeting notes
- design docs

Do not rebuild Google Docs.

## 17. Team

Routes:
- /team
- /team/[id]

Fields:
- name
- email
- avatar
- role
- job_title
- status
- joined_at

Statuses:
- ACTIVE
- ON_LEAVE
- INACTIVE

Do not build invasive surveillance.

## 18. RBAC

Initial roles:
- OWNER
- ADMIN
- MANAGER
- MEMBER

Backend must enforce authorization.

Avoid scattered role checks.

Use centralized permissions/authorization services.

## 19. Finance

Keep V1 lightweight.

Routes:
- /finance
- /finance/income
- /finance/expenses
- /invoices
- /invoices/[id]

Income:
- amount
- source
- client
- project
- date
- payment_method
- reference
- notes

Expense:
- amount
- category
- description
- vendor
- date
- payment_method
- receipt
- notes

Categories:
- Hosting
- Domains
- Software
- Marketing
- Salary
- Contractor
- Office
- Travel
- Equipment
- Other

Dashboard:
- revenue this month
- expenses this month
- net cash flow
- outstanding invoices
- revenue trend
- expense breakdown

## 20. Invoices

Fields:
- invoice_number
- client
- issue_date
- due_date
- currency
- items
- subtotal
- discount
- tax
- total
- status
- notes

Statuses:
- DRAFT
- SENT
- PARTIALLY_PAID
- PAID
- OVERDUE
- CANCELLED

Example number:
TRI-2026-0001

Generate professional PDF invoices.

Do not allow duplicate invoice numbers.

## 21. Activity System

Events such as:
- TASK_CREATED
- TASK_UPDATED
- TASK_COMPLETED
- PROJECT_CREATED
- PROJECT_STATUS_CHANGED
- LEAD_CREATED
- LEAD_STAGE_CHANGED
- CLIENT_CREATED
- INVOICE_CREATED
- INVOICE_PAID
- MEETING_CREATED

Store:
- actor
- event
- entity_type
- entity_id
- metadata
- timestamp

## 22. Notifications

Examples:
- task assigned
- task due soon
- task overdue
- lead follow-up due
- meeting approaching
- project deadline approaching
- invoice overdue

## 23. Global Search / Command Palette

Shortcut:
CMD/CTRL + K

Search:
- projects
- tasks
- clients
- leads
- team

Quick actions:
- create task
- create lead
- create project
- create client

## 24. Attachments

Use a storage abstraction.

Development:
- local or S3-compatible

Production:
- S3-compatible object storage

Validate:
- file size
- MIME
- extension
- safe filenames

## 25. Data Model

Core entities likely include:

User
Organization
Membership
Role
Permission
Client
Lead
Project
ProjectMember
Milestone
Task
TaskAssignee
TaskComment
TaskAttachment
TaskChecklistItem
Meeting
MeetingParticipant
MeetingDecision
MeetingAction
Income
Expense
Invoice
InvoiceItem
Payment
Notification
ActivityEvent
DocumentReference
ContactSubmission
RefreshSession

Analyze relationships before implementing.

Use:
- UUIDs where appropriate
- foreign keys
- indexes
- unique constraints
- check constraints
- timestamps

Avoid N+1 queries.

## 26. Multi-Tenancy Readiness

Organization should be a first-class concept from day one.

Business data should be organization-scoped.

Do not introduce unnecessary enterprise complexity, but do not create a design that requires rewriting every query later.

## 27. Security

Implement:
- secure auth
- password hashing
- session management
- refresh-token rotation if JWT architecture is selected
- CSRF protection where relevant
- CORS policy
- rate limiting
- secure cookies
- validation
- authorization
- safe uploads
- security headers
- secrets management

Never:
- commit secrets
- expose SMTP credentials
- expose database credentials
- log passwords
- log auth tokens
- trust frontend authorization

## 28. Audit Log

Audit sensitive actions:
- role changed
- member removed
- invoice cancelled/deleted
- lead converted
- project deleted
- payment recorded
- security settings changed

Audit entries should not be casually editable.

## 29. Email System

Create EmailService abstraction.

Development:
- log/sandbox adapter

Production:
- Hostinger SMTP initially

Environment variables:
SMTP_HOST
SMTP_PORT
SMTP_USERNAME
SMTP_PASSWORD
SMTP_FROM_EMAIL
SMTP_FROM_NAME

Example:
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USERNAME=hello@trinolit.com
SMTP_FROM_EMAIL=hello@trinolit.com
SMTP_FROM_NAME=TrinolIT

Templates:
- contact confirmation
- new lead notification
- task assignment
- meeting reminder
- invoice email
- password reset
- email verification

## 30. AI — Later

Do not make V1 dependent on an LLM.

Future:
- executive assistant
- meeting summarization
- task extraction
- proposal generation
- email drafting
- lead scoring
- project risk detection
- RAG over company knowledge
- financial insights
- semantic search

Do not let an LLM calculate authoritative financial totals.

## 31. Analytics

V1:
- project completion
- task completion
- overdue tasks
- pipeline value
- lead conversion
- revenue
- expenses

Later:
- conversion by source
- average project duration
- revenue/client
- revenue/service
- project profitability
- workload
- forecasting

## 32. Responsive Design

Support:
- desktop
- laptop
- tablet
- mobile

Mobile priorities:
- My Tasks
- Today's meetings
- Notifications
- Lead follow-ups
- Quick actions

## 33. Accessibility

Target WCAG AA where practical.

Support:
- keyboard navigation
- visible focus
- semantic HTML
- ARIA where needed
- labels
- sufficient contrast
- reduced motion

## 34. Error Handling

Backend format example:

{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task not found",
    "request_id": "..."
  }
}

Frontend should show useful errors, not raw 500s.

## 35. Observability

Structured logs:
- request_id
- user_id where safe
- organization_id
- endpoint
- status
- latency

Health endpoints:
- /health
- /ready

## 36. Seed Data

Seed realistic data:
- Founder
- Developer
- Designer
- 3–5 clients
- TrinolIT Website project
- Example client project
- Internal product
- 20+ tasks
- 10+ leads
- invoices
- expenses
- past/upcoming meetings

Avoid lorem ipsum.

## 37. Testing

Unit:
- business logic
- authorization
- financial calculations
- project progress
- invoice math

Integration:
- auth
- database
- RBAC
- leads
- tasks
- invoices
- contact submission

E2E:
- login
- create lead
- convert lead
- create project
- create task
- move task
- create client
- create invoice

Security tests:
- unauthorized resources
- privilege escalation
- unauthenticated access
- cross-org isolation

## 38. Documentation

Maintain:
- README.md
- ROADMAP.md
- CHANGELOG.md

Architecture docs:
- ARCHITECTURE.md
- DATABASE.md
- AUTH.md
- RBAC.md
- EMAIL.md
- DEPLOYMENT.md
- SECURITY.md

ADRs for major decisions.

## 39. Development Phases

### Phase 0 — Discovery / Architecture
Before product code:
1. inspect repo
2. analyze requirements
3. identify ambiguity
4. identify overengineering
5. design architecture
6. design ERD
7. auth
8. RBAC
9. frontend architecture
10. API conventions
11. testing
12. deployment
13. ADRs
14. roadmap

STOP after Phase 0 and present findings.

### Phase 1 — Foundation
- monorepo
- FastAPI
- Next.js
- PostgreSQL
- Alembic
- auth
- organization
- users
- membership
- RBAC
- app shell
- dashboard shell
- Docker
- CI
- testing foundation

### Phase 2 — Projects + Tasks
- projects
- tasks
- Kanban
- milestones
- project members
- comments
- activity
- dashboard widgets

### Phase 3 — CRM
- leads
- pipeline
- clients
- follow-ups
- lead conversion
- contact endpoint
- email notifications

### Phase 4 — Meetings + Calendar
- meetings
- notes
- decisions
- action items
- action → task
- Google Calendar if justified

### Phase 5 — Finance
- income
- expenses
- invoices
- payments
- PDF invoices
- finance dashboard

### Phase 6 — Documents + Integrations
- document references
- Google Drive
- GitHub integration
- useful integrations only

### Phase 7 — Analytics
- company
- project
- sales
- finance

### Phase 8 — AI
Only after enough real company data exists.

Start with meeting summary/action extraction.

## 40. Working Rules

- Never build everything in one pass.
- Plan before implementation.
- Read existing code first.
- Do not rewrite working architecture without justification.
- Verify features.
- Run lint/typecheck/tests/build.
- Fix root causes.
- Do not disable checks to pass CI.
- Avoid unnecessary any.
- Avoid giant components.
- Backend owns business rules.
- Use DB constraints for invariants.
- Do not delete data to solve dev problems.
- Do not fabricate tests.
- Do not install libraries without reason.
- Keep ROADMAP.md current.
- Track technical debt.
- Do not silently change requirements.

## 41. UX Quality Gate

For every major page ask:
- what is the user's main goal?
- can it be done quickly?
- what if there is no data?
- what while loading?
- what on API failure?
- what on mobile?
- what with 1 item?
- what with 1,000 items?
- keyboard usable?
- destructive actions obvious?
- clear success feedback?

## 42. Performance

Avoid:
- unnecessary client components
- massive JS bundles
- unbounded queries
- N+1 queries
- fetching entire tables
- unoptimized images
- unnecessary rerenders

Use:
- pagination
- server components where appropriate
- indexes
- query optimization
- caching only when justified
- lazy loading

## 43. Definition of Done

A feature is complete only when:
- UI
- backend
- validation
- authorization
- persistence
- errors
- loading
- empty states
- responsive behavior
- tests
- passing lint
- passing typecheck
- passing build
- updated docs

## 44. First Command

Begin with Phase 0 only.

Do not implement Phase 1 yet.

Inspect the repository, design architecture and ERD, auth, RBAC, org isolation, API conventions, frontend, testing, deployment, security risks, V1 scope, roadmap, and ADRs.

Stop after Phase 0 and wait for approval.
