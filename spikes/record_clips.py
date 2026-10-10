"""Record raw demo clips (mp4 via Xvfb + ffmpeg x11grab) in a headless browser against a server in PAYPAL_MODE=sandbox.
Usage: record_clips.py <base> <act: socks|durian> ; writes video/raw/<act>_*.webm and video/raw/<act>_events.json
The buyer's-view clip uses PayPal guest card checkout only (never the sandbox wallet login)."""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from tipping_point.sandbox_buyers import approve_guest

base, act = sys.argv[1], sys.argv[2]
OUT = Path("video/raw"); OUT.mkdir(parents=True, exist_ok=True)
CURSOR = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.id = '__cursor';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 13.8 L10.5 20 L13 19 L10 12.8 L16 12.8 Z" fill="#111" stroke="#fff" stroke-width="1.4"/></svg>';
  Object.assign(c.style, {position:'fixed', left:'-50px', top:'-50px', zIndex: 2147483647, pointerEvents:'none', transition:'none'});
  document.body.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; }, true);
  document.addEventListener('mousedown', e => {
    const r = document.createElement('div');
    Object.assign(r.style, {position:'fixed', left: e.clientX - 18 + 'px', top: e.clientY - 18 + 'px', width:'36px', height:'36px',
      borderRadius:'50%', background:'rgba(15,118,110,.35)', zIndex: 2147483646, pointerEvents:'none', transition:'all .45s ease-out'});
    document.body.appendChild(r);
    requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 600);
  }, true);
});
"""

events, T0 = [], None
def log(name, **kw):
    events.append({"t": round(time.time() - T0, 2), "event": name, **kw}); print(events[-1], flush=True)

def glide_click(page, sel, pause=0.5):
    box = page.locator(sel).first.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30)
    time.sleep(pause)
    page.mouse.down(); page.mouse.up()

def wait_js(page, expr, timeout=1200):
    t = time.time()
    while time.time() - t < timeout:
        if page.evaluate(expr):
            return
        time.sleep(0.25)
    raise TimeoutError(expr)

def play_buyers_and_track(page):
    glide_click(page, "#btnBuyers"); log("buyers_start")
    page.mouse.move(1000, 640, steps=15)        # off the button, so its tooltip doesn't sit on screen
    time.sleep(2)
    last = -1
    while True:
        st = page.evaluate("view ? [view.progress.held, view.demo_running, view.progress.tipped] : [0, true, false]")
        if st[0] != last:
            log("held", held=st[0], tipped=st[2]); last = st[0]
        if not st[1]:
            break
        time.sleep(0.3)
    log("buyers_done")

DISPLAY = ":57"
xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1440x990x24", "-nolisten", "tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
env = {**os.environ, "DISPLAY": DISPLAY}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=False, env=env,
                          args=["--window-position=0,0", "--window-size=1440,990", "--disable-infobars",
                                "--hide-scrollbars", "--force-device-scale-factor=1", "--no-first-run"])
    ctx = b.new_context(no_viewport=True, locale="en-US")
    ctx.add_init_script(CURSOR)
    page = ctx.new_page()
    page.goto(base); page.mouse.move(700, 450); time.sleep(2)
    out_mp4 = OUT / f"{act}_raw.mp4"
    rec = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0", "-framerate", "30",
                            "-video_size", "1440x990", "-i", DISPLAY + ".0", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "16", "-pix_fmt", "yuv420p", str(out_mp4)], stdin=subprocess.PIPE)
    time.sleep(0.6); T0 = time.time()
    time.sleep(3); log("empty")
    sample = {"socks": "socks", "durian": "durian"}[act]
    glide_click(page, f"[data-sample={sample}]"); log("sample_click"); time.sleep(2.5)
    glide_click(page, "#btnRead"); log("read_click")
    wait_js(page, "!document.querySelector('#bubbles').classList.contains('hidden')", 180); log("bubbles_start")
    wait_js(page, "!document.querySelector('#btnHolds').disabled"); log("read_done")
    used = page.evaluate("view.reader_used"); log("reader_used", reader=used)
    if os.environ.get("REQUIRE_READER") and used != os.environ["REQUIRE_READER"]:
        print("ABORT: reader was", used); rec.communicate(b"q", timeout=60); b.close(); xvfb.terminate(); sys.exit(3)
    time.sleep(3)
    glide_click(page, "#btnHolds"); log("holds_click")
    wait_js(page, "view && view.rows.every(r => r.status === 'AWAITING BUYER')"); log("holds_done"); time.sleep(3)
    if act == "socks":
        cid = page.evaluate("cid")
        row = page.evaluate("view.rows.find(r => r.participant === 'Ahmad')")
        url = row["links"][0]["url"]
        ok = False
        for attempt in range(3):
            # a fresh context per attempt: PayPal buckets page variants per session
            c2 = b.new_context(no_viewport=True, locale="en-US"); c2.add_init_script(CURSOR)
            p2 = c2.new_page(); p2.bring_to_front(); log("buyer_view_start", attempt=attempt)
            try:
                ok = approve_guest(p2, url, f"{base}/r/{cid}/", "Ahmad", "Tester", "ahmad.tp-sandbox-test@example.com", timeout_s=90)
            except Exception as e:  # noqa: BLE001
                log("buyer_view_error", error=str(e)[:200])
            if ok:
                log("buyer_view_returned"); time.sleep(4)
            p2.close(); c2.close(); page.bring_to_front(); log("buyer_view_end", ok=ok)
            if ok:
                break
        wait_js(page, "view.rows.find(r => r.participant === 'Ahmad').status === 'HELD'", 60); time.sleep(2)
    play_buyers_and_track(page); time.sleep(3)
    glide_click(page, "#btnClose"); log("close_click")
    wait_js(page, "!document.querySelector('#settle').classList.contains('hidden')"); log("plan_shown"); time.sleep(3)
    page.mouse.move(820, 400, steps=20); page.mouse.wheel(0, 300); time.sleep(2.5); page.mouse.wheel(0, 600); time.sleep(2)
    glide_click(page, "#btnApprove"); log("approve_click")
    wait_js(page, "view && view.stage === 'settled'", 120); log("settled"); time.sleep(8); log("end")
    rec.communicate(b"q", timeout=60)
    ctx.close(); b.close()
xvfb.terminate()
json.dump(events, open(OUT / f"{act}_events.json", "w"), indent=1)
print("DONE", act, out_mp4)
