# Safety: the guard rails, and why they are built into the tools

These tools are pointed at private documents and private mail. This page says what they can and
cannot do to that data, what their reports contain, how the repository itself is kept clean, and why
the checks are code and not advice.

## What the tools do to your data

**They read sources and do not change them.** The PDF pipeline, the mail tools, the local-model tools
and the folder diff do not write to their inputs. No tool moves, renames or deletes a document.
A tool does not check that an output path you give is different from an input: name an input as the
output of `fill_form.py` or of the collate step of `scan_intake.py`, and it is replaced.

**They do not touch mail.** `mail_extract.sh` and `scam_sweep.py` read the mail store and its index.
Nothing is sent, moved, labelled, marked read or deleted. The index is a SQLite database opened
read-only; SQLite may create its `-shm` and `-wal` helper files beside it, and the index itself is
not written.

**What they write is their own output files, in a place you can see.** A tool replaces an earlier
output of the same name without asking.

| tool | writes | where |
|---|---|---|
| `extract_all.sh`, `ocr_queue.sh` | text sidecars, OCR copies, a log, the image-only list | `_DERIVED/` under the archive root; OCR staging files in `~/.ocrtmp` |
| `pii_sweep.sh` | one report | `_DERIVED/` under the archive root |
| `mail_extract.sh` | one Markdown report | the output folder you name |
| `scam_sweep.py` | three TSV files | the output folder you name |
| `local_triage.py` | one TSV index | `index_dir` from your local config, or the path given with `--out` |
| `drive_folder_diff.py` | four TSV files and a summary | the output folder you name |
| `scan_intake.py` | the collated PDF and the index CSV; an OCR copy and a text sidecar for each scan; a blank-pages CSV | the two paths you name; beside each scan and beside the index, with derived names |
| `fill_form.py` | the filled form | the output path you name |
| `vision_ocr.py` | one JSONL file | the output path you name |
| `backup_repo_bundle.sh` | one bundle | the backup folder you name |
| `tests/run_checks.sh` | generated fixtures and what the pipeline makes of them | the work folder you name, or a new temporary folder; OCR staging files in `~/.ocrtmp` |

**The only things they delete are their own temporary files:** the canary file of `pii_sweep.sh`,
the partial sidecar of a failed extraction in `extract_all.sh`, the partial outputs of a failed OCR
in `ocr_queue.sh`, the page images of the Vision OCR tools and the work folder of
`backup_repo_bundle.sh`. `ocr_queue.sh` also replaces a queue file in the old one-path-per-line
format (its own earlier output) with a rewritten copy, only when every path was written to the copy;
if not, it removes the copy and leaves the old queue as it was.
`restore_test_bundle_chain.sh` leaves its scratch clone in place. It prints where the clone is when
the test runs, and not when it stops with status 2.

## What leaves the machine

The document and mail tools call no web service. These can reach outside, each by a setting or a
command you choose:

- **The local model.** `ask_local.sh` and `local_triage.py` send text to the address in `OLLAMA_URL`,
  which defaults to this machine. A non-loopback HTTP endpoint is refused unless
  `OLLAMA_ALLOW_REMOTE=1` is set; HTTPS endpoints are allowed. If you point either tool at another
  host, the text of your documents goes to that host. Use the opt-in only when that transfer is
  intended and the network is trusted.
- **The backup.** `backup_repo_bundle.sh` copies a bundle of the whole repository history to the
  folder in `BACKUP_DEST`. If a sync client uploads that folder, the bundle leaves the machine.
- **The clock check.** `datecheck.sh` requests the headers of the websites you name, or of four
  public sites if you name none.
- **The `_DERIVED/` folder.** It sits inside the archive root. If a sync client uploads that root,
  the text sidecars and the redaction report go with it.
- **Other outputs.** The OCR copy and text sidecar that `scan_intake.py` writes beside each scan, and
  any report folder you name. If a sync client uploads that folder, they go with it.

## What the reports contain

