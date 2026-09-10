from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.factories import make_client, make_expense, make_income, make_invoice
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.finance.models import ExpenseCategory, InvoiceStatus

pytestmark = pytest.mark.usefixtures("db_session")


def _this_month(day: int = 1) -> date:
    return date.today().replace(day=day)


async def test_admin_can_view_finance_stats(client: AsyncClient, fake_verifier, db_session) -> None:
    """RBAC.md §2: "Finance: view" is ADMIN+-tier only."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    client_row = await make_client(db_session, organization=actor.organization)

    await make_income(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        amount=Decimal("500.00"),
        received_on=_this_month(),
    )
    await make_income(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        amount=Decimal("300.00"),
        received_on=_this_month(),
    )
    await make_expense(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        amount=Decimal("120.00"),
        category=ExpenseCategory.HOSTING,
        spent_on=_this_month(),
    )
    await make_expense(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        amount=Decimal("80.00"),
        category=ExpenseCategory.SOFTWARE,
        spent_on=_this_month(),
    )
    await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        subtotal=Decimal("1000.00"),
        status=InvoiceStatus.SENT,
    )
    await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        subtotal=Decimal("200.00"),
        status=InvoiceStatus.PAID,
    )
    await db_session.commit()

    response = await client.get("/api/v1/finance/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["revenue_this_month"] == "800.00"
    assert body["expenses_this_month"] == "200.00"
    assert body["net_cash_flow"] == "600.00"
    assert body["outstanding_invoices_count"] == 1
    assert body["outstanding_invoices_total"] == "1000.00"

    breakdown = {row["category"]: row["amount"] for row in body["expense_breakdown"]}
    assert breakdown["HOSTING"] == "120.00"
    assert breakdown["SOFTWARE"] == "80.00"

    current_month_key = _this_month().isoformat()
    trend_by_month = {row["month"]: row["amount"] for row in body["revenue_trend"]}
    assert trend_by_month[current_month_key] == "800.00"
    assert len(body["revenue_trend"]) <= 6


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
async def test_member_and_manager_cannot_view_finance_stats(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    await login_as(client, fake_verifier, db_session, role=role)
    response = await client.get("/api/v1/finance/stats")
    assert response.status_code == 403


async def test_finance_stats_with_no_data_are_all_zero(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.get("/api/v1/finance/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["revenue_this_month"] == "0"
    assert body["expenses_this_month"] == "0"
    assert body["net_cash_flow"] == "0"
    assert body["outstanding_invoices_count"] == 0
    assert body["outstanding_invoices_total"] == "0"
    assert body["revenue_trend"] == []
    assert body["expense_breakdown"] == []


async def test_finance_stats_excludes_other_orgs_data(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    await make_income(
        db_session,
        organization=other_actor.organization,
        created_by=other_actor.membership,
        amount=Decimal("999.00"),
        received_on=_this_month(),
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.get("/api/v1/finance/stats")
    assert response.status_code == 200
    assert response.json()["revenue_this_month"] == "0"
