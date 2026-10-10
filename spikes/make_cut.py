"""Rough cut: video/raw/{socks,durian}_raw.mp4 + *_events.json -> video/tipping_point_rough_cut.mp4 (1920x1080, silent, burned captions)."""
import json, subprocess, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

RAW, BUILD = Path("video/raw"), Path("video/build")
BUILD.mkdir(parents=True, exist_ok=True)
W, H, CW, CH, BAND = 1920, 1080, 1396, 960, 120           # canvas, content, caption band
X0 = (W - CW) // 2
FULL = (0, 0, 1440, 990)
ASPECT = CW / CH

ev = {a: json.load(open(RAW / f"{a}_events.json")) for a in ("socks", "durian")}
def t(act, name, which="last"):
    xs = [e["t"] for e in ev[act] if e["event"] == name]
    return xs[-1] if which == "last" else xs[0]

def zoom(x, y, w):            # rectangle in raw 1440x990 coords, aspect locked to the content box
    h = round(w / ASPECT)
    return (x, y, w, h)

# ---- the minimum crossing in the socks run
held = [e for e in ev["socks"] if e["event"] == "held"]
cross = next(e for e in held if e["held"] >= 20)
before_cross = max(e["t"] for e in held if e["t"] < cross["t"])
tier30 = next((e for e in held if e["held"] >= 30), held[-1])

S = "socks"
SEGS = [
 # (source, start, end, speed, zoom rect, caption, tag, freeze_after)
 (S, t(S, "sample_click") + 1.2, t(S, "read_click") - 0.1, 1, zoom(0, 250, 860),
  "A school parents’ chat: <b>“+2 L”</b>, <b>“oops make it 2 L only”</b>, <b>“the M one cancel, S keep”</b>… and the supplier ships only at <b>20 pairs</b>.", None, 4.0),
 (S, t(S, "end") - 6.5, t(S, "end") - 0.5, 1, zoom(400, 170, 720),
  "<b>Tipping Point:</b> everyone places a PayPal <b>hold</b>. Group hits 20 → charged the lower group price, rest released. Misses → nobody pays.", None, 1.0),
 (S, t(S, "read_click") - 0.4, t(S, "read_click") + 2.5, 1, FULL,
  "Paste the chat. <b>Gemini</b> reads every message.", None, 0),
 (S, t(S, "read_click") + 2.5, t(S, "bubbles_start") - 0.3, 8, FULL,
  "<b>Gemini</b> reads every message. <span class=dim>About 20 s on the free tier, sped up</span>", "8×", 0),
 (S, t(S, "bubbles_start") - 0.3, t(S, "read_done") + 1.0, 1, FULL,
  "Each message becomes an order, a change, a cancel or a flag, and each one is <b>checked against the chat</b> before it counts.", None, 0),
 (S, t(S, "read_done") + 1.0, t(S, "read_done") + 1.8, 1, zoom(10, 440, 640),
  "<b>“oops make it 2 L only”</b> → 2 L &nbsp;·&nbsp; <b>“the M one cancel, S keep”</b> → cancel M &nbsp;·&nbsp; <b>“add 4 L for Mrs Chan”</b> → ordered on her behalf", None, 2.6),
 (S, t(S, "read_done") + 1.8, t(S, "read_done") + 2.6, 1, zoom(1040, 170, 400),
  "Anything unclear is flagged, with a reply drafted for the organiser.", None, 2.0),
 (S, t(S, "read_done") + 2.6, t(S, "holds_click") - 0.6, 1, zoom(400, 170, 720),
  "30 pairs said yes. But a “yes” in chat isn’t money.", None, 1.5),
 (S, t(S, "holds_click") - 0.6, t(S, "holds_done") + 1.5, 1.5, FULL,
  "Each buyer gets a PayPal link for an <b>authorization hold</b> at the top price, SGD 2.50 a pair. Held, not charged.", "1.5×", 0),
 (S, t(S, "buyer_view_start"), t(S, "buyer_view_returned"), 5, FULL,
  "What a buyer sees: PayPal’s own checkout. <span class=dim>Sandbox · guest card · test money</span>", "5×", 0),
 (S, t(S, "buyer_view_returned"), t(S, "buyer_view_returned") + 3.2, 1, FULL,
  "…then: <b>held, not charged</b>. They pay only if the group hits the minimum.", None, 0.8),
 (S, t(S, "buyers_start") - 0.5, cross["t"] - 3, 16, FULL,
  "The rest of the group approves. <span class=dim>Automated for this demo; real buyers tap their link.</span>", "16×", 0),
 (S, cross["t"] - 3, cross["t"] + 3, 1, zoom(400, 170, 720),
  "<b>Minimum reached.</b> The group tips.", None, 0),
 (S, cross["t"] + 3, tier30["t"] + 2.5, 16, FULL,
  "More holds arrive… 30 pairs unlocks the <b>SGD 2.20</b> tier.", "16×", 0),
 (S, tier30["t"] + 2.5, tier30["t"] + 5, 1, zoom(400, 170, 720),
  "30 pairs: the group price drops to <b>SGD 2.20</b>, below what everyone held.", None, 0),
 (S, t(S, "close_click") - 0.6, t(S, "approve_click") + 0.3, 1, FULL,
  "Close: every hold is <b>captured at SGD 2.20</b>, less than the SGD 2.50 held. The organiser approves exactly this plan.", None, 0),
 (S, t(S, "approve_click") + 0.3, t(S, "settled") + 3.5, 2, FULL,
  "Real PayPal sandbox captures, one per buyer. The unused <b>SGD 9.00 is released automatically</b>. No refunds.", "2×", 0),
 (S, t(S, "settled") + 3.5, t(S, "end") - 0.3, 1, zoom(400, 170, 720),
  "Held SGD 75.00 → charged SGD 66.00 → released SGD 9.00.", None, 1.0),
 ("durian", t("durian", "read_done") + 1.0, t("durian", "buyers_done") + 2, 120, FULL,
  "A different chat: durian puffs. 17 boxes said yes, but only <b>15 got held</b>: one buyer never approved.", "120×", 0),
 ("durian", t("durian", "close_click") - 0.5, t("durian", "approve_click") + 0.3, 1.3, FULL,
  "Missed the minimum by 5 → <b>every hold is voided</b>.", "1.3×", 0),
 ("durian", t("durian", "approve_click") + 0.3, t("durian", "settled") + 1.0, 1, FULL,
  "Real PayPal sandbox voids, one per hold.", None, 0),
 ("durian", t("durian", "settled") + 1.0, t("durian", "settled") + 4.5, 1, zoom(400, 170, 720),
  "Nobody was charged. Nothing to refund.", None, 1.0),
]

