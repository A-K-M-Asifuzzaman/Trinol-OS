from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.modules.identity.models import Membership, MembershipStatus, Organization
from trinol.modules.identity.services.session_service import revoke_org_sessions

# RBAC.md §5's six escalation guards. #6 (activity events for role changes
# and removals) is a Stage 7 retrofit, same as exchange_session's — see
# ROADMAP.md Phase 1 Stage 7; platform/activity.py doesn't exist yet.


async def _lock_organization(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Guard 4 needs this taken before either function reads the current
    owner count, so two concurrent demotions of different owners can't both
    observe "more than one owner remaining" and both proceed."""
    stmt = select(Organization.id).where(Organization.id == organization_id).with_for_update()
    await db.execute(stmt)


async def _get_membership_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, membership_id: uuid.UUID
) -> Membership:
    result = await db.execute(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.id == membership_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        # Not RBAC.md §4's cross-org case specifically, but the same
        # principle: the query is already org-scoped, so a wrong-org id
        # lands here indistinguishably from a genuinely missing one.
        raise NotFoundError("Membership not found")
    return membership


def _ensure_actor_can_act(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, shared by change_role and remove_member: neither
    function may trust that its caller passed a matching (actor,
    organization_id) pair, or that actor already has ADMIN+ — the route-level
    Permission.MEMBER_ROLE_WRITE/MEMBER_REMOVE gate (RBAC.md §2) and
    get_current_membership resolving the org from the session are what make
    that true in practice, but this function has no way to verify either
    happened. A caller bug that passes a mismatched organization_id — e.g.
    from a request body or path param instead of the actor's own session —
    would otherwise let an OWNER of org A operate on org B's memberships."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")
    if actor.role not in (Role.ADMIN, Role.OWNER):
        raise ForbiddenError("Insufficient role to act on organization membership")


async def _ensure_not_last_owner(
    db: AsyncSession, organization_id: uuid.UUID, *, excluding_membership_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.organization_id == organization_id,
            Membership.role == Role.OWNER,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.id != excluding_membership_id,
        )
    )
    if result.scalar_one() == 0:
        raise ForbiddenError("Cannot demote, remove, or deactivate the last remaining OWNER")


async def change_role(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    target_membership_id: uuid.UUID,
    new_role: Role,
) -> Membership:
    _ensure_actor_can_act(actor, organization_id)

    await _lock_organization(db, organization_id)
    target = await _get_membership_in_org(
        db, organization_id=organization_id, membership_id=target_membership_id
    )

    if target.user_id == actor.user_id:
        raise ForbiddenError("You cannot change your own role")  # guard 1
    if new_role in (Role.OWNER, Role.ADMIN) and actor.role != Role.OWNER:
        raise ForbiddenError("Only an OWNER may grant OWNER or ADMIN")  # guard 2
    if actor.role == Role.ADMIN and target.role in (Role.OWNER, Role.ADMIN):
        raise ForbiddenError("An ADMIN may not modify an OWNER or another ADMIN")  # guard 3
    if target.role == Role.OWNER and new_role != Role.OWNER:
        await _ensure_not_last_owner(  # guard 4
            db, organization_id, excluding_membership_id=target.id
        )

    target.role = new_role
    await revoke_org_sessions(  # guard 5
        db, organization_id=organization_id, user_id=target.user_id
    )
    await db.commit()
    return target


async def remove_member(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    target_membership_id: uuid.UUID,
) -> Membership:
    """ "Remove" is deactivation, never a delete (DATABASE.md §5.2) —
    memberships are never deleted by any product flow."""
    _ensure_actor_can_act(actor, organization_id)

    await _lock_organization(db, organization_id)
    target = await _get_membership_in_org(
        db, organization_id=organization_id, membership_id=target_membership_id
    )

    if target.user_id == actor.user_id:
        # Not literally one of RBAC.md §5's six numbered guards, but the same
        # spirit as guard 1: self-service removal through an ADMIN-gated
        # action invites exactly the kind of accidental self-lockout guard 1
        # exists to prevent, and nothing in the spec asks for a "leave org"
        # feature this would otherwise double as.
        raise ForbiddenError("You cannot remove yourself")
    if actor.role == Role.ADMIN and target.role in (Role.OWNER, Role.ADMIN):
        raise ForbiddenError("An ADMIN may not remove an OWNER or another ADMIN")  # guard 3
    if target.role == Role.OWNER:
        await _ensure_not_last_owner(  # guard 4
            db, organization_id, excluding_membership_id=target.id
        )

    target.status = MembershipStatus.INACTIVE
    await revoke_org_sessions(  # guard 5
        db, organization_id=organization_id, user_id=target.user_id
    )
    await db.commit()
    return target
