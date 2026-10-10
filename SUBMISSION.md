# Devpost submission text

> Copy each section into the matching Devpost field. This header is not part of the submission.

## Name
Tipping Point

## Tagline (under 200 characters)
Group buys from a chat where nobody pays unless the group hits the minimum: PayPal holds for everyone, captured at the final tier price or released.

## Inspiration
In Singapore, group buys run on WhatsApp and Telegram: durian boxes for the block, house socks for a school, keycaps for a hobby group. The supplier only ships above a minimum quantity, and bulk tiers make it cheaper the more people join. The organiser is usually a volunteer and ends up doing three thankless jobs: turning 40 messy messages into an order list, chasing payments up front, and refunding everyone by hand when the group falls short. Paying first also makes people hesitate ("what if it doesn't happen?"), which is exactly what stops the group from reaching the minimum.

## What it does
1. **Paste the group chat** (a WhatsApp export or Telegram JSON). Each message becomes a structured order event: set, add, remove or cancel, a variant switch, "same as Jason", a maybe, a question, or an order placed for someone else. Unclear lines go to a *Needs attention* list, each with a reply drafted for the organiser.
2. **Send hold links.** Each buyer gets a PayPal link that places an **authorization hold** at the top-tier price. The money is held, not charged.
3. **Watch the group tip.** A live tier bar separates "said yes in chat" from "held with PayPal", and only holds count towards the minimum. If someone raises their order later, a **top-up hold** covers just the difference.
4. **Close and settle.** The organiser reviews and approves the exact plan:
   - **Minimum reached:** each hold is **captured at the final group price**, which is never more than the hold. PayPal releases the unused part.
   - **Minimum missed:** every hold is **voided**. Nobody paid, so there is nothing to refund.

In the demo video, 10 buyers hold SGD 2.50 a pair for house socks. The group reaches the 30-pair tier, so each authorization is captured at SGD 2.20: **SGD 75.00 held, SGD 66.00 charged, SGD 9.00 released, zero refunds.** In the second story, 17 boxes of durian puffs are promised but only 15 are held: one buyer's link is deliberately left unapproved, and the video says so. All six holds (SGD 72.00) are voided.

## How we built it: PayPal
Every payment step is a real PayPal REST API call against the **sandbox**:
- **Orders v2** `POST /v2/checkout/orders` with `intent: AUTHORIZE`: one order per buyer, plus one per top-up. The buyer approves on PayPal's own hosted page, either with a PayPal account or as a guest paying by card.
- **Orders v2** `POST /v2/checkout/orders/{id}/authorize` when the buyer returns, which creates the hold.
- **Payments v2** `POST /v2/payments/authorizations/{id}/capture` with an amount **below the authorized amount** and `final_capture: true`. This is the key mechanic: the buyer pays the tier price and PayPal releases the rest.
- **Payments v2** `POST /v2/payments/authorizations/{id}/void` when the minimum is missed.
- **Status updates:** the app polls the order and authorization (`GET`), so a buyer who approves and closes the tab is still recorded. There is also a webhook endpoint (`CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.VOIDED`) that checks signatures with `POST /v1/notifications/verify-webhook-signature`. It is covered by tests, but the local demo relies on polling, because PayPal cannot reach a laptop.
- Every money-moving call carries a deterministic **`PayPal-Request-Id`**, so retrying after a failure never charges twice. The organiser's approval is bound to a **SHA-256 hash of the plan**: if anything changes after review, the approval no longer applies.

## How we built it: AI
- The live chat reader is **Google Gemini** (`gemini-3.7-flash`, with `gemini-3.5-flash` as second choice), called through the `generateContent` API with a strict JSON response schema. It turns free-form, multi-person chat into typed order events. Our offline rules reader handles the three sample chats because we wrote rules for exactly those phrasings. Real chats vary far more ("the M one cancel, S keep", "add 4 L for Mrs Chan, she messaged me privately"), which is why the live reader is an LLM.
- **Every AI answer is checked against the chat before it can affect money.** Each event must cite a real message. The person ordering must be that message's sender, unless the sender explicitly ordered for someone they named. The variant must be one the organiser listed, and quantities must be positive. An answer that fails any check is rejected as a whole.
- **The AI never moves money.** Its output becomes an order list. A tested rules engine (minimum, tiers, holds) turns that list into a settlement plan, and a person approves that exact plan.
- **Designed to degrade, not stall.** A group buy can't wait on a busy model. If Gemini answers 429 (quota) or 503 (overloaded), or doesn't answer in time, the reader backs off, retries, then tries the second model. If that fails too, or an answer fails the checks, the app reads the chat with the rules reader instead and says so on screen. Each campaign records which reader produced its order list, and the UI shows it ("Read by Gemini" or "rules (Gemini unavailable)"). The two readers' results are never mixed.
- **How well it does:** on our three invented chats, every Gemini read that completed matched the hand-checked order list and flags exactly: 7 of 7 completed reads across both models (`spikes/gemini_check.py`), plus the two reads filmed for the video. Many other free-tier requests did not complete (429, 503 or timeouts), and those fell back to the rules reader as designed. The sample is small, so this shows the approach works on these chats, not that it is accurate in general.

