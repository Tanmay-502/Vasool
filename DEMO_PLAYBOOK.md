# Vasool — Judge Demo Playbook

## The 2-minute story

**Problem:** failed payments are recoverable only when the merchant can diagnose the failure, choose the right intervention, respect policy, and prove the customer actually paid.

**Vasool:**

```text
Failed payment
  → AI diagnosis
  → Recovery recommendation
  → Deterministic policy
  → Human review OR controlled Test Mode execution
  → Razorpay Payment Link
  → Signed webhook
  → Verified recovery
```

## Demo sequence

### 1. Start on Overview

Point to the three numbers:

- **Revenue at risk** — the historical value of failed payments in scope.
- **Recovered** — only money represented by verified `Outcome` records.
- **Recovery rate** — recovered / historical revenue at risk.

Say: **“Vasool never calls an AI prediction revenue. Recovery is credited only after payment evidence arrives from Razorpay.”**

### 2. Pick one useful case

Prefer a case whose policy result is easy to explain in under 20 seconds.

Use **Analyze**. Show:

- AI root cause
- recommended recovery action
- confidence and model tier
- customer consent / opt-out state
- attempt number
- every policy gate

The point is not to read every field. Show that the AI proposes a structured action and the deterministic policy engine independently gates it.

### 3. Show the safety path

For a `human_review` case:

- **Reject** proves the decision is recorded.
- **Approve** moves the case to `pending_execution` only when hard gates are satisfied and the kill switch is off.

For a `pending_execution` case, use **Execute Test Mode**. Confirm the action.

### 4. Show outcome verification

After a successful Payment Link payment in Razorpay Test Mode, Razorpay sends the signed webhook to:

```text
POST /webhooks/razorpay
```

Vasool verifies the signature, deduplicates the event id, updates the case/action/payment/order/outcome state, and adds an audit event.

The dashboard then shows:

```text
Recovered
₹X recovered
Verified from webhook-backed outcome
```

### 5. End on the audit ledger

Close with:

> **“You can trace why Vasool acted, what policy allowed, what Razorpay returned, and exactly when revenue became verified.”**

## Safety rules for demo day

- Use **Razorpay Test Mode** only.
- Keep a single curated execution case ready; do not execute the whole synthetic dataset.
- Run analysis in the dashboard before execution.
- Never treat a Payment Link creation response as recovered revenue.
- If Test Mode quota or an external provider is unavailable, switch to the safe analysis/shadow path and say so explicitly.
- Keep the kill switch visible so the reviewer can see that automation can be paused immediately.

## Razorpay webhook setup

Configure a Razorpay Test Mode webhook endpoint pointing to:

```text
https://<backend-host>/webhooks/razorpay
```

Subscribe to the Payment Link events used by the Vasool recovery lifecycle:

- `payment_link.paid`
- `payment_link.partially_paid`
- `payment_link.cancelled`
- `payment_link.expired`

Store the webhook secret in `RAZORPAY_WEBHOOK_SECRET`. Do not put it in the frontend bundle.

## What not to claim

Do not claim a percentage of real-world recovery unless it comes from actual outcome records. Synthetic holdout metrics and Test Mode results must be labeled as such.
