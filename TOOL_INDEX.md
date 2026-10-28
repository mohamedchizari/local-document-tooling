# Tool index

| tool | what it does |
|---|---|
| `local_pipeline/extract_all.sh` | writes a text sidecar for every PDF under a folder; resumable; rebuilds a NUL-delimited image-only queue and exits nonzero on extraction or image-check failures (an image-check failure on a PDF already OCR'd is logged, not counted) |
| `local_pipeline/ocr_queue.sh` | OCRs the image-only PDFs that `extract_all.sh` listed; never changes an original; exits with status 1 if a file failed |
| `local_pipeline/env.sh` | sourced by the two scripts above: adds `PDFTOOLS_BIN` to PATH and moves `TMPDIR` under the home folder |
| `local_pipeline/pii_sweep.sh` | finds hyphenated 3-2-4 IDs and 13 to 19 digit runs (card checksum tested) in the text sidecars; starts with a canary self-test and handles newline filenames |
| `local_pipeline/mail_extract.sh` | lists the Apple Mail messages whose raw `.emlx` file contains a term (case-insensitive; encoded bodies are not searched); counts header-only files separately and reads file paths NUL-delimited, so names with line breaks work |
| `local_pipeline/scam_sweep.py` | scores received mail for phishing signals from the Mail index, then checks Reply-To and SPF/DKIM/DMARC on the top hits |
| `local_pipeline/local_triage.py` | an Ollama model writes one pointer card per text file; refuses to run unless a canary call succeeds; any endpoint not on this machine needs an explicit opt-in; a request to this machine never goes through a proxy |
| `local_pipeline/ask_local.sh` | sends one narrowed question, with stdin as the text, to Ollama; any endpoint not on this machine requires an explicit opt-in; a request to this machine never goes through a proxy |
| `local_pipeline/config.example.json` | example config for `local_triage.py` |
| `local_pipeline/drive_folder_diff.py` | lists files that are only in a synced folder, only in a local folder, or in both, by file name and size, optionally SHA-256 |
| `local_pipeline/app_census.py` | Markdown list of installed Mac apps with architecture, from `system_profiler` JSON |
| `scan_intake/scan_intake.py` | interleaves front and back scan passes, OCRs them with nonzero status on failure, and writes one CSV row per statement; the CSV holds only the last four digits of an account number |
| `pdf_forms/widget_dump.py` | lists every form widget in a PDF with its name, position, label, value and state; reports pdftotext errors, and warns and skips a file pypdf cannot open or walk |
| `pdf_forms/fill_form.py` | fills a PDF form from a JSON values file, widget by widget |
| `pdf_forms/check_field_fit.py` | reports filled text fields whose value does not fit the box |
| `tools/vision_ocr.py` | OCRs a list of PDFs with the macOS Vision framework; JSONL reports actual coverage and page failures |
| `tools/vision_ocr_one.py` | OCRs one PDF with macOS Vision and prints it page by page; unlocks a password-protected PDF |
| `tools/backup_repo_bundle.sh` | writes a git repo to one bundle, restore-tests it, copies it to a backup folder and compares checksums |
| `tools/restore_test_bundle_chain.sh` | restores a full bundle plus its incremental bundles into a scratch clone and compares the tip with the live repo |
| `tools/pii_guard.sh` | fails when a tracked file carries a home path, a hyphenated 3-2-4 ID, a 13 to 19 digit run or a real email address |
| `tools/stamp.sh` | prints the current time in UTC and local time, for log lines |
| `tools/datecheck.sh` | prints the HTTP `Date` header of several public sites next to the local clock; exits nonzero on request/header failures |
| `tests/run_checks.sh` | checks the PDF text pipeline and the amount patterns of `scan_intake.py` against generated fixtures; PASS, FAIL or SKIP per assertion |
| `tests/make_fixtures.py` | writes the made-up PDFs the check script uses |
| `tests/test_reliability.py` | focused regressions for amount signs and separators, extraction/OCR failures, hashes, endpoint and proxy policy, coverage reporting, dates (error responses included), form-dump failures and worktree and subfolder backups |
