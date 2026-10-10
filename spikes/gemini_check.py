"""Run the three fixtures through the Gemini reader and compare with fixtures/expected.json.
Usage (once a key exists):  GEMINI_API_KEY=... [GEMINI_MODEL=...] .venv/bin/python spikes/gemini_check.py
Uses only the free-tier generateContent endpoint; 3 requests total."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tipping_point.chat import parse_export
from tipping_point.ledger import build_order_list
from tipping_point.readers import GeminiReader, ReaderContext

F = Path(__file__).resolve().parent.parent / "fixtures"
exp_all = json.loads((F / "expected.json").read_text())
r = GeminiReader()
print("model:", r.model)
ok_all = True
for name, exp in exp_all.items():
    ctx = ReaderContext(exp["ctx"]["organiser"], exp["ctx"]["variants"], exp["ctx"].get("aliases", {}))
    try:
        ev = r.extract(parse_export((F / name).read_text()), ctx)
    except Exception as e:  # noqa: BLE001
        print(f"{name}: ERROR {type(e).__name__}: {str(e)[:300]}"); ok_all = False; continue
    ol = build_order_list(ev, ctx.variants, exp["ctx"].get("max_per_person"))
    rows = sorted([r["participant"], r["variant"], r["qty"]] for r in ol.as_rows() if r["qty"])
    want = sorted(map(list, exp["rows"]))
    got_issues = sorted((i.kind, i.participant) for i in ol.issues)
    want_issues = sorted(tuple(i) for i in exp.get("issues", []))
    same = rows == want and ol.total == exp["total"]
    print(f"  issues {'same' if got_issues == want_issues else 'DIFF'}: got {got_issues}" + ("" if got_issues == want_issues else f" want {want_issues}"))
    ok_all &= same
    print(f"{name}: {'MATCH' if same else 'DIFF'} total {ol.total} (want {exp['total']})")
    if not same:
        print("  got :", rows); print("  want:", want)
sys.exit(0 if ok_all else 1)
