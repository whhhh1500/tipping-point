# Tipping Point (working title)

Chat-native group buys where **nobody is charged unless the group hits the supplier's minimum**.

The organiser pastes a WhatsApp or Telegram group-buy chat. An AI reader turns the messy messages ("+1 MSW", "change mine to 3", "same as Jason", "cancel pls", "maybe 2?") into a clean order list. Each buyer gets a PayPal **authorization hold** at the top-tier price. At the deadline (under 72 h, inside PayPal's 3-day honor period):
- **MOQ reached:** every hold is captured at the *final volume-tier price*, which is lower than or equal to the hold. The rest is released automatically.
- **MOQ missed:** every hold is voided. Nobody paid anything.

Status: local only, not published. Web app, multi-buyer sandbox runs, video script (`VIDEO_SCRIPT.md`) and submission draft (`SUBMISSION.md`) done.

## Layout
| Path | What |
|---|---|
| `spikes/sandbox_spike.py`, `spikes/sandbox_probe2.py`, `spikes/SPIKE_RESULT.md` | Real-sandbox proof of hold → lower capture / void with automated buyer approval |
| `tipping_point/campaign.py` | Rules engine: MOQ, price tiers, <72 h deadline, hold amount, settlement plan (pure) |
| `tipping_point/chat.py` | WhatsApp (Android/iOS) and Telegram JSON export parsers |
| `tipping_point/readers.py` | `ChatReader` interface: `StubReader` (deterministic, offline) and `GeminiReader` (REST + JSON schema), with a shared grounding check |
| `tipping_point/ledger.py` | Events → order list + issues with draft replies |
| `tipping_point/paypal.py` | `SandboxHolds` (refuses live URLs) and `FakeHolds` (mirrors observed sandbox semantics) |
| `tipping_point/settle.py` | The only money-moving path: hash-bound approval, idempotent request ids |
| `tipping_point/service.py` | Campaign lifecycle: read chat → hold links (incl. top-ups) → holds → close → approved settlement; status sync + webhook handling |
| `tipping_point/web.py`, `static/` | FastAPI app + one-screen UI (chat bubbles with parsed chips, tier progress bar, AG Grid order list, issues with draft replies, live PayPal activity feed, settlement approval) |
| `tipping_point/demo_runner.py`, `tipping_point/sandbox_buyers.py` | Demo only: plays the buyers through PayPal's real sandbox approval page (1 sandbox wallet + guest card checkout, no accounts created) |
| `spikes/ui_walk.py`, `spikes/e2e_sandbox.py` | Screenshot walk-through and multi-buyer sandbox end-to-end runs |
| `fixtures/` | 3 invented Singapore group chats + `expected.json` |

## Run
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                       # offline (stub reader, fake PayPal)
RUN_SANDBOX_TESTS=1 .venv/bin/python -m pytest -q -m sandbox   # real sandbox, tiny TEST holds
GEMINI_API_KEY=... .venv/bin/python spikes/gemini_check.py   # Gemini reader vs the 3 fixtures (3 requests)
TP_READER=gemini GEMINI_API_KEY=... uvicorn ...      # app with the Gemini reader (GEMINI_MODEL, default "gemini-3.7-flash,gemini-3.5-flash"; falls back to rules, with a notice)

# web app, offline simulator (no network)
.venv/bin/uvicorn tipping_point.web:app --port 8000
# web app against the PayPal sandbox (small TEST amounts; refuses live URLs)
PAYPAL_MODE=sandbox TP_BASE_URL=http://127.0.0.1:8000 .venv/bin/uvicorn tipping_point.web:app --port 8000
```
Open http://127.0.0.1:8000, pick a sample chat, then go left to right: Read the chat → Send hold links → Play buyers → Close campaign → Approve & execute.

## Honest notes
- The StubReader is a rule-based stand-in (phrasing coverage in `tests/test_stub_phrasings.py`) so tests run without a model. It was written against the fixtures and will miss phrasings it hasn't seen. The product's reader is the LLM, and both go through the same grounding check: no invented senders, messages, or variants.
- "Play buyers" is demo tooling. Real buyers open the hold link themselves; the app's /r/ return URL places the hold exactly the same way. Without a public URL, status comes from polling (`/sync`); the webhook endpoint (`/api/webhooks/paypal`, signature verified through PayPal) is for the hosted version.
- Fixture prices are deliberately tiny (SGD 1.90 to 6.90 a unit) so every sandbox artifact is small and clearly fake.
- Production caveats: live fees for voided authorizations still need checking; the sandbox merchant receives USD, so SGD was converted.
