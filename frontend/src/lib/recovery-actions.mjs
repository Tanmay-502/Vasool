export const TERMINAL_STATUSES = new Set([
  "resolved",
  "executed",
  "partially_recovered",
  "rejected",
  "recovery_cancelled",
  "recovery_expired",
]);

export function availableActions(status, { killSwitch = false, customerOptedOut = false } = {}) {
  if (TERMINAL_STATUSES.has(status)) return [];
  if (status === "human_review") return killSwitch ? ["reject"] : ["approve", "reject"];
  if (status === "pending_execution") return killSwitch ? [] : ["execute"];
  if (status === "detected") return ["analyze"];
  if (status === "execution_failed") return ["analyze"];
  if (status === "scheduled_retry") return [];
  return customerOptedOut ? [] : [];
}

export function canReanalyze(status) {
  return !TERMINAL_STATUSES.has(status) && status !== "paid";
}
