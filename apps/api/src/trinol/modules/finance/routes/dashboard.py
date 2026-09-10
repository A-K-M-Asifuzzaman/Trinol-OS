from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.finance.schemas import (
    ExpenseBreakdownPointResponse,
    FinanceStatsResponse,
    RevenueTrendPointResponse,
)
from trinol.modules.finance.services.dashboard_service import get_finance_stats
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

# Its own router, not nested under income/expenses/invoices — the stats
# aggregate spans all three entities, same reasoning leads/pipeline.py's
# GET /leads/stats gets its own static route rather than living under a
# single entity's own prefix.
router = APIRouter(prefix="/api/v1/finance", tags=["finance"])


@router.get(
    "/stats",
    response_model=FinanceStatsResponse,
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def get_finance_stats_route(
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> FinanceStatsResponse:
    stats = await get_finance_stats(
        db, organization_id=membership.organization_id, actor=membership
    )
    return FinanceStatsResponse(
        revenue_this_month=stats.revenue_this_month,
        expenses_this_month=stats.expenses_this_month,
        net_cash_flow=stats.net_cash_flow,
        outstanding_invoices_count=stats.outstanding_invoices_count,
        outstanding_invoices_total=stats.outstanding_invoices_total,
        revenue_trend=[
            RevenueTrendPointResponse(month=p.month, amount=p.amount) for p in stats.revenue_trend
        ],
        expense_breakdown=[
            ExpenseBreakdownPointResponse(category=p.category, amount=p.amount)
            for p in stats.expense_breakdown
        ],
    )
