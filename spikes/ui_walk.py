"""Walk the UI through the whole story and screenshot each stage. Usage: ui_walk.py <base> <sample> <outprefix> [buyers_timeout_s]"""
import sys, time
from playwright.sync_api import sync_playwright
base, sample, out = sys.argv[1], sys.argv[2], sys.argv[3]
wait_buyers = int(sys.argv[4]) if len(sys.argv) > 4 else 30
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(base); pg.wait_for_timeout(800)
    pg.click(f"[data-sample={sample}]"); pg.wait_for_timeout(1200); pg.screenshot(path=f"{out}_1_paste.png")
    pg.click("#btnRead"); pg.wait_for_function("!document.querySelector('#btnHolds').disabled", timeout=60000)
    pg.wait_for_timeout(1500); pg.screenshot(path=f"{out}_2_read.png")
    pg.click("#btnHolds"); pg.wait_for_timeout(1500); pg.screenshot(path=f"{out}_3_links.png")
    pg.click("#btnBuyers")
    t0 = time.time()
    pg.wait_for_timeout(2500); pg.screenshot(path=f"{out}_4a_buyers.png")
    pg.wait_for_function("document.querySelector('#btnBuyers').textContent.includes('Play')", timeout=wait_buyers * 1000)
    pg.wait_for_timeout(1500); pg.screenshot(path=f"{out}_4b_held.png")
    print("buyers took", round(time.time() - t0), "s")
    pg.click("#btnClose"); pg.wait_for_timeout(1200); pg.screenshot(path=f"{out}_5_plan.png")
    pg.click("#btnApprove"); pg.wait_for_selector("#result:not(.hidden)", timeout=120000)
    pg.wait_for_timeout(1800); pg.screenshot(path=f"{out}_6_settled.png")
    print(pg.inner_text("#result"))
    b.close()
