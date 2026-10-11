
### fork-fix136-20261011T213329Z (anvil fork of Base Sepolia)

`image: xd-x402-facilitator:fix136`, `labels: {"org.opencontainers.image.revision":"ec55c6269cf42c2753453243090b7db1b1feb261","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 7.6 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x89e1cf10...835f` |
| receipt-503-15s | 402 unexpected_error tx=empty | 7.3 | 200 success, 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0xa2c20124...1bab` |
| receipt-503-60s | 402 unexpected_error tx=empty | 7.3 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0xe57532dc...deb0` |
| receipt-503-60s-app-retries | 402 unexpected_error tx=empty; 200 success tx=yes | 7.3, 7.3 | 202 settlement_pending, 500 unexpected_error, 200 success | 2 x, seller +0.02 USDC | 1 | **DOUBLE_CHARGED** | `0xb5ec8c96...fc65`, `0x33f8ac8e...52d4` |
| receipt-null-60s | 402 unexpected_error tx=empty | 14.3 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0xcdad153d...6cba` |

### fork-fix136-120s-20261011T215903Z (anvil fork of Base Sepolia)

`image: xd-x402-facilitator:fix136`, `labels: {"org.opencontainers.image.revision":"ec55c6269cf42c2753453243090b7db1b1feb261","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 7.6 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xef2bfa92...4ab5` |
| receipt-503-120s | 402 unexpected_error tx=empty | 7.3 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0xa495a1d3...5065` |

### fork-pending-store-894e9d7-20261011T215157Z (anvil fork of Base Sepolia)

`image: xd-x402-facilitator:pending-store`, `labels: {"org.opencontainers.image.revision":"894e9d7290b8980431eb2c41c2271af9469d62eb","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 7.6 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xbce7f483...5824` |
| receipt-503-15s | 200 success tx=yes | 15.3 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x526a089b...234b` |
| receipt-503-60s | 402 settlement_pending tx=yes | 36.4 | 202 settlement_pending, 202 settlement_pending | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0x0b86acc5...3d9b` |
| receipt-503-60s-app-retries | 402 settlement_pending tx=yes; 200 success tx=yes | 36.4, 7.3 | 202 settlement_pending, 202 settlement_pending, 200 success | 2 x, seller +0.02 USDC | 1 | **DOUBLE_CHARGED** | `0x7baaf398...0bcd`, `0xe4e86c3e...db77` |
| receipt-null-60s | 402 settlement_pending tx=yes | 43.5 | 202 settlement_pending, 202 settlement_pending | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0x8e220e30...b381` |
| receipt-503-120s | 402 settlement_pending tx=yes | 36.4 | 202 settlement_pending, 202 settlement_pending | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0x23d286b7...76fa` |

### fork-pending-store-timeout75-20261011T221406Z (anvil fork of Base Sepolia)

`image: xd-x402-facilitator:pending-store`, `facilitator config: facilitator-fork-timeout75.json`, `labels: {"org.opencontainers.image.revision":"894e9d7290b8980431eb2c41c2271af9469d62eb","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| receipt-503-60s | 200 success tx=yes | 60.7 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x52dbdb7e...2f52` |
| receipt-null-60s | 200 success tx=yes | 60.5 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xc2117c62...5aa0` |

### fault-fix136-20261011T220619Z (Base Sepolia)

`image: xd-x402-facilitator:fix136`, `labels: {"org.opencontainers.image.revision":"ec55c6269cf42c2753453243090b7db1b1feb261","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 8.3 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | [0xe543b0c3...2d8c](https://sepolia.basescan.org/tx/0xe543b0c30044dfeadc3a288b5a64a19f2bea8c9fb6f5012167d8656d33a22d8c) |
| receipt-503-15s | 402 unexpected_error tx=empty | 8.1 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | [0xf417f27b...991e](https://sepolia.basescan.org/tx/0xf417f27b0e0caf1e246ad4bd768fa4b30821834c58c3353567ae7a012990991e) |
| receipt-503-60s | 402 unexpected_error tx=empty | 8.3 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | [0x05e18f65...0dc4](https://sepolia.basescan.org/tx/0x05e18f65b8cdbdf0365b97bddaf302240c30f0976d893702562abcc37e4d0dc4) |
| receipt-503-60s-app-retries | 402 unexpected_error tx=empty; 200 success tx=yes | 8.3, 1.2 | 202 settlement_pending, 500 unexpected_error, 200 success | 2 x, seller +0.02 USDC | 1 | **DOUBLE_CHARGED** | [0x5bedc270...23ab](https://sepolia.basescan.org/tx/0x5bedc270cb1267ffe9a0791d1d77993bae0b317c5557658135507229c6f323ab), [0x85117cb1...58bf](https://sepolia.basescan.org/tx/0x85117cb1e0e6fb74ec6ecea64f594fa629f6f896d56facf4fa8fa2fc7c7758bf) |

### fault-pending-store-20261011T221014Z (Base Sepolia)

`image: xd-x402-facilitator:pending-store`, `labels: {"org.opencontainers.image.revision":"894e9d7290b8980431eb2c41c2271af9469d62eb","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 1.4 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | [0x0d60e8af...7e20](https://sepolia.basescan.org/tx/0x0d60e8afa8e32f1903032e2838d65c55054b1d201b95ad566bf2ed13668e7e20) |
| receipt-503-15s | 200 success tx=yes | 16.1 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | [0x4e232abe...4cce](https://sepolia.basescan.org/tx/0x4e232abeef236ca34ce7e916edf4f8b87c2d96e7cf686a5b94ddf7c80b4b4cce) |
| receipt-503-60s | 402 settlement_pending tx=yes | 37.2 | 202 settlement_pending, 202 settlement_pending | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | [0x9071bf0e...fa09](https://sepolia.basescan.org/tx/0x9071bf0e073456df2664fe2d2f2246bac32641f65ba67995b9ecfc802a6afa09) |
| receipt-503-60s-app-retries | 402 settlement_pending tx=yes; 200 success tx=yes | 37.1, 1.2 | 202 settlement_pending, 202 settlement_pending, 200 success | 2 x, seller +0.02 USDC | 1 | **DOUBLE_CHARGED** | [0xd0e55369...fe61](https://sepolia.basescan.org/tx/0xd0e55369f74cbdb7ec54149999983045ff30546f044039914db3c884ad3dfe61), [0x44abefda...8511](https://sepolia.basescan.org/tx/0x44abefda3a5803b4d65b4862572e4ff333aced082db1e2a27d56f48c8f478511) |

### fork-harness-check-fix136-20261011T230843Z (anvil fork of Base Sepolia)

`image: xd-x402-facilitator:fix136`, `facilitator config: facilitator-fork.json`, `labels: {"org.opencontainers.image.revision":"ec55c6269cf42c2753453243090b7db1b1feb261","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 7.6 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xf5b5b8c7...8d10` |
| receipt-503-15s | 402 unexpected_error tx=empty | 7.3 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0x12047793...e1ab` |

### fork-harness-check-pending-store-20261011T230946Z (anvil fork of Base Sepolia)

`image: xd-x402-facilitator:pending-store`, `facilitator config: facilitator-fork.json`, `labels: {"org.opencontainers.image.revision":"894e9d7290b8980431eb2c41c2271af9469d62eb","org.opencontainers.image.source":"https://github.com/x402-rs/x402-rs"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 7.7 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xac97c140...4279` |
| receipt-503-15s | 200 success tx=yes | 15.3 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x93db8a82...3653` |

Note: in fork-fix136-20261011T213329Z the receipt-503-15s row also lists the control's `200 success` (0x89e1cf10...): that run filtered the server log by the second, and both settles fell in the same second. The fix (millisecond filter) came before every later run.
