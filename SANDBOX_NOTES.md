# Sandbox buyers and runs (local notes, not for the public repo)

## Test buyers: no new sandbox accounts were created
- Creating sandbox accounts needs the PayPal Developer Dashboard (https://developer.paypal.com/dashboard/accounts),
  which signs in with the user's real PayPal login. That login is not on the box, so I did not try.
- It turned out not to be needed. PayPal's hosted approval page offers **"Pay with Debit or Credit Card" guest checkout**
  in the sandbox. Each fake buyer goes through the real approval page as a guest and gets a distinct PayerID.
- Buyer kinds used by `tipping_point/demo_runner.py`:
  - 1 x existing sandbox personal (wallet) account. Credentials stay in `~/.secrets/paypal_sandbox_buyer.env`, never written to the repo.
  - N x guests using test card 4111 1111 1111 1111, 11/30, CVV 123, billing address "1 Test Street, San Jose CA 95131",
    phone 408-555-0100, and an email like `<firstname><n>.tp-sandbox-test@example.com` (example.com does not deliver mail).
- PayPal randomly serves a guest-page variant with a "Save info & create your PayPal account" switch that is ON by default.
  The runner switches it off and refuses to continue if it stays on (`sandbox_buyers.guest_form`). It never clicks
  "Create Account". PayPal also rejects honorifics ("Mr", "Mrs") as first names, so these are stripped from the guest identity.
- Leftovers: about 20 small (SGD 1.00 to 3.00) TEST orders from probes, approved and then voided or never approved. Unapproved orders expire by themselves.

## Multi-buyer end-to-end runs, 2026-10-10 (sandbox, through the web app on 127.0.0.1:8000)
| Scenario | Buyers | Result |
|---|---|---|
| House socks (`ui_walk.py`, through the UI) | 10 (1 wallet + 9 guest), 10/10 held | TIPPED at 30 pairs. Every SGD 2.50/pair hold captured at SGD 2.20, final_capture=true. SGD 75.00 held, SGD 66.00 captured, SGD 9.00 released. 0 PayPal errors |
| Durian puffs (`e2e_sandbox.py durian-miss`) | 7, 7/7 held | FAILED, 17 of 20. All 7 authorizations voided: SGD 81.60 held, 0 charged. 0 PayPal errors |
| Keycaps + top-up (`e2e_sandbox.py keycaps-topup`) | 7 (1 wallet + 6 guest), 7/7 held, plus 1 top-up | 13 held. Then `kai: +2 base` was added to the chat, and kai's row showed TOP-UP NEEDED. A second link went out for 2 x 6.90 = SGD 13.80 and was approved. 15 of 15 TIPPED at SGD 6.90 (no lower tier reached), so kai's two authorizations were each captured. SGD 103.50 captured. 0 PayPal errors |
| (operator slip) keycaps with `kai_keebs: +2 base` | 8 | The script used the Telegram username, not the display name, so a *new* buyer was created instead of a top-up. Also TIPPED, SGD 103.50. Kept as `e2e_keycaps-newbuyer.json` |
Per-run JSON (authorization IDs and every PayPal call): `spikes/out/e2e_*.json` (gitignored).
Earlier attempts: run 1 held 6/10 and run 2 held 8/10 (guest-page variant and honorific names). Both are fixed. Those runs captured at SGD 2.50 because the groups only reached the first tier.
