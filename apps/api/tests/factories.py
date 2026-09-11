from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.ids import uuid7
from trinol.modules.crm.models import Client, ClientStatus, Lead, LeadSource, LeadStage
from trinol.modules.documents.models import DocumentKind, DocumentReference
from trinol.modules.finance.models import (
    Expense,
    ExpenseCategory,
    Income,
    Invoice,
    InvoiceItem,
    InvoiceStatus,
    Payment,
)
from trinol.modules.identity.models import (
    AuthProvider,
    Invitation,
    Membership,
    MembershipStatus,
    Organization,
    User,
)
from trinol.modules.meetings.models import (
    Meeting,
    MeetingAction,
    MeetingDecision,
    MeetingParticipant,
    MeetingParticipantResponse,
)
from trinol.modules.work.models import (
    Milestone,
    Project,
    ProjectMember,
    ProjectStatus,
    RoleOnProject,
    Task,
    TaskAttachment,
    TaskChecklistItem,
    TaskComment,
    TaskPriority,
    TaskStatus,
)
from trinol.platform.file_storage.protocol import FileStorage
from trinol.platform.files import create_file_object

# Plain factory functions, not factory_boy (TESTING.md §2): each adds+flushes
# a row and returns it, so a caller can chain them without repeating
# boilerplate.


async def make_organization(
    db: AsyncSession, *, name: str = "Test Org", slug: str | None = None
) -> Organization:
    org = Organization(id=uuid7(), name=name, slug=slug or f"test-org-{uuid7()}")
    db.add(org)
    await db.flush()
    return org


