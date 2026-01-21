# modules/accounting/schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from enum import Enum


# Enums for request/response
class AccountTypeEnum(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class AccountSubtypeEnum(str, Enum):
    CASH = "cash"
    BANK = "bank"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    INVENTORY = "inventory"
    FIXED_ASSET = "fixed_asset"
    OTHER_ASSET = "other_asset"
    ACCOUNTS_PAYABLE = "accounts_payable"
    TAX_PAYABLE = "tax_payable"
    LOAN = "loan"
    OTHER_LIABILITY = "other_liability"
    OWNER_EQUITY = "owner_equity"
    RETAINED_EARNINGS = "retained_earnings"
    DRAWINGS = "drawings"
    SALES = "sales"
    SERVICE_REVENUE = "service_revenue"
    OTHER_REVENUE = "other_revenue"
    SALES_RETURNS = "sales_returns"
    COST_OF_GOODS_SOLD = "cost_of_goods_sold"
    OPERATING_EXPENSE = "operating_expense"
    MARKETING = "marketing"
    UTILITIES = "utilities"
    RENT = "rent"
    PAYROLL = "payroll"
    OTHER_EXPENSE = "other_expense"


class NormalBalanceEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalEntryStatusEnum(str, Enum):
    DRAFT = "draft"
    POSTED = "posted"
    VOIDED = "voided"


class JournalEntrySourceEnum(str, Enum):
    MANUAL = "manual"
    ORDER = "order"
    PAYMENT = "payment"
    POS = "pos"
    REFUND = "refund"
    EXPENSE = "expense"
    ADJUSTMENT = "adjustment"


class ExpenseStatusEnum(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"


class FiscalPeriodStatusEnum(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"


# ============ Account Schemas ============

class AccountCreate(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    account_type: AccountTypeEnum
    account_subtype: AccountSubtypeEnum
    parent_id: Optional[UUID] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    parent_id: Optional[UUID] = None


class AccountResponse(BaseModel):
    id: UUID
    store_id: UUID
    account_code: str
    name: str
    description: Optional[str]
    account_type: AccountTypeEnum
    account_subtype: AccountSubtypeEnum
    normal_balance: NormalBalanceEnum
    parent_id: Optional[UUID]
    current_balance: float
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountListResponse(BaseModel):
    accounts: List[AccountResponse]
    total: int


# ============ Journal Entry Schemas ============

class JournalEntryLineCreate(BaseModel):
    account_id: UUID
    description: Optional[str] = None
    debit_amount: float = Field(default=0, ge=0)
    credit_amount: float = Field(default=0, ge=0)

    @field_validator('credit_amount')
    @classmethod
    def validate_amounts(cls, v, info):
        debit = info.data.get('debit_amount', 0)
        if debit > 0 and v > 0:
            raise ValueError('Cannot have both debit and credit amounts on the same line')
        if debit == 0 and v == 0:
            raise ValueError('Must have either debit or credit amount')
        return v


class JournalEntryCreate(BaseModel):
    entry_date: date
    description: str = Field(..., min_length=1)
    reference: Optional[str] = None
    lines: List[JournalEntryLineCreate] = Field(..., min_length=2)

    @field_validator('lines')
    @classmethod
    def validate_balanced(cls, v):
        total_debit = sum(line.debit_amount for line in v)
        total_credit = sum(line.credit_amount for line in v)
        if abs(total_debit - total_credit) > 0.001:
            raise ValueError(f'Journal entry must be balanced. Debit: {total_debit}, Credit: {total_credit}')
        return v


class JournalEntryLineResponse(BaseModel):
    id: UUID
    journal_entry_id: UUID
    account_id: UUID
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    description: Optional[str]
    debit_amount: float
    credit_amount: float
    line_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class JournalEntryResponse(BaseModel):
    id: UUID
    store_id: UUID
    entry_number: str
    entry_date: date
    source: JournalEntrySourceEnum
    source_id: Optional[str]
    description: str
    reference: Optional[str]
    status: JournalEntryStatusEnum
    total_debit: float
    total_credit: float
    fiscal_period_id: Optional[UUID]
    posted_at: Optional[datetime]
    voided_at: Optional[datetime]
    void_reason: Optional[str]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    lines: List[JournalEntryLineResponse] = []

    class Config:
        from_attributes = True


class JournalEntryListResponse(BaseModel):
    entries: List[JournalEntryResponse]
    total: int


class PostJournalEntryRequest(BaseModel):
    pass  # Just needs the entry_id from path


class VoidJournalEntryRequest(BaseModel):
    reason: str = Field(..., min_length=1)


# ============ Expense Category Schemas ============

class ExpenseCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    account_id: Optional[UUID] = None
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')
    icon: Optional[str] = None


class ExpenseCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    account_id: Optional[UUID] = None
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')
    icon: Optional[str] = None
    is_active: Optional[bool] = None


class ExpenseCategoryResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    description: Optional[str]
    account_id: Optional[UUID]
    color: Optional[str]
    icon: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ Expense Schemas ============

class ExpenseCreate(BaseModel):
    expense_date: date
    category_id: Optional[UUID] = None
    account_id: UUID
    vendor_name: Optional[str] = None
    description: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    tax_amount: float = Field(default=0, ge=0)
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    receipt_url: Optional[str] = None
    attachments: List[str] = []


class ExpenseUpdate(BaseModel):
    expense_date: Optional[date] = None
    category_id: Optional[UUID] = None
    account_id: Optional[UUID] = None
    vendor_name: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    tax_amount: Optional[float] = Field(None, ge=0)
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    receipt_url: Optional[str] = None
    attachments: Optional[List[str]] = None


class ExpenseResponse(BaseModel):
    id: UUID
    store_id: UUID
    expense_number: str
    expense_date: date
    category_id: Optional[UUID]
    category_name: Optional[str] = None
    account_id: UUID
    account_name: Optional[str] = None
    vendor_name: Optional[str]
    description: str
    amount: float
    tax_amount: float
    total_amount: float
    payment_method: Optional[str]
    payment_reference: Optional[str]
    receipt_url: Optional[str]
    attachments: List[str]
    status: ExpenseStatusEnum
    journal_entry_id: Optional[UUID]
    approved_by: Optional[UUID]
    approved_at: Optional[datetime]
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ExpenseListResponse(BaseModel):
    expenses: List[ExpenseResponse]
    total: int


class ApproveExpenseRequest(BaseModel):
    pass


class RejectExpenseRequest(BaseModel):
    reason: Optional[str] = None


# ============ Fiscal Year/Period Schemas ============

class FiscalYearCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date

    @field_validator('end_date')
    @classmethod
    def validate_dates(cls, v, info):
        start = info.data.get('start_date')
        if start and v <= start:
            raise ValueError('End date must be after start date')
        return v


class FiscalYearResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    start_date: date
    end_date: date
    is_closed: bool
    closed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FiscalPeriodResponse(BaseModel):
    id: UUID
    store_id: UUID
    fiscal_year_id: UUID
    period_number: int
    name: str
    start_date: date
    end_date: date
    status: FiscalPeriodStatusEnum
    closed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ClosePeriodRequest(BaseModel):
    pass


# ============ Report Schemas ============

class IncomeStatementLineItem(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    amount: float


class IncomeStatementSection(BaseModel):
    title: str
    items: List[IncomeStatementLineItem]
    total: float


class IncomeStatementResponse(BaseModel):
    store_id: UUID
    start_date: date
    end_date: date
    revenue: IncomeStatementSection
    cost_of_goods_sold: IncomeStatementSection
    gross_profit: float
    operating_expenses: IncomeStatementSection
    operating_income: float
    other_income: IncomeStatementSection
    other_expenses: IncomeStatementSection
    net_income: float


class BalanceSheetSection(BaseModel):
    title: str
    items: List[IncomeStatementLineItem]
    total: float


class BalanceSheetResponse(BaseModel):
    store_id: UUID
    as_of_date: date
    assets: List[BalanceSheetSection]
    total_assets: float
    liabilities: List[BalanceSheetSection]
    total_liabilities: float
    equity: List[BalanceSheetSection]
    total_equity: float
    liabilities_and_equity: float


class CashFlowSection(BaseModel):
    title: str
    items: List[IncomeStatementLineItem]
    total: float


class CashFlowResponse(BaseModel):
    store_id: UUID
    start_date: date
    end_date: date
    operating_activities: CashFlowSection
    investing_activities: CashFlowSection
    financing_activities: CashFlowSection
    net_change_in_cash: float
    beginning_cash: float
    ending_cash: float


class SalesReportItem(BaseModel):
    date: date
    order_count: int
    gross_sales: float
    discounts: float
    refunds: float
    net_sales: float
    tax_collected: float


class SalesReportResponse(BaseModel):
    store_id: UUID
    start_date: date
    end_date: date
    items: List[SalesReportItem]
    total_orders: int
    total_gross_sales: float
    total_discounts: float
    total_refunds: float
    total_net_sales: float
    total_tax: float


# ============ General Ledger Schemas ============

class LedgerEntry(BaseModel):
    date: date
    entry_number: str
    description: str
    debit: float
    credit: float
    balance: float


class GeneralLedgerResponse(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: AccountTypeEnum
    normal_balance: NormalBalanceEnum
    start_date: date
    end_date: date
    opening_balance: float
    entries: List[LedgerEntry]
    closing_balance: float


# ============ Dashboard Schemas ============

class AccountingDashboardResponse(BaseModel):
    store_id: UUID
    period_start: date
    period_end: date
    total_revenue: float
    total_expenses: float
    net_income: float
    cash_balance: float
    accounts_receivable: float
    accounts_payable: float
    recent_transactions: List[JournalEntryResponse]
    expense_by_category: List[dict]
