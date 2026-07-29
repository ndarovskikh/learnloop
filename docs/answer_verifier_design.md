# Answer assessment: executor and verifier

## Delegation brief — Answer verifier

**Scope.** Independently validate an executor's proposed assessment against the
question's `expected_concepts`, explanation, and source. Return a final score,
knowledge gaps, and constructive feedback for the learner. Do not generate the
next question, write student progress, or access persistence tools.

**When to act alone.** Verify every `status: "assessment_proposed"` hand-off
whose `needs_approval` is `false`.

**When to ask.** Set `needs_approval: true` when the rubric is absent or the
answer cannot be evaluated from the supplied course material.

**When to escalate.** Reject a mismatched question id or invalid score with
`status: "rejected"`; the orchestrator stops without writing progress.

**Effort budget.** One independent verification pass per answer; no retries.

## Coordination contract

The executor and verifier exchange only this structured object:

```json
{"status":"assessment_proposed","result":{"assessment":{}},"needs_approval":false}
```

The orchestrator branches on `status` and `needs_approval`, then records only a
verified result. Both roles write their hand-offs to the append-only shared
memory file `progress/agent_coordination.jsonl`.

Shared memory is the hardest coordination element to debug: an incorrect or
out-of-order record can make two otherwise correct agents appear inconsistent.
The log is append-only, timestamped, and stores the exact structured hand-off
for each role, so every final learner score can be traced back to its proposal
and verification.
