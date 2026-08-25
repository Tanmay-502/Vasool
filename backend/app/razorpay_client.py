"""
Thin Razorpay Test Mode client for Day 4 execution.

Uses the Payment Links API (POST https://api.razorpay.com/v1/payment_links)
— confirmed against current Razorpay docs (Aug 2026). This is Razorpay's own
recommended path for recovering a failed payment: there's no API to "retry"
a specific failed charge, so instead you create a fresh payment link for the
same amount and the customer completes it. All three of our auto-executable
actions (retry_now, retry_later, send_payment_link) call this same endpoint
— they differ only in `notify` (whether Razorpay itself emails/SMSs the
customer), set by the caller (app/executor.py), not by this client.

Idempotency: `reference_id` must be unique per Payment Link on Razorpay's
side — creating a second link with a reference_id that already exists is
rejected. We pass Action.idempotency_key (a uuid4 hex, 32 chars) as
reference_id, so a retried execution call reuses the same link instead of
minting a duplicate. Razorpay's stated limit is 40 chars for this field —
32 fits with room to spare.

KNOWN TEST-MODE CONSTRAINT, confirmed in docs: Razorpay caps Test Mode at
30 Payment Links per business. Do not batch-execute the full 500+ case
synthetic dataset against this client — pick a small curated set for demos
and shadow-mode/dry-run the rest (see PROGRESS.md Day 6).

Raises RazorpayError for any failure — missing keys, network error,
timeout, non-2xx — same single-exception-type pattern as AgentTierError in
app/agents/llm_clients.py, so callers only ever need to catch one thing.
"""
import httpx

from app.config import settings

RAZORPAY_PAYMENT_LINKS_URL = "https://api.razorpay.com/v1/payment_links"


class RazorpayError(Exception):
    """Raised for any Razorpay call failure — missing keys, network error,
    timeout, or non-2xx response."""


class RazorpayClient:
    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        timeout: float | None = None,
    ):
        self.key_id = key_id if key_id is not None else settings.RAZORPAY_KEY_ID
        self.key_secret = key_secret if key_secret is not None else settings.RAZORPAY_KEY_SECRET
        self.timeout = timeout or settings.AGENT_TIMEOUT_SECONDS

    def create_payment_link(
        self,
        *,
        amount_paise: int,
        reference_id: str,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        notify: bool,
        currency: str = "INR",
    ) -> dict:
        if not self.key_id or not self.key_secret:
            raise RazorpayError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not configured")

        body = {
            "amount": amount_paise,
            "currency": currency,
            "reference_id": reference_id,
            "description": "Vasool automated payment recovery",
            "customer": {
                "name": customer_name,
                "email": customer_email,
                "contact": customer_phone,
            },
            "notify": {"sms": notify, "email": notify},
            "reminder_enable": notify,
        }

        try:
            resp = httpx.post(
                RAZORPAY_PAYMENT_LINKS_URL,
                json=body,
                auth=(self.key_id, self.key_secret),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise RazorpayError(f"Razorpay call failed: {exc}") from exc