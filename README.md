# Trinol OS

Trinol OS is TrinolIT's internal company operating system.

The first goal is to help TrinolIT manage:
- projects
- tasks
- leads
- clients
- meetings
- finance
- documents
- team activity

The long-term goal is to evolve it into a SaaS product for software agencies, startups, service companies, and SMEs.

## Agent Workflow

Shared instructions:
- AGENTS.md

Claude Code:
- CLAUDE.md
- PHASE_0_PROMPT.md
- CLAUDE_REVIEW_RESOLUTION.md

Codex:
- CODEX.md
- CODEX_PHASE_0_AUDIT.md
- CODEX_PHASE_REVIEW_TEMPLATE.md

Product specification:
- MASTER_PROMPT.md

Roadmap:
- ROADMAP.md

## Recommended Workflow

1. Claude executes Phase 0 only.
2. Codex audits Phase 0.
3. Claude resolves valid P0/P1 findings.
4. Codex verifies.
5. Only then begin Phase 1.
6. Repeat the builder → reviewer → fix → verify loop for every phase.

Do not let Claude and Codex modify the same working tree simultaneously unless you are using isolated Git worktrees/branches.
