# Originality log (check against /workspace/earn/paypal/data/field_list.md)

## 2026-10-10 Day 1
Re-searched Devpost for: paypal + group buy / telegram / whatsapp / bulk order / preorder / pool / minimum / tier / pledge / crowdfund.
**No entry does MOQ / all-or-nothing group buys or tier-price capture.** No new entries since the 08:10 scan.

| What we built today | Nearest field entry | Status |
|---|---|---|
| Multi-buyer pooled holds, capture-if-MOQ, void-if-not, tier-price partial capture | ShopVoice Pay: auth then partial capture, but one shop paying its suppliers on delivery | Distinct (multi-payer threshold vs single-payer delivery match) |
| AI reading group chat into orders | SarafuPay: WhatsApp agent for group *contributions*, captured immediately, no threshold | Distinct mechanic. **Watch:** do not drift toward "group collection page" UX |
| Hash-bound human approval before money moves | Pulse Safe, PayGuard ×3, SpendGuard, Bursar, LexProof… | **Commodity.** Keep it, but never pitch it as a novelty |
| AG Grid ledger (planned) | Rebuttal, many others | Commodity UI; the differentiator is the tier-progress / hold-state view |

Drift alarms for later days:
- Adding "escrow until delivery" would move us into the ~15-entry escrow cluster. Don't.
- An "agent spending limit" angle moves us into the mandate cluster. Don't.
- A generic chat → invoice step would recreate the dropped Copilot. Don't.

## 2026-10-10 web app + sandbox run
Re-searched Devpost (paypal + group buy / minimum order / authorization hold / pooled / whatsapp).
- New name seen: **StudentShare** ("Save money by joining group buys"). It is a GreatUniHack 2025 entry, not this hackathon: student matchmaking for splitting subscriptions; payment is coordinated off-platform. No holds, no MOQ, no tier capture. Distinct.
- Auth-hold results are the known ones (ShopVoice Pay, escrow cluster, permission APIs). No new MOQ / all-or-nothing group-buy entry.
- Web app check: the screen is about the *threshold* (progress bar to the minimum, hold → capture at the tier price or release). It is not a collection page (SarafuPay) or an approval console (mandate cluster). The settlement approval modal is commodity; it stays a small step, not the pitch.
