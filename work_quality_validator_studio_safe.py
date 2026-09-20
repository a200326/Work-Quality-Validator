# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }


from genlayer import *
import json


# Sending GEN to a plain wallet address (EOA) is modeled as an external
# message to an EVM-layer interface. gl.get_contract_at(...).emit_transfer
# only works between two Intelligent Contracts — it is NOT valid for
# paying out to a freelancer's/client's regular wallet address.
@gl.evm.contract_interface
class _Payee:
    class View:
        pass

    class Write:
        pass


class WorkQualityValidator(gl.Contract):
    contracts: str  # JSON: {"<id>": {...WorkContract fields...}}
    balances: str  # JSON: {"<address>": "<amount as string>"}
    next_id: str  # stringified integer

    def __init__(self):
        self.contracts = "{}"
        self.balances = "{}"
        self.next_id = "0"

    # ------------------------------------------------------------------
    # Client creates a contract and escrows GEN in the same transaction
    # ------------------------------------------------------------------
    @gl.public.write.payable
    def create_contract(
        self,
        freelancer: str,
        rubric: list[str],
        threshold: int,
        deadline: int,
    ) -> int:
        amount = int(gl.message.value)
        if amount == 0:
            raise gl.vm.UserError("escrow amount must be greater than zero")
        if len(rubric) == 0:
            raise gl.vm.UserError("rubric must contain at least one criterion")
        if threshold < 0 or threshold > 100:
            raise gl.vm.UserError("threshold must be between 0 and 100")

        contracts = json.loads(self.contracts)
        contract_id = int(self.next_id)

        contracts[str(contract_id)] = {
            "client": str(gl.message.sender_address),
            "freelancer": freelancer,
            "rubric": "\n".join(f"- {c}" for c in rubric),
            "amount": str(amount),
            "threshold": threshold,
            "deadline": deadline,
            "delivery_url": "",
            "status": "open",
            "score": 0,
            "issues": "",
            "revisions": 0,
        }

        self.contracts = json.dumps(contracts, sort_keys=True)
        self.next_id = str(contract_id + 1)
        return contract_id

    # ------------------------------------------------------------------
    # Freelancer submits (or resubmits) a delivery URL for evaluation
    # ------------------------------------------------------------------
    @gl.public.write
    def submit_work(self, contract_id: int, delivery_url: str) -> None:
        contracts = json.loads(self.contracts)
        key = str(contract_id)
        if key not in contracts:
            raise gl.vm.UserError("contract does not exist")

        work = contracts[key]
        sender = str(gl.message.sender_address)

        if sender != work["freelancer"]:
            raise gl.vm.UserError("only the assigned freelancer may submit work")
        if work["status"] not in ("open", "needs_revision"):
            raise gl.vm.UserError(f"contract is not open for submission (status: {work['status']})")

        work["delivery_url"] = delivery_url
        work["status"] = "submitted"
        contracts[key] = work
        self.contracts = json.dumps(contracts, sort_keys=True)

        rubric_text = work["rubric"]
        threshold = int(work["threshold"])

        def get_input() -> str:
            page = gl.nondet.web.render(delivery_url, mode="text")
            return (
                f"RUBRIC (each line is a required criterion):\n{rubric_text}\n\n"
                f"SUBMITTED WORK CONTENT:\n{page[:12000]}"
            )

        raw_result = gl.eq_principle.prompt_non_comparative(
            get_input,
            task=(
                "Evaluate the submitted work strictly against the rubric. "
                "Respond with ONLY a single JSON object, no prose before or "
                "after it, in exactly this shape: "
                '{"score": <integer 0-100>, "issues": ["<short issue>", ...]}. '
                "score reflects the percentage of rubric criteria that are "
                "clearly satisfied. issues lists, in a few words each, every "
                "criterion that is not satisfied. If everything is satisfied, "
                "issues must be an empty list."
            ),
            criteria="""
                The response is valid JSON and nothing else (no markdown
                fences, no commentary before or after the JSON object)
                The JSON object has exactly two keys: "score" and "issues"
                "score" is an integer between 0 and 100 inclusive
                "issues" is a list of strings (an empty list is valid)
            """,
        )

        parsed = self._parse_evaluation(raw_result)
        score = parsed["score"]
        issues = parsed["issues"]

        contracts = json.loads(self.contracts)
        work = contracts[key]
        work["score"] = score
        work["issues"] = "\n".join(f"- {i}" for i in issues) if issues else ""

        balances = json.loads(self.balances)
        if score >= threshold:
            work["status"] = "approved"
            freelancer = work["freelancer"]
            balances[freelancer] = str(int(balances.get(freelancer, "0")) + int(work["amount"]))
        else:
            work["status"] = "needs_revision"
            work["revisions"] = int(work["revisions"]) + 1

        contracts[key] = work
        self.contracts = json.dumps(contracts, sort_keys=True)
        self.balances = json.dumps(balances, sort_keys=True)

    def _parse_evaluation(self, raw: str) -> dict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            data = json.loads(cleaned)
        except Exception:
            raise gl.vm.UserError("validator consensus returned malformed evaluation JSON")

        if "score" not in data or "issues" not in data:
            raise gl.vm.UserError("evaluation JSON missing required keys")

        score = int(data["score"])
        score = max(0, min(100, score))
        issues = [str(i) for i in data["issues"]]
        return {"score": score, "issues": issues}

    # ------------------------------------------------------------------
    # Client can cancel an unfinished contract and reclaim escrow
    # ------------------------------------------------------------------
    @gl.public.write
    def cancel_contract(self, contract_id: int) -> None:
        contracts = json.loads(self.contracts)
        key = str(contract_id)
        if key not in contracts:
            raise gl.vm.UserError("contract does not exist")

        work = contracts[key]
        sender = str(gl.message.sender_address)
        if sender != work["client"]:
            raise gl.vm.UserError("only the client may cancel this contract")
        if work["status"] in ("approved", "paid"):
            raise gl.vm.UserError("cannot cancel a contract that has already been approved")

        balances = json.loads(self.balances)
        balances[work["client"]] = str(int(balances.get(work["client"], "0")) + int(work["amount"]))
        work["status"] = "cancelled"
        contracts[key] = work

        self.contracts = json.dumps(contracts, sort_keys=True)
        self.balances = json.dumps(balances, sort_keys=True)

    # ------------------------------------------------------------------
    # Pull-payment withdrawal
    # ------------------------------------------------------------------
    @gl.public.write
    def withdraw(self) -> None:
        payee = str(gl.message.sender_address)
        balances = json.loads(self.balances)
        owed = int(balances.get(payee, "0"))
        if owed == 0:
            raise gl.vm.UserError("nothing to withdraw")

        balances[payee] = "0"
        self.balances = json.dumps(balances, sort_keys=True)

        recipient = gl.message.sender_address
        _Payee(recipient).emit_transfer(value=u256(owed))

    # ------------------------------------------------------------------
    # Read-only views
    # ------------------------------------------------------------------
    @gl.public.view
    def get_contract(self, contract_id: int) -> str:
        contracts = json.loads(self.contracts)
        key = str(contract_id)
        if key not in contracts:
            raise gl.vm.UserError("contract does not exist")
        return json.dumps(contracts[key])

    @gl.public.view
    def get_balance(self, address: str) -> int:
        balances = json.loads(self.balances)
        return int(balances.get(address, "0"))

    @gl.public.view
    def get_contract_count(self) -> int:
        return int(self.next_id)
