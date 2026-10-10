# Devpost submission text (draft, not submitted)

> Lines marked **[[CHECK]]** depend on something not yet done (the Gemini key, the public repo, the video URL). Fix or remove them before submitting.
> Nothing here states where the builder lives. The product is set in Singapore because that is where this style of chat group buy is everywhere.

## Name
Tipping Point

## Tagline (under 200 characters)
Group buys from a chat where nobody pays unless the group hits the minimum: PayPal holds for everyone, captured at the final tier price or released.

## Inspiration
In Singapore, group buys run on WhatsApp and Telegram: durian boxes for the block, house socks for a school, keycaps for a hobby group. The supplier only ships above a minimum quantity, and bulk tiers make it cheaper the more people join. The organiser, usually a volunteer, ends up doing three thankless jobs. They turn 40 messy messages into an order list. They chase payments up front. And when the group falls short, they refund everyone by hand. Pay-first collection also makes people hesitate ("what if it doesn't happen?"), which is exactly what keeps the group from reaching the minimum.

## What it does
1. **Paste the group chat** (a WhatsApp export or Telegram JSON). Each message becomes a structured order event: a set, add, remove or cancel, a variant switch, "same as Jason", a maybe, a question, or an order placed for someone else. Ambiguous lines go to a *Needs attention* list, each with a reply drafted for the organiser.
2. **Send hold links.** Each buyer gets a PayPal link that places an **authorization hold** at the top-tier price. Their money is held, not charged.
3. **Watch the group tip.** A live tier bar separates "said yes in chat" from "held with PayPal". Only holds count towards the minimum. Raising your order later creates a **top-up hold** for just the difference.
4. **Close and settle, with the organiser's explicit approval of the exact plan:**
   - **Minimum reached:** each hold is **captured at the final group price**, which is lower than or equal to the hold. PayPal releases the unused part automatically.
   - **Minimum missed:** every hold is **voided**. Nobody paid, so there is nothing to refund.

In our sandbox run, 10 buyers held SGD 2.50 a pair for house socks. The group reached the 30-pair tier, so each authorization was captured at SGD 2.20: **SGD 75.00 held, SGD 66.00 charged, SGD 9.00 released, zero refunds.** In a second run, a group stopped at 17 of 20, and all seven holds (SGD 81.60) were voided.

## How we built it: PayPal
All of this is real PayPal REST API calls against the **sandbox**:
- **Orders v2** `POST /v2/checkout/orders` with `intent: AUTHORIZE`, one order per buyer (and one more per top-up). The buyer approves on PayPal's own hosted page, as a wallet buyer or as a guest with a card.
- **Orders v2** `POST /v2/checkout/orders/{id}/authorize` when the buyer returns, creating the authorization hold.
- **Payments v2** `POST /v2/payments/authorizations/{id}/capture` with an amount **below the authorized amount** and `final_capture: true`. This is the key mechanic: the buyer pays the tier price and PayPal releases the remainder.
- **Payments v2** `POST /v2/payments/authorizations/{id}/void` when the minimum is missed.
- **Status updates:** a webhook endpoint (`CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.VOIDED`), verified with `POST /v1/notifications/verify-webhook-signature`, plus a polling fallback (`GET` order and authorization) so a buyer who approves and closes the tab still gets their hold recorded.
- Every money-moving call carries a deterministic **`PayPal-Request-Id`**, so retrying after a failure never double-captures. The organiser approves a **SHA-256-bound plan**: if anything changes after review, the approval no longer applies.
- Campaigns are capped **under 72 hours**, so captures happen inside PayPal's 3-day honor period for authorizations.

We first confirmed in the sandbox that a capture below the authorized amount works and that voids stop later captures. Only then did we write the product.

