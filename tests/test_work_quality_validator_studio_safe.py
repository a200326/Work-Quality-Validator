"""
Direct-mode tests for the Studio-safe WorkQualityValidator (JSON-string
state, no TreeMap-of-dataclass). Matches contracts/work_quality_validator_studio_safe.py
exactly — get_contract returns a JSON string, amounts/scores are stored
as strings/ints inside that JSON, not as native u256/dataclass fields.

The contract's submit_work uses gl.eq_principle.prompt_comparative: each
simulated validator independently re-fetches the delivery and calls the
LLM via gl.nondet.exec_prompt. direct_vm.mock_llm mocks that underlying
call, so every validator in these tests receives the identical mocked
response — which is naturally judged "equivalent" by prompt_comparative,
exercising the approve/needs_revision/malformed-output branches exactly
as they behave when real (differing) validator LLMs independently agree.

Run with:
    pip install genlayer-test
    gltest --mode direct
"""

import json
import pytest
from gltest import get_contract_factory, get_default_account, create_account


GOOD_EVAL = json.dumps({"score": 92, "issues": []})
BAD_EVAL = json.dumps({"score": 33, "issues": ["Has unit tests", "Matches the spec"]})
WEI = 10**18


@pytest.fixture
def parties():
    client = get_default_account()
    freelancer = create_account()
    impostor = create_account()
    return client, freelancer, impostor


@pytest.fixture
def contract(direct_vm):
    factory = get_contract_factory("WorkQualityValidator")
    return factory.deploy()


def _create(contract, client, freelancer, amount_gen=50, threshold=80, deadline=1767225600):
    return contract.create_contract(
        args=[
            freelancer.address,
            ["Code compiles", "Has unit tests", "Matches the spec"],
            threshold,
            deadline,
        ],
        value=amount_gen * WEI,
        sender=client,
    )


def _contract_state(contract, contract_id):
    return json.loads(contract.get_contract(args=[contract_id]).call())


# ------------------------------------------------------------------
# Happy paths (already verified live on Studio; re-asserted here so
# regressions are caught locally before redeploying)
# ------------------------------------------------------------------

def test_approved_and_withdrawable_when_score_clears_threshold(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer, threshold=10)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "def solve(): return 42"})
    direct_vm.mock_llm(r".*", GOOD_EVAL)
    contract.submit_work(args=[contract_id, "https://example.com/delivery.py"], sender=freelancer)

    state = _contract_state(contract, contract_id)
    assert state["status"] == "approved"
    assert contract.get_balance(args=[freelancer.address]).call() == 50 * WEI

    contract.withdraw(sender=freelancer)
    assert contract.get_balance(args=[freelancer.address]).call() == 0


def test_needs_revision_then_resubmit_succeeds(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer, threshold=80)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "def solve(): pass"})
    direct_vm.mock_llm(r".*", BAD_EVAL)
    contract.submit_work(args=[contract_id, "https://example.com/v1.py"], sender=freelancer)

    state = _contract_state(contract, contract_id)
    assert state["status"] == "needs_revision"
    assert state["revisions"] == 1
    assert "Has unit tests" in state["issues"]

    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*", {"status": 200, "body": "def solve(): return 42  # with tests now"})
    direct_vm.mock_llm(r".*", GOOD_EVAL)
    contract.submit_work(args=[contract_id, "https://example.com/v2.py"], sender=freelancer)

    state = _contract_state(contract, contract_id)
    assert state["status"] == "approved"


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

def test_only_assigned_freelancer_can_submit(direct_vm, contract, parties):
    client, freelancer, impostor = parties
    tx = _create(contract, client, freelancer)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "irrelevant"})
    direct_vm.mock_llm(r".*", GOOD_EVAL)

    with direct_vm.expect_revert("only the assigned freelancer"):
        contract.submit_work(args=[contract_id, "https://example.com/x.py"], sender=impostor)


def test_cannot_submit_to_nonexistent_contract(direct_vm, contract, parties):
    _, freelancer, _ = parties
    with direct_vm.expect_revert("contract does not exist"):
        contract.submit_work(args=[999, "https://example.com/x.py"], sender=freelancer)


def test_cannot_submit_twice_while_approved(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer, threshold=10)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "ok"})
    direct_vm.mock_llm(r".*", GOOD_EVAL)
    contract.submit_work(args=[contract_id, "https://example.com/x.py"], sender=freelancer)

    with direct_vm.expect_revert("not open for submission"):
        contract.submit_work(args=[contract_id, "https://example.com/y.py"], sender=freelancer)


