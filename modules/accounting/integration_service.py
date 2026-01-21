# modules/accounting/integration_service.py
"""
Service for automatically creating journal entries from business events.
Call these functions from order/payment/POS routers when transactions complete.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from uuid import UUID
from datetime import datetime, date

from .models import (
    Account, AccountType, AccountSubtype, NormalBalance,
    JournalEntry, JournalEntryStatus, JournalEntrySource, JournalEntryLine
)


def generate_entry_number(db: Session) -> str:
    """Generate unique journal entry number"""
    count = db.query(func.count(JournalEntry.id)).scalar() or 0
    return f"JE-{count + 1:06d}"


def get_account_by_subtype(db: Session, store_id: UUID, subtype: AccountSubtype) -> Optional[Account]:
    """Get account by subtype for a store"""
    return db.query(Account).filter(
        Account.store_id == store_id,
        Account.account_subtype == subtype,
        Account.is_active == True
    ).first()


def update_account_balance(account: Account, debit: float, credit: float):
    """Update account balance based on normal balance type"""
    if account.normal_balance == NormalBalance.DEBIT:
        account.current_balance += debit - credit
    else:
        account.current_balance += credit - debit


def create_journal_entry_for_order(
    db: Session,
    store_id: UUID,
    order_id: UUID,
    order_total: float,
    tax_amount: float,
    user_id: UUID,
    description: str = "Order completed"
) -> Optional[JournalEntry]:
    """
    Create journal entry when an order is completed.
    Debit: Cash/Accounts Receivable
    Credit: Sales Revenue + Tax Payable
    """
    # Get required accounts
    cash_account = get_account_by_subtype(db, store_id, AccountSubtype.CASH)
    revenue_account = get_account_by_subtype(db, store_id, AccountSubtype.SALES)
    tax_account = get_account_by_subtype(db, store_id, AccountSubtype.TAX_PAYABLE)

    if not cash_account or not revenue_account:
        return None  # Accounts not set up yet

    net_amount = order_total - tax_amount

    # Create journal entry
    entry = JournalEntry(
        store_id=store_id,
        entry_number=generate_entry_number(db),
        entry_date=date.today(),
        description=description,
        source=JournalEntrySource.ORDER,
        source_id=str(order_id),
        total_debit=order_total,
        total_credit=order_total,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.utcnow(),
        posted_by=user_id,
        created_by=user_id
    )
    db.add(entry)
    db.flush()

    # Debit Cash
    debit_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=cash_account.id,
        description=f"Cash received for order",
        debit_amount=order_total,
        credit_amount=0,
        line_order=0
    )
    db.add(debit_line)
    update_account_balance(cash_account, order_total, 0)

    # Credit Revenue
    revenue_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=revenue_account.id,
        description=f"Sales revenue",
        debit_amount=0,
        credit_amount=net_amount,
        line_order=1
    )
    db.add(revenue_line)
    update_account_balance(revenue_account, 0, net_amount)

    # Credit Tax Payable (if tax exists)
    if tax_amount > 0 and tax_account:
        tax_line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=tax_account.id,
            description=f"Tax collected",
            debit_amount=0,
            credit_amount=tax_amount,
            line_order=2
        )
        db.add(tax_line)
        update_account_balance(tax_account, 0, tax_amount)

    return entry


def create_journal_entry_for_pos_sale(
    db: Session,
    store_id: UUID,
    transaction_id: UUID,
    transaction_number: str,
    total_amount: float,
    tax_amount: float,
    payment_method: str,
    user_id: UUID
) -> Optional[JournalEntry]:
    """
    Create journal entry for POS sale.
    Similar to order but source is POS.
    """
    cash_account = get_account_by_subtype(db, store_id, AccountSubtype.CASH)
    revenue_account = get_account_by_subtype(db, store_id, AccountSubtype.SALES)
    tax_account = get_account_by_subtype(db, store_id, AccountSubtype.TAX_PAYABLE)

    if not cash_account or not revenue_account:
        return None

    net_amount = total_amount - tax_amount

    entry = JournalEntry(
        store_id=store_id,
        entry_number=generate_entry_number(db),
        entry_date=date.today(),
        description=f"POS Sale: {transaction_number}",
        source=JournalEntrySource.POS,
        source_id=str(transaction_id),
        total_debit=total_amount,
        total_credit=total_amount,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.utcnow(),
        posted_by=user_id,
        created_by=user_id
    )
    db.add(entry)
    db.flush()

    # Debit Cash
    debit_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=cash_account.id,
        description=f"POS Sale - {payment_method}",
        debit_amount=total_amount,
        credit_amount=0,
        line_order=0
    )
    db.add(debit_line)
    update_account_balance(cash_account, total_amount, 0)

    # Credit Revenue
    revenue_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=revenue_account.id,
        description=f"POS Sales revenue",
        debit_amount=0,
        credit_amount=net_amount,
        line_order=1
    )
    db.add(revenue_line)
    update_account_balance(revenue_account, 0, net_amount)

    if tax_amount > 0 and tax_account:
        tax_line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=tax_account.id,
            description=f"Tax collected",
            debit_amount=0,
            credit_amount=tax_amount,
            line_order=2
        )
        db.add(tax_line)
        update_account_balance(tax_account, 0, tax_amount)

    return entry


def create_journal_entry_for_refund(
    db: Session,
    store_id: UUID,
    original_source: JournalEntrySource,
    original_source_id: str,
    refund_amount: float,
    tax_refund: float,
    user_id: UUID,
    reason: str = "Refund issued"
) -> Optional[JournalEntry]:
    """
    Create journal entry for refund (reverses the original sale).
    Debit: Sales Revenue + Tax Payable
    Credit: Cash
    """
    cash_account = get_account_by_subtype(db, store_id, AccountSubtype.CASH)
    revenue_account = get_account_by_subtype(db, store_id, AccountSubtype.SALES)
    tax_account = get_account_by_subtype(db, store_id, AccountSubtype.TAX_PAYABLE)

    if not cash_account or not revenue_account:
        return None

    net_amount = refund_amount - tax_refund

    entry = JournalEntry(
        store_id=store_id,
        entry_number=generate_entry_number(db),
        entry_date=date.today(),
        description=f"Refund: {reason}",
        source=JournalEntrySource.REFUND,
        source_id=original_source_id,
        total_debit=refund_amount,
        total_credit=refund_amount,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.utcnow(),
        posted_by=user_id,
        created_by=user_id
    )
    db.add(entry)
    db.flush()

    # Debit Revenue (reverse)
    revenue_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=revenue_account.id,
        description=f"Sales refund",
        debit_amount=net_amount,
        credit_amount=0,
        line_order=0
    )
    db.add(revenue_line)
    update_account_balance(revenue_account, net_amount, 0)

    # Debit Tax Payable (reverse)
    if tax_refund > 0 and tax_account:
        tax_line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=tax_account.id,
            description=f"Tax refund",
            debit_amount=tax_refund,
            credit_amount=0,
            line_order=1
        )
        db.add(tax_line)
        update_account_balance(tax_account, tax_refund, 0)

    # Credit Cash
    cash_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=cash_account.id,
        description=f"Cash refunded",
        debit_amount=0,
        credit_amount=refund_amount,
        line_order=2
    )
    db.add(cash_line)
    update_account_balance(cash_account, 0, refund_amount)

    return entry


def create_journal_entry_for_payment_received(
    db: Session,
    store_id: UUID,
    payment_id: UUID,
    amount: float,
    user_id: UUID,
    description: str = "Payment received"
) -> Optional[JournalEntry]:
    """
    Create journal entry when payment is received against an invoice.
    Debit: Cash
    Credit: Accounts Receivable
    """
    cash_account = get_account_by_subtype(db, store_id, AccountSubtype.CASH)
    ar_account = get_account_by_subtype(db, store_id, AccountSubtype.ACCOUNTS_RECEIVABLE)

    if not cash_account or not ar_account:
        return None

    entry = JournalEntry(
        store_id=store_id,
        entry_number=generate_entry_number(db),
        entry_date=date.today(),
        description=description,
        source=JournalEntrySource.PAYMENT,
        source_id=str(payment_id),
        total_debit=amount,
        total_credit=amount,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.utcnow(),
        posted_by=user_id,
        created_by=user_id
    )
    db.add(entry)
    db.flush()

    # Debit Cash
    cash_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=cash_account.id,
        description=f"Payment received",
        debit_amount=amount,
        credit_amount=0,
        line_order=0
    )
    db.add(cash_line)
    update_account_balance(cash_account, amount, 0)

    # Credit AR
    ar_line = JournalEntryLine(
        journal_entry_id=entry.id,
        account_id=ar_account.id,
        description=f"Receivable cleared",
        debit_amount=0,
        credit_amount=amount,
        line_order=1
    )
    db.add(ar_line)
    update_account_balance(ar_account, 0, amount)

    return entry
