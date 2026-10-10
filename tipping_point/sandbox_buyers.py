"""Demo tooling: drive the real PayPal *sandbox* approval page for fake buyers.

Two buyer kinds:
- wallet: the existing sandbox personal account (credentials from ~/.secrets, never printed)
- guest:  PayPal's hosted "Pay with Debit or Credit Card" guest checkout with a sandbox test card
          (no account is created; we click "Continue as Guest")
Only sandbox.paypal.com URLs are accepted.
"""
from __future__ import annotations

import os
import time

from .paypal import load_env_file

TEST_CARD = {"number": "4111111111111111", "exp": "11/30", "cvv": "123"}


def _assert_sandbox(url: str):
    if not url.startswith("https://www.sandbox.paypal.com/"):
        raise ValueError(f"refusing non-sandbox approval URL: {url[:60]}")


def approve_wallet(page, url: str, return_prefix: str, timeout_s: int = 150) -> bool:
    _assert_sandbox(url)
    buyer = load_env_file("~/.secrets/paypal_sandbox_buyer.env")
    page.goto(url, wait_until="domcontentloaded")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if page.url.startswith(return_prefix):
            return True
        try:
            if page.locator("#email").is_visible(timeout=800) and page.locator("#email").input_value() == "":
                page.fill("#email", buyer["PAYPAL_SANDBOX_BUYER_EMAIL"])
                if page.locator("#btnNext").is_visible(timeout=800):
                    page.click("#btnNext")
                continue
        except Exception:
            pass
        try:
            if page.locator("#password").is_visible(timeout=800):
                page.fill("#password", buyer["PAYPAL_SANDBOX_BUYER_PASSWORD"])
                page.click("#btnLogin"); page.wait_for_timeout(3000); continue
        except Exception:
            pass
        for sel in ["#payment-submit-btn", "button[data-id='payment-submit-btn']", "#consentButton",
                    "button:has-text('Continue to Review Order')", "button:has-text('Continue')",
                    "button:has-text('Agree & Continue')", "#acceptAllButton"]:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=400):
                    loc.click(); page.wait_for_timeout(2500); break
            except Exception:
                pass
        page.wait_for_timeout(1000)
    return False


def approve_guest(page, url: str, return_prefix: str, first: str, last: str, email: str,
                  timeout_s: int = 120, shot_dir: str | None = None) -> bool:
    _assert_sandbox(url)
    page.goto(url, wait_until="domcontentloaded")
    classic = page.locator("text=Pay with Debit or Credit Card").first
    email_first = page.locator("text=Check out as a guest").first
    t0 = time.time()
    while time.time() - t0 < 30 and not (classic.is_visible() or email_first.is_visible()):
        page.wait_for_timeout(300)
    if classic.is_visible():
        classic.click()
    elif email_first.is_visible():          # rarer variant: email first, then the card form
        box = page.locator("input:visible").first
        box.click(); box.press_sequentially(email, delay=25)
        page.locator("button:has-text('Continue to Payment')").first.click()
    else:
        raise TimeoutError("no guest checkout option on the PayPal page")
    return guest_form(page, return_prefix, first, last, email, timeout_s, shot_dir)


def guest_form(page, return_prefix, first, last, email, timeout_s=120, shot_dir=None) -> bool:
    card = page.locator("input[name='cardnumber']").first
    email_step = page.locator("button:has-text('Continue to Payment')").first
    t0 = time.time()
    while time.time() - t0 < 30 and not card.is_visible():
        if email_step.is_visible():          # some sessions ask for the email first, then show the card form
            box = page.locator("input:visible").first
            box.click(); box.press_sequentially(email, delay=25)
            email_step.click()
            page.wait_for_timeout(2500)
        page.wait_for_timeout(300)
    page.wait_for_selector("input[name='cardnumber']", timeout=30000)
    page.wait_for_timeout(3000)   # the form re-renders once after load; typing before that is lost

    def typ(sel, val):
        loc = page.locator(sel).first
        loc.click()
        loc.press_sequentially(val, delay=25)

    typ("#cardNumber", TEST_CARD["number"])
    for attempt in ("1130", "11/30", "11 / 30"):
        page.locator("#cardExpiry").fill("")
        typ("#cardExpiry", attempt)
        page.wait_for_timeout(300)
        if page.locator("#cardExpiry").input_value().replace(" ", "") in ("11/30", "1130"):
            break
    typ("#cardCvv", TEST_CARD["cvv"])
    typ("#firstName", first)
    typ("#lastName", last)
    typ("#billingLine1", "1 Test Street")
    typ("#billingCity", "San Jose")
    try:
        page.select_option("select[name='billingState']", "CA", timeout=3000)
    except Exception:
        try:
            page.select_option("#billingState", "CA", timeout=3000)
        except Exception:
            pass
    typ("#billingPostalCode", "95131")
    if not page.locator("#phone").input_value().strip().replace("+1", ""):
        typ("#phone", "4085550100")
    if not page.locator("#email").input_value():
        typ("#email", email)
    # Two page variants exist. A: a "Continue as Guest" button. B: a "Save info & create your PayPal account"
    # switch that is ON by default. We never create an account: switch it off, and refuse if it stays on.
    guest_btn = page.locator("button:has-text('Continue as Guest')").first
    if guest_btn.count() and guest_btn.is_visible():
        guest_btn.click()
    else:
        switch = page.locator("[data-testid='onboard-options-switch'], input[type='checkbox'][role='switch']").first
        if switch.count() and switch.is_checked():
            switch.evaluate("e => e.click()")          # the input itself is visually hidden
            page.wait_for_timeout(1000)
        if (switch.count() and switch.is_checked()) or page.locator("input[type='password']").first.is_visible():
            raise RuntimeError("guest page wants to create an account; refusing")
        btn = page.locator("button[type='submit']:not(:has-text('Create Account'))").first
        btn.click()
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if page.url.startswith(return_prefix):
            return True
        for sel in ["button:has-text('Continue'):not(:has-text('Create'))", "#payment-submit-btn", "button:has-text('Agree & Continue')"]:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=400):
                    loc.click(); page.wait_for_timeout(2000); break
            except Exception:
                pass
        page.wait_for_timeout(1000)
    if shot_dir:
        page.screenshot(path=os.path.join(shot_dir, f"guest_fail_{int(time.time())}.png"), full_page=True)
    return False
