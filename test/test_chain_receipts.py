from agents.chain import ContractRegistry, ExecutionResult, ReceiptVerifier, TimeExhausted
from test.test_chain_contracts import FakeContract, scenario, write_abis


class FakeEventProcessor:
    def __init__(self, logs):
        self.logs = logs

    def __call__(self):
        return self

    def process_receipt(self, receipt):
        return self.logs


class FakeEvents:
    def __init__(self, event_logs):
        self.event_logs = event_logs

    def __getattr__(self, name):
        return FakeEventProcessor(self.event_logs.get(name, []))


class FakeEventContract:
    def __init__(self, address, event_logs):
        self.address = address
        self.events = FakeEvents(event_logs)


class FakeReceiptEth:
    def __init__(self, receipt=None, raises_timeout=False):
        self.receipt = receipt
        self.raises_timeout = raises_timeout
        self.contracts = {}

    def contract(self, address, abi):
        contract = FakeContract(address, abi)
        self.contracts[address] = contract
        return contract

    def wait_for_transaction_receipt(self, tx_hash, timeout, poll_latency):
        if self.raises_timeout:
            raise TimeExhausted("timed out")
        return self.receipt


class FakeReceiptWeb3:
    def __init__(self, receipt=None, raises_timeout=False):
        super().__init__()
        self.eth = FakeReceiptEth(receipt=receipt, raises_timeout=raises_timeout)


def receipt_verifier(tmp_path, *, receipt, pool_events=None, vault_events=None, raises_timeout=False):
    write_abis(tmp_path)
    registry = ContractRegistry(
        scenario(),
        web3=FakeReceiptWeb3(receipt=receipt, raises_timeout=raises_timeout),
        abi_dir=tmp_path,
    )
    registry.pools["TECH-USD"].pool = FakeEventContract("0xtechpool", pool_events or {})
    registry.pools["TECH-USD"].vault = FakeEventContract("0xtechvault", vault_events or {})
    return ReceiptVerifier(registry)


def test_execution_result_is_defined():
    result = ExecutionResult(status="PENDING", tx_hash="0xabc", action="SWAP")

    assert result.status == "PENDING"
    assert result.tx_hash == "0xabc"


def test_receipt_verifier_confirms_successful_receipt_with_expected_event(tmp_path):
    verifier = receipt_verifier(
        tmp_path,
        receipt={"status": 1},
        pool_events={
            "Swap": [
                {
                    "args": {
                        "trader": "0xtrader",
                        "tokenIn": "0xusd",
                        "amountIn": 100,
                        "amountOut": 95,
                    }
                }
            ]
        },
    )

    result = verifier.verify_swap("0xtx", "TECH-USD", timeout=1)

    assert result.status == "CONFIRMED"
    assert result.event_name == "Swap"
    assert result.event_data == {
        "trader": "0xtrader",
        "tokenIn": "0xusd",
        "amountIn": 100,
        "amountOut": 95,
    }


def test_receipt_verifier_rejects_reverted_receipt(tmp_path):
    verifier = receipt_verifier(tmp_path, receipt={"status": 0})

    result = verifier.verify_swap("0xtx", "TECH-USD", timeout=1)

    assert result.status == "REJECTED"
    assert result.reason == "transaction reverted"


def test_receipt_verifier_rejects_successful_receipt_missing_expected_event(tmp_path):
    verifier = receipt_verifier(tmp_path, receipt={"status": 1}, pool_events={"LiquidityAdded": [{"args": {}}]})

    result = verifier.verify_swap("0xtx", "TECH-USD", timeout=1)

    assert result.status == "REJECTED"
    assert result.reason == "missing expected event: Swap"


def test_receipt_verifier_returns_pending_when_receipt_times_out(tmp_path):
    verifier = receipt_verifier(tmp_path, receipt=None, raises_timeout=True)

    result = verifier.verify_swap("0xtx", "TECH-USD", timeout=1)

    assert result.status == "PENDING"
    assert result.reason == "receipt unavailable"


def test_receipt_verifier_extracts_lp_event_data(tmp_path):
    verifier = receipt_verifier(
        tmp_path,
        receipt={"status": 1},
        vault_events={"FeesCollected": [{"args": {"lp": "0xlp", "feesA": 3, "feesB": 4}}]},
    )

    result = verifier.verify_collect_fees("0xtx", "TECH-USD", timeout=1)

    assert result.status == "CONFIRMED"
    assert result.event_data == {"lp": "0xlp", "feesA": 3, "feesB": 4}
