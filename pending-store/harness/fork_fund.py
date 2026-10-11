"""Fund the facilitator signer and the buyer on the Base Sepolia anvil fork (127.0.0.1:19450).

ETH: anvil_setBalance. USDC (Base Sepolia, 0x036C...CF7e, FiatToken): its balances live in
balanceAndBlacklistStates (storage slot 9), which anvil_dealERC20 cannot find; write
keccak256(abi.encode(holder, 9)) and check balanceOf. The keys in XD_FACILITATOR_SIGNER and
XD_BUYER_PRIVATE_KEY are only used to derive the two addresses; XD_PAY_TO is the seller.
"""
import json
import os
import time

import httpx
from eth_account import Account
from eth_utils import keccak

ANVIL = os.environ.get("ANVIL", "http://127.0.0.1:19450")
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def rpc(method, params):
    for _ in range(60):
        try:
            reply = httpx.post(ANVIL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30).json()
            if "error" in reply:
                raise RuntimeError(f"{method}: {reply['error']}")
            return reply["result"]
        except httpx.HTTPError:
            time.sleep(1)
    raise RuntimeError("anvil did not answer")


def usdc_balance(holder):
    return int(rpc("eth_call", [{"to": USDC, "data": "0x70a08231" + holder[2:].lower().rjust(64, "0")}, "latest"]), 16)


facilitator = Account.from_key(os.environ["XD_FACILITATOR_SIGNER"]).address
buyer = Account.from_key(os.environ["XD_BUYER_PRIVATE_KEY"]).address
seller = os.environ["XD_PAY_TO"]
rpc("anvil_setBalance", [facilitator, hex(10**18)])
slot = "0x" + keccak(bytes.fromhex(buyer[2:].lower().rjust(64, "0") + "9".rjust(64, "0"))).hex()
rpc("anvil_setStorageAt", [USDC, slot, "0x" + hex(5_000_000)[2:].rjust(64, "0")])
print(json.dumps({
    "fork_block": int(rpc("eth_blockNumber", []), 16),
    "facilitator": facilitator, "facilitator_eth_wei": int(rpc("eth_getBalance", [facilitator, "latest"]), 16),
    "buyer": buyer, "buyer_usdc_atomic": usdc_balance(buyer),
    "seller": seller, "seller_usdc_atomic": usdc_balance(seller),
}))
