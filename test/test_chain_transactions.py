from types import SimpleNamespace

from agents.chain import ChainTransactionSubmitter, ContractRegistry
from agents.schemas import LPDecision, TraderDecision
from test.test_chain_contracts import FakeContract, scenario, write_abis


class FakeBuildFunction:
    def __init__(self, name, args):
        self.name = name
        self.args = args

    def build_transaction(self, tx_params):
        return {
            "function": self.name,
            "args": self.args,
            **tx_params,
        }


class FakeBuildFunctions:
    def __getattr__(self, name):
        def method(*args):
            return FakeBuildFunction(name, args)

        return method


class FakeBuildContract:
    def __init__(self, address):
        self.address = address
        self.functions = FakeBuildFunctions()


class FakeAccount:
    def __init__(self):
        self.signed = []

    def sign_transaction(self, transaction, private_key):
        self.signed.append((transaction, private_key))
        return SimpleNamespace(raw_transaction=b"signed-transaction")


class FakeTxEth:
    chain_id = 31337
    gas_price = 2

    def __init__(self):
        self.account = FakeAccount()
        self.sent = []
        self.contracts = {}

    def contract(self, address, abi):
        contract = FakeContract(address, abi)
        self.contracts[address] = contract
        return contract

    def get_transaction_count(self, address):
        return 7

    def get_block(self, block_name):
        assert block_name == "latest"
        return {"timestamp": 1_000}

    def send_raw_transaction(self, raw_transaction):
        self.sent.append(raw_transaction)
        return b"\x12\x34"


class FakeTxWeb3:
    def __init__(self):
        super().__init__()
        self.eth = FakeTxEth()


def transaction_submitter(tmp_path):
    write_abis(tmp_path)
    registry = ContractRegistry(scenario(), web3=FakeTxWeb3(), abi_dir=tmp_path)
    registry.pools["TECH-USD"].pool = FakeBuildContract("0xtechpool")
    registry.pools["TECH-USD"].vault = FakeBuildContract("0xtechvault")
    return ChainTransactionSubmitter(registry), registry.web3


def test_builds_swap_transaction(tmp_path):
    submitter, _ = transaction_submitter(tmp_path)

    tx = submitter.build_swap_transaction(
        "0xtrader",
        TraderDecision(
            action="SWAP",
            pool_id="TECH-USD",
            token_in="USD",
            amount_in=100,
            deadline_seconds=30,
            reason="buy",
        ),
        min_amount_out=95,
    )

    assert tx["function"] == "swap"
    assert tx["args"] == ("0xusd", 100, 95, 1_030)
    assert tx["from"] == "0xtrader"
    assert tx["nonce"] == 7
    assert tx["chainId"] == 31337
    assert tx["gas"] == 500_000
    assert tx["gasPrice"] == 2


def test_builds_lp_transactions(tmp_path):
    submitter, _ = transaction_submitter(tmp_path)

    add = submitter.build_add_liquidity_transaction(
        "0xlp",
        LPDecision(
            action="ADD_LIQUIDITY",
            pool_id="TECH-USD",
            amount_a=100,
            amount_b=200,
            min_lp_shares=10,
            reason="add",
        ),
        tx_options={"gas": 600_000},
    )
    remove = submitter.build_remove_liquidity_transaction(
        "0xlp",
        LPDecision(action="REMOVE_LIQUIDITY", pool_id="TECH-USD", lp_shares=50, reason="remove"),
    )
    collect = submitter.build_collect_fees_transaction(
        "0xlp",
        LPDecision(action="COLLECT_FEES", pool_id="TECH-USD", lp_shares=25, reason="collect"),
    )

    assert add["function"] == "addLiquidity"
    assert add["args"] == (100, 200, 10)
    assert add["gas"] == 600_000
    assert remove["function"] == "removeLiquidity"
    assert remove["args"] == (50,)
    assert collect["function"] == "collectFees"
    assert collect["args"] == (25,)


def test_signs_and_submits_without_portfolio_mutation(tmp_path):
    submitter, web3 = transaction_submitter(tmp_path)
    tx = {"to": "0xtechpool", "value": 0}

    tx_hash = submitter.sign_and_submit(tx, "0xprivate")

    assert tx_hash == "0x1234"
    assert web3.eth.account.signed == [(tx, "0xprivate")]
    assert web3.eth.sent == [b"signed-transaction"]
