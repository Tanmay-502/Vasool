import test from "node:test";
import assert from "node:assert/strict";

import { TERMINAL_STATUSES, availableActions, canReanalyze } from "../src/lib/recovery-actions.mjs";

test("terminal states expose no mutation actions", () => {
  for (const status of TERMINAL_STATUSES) {
    assert.deepEqual(availableActions(status), []);
    assert.equal(canReanalyze(status), false);
  }
});

test("detected cases expose only analysis", () => {
  assert.deepEqual(availableActions("detected"), ["analyze"]);
  assert.equal(canReanalyze("detected"), true);
});

test("human review requires an approval decision unless paused", () => {
  assert.deepEqual(availableActions("human_review"), ["approve", "reject"]);
  assert.deepEqual(availableActions("human_review", { killSwitch: true }), ["reject"]);
});

test("pending execution cannot execute while kill switch is engaged", () => {
  assert.deepEqual(availableActions("pending_execution"), ["execute"]);
  assert.deepEqual(availableActions("pending_execution", { killSwitch: true }), []);
});

test("scheduled retries expose no immediate mutation action", () => {
  assert.deepEqual(availableActions("scheduled_retry"), []);
});