## How we built it: AI
**[[CHECK: true only once the Gemini reader has been run against the fixtures. Otherwise rewrite this section.]]**
- The chat reader is an LLM (**Google Gemini** through the `generateContent` API, with a strict JSON response schema). It turns free-form multi-person chat into typed `CommitmentEvent`s. This is the part rules cannot do well: "the M one cancel, S keep", "add 4 L for Mrs Chan, she messaged me privately", "bro pulled out, just 1 for me".
- **Every AI answer is checked against the chat before it can affect money.** Each event must cite a real message ID. The participant must be that message's sender, unless the sender explicitly ordered for a named person. The variant must be one the organiser listed, and quantities must be positive. An answer that fails is rejected, and the app falls back to a deterministic rules reader, with a visible notice.
- The AI never moves money. Its output becomes an order list. A pure, tested rules engine (minimum, tiers, holds) turns that list into a settlement plan, and a human approves the exact plan.
- The reader sits behind a provider interface, so tests run on a deterministic offline reader with the same grounding.

## Challenges we ran into
- **Proving partial capture first.** The whole idea depends on capturing *less* than was authorized. We tested it end to end in the sandbox (hold → lower `final_capture` → remainder released; hold → void → capture refused) before writing product code. We also learned that reauthorizing inside the honor period fails (`REAUTHORIZATION_TOO_SOON`), so the campaign window is capped below 72 hours.
- **Top-ups.** When someone raises their order after holding, the existing authorization can't grow. A second hold covers just the difference, and settlement splits each buyer's capture across their authorizations.
- **Messy chat semantics.** Is "+1" one more unit or a new order of one? Is "make it 2" a set or an add? Is an order "for my mum" an order for someone else? We pinned these down as explicit event types with tests across three invented chats (WhatsApp Android, WhatsApp iOS, Telegram JSON).
- **Failure handling.** If one capture fails halfway through settlement, the campaign stays open and shows which call failed. Retrying is safe because the same request IDs are reused.

## Accomplishments we're proud of
- Real multi-buyer runs in the PayPal sandbox through the actual UI: 10/10 buyers held, then captured below their holds; 7/7 voided in the miss case; a top-up hold captured alongside the original. No PayPal errors in the final runs.
- 150 automated tests (rules engine, chat parsing, reader grounding, settlement, web flow, failure and retry), plus an opt-in real-sandbox test.

## What we learned
Authorization holds are an under-used PayPal primitive for *conditional* commerce. "Charge only if X happens, and maybe charge less" is a real need well beyond group buys.

## What's next
Hosted version with live webhooks; organiser-side sharing of hold links back into the chat; per-variant minimums; reminders before the deadline.

## Built with
Python, FastAPI, httpx, Pydantic, pytest, Playwright (demo buyer automation and tests), AG Grid Community, PayPal REST APIs (Orders v2, Payments v2, Webhooks), Google Gemini API **[[CHECK]]**.

## AI tools used to build this project (disclosure)
> **[[REWRITE IN YOUR OWN VOICE]]** This is a draft written for you. Keep it honest, but put it in your own words before submitting.

I set the direction for Tipping Point. I chose the problem and the product, decided what it should and shouldn't do, and made the calls on scope, design and what to cut. An AI agent, **Grok Bot**, wrote most of the code, tests, sample chats and documentation under that direction. It also ran the PayPal sandbox experiments and the automated demo buyers. I reviewed its work and steered it throughout.

- **[[CHECK]]** Google Gemini is used *at runtime* as the chat reader. Keep this line only once the Gemini reader has actually run.
- The sample chats are invented. No real people's messages were used.

## Testing instructions (for judges)
- Repo: **[[CHECK: public GitHub URL]]**. MIT licence (`LICENSE`).
- Offline, no accounts needed: `pip install -r requirements.txt && uvicorn tipping_point.web:app`. Open http://127.0.0.1:8000 and pick a sample chat. PayPal is simulated in-process.
- Sandbox: put your own sandbox REST app credentials in an env file and run with `PAYPAL_MODE=sandbox`. Buyers can approve as PayPal guests with the sandbox test card 4111 1111 1111 1111, any future expiry, CVV 123.
- Video: **[[CHECK: YouTube URL]]**
