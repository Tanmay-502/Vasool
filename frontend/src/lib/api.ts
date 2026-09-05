import type { AuditEntry } from "@/components/AuditLedger";

export type FailureReasonBreakdown = {
  reason: string;
  count: number;
  amount_at_risk_paise: number;
};

export type SplitBreakdown = {
  eval_split: string;
  count: number;
};

export type MetricsResponse = {
  total_orders: number;
  total_failed_payments: number;
  failure_rate_pct: number;
  revenue_at_risk_paise: number;
  revenue_at_risk_inr: number;
  revenue_recovered_paise: number;
  revenue_recovered_inr: number;
  recovery_rate_pct: number;
  cases_pending_review: number;
  ground_truth_recoverable_count: number;
  ground_truth_recoverable_pct: number;
  by_failure_reason: FailureReasonBreakdown[];
  by_split: SplitBreakdown[];
};

export type KillSwitchStatus = {
  kill_switch_engaged: boolean;
};

export type HealthResponse = {
  status: string;
  env: string;
};

export type AuditLedgerEntry = {
  id: number;
  case_id: number;
  event_type: string;
  detail: string;
  created_at: string;
};

export type AuditLedgerApiResponse = {
  entries: AuditLedgerEntry[];
};

export type CaseSummary = {
  id: number;
  status: string;
  amount_paise: number;
  amount_inr: number;
  currency: string;
  failure_reason: string;
  payment_method: string;
  attempt_number: number;
  customer_name: string;
  customer_opted_out: boolean;
  created_at: string;
  updated_at: string;
};

export type PolicyCheck = { check_name: string; passed: boolean; reason: string };
export type CaseDetail = {
  case: CaseSummary;
  root_cause: { root_cause_category?: string; is_transient?: boolean; reasoning?: string; confidence?: number } | null;
  root_cause_meta: { confidence: number; model_used: string; latency_ms: number | null } | null;
  strategy: { action?: string; reasoning?: string; confidence?: number } | null;
  strategy_meta: { confidence: number; model_used: string; latency_ms: number | null } | null;
  policy_checks: PolicyCheck[];
};

export type CasesResponse = { cases: CaseSummary[] };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function getJSON<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function postJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  const body = (await res.json().catch(() => null)) as { detail?: string } | T | null;
  if (!res.ok) {
    throw new Error(
      body && typeof body === "object" && "detail" in body
        ? body.detail ?? `Request failed (${res.status})`
        : `Request failed (${res.status})`,
    );
  }
  return body as T;
}

export function getMetrics() {
  return getJSON<MetricsResponse>("/metrics");
}

export function getKillSwitchStatus() {
  return getJSON<KillSwitchStatus>("/admin/kill-switch");
}

export function getHealth() {
  return getJSON<HealthResponse>("/health");
}

export function getCases() {
  return getJSON<CasesResponse>("/cases");
}

export function getCase(caseId: number) {
  return getJSON<CaseDetail>(`/cases/${caseId}`);
}

export function analyzeCase(caseId: number) {
  return postJSON<Record<string, unknown>>(`/cases/${caseId}/analyze?force=true`);
}

export function evaluatePolicy(caseId: number) {
  return postJSON<Record<string, unknown>>(`/cases/${caseId}/evaluate-policy`);
}

export function setKillSwitch(engaged: boolean) {
  return postJSON<KillSwitchStatus>(`/admin/kill-switch/${engaged ? "engage" : "disengage"}`);
}

export async function getRecentCases(): Promise<AuditEntry[]> {
  const data = await getJSON<AuditLedgerApiResponse>("/cases/recent");
  if (!data) return [];
  return data.entries.map((entry) => ({
    id: entry.id,
    timestamp: entry.created_at,
    caseId: entry.case_id,
    eventType: entry.event_type,
    detail: entry.detail,
  }));
}

export function formatINR(amount: number, opts: { compact?: boolean } = {}) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: opts.compact ? 1 : 0,
    notation: opts.compact ? "compact" : "standard",
  }).format(amount);
}