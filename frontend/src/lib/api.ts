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

export function getMetrics() {
  return getJSON<MetricsResponse>("/metrics");
}

export function getKillSwitchStatus() {
  return getJSON<KillSwitchStatus>("/admin/kill-switch");
}

export function getHealth() {
  return getJSON<HealthResponse>("/health");
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