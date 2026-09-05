# ADR-0007 — Money representation and invoice arithmetic

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §19–20 specifies invoices with subtotal, discount, tax and total,
unique invoice numbers like `TRI-2026-0001`, and payment recording. §30 warns
that an LLM must never compute authoritative financial totals. Financial
correctness is the one area where a bug is not merely embarrassing.

## Decision

**Representation.** `NUMERIC(14,2)` in PostgreSQL, `Decimal` in Python, a
decimal **string** in JSON, plus an explicit 3-letter `currency` on every
monetary row. Never float, anywhere in the stack. `Decimal` context is set
explicitly with `ROUND_HALF_UP`.

Deliberately not a minor-unit integer: `NUMERIC` is exact, is what the database
natively aggregates correctly, and avoids a scaling factor that every reader
must remember. The gain of integer cents is defence against float — already
achieved.

**Totals are computed by the backend, always.** The client sends line items;
subtotal, tax and total are derived server-side and the client's values, if any,
are ignored. Rounding happens once per line
(`line_total = round(quantity × unit_price, 2)`), then lines are summed — not
the reverse.

**The database checks the arithmetic**, so a bad write fails even if it bypasses
the service layer:

```sql
CHECK (total = subtotal - discount_amount + tax_amount)
CHECK (line_total = round(quantity * unit_price, 2))
CHECK (subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0 AND total >= 0)
CHECK (amount_paid >= 0)
```

**Invoice numbers.** `TRI-{year}-{seq:04d}`, sequence from an
`invoice_counters(organization_id, year)` row taken with `SELECT … FOR UPDATE`
inside the invoice's transaction, backed by
`UNIQUE (organization_id, invoice_number)`. A sequence generator alone is
rejected: it does not reset per year and leaves gaps on rollback, both of which
matter to accountants.

**Immutability.** A `DRAFT` invoice is freely editable. Once `SENT`, financial
fields are frozen; corrections are a credit note or a cancellation, never a
silent edit. Cancellation is a status change with an audit event, never a
delete.

**`OVERDUE` is derived**, not stored: `status IN (SENT, PARTIALLY_PAID) AND
due_date < today`. No nightly job to run, to monitor, or to forget.

**Payments** are append-only rows. `amount_paid` is recomputed as the sum of
payments inside the same transaction, and the status moves to
`PARTIALLY_PAID` or `PAID` from that sum. Overpayment beyond the total is
rejected with a `409`.

**Multi-currency** is out of V1: one currency per organization, stored per row
so the column does not have to be added later. Cross-currency reporting and
exchange rates are not built.

## Consequences

- Financial invariants survive a bad migration or a manual `psql` session.
- Concurrency on invoice numbering is handled by a row lock, tested by a
  concurrent-creation test.
- Tests must include values that expose rounding (`33.33 × 3`, 3-decimal
  quantities, a discount larger than a line).