async def make_user(
    db: AsyncSession,
    *,
    email: str = "user@example.com",
    firebase_uid: str | None = None,
    auth_provider: AuthProvider = AuthProvider.PASSWORD,
    full_name: str = "Test User",
) -> User:
    user = User(
        id=uuid7(),
        firebase_uid=firebase_uid or f"fb-{uuid7()}",
        email=email,
        auth_provider=auth_provider,
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def make_membership(
    db: AsyncSession,
    *,
    organization: Organization,
    user: User,
    role: Role = Role.MEMBER,
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> Membership:
    membership = Membership(
        id=uuid7(),
        organization_id=organization.id,
        user_id=user.id,
        role=role,
        status=status,
    )
    db.add(membership)
    await db.flush()
    return membership


async def make_invitation(
    db: AsyncSession,
    *,
    organization: Organization,
    email: str,
    invited_by: User,
    role: Role = Role.MEMBER,
    expires_in: timedelta = timedelta(days=7),
    token_hash: str | None = None,
) -> Invitation:
    invitation = Invitation(
        id=uuid7(),
        organization_id=organization.id,
        email=email,
        role=role,
        token_hash=token_hash or f"tok-{uuid7()}",
        invited_by=invited_by.id,
        expires_at=datetime.now(UTC) + expires_in,
    )
    db.add(invitation)
    await db.flush()
    return invitation


async def make_project(
    db: AsyncSession,
    *,
    organization: Organization,
    owner: Membership,
    project_code: str | None = None,
    name: str = "Test Project",
    status: ProjectStatus = ProjectStatus.PLANNING,
) -> Project:
    project = Project(
        id=uuid7(),
        organization_id=organization.id,
        project_code=project_code or f"P-{uuid7()}",
        name=name,
        status=status,
        owner_id=owner.user_id,
    )
    db.add(project)
    await db.flush()
    # Mirrors project_service.create_project's invariant: the owner is
    # always a project_members row (LEAD) — ensure_project_visible relies
    # on this being true for every project, not just ones created through
    # the API.
    db.add(
        ProjectMember(
            id=uuid7(),
            organization_id=organization.id,
            project_id=project.id,
            user_id=owner.user_id,
            role_on_project=RoleOnProject.LEAD,
        )
    )
    await db.flush()
    return project


async def make_client(
    db: AsyncSession,
    *,
    organization: Organization,
    name: str = "Test Client",
    email: str | None = None,
    owner: Membership | None = None,
    status: ClientStatus = ClientStatus.ACTIVE,
) -> Client:
    client = Client(
        id=uuid7(),
        organization_id=organization.id,
        name=name,
        email=email,
        status=status,
        owner_id=owner.user_id if owner is not None else None,
    )
    db.add(client)
    await db.flush()
    return client


async def make_lead(
    db: AsyncSession,
    *,
    organization: Organization,
    name: str = "Test Lead",
    email: str | None = "lead@x.com",
    phone: str | None = None,
    source: LeadSource = LeadSource.WEBSITE,
    stage: LeadStage = LeadStage.NEW,
    assigned_to: Membership | None = None,
    board_position: Decimal | None = None,
    estimated_value: Decimal | None = None,
    next_follow_up: date | None = None,
) -> Lead:
    lead = Lead(
        id=uuid7(),
        organization_id=organization.id,
        name=name,
        email=email,
        phone=phone,
        source=source,
        currency="USD",
        stage=stage,
        assigned_to=assigned_to.user_id if assigned_to is not None else None,
        estimated_value=estimated_value,
        next_follow_up=next_follow_up,
        **({"board_position": board_position} if board_position is not None else {}),
    )
    db.add(lead)
    await db.flush()
    return lead


async def make_project_member(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    role_on_project: RoleOnProject = RoleOnProject.CONTRIBUTOR,
) -> ProjectMember:
    member = ProjectMember(
        id=uuid7(),
        organization_id=project.organization_id,
        project_id=project.id,
        user_id=user.id,
        role_on_project=role_on_project,
    )
    db.add(member)
    await db.flush()
    return member


async def make_milestone(
    db: AsyncSession,
    *,
    project: Project,
    name: str = "Test Milestone",
    position: int = 0,
) -> Milestone:
    milestone = Milestone(
        id=uuid7(),
        organization_id=project.organization_id,
        project_id=project.id,
        name=name,
        position=position,
    )
    db.add(milestone)
    await db.flush()
    return milestone


async def make_task(
    db: AsyncSession,
    *,
    organization: Organization,
    created_by: Membership,
    project: Project | None = None,
    assignee: Membership | None = None,
    title: str = "Test Task",
    status: TaskStatus = TaskStatus.TODO,
    priority: TaskPriority = TaskPriority.MEDIUM,
    board_position: Decimal | None = None,
) -> Task:
    task = Task(
        id=uuid7(),
        organization_id=organization.id,
        project_id=project.id if project is not None else None,
        title=title,
        status=status,
        priority=priority,
        assignee_id=assignee.user_id if assignee is not None else None,
        created_by=created_by.user_id,
        completed_at=datetime.now(UTC) if status == TaskStatus.DONE else None,
        **({"board_position": board_position} if board_position is not None else {}),
    )
    db.add(task)
    await db.flush()
    return task


async def make_task_comment(
    db: AsyncSession, *, task: Task, author: User, body: str = "Test comment"
) -> TaskComment:
    comment = TaskComment(
        id=uuid7(),
        organization_id=task.organization_id,
        task_id=task.id,
        author_id=author.id,
        body=body,
    )
    db.add(comment)
    await db.flush()
    return comment


async def make_checklist_item(
    db: AsyncSession, *, task: Task, label: str = "Test item", position: int = 0
) -> TaskChecklistItem:
    item = TaskChecklistItem(
        id=uuid7(),
        organization_id=task.organization_id,
        task_id=task.id,
        label=label,
        position=position,
    )
    db.add(item)
    await db.flush()
    return item


# A minimal, valid PNG (the smallest possible: 1x1 transparent pixel) so
# tests exercise the real sniff-and-validate path (platform/files.py)
# instead of bypassing it.
PNG_1X1_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415478da6360606060000000050001a5f645400000000049454e44ae426082"
)


async def make_meeting(
    db: AsyncSession,
    *,
    organization: Organization,
    created_by: Membership,
    title: str = "Test Meeting",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    client: Client | None = None,
    project: Project | None = None,
) -> Meeting:
    starts = starts_at or datetime.now(UTC)
    meeting = Meeting(
        id=uuid7(),
        organization_id=organization.id,
        title=title,
        starts_at=starts,
        ends_at=ends_at or starts + timedelta(hours=1),
        client_id=client.id if client is not None else None,
        project_id=project.id if project is not None else None,
        created_by=created_by.user_id,
    )
    db.add(meeting)
    await db.flush()
    return meeting


async def make_meeting_participant(
    db: AsyncSession,
    *,
    meeting: Meeting,
    user: Membership | None = None,
    external_email: str | None = None,
    response: MeetingParticipantResponse = MeetingParticipantResponse.PENDING,
) -> MeetingParticipant:
    participant = MeetingParticipant(
        id=uuid7(),
        organization_id=meeting.organization_id,
        meeting_id=meeting.id,
        user_id=user.user_id if user is not None else None,
        external_email=external_email if user is None else None,
        response=response,
    )
    db.add(participant)
    await db.flush()
    return participant


async def make_meeting_decision(
    db: AsyncSession,
    *,
    meeting: Meeting,
    decided_by: Membership | None = None,
    body: str = "Test decision",
) -> MeetingDecision:
    decision = MeetingDecision(
        id=uuid7(),
        organization_id=meeting.organization_id,
        meeting_id=meeting.id,
        body=body,
        decided_by=decided_by.user_id if decided_by is not None else None,
    )
    db.add(decision)
    await db.flush()
    return decision


async def make_meeting_action(
    db: AsyncSession,
    *,
    meeting: Meeting,
    owner: Membership | None = None,
    description: str = "Test action",
    due_date: date | None = None,
    task_id: uuid.UUID | None = None,
) -> MeetingAction:
    action = MeetingAction(
        id=uuid7(),
        organization_id=meeting.organization_id,
        meeting_id=meeting.id,
        description=description,
        owner_id=owner.user_id if owner is not None else None,
        due_date=due_date,
        task_id=task_id,
    )
    db.add(action)
    await db.flush()
    return action


async def make_task_attachment(
    db: AsyncSession,
    *,
    task: Task,
    uploaded_by: Membership,
    storage: FileStorage,
    filename: str = "receipt.png",
    data: bytes = PNG_1X1_BYTES,
) -> TaskAttachment:
    """Uses the real upload path (platform.files.create_file_object), not a
    bare row insert — `storage` must be a real `FileStorage` (e.g.
    `LocalFileStorage(tmp_path)`) so `download_attachment`'s later
    `storage.get()` finds real bytes, not a phantom key."""
    file_object = await create_file_object(
        db,
        organization_id=task.organization_id,
        uploaded_by=uploaded_by.user_id,
        filename=filename,
        data=data,
        storage=storage,
    )
    attachment = TaskAttachment(
        id=uuid7(),
        organization_id=task.organization_id,
        task_id=task.id,
        file_id=file_object.id,
        uploaded_by=uploaded_by.user_id,
    )
    db.add(attachment)
    await db.flush()
    return attachment


async def make_invoice(
    db: AsyncSession,
    *,
    organization: Organization,
    client: Client,
    created_by: Membership,
    project: Project | None = None,
    invoice_number: str | None = None,
    issue_date: date | None = None,
    due_date: date | None = None,
    subtotal: Decimal = Decimal("100.00"),
    discount_amount: Decimal = Decimal("0"),
    tax_amount: Decimal = Decimal("0"),
    status: InvoiceStatus = InvoiceStatus.DRAFT,
) -> Invoice:
    """`total` is derived here the same way the service always derives it
    (`ck_invoice_total` would reject anything else) — a factory bypassing
    invoice_service.create_invoice still has to satisfy the DB invariant."""
    issued = issue_date or date.today()
    invoice = Invoice(
        id=uuid7(),
        organization_id=organization.id,
        invoice_number=invoice_number or f"TRI-TEST-{uuid7()}",
        client_id=client.id,
        project_id=project.id if project is not None else None,
        issue_date=issued,
        due_date=due_date or issued + timedelta(days=14),
        subtotal=subtotal,
        discount_amount=discount_amount,
        tax_amount=tax_amount,
        total=subtotal - discount_amount + tax_amount,
        status=status,
        created_by=created_by.user_id,
    )
    db.add(invoice)
    await db.flush()
    return invoice


async def make_invoice_item(
    db: AsyncSession,
    *,
    invoice: Invoice,
    description: str = "Test line item",
    quantity: Decimal = Decimal("1.000"),
    unit_price: Decimal = Decimal("100.00"),
    position: int = 0,
) -> InvoiceItem:
    item = InvoiceItem(
        id=uuid7(),
        organization_id=invoice.organization_id,
        invoice_id=invoice.id,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        line_total=round(quantity * unit_price, 2),
        position=position,
    )
    db.add(item)
    await db.flush()
    return item


async def make_payment(
    db: AsyncSession,
    *,
    invoice: Invoice,
    recorded_by: Membership,
    amount: Decimal = Decimal("50.00"),
    paid_on: date | None = None,
    method: str = "bank_transfer",
) -> Payment:
    payment = Payment(
        id=uuid7(),
        organization_id=invoice.organization_id,
        invoice_id=invoice.id,
        amount=amount,
        paid_on=paid_on or date.today(),
        method=method,
        recorded_by=recorded_by.user_id,
    )
    db.add(payment)
    await db.flush()
    return payment


async def make_income(
    db: AsyncSession,
    *,
    organization: Organization,
    created_by: Membership,
    amount: Decimal = Decimal("100.00"),
    source: str = "Test income",
    client: Client | None = None,
    project: Project | None = None,
    invoice: Invoice | None = None,
    received_on: date | None = None,
    payment_method: str = "bank_transfer",
) -> Income:
    income = Income(
        id=uuid7(),
        organization_id=organization.id,
        amount=amount,
        source=source,
        client_id=client.id if client is not None else None,
        project_id=project.id if project is not None else None,
        invoice_id=invoice.id if invoice is not None else None,
        received_on=received_on or date.today(),
        payment_method=payment_method,
        created_by=created_by.user_id,
    )
    db.add(income)
    await db.flush()
    return income


async def make_expense(
    db: AsyncSession,
    *,
    organization: Organization,
    created_by: Membership,
    amount: Decimal = Decimal("50.00"),
    category: ExpenseCategory = ExpenseCategory.SOFTWARE,
    description: str = "Test expense",
    vendor: str | None = None,
    spent_on: date | None = None,
    payment_method: str = "card",
    receipt_file_id: uuid.UUID | None = None,
) -> Expense:
    expense = Expense(
        id=uuid7(),
        organization_id=organization.id,
        amount=amount,
        category=category,
        description=description,
        vendor=vendor,
        spent_on=spent_on or date.today(),
        payment_method=payment_method,
        receipt_file_id=receipt_file_id,
        created_by=created_by.user_id,
    )
    db.add(expense)
    await db.flush()
    return expense


async def make_document_reference(
    db: AsyncSession,
    *,
    organization: Organization,
    added_by: Membership,
    title: str = "Test Document",
    url: str = "https://drive.google.com/test",
    kind: DocumentKind = DocumentKind.GOOGLE_DRIVE,
    project: Project | None = None,
    client: Client | None = None,
    meeting: Meeting | None = None,
) -> DocumentReference:
    document_reference = DocumentReference(
        id=uuid7(),
        organization_id=organization.id,
        title=title,
        url=url,
        kind=kind,
        project_id=project.id if project is not None else None,
        client_id=client.id if client is not None else None,
        meeting_id=meeting.id if meeting is not None else None,
        added_by=added_by.user_id,
    )
    db.add(document_reference)
    await db.flush()
    return document_reference
