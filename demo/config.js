window.DEMO = {
  repo: "data-merger",
  title: "data-merger",
  tagline: "Drop in two or more exports of the same customers (CRM, billing, a mailing list). Get one merged record per customer, with conflicts kept side by side, a review list of close calls and where every value came from.",
  pkg: "data_merger",
  packages: ["openpyxl", "sqlite3"],
  inputs: [
    { id: "files", label: "Two or more CSV or XLSX files", accept: ".csv,.xlsx", multiple: true,
      sample: ["samples/crm_export.csv", "samples/billing_export.xlsx", "samples/mailing_list.csv"] },
  ],
  options: [
    { id: "auto", label: "Auto-merge at", type: "text", value: "", placeholder: "0.88" },
    { id: "review", label: "Review from", type: "text", value: "", placeholder: "0.70" },
  ],
  sampleNote: 'The sample is three synthetic exports of invented customers: <a href="samples/crm_export.csv">crm_export.csv</a>, <a href="samples/billing_export.xlsx">billing_export.xlsx</a> and <a href="samples/mailing_list.csv">mailing_list.csv</a>.<br>Matching uses rapidfuzz\'s own pure-Python implementation here, because rapidfuzz has no WebAssembly build. Same algorithms and scores, just slower than on a desktop.',
  python: `
import os
os.environ["RAPIDFUZZ_IMPL"] = "python"  # the C extension has no Pyodide build
from pathlib import Path
from data_merger.cli import main as cli_main

ORDER = ["Merged", "Review", "Conflicts", "Unmatched"]

def run(paths, opts):
    out = "/work/merged.xlsx"
    argv = ["merge", *paths["files"], "-o", out]
    for k in ("auto", "review"):
        if opts.get(k, "").strip():
            argv += ["--" + k, opts[k].strip()]
    code, log = run_cli(cli_main, argv)
    if code != 0 or not Path(out).exists():
        return {"ok": False, "log": log, "sheets": [], "download": None}
    sheets = sheets_from_xlsx(out)
    sheets.sort(key=lambda s: ORDER.index(s["name"]) if s["name"] in ORDER else len(ORDER))
    return {"ok": True, "log": log, "sheets": sheets, "download": out}
`,
};
