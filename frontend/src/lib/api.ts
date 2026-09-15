export type FailureReasonBreakdown = { reason: string; count: number; amount_at_risk_paise: number };
export type SplitBreakdown = { eval_split: string; count: number };
export type MetricsResponse = { total_orders: number; total_failed_payments: number; failure_rate_pct: number; revenue_at_risk_paise: number; revenue_at_risk_inr: number; revenue_recovered_paise: number; revenue_recovered_inr: number; recovery_rate_pct: number; cases_pending_review: number; resolved_cases: number; partially_recovered_cases: number; executed_cases: number; ground_truth_recoverable_count: number; ground_truth_recoverable_pct: number; by_failure_reason: FailureReasonBreakdown[]; by_split: SplitBreakdown[] };
export type KillSwitchStatus = { kill_switch_engaged: boolean };
export type HealthResponse = { status: string; env: string; database?: string };
export type AuditEntry = { id: number; timestamp: string; caseId: number; eventType: string; detail: string };
export type AuditLedgerEntry = { id: number; case_id: number; event_type: string; detail: string; created_at: string };
export type AuditLedgerApiResponse = { entries: AuditLedgerEntry[] };
export type CaseSummary = { id: number; status: string; amount_paise: number; amount_inr: number; currency: string; failure_reason: string; payment_method: string; attempt_number: number; customer_name: string; customer_opted_out: boolean; payment_link: string | null; outcome_amount_paise: number; outcome_amount_inr: number; outcome_success: boolean; action_status: string | null; created_at: string; updated_at: string };
export type PolicyCheck = { check_name: string; passed: boolean; reason: string };
export type CaseDetail = { case: CaseSummary; root_cause: { root_cause_category?: string; is_transient?: boolean; reasoning?: string; confidence?: number } | null; root_cause_meta: { confidence: number; model_used: string; latency_ms: number | null } | null; strategy: { action?: string; reasoning?: string; confidence?: number } | null; strategy_meta: { confidence: number; model_used: string; latency_ms: number | null } | null; policy_checks: PolicyCheck[]; action: { status: string; payment_link_id: string | null } | null; outcome: { recovered_amount_paise: number; success: boolean } | null };
export type CasesResponse = { cases: CaseSummary[] };

const DEFAULT_PRODUCTION_API_URL = "https://vasool-ta24.onrender.com";
const DEFAULT_LOCAL_API_URL = "http://127.0.0.1:8000";
const configuredApiUrl = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/+$/, "");
const configuredLocalhost = configuredApiUrl
  ? /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(configuredApiUrl)
  : false;
const API_URL =
  process.env.NODE_ENV === "production"
    ? configuredApiUrl && !configuredLocalhost
      ? configuredApiUrl
      : DEFAULT_PRODUCTION_API_URL
    : configuredApiUrl || DEFAULT_LOCAL_API_URL;
const API_KEY = process.env.NEXT_PUBLIC_VASOOL_API_KEY ?? "";

export class ApiRequestError extends Error {
  status: number | null;
  path: string;

  constructor(path: string, message: string, status: number | null = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.path = path;
  }
}

async function getJSON<T>(path: string): Promise<T> {
  try {
    const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
    const body = (await res.json().catch(() => null)) as { detail?: string } | T | null;
    if (!res.ok) {
      const detail = body && typeof body === "object" && body && "detail" in body ? body.detail : undefined;
      throw new ApiRequestError(path, typeof detail === "string" ? detail : `Request failed (${res.status})`, res.status);
    }
    if (body === null) throw new ApiRequestError(path, "Backend returned an empty response.");
    return body as T;
  } catch (error) {
    if (error instanceof ApiRequestError) throw error;
    throw new ApiRequestError(path, "Could not reach the Vasool backend.");
  }
}

async function postJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (init.headers instanceof Headers) init.headers.forEach((value, key) => { headers[key] = value; });
  else if (Array.isArray(init.headers)) init.headers.forEach(([key, value]) => { headers[key] = value; });
  else if (init.headers) Object.assign(headers, init.headers);
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const res = await fetch(`${API_URL}${path}`, { ...init, method: "POST", headers, });
  const body = (await res.json().catch(() => null)) as { detail?: string } | T | null;
  if (!res.ok) throw new Error(body && typeof body === "object" && "detail" in body ? body.detail ?? `Request failed (${res.status})` : `Request failed (${res.status})`);
  return body as T;
}

export function getMetrics() { return getJSON<MetricsResponse>("/metrics"); }
export function getKillSwitchStatus() { return getJSON<KillSwitchStatus>("/admin/kill-switch"); }
export function getHealth() { return getJSON<HealthResponse>("/ready"); }
export function getCases() { return getJSON<CasesResponse>("/cases"); }
export function getCase(caseId: number) { return getJSON<CaseDetail>(`/cases/${caseId}`); }
export function analyzeCase(caseId: number) { return postJSON<Record<string, unknown>>(`/cases/${caseId}/analyze`); }
export function reanalyzeCase(caseId: number) { return postJSON<Record<string, unknown>>(`/cases/${caseId}/analyze?force=true`); }
export function evaluatePolicy(caseId: number) { return postJSON<Record<string, unknown>>(`/cases/${caseId}/evaluate-policy`); }
export function executeCase(caseId: number) { return postJSON<Record<string, unknown>>(`/cases/${caseId}/execute`); }
export function reviewCase(caseId: number, decision: "approve" | "reject", note = "") { return postJSON<{ case_id: number; decision: string; status: string }>(`/cases/${caseId}/review`, { body: JSON.stringify({ decision, note }) }); }
export function setKillSwitch(engaged: boolean) { return postJSON<KillSwitchStatus>(`/admin/kill-switch/${engaged ? "engage" : "disengage"}`); }

export async function getRecentCases(): Promise<AuditEntry[]> {
  const data = await getJSON<AuditLedgerApiResponse>("/cases/recent");
  return data.entries.map((entry) => ({ id: entry.id, timestamp: entry.created_at, caseId: entry.case_id, eventType: entry.event_type, detail: entry.detail }));
}

export function formatINR(amount: number, opts: { compact?: boolean } = {}) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: opts.compact ? 1 : 0, notation: opts.compact ? "compact" : "standard" }).format(amount);
}
