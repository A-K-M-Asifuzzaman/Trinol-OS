# Trinol OS — Email

## 1. Abstraction

```python
class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...
```

Three implementations, selected by `EMAIL_BACKEND`:

| Backend | Use | Behaviour |
|---|---|---|
| `console` | local dev, default | renders and logs the message, sends nothing |
| `memory` | tests | appends to a list the test asserts against |
| `smtp` | staging + production | Hostinger SMTP over implicit TLS |

No provider SDK. `aiosmtplib` plus stdlib `email.message` covers this
completely; a transactional-email vendor gets added when deliverability
actually becomes a problem, and the Protocol is where that plugs in.

## 2. Configuration

```
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USERNAME=hello@trinolit.com
SMTP_PASSWORD=            # secret, injected by the deployment
SMTP_FROM_EMAIL=hello@trinolit.com
SMTP_FROM_NAME=TrinolIT
```

Port 465 is implicit TLS (`use_tls=True`), not STARTTLS — a common
misconfiguration that fails silently into an unencrypted session on some
clients. Certificate verification is never disabled.

Credentials are read once at startup into the settings object, never logged,
never exposed to the browser, never prefixed `NEXT_PUBLIC_`.

## 3. Sending discipline

- Email is sent **after** the database transaction commits, from a FastAPI
  background task. A mail failure must never roll back a lead, an invoice or a
  task assignment.
- Every send is wrapped: failures are logged with the template name and
  recipient domain, and never surface as a 500 to the user.
- Retries: one immediate retry on a transient SMTP error, then give up and log.
  `ponytail: no persistent outbox in V1 — add one when a lost email actually
  costs something, i.e. when invoice delivery goes live in Phase 5.`
- Non-production environments refuse to send to any address outside an
  allowlist, so a seeded database can never mail a real client.

## 4. Templates

Jinja2, one directory, each template as an HTML file plus a plain-text
counterpart. Multipart `alternative` on every message — HTML-only mail is a
spam signal.

Phase 1: invitation. (Password reset and email verification are sent by
Firebase — see [ADR-0013](../adr/0013-firebase-as-identity-provider.md) — and
are not our templates. Firebase's sender domain should be customized to
`trinolit.com` so those mails match the rest.)
Phase 3: contact confirmation, new-lead notification.
Phase 2/4: task assignment, meeting reminder.
Phase 5: invoice email.

House style: single-column, max 600 px, table-based layout, inlined CSS, logo at
top, plain footer with the company address and website. No web fonts, no
background images, no dark-mode-only colours — mail clients break all three.

Every interpolated value is autoescaped. Any user-controlled value used in a
header (subject, display name) has CR/LF stripped, which closes header
injection.

## 5. Contact flow (Phase 3)

```
POST /api/public/contact
  → store contact_submission (raw, with IP)
  → create Lead
  → commit
  → notify hello@trinolit.com          "New lead: {name} — {service}"
  → confirm to the customer            "We received your message — ref TRI-C-0042"
```

The confirmation carries the reference number, an echo of their message, the
website link and contact details. `Reply-To` is set to `hello@trinolit.com`.
The customer's address is never used as the `From`.

## 6. Deliverability

SPF, DKIM and a `p=none` DMARC record are configured for the sending domain
before the first production send, and DMARC is tightened once reports are clean.
Bounce handling is out of V1 scope.
