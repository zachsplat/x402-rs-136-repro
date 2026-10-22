// Paying client on the reference SDK (@x402/fetch + @x402/evm exact client). For each path it
// calls the API, pays when asked (EIP-3009 USDC authorization), and records exactly what came
// back (status, PAYMENT-RESPONSE, body) next to what the chain says about that authorization.
//   XD_SERVER=http://127.0.0.1:19453 XD_RPC=<payment chain rpc> XD_OUT=<jsonl> \
//   XD_BUYER_PRIVATE_KEY=... tsx src/client.ts <path> [<path> ...]
// XD_REPEAT_ON_402=1: after a paid request answered 402, call once more, as an application that
// is told "payment required" again would.
// XD_COPIES=N: send the paid request N times with the same PAYMENT-SIGNATURE header,
// XD_COPY_GAP_MS milliseconds apart (default 0: at once), as a client that replays its own
// payment would. Copy 1 is the request the SDK sees; every copy is recorded as a call of its own.
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
const COPIES = Math.max(1, Number(process.env.XD_COPIES ?? 1) || 1);
const COPY_GAP_MS = Math.max(0, Number(process.env.XD_COPY_GAP_MS ?? 0) || 0);
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
interface CopyAnswer {
  copy: number;
  sent_after_ms: number;
  response: Response;
  ms: number;
}
let copies: Promise<CopyAnswer>[] = [];

// The fetch under the SDK: a request that carries a payment goes out COPIES times.
async function copyingFetch(input: string | URL | globalThis.Request, init?: RequestInit): Promise<Response> {
  const request = new Request(input, init);
  if (COPIES === 1 || !request.headers.has("PAYMENT-SIGNATURE")) return fetch(request);
  const t0 = performance.now();
  const send = (copy: number): Promise<CopyAnswer> => {
    const sent = performance.now();
    return fetch(request.clone()).then(response => ({
      copy,
      sent_after_ms: Math.round(sent - t0),
      response,
      ms: Math.round(performance.now() - sent),
    }));
  };
  const first = send(1);
  for (let copy = 2; copy <= COPIES; copy++) {
    if (COPY_GAP_MS) await new Promise(resolve => setTimeout(resolve, COPY_GAP_MS));
    copies.push(send(copy));
  }
  return (await first).response;
}
const fetchWithPayment = wrapFetchWithPayment(copyingFetch as typeof fetch, client);

function decodeHeader(header: string | null): unknown {
  if (!header) return null;
  try {
    return decodePaymentResponseHeader(header);
  } catch (error) {
    return { undecodable: String(error) };
  }
}

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
  const paymentResponse = decodeHeader(response.headers.get("PAYMENT-RESPONSE"));
  return { path, attempt, copy: 1, status: response.status, ms, payment_response: paymentResponse, body, payments: created.slice(before) };
}

// The answers to the other copies of the last paid request, with the payment of the first copy.
async function otherCopies(first: Awaited<ReturnType<typeof callOnce>>) {
  const answers = await Promise.all(copies);
  copies = [];
  const out = [];
  for (const a of answers) {
    const text = await a.response.text();
    let body: unknown = text.slice(0, 4000);
    try {
      body = JSON.parse(text);
    } catch {
      /* keep text */
    }
    out.push({
      ...first,
      copy: a.copy,
      sent_after_ms: a.sent_after_ms,
      status: a.response.status,
      ms: a.ms,
      payment_response: decodeHeader(a.response.headers.get("PAYMENT-RESPONSE")),
      body,
    });
  }
  return out;
}

async function main() {
  const paths = process.argv.slice(2);
  if (!paths.length) throw new Error("give at least one path");
  fromBlock = (await chain.getBlockNumber()) - 2n;
  record({ kind: "start", server: SERVER, buyer: account.address, rpc: RPC, from_block: fromBlock });
  let asset: Hex | undefined;
  for (const path of paths) {
    const results = [await callOnce(path, 1)];
    results.push(...(await otherCopies(results[0])));
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
        copy: r.copy,
        sent_after_ms: (r as { sent_after_ms?: number }).sent_after_ms,
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