CAP_HTML = """<html><body style="margin:0;background:transparent">
<div style="width:1920px;height:120px;display:flex;align-items:center;justify-content:center;background:#1d2433;
 font:500 34px/1.25 'Inter','Noto Sans','DejaVu Sans',sans-serif;color:#f5f3ee;padding:0 120px;box-sizing:border-box;text-align:center">
<div>%s</div></div><style>b{color:#7fe0c0;font-weight:700}.dim{color:#a8b0c0;font-size:26px}</style></body></html>"""
TAG_HTML = """<html><body style="margin:0;background:transparent"><div style="display:inline-block;padding:10px 20px;border-radius:14px;
background:rgba(29,36,51,.88);color:#fff;font:800 40px 'Inter','Noto Sans',sans-serif">⏩ %s</div></body></html>"""
END_HTML = """<html><body style="margin:0;width:1920px;height:1080px;background:#f4f1ea;display:flex;align-items:center;justify-content:center;
font-family:'Inter','Noto Sans','DejaVu Sans',sans-serif;color:#1d2433"><div style="text-align:center">
<div style="font-size:96px;font-weight:800;letter-spacing:-2px"><span style="color:#0f766e">◔</span> Tipping Point</div>
<div style="font-size:40px;margin:14px 0 50px;color:#4b5563">Group buys where nobody pays unless the group hits the minimum</div>
<div style="font-size:30px;line-height:1.7">PayPal Orders v2 with intent <b>AUTHORIZE</b> · <b>capture below the hold</b> (final_capture) · <b>void</b> · webhooks<br>
Chat → orders by <b>Gemini</b>, every event checked against the chat · organiser approves the exact plan<br>
<span style="color:#6b7280">PayPal Sandbox · test money · <b style="color:#1d2433">github.com/whhhh1500/tipping-point</b> · PayPal AI Hackathon</span></div></div></body></html>"""

def render_pngs():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1920, "height": 120})
        for i, s in enumerate(SEGS):
            pg.set_content(CAP_HTML % s[5]); pg.screenshot(path=str(BUILD / f"cap{i:02d}.png"), omit_background=True)
        tags = {s[6] for s in SEGS if s[6]}
        pg2 = b.new_page(viewport={"width": 400, "height": 90})
        for tg in tags:
            pg2.set_content(TAG_HTML % tg)
            pg2.locator("div").screenshot(path=str(BUILD / f"tag_{tg.replace('×','x')}.png"), omit_background=True)
        pg3 = b.new_page(viewport={"width": 1920, "height": 1080})
        pg3.set_content(END_HTML); pg3.screenshot(path=str(BUILD / "endcard.png"))
        b.close()

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:]); sys.exit(1)

def build_segment(i, s):
    src, a, b, speed, (zx, zy, zw, zh), cap, tag, freeze = s
    out = BUILD / f"seg{i:02d}.mp4"
    vf = f"[0:v]trim=start={a:.2f}:end={b:.2f},setpts=(PTS-STARTPTS)/{speed},crop={zw}:{zh}:{zx}:{zy},scale={CW}:{CH}:flags=lanczos,fps=30"
    if freeze:
        vf += f",tpad=stop_mode=clone:stop_duration={freeze}"
    vf += f",pad={W}:{H}:{X0}:0:color=0x1d2433[v0];[v0][1:v]overlay=0:{H - BAND}[v1]"
    inputs = ["-i", str(RAW / f"{src}_raw.mp4"), "-i", str(BUILD / f"cap{i:02d}.png")]
    last = "v1"
    if tag:
        inputs += ["-i", str(BUILD / f"tag_{tag.replace('×','x')}.png")]
        vf += f";[v1][2:v]overlay={X0 + CW - 230}:24[v2]"; last = "v2"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", vf, "-map", f"[{last}]", "-an",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", str(out)])
    return out

if __name__ == "__main__":
    render_pngs()
    parts = [build_segment(i, s) for i, s in enumerate(SEGS)]
    end = BUILD / "seg_end.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", "7", "-i", str(BUILD / "endcard.png"), "-vf", "fps=30,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", "30", str(end)])
    parts.append(end)
    (BUILD / "concat.txt").write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    out = Path("video/tipping_point_rough_cut.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(BUILD / "concat.txt"), "-c", "copy", "-movflags", "+faststart", str(out)])
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
    print("OUT", out, f"{d:.1f}s")
    for i, p in enumerate(parts):
        dd = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
        print(f"  seg{i:02d} {dd}s")
