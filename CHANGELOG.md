# Changelog

All notable changes to Trinol OS. Format loosely follows Keep a Changelog.

## [Unreleased]

### Added — Phase 0 (architecture only, no product code)
- Architecture docs: ARCHITECTURE, DATABASE, AUTH, RBAC, SECURITY, EMAIL,
  TESTING, DEPLOYMENT.
- 13 ADRs covering stack, sessions, organization isolation, authorization,
  API conventions, activity/audit, money, storage, deployment, omitted
  infrastructure, soft delete, V1 scope trims, and Firebase as identity provider.
- V1 scope document and roadmap with per-phase exit criteria and a technical
  debt ledger.

### Changed — Phase 0 audit resolution
- Documented composite organization-scoped foreign keys for cross-tenant
  relationship integrity.
- Specified atomic PostgreSQL rate-limit updates.
- Removed persisted `OVERDUE` invoice status and required invoice-row locking
  for concurrent payment recording.
- Made invited-user provisioning and invitation consumption one locked
  transaction.
