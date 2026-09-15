import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import VasoolConsole from "@/components/VasoolConsole";

const state = { status: "detected", killSwitch: false };

const caseDetail = () => ({
  case: {
    id: 1,
    status: state.status,
    amount_paise: 50000,
    amount_inr: 500,
    currency: "INR",
    failure_reason: "insufficient_funds",
    payment_method: "upi",
    attempt_number: 1,
    customer_name: "Test Customer",
    customer_opted_out: false,
    payment_link: state.status === "executed" ? "https://example.test/pay" : null,
    outcome_amount_paise: state.status === "executed" ? 50000 : 0,
    outcome_amount_inr: state.status === "executed" ? 500 : 0,
    outcome_success: state.status === "executed",
    action_status: state.status === "executed" ? "sent" : null,
    created_at: "2026-09-15T10:00:00Z",
    updated_at: "2026-09-15T10:00:00Z",
  },
  root_cause: state.status === "detected" ? null : {
    root_cause_category: "cashflow_timing",
    reasoning: "Test diagnosis",
  },
  root_cause_meta: null,
  strategy: state.status === "detected" ? null : {
    action: "retry_now",
    reasoning: "Test strategy",
  },
  strategy_meta: null,
  policy_checks: [],
  action: state.status === "executed" ? { status: "sent", payment_link_id: "plink_test" } : null,
  outcome: state.status === "executed" ? { recovered_amount_paise: 50000, success: true } : null,
});

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

function mockFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";

    if (url.pathname === "/metrics") {
      return jsonResponse({
        total_orders: 1,
        total_failed_payments: 1,
        failure_rate_pct: 100,
        revenue_at_risk_paise: 50000,
        revenue_at_risk_inr: 500,
        revenue_recovered_paise: 0,
        revenue_recovered_inr: 0,
        recovery_rate_pct: 0,
        cases_pending_review: 0,
        resolved_cases: 0,
        partially_recovered_cases: 0,
        executed_cases: 0,
        ground_truth_recoverable_count: 1,
        ground_truth_recoverable_pct: 100,
        by_failure_reason: [],
        by_split: [],
      });
    }
    if (url.pathname === "/ready") return jsonResponse({ status: "ok", env: "test", database: "ok" });
    if (url.pathname === "/admin/kill-switch") return jsonResponse({ kill_switch_engaged: state.killSwitch });
    if (url.pathname === "/cases/recent") return jsonResponse({ entries: [] });
    if (url.pathname === "/cases" && method === "GET") return jsonResponse({ cases: [caseDetail().case] });
    if (url.pathname === "/cases/1" && method === "GET") return jsonResponse(caseDetail());

    if (url.pathname === "/cases/1/analyze" && method === "POST") {
      state.status = "human_review";
      return jsonResponse({ case_id: 1 });
    }
    if (url.pathname === "/cases/1/evaluate-policy" && method === "POST") return jsonResponse({ case_id: 1 });
    if (url.pathname === "/cases/1/review" && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { decision?: string };
      state.status = body.decision === "approve" ? "pending_execution" : "rejected";
      return jsonResponse({ case_id: 1, decision: body.decision, status: state.status });
    }
    if (url.pathname === "/cases/1/execute" && method === "POST") {
      state.status = "executed";
      return jsonResponse({ case_id: 1, action_status: "sent" });
    }
    throw new Error(`Unhandled fetch: ${method} ${url.pathname}`);
  });
}

beforeEach(() => {
  cleanup();
  state.status = "detected";
  state.killSwitch = false;
  mockFetch();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("VasoolConsole", () => {
  test("completes analyze -> review -> execute with the mocked fetch layer", async () => {
    render(<VasoolConsole />);
    fireEvent.click(await screen.findByText("CASE #1"));
    fireEvent.click(await screen.findByRole("button", { name: "Analyze" }));
    await screen.findByRole("button", { name: "Approve" });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByRole("button", { name: "Execute Test Mode" });
    fireEvent.click(screen.getByRole("button", { name: "Execute Test Mode" }));

    await waitFor(() => expect(screen.getByText("Verified recovery")).toBeTruthy());
  });

  test("kill switch disables approval and execution", async () => {
    state.status = "human_review";
    state.killSwitch = true;
    render(<VasoolConsole />);
    fireEvent.click(await screen.findByText("CASE #1"));
    expect((await screen.findByRole("button", { name: "Approve" })).disabled).toBe(true);

    cleanup();
    state.status = "pending_execution";
    render(<VasoolConsole />);
    fireEvent.click(await screen.findByText("CASE #1"));
    expect((await screen.findByRole("button", { name: "Execute Test Mode" })).disabled).toBe(true);
  });

  test("terminal status hides all mutation buttons", async () => {
    state.status = "resolved";
    render(<VasoolConsole />);
    fireEvent.click(await screen.findByText("CASE #1"));

    expect(screen.queryByRole("button", { name: "Analyze" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Execute Test Mode" })).toBeNull();
  });
});
