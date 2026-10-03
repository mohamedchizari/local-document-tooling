# Design: what each tool is for, and the failure it exists to prevent

Each tool answers a failure that is generic and repeatable. This page gives that failure for each
tool, as a scenario with no real data in it, then what the tool checks about itself when it runs, and
its known limits.

"Built-in checks" below means checks the tool runs on every use. The last section says how the tools
themselves were checked: the PDF text pipeline and the statement amounts by a script, the rest by
hand.

## The idea underneath

A search that returns nothing has two possible meanings: the thing is not there, or the search did
not work. They look the same on the screen. Most of the tools in this repo exist to tell the two
apart, in one of three ways:

1. **Stop on zero input, or show the count.** `extract_all.sh`, `ocr_queue.sh` and `mail_extract.sh`
   stop with an error when they find nothing to read. `pii_sweep.sh` and `scam_sweep.py` print how
   much they read, so a zero is on the screen.
2. **Run a canary first.** A file with a known answer goes through the same code path as the real
   input. If the known answer does not come out, the tool stops.
3. **Name what was not read.** Where a tool cannot see part of the input (a scan with no text layer,
   an encoded mail body), it names that part in its output or its usage text, and counts it where it
   can.

Not every check stops the run. Several tools print a problem and still exit with status 0. The
limits below say where.

## PDF text pipeline (`local_pipeline/`)

### `extract_all.sh`

**Failure it prevents.** Someone searches a folder of PDFs for a term, finds nothing and concludes
the term appears in no document. Half of the PDFs were scans with no text layer, and a few had an
upper-case `.PDF` extension that the search pattern skipped.

**What it does.** Writes one text sidecar per PDF under `_DERIVED/text/`, so that a later search is a
grep over text files. It lists each PDF that holds at least one raster image and whose sidecar has
fewer than 200 bytes of non-blank text, because those have not been read yet. A PDF whose OCR copy
is newer than the PDF itself is not listed, however little text the OCR found.

**Built-in checks.** Stops if it finds zero PDFs. Matches the extension without regard to case.
Separates a scan (a raster image, almost no text) from a short document with no image in it, so that
a short page of plain text is not queued for OCR. Counts only the bytes that are not white space:
the extractor writes one byte per page even for an empty page, so the sidecar of a long scan is
hundreds of bytes with nothing in them. Skips a PDF whose sidecar is newer than the PDF, and rebuilds the
image-only list on every run, so that a scan stays listed until it has been OCR'd. When the sidecar
of a PDF that was already OCR'd has to be written again, it is written from the OCR copy, which has
the text.

**Limits.**

- The test is per file. A PDF that mixes text pages and scanned pages has enough text to pass, and
  its scanned pages stay unread. So does a scan with a running header or footer of real text on each
  page.
- A short page of real text that also holds an image, such as a logo, is listed, and `ocr_queue.sh`
  then replaces its sidecar with OCR text.
- A PDF that cannot be extracted (locked, damaged) is counted as failed and written to the log. It is
  not on the image-only list, and the exit status is still 0.
- A file without a `.pdf` extension is not seen.
- The image-only list holds one path per line. A file whose name contains a line break is reported
  as missing by `ocr_queue.sh` and is not OCR'd.
- "Newer" is judged by modification time only. A PDF that is replaced by a different file with an
  older date keeps the sidecar and the OCR copy of the file before it; to force a re-read, delete
  both. A PDF dated in the future is extracted again on every run, and OCR'd again on every run if it
  is a scan.
- The 200 is a count of bytes. A character outside ASCII counts as two or more, so a scan with a
  short text layer in such characters can pass.

### `ocr_queue.sh` and `env.sh`

**Failure it prevents.** A text extractor returns an empty string for a scanned page, and the empty
string is read as "nothing on this page".

**What it does.** OCRs the PDFs that `extract_all.sh` listed. The text goes to the same sidecar path.
An OCR'd copy of the PDF goes under `_DERIVED/ocr_pdf/`, named after the whole file name
(`a.pdf_OCR.pdf`), so that `a.pdf` and `a.PDF` do not share one copy. The original is not modified.

