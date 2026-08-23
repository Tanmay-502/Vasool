"""
Synthetic transaction generator for Vasool.

    python -m scripts.generate_synthetic_data                # 1500 orders, seed 42
    python -m scripts.generate_synthetic_data --count 2000
    python -m scripts.generate_synthetic_data --reset         # wipe & regenerate everything

Produces merchants, customers, orders and payments with a realistic Indian
payment-method and failure-reason mix. Every FAILED payment gets:
  - a RecoveryCase (status="detected") — this is what the pipeline will pick up
  - a GroundTruth label (is_recoverable, ideal_action) — the answer key for
    Day 6 evaluation, split 80/20 into "dev" / "holdout"

IMPORTANT — ground truth is generated with a fixed seed so it is
reproducible ("frozen"). Once you start building the Root Cause / Recovery
Strategy agents against this data (Day 3+), do not re-run this script with a
different seed — that silently changes the answer key you're being scored
against and invalidates every metric you've collected so far. If you need
more data later, increase --count, don't change --seed.

The agents built on Day 3+ must never query the ground_truth_labels table.
It is read only by the Day 6 evaluation script.

PERFORMANCE NOTE (Day 2): rows are built in memory and written in a handful
of batched INSERTs (one add_all() + one flush() per table) instead of one
flush per row. On a remote DB, each flush is a network round trip — flushing
per-row turned a 1500-row run into 2,000+ round trips to Neon, which is why
it felt like it hung. Batching drops that to about 6 round trips total.

NOTE: this restructuring changed the order in which the RNG is consumed
compared to the original per-row version, so seed=42 now produces a
different (but still fully deterministic and reproducible) dataset than it
did before. That's safe to do now, on Day 2, before anything downstream has
been built against a specific frozen dataset — just don't mix output from
this version with output from the old version, and don't change it again
once Day 3+ agents are evaluated against it.

DAY 2.5 HARDENING: added a real opted_out cohort (OPTED_OUT_PROB) and real
attempt_number variation (ATTEMPT_NUMBER_WEIGHTS) on failed payments — both
were previously hardcoded to "never happens" / "always 1". This shifts the
RNG stream again, so seed=42 now produces yet another (still fully
deterministic) dataset vs. the version before this change. Same rule as
above: fine now, not fine once Day 3+ agents are being scored against it.
"""
import argparse
import random
from datetime import datetime, timedelta

from sqlalchemy.exc import DBAPIError, OperationalError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Customer, GroundTruth, Merchant, Order, Payment, RecoveryCase

MERCHANTS = [
    "Zenith Retail",
    "Bharat Mart",
    "Swift Grocers",
    "UrbanCart",
    "PixelStore",
]

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Kabir", "Ananya", "Diya", "Saanvi", "Aadhya", "Myra", "Anika",
    "Riya", "Prisha", "Kiara", "Navya", "Rohan", "Karan", "Neha", "Priya",
    "Sanya", "Rahul", "Pooja", "Vikram", "Meera", "Aisha",
]
LAST_NAMES = [
    "Sharma", "Verma", "Iyer", "Reddy", "Nair", "Gupta", "Patel", "Singh",
    "Rao", "Menon", "Kulkarni", "Bose", "Das", "Chatterjee", "Pillai",
]

PAYMENT_METHOD_WEIGHTS = {
    "upi": 0.45,
    "card": 0.30,
    "netbanking": 0.15,
    "wallet": 0.07,
    "emi": 0.03,
}

# prob = base rate a case of this kind is genuinely recoverable if handled well
# action = the recovery move that gets there
FAILURE_PROFILES = {
    "insufficient_funds": {"weight": 0.25, "prob": 0.55, "action": "retry_later"},
    "card_declined": {"weight": 0.20, "prob": 0.35, "action": "send_payment_link"},
    "otp_timeout": {"weight": 0.15, "prob": 0.88, "action": "retry_now"},
    "bank_server_error": {"weight": 0.12, "prob": 0.80, "action": "retry_now"},
    "network_error": {"weight": 0.10, "prob": 0.85, "action": "retry_now"},
    "expired_card": {"weight": 0.08, "prob": 0.30, "action": "send_payment_link"},
    "limit_exceeded": {"weight": 0.05, "prob": 0.25, "action": "retry_later"},
    "user_cancelled": {"weight": 0.03, "prob": 0.40, "action": "send_payment_link"},
    "risk_flagged": {"weight": 0.02, "prob": 0.10, "action": "escalate_human"},
}

