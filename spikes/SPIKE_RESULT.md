# Sandbox spike: hold / partial capture / void (2026-10-10, PayPal sandbox)

Result: **The mechanic works.** PayPal sandbox allows capturing less than the authorized amount. With `final_capture: true`, the rest of the hold is released.

Setup: Orders v2 `intent=AUTHORIZE`, currency SGD, the existing sandbox REST app plus the existing sandbox personal buyer. Buyer approval is automated with Playwright: headless Chrome logs in on the sandbox approval page and redirects to `https://example.com/tipping-point-test/return`. Every amount is ≤ SGD 30, and every reference is labelled `TEST-TP-*` / "TEST ONLY".

| # | Call | Result |
|---|---|---|
| 1 | `POST /v2/checkout/orders` `{intent: AUTHORIZE, amount SGD 30.00, payment_source.paypal.experience_context{return_url, cancel_url, user_action: CONTINUE, shipping_preference: NO_SHIPPING}}` | 201 `PAYER_ACTION_REQUIRED`, `payer-action` link |
| 2 | Playwright: open payer-action link → email → password → Continue | redirected to return_url (about 10 s) |
| 3 | `POST /v2/checkout/orders/{order}/authorize` `{}` | 201 `COMPLETED`; authorization `CREATED` SGD 30.00, `expiration_time` = +29 days |
| 4 | `POST /v2/payments/authorizations/{auth}/capture` `{amount: SGD 24.00, final_capture: true}` | 201 `COMPLETED`, captured **SGD 24.00** (fee SGD 1.32; converted to USD 17.45 because the sandbox merchant holds USD) |
| 5 | `GET /v2/payments/authorizations/{auth}` | `CAPTURED`. The SGD 6.00 remainder is released |
| 6 | second capture on that auth | 422 `AUTHORIZATION_ALREADY_CAPTURED` (a finalized hold can't be re-charged) |
| 7 | new order → approve → authorize SGD 30.00 → `POST /v2/payments/authorizations/{auth}/void` (no body) | 200 `VOIDED`; GET shows `VOIDED` |
| 8 | capture after void | 422 `AUTHORIZATION_VOIDED` |
| 9 | (probe 2) authorize SGD 20.00 → capture 5.00 `final_capture:false` → GET → capture 7.00 `final_capture:true` → GET | `PARTIALLY_CAPTURED` then `CAPTURED`, total 12.00 of 20.00 |
| 10 | (probe 2) `POST .../reauthorize` right after authorizing | 422 `REAUTHORIZATION_TOO_SOON` (honor-period rule enforced in sandbox) |

IDs (sandbox): partial = order 2N142544A78591119 / auth 4M433596FE6946146 / capture 1HM53854JY192312P; void = order 1CB658795B719083N / auth 3MX353074B494031R; multi = order 5JX0957467369560E / auth 8HT85367T9792030X.
Full redacted logs (no tokens; includes paypal-debug-id): `spikes/out/spike_*.json`, `spikes/out/probe2_*.json`.

Design consequences:
- Hold at the top-tier price (or the most a buyer could owe). Capture at the final tier price with `final_capture:true`.
- A buyer who *raises* their quantity after the hold needs a new top-up hold, because one capture can't exceed the hold here. Lowering quantity is covered automatically.
- Campaigns must settle within the 3-day honor period. Reauthorize is not available inside it and can be tested only after day 3, so the deadline limit stays under 72 h.
- The sandbox merchant receives USD. A live merchant would need SGD held or auto-conversion. This is a production note, not a blocker.
- Not tested yet: live-mode fees on voided authorizations (sandbox showed none). It goes in the README as a caveat.
