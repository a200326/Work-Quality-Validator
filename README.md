# WorkQualityValidator

An Intelligent Contract on GenLayer that verifies freelance/remote-work
deliverables against a client-defined rubric using an LLM, reaches
consensus on the verdict through GenLayer's comparative Equivalence
Principle, and pays out through a pull-payment escrow once a delivery
clears the client's quality threshold.

📜 **Contract (GenLayer Studio):** `0x6eaF73f4075Be4E4145Ce9eF3053E1Ea938aE02A`
🖥️ **Dashboard (separate repo/Project submission):** https://github.com/a200326/work-quality-validator-dashboard

## The problem

On freelance platforms and crypto bounty boards, the biggest recurring
dispute is whether delivered work actually meets the agreed standard.
Today that's resolved either by slow human arbitration or a one-sided
platform decision — and it's the same problem whether the deliverable
is code, a translation, a design file, or written content.

## How it works

1. **Client** creates a contract with a plain-language rubric (e.g.
   "code compiles", "has unit tests", "matches the spec"), an escrow
   amount, and a minimum passing score.
2. **Freelancer** submits a link to their delivered work.
3. The contract fetches that content and asks the network's LLM
   validators to independently score it against the rubric.
4. If the score clears the threshold, the escrow is credited to the
   freelancer's pull-payment balance, withdrawable at any time. If not,
   the itemized issues are stored and the freelancer can revise and
   resubmit.

The same contract works for code, content, translations, or design —
only the rubric text changes.

## Consensus design

Every validator independently re-fetches the delivery URL and
independently calls the LLM to produce its own score and issues list —
via `gl.eq_principle.prompt_comparative`. A separate LLM judgment then
checks whether the leader's score is *equivalent* to each validator's
own independent score (within a 15-point tolerance) and whether the
issues describe the same underlying shortcomings. A leader score that
is clearly more lenient or harsher than an independent re-evaluation of
the same content against the same rubric is rejected as non-equivalent.

This is a deliberate design choice over the simpler
`prompt_non_comparative` + format-only criteria approach: checking only
that the leader's output is valid JSON lets any score pass consensus,
since nothing re-verifies it against the actual rubric/content. Making
validators re-derive the score independently is what turns this into a
genuine trust-minimized quality check rather than a single leader's
unverified opinion wrapped in valid JSON.

## Repo layout

```
contracts/work_quality_validator_studio_safe.py    # the Intelligent Contract
tests/test_work_quality_validator_studio_safe.py   # gltest direct-mode test suite
```

## Running the tests locally

```bash
pip install genlayer-test
gltest --mode direct
```

## Deploying your own copy

Paste `contracts/work_quality_validator_studio_safe.py` into
[GenLayer Studio](https://studio.genlayer.com/contracts) and deploy.
No constructor arguments are needed.

## Design notes

- All non-deterministic work (fetching the delivery URL, calling the
  LLM) happens inside the function passed to
  `gl.eq_principle.prompt_comparative`, per GenVM's rules for
  non-determinism.
- State is stored as JSON strings rather than `TreeMap`-of-dataclass,
  which avoids a schema-extraction issue in GenLayer Studio.
- Payment is pull-based (`withdraw()`), so a failed transfer can never
  block consensus on the evaluation itself.
- Paying out to a freelancer's wallet (an EOA) goes through an EVM
  contract interface (`@gl.evm.contract_interface`), since
  `gl.get_contract_at(...).emit_transfer` only works between two
  Intelligent Contracts.