OVERALL_FAILURE_RATE = 0.35
NOISE_FLIP_PROB = 0.08  # keep the label non-trivial to reverse-engineer
LARGE_AMOUNT_PAISE = 500_000  # > ₹5,000 — matches MAX_AUTO_RETRY_AMOUNT_PAISE

# ~1 in 14 customers has opted out of contact (DND-style). Previously every
# customer had opted_out=False, so the Day 4 policy engine had zero cases to
# prove its "never send a payment link to someone who opted out" check
# against. This cohort exists so that guardrail has something real to catch.
OPTED_OUT_PROB = 0.07

# How many times a payment had already failed *before* Vasool ever saw it —
# i.e. bank/checkout-side auto-retries that happened upstream of this
# pipeline. Weighted toward 1 (most failures are caught on the first pass);
# capped at MAX_RETRY_ATTEMPTS (see app/config.py). Previously every failed
# payment was hardcoded to attempt_number=1, which silently made the
# diminishing-returns decay in compute_ground_truth() (0.88 ** (attempt-1))
# dead code — it was written and unit-tested but never exercised by the
# actual frozen dataset.
ATTEMPT_NUMBER_WEIGHTS = {1: 0.55, 2: 0.30, 3: 0.15}


def weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def compute_ground_truth(
    rng: random.Random, failure_reason: str, attempt_number: int, amount_paise: int
) -> tuple[bool, str, str]:
    """Pure function so this logic is independently unit-testable."""
    profile = FAILURE_PROFILES[failure_reason]
    prob = profile["prob"]
    prob *= 0.88 ** (attempt_number - 1)  # diminishing returns on repeat attempts
    if amount_paise > LARGE_AMOUNT_PAISE:
        prob *= 0.92
    prob = max(0.03, min(0.97, prob))

    is_recoverable = rng.random() < prob
    flipped = rng.random() < NOISE_FLIP_PROB
    if flipped:
        is_recoverable = not is_recoverable

    if failure_reason == "risk_flagged":
        # fraud-flagged cases always need a human's eyes regardless of recoverability
        ideal_action = "escalate_human"
    elif is_recoverable:
        ideal_action = profile["action"]
    else:
        ideal_action = "no_action"

    rationale = (
        f"{failure_reason}: base_prob={profile['prob']}, attempt={attempt_number}, "
        f"adj_prob={round(prob, 3)}, noise_flipped={flipped}"
    )
    return is_recoverable, ideal_action, rationale


def random_timestamp(rng: random.Random, days_back: int = 45) -> datetime:
    delta = timedelta(
        days=rng.randint(0, days_back),
        hours=rng.randint(0, 23),
        minutes=rng.randint(0, 59),
    )
    return datetime.utcnow() - delta


def reset_data(db) -> None:
    if settings.ENV == "production":
        raise RuntimeError("Refusing to reset data with ENV=production. Aborting.")
    # FK-safe delete order (children before parents)
    for model in [GroundTruth, RecoveryCase, Payment, Order, Customer, Merchant]:
        db.query(model).delete()
    db.commit()