The reports are as private as the documents. Write them outside this repository.

| report | holds |
|---|---|
| text sidecars and OCR output (`extract_all.sh`, `ocr_queue.sh`, the `ocr` step of `scan_intake.py`, `vision_ocr.py`) | the text of each document as far as it was read (`vision_ocr.py`: the first 12 pages of each PDF unless you pass another number, and at most 400,000 characters), account numbers included |
| `pii_sweep.sh` report | the matched numbers in full |
| `mail_extract.sh` report | dates, senders or recipients, subjects, attachment names |
| `scam_sweep.py` TSV files | sender addresses, display names, subjects, the mailbox folder name, a short account identifier, Reply-To addresses and authentication results |
| `local_triage.py` index | file paths, a one-sentence description, proper nouns and dates found in each file |
| `scan_intake.py` index | issuer, last four digits, closing date, balances |
| `drive_folder_diff.py` output | file names and paths |
| `widget_dump.py` output | the values in a filled form |

## Keeping this repository clean

Three layers, none of them sufficient alone:

1. **`.gitignore`** keeps the usual outputs out: PDFs, mail files, JSON other than the example config,
   TSV, CSV, JSONL, bundles and `_DERIVED/`. It does not cover Markdown or plain-text reports.
2. **`tools/pii_guard.sh`** fails when a tracked file carries a home-directory path, a hyphenated
   3-2-4 digit ID, a run of 13 to 19 digits or an email address other than an `example.com`, `.org` or
   `.net` address or a GitHub no-reply address. Install it as a pre-push hook:

   ```bash
   printf '#!/bin/bash\nexec bash tools/pii_guard.sh\n' > .git/hooks/pre-push
   chmod +x .git/hooks/pre-push
   ```

   It checks the working-tree copies of tracked files, not the commits being pushed. Commit a fix
   before trusting a clean result. A value that was committed and later removed still goes out with
   the history, and the guard reports clean when nothing is tracked yet.
3. **Reading the diff.** The guard is a tripwire for four patterns. It does not see names, street
   addresses, phone numbers or a comment that says too much. A guard that passes is not a clearance.

Commit metadata is published with the code. Before the first commit to a repository that may become
public, set the author address to a no-reply address.

## Secrets

- `vision_ocr_one.py` reads a PDF password from the environment variable `PDF_PASSWORD` or from a
  prompt, never from a command-line argument, because arguments show up in the process list and in
  the shell history.
- Local values for `local_triage.py` (the canary file and its expected words) live in
  `config.local.json`, which is git-ignored. Only the example config is tracked.
- No tool stores a password or a token.

## Why the checks are code and not advice

A written rule is followed when someone remembers it, and the day it matters is usually the day
nobody does. "Check that the search really ran" is good advice and is skipped at the end of a long
session. A sweep that stops when its canary does not fire cannot be skipped.

So each rule on the design page is attached to the act it guards:

- The redaction sweep does not report on an archive until it has found three planted values.
- The form filler prints every entry it used whose state no widget on that page has, so a checkbox
  left unticked for that reason is not silent. (Of two entries for one field on one page it uses
  only the last.)
- The backup script does not call a bundle good until it has cloned it, unless you tell it to skip
  that step.
- The mail report ends with the list of what it did not search.

A check that runs every time costs a second. A check that depends on memory fails without a sound.

Not every check stops the run. A failed extraction is logged, the run goes on with the next file,
and `extract_all.sh` exits with status 1 at the end. A form entry that matched nothing is printed
and the form filler still exits with status 0. The last lines of the output have to be read.

This matters most when the operator is an AI assistant. An assistant can follow a written
instruction a thousand times and miss it once, with no sign that anything was missed. These tools
were written to be run by an assistant on its owner's behalf as well as by a person. Where a script
can refuse, it does, so less depends on recall.

## What these guard rails do not do

They do not decide what a document, a number or a message means. They narrow where a person has to
look, and they say when they could not look.