def test_client_can_cancel_and_reclaim_escrow(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer, amount_gen=25)
    contract_id = tx.return_value

    contract.cancel_contract(args=[contract_id], sender=client)

    state = _contract_state(contract, contract_id)
    assert state["status"] == "cancelled"
    assert contract.get_balance(args=[client.address]).call() == 25 * WEI

    contract.withdraw(sender=client)
    assert contract.get_balance(args=[client.address]).call() == 0


def test_only_client_can_cancel(direct_vm, contract, parties):
    client, freelancer, impostor = parties
    tx = _create(contract, client, freelancer)
    contract_id = tx.return_value

    with direct_vm.expect_revert("only the client may cancel"):
        contract.cancel_contract(args=[contract_id], sender=impostor)


def test_cannot_cancel_after_approval(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer, threshold=10)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "ok"})
    direct_vm.mock_llm(r".*", GOOD_EVAL)
    contract.submit_work(args=[contract_id, "https://example.com/x.py"], sender=freelancer)

    with direct_vm.expect_revert("already been approved"):
        contract.cancel_contract(args=[contract_id], sender=client)


def test_create_contract_rejects_zero_escrow(direct_vm, contract, parties):
    client, freelancer, _ = parties
    with direct_vm.expect_revert("escrow amount must be greater than zero"):
        _create(contract, client, freelancer, amount_gen=0)


def test_create_contract_rejects_empty_rubric(direct_vm, contract, parties):
    client, freelancer, _ = parties
    with direct_vm.expect_revert("rubric must contain at least one criterion"):
        contract.create_contract(
            args=[freelancer.address, [], 80, 1767225600],
            value=10 * WEI,
            sender=client,
        )


def test_create_contract_rejects_out_of_range_threshold(direct_vm, contract, parties):
    client, freelancer, _ = parties
    with direct_vm.expect_revert("threshold must be between 0 and 100"):
        contract.create_contract(
            args=[freelancer.address, ["Code compiles"], 150, 1767225600],
            value=10 * WEI,
            sender=client,
        )


def test_withdraw_with_nothing_owed_reverts(direct_vm, contract, parties):
    _, freelancer, _ = parties
    with direct_vm.expect_revert("nothing to withdraw"):
        contract.withdraw(sender=freelancer)


def test_malformed_llm_output_reverts_instead_of_corrupting_state(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "some delivery"})
    direct_vm.mock_llm(r".*", "not valid json at all")

    with direct_vm.expect_revert("malformed evaluation JSON"):
        contract.submit_work(args=[contract_id, "https://example.com/x.py"], sender=freelancer)

    # state must still show "submitted", not something corrupted
    state = _contract_state(contract, contract_id)
    assert state["status"] == "submitted"


def test_llm_output_missing_required_keys_reverts(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "some delivery"})
    direct_vm.mock_llm(r".*", json.dumps({"score": 90}))  # missing "issues"

    with direct_vm.expect_revert("missing required keys"):
        contract.submit_work(args=[contract_id, "https://example.com/x.py"], sender=freelancer)


def test_score_is_clamped_to_0_100_range(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer, threshold=10)
    contract_id = tx.return_value

    direct_vm.mock_web(r".*", {"status": 200, "body": "ok"})
    direct_vm.mock_llm(r".*", json.dumps({"score": 500, "issues": []}))
    contract.submit_work(args=[contract_id, "https://example.com/x.py"], sender=freelancer)

    state = _contract_state(contract, contract_id)
    assert state["score"] == 100


def test_cannot_submit_to_cancelled_contract(direct_vm, contract, parties):
    client, freelancer, _ = parties
    tx = _create(contract, client, freelancer)
    contract_id = tx.return_value

    contract.cancel_contract(args=[contract_id], sender=client)

    with direct_vm.expect_revert("not open for submission"):
        contract.submit_work(args=[contract_id, "https://example.com/x.py"], sender=freelancer)


def test_get_contract_count_tracks_number_of_contracts(direct_vm, contract, parties):
    client, freelancer, _ = parties
    assert contract.get_contract_count().call() == 0
    _create(contract, client, freelancer)
    assert contract.get_contract_count().call() == 1
    _create(contract, client, freelancer)
    assert contract.get_contract_count().call() == 2
