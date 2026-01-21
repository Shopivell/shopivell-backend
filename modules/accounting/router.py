# modules/accounting/router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from datetime import datetime, date, timedelta
from uuid import UUID
from calendar import monthrange

from database import get_db
from dependencies import get_current_user, CurrentUser
from modules.stores.models import Store

from .models import (
    Account, AccountType, AccountSubtype, NormalBalance,
    JournalEntry, JournalEntryStatus, JournalEntrySource, JournalEntryLine,
    Expense, ExpenseStatus, ExpenseCategory,
    FiscalYear, FiscalPeriod, FiscalPeriodStatus
)
from .schemas import (
    AccountCreate, AccountUpdate, AccountResponse, AccountListResponse,
    JournalEntryCreate, JournalEntryResponse, JournalEntryListResponse,
    JournalEntryLineResponse, PostJournalEntryRequest, VoidJournalEntryRequest,
    ExpenseCategoryCreate, ExpenseCategoryUpdate, ExpenseCategoryResponse,
    ExpenseCreate, ExpenseUpdate, ExpenseResponse, ExpenseListResponse,
    FiscalYearCreate, FiscalYearResponse, FiscalPeriodResponse, ClosePeriodRequest,
    IncomeStatementResponse, IncomeStatementSection, IncomeStatementLineItem,
    BalanceSheetResponse, BalanceSheetSection,
    CashFlowResponse, CashFlowSection,
    SalesReportResponse, SalesReportItem,
    GeneralLedgerResponse, LedgerEntry,
    AccountingDashboardResponse,
    AccountTypeEnum, NormalBalanceEnum
)

accounting_router = APIRouter()
API_PREFIX = '/v1/api/accounting'


# ============ Helper Functions ============

def get_normal_balance(account_type: AccountType) -> NormalBalance:
    """Determine normal balance based on account type"""
    if account_type in [AccountType.ASSET, AccountType.EXPENSE]:
        return NormalBalance.DEBIT
    return NormalBalance.CREDIT


def generate_entry_number(db: Session) -> str:
    """Generate unique journal entry number"""
    count = db.query(func.count(JournalEntry.id)).scalar() or 0
    return f"JE-{count + 1:06d}"


def generate_expense_number(db: Session) -> str:
    """Generate unique expense number"""
    count = db.query(func.count(Expense.id)).scalar() or 0
    return f"EXP-{count + 1:06d}"


DEFAULT_ACCOUNTS = [
    # Assets
    {"code": "1000", "name": "Cash", "type": AccountType.ASSET, "subtype": AccountSubtype.CASH},
    {"code": "1010", "name": "Bank Account", "type": AccountType.ASSET, "subtype": AccountSubtype.BANK},
    {"code": "1100", "name": "Accounts Receivable", "type": AccountType.ASSET, "subtype": AccountSubtype.ACCOUNTS_RECEIVABLE},
    {"code": "1200", "name": "Inventory", "type": AccountType.ASSET, "subtype": AccountSubtype.INVENTORY},
    # Liabilities
    {"code": "2000", "name": "Accounts Payable", "type": AccountType.LIABILITY, "subtype": AccountSubtype.ACCOUNTS_PAYABLE},
    {"code": "2100", "name": "Tax Payable", "type": AccountType.LIABILITY, "subtype": AccountSubtype.TAX_PAYABLE},
    # Equity
    {"code": "3000", "name": "Owner's Equity", "type": AccountType.EQUITY, "subtype": AccountSubtype.OWNER_EQUITY},
    {"code": "3100", "name": "Retained Earnings", "type": AccountType.EQUITY, "subtype": AccountSubtype.RETAINED_EARNINGS},
    # Revenue
    {"code": "4000", "name": "Sales Revenue", "type": AccountType.REVENUE, "subtype": AccountSubtype.SALES},
    {"code": "4100", "name": "Service Revenue", "type": AccountType.REVENUE, "subtype": AccountSubtype.SERVICE_REVENUE},
    {"code": "4900", "name": "Sales Returns", "type": AccountType.REVENUE, "subtype": AccountSubtype.SALES_RETURNS},
    # Expenses
    {"code": "5000", "name": "Cost of Goods Sold", "type": AccountType.EXPENSE, "subtype": AccountSubtype.COST_OF_GOODS_SOLD},
    {"code": "6000", "name": "Operating Expenses", "type": AccountType.EXPENSE, "subtype": AccountSubtype.OPERATING_EXPENSE},
    {"code": "6100", "name": "Marketing Expenses", "type": AccountType.EXPENSE, "subtype": AccountSubtype.MARKETING},
    {"code": "6200", "name": "Utilities", "type": AccountType.EXPENSE, "subtype": AccountSubtype.UTILITIES},
    {"code": "6300", "name": "Rent", "type": AccountType.EXPENSE, "subtype": AccountSubtype.RENT},
    {"code": "6400", "name": "Payroll", "type": AccountType.EXPENSE, "subtype": AccountSubtype.PAYROLL},
]


# ============ Account Endpoints ============

