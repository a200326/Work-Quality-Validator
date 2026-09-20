# WorkQualityValidator

An Intelligent Contract on GenLayer that verifies freelance/remote-work
deliverables against a client-defined rubric using an LLM, reaches
consensus on the verdict through GenLayer's Equivalence Principle, and
pays out through a pull-payment escrow once a delivery clears the
client's quality threshold.

🔗 **Live dashboard:** https://a200326.github.io/Work-Quality-Validator/
📜 **Contract (GenLayer Studio):** `0x1eB3E0bc95c6b60816203401877f15b96aEeFDb1`

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
   validators to score it against the rubric, returning strict JSON
   (`{"score": 0-100, "issues": [...]}`). Every validator independently
   checks the leader's output against explicit, purely mechanical
   criteria (valid JSON, correct keys, correct types) — never against
   subjective quality judgments — so a network of different LLM
   providers can reliably reach consensus.
4. If the score clears the threshold, the escrow is credited to the
   freelancer's pull-payment balance, withdrawable at any time. If not,
   the itemized issues are stored and the freelancer can revise and
   resubmit.

The same contract works for code, content, translations, or design —
only the rubric text changes.

## Repo layout

```
index.html                                        # read-only dashboard (GitHub Pages)
contracts/work_quality_validator_studio_safe.py    # the Intelligent Contract
tests/test_work_quality_validator_studio_safe.py   # gltest direct-mode test suite
```

## Running the tests locally

```bash
pip install genlayer-test
gltest --mode direct
```

Covers the full lifecycle: approval, needs-revision → resubmit,
freelancer-only submission, escrow cancellation/refund, rejection of
invalid inputs, and safe reverting on malformed LLM output — all
without needing Studio or a live LLM call.

## Deploying your own copy

Paste `contracts/work_quality_validator_studio_safe.py` into
[GenLayer Studio](https://studio.genlayer.com/contracts) and deploy.
No constructor arguments are needed.

## Design notes

- All non-deterministic work (fetching the delivery URL, calling the
  LLM) is isolated inside `gl.eq_principle.prompt_non_comparative`, per
  GenVM's rules for non-determinism.
- State is stored as JSON strings rather than `TreeMap`-of-dataclass,
  which avoids a schema-extraction issue in GenLayer Studio.
- Payment is pull-based (`withdraw()`), so a failed transfer can never
  block consensus on the evaluation itself.
- Paying out to a freelancer's wallet (an EOA) goes through an EVM
  contract interface, since `gl.get_contract_at(...).emit_transfer`
  only works between two Intelligent Contracts.
