# Tipping Point: 3-minute demo video script

**Target length 2:50** (the hard limit is under 3:00). 1440×900 browser window, recorded at 60 fps. The app runs in **PayPal sandbox mode**,
so every PayPal ID on screen is real. Every shot is built to make sense **without sound**. The burned-in captions carry the story;
the voice-over (VO) is optional and says the same thing.

**One condition before filming:** the hackathon requires *meaningful use of AI*. Film the chat-reading shot with the
**Gemini reader** (`TP_READER=gemini`), not the offline rules reader. If the key is not in time, the reader badge will read
"Chat reader: rules (offline)", and the captions below must not say "AI reads". Use the alternate wording in shot 4.

## Before recording
- Start fresh: `PAYPAL_MODE=sandbox TP_BASE_URL=http://127.0.0.1:8000 [TP_READER=gemini] uvicorn tipping_point.web:app --port 8000`
- Browser at 100% zoom, no bookmarks bar, no other tabs. Mouse moves slowly, and clicks are highlighted in the edit.
- **Do not film a sandbox wallet login.** Its email is a sandbox credential. For the "buyer's view" shot, use the
  **guest card** flow (fake name, `@example.com` email, test card 4111…). If a wallet login is filmed anyway, blur the email field.
- Record each act as its own clip: A (socks, tips), B (durian, misses), plus a buyer's-view clip. That keeps re-takes cheap.
- Raw timings, so the edit can be planned: reading the chat about 6 s, one guest approval about **43 s**, one wallet approval about 11 s,
  10 buyers about **7 min**, closing and settling 2–4 s.

## Shot list

| # | Time | Screen | Action | Burned-in caption | Optional VO | Edit note |
|---|---|---|---|---|---|---|
| 1 | 0:00–0:06 | **Cold open, the problem:** the raw socks chat export in the paste box (zoomed) | none | "A school parents’ chat: ‘+2 L’, ‘oops make it 2 L only’, ‘the M one cancel, S keep’… and the supplier ships only at **20 pairs**." | "Group buys run on chat, and the supplier only ships at the minimum." | Real speed plus a 4 s hold so the caption can be read |
| 2 | 0:06–0:13 | **Cold open, the payoff:** the settled socks card (TIPPED, green strip "SGD 66.00 charged · SGD 9.00 released back to buyers") over the CAPTURED rows | none | "**Tipping Point:** everyone places a PayPal **hold**. If the group hits 20, they’re charged the lower group price and the rest is released. If it misses, nobody pays." | "Tipping Point makes that rule real, with PayPal." | Taken from the end of Act A. No logo or title card: the end card is the only branding |
| 3 | 0:16–0:22 | Left column | Click **House socks**; the chat lands in the box | "Paste the chat." | — | Real speed |
| 4 | 0:22–0:42 | Chat bubbles appear one by one with chips | Click **Read the chat** | "Gemini reads every message into orders. Changes, cancels and ‘for Mrs Chan’ included." *(if filmed with the rules reader: "Every message becomes an order, a change, or a flag.")* | "Each message becomes a structured order: changes, cancels, orders placed for someone else." | Real speed for the first 6 bubbles, then 2×. **Zoom 1:** "oops make it 2 L only" → chip `2 L`. **Zoom 2:** "the M one cancel, S keep" → `cancel M`. **Zoom 3:** the amber Ms Goh bubble → the Needs attention card with its drafted reply |
| 5 | 0:42–0:50 | Centre: order list filled, striped bar at 30, pill "enough interest · now make it real with holds" | none | "Saying yes in chat isn't paying. A PayPal hold is." | "But a ‘yes’ in chat isn't money." | Hold 2 s on the striped bar |
| 6 | 0:50–0:58 | Click **Send hold links** | Rows turn AWAITING BUYER; the activity feed fills with `POST orders 201 PAYER_ACTION_REQUIRED · SGD 12.50 …` | "Each buyer gets a PayPal link for an **authorization hold** at the top-tier price, SGD 2.50 a pair. A hold, not a charge." | "Everyone gets a PayPal hold at the highest price. Nothing is charged." | Zoom on the feed for 1 s |
| 7 | 0:58–1:16 | **Buyer's view** clip: the PayPal sandbox approval page (guest card), then the app's return page "Hold placed ✓ … held, not charged" | Buyer fills in the card and approves | "What a buyer sees: PayPal's own page, then ‘held, not charged’." · small corner tag "PayPal Sandbox: test card, no real money" | "Buyers approve on PayPal's own page. Their money is held, not taken." | 43 s raw → **about 4×** for the form, real speed on the return page (2 s) |
| 8 | 1:16–1:44 | Back to the app; play the other buyers | Click **▶ Play buyers (sandbox)**; rows flip to HELD, the solid bar grows, the progress box says "Buyer 5 of 10 · Grace…" | "⏩ 9 more buyers, sped up 16×. Approvals automated for this demo; real buyers tap their link." | — | About 6.5 min raw → **16× (about 24 s)**. **Drop to real speed for the crossing**: held 19 → 21 passes the MINIMUM line and the pill pops "TIPPED ✓". Hold 2 s. Then 16× again until 30, when the `30+ → SGD 2.20` tier mark turns green and the pill reads "group price SGD 2.20" |
| 9 | 1:44–2:10 | Click **Close campaign** → settlement window | Show the capture list | "The group reached 30. Every hold is **captured at SGD 2.20**, below what was held. You approve exactly this plan." | "The group got the 30-pair price, so everyone pays less than their hold." | Zoom on Ahmad's line: hold 12.50 → `capture {"value":"11.00","final_capture":true}`. Show the sha256 line for 1 s |
| 10 | 2:10–2:24 | Click **Approve & execute** | Rows flip to CAPTURED; the Charged and Released columns appear; the green result strip reads "SGD 66.00 charged · SGD 9.00 released back to buyers" | "Real PayPal captures. The unused SGD 9.00 is released automatically. No refunds." | "PayPal captures the lower amount and releases the rest. No refunds, ever." | Real speed. Zoom on the strip, then on one authorization ID in the feed |
| 11 | 2:24–2:38 | Act B (durian, pre-recorded): bar stuck at 17 / 20 → **Close** → "Missed the minimum by 3. Release every hold" → Approve → "Nobody was charged · SGD 81.60 in holds released" | — | "Different chat: 17 of 20. Every hold is **voided**. Nobody pays." | "If the group falls short, every hold is voided. Nobody pays." | Collection sped up, about 3 s total. Real speed from Close onwards |
| 12 | 2:38–2:50 | End card (static slide) | — | "PayPal Orders v2 · authorize · partial capture (final_capture) · void · webhooks" / "Chat → orders: Gemini, every answer grounded against the chat" / "Tipping Point · github.com/‹repo› · built for the PayPal AI Hackathon" | "Tipping Point. Group buys that only charge when the group tips." | No music, or royalty-free music only (rule) |