@accounting_router.get("/accounts/{store_id}", response_model=AccountListResponse)
async def list_accounts(
    store_id: UUID,
    account_type: Optional[AccountTypeEnum] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List all accounts for a store"""
    query = db.query(Account).filter(Account.store_id == store_id)

    if account_type:
        query = query.filter(Account.account_type == account_type.value)
    if is_active is not None:
        query = query.filter(Account.is_active == is_active)

    accounts = query.order_by(Account.account_code).all()
    return AccountListResponse(accounts=accounts, total=len(accounts))


@accounting_router.post("/accounts/{store_id}", response_model=AccountResponse, status_code=201)
async def create_account(
    store_id: UUID,
    data: AccountCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create a new account"""
    # Check for duplicate code
    existing = db.query(Account).filter(
        Account.store_id == store_id,
        Account.account_code == data.account_code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Account code already exists")

    account = Account(
        store_id=store_id,
        account_code=data.account_code,
        name=data.name,
        description=data.description,
        account_type=data.account_type.value,
        account_subtype=data.account_subtype.value,
        normal_balance=get_normal_balance(AccountType(data.account_type.value)),
        parent_id=data.parent_id
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@accounting_router.post("/accounts/{store_id}/initialize", response_model=AccountListResponse)
async def initialize_default_accounts(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Initialize default chart of accounts for a store"""
    # Check if accounts already exist
    existing_count = db.query(func.count(Account.id)).filter(Account.store_id == store_id).scalar()
    if existing_count > 0:
        raise HTTPException(status_code=400, detail="Store already has accounts. Cannot reinitialize.")

    accounts = []
    for acc_data in DEFAULT_ACCOUNTS:
        account = Account(
            store_id=store_id,
            account_code=acc_data["code"],
            name=acc_data["name"],
            account_type=acc_data["type"],
            account_subtype=acc_data["subtype"],
            normal_balance=get_normal_balance(acc_data["type"]),
            is_system=True
        )
        db.add(account)
        accounts.append(account)

    db.commit()
    for acc in accounts:
        db.refresh(acc)

    return AccountListResponse(accounts=accounts, total=len(accounts))


@accounting_router.get("/accounts/{store_id}/{account_id}", response_model=AccountResponse)
async def get_account(
    store_id: UUID,
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get a specific account"""
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.store_id == store_id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@accounting_router.put("/accounts/{store_id}/{account_id}", response_model=AccountResponse)
async def update_account(
    store_id: UUID,
    account_id: UUID,
    data: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update an account"""
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.store_id == store_id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if data.name is not None:
        account.name = data.name
    if data.description is not None:
        account.description = data.description
    if data.is_active is not None:
        account.is_active = data.is_active
    if data.parent_id is not None:
        account.parent_id = data.parent_id

    db.commit()
    db.refresh(account)
    return account


@accounting_router.delete("/accounts/{store_id}/{account_id}")
async def delete_account(
    store_id: UUID,
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Delete an account (only if no transactions)"""
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.store_id == store_id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if account.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system accounts")

    # Check for journal entries
    has_entries = db.query(JournalEntryLine).filter(JournalEntryLine.account_id == account_id).first()
    if has_entries:
        raise HTTPException(status_code=400, detail="Cannot delete account with transactions. Deactivate it instead.")

    db.delete(account)
    db.commit()
    return {"message": "Account deleted"}


@accounting_router.get("/accounts/{store_id}/{account_id}/ledger", response_model=GeneralLedgerResponse)
async def get_account_ledger(
    store_id: UUID,
    account_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get general ledger for an account"""
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.store_id == store_id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Get opening balance (sum of all entries before start_date)
    opening_entries = db.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0).label('debits'),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0).label('credits')
    ).join(JournalEntry).filter(
        JournalEntryLine.account_id == account_id,
        JournalEntry.entry_date < start_date,
        JournalEntry.status == JournalEntryStatus.POSTED
    ).first()

    opening_balance = float(opening_entries.debits or 0) - float(opening_entries.credits or 0)
    if account.normal_balance == NormalBalance.CREDIT:
        opening_balance = -opening_balance

    # Get entries in period
    entries = db.query(JournalEntryLine, JournalEntry).join(JournalEntry).filter(
        JournalEntryLine.account_id == account_id,
        JournalEntry.entry_date >= start_date,
        JournalEntry.entry_date <= end_date,
        JournalEntry.status == JournalEntryStatus.POSTED
    ).order_by(JournalEntry.entry_date, JournalEntry.entry_number).all()

    ledger_entries = []
    running_balance = opening_balance

    for line, entry in entries:
        if account.normal_balance == NormalBalance.DEBIT:
            running_balance += float(line.debit_amount) - float(line.credit_amount)
        else:
            running_balance += float(line.credit_amount) - float(line.debit_amount)

        ledger_entries.append(LedgerEntry(
            date=entry.entry_date,
            entry_number=entry.entry_number,
            description=line.description or entry.description,
            debit=float(line.debit_amount),
            credit=float(line.credit_amount),
            balance=running_balance
        ))

    return GeneralLedgerResponse(
        account_id=account.id,
        account_code=account.account_code,
        account_name=account.name,
        account_type=AccountTypeEnum(account.account_type.value),
        normal_balance=NormalBalanceEnum(account.normal_balance.value),
        start_date=start_date,
        end_date=end_date,
        opening_balance=opening_balance,
        entries=ledger_entries,
        closing_balance=running_balance
    )


# ============ Journal Entry Endpoints ============

@accounting_router.get("/journal-entries/{store_id}", response_model=JournalEntryListResponse)
async def list_journal_entries(
    store_id: UUID,
    status: Optional[JournalEntryStatus] = None,
    source: Optional[JournalEntrySource] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List journal entries for a store"""
    query = db.query(JournalEntry).filter(JournalEntry.store_id == store_id)

    if status:
        query = query.filter(JournalEntry.status == status)
    if source:
        query = query.filter(JournalEntry.source == source)
    if start_date:
        query = query.filter(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.entry_date <= end_date)

    total = query.count()
    entries = query.order_by(JournalEntry.entry_date.desc(), JournalEntry.entry_number.desc()).offset(offset).limit(limit).all()

    # Load lines with account info
    result_entries = []
    for entry in entries:
        entry_dict = JournalEntryResponse.model_validate(entry).model_dump()
        lines = []
        for line in entry.lines:
            line_dict = JournalEntryLineResponse.model_validate(line).model_dump()
            if line.account:
                line_dict['account_code'] = line.account.account_code
                line_dict['account_name'] = line.account.name
            lines.append(JournalEntryLineResponse(**line_dict))
        entry_dict['lines'] = lines
        result_entries.append(JournalEntryResponse(**entry_dict))

    return JournalEntryListResponse(entries=result_entries, total=total)


@accounting_router.post("/journal-entries/{store_id}", response_model=JournalEntryResponse, status_code=201)
async def create_journal_entry(
    store_id: UUID,
    data: JournalEntryCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create a new journal entry"""
    # Calculate totals
    total_debit = sum(line.debit_amount for line in data.lines)
    total_credit = sum(line.credit_amount for line in data.lines)

    entry = JournalEntry(
        store_id=store_id,
        entry_number=generate_entry_number(db),
        entry_date=data.entry_date,
        description=data.description,
        reference=data.reference,
        source=JournalEntrySource.MANUAL,
        total_debit=total_debit,
        total_credit=total_credit,
        created_by=current_user.id
    )
    db.add(entry)
    db.flush()

    # Add lines
    for idx, line_data in enumerate(data.lines):
        line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=line_data.account_id,
            description=line_data.description,
            debit_amount=line_data.debit_amount,
            credit_amount=line_data.credit_amount,
            line_order=idx
        )
        db.add(line)

    db.commit()
    db.refresh(entry)

    # Return with lines
    entry_dict = JournalEntryResponse.model_validate(entry).model_dump()
    lines = []
    for line in entry.lines:
        line_dict = JournalEntryLineResponse.model_validate(line).model_dump()
        if line.account:
            line_dict['account_code'] = line.account.account_code
            line_dict['account_name'] = line.account.name
        lines.append(JournalEntryLineResponse(**line_dict))
    entry_dict['lines'] = lines

    return JournalEntryResponse(**entry_dict)


@accounting_router.get("/journal-entries/{store_id}/{entry_id}", response_model=JournalEntryResponse)
async def get_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get a specific journal entry"""
    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.store_id == store_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    entry_dict = JournalEntryResponse.model_validate(entry).model_dump()
    lines = []
    for line in entry.lines:
        line_dict = JournalEntryLineResponse.model_validate(line).model_dump()
        if line.account:
            line_dict['account_code'] = line.account.account_code
            line_dict['account_name'] = line.account.name
        lines.append(JournalEntryLineResponse(**line_dict))
    entry_dict['lines'] = lines

    return JournalEntryResponse(**entry_dict)


@accounting_router.post("/journal-entries/{store_id}/{entry_id}/post", response_model=JournalEntryResponse)
async def post_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Post (finalize) a journal entry"""
    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.store_id == store_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.status != JournalEntryStatus.DRAFT:
        raise HTTPException(status_code=400, detail=f"Cannot post entry with status: {entry.status}")

    # Update account balances
    for line in entry.lines:
        account = line.account
        if account.normal_balance == NormalBalance.DEBIT:
            account.current_balance += float(line.debit_amount) - float(line.credit_amount)
        else:
            account.current_balance += float(line.credit_amount) - float(line.debit_amount)

    entry.status = JournalEntryStatus.POSTED
    entry.posted_at = datetime.utcnow()
    entry.posted_by = current_user.id

    db.commit()
    db.refresh(entry)

    entry_dict = JournalEntryResponse.model_validate(entry).model_dump()
    lines = []
    for line in entry.lines:
        line_dict = JournalEntryLineResponse.model_validate(line).model_dump()
        if line.account:
            line_dict['account_code'] = line.account.account_code
            line_dict['account_name'] = line.account.name
        lines.append(JournalEntryLineResponse(**line_dict))
    entry_dict['lines'] = lines

    return JournalEntryResponse(**entry_dict)


@accounting_router.post("/journal-entries/{store_id}/{entry_id}/void", response_model=JournalEntryResponse)
async def void_journal_entry(
    store_id: UUID,
    entry_id: UUID,
    data: VoidJournalEntryRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Void a posted journal entry"""
    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.store_id == store_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.status != JournalEntryStatus.POSTED:
        raise HTTPException(status_code=400, detail=f"Cannot void entry with status: {entry.status}")

    # Reverse account balances
    for line in entry.lines:
        account = line.account
        if account.normal_balance == NormalBalance.DEBIT:
            account.current_balance -= float(line.debit_amount) - float(line.credit_amount)
        else:
            account.current_balance -= float(line.credit_amount) - float(line.debit_amount)

    entry.status = JournalEntryStatus.VOIDED
    entry.voided_at = datetime.utcnow()
    entry.voided_by = current_user.id
    entry.void_reason = data.reason

    db.commit()
    db.refresh(entry)

    entry_dict = JournalEntryResponse.model_validate(entry).model_dump()
    lines = []
    for line in entry.lines:
        line_dict = JournalEntryLineResponse.model_validate(line).model_dump()
        if line.account:
            line_dict['account_code'] = line.account.account_code
            line_dict['account_name'] = line.account.name
        lines.append(JournalEntryLineResponse(**line_dict))
    entry_dict['lines'] = lines

    return JournalEntryResponse(**entry_dict)


# ============ Expense Category Endpoints ============

@accounting_router.get("/expense-categories/{store_id}", response_model=List[ExpenseCategoryResponse])
async def list_expense_categories(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List expense categories for a store"""
    categories = db.query(ExpenseCategory).filter(
        ExpenseCategory.store_id == store_id
    ).order_by(ExpenseCategory.name).all()
    return categories


@accounting_router.post("/expense-categories/{store_id}", response_model=ExpenseCategoryResponse, status_code=201)
async def create_expense_category(
    store_id: UUID,
    data: ExpenseCategoryCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create an expense category"""
    existing = db.query(ExpenseCategory).filter(
        ExpenseCategory.store_id == store_id,
        ExpenseCategory.name == data.name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category name already exists")

    category = ExpenseCategory(
        store_id=store_id,
        name=data.name,
        description=data.description,
        account_id=data.account_id,
        color=data.color,
        icon=data.icon
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@accounting_router.put("/expense-categories/{store_id}/{category_id}", response_model=ExpenseCategoryResponse)
async def update_expense_category(
    store_id: UUID,
    category_id: UUID,
    data: ExpenseCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update an expense category"""
    category = db.query(ExpenseCategory).filter(
        ExpenseCategory.id == category_id,
        ExpenseCategory.store_id == store_id
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(category, field, value)

    db.commit()
    db.refresh(category)
    return category


@accounting_router.delete("/expense-categories/{store_id}/{category_id}")
async def delete_expense_category(
    store_id: UUID,
    category_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Delete an expense category"""
    category = db.query(ExpenseCategory).filter(
        ExpenseCategory.id == category_id,
        ExpenseCategory.store_id == store_id
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Check for expenses
    has_expenses = db.query(Expense).filter(Expense.category_id == category_id).first()
    if has_expenses:
        raise HTTPException(status_code=400, detail="Cannot delete category with expenses")

    db.delete(category)
    db.commit()
    return {"message": "Category deleted"}


# ============ Expense Endpoints ============

@accounting_router.get("/expenses/{store_id}", response_model=ExpenseListResponse)
async def list_expenses(
    store_id: UUID,
    status: Optional[ExpenseStatus] = None,
    category_id: Optional[UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List expenses for a store"""
    query = db.query(Expense).filter(Expense.store_id == store_id)

    if status:
        query = query.filter(Expense.status == status)
    if category_id:
        query = query.filter(Expense.category_id == category_id)
    if start_date:
        query = query.filter(Expense.expense_date >= start_date)
    if end_date:
        query = query.filter(Expense.expense_date <= end_date)

    total = query.count()
    expenses = query.order_by(Expense.expense_date.desc()).offset(offset).limit(limit).all()

    # Add category and account names
    result = []
    for exp in expenses:
        exp_dict = ExpenseResponse.model_validate(exp).model_dump()
        if exp.category:
            exp_dict['category_name'] = exp.category.name
        if exp.expense_account:
            exp_dict['account_name'] = exp.expense_account.name
        result.append(ExpenseResponse(**exp_dict))

    return ExpenseListResponse(expenses=result, total=total)


@accounting_router.post("/expenses/{store_id}", response_model=ExpenseResponse, status_code=201)
async def create_expense(
    store_id: UUID,
    data: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create an expense"""
    expense = Expense(
        store_id=store_id,
        expense_number=generate_expense_number(db),
        expense_date=data.expense_date,
        category_id=data.category_id,
        account_id=data.account_id,
        vendor_name=data.vendor_name,
        description=data.description,
        amount=data.amount,
        tax_amount=data.tax_amount,
        total_amount=data.amount + data.tax_amount,
        payment_method=data.payment_method,
        payment_reference=data.payment_reference,
        receipt_url=data.receipt_url,
        attachments=data.attachments,
        created_by=current_user.id
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)

    exp_dict = ExpenseResponse.model_validate(expense).model_dump()
    if expense.category:
        exp_dict['category_name'] = expense.category.name
    if expense.expense_account:
        exp_dict['account_name'] = expense.expense_account.name

    return ExpenseResponse(**exp_dict)


@accounting_router.get("/expenses/{store_id}/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    store_id: UUID,
    expense_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get a specific expense"""
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.store_id == store_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    exp_dict = ExpenseResponse.model_validate(expense).model_dump()
    if expense.category:
        exp_dict['category_name'] = expense.category.name
    if expense.expense_account:
        exp_dict['account_name'] = expense.expense_account.name

    return ExpenseResponse(**exp_dict)


@accounting_router.put("/expenses/{store_id}/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    store_id: UUID,
    expense_id: UUID,
    data: ExpenseUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update an expense"""
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.store_id == store_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    if expense.status in [ExpenseStatus.APPROVED, ExpenseStatus.PAID]:
        raise HTTPException(status_code=400, detail="Cannot update approved/paid expense")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(expense, field, value)

    # Recalculate total
    if 'amount' in update_data or 'tax_amount' in update_data:
        expense.total_amount = expense.amount + expense.tax_amount

    db.commit()
    db.refresh(expense)

    exp_dict = ExpenseResponse.model_validate(expense).model_dump()
    if expense.category:
        exp_dict['category_name'] = expense.category.name
    if expense.expense_account:
        exp_dict['account_name'] = expense.expense_account.name

    return ExpenseResponse(**exp_dict)


@accounting_router.post("/expenses/{store_id}/{expense_id}/approve", response_model=ExpenseResponse)
async def approve_expense(
    store_id: UUID,
    expense_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Approve an expense and create journal entry"""
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.store_id == store_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    if expense.status != ExpenseStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Cannot approve expense with status: {expense.status}")

    # Get cash account for credit
    cash_account = db.query(Account).filter(
        Account.store_id == store_id,
        Account.account_subtype == AccountSubtype.CASH
    ).first()
    if not cash_account:
        raise HTTPException(status_code=400, detail="No cash account found. Please initialize accounts first.")

    # Create journal entry
    journal_entry = JournalEntry(
        store_id=store_id,
        entry_number=generate_entry_number(db),
        entry_date=expense.expense_date,
        description=f"Expense: {expense.description}",
        source=JournalEntrySource.EXPENSE,
        source_id=str(expense.id),
        total_debit=expense.total_amount,
        total_credit=expense.total_amount,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.utcnow(),
        posted_by=current_user.id,
        created_by=current_user.id
    )
    db.add(journal_entry)
    db.flush()

    # Debit expense account
    debit_line = JournalEntryLine(
        journal_entry_id=journal_entry.id,
        account_id=expense.account_id,
        description=expense.description,
        debit_amount=expense.total_amount,
        credit_amount=0,
        line_order=0
    )
    db.add(debit_line)

    # Credit cash account
    credit_line = JournalEntryLine(
        journal_entry_id=journal_entry.id,
        account_id=cash_account.id,
        description=expense.description,
        debit_amount=0,
        credit_amount=expense.total_amount,
        line_order=1
    )
    db.add(credit_line)

    # Update account balances
    expense_account = expense.expense_account
    expense_account.current_balance += expense.total_amount
    cash_account.current_balance -= expense.total_amount

    expense.status = ExpenseStatus.APPROVED
    expense.approved_by = current_user.id
    expense.approved_at = datetime.utcnow()
    expense.journal_entry_id = journal_entry.id

    db.commit()
    db.refresh(expense)

    exp_dict = ExpenseResponse.model_validate(expense).model_dump()
    if expense.category:
        exp_dict['category_name'] = expense.category.name
    if expense.expense_account:
        exp_dict['account_name'] = expense.expense_account.name

    return ExpenseResponse(**exp_dict)


@accounting_router.delete("/expenses/{store_id}/{expense_id}")
async def delete_expense(
    store_id: UUID,
    expense_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Delete an expense"""
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.store_id == store_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    if expense.status in [ExpenseStatus.APPROVED, ExpenseStatus.PAID]:
        raise HTTPException(status_code=400, detail="Cannot delete approved/paid expense")

    db.delete(expense)
    db.commit()
    return {"message": "Expense deleted"}


# ============ Fiscal Year/Period Endpoints ============

@accounting_router.get("/fiscal-years/{store_id}", response_model=List[FiscalYearResponse])
async def list_fiscal_years(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List fiscal years for a store"""
    years = db.query(FiscalYear).filter(
        FiscalYear.store_id == store_id
    ).order_by(FiscalYear.start_date.desc()).all()
    return years


@accounting_router.post("/fiscal-years/{store_id}", response_model=FiscalYearResponse, status_code=201)
async def create_fiscal_year(
    store_id: UUID,
    data: FiscalYearCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create a fiscal year with monthly periods"""
    fiscal_year = FiscalYear(
        store_id=store_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date
    )
    db.add(fiscal_year)
    db.flush()

    # Create monthly periods
    current_date = data.start_date
    period_num = 1
    while current_date <= data.end_date:
        # Get last day of month
        _, last_day = monthrange(current_date.year, current_date.month)
        period_end = date(current_date.year, current_date.month, last_day)
        if period_end > data.end_date:
            period_end = data.end_date

        period = FiscalPeriod(
            store_id=store_id,
            fiscal_year_id=fiscal_year.id,
            period_number=period_num,
            name=current_date.strftime("%B %Y"),
            start_date=current_date,
            end_date=period_end
        )
        db.add(period)

        # Move to next month
        if current_date.month == 12:
            current_date = date(current_date.year + 1, 1, 1)
        else:
            current_date = date(current_date.year, current_date.month + 1, 1)
        period_num += 1

    db.commit()
    db.refresh(fiscal_year)
    return fiscal_year


@accounting_router.get("/fiscal-years/{store_id}/{year_id}/periods", response_model=List[FiscalPeriodResponse])
async def list_fiscal_periods(
    store_id: UUID,
    year_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List fiscal periods for a fiscal year"""
    periods = db.query(FiscalPeriod).filter(
        FiscalPeriod.fiscal_year_id == year_id,
        FiscalPeriod.store_id == store_id
    ).order_by(FiscalPeriod.period_number).all()
    return periods


@accounting_router.post("/fiscal-periods/{store_id}/{period_id}/close", response_model=FiscalPeriodResponse)
async def close_fiscal_period(
    store_id: UUID,
    period_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Close a fiscal period"""
    period = db.query(FiscalPeriod).filter(
        FiscalPeriod.id == period_id,
        FiscalPeriod.store_id == store_id
    ).first()
    if not period:
        raise HTTPException(status_code=404, detail="Fiscal period not found")

    if period.status != FiscalPeriodStatus.OPEN:
        raise HTTPException(status_code=400, detail=f"Period is already {period.status}")

    # Check for draft entries in period
    draft_entries = db.query(JournalEntry).filter(
        JournalEntry.store_id == store_id,
        JournalEntry.entry_date >= period.start_date,
        JournalEntry.entry_date <= period.end_date,
        JournalEntry.status == JournalEntryStatus.DRAFT
    ).count()

    if draft_entries > 0:
        raise HTTPException(status_code=400, detail=f"Cannot close period with {draft_entries} draft entries")

    period.status = FiscalPeriodStatus.CLOSED
    period.closed_at = datetime.utcnow()
    period.closed_by = current_user.id

    db.commit()
    db.refresh(period)
    return period


# ============ Report Endpoints ============

@accounting_router.get("/reports/{store_id}/income-statement", response_model=IncomeStatementResponse)
async def get_income_statement(
    store_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Generate income statement (P&L) for a period"""

    def get_account_totals(account_type: AccountType, subtypes: list = None):
        query = db.query(
            Account.id,
            Account.account_code,
            Account.name,
            func.coalesce(func.sum(JournalEntryLine.credit_amount), 0).label('credits'),
            func.coalesce(func.sum(JournalEntryLine.debit_amount), 0).label('debits')
        ).outerjoin(
            JournalEntryLine, JournalEntryLine.account_id == Account.id
        ).outerjoin(
            JournalEntry, and_(
                JournalEntry.id == JournalEntryLine.journal_entry_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == JournalEntryStatus.POSTED
            )
        ).filter(
            Account.store_id == store_id,
            Account.account_type == account_type
        )

        if subtypes:
            query = query.filter(Account.account_subtype.in_(subtypes))

        return query.group_by(Account.id, Account.account_code, Account.name).all()

    # Revenue
    revenue_data = get_account_totals(AccountType.REVENUE, [AccountSubtype.SALES, AccountSubtype.SERVICE_REVENUE, AccountSubtype.OTHER_REVENUE])
    revenue_items = []
    revenue_total = 0
    for acc in revenue_data:
        amount = float(acc.credits or 0) - float(acc.debits or 0)
        if amount != 0:
            revenue_items.append(IncomeStatementLineItem(
                account_id=acc.id, account_code=acc.account_code, account_name=acc.name, amount=amount
            ))
            revenue_total += amount

    # Sales Returns (contra revenue)
    returns_data = get_account_totals(AccountType.REVENUE, [AccountSubtype.SALES_RETURNS])
    for acc in returns_data:
        amount = float(acc.debits or 0) - float(acc.credits or 0)
        if amount != 0:
            revenue_items.append(IncomeStatementLineItem(
                account_id=acc.id, account_code=acc.account_code, account_name=acc.name, amount=-amount
            ))
            revenue_total -= amount

    # COGS
    cogs_data = get_account_totals(AccountType.EXPENSE, [AccountSubtype.COST_OF_GOODS_SOLD])
    cogs_items = []
    cogs_total = 0
    for acc in cogs_data:
        amount = float(acc.debits or 0) - float(acc.credits or 0)
        if amount != 0:
            cogs_items.append(IncomeStatementLineItem(
                account_id=acc.id, account_code=acc.account_code, account_name=acc.name, amount=amount
            ))
            cogs_total += amount

    gross_profit = revenue_total - cogs_total

    # Operating Expenses
    opex_data = get_account_totals(AccountType.EXPENSE, [
        AccountSubtype.OPERATING_EXPENSE, AccountSubtype.MARKETING,
        AccountSubtype.UTILITIES, AccountSubtype.RENT, AccountSubtype.PAYROLL
    ])
    opex_items = []
    opex_total = 0
    for acc in opex_data:
        amount = float(acc.debits or 0) - float(acc.credits or 0)
        if amount != 0:
            opex_items.append(IncomeStatementLineItem(
                account_id=acc.id, account_code=acc.account_code, account_name=acc.name, amount=amount
            ))
            opex_total += amount

    operating_income = gross_profit - opex_total

    # Other income/expenses (simplified)
    other_income = IncomeStatementSection(title="Other Income", items=[], total=0)
    other_expenses = IncomeStatementSection(title="Other Expenses", items=[], total=0)

    net_income = operating_income + other_income.total - other_expenses.total

    return IncomeStatementResponse(
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
        revenue=IncomeStatementSection(title="Revenue", items=revenue_items, total=revenue_total),
        cost_of_goods_sold=IncomeStatementSection(title="Cost of Goods Sold", items=cogs_items, total=cogs_total),
        gross_profit=gross_profit,
        operating_expenses=IncomeStatementSection(title="Operating Expenses", items=opex_items, total=opex_total),
        operating_income=operating_income,
        other_income=other_income,
        other_expenses=other_expenses,
        net_income=net_income
    )


@accounting_router.get("/reports/{store_id}/balance-sheet", response_model=BalanceSheetResponse)
async def get_balance_sheet(
    store_id: UUID,
    as_of_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Generate balance sheet as of a specific date"""

    def get_account_balances(account_type: AccountType):
        accounts = db.query(Account).filter(
            Account.store_id == store_id,
            Account.account_type == account_type,
            Account.is_active == True
        ).all()

        items = []
        for acc in accounts:
            # Get balance from posted entries up to as_of_date
            result = db.query(
                func.coalesce(func.sum(JournalEntryLine.debit_amount), 0).label('debits'),
                func.coalesce(func.sum(JournalEntryLine.credit_amount), 0).label('credits')
            ).join(JournalEntry).filter(
                JournalEntryLine.account_id == acc.id,
                JournalEntry.entry_date <= as_of_date,
                JournalEntry.status == JournalEntryStatus.POSTED
            ).first()

            if acc.normal_balance == NormalBalance.DEBIT:
                balance = float(result.debits or 0) - float(result.credits or 0)
            else:
                balance = float(result.credits or 0) - float(result.debits or 0)

            if balance != 0:
                items.append(IncomeStatementLineItem(
                    account_id=acc.id, account_code=acc.account_code, account_name=acc.name, amount=balance
                ))

        return items

    # Assets
    asset_items = get_account_balances(AccountType.ASSET)
    total_assets = sum(item.amount for item in asset_items)

    # Liabilities
    liability_items = get_account_balances(AccountType.LIABILITY)
    total_liabilities = sum(item.amount for item in liability_items)

    # Equity
    equity_items = get_account_balances(AccountType.EQUITY)
    total_equity = sum(item.amount for item in equity_items)

    return BalanceSheetResponse(
        store_id=store_id,
        as_of_date=as_of_date,
        assets=[BalanceSheetSection(title="Assets", items=asset_items, total=total_assets)],
        total_assets=total_assets,
        liabilities=[BalanceSheetSection(title="Liabilities", items=liability_items, total=total_liabilities)],
        total_liabilities=total_liabilities,
        equity=[BalanceSheetSection(title="Equity", items=equity_items, total=total_equity)],
        total_equity=total_equity,
        liabilities_and_equity=total_liabilities + total_equity
    )


@accounting_router.get("/reports/{store_id}/cash-flow", response_model=CashFlowResponse)
async def get_cash_flow(
    store_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Generate cash flow statement for a period"""

    # Get cash account
    cash_account = db.query(Account).filter(
        Account.store_id == store_id,
        Account.account_subtype == AccountSubtype.CASH
    ).first()

    if not cash_account:
        raise HTTPException(status_code=400, detail="No cash account found")

    # Get beginning cash balance
    beginning_result = db.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0).label('debits'),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0).label('credits')
    ).join(JournalEntry).filter(
        JournalEntryLine.account_id == cash_account.id,
        JournalEntry.entry_date < start_date,
        JournalEntry.status == JournalEntryStatus.POSTED
    ).first()

    beginning_cash = float(beginning_result.debits or 0) - float(beginning_result.credits or 0)

    # Get cash movement in period (simplified)
    period_result = db.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0).label('debits'),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0).label('credits')
    ).join(JournalEntry).filter(
        JournalEntryLine.account_id == cash_account.id,
        JournalEntry.entry_date >= start_date,
        JournalEntry.entry_date <= end_date,
        JournalEntry.status == JournalEntryStatus.POSTED
    ).first()

    net_change = float(period_result.debits or 0) - float(period_result.credits or 0)
    ending_cash = beginning_cash + net_change

    return CashFlowResponse(
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
        operating_activities=CashFlowSection(title="Operating Activities", items=[], total=net_change),
        investing_activities=CashFlowSection(title="Investing Activities", items=[], total=0),
        financing_activities=CashFlowSection(title="Financing Activities", items=[], total=0),
        net_change_in_cash=net_change,
        beginning_cash=beginning_cash,
        ending_cash=ending_cash
    )


@accounting_router.get("/reports/{store_id}/sales", response_model=SalesReportResponse)
async def get_sales_report(
    store_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Generate sales report for a period"""
    from modules.orders.models import Order

    # Query orders grouped by date
    results = db.query(
        func.date(Order.created_at).label('order_date'),
        func.count(Order.id).label('order_count'),
        func.coalesce(func.sum(Order.total_amount), 0).label('gross_sales'),
        func.coalesce(func.sum(Order.discount_amount), 0).label('discounts'),
        func.coalesce(func.sum(Order.tax_amount), 0).label('tax')
    ).filter(
        Order.store_id == store_id,
        func.date(Order.created_at) >= start_date,
        func.date(Order.created_at) <= end_date
    ).group_by(func.date(Order.created_at)).order_by(func.date(Order.created_at)).all()

    items = []
    total_orders = 0
    total_gross = 0
    total_discounts = 0
    total_refunds = 0
    total_tax = 0

    for row in results:
        gross = float(row.gross_sales or 0)
        disc = float(row.discounts or 0)
        tax = float(row.tax or 0)
        net = gross - disc

        items.append(SalesReportItem(
            date=row.order_date,
            order_count=row.order_count,
            gross_sales=gross,
            discounts=disc,
            refunds=0,
            net_sales=net,
            tax_collected=tax
        ))

        total_orders += row.order_count
        total_gross += gross
        total_discounts += disc
        total_tax += tax

    return SalesReportResponse(
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
        items=items,
        total_orders=total_orders,
        total_gross_sales=total_gross,
        total_discounts=total_discounts,
        total_refunds=total_refunds,
        total_net_sales=total_gross - total_discounts,
        total_tax=total_tax
    )


# ============ Dashboard Endpoint ============

@accounting_router.get("/dashboard/{store_id}", response_model=AccountingDashboardResponse)
async def get_accounting_dashboard(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get accounting dashboard summary"""
    today = date.today()
    period_start = date(today.year, today.month, 1)
    period_end = today

    # Get revenue (credits to revenue accounts)
    revenue_result = db.query(
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0).label('credits'),
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0).label('debits')
    ).join(JournalEntry).join(Account).filter(
        Account.store_id == store_id,
        Account.account_type == AccountType.REVENUE,
        JournalEntry.entry_date >= period_start,
        JournalEntry.entry_date <= period_end,
        JournalEntry.status == JournalEntryStatus.POSTED
    ).first()

    total_revenue = float(revenue_result.credits or 0) - float(revenue_result.debits or 0)

    # Get expenses (debits to expense accounts)
    expense_result = db.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0).label('debits'),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0).label('credits')
    ).join(JournalEntry).join(Account).filter(
        Account.store_id == store_id,
        Account.account_type == AccountType.EXPENSE,
        JournalEntry.entry_date >= period_start,
        JournalEntry.entry_date <= period_end,
        JournalEntry.status == JournalEntryStatus.POSTED
    ).first()

    total_expenses = float(expense_result.debits or 0) - float(expense_result.credits or 0)

    # Get cash balance
    cash_account = db.query(Account).filter(
        Account.store_id == store_id,
        Account.account_subtype == AccountSubtype.CASH
    ).first()
    cash_balance = float(cash_account.current_balance) if cash_account else 0

    # Get AR balance
    ar_account = db.query(Account).filter(
        Account.store_id == store_id,
        Account.account_subtype == AccountSubtype.ACCOUNTS_RECEIVABLE
    ).first()
    ar_balance = float(ar_account.current_balance) if ar_account else 0

    # Get AP balance
    ap_account = db.query(Account).filter(
        Account.store_id == store_id,
        Account.account_subtype == AccountSubtype.ACCOUNTS_PAYABLE
    ).first()
    ap_balance = float(ap_account.current_balance) if ap_account else 0

    # Get recent journal entries
    recent_entries = db.query(JournalEntry).filter(
        JournalEntry.store_id == store_id
    ).order_by(JournalEntry.created_at.desc()).limit(5).all()

    recent_list = []
    for entry in recent_entries:
        entry_dict = JournalEntryResponse.model_validate(entry).model_dump()
        entry_dict['lines'] = []
        recent_list.append(JournalEntryResponse(**entry_dict))

    # Get expenses by category
    expense_by_cat = db.query(
        ExpenseCategory.name,
        func.sum(Expense.total_amount).label('total')
    ).join(Expense).filter(
        ExpenseCategory.store_id == store_id,
        Expense.expense_date >= period_start,
        Expense.expense_date <= period_end
    ).group_by(ExpenseCategory.name).all()

    expense_categories = [{"name": cat.name, "amount": float(cat.total or 0)} for cat in expense_by_cat]

    return AccountingDashboardResponse(
        store_id=store_id,
        period_start=period_start,
        period_end=period_end,
        total_revenue=total_revenue,
        total_expenses=total_expenses,
        net_income=total_revenue - total_expenses,
        cash_balance=cash_balance,
        accounts_receivable=ar_balance,
        accounts_payable=ap_balance,
        recent_transactions=recent_list,
        expense_by_category=expense_categories
    )
