#!/usr/bin/env python3
"""vision_ocr_one.py - OCR one PDF with the macOS Vision framework and print the text page by page,
next to the page's own text layer when it has one.

Usage: python3 vision_ocr_one.py file.pdf
A locked PDF: put the password in the environment variable PDF_PASSWORD, or the script asks for it.
(It is not taken as an argument, because arguments show up in the process list and the shell history.)
Needs: macOS and `pip install pyobjc-core`.
"""
import getpass
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision_ocr import NSURL, PDFDocument_, ocr_png, page_png


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    pdf = sys.argv[1]
    d = PDFDocument_.alloc().initWithURL_(NSURL.fileURLWithPath_(pdf))
    if d is None:
        sys.exit(f"could not open {pdf}")
    if d.isLocked():
        pw = os.environ.get('PDF_PASSWORD') or getpass.getpass('PDF password: ')
        if not d.unlockWithPassword_(pw):
            sys.exit("wrong password")
    n = int(d.pageCount())
    print("[pages:", n, "]")
    with tempfile.TemporaryDirectory(prefix='vision_ocr_') as tmp:
        for i in range(n):
            p = d.pageAtIndex_(i)
            png = os.path.join(tmp, "p%d.png" % i)
            txt = ocr_png(png) if page_png(p, png) else ""
            native = str(p.string() or "")
            print("#" * 100)
            print("PAGE %d  (native chars: %d)" % (i + 1, len(native)))
            if len(native.strip()) > 20:
                print("--- native text ---")
                print(native)
            print("--- OCR ---")
            print(txt)


if __name__ == '__main__':
    main()