**Optional insert (if the cut runs short; +10 s, after shot 8):** type `Grace: actually make mine 6` in the late-message box.
Grace's row turns **TOP-UP NEEDED** and the button changes to **Send top-up links**. Caption: "Changed your mind late? A top-up hold covers only the difference."

## Speed-up summary
| Raw segment | Raw | In the video | How |
|---|---|---|---|
| One guest approval (buyer's view) | about 43 s | about 14 s | 4× on form filling, real speed on submit and return |
| The other 9 approvals | about 6.5 min | about 24 s | 16×, with **real speed at the minimum crossing** |
| Act B collection (7 buyers) | about 5 min | about 3 s | Jump cut with a "⏩" caption, or pre-record and show only the 17/20 state |
| Settlement | 2–4 s | real speed | This is the payoff. Never speed it up |

## Honesty rules for the edit
- Every speed-up gets an on-screen "⏩ N×" tag.
- Say "PayPal Sandbox" wherever money appears. Never imply real money moved.
- State that the buyer approvals are automated for the demo.
- Don't call the reader AI unless the filmed run used Gemini (the reader badge in the header shows which one ran).
- No claims about who built it or where they are; the product story is set in Singapore group chats, nothing more.


## Rough cut as built (2026-10-10)
- Raw clips: `video/raw/socks_raw.mp4` (Act A: about 7.7 min, includes the buyer's view as guest card checkout) and `video/raw/durian_raw.mp4` (Act B: about 14 min). Event timestamps are in `video/raw/*_events.json`. Recorder: `spikes/record_clips.py` (private Xvfb display, real Chrome window, ffmpeg x11grab, 30 fps).
- Cut: `video/tipping_point_rough_cut.mp4` (1920×1080, 30 fps, **no audio track**, captions burned in). Builder: `spikes/make_cut.py` (every segment, speed and caption is in one table there).
- The sandbox wallet login never appears. It runs in the demo runner's own off-screen browser for one buyer. The only checkout on screen is Ahmad's guest card checkout.
- Speed-ups are labelled on screen (⏩ 1.5×, 5×, 16×, 2×, 120×, 1.3×). The minimum crossing (19 → 21) plays at real speed.
- Act B differs from the plan: in the recorded take, one buyer (Ah Seng, 2 boxes) never got held, so the board ends at **15 / 20, missed by 5, SGD 72.00 released**. The captions say exactly that, and it adds a realistic "said yes but never approved" beat.
- The captions use rules-reader wording ("Every message becomes an order…"). No caption mentions Gemini or AI until the Gemini reader has run.