## Challenges we ran into
- **Proving partial capture first.** The whole idea depends on capturing *less* than was authorized. Before writing any product code, we tested it end to end in the sandbox: hold, then a lower final capture with the rest released; and hold, then void, after which a capture is refused. We also found that reauthorizing within PayPal's 3-day honor period fails (`REAUTHORIZATION_TOO_SOON`), so campaigns are capped below 72 hours and all captures happen inside that window.
- **Top-ups.** An existing authorization can't grow when someone raises their order. A second hold covers the difference, and settlement splits that buyer's capture across both authorizations.
- **Messy chat semantics.** Is "+1" one more unit or a new order of one? Is "make it 2" a set or an add? Is an order "for my mum" an order for someone else? We pinned these down as explicit event types, with tests across three invented chats (WhatsApp Android, WhatsApp iOS and Telegram JSON).
- **Free-tier model limits.** Our first model choice was closed to new API keys, and the newer models often hit their limits (429 or 503). In one test, a lighter model gave an order to the wrong person, and the checks rejected it. The opposite happened too: a correct answer was rejected because the model wrote "Auntie Lin" for the sender "Auntie Lin (organiser)". The check now accepts the sender's own name without the bracketed part, and still rejects anyone else.
- **Failure handling.** If one capture fails partway through settlement, the campaign stays open and shows which call failed. Retrying is safe because the same request IDs are reused.

## Accomplishments we're proud of
- Multi-buyer runs in the PayPal sandbox through the real UI: every approved hold in the socks run was captured below its authorized amount, every hold in the durian run was voided, and a top-up hold was captured alongside the original one.
- 151 automated tests (rules engine, chat parsing, the AI answer checks, settlement, web flow, failure and retry), plus an opt-in test against the real sandbox.

## What we learned
Authorization holds are an under-used PayPal tool for *conditional* commerce. "Charge only if X happens, and maybe charge less" is a real need well beyond group buys.

## What's next
A hosted version, so webhooks work live; easy sharing of hold links back into the chat; minimums per variant; reminders before the deadline.

## Built with
Python, FastAPI, httpx, Pydantic, pytest, Playwright (demo buyer automation and tests), AG Grid Community, ffmpeg (demo video), PayPal REST APIs (Orders v2, Payments v2, Webhooks), Google Gemini API (`gemini-3.7-flash`, `gemini-3.5-flash`).

## AI tools used to build this project (disclosure)
I chose the problem and the product, made the design and scope decisions, and directed the work throughout. An AI coding agent, **Grok Bot**, worked under that direction. It wrote most of the code, the tests, the invented sample chats and the documentation. It also ran the PayPal sandbox integration, including the automated demo buyers, and produced the demo video: it recorded the screen with scripted browser sessions and cut it with ffmpeg. An AI video-review model gave feedback on rough cuts of the video. I reviewed the results and decided what to keep, change or cut. Separately from how it was built, the product itself uses **Google Gemini** at runtime as its chat reader, as described above. All sample chats are invented; no real people's messages were used.

## Testing instructions (for judges)
- Repo: https://github.com/whhhh1500/tipping-point (MIT licence).
- Video: https://youtu.be/kuPeHjhGwwc
- **Offline, no accounts needed:** `pip install -r requirements.txt && uvicorn tipping_point.web:app`, then open http://127.0.0.1:8000 and pick a sample chat. PayPal is simulated in-process and chats are read by the rules reader.
- **With Gemini:** add `TP_READER=gemini GEMINI_API_KEY=<your key>`. If Gemini is unavailable, the app falls back to the rules reader and shows a notice.
- **With the PayPal sandbox:** put your own sandbox REST app credentials in `~/.secrets/paypal_sandbox.env` (`PAYPAL_CLIENT_ID=…`, `PAYPAL_CLIENT_SECRET=…`) and run with `PAYPAL_MODE=sandbox`. Buyers can approve as PayPal guests with the sandbox test card 4111 1111 1111 1111, any future expiry and CVV 123. The "Play buyers" button automates approvals with Playwright (needs Google Chrome: `playwright install chrome`).
