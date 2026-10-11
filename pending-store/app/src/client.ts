// Paying client on the reference SDK (@x402/fetch + @x402/evm exact client). For each path it
// calls the API, pays when asked (EIP-3009 USDC authorization), and records exactly what came
// back (status, PAYMENT-RESPONSE, body) next to what the chain says about that authorization.
//   XD_SERVER=http://127.0.0.1:19453 XD_RPC=<payment chain rpc> XD_OUT=<jsonl> \
//   XD_BUYER_PRIVATE_KEY=... tsx src/client.ts <path> [<path> ...]
// XD_REPEAT_ON_402=1: after a paid request answered 402, call once more, as an application that
// is told "payment required" again would.
import { appendFileSync } from "node:fs";
import { decodePaymentResponseHeader, wrapFetchWithPayment, x402Client } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { createPublicClient, http, keccak256, pad, parseAbi, toBytes, type Hex } from "viem";
import { privateKeyToAccount } from "viem/accounts";

const SERVER = (process.env.XD_SERVER ?? "http://127.0.0.1:19453").replace(/\/$/, "");
const RPC = process.env.XD_RPC ?? "http://127.0.0.1:19450";
const OUT = process.env.XD_OUT ?? "";
const LABEL = process.env.XD_LABEL ?? "client";
const REPEAT_ON_402 = process.env.XD_REPEAT_ON_402 === "1";
const key = process.env.XD_BUYER_PRIVATE_KEY as Hex | undefined;
if (!key) throw new Error("XD_BUYER_PRIVATE_KEY is required");

const account = privateKeyToAccount(key);
const chain = createPublicClient({ transport: http(RPC, { timeout: 20_000 }) });
const USDC_ABI = parseAbi([
  "function balanceOf(address) view returns (uint256)",
  "function authorizationState(address authorizer, bytes32 nonce) view returns (bool)",
]);
const AUTH_USED = keccak256(toBytes("AuthorizationUsed(address,bytes32)"));

interface Created {
  nonce: Hex;
  value: string;
  asset: Hex;
  network: string;
}
const created: Created[] = [];
const client = new x402Client();
client.setSpendControls({ maxAmountPerPayment: "$0.02" });
client.register("eip155:*", new ExactEvmScheme(account));
client.onAfterPaymentCreation(async ctx => {
  const auth = (ctx.paymentPayload.payload as { authorization?: { nonce: Hex; value: string } }).authorization;
  if (auth) {
    created.push({ nonce: auth.nonce, value: auth.value, asset: ctx.selectedRequirements.asset as Hex, network: ctx.selectedRequirements.network });
  }
});
const fetchWithPayment = wrapFetchWithPayment(fetch, client);

function record(entry: Record<string, unknown>) {
  const line = JSON.stringify({ t: new Date().toISOString(), label: LABEL, ...entry }, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
  console.log(line);
  if (OUT) appendFileSync(OUT, line + "\n");
}

let fromBlock = 0n;

async function chainFacts(p: Created) {
  const [used, logs] = await Promise.all([
    chain.readContract({ address: p.asset, abi: USDC_ABI, functionName: "authorizationState", args: [account.address, p.nonce] }),
    chain.request({
      method: "eth_getLogs",
      params: [{ address: p.asset, fromBlock: `0x${fromBlock.toString(16)}`, toBlock: "latest", topics: [AUTH_USED, pad(account.address), p.nonce] }],
    }) as Promise<{ transactionHash: Hex; blockNumber: Hex }[]>,
  ]);
  return {
    nonce: p.nonce,
    value: p.value,
    authorization_used: used,
    used_in: logs.map(l => ({ tx: l.transactionHash, block: Number(BigInt(l.blockNumber)) })),
  };
}

async function callOnce(path: string, attempt: number) {
  const before = created.length;
  const t0 = performance.now();
  const response = await fetchWithPayment(`${SERVER}${path}`, { method: "GET" });
  const ms = Math.round(performance.now() - t0);
  const text = await response.text();
  let body: unknown = text.slice(0, 4000);
  try {
    body = JSON.parse(text);
  } catch {
    /* keep text */
  }
  const header = response.headers.get("PAYMENT-RESPONSE");
  let paymentResponse: unknown = null;
  if (header) {
    try {
      paymentResponse = decodePaymentResponseHeader(header);
    } catch (error) {
      paymentResponse = { undecodable: String(error) };
    }
  }
  return { path, attempt, status: response.status, ms, payment_response: paymentResponse, body, payments: created.slice(before) };
}

async function main() {
  const paths = process.argv.slice(2);
  if (!paths.length) throw new Error("give at least one path");
  fromBlock = (await chain.getBlockNumber()) - 2n;
  record({ kind: "start", server: SERVER, buyer: account.address, rpc: RPC, from_block: fromBlock });
  let asset: Hex | undefined;
  for (const path of paths) {
    const results = [await callOnce(path, 1)];
    if (REPEAT_ON_402 && results[0].status === 402 && results[0].payments.length) results.push(await callOnce(path, 2));
    for (const r of results) {
      const facts = [];
      for (const p of r.payments) {
        asset = p.asset;
        facts.push(await chainFacts(p));
      }
      const tx = (r.payment_response as { transaction?: string } | null)?.transaction;
      record({
        kind: "call",
        path: r.path,
        attempt: r.attempt,
        status: r.status,
        ms: r.ms,
        payment_response: r.payment_response,
        body: r.body,
        payments: facts,
        tx_matches_chain: tx ? facts.some(f => f.used_in.some(u => u.tx.toLowerCase() === tx.toLowerCase())) : null,
      });
    }
  }
  if (asset) {
    const bal = await chain.readContract({ address: asset, abi: USDC_ABI, functionName: "balanceOf", args: [account.address] });
    record({ kind: "balance", asset, buyer: account.address, usdc_atomic: bal.toString() });
  }
}

main().catch(error => {
  record({ kind: "error", error: String(error?.stack ?? error) });
  process.exit(1);
});
