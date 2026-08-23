import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on Postgres (fast containment queries, indexable) but falls back to
# plain JSON on any other dialect — this is what lets the test suite run
# against SQLite instead of needing a live Postgres connection for CI.
JSONVariant = JSON().with_variant(JSONB, "postgresql")


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customers: Mapped[list["Customer"]] = relationship(back_populates="merchant")
    orders: Mapped[list["Order"]] = relationship(back_populates="merchant")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20))
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    merchant: Mapped["Merchant"] = relationship(back_populates="customers")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    merchant: Mapped["Merchant"] = relationship(back_populates="orders")
    customer: Mapped["Customer"] = relationship(back_populates="orders")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    method: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    order: Mapped["Order"] = relationship(back_populates="payments")
    recovery_case: Mapped["RecoveryCase | None"] = relationship(back_populates="payment", uselist=False)
    ground_truth: Mapped["GroundTruth | None"] = relationship(back_populates="payment", uselist=False)


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    status: Mapped[str] = mapped_column(String(30), default="detected")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    payment: Mapped["Payment"] = relationship(back_populates="recovery_case")
    decisions: Mapped[list["AgentDecision"]] = relationship(back_populates="case")
    policy_checks: Mapped[list["PolicyCheck"]] = relationship(back_populates="case")
    actions: Mapped[list["Action"]] = relationship(back_populates="case")
    outcome: Mapped["Outcome | None"] = relationship(back_populates="case", uselist=False)


class AgentDecision(Base):
    __tablename__ = "agent_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_case_id: Mapped[int] = mapped_column(ForeignKey("recovery_cases.id"))
    agent_name: Mapped[str] = mapped_column(String(50))
    model_used: Mapped[str] = mapped_column(String(30))
    input_snapshot: Mapped[dict] = mapped_column(JSONVariant)
    output: Mapped[dict] = mapped_column(JSONVariant)
    confidence: Mapped[float] = mapped_column(Float)
    # nullable: the rules-based fallback tier has no token/latency concept
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["RecoveryCase"] = relationship(back_populates="decisions")


class PolicyCheck(Base):
    __tablename__ = "policy_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_case_id: Mapped[int] = mapped_column(ForeignKey("recovery_cases.id"))
    check_name: Mapped[str] = mapped_column(String(50))
    passed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["RecoveryCase"] = relationship(back_populates="policy_checks")


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_case_id: Mapped[int] = mapped_column(ForeignKey("recovery_cases.id"))
    action_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    razorpay_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # generated client-side (not DB default) so it exists the instant the Action
    # object is created in Python, before it's ever flushed to Razorpay — the
    # executor must send this on every call and treat a repeat as a no-op.
    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: uuid.uuid4().hex
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["RecoveryCase"] = relationship(back_populates="actions")


class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_case_id: Mapped[int] = mapped_column(ForeignKey("recovery_cases.id"))
    recovered_amount_paise: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["RecoveryCase"] = relationship(back_populates="outcome")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_case_id: Mapped[int | None] = mapped_column(ForeignKey("recovery_cases.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroundTruth(Base):
    """
    Pre-labeled answer key for the held-out evaluation described in the PRD
    ("precision/recall on 'is this actually recoverable' vs pre-labeled
    ground truth"). Generated once by scripts/generate_synthetic_data.py and
    then frozen — do not regenerate once agent development starts, or every
    evaluation number becomes a moving target.

    INTEGRITY RULE: the Root Cause Agent and Recovery Strategy Agent must
    NEVER read this table. It exists purely for scoring their output after
    the fact (Day 6). If an agent's prompt or context ever includes
    is_recoverable/ideal_action, the eval numbers are meaningless.
    """

    __tablename__ = "ground_truth_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), unique=True)

    is_recoverable: Mapped[bool] = mapped_column(Boolean)
    # one of: retry_now | retry_later | send_payment_link | escalate_human | no_action
    ideal_action: Mapped[str] = mapped_column(String(30))
    # "dev" (80%, agents may be iterated against this) | "holdout" (20%, touch once, at the end)
    eval_split: Mapped[str] = mapped_column(String(10), default="dev")
    rationale: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    payment: Mapped["Payment"] = relationship(back_populates="ground_truth")