// Resource server for the pending-store runs, on the reference x402 SDK (@x402/express and
// @x402/core 2.28.0). One paid route, GET /v1/release-check ($0.01, x402 v2 exact, USDC),
// settled by the facilitator at XD_FACILITATOR_URL; it answers a fixed record, after work_ms
// milliseconds when the query asks for them. Every exchange with the facilitator is logged with
// its status and body, so a 202 settlement_pending and the retry that follows it are on record.
// A handler that fails answers 4xx, and the middleware does not settle.
//   XD_PAY_TO=<seller address> XD_FACILITATOR_URL=http://facilitator:8080 \
//   [XD_NETWORK=eip155:84532] [XD_PORT=4021] [XD_LOG=server.log] tsx src/server.ts
import { appendFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import express, { type NextFunction, type Request, type Response } from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { declareDiscoveryExtension } from "@x402/extensions/bazaar";
import { getAddress } from "viem";

const PAY_TO = getAddress(process.env.XD_PAY_TO ?? "");
const FACILITATOR_URL = (process.env.XD_FACILITATOR_URL ?? "").replace(/\/$/, "");
const NETWORK = (process.env.XD_NETWORK ?? "eip155:84532") as `${string}:${string}`;
const PORT = Number(process.env.XD_PORT ?? 4021);
const LOG_FILE = process.env.XD_LOG ?? "";
if (!FACILITATOR_URL) throw new Error("XD_FACILITATOR_URL is required");

function log(entry: Record<string, unknown>): void {
  const line = JSON.stringify({ t: new Date().toISOString(), ...entry });
  console.log(line);
  if (LOG_FILE) appendFileSync(LOG_FILE, line + "\n");
}

// Every exchange with the facilitator, as it answered (status and body), so a 202
// settlement_pending and the retry that follows it are on record.
const realFetch = globalThis.fetch;
globalThis.fetch = async (input: string | URL | globalThis.Request, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (!url.startsWith(FACILITATOR_URL)) return realFetch(input, init);
  const path = url.slice(FACILITATOR_URL.length);
  let nonce: string | undefined;
  if (typeof init?.body === "string" && path.startsWith("/settle")) {
    try {
      nonce = JSON.parse(init.body)?.paymentPayload?.payload?.authorization?.nonce;
    } catch {
      /* not JSON */
    }
  }
  const t0 = Date.now();
  try {
    const res = await realFetch(input, init);
    const text = await res.clone().text();
    let body: unknown = text.slice(0, 2000);
    try {
      body = JSON.parse(text);
    } catch {
      /* keep text */
    }
    if (!path.startsWith("/supported")) {
      log({ kind: "facilitator", path, status: res.status, ms: Date.now() - t0, nonce, body });
    }
    return res;
  } catch (error) {
    log({ kind: "facilitator", path, error: String(error), ms: Date.now() - t0, nonce });
    throw error;
  }
};

const facilitator = new HTTPFacilitatorClient({ url: FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(NETWORK, new ExactEvmScheme());
resourceServer.onAfterSettle(async ctx => {
  log({ kind: "settled", result: ctx.result, payer: ctx.result.payer, nonce: (ctx.paymentPayload.payload as { authorization?: { nonce?: string } }).authorization?.nonce });
});
resourceServer.onSettleFailure(async ctx => {
  log({ kind: "settle_failure", error: String(ctx.error), nonce: (ctx.paymentPayload.payload as { authorization?: { nonce?: string } }).authorization?.nonce });
});

const routes = {
  "GET /v1/release-check": {
    accepts: { scheme: "exact" as const, price: "$0.01", network: NETWORK, payTo: PAY_TO },
    description: "A fixed test record, for the x402-rs pending-settlement runs.",
    mimeType: "application/json",
    extensions: declareDiscoveryExtension({
      input: { image: "openzeppelin-relayer@30b32b1" },
      inputSchema: {
        properties: { image: { type: "string", description: "Any image reference; the answer is the same fixed record" } },
        required: ["image"],
      },
      output: { example: { image: "openzeppelin-relayer@30b32b1", record: "fixed test record" } },
    }),
  },
};

const app = express();
app.disable("x-powered-by");

app.use((req: Request, res: Response, next: NextFunction) => {
  const id = randomUUID();
  const t0 = Date.now();
  res.setHeader("X-Request-Id", id);
  res.on("finish", () => {
    log({
      kind: "request",
      id,
      method: req.method,
      path: req.path,
      query: req.query,
      status: res.statusCode,
      ms: Date.now() - t0,
      paid: Boolean(req.header("PAYMENT-SIGNATURE")),
      payment_response: res.getHeader("PAYMENT-RESPONSE") ? "set" : undefined,
    });
  });
  next();
});

app.get("/healthz", (_req, res) => res.json({ ok: true }));

app.use(paymentMiddleware(routes, resourceServer));

app.get("/v1/release-check", async (req, res) => {
  const image = String(req.query.image ?? "");
  if (!image) {
    res.status(400).json({ error: "image is required; nothing was charged" });
    return;
  }
  // work_ms: how long the handler works before it answers (at most 20 s), as a handler that
  // calls a model or fetches data would. The middleware verifies the payment before the handler
  // runs and settles it after the handler has answered.
  const work = Math.min(Math.max(Number(req.query.work_ms ?? 0) || 0, 0), 20_000);
  if (work) await new Promise(resolve => setTimeout(resolve, work));
  res.json({ image, record: "fixed test record" });
});

app.listen(PORT, "0.0.0.0", () => {
  log({ kind: "start", port: PORT, network: NETWORK, pay_to: PAY_TO, facilitator: FACILITATOR_URL });
});
