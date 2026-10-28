# Contributing

Fixes and small additions are welcome. A change has to keep these true:

1. **No real data, anywhere.** Examples use `example.com` addresses, made-up names and test numbers.
   A test value that looks like an ID or a card number is assembled at run time, as the canary in
   `local_pipeline/pii_sweep.sh` does, so that the source file does not contain it.
   Run `bash tools/pii_guard.sh` before you push, and read your diff as well: the guard sees four
   patterns and nothing else, and it does not read history.
2. **Sources stay read-only.** A tool writes its own output files: under `_DERIVED/`, beside its
   input with a derived name, or in a place the user names. It does not modify, move or delete an
   input.
3. **A tool that can report "none" must be able to fail, or must show its count.** Stop on zero
   input, run a canary with a known answer through the same code path first, or print how much was
   read so that a zero is visible.
4. **Say what was not covered.** If part of the input cannot be read (a scan with no text layer, an
   encoded body, a cloud placeholder), name it in the output or the usage text, and count it where
   you can.
5. **A model's output is a pointer.** Nothing in this repository treats text from a language model as
   a fact about a document.
6. **The header is the documentation.** Each file starts with its usage and, where they apply, the
   environment variables it reads and what it needs installed. Change the header and `TOOL_INDEX.md`
   together with the code.
7. **Shell scripts run on bash 3.2**, the version macOS ships: no `mapfile`, no associative arrays.

`bash tests/run_checks.sh` checks the PDF text pipeline and the amount patterns of `scan_intake.py`
against generated fixtures and runs focused reliability regression tests; run it when you touch
those, and add a case for what you changed. The other tools have selected regression coverage, but
many behaviors remain manually checked. In a pull request, say what you ran the change against and
what came out, using made-up input only. `docs/DESIGN.md` lists what each tool checks about itself.

By contributing you agree that your contribution is released under the MIT license in `LICENSE`.