**Built-in checks.** Stops with status 1 if there is no queue file or it is empty. Asks before it
starts, unless `OCR_YES=1` is set; if no answer can be read (no keyboard), it says so and exits with
status 1. Skips a file whose sidecar exists and whose OCR copy is newer than the PDF. Writes both
outputs under temporary names and renames them only when the OCR succeeded, so a failed run leaves
nothing that looks finished. Prints four counts (OCR'd, already done, failed, missing) and exits
with status 1 if any file failed or was missing. `env.sh` moves the OCR staging directory under the
home folder, because OCR launched from a non-login shell may be unable to read files under `/tmp`.

**Limits.** Every page of a listed file is OCR'd (`--force-ocr`), a page with a real text layer
included; see the logo case above. A "no" at the question exits with status 0. OCR copies written by
the first published version were named without the PDF's own extension (`a_OCR.pdf`) and are not
recognised: a scan whose sidecar holds fewer than 200 bytes of non-blank text is OCR'd once more.
Run `extract_all.sh` first; with a queue file left by the first version, every file in it is OCR'd
again. A run that is killed can leave `.part` files under `_DERIVED/`. They are not taken for
outputs and `pii_sweep.sh` does not read them; the next OCR of the same file replaces them.

### `pii_sweep.sh`

**Failure it prevents.** Two opposite ones. A redaction check that looks only for 16-digit card
numbers misses a 17-digit account number. A check that removes every space in a file before looking
glues unrelated table columns together and reports card numbers that are nowhere in the document;
about one random digit string in ten passes the card checksum, so some of those inventions look valid.

**What it does.** Finds hyphenated 3-2-4 digit IDs and runs of 13 to 19 digits in the text sidecars.
Separators are removed inside one candidate only. Each long run is labelled as passing the card
checksum or not.

**Built-in checks.** Builds a canary file at run time with three known hits and stops if fewer than
three come back. The canary values are assembled from pieces, so the script's own source does not
contain an ID-shaped or card-shaped number. Prints the number of sidecars it scanned. At the end it
prints a reminder that the report holds the matched numbers in full and has to be kept private.

**Limits.**

- It reads sidecars only. A scan that was never OCR'd is not covered, and the report does not list
  those.
- An ID written with spaces, with dots or with no separator is not found.
- Two numbers that sit exactly one space apart are joined into one candidate, so a card number
  followed by another number can be reported as one longer number.
- A run of more than 19 digits is reported in pieces of up to 19 digits, starting with its first
  19; a last piece shorter than 13 digits is dropped.
- The canary proves that the patterns fire. It does not test the checksum label, which needs
  `python3`: without it, a valid card number is still reported, as a long number.
- The exit status is 0 with or without hits.

## Mail (`local_pipeline/`)

### `mail_extract.sh`

**Failure it prevents.** The mail client's index shows no messages from a sender in the mailbox where
they are expected, and the conclusion is that none exist. The messages are on disk under a different
mailbox folder. A second version of the same failure: a message whose body was never downloaded is
counted as a message that was read.

**What it does.** Reads the `.emlx` files themselves and lists every message whose raw file contains
a term, with date, sender or recipients, subject and attachment names.

**Built-in checks.** Stops if the store holds zero `.emlx` files. Counts header-only `.partial.emlx`
files and marks each row `full` or `partial`. Opens the index read-only in a mode that still sees
the newest rows. Restricts the term to a safe character set, since it is also used in a file name and
a query. Ends the report with what it did not search: encoded bodies, attachments, the bodies of
partial messages, the provider's web mailbox and accounts with no local copy.

**Limit.** The match is on the raw bytes of each file. An address in a header is found; a word inside
an encoded body or an attachment is not.

### `scam_sweep.py`

**Failure it prevents.** A lookalike sender uses a trusted brand as its display name and gets past
the junk filter. Read one message at a time, it looks plausible. Seen in a table of every sender that
uses a brand name from an unrelated domain, it does not.

**What it does.** Scores the messages in its window (one year back unless `--since` says otherwise)
on sender address, display name and subject. For the highest-scoring messages that are not already in
Junk, it reads the headers for a Reply-To that points to another domain and for SPF, DKIM and DMARC
results. Writes three TSV files. It never moves, labels or deletes mail.

**Built-in checks.** Brand names match as whole words, so a short brand name does not match inside a
longer word. A brand's own subdomains count as that brand. A long domain made of ordinary words is not
treated as random. It prints the number of messages scanned, so a zero is visible.

**Limits.**

- The score uses sender and subject only. It is a list to look at, not a verdict.
- To leave out sent mail and drafts, it skips every mailbox whose address contains "sent" or "drafts"
  anywhere, in any letter case. A folder named "Consent" or "Presentations" is skipped too.
- The header check covers the top 150 candidates outside Junk unless `--top` says otherwise.
- The TSV files do not record the window they cover.

## Local model (`local_pipeline/`)

### `local_triage.py` and `config.example.json`

**Failure it prevents.** A small local model summarises a folder of files, and its summaries are
then quoted as if they were the documents. A wrong date in a summary is indistinguishable from a
right one.

**What it does.** Writes one pointer card per text file: the question a reader would open the file to
answer, proper nouns and dates exactly as written, a kind, and whether a person needs to act. The
index says where to look.

**Built-in checks.** A canary file with a known answer is carded first; if the card misses the
expected tokens, nothing is indexed. Waits when another model holds the single model slot, instead of
queueing requests that time out into error rows. Resumable: good rows are kept, failed rows are
retried, and files never tried come first so that one file that always fails cannot block the rest.
Local values (the canary path and tokens) live in a git-ignored config file beside the script.

**Limits.** The model sees the first 12,000 characters of each file, and the index does not mark a
file that was longer. One run cards at most `--limit` files (200 unless told otherwise), new ones
first and then retries, and prints the totals at the end.

### `ask_local.sh`

**Failure it prevents.** A model that is larger than the machine's memory is asked a question and
appears to hang; or a model's yes/no label is taken as a finding.

**What it does.** Sends one narrowed question, with standard input as the text, to a local model and
prints the answer.

**Built-in checks.** Refuses to run if the local `ollama` command does not list the model, and prints
the models it does list. Prints the model and its size before the answer. After every request to the
model, answered or failed, it prints a line saying that the output is a filter and the source document
has to be opened.

**Limit.** The model check asks the local `ollama` command. With `OLLAMA_URL` pointed at another
server, the check and the request go to different servers.

## Folders and machine (`local_pipeline/`)

### `drive_folder_diff.py`

**Failure it prevents.** Two copies of a folder tree, one local and one synced, are assumed to be the
same because they have the same top-level folders. One side is then cleaned up.

**What it does.** Lists files that are only in the synced tree, only in the local tree, or in both,
keyed by file name and size, and optionally by checksum.

**Built-in checks.** Takes a list of directory names to skip, for a copy of one tree kept inside the
other. The summary it writes gives the file counts of both trees and states what the key can and
cannot tell apart.

**Limits.** Dot-files, dot-directories, `.git`, `__pycache__`, `node_modules`, `.Trash`, cloud
placeholder files (links, not documents), broken links, directories that cannot be opened,
directories inside either tree that are reached through a symbolic link and any directory named with
`--skip` are left out. (A root that is itself a link is followed.) The
usage text names the first seven and `--skip`; the summary counts none of them. A file that can be
listed but not read is still compared by name and size. With `--md5`, if a file of the same name and
size exists in the other tree, the run stops with an error before any report file is written.

### `app_census.py`

**Failure it prevents.** Nobody has a list of which installed apps are Intel-only.

**What it does.** Turns the system's application report into a Markdown table with architecture,
version and source, Intel-only apps first. It covers the apps under `/Applications` and
`~/Applications`. Architecture matters to the other tools: the fallback in the Vision OCR tool exists
for an Intel Python running on Apple Silicon.

## Scanned paper (`scan_intake/`)

### `scan_intake.py`

**Failure it prevents.** A two-sided stack is scanned as two one-sided passes. One sheet double-feeds
in the second pass, and every page after it is paired with the wrong back.

**What it does.** Three steps: interleave fronts and backs, OCR, and index. The index is one CSV row
per statement with issuer, last four digits, closing date, new balance, minimum due and page count.
Blank pages are listed in a second CSV.

**Built-in checks.** Refuses to interleave when the two page counts differ. Takes the last four
digits only from a labelled account line, and for a full 16-digit layout only when no fifth group
follows. Prints the number of statements and blank pages it found, and how many rows are missing an
issuer, last four or date; those rows need a look.

**Limits.**

- An amount is looked for after its label in this order: a signed amount directly after the label
  on the same line; an unsigned figure directly after the label, with only white space or colons
  between, on the same line or a line below; a signed amount after up to 30 characters of other text
  on the label's line; the nearest unsigned figure after up to 30 characters of other text on the
  label's line and any white space after that, line breaks included. An unsigned figure is passed
  over when a slash follows it directly, when a percent sign follows it directly or after one
  white-space character, when a point and a digit follow it (a dotted date), or when a point or a
  slash comes directly before it, as at the end of a row of dots. So an unsigned figure directly after the label wins over a signed
  one further along the line, and of two unsigned figures the nearer one is taken, whatever it is.
  When two labels sit side by side above their figures, unsigned figures are read wrongly (the
  second label takes the first figure) and signed ones are left blank. A credit balance is indexed
  without its minus sign. Check the amounts against the page.
- The index step does not print how many sidecars or pages it read. A first page that the patterns
  do not recognise is counted nowhere: it is added to the page count of the statement before it, or
  dropped if it comes first.
- The OCR step runs ocrmypdf with `--skip-text`. A page that already has a text layer is not
  OCR'd, so its text is not in the sidecar and the index step does not see it. The step writes an OCR
  copy and a text sidecar beside each scan, replacing an earlier file of the same name. The sidecar
  holds the OCR text in full, account numbers included; only the index is reduced to the last four
  digits.
- The OCR step does not use `env.sh`. Launched from a non-login shell it can fail in the way that
  file describes, until `TMPDIR` points to a folder under the home folder.

## PDF forms (`pdf_forms/`)

### `widget_dump.py`

**Failure it prevents.** A form is filled by field name, and a field that has two widgets (a radio
group, or one field shown in two places) ends up with one of them wrong, because the field tree shows
one entry.

**What it does.** Walks the widgets on each page and prints one row per widget: field name, position,
the printed label to its left, the text above it, the value and, for buttons, the appearance state.
It checks nothing; it prints what is there.

**Limit.** The label and the text above a widget are found by position on the page. They are a guide
to which box is which, and can be wrong on a dense form.

### `fill_form.py`

**Failure it prevents.** A value is written to a checkbox using a state name that the widget does not
have, the file saves without an error, and the box is not ticked.

**What it does.** Fills a form from a JSON list of page, field name and value.

**Built-in checks.** For a button, the value has to be a state that some widget of that field on
that page really has; otherwise nothing is changed and the entry is reported as missing. Choosing one radio button
switches off the other buttons of its group on the same page. A single-line value that cannot fit at the minimum font size is
listed as too long. Every entry that matched no widget is printed.

**Limits.** It prints those problems, still writes the output file and exits with status 0. A
multi-line value is wrapped and not measured against the height of its box; that is the job of
`check_field_fit.py`. Entries are matched page by page: buttons of a radio group that sit on another
page are not touched, and when two entries name the same field on the same page the last one wins
without a message.

### `check_field_fit.py`

**Failure it prevents.** A filled form looks complete in the values file, and on paper a value is
cut off at the edge of its box.

**What it does.** Measures each filled text field against its box: width for single-line fields,
wrapped line count against height for multi-line fields. Exit status 1 if anything overflows.

**Limit.** Widths are measured in Helvetica whatever font the field names. A field whose font size is
automatic (0) or missing is measured as 8 pt. A viewer may draw such a field smaller, so an overflow
reported for it needs a look at the rendered page.

## macOS Vision OCR (`tools/`)

### `vision_ocr.py` and `vision_ocr_one.py`

**Failure it prevents.** A Mac has no OCR software installed, and scans are set aside as unreadable
although the operating system ships a text recogniser.

**What it does.** Renders PDF pages with PDFKit and runs the Vision text recogniser on them.
`vision_ocr.py` takes a list of PDFs and writes one JSON line per PDF. `vision_ocr_one.py` prints one
PDF page by page, next to the page's own text layer when it has one.

**Built-in checks.** Tries the accurate recognition level first and falls back to the fast level
when the accurate one returns nothing, which happens without an error under an Intel Python on Apple
Silicon. Page images go to a temporary folder that is removed when the run ends. `vision_ocr_one.py`
reads a PDF password from an environment variable or a prompt, never from an argument, because
arguments show up in the process list and the shell history.

**Limits.** `vision_ocr.py` reads at most 12 pages of each PDF unless given another limit, keeps at
most 400,000 characters of text per PDF, and has no handling for a locked PDF. Each JSON line carries
the page count, the number of pages it was allowed to read, the character count and any error.
Compare the first two to see whether a PDF was longer than the limit, and look for a character count
of zero.

## Repository utilities (`tools/`)

### `backup_repo_bundle.sh`

**Failure it prevents.** A backup file exists, has a plausible size, and does not restore.

**What it does.** Writes the whole history of a git repository to one bundle file and copies it to a
backup folder.

**Built-in checks.** Clones the new bundle and counts the commits and files it restored, before
copying it (`SKIP_RESTORE=1` skips this step for a large repository). Compares the checksum of the copy
with the source. Counts the uncommitted paths, which a bundle does not cover, and shows the first five.

**Limit.** Files that git ignores, a local config file for example, are not in the bundle and not in
the count of uncommitted paths.

### `restore_test_bundle_chain.sh`

**Failure it prevents.** A backup made of one full bundle and many incremental bundles has a hole:
one commit that was never bundled. Each bundle still verifies, because the usual verify command only
asks whether a bundle's prerequisite commits exist in the live repository, and they always do.
Nothing after the hole can be restored.

**What it does.** Clones the newest full bundle into a scratch folder, applies every incremental
whose prerequisites are present, repeats until the tip stops moving, and compares the tip with the
live branch. Prints one `RESULT` line and, when the chain is short, the one command that bridges it.

**Built-in checks.** Exit status 0 when the backup restores to the live tip, 1 when it is broken or
behind, 2 when the test could not run (no full bundle, no branch).

**Limits.** With `REPO` or `BACKUP_DIR` unset it also exits with status 1. It leaves its scratch
folder behind; it prints the path when the test runs, and not when it stops with status 2.

### `pii_guard.sh`

**Failure it prevents.** A home-directory path, an ID number or an email address is committed to a
repository that is later made public.

**Built-in checks.** Refuses to run unless the folder above `tools/` is itself a repository root, so
that it cannot climb to a parent repository and scan that instead. Tests each match on its own, so a
placeholder on the same line does not hide a real value. Reports the file and the kind of hit, not
the value.

**Limits.**

- Four patterns. It does not see names, street addresses, phone numbers, IDs written without hyphens
  or prose that says too much, and it skips any line that carries its allow marker.
- It reads the working-tree copies of tracked files, not the commits being pushed. Commit a fix
  before trusting a clean result. A value that was committed and later removed is still in the
  history, and the guard does not see it.
- It skips png, jpg, pdf and zip files. With no tracked files it reports clean.

### `stamp.sh` and `datecheck.sh`

**Failure they prevent.** A log line carries a time that was typed from memory and is an hour off,
or a machine's clock is wrong and nothing shows it.

**What they do.** `stamp.sh` prints the time in UTC and local time, read from the clock.
`datecheck.sh` prints the HTTP `Date` header of several public sites next to the local clock, with
each response's cache markers, since a cached response carries an old date. It prints; it does not
compute a difference.

## How the tools were checked

`tests/run_checks.sh` covers the PDF text pipeline and the amount patterns of the scan intake: 43
assertions over fixtures it generates itself (a text PDF, a short one, a one-page scan, a nearly
blank scan, a 210-page scan, an OCR stand-in that fails after writing partial output, a root folder
with `[`, `*` and `?` in its name, and two files that differ only in the case of the extension). It
was run on Linux and on macOS with bash 3.2. On a file system that does not tell `a.pdf` from
`a.PDF`, the five assertions on that pair are skipped.

Everything else was checked by hand. Every document fixture is made up. Two kinds of tool need the
machine itself: the mail tools were run against a local mail store, with only the counts they
printed read, and the application census against the machine's own application list.

- On macOS: the OCR step of the scan intake, the two Vision OCR tools and the two local-model tools
  against made-up documents; the mail tools and the census as described above; the backup and clock
  tools against this repository.
- On Linux: the three form tools, the collate and index steps of the scan intake, the folder diff
  and the guard with its pre-push hook, against generated PDFs, a generated form and text with
  planted test values.

Two defects in the first published version were found by reading the code against this page. A scan
of 200 pages or more was never listed for OCR, because the test counted bytes and the extractor
writes one byte per page. An amount printed without a currency sign was indexed as its last digit
and the cents. Both are fixed, and the check script holds a case for each.

No sample documents ship with the repository. The check script generates its fixtures, and every
value in them is invented.

A tool that reports a count should be given an input where the right count is known in advance. That
is what the canaries do on every run, and it is the first thing to do with any change.
