# Codex Phase 0 Architecture Audit Prompt

Read:
- AGENTS.md
- CODEX.md
- MASTER_PROMPT.md
- all Phase 0 architecture documents
- ADRs
- ROADMAP.md

You are acting as an independent principal software architect and adversarial reviewer.

Do NOT implement features.
Do NOT modify files.

Audit Claude's Phase 0 design for Trinol OS.

Review specifically:

1. Domain boundaries
2. PostgreSQL schema
3. Multi-tenancy readiness
4. Organization isolation
5. Authentication/session architecture
6. RBAC and privilege escalation risks
7. API architecture
8. Next.js/FastAPI boundaries
9. Database constraints and indexes
10. Concurrency risks
11. Financial-data correctness
12. Activity/audit architecture
13. File upload security
14. SMTP/email architecture
15. Contact-form abuse/spam risks
16. Testing architecture
17. Deployment architecture
18. Scalability
19. Unnecessary complexity
20. Missing requirements

Classify every finding:

P0 — critical; architecture must not proceed  
P1 — important; fix before implementation  
P2 — improvement  
P3 — optional

For every finding provide:
- problem
- why it matters
- affected files/design
- recommended solution
- evidence

Also identify places where the architecture is overengineered.

At the end provide:

APPROVE

or

BLOCK

If BLOCK, list exactly which P0/P1 findings must be resolved.

Do not modify the repository.
