from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import TIMESTAMP, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.errors import ForbiddenError
from trinol.modules.finance.models import Expense, ExpenseCategory, Income, Invoice, InvoiceStatus
from trinol.modules.identity.models import Membership

_OUTSTANDING_STATUSES = (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID)
_TREND_MONTHS = 6


@dataclass(frozen=True, slots=True)
class RevenueTrendPoint:
    month: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ExpenseBreakdownPoint:
    category: ExpenseCategory
    amount: Decimal


@dataclass(frozen=True, slots=True)
class FinanceStats:
    revenue_this_month: Decimal
    expenses_this_month: Decimal
    net_cash_flow: Decimal
    outstanding_invoices_count: int
    outstanding_invoices_total: Decimal
    revenue_trend: list[RevenueTrendPoint]
    expense_breakdown: list[ExpenseBreakdownPoint]


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy of
    this check (e.g. income_service's own copy)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


def _add_months(d: date, delta: int) -> date:
    """Plain month arithmetic — Python's stdlib has no month-add, and a
    `timedelta` can't express "one calendar month" correctly across
    varying month lengths."""
    month_index = d.year * 12 + (d.month - 1) + delta
    year, month = divmod(month_index, 12)
    return date(year, month + 1, 1)


async def get_finance_stats(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership
) -> FinanceStats:
    """MASTER_PROMPT §19's six finance dashboard tiles (ROADMAP.md Phase 5
    decision 5's own exact data sources), mirroring `lead_service.
    get_lead_stats`'s shape: one service function, a handful of aggregate
    queries, a small dataclass. RBAC.md §2: "Finance: view" is ADMIN+-tier
    only (`FINANCE_READ`, enforced at the route) — unlike lead stats, not
    open to every role.

    ponytail: every amount here is summed regardless of `currency` — every
    row in this org's real usage defaults to USD and nothing mixes
    currencies today; a true multi-currency aggregate needs a per-currency
    breakdown or a conversion step, add it if that ever stops being true.
    Same disclaimer `get_lead_stats` already carries for `estimated_value`.

    Revenue trend and expense breakdown use a fixed 6-month/current-month
    window — no user-configurable date range yet, add one if requested."""
    ensure_actor_in_org(actor, organization_id)
    today = date.today()
    month_start = today.replace(day=1)
    next_month_start = _add_months(month_start, 1)

    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0)).where(
            Income.organization_id == organization_id,
            Income.received_on >= month_start,
            Income.received_on < next_month_start,
        )
    )
    revenue_this_month = revenue_result.scalar_one()

    expenses_result = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.organization_id == organization_id,
            Expense.spent_on >= month_start,
            Expense.spent_on < next_month_start,
        )
    )
    expenses_this_month = expenses_result.scalar_one()

    outstanding_result = await db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0),
        ).where(
            Invoice.organization_id == organization_id,
            Invoice.status.in_(_OUTSTANDING_STATUSES),
            Invoice.archived_at.is_(None),
        )
    )
    outstanding_count, outstanding_total = outstanding_result.one()

    trend_start = _add_months(month_start, -(_TREND_MONTHS - 1))
    # date_trunc('month', date) resolves via an implicit cast to
    # timestamptz, truncating in the *session's* timezone — a value
    # computed under one connection's timezone setting then read back
    # through another (e.g. asyncpg's own default) can land on the wrong
    # calendar day entirely (confirmed empirically: a Dhaka-timezone
    # session and a UTC-reading client disagreed by a full day). Casting
    # to a plain (zoneless) timestamp first makes the truncation a pure
    # calendar operation, immune to any session's timezone setting.
    month_expr = func.date_trunc("month", cast(Income.received_on, TIMESTAMP))
    trend_result = await db.execute(
        select(month_expr, func.sum(Income.amount))
        .where(
            Income.organization_id == organization_id,
            Income.received_on >= trend_start,
            Income.received_on < next_month_start,
        )
        .group_by(month_expr)
        .order_by(month_expr)
    )
    revenue_trend = [
        RevenueTrendPoint(month=month.date(), amount=amount) for month, amount in trend_result.all()
    ]

    breakdown_result = await db.execute(
        select(Expense.category, func.sum(Expense.amount))
        .where(
            Expense.organization_id == organization_id,
            Expense.spent_on >= month_start,
            Expense.spent_on < next_month_start,
        )
        .group_by(Expense.category)
        .order_by(Expense.category)
    )
    expense_breakdown = [
        ExpenseBreakdownPoint(category=category, amount=amount)
        for category, amount in breakdown_result.all()
    ]

    return FinanceStats(
        revenue_this_month=revenue_this_month,
        expenses_this_month=expenses_this_month,
        net_cash_flow=revenue_this_month - expenses_this_month,
        outstanding_invoices_count=outstanding_count,
        outstanding_invoices_total=outstanding_total,
        revenue_trend=revenue_trend,
        expense_breakdown=expense_breakdown,
    )
