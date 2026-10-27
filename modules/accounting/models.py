# modules/accounting/models.py
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Integer, Boolean, JSON, Enum as SQLEnum, Numeric, Date, UniqueConstraint, CheckConstraint
from db_compat import PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, date
import uuid
from database import Base
import enum


class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class AccountSubtype(str, enum.Enum):
    # Asset subtypes
    CASH = "cash"
    BANK = "bank"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    INVENTORY = "inventory"
    FIXED_ASSET = "fixed_asset"
    OTHER_ASSET = "other_asset"
    # Liability subtypes
    ACCOUNTS_PAYABLE = "accounts_payable"
    TAX_PAYABLE = "tax_payable"
    LOAN = "loan"
    OTHER_LIABILITY = "other_liability"
    # Equity subtypes
    OWNER_EQUITY = "owner_equity"
    RETAINED_EARNINGS = "retained_earnings"
    DRAWINGS = "drawings"
    # Revenue subtypes
    SALES = "sales"
    SERVICE_REVENUE = "service_revenue"
    OTHER_REVENUE = "other_revenue"
    SALES_RETURNS = "sales_returns"
    # Expense subtypes
    COST_OF_GOODS_SOLD = "cost_of_goods_sold"
    OPERATING_EXPENSE = "operating_expense"
    MARKETING = "marketing"
    UTILITIES = "utilities"
    RENT = "rent"
    PAYROLL = "payroll"
    OTHER_EXPENSE = "other_expense"


class NormalBalance(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalEntryStatus(str, enum.Enum):
    DRAFT = "draft"
    POSTED = "posted"
    VOIDED = "voided"


class JournalEntrySource(str, enum.Enum):
    MANUAL = "manual"
    ORDER = "order"
    PAYMENT = "payment"
    POS = "pos"
    REFUND = "refund"
    EXPENSE = "expense"
    ADJUSTMENT = "adjustment"


class ExpenseStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"


class FiscalPeriodStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"


class Account(Base):
    """Chart of Accounts - Double Entry Accounting"""
    __tablename__ = "accounting_accounts"
    __table_args__ = (
        UniqueConstraint('store_id', 'account_code', name='uq_store_account_code'),
    )

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    account_type: Mapped[AccountType] = mapped_column(SQLEnum(AccountType), nullable=False)
    account_subtype: Mapped[AccountSubtype] = mapped_column(SQLEnum(AccountSubtype), nullable=False)
    normal_balance: Mapped[NormalBalance] = mapped_column(SQLEnum(NormalBalance), nullable=False)

    parent_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_accounts.id"), nullable=True)

    current_balance: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # System accounts can't be deleted

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="accounting_accounts")
    parent = relationship("Account", remote_side="Account.id", backref="children")
    journal_lines = relationship("JournalEntryLine", back_populates="account")


class JournalEntry(Base):
    """Double Entry Journal Headers"""
    __tablename__ = "accounting_journal_entries"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    entry_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)

    source: Mapped[JournalEntrySource] = mapped_column(SQLEnum(JournalEntrySource), default=JournalEntrySource.MANUAL)
    source_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)  # Links to order/payment/transaction

    description: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    status: Mapped[JournalEntryStatus] = mapped_column(SQLEnum(JournalEntryStatus), default=JournalEntryStatus.DRAFT)

    total_debit: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    total_credit: Mapped[float] = mapped_column(Numeric(15, 2), default=0)

    fiscal_period_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_fiscal_periods.id"), nullable=True)

    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    posted_by: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="journal_entries")
    fiscal_period = relationship("FiscalPeriod", backref="journal_entries")
    lines = relationship("JournalEntryLine", back_populates="journal_entry", cascade="all, delete-orphan")
    created_by_user = relationship("User", foreign_keys=[created_by], backref="created_journal_entries")
    posted_by_user = relationship("User", foreign_keys=[posted_by], backref="posted_journal_entries")
    voided_by_user = relationship("User", foreign_keys=[voided_by], backref="voided_journal_entries")


class JournalEntryLine(Base):
    """Individual debit/credit lines for journal entries"""
    __tablename__ = "accounting_journal_entry_lines"
    __table_args__ = (
        CheckConstraint('NOT (debit_amount > 0 AND credit_amount > 0)', name='check_debit_xor_credit'),
    )

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_entry_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_journal_entries.id"), nullable=False, index=True)
    account_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_accounts.id"), nullable=False, index=True)

    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    debit_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    credit_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)

    line_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    journal_entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("Account", back_populates="journal_lines")


class ExpenseCategory(Base):
    """Categories for expense tracking"""
    __tablename__ = "accounting_expense_categories"
    __table_args__ = (
        UniqueConstraint('store_id', 'name', name='uq_store_expense_category_name'),
    )

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_accounts.id"), nullable=True)

    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # Hex color
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="expense_categories")
    default_account = relationship("Account", backref="expense_categories")
    expenses = relationship("Expense", back_populates="category")


class Expense(Base):
    """Manual expense tracking"""
    __tablename__ = "accounting_expenses"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    expense_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)

    category_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_expense_categories.id"), nullable=True)
    account_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_accounts.id"), nullable=False)

    vendor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)

    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    receipt_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    attachments: Mapped[List[str]] = mapped_column(JSON, default=list)

    status: Mapped[ExpenseStatus] = mapped_column(SQLEnum(ExpenseStatus), default=ExpenseStatus.PENDING)

    journal_entry_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_journal_entries.id"), nullable=True)

    approved_by: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="expenses")
    category = relationship("ExpenseCategory", back_populates="expenses")
    expense_account = relationship("Account", foreign_keys=[account_id], backref="expenses")
    journal_entry = relationship("JournalEntry", backref="expense")
    created_by_user = relationship("User", foreign_keys=[created_by], backref="created_expenses")
    approved_by_user = relationship("User", foreign_keys=[approved_by], backref="approved_expenses")


class FiscalYear(Base):
    """Annual fiscal year periods"""
    __tablename__ = "accounting_fiscal_years"
    __table_args__ = (
        UniqueConstraint('store_id', 'name', name='uq_store_fiscal_year_name'),
    )

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="fiscal_years")
    periods = relationship("FiscalPeriod", back_populates="fiscal_year", cascade="all, delete-orphan")
    closed_by_user = relationship("User", backref="closed_fiscal_years")


class FiscalPeriod(Base):
    """Monthly fiscal periods within a fiscal year"""
    __tablename__ = "accounting_fiscal_periods"
    __table_args__ = (
        UniqueConstraint('fiscal_year_id', 'period_number', name='uq_fiscal_year_period'),
    )

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    fiscal_year_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("accounting_fiscal_years.id"), nullable=False)

    period_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-12
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "January 2024"
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[FiscalPeriodStatus] = mapped_column(SQLEnum(FiscalPeriodStatus), default=FiscalPeriodStatus.OPEN)

    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="fiscal_periods")
    fiscal_year = relationship("FiscalYear", back_populates="periods")
    closed_by_user = relationship("User", backref="closed_fiscal_periods")