@retry(
    retry=retry_if_exception_type((OperationalError, DBAPIError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    reraise=True,
)
def add_and_flush(db, objects: list) -> None:
    """Add a batch of ORM objects and flush them in one round trip (SQLAlchemy
    auto-batches add_all() + a single flush() into a few multi-row INSERT
    statements instead of one INSERT per object).

    Retries up to 3 times on a transient connection drop. A failed flush
    leaves the session's transaction unusable, so on error we roll back and
    re-add the same objects before the next attempt — SQLAlchemy expunges
    pending ("new", never-flushed) objects on rollback, so they have to be
    re-added, not just re-flushed.
    """
    try:
        db.add_all(objects)
        db.flush()
    except (OperationalError, DBAPIError):
        db.rollback()
        raise


def generate(count: int, seed: int, reset: bool) -> None:
    rng = random.Random(seed)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if reset:
            print("Resetting existing synthetic data...")
            reset_data(db)

        merchants = [Merchant(name=name) for name in MERCHANTS]
        add_and_flush(db, merchants)

        num_customers = max(50, count // 3)  # repeat customers, like real life
        customers = []
        for _ in range(num_customers):
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            merchant = rng.choice(merchants)
            customers.append(Customer(
                merchant_id=merchant.id,
                name=f"{first} {last}",
                email=f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@example.com",
                phone=f"9{rng.randint(100000000, 999999999)}",
                opted_out=rng.random() < OPTED_OUT_PROB,
            ))
        add_and_flush(db, customers)
        print(f"Merchants + customers written ({len(merchants)} / {len(customers)})...")

        # ---- Build every order in memory first, then insert as one batch ----
        orders = []
        order_meta = []
        for _ in range(count):
            customer = rng.choice(customers)
            amount_paise = rng.choice(
                [rng.randint(9900, 99900), rng.randint(100000, 499900), rng.randint(500000, 1500000)]
            )
            is_failed = rng.random() < OVERALL_FAILURE_RATE
            created_at = random_timestamp(rng)
            orders.append(Order(
                merchant_id=customer.merchant_id,
                customer_id=customer.id,
                amount_paise=amount_paise,
                status="failed" if is_failed else "paid",
                created_at=created_at,
            ))
            order_meta.append({
                "is_failed": is_failed,
                "amount_paise": amount_paise,
                "created_at": created_at,
            })

        add_and_flush(db, orders)  # assigns order.id for every row, one batch
        print(f"Orders written ({len(orders)})...")

        # ---- Build every payment in memory first, then insert as one batch ----
        payments = []
        payment_meta = []
        for order, meta in zip(orders, order_meta):
            method = weighted_choice(rng, PAYMENT_METHOD_WEIGHTS)
            if meta["is_failed"]:
                failure_reason = weighted_choice(
                    rng, {k: v["weight"] for k, v in FAILURE_PROFILES.items()}
                )
                attempt_number = rng.choices(
                    list(ATTEMPT_NUMBER_WEIGHTS.keys()),
                    weights=list(ATTEMPT_NUMBER_WEIGHTS.values()),
                    k=1,
                )[0]
                payments.append(Payment(
                    order_id=order.id,
                    method=method,
                    status="failed",
                    failure_reason=failure_reason,
                    attempt_number=attempt_number,
                    created_at=meta["created_at"],
                ))
                payment_meta.append({
                    "failed": True,
                    "failure_reason": failure_reason,
                    "amount_paise": meta["amount_paise"],
                })
            else:
                payments.append(Payment(
                    order_id=order.id,
                    razorpay_payment_id=f"pay_synthetic_{order.id}",
                    method=method,
                    status="success",
                    attempt_number=1,
                    created_at=meta["created_at"],
                ))
                payment_meta.append({"failed": False})

        add_and_flush(db, payments)  # assigns payment.id for every row, one batch
        print(f"Payments written ({len(payments)})...")

        # ---- Recovery cases for every failed payment ----
        failed_payment_rows = []  # (payment, failure_reason, amount_paise)
        cases = []
        for payment, meta in zip(payments, payment_meta):
            if meta["failed"]:
                cases.append(RecoveryCase(
                    payment_id=payment.id, status="detected", created_at=payment.created_at
                ))
                failed_payment_rows.append((payment, meta["failure_reason"], meta["amount_paise"]))
        add_and_flush(db, cases)
        print(f"Recovery cases written ({len(cases)})...")

        # 80/20 split, assigned after shuffling so it isn't correlated with
        # insertion order or failure reason
        shuffled = failed_payment_rows[:]
        rng.shuffle(shuffled)
        split_index = int(len(shuffled) * 0.8)
        holdout_payment_ids = {p.id for p, _, _ in shuffled[split_index:]}

        ground_truths = []
        recoverable_count = 0
        for payment, failure_reason, amount_paise in failed_payment_rows:
            is_recoverable, ideal_action, rationale = compute_ground_truth(
                rng, failure_reason, payment.attempt_number, amount_paise
            )
            recoverable_count += int(is_recoverable)
            eval_split = "holdout" if payment.id in holdout_payment_ids else "dev"
            ground_truths.append(GroundTruth(
                payment_id=payment.id,
                is_recoverable=is_recoverable,
                ideal_action=ideal_action,
                eval_split=eval_split,
                rationale=rationale,
            ))
        add_and_flush(db, ground_truths)

        db.commit()

        total_failed = len(failed_payment_rows)
        print(f"Merchants:        {len(merchants)}")
        print(f"Customers:        {len(customers)}")
        print(f"Orders:           {count}")
        print(f"Failed payments:  {total_failed} ({total_failed / count:.1%})")
        print(
            f"Ground truth:     {recoverable_count} recoverable "
            f"({recoverable_count / total_failed:.1%}), "
            f"{total_failed - recoverable_count} not"
        )
        print(f"Split:            {split_index} dev / {total_failed - split_index} holdout")
        print(f"Seed:             {seed} (frozen — don't change without a reason)")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Vasool transaction data.")
    parser.add_argument("--count", type=int, default=1500, help="number of orders to generate")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (keep fixed once frozen)")
    parser.add_argument("--reset", action="store_true", help="wipe existing data first")
    args = parser.parse_args()
    generate(count=args.count, seed=args.seed, reset=args.reset)


if __name__ == "__main__":
    main()