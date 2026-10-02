# Local document and mail tooling (macOS)

Small command-line tools for working through a large personal archive of PDFs and Apple Mail on a Mac.
The document and mail tools run locally and call no web service:

- give every PDF a searchable text file, and OCR the scans (`local_pipeline/`)
- check a redaction for ID-shaped and card-shaped numbers
- read the Apple Mail store directly, and sweep it for phishing
- build a pointer index with a local model (Ollama, on this machine)
- inspect, fill and check PDF forms (`pdf_forms/`)
- turn a stack of scanned paper statements into one CSV (`scan_intake/`)

Two utilities in `tools/` do reach outside the machine, by design: `backup_repo_bundle.sh` copies a git
bundle to a backup folder you name (which may be one that syncs to a cloud), and `datecheck.sh` reads
the `Date` header of a few public websites.

`TOOL_INDEX.md` lists every tool in one line each. The header of each file gives its usage, the
environment variables it reads and what it needs installed.

## Requirements

macOS for the Mail and Vision tools; the PDF text pipeline and the form tools also run on Linux.
bash 3.2 or later and Python 3.9 or later. Depending on the tool: poppler (`pdftotext`, `pdfimages`),
tesseract and ocrmypdf, the `sqlite3` command-line tool, `curl`, `git`, Ollama, and the Python packages
`pypdf`, `reportlab` and `pyobjc-core`.

## Privacy

The tools read private documents and write reports about them. Some reports contain the very numbers
they look for, and others list senders and subjects. Write reports outside this repo.

`.gitignore` keeps the usual outputs out if one lands here anyway: PDFs, mail files, JSON other than the
example config, TSV, CSV, JSONL, bundles and the `_DERIVED/` folder. It does not cover Markdown or
plain-text outputs (reports, OCR sidecars written beside a scan), so do not point a tool's output here.

`tools/pii_guard.sh` fails when a tracked file carries a home-directory path, a hyphenated 3-2-4 digit
ID, a run of 13 to 19 digits or a real email address. Run it before every push; a git pre-push hook that
calls it is the easy way. It is a tripwire for four patterns. It does not see names, addresses, phone
numbers or prose that says too much, and it skips lines marked `pii-guard: allow`.

## Known limits

- The phishing sweep scores on sender and subject only and is tuned for recall of obvious cases; treat
  its output as a list to look at.
- The form filler estimates text width from character counts; `check_field_fit.py` measures in Helvetica.
- There is no automated test suite. The scripts are checked by hand on macOS; the PDF pipeline and form tools also on Linux.

## License

MIT. See `LICENSE`.
