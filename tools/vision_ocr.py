#!/usr/bin/env python3
"""vision_ocr.py - OCR image-only PDFs with the macOS Vision framework, through pyobjc-core.

For a Mac where tesseract and poppler are not installed. Renders each page with PDFKit to a PNG,
then runs VNRecognizeTextRequest on it. Writes one JSON line per PDF.

Usage: python3 vision_ocr.py <file-with-one-pdf-path-per-line> <out.jsonl> [max-pages-per-pdf, default 12]
Needs: macOS and `pip install pyobjc-core` in the Python that runs it (a native arm64 Python is best).
"""
import sys, os, json, objc, tempfile

objc.loadBundle("PDFKit", globals(),
                bundle_path="/System/Library/Frameworks/Quartz.framework/Frameworks/PDFKit.framework")
objc.loadBundle("AppKit", globals(),
                bundle_path="/System/Library/Frameworks/AppKit.framework")
objc.loadBundle("Vision", globals(),
                bundle_path="/System/Library/Frameworks/Vision.framework")
NSURL = objc.lookUpClass("NSURL")
NSBitmapImageRep = objc.lookUpClass("NSBitmapImageRep")
PDFDocument_ = objc.lookUpClass("PDFDocument")
VNImageRequestHandler = objc.lookUpClass("VNImageRequestHandler")
VNRecognizeTextRequest = objc.lookUpClass("VNRecognizeTextRequest")

PNG = 4          # NSBitmapImageFileTypePNG
MEDIABOX = 0     # kPDFDisplayBoxMediaBox
SCALE = 2.0      # ~144 dpi

def page_png(page, out):
    b = page.boundsForBox_(MEDIABOX)
    try:
        bw, bh = float(b.size.width), float(b.size.height)
    except AttributeError:          # pyobjc-core returns a plain ((x,y),(w,h))
        bw, bh = float(b[1][0]), float(b[1][1])
    w, h = bw * SCALE, bh * SCALE
    img = page.thumbnailOfSize_forBox_((w, h), MEDIABOX)
    tiff = img.TIFFRepresentation()
    rep = NSBitmapImageRep.imageRepWithData_(tiff)
    data = rep.representationUsingType_properties_(PNG, {})
    return bool(data.writeToFile_atomically_(out, True))

def _recognise(path, level):
    """Text lines Vision finds in one image at one recognition level (0 accurate, 1 fast); None when the request fails."""
    req = VNRecognizeTextRequest.alloc().init()
    try:
        req.setRecognitionLevel_(level)
        req.setUsesLanguageCorrection_(True)
    except Exception:
        pass
    # options is None, not {}: an empty Python dict raises "key does not exist" on recent macOS
    h = VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), None)
    # pyobjc-core has no Vision metadata, so error: is not an out-parameter here: the call returns a bare BOOL
    r = h.performRequests_error_([req], None)
    ok = r[0] if isinstance(r, tuple) else r
    if not ok:
        return None
    out = []
    for obs in (req.results() or []):
        c = obs.topCandidates_(1)
        if c and len(c):
            out.append(str(c[0].string()))
    return out


def ocr_png(path):
    """OCR one image. Accurate recognition first, then the fast level when accurate returns nothing:
    the accurate level fails without an error under an x86_64 Python running on Apple Silicon."""
    for level in (0, 1):
        lines = _recognise(path, level)
        if lines:
            return "\n".join(lines)
    return ""


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    pdflist, outp = sys.argv[1], sys.argv[2]
    maxpages = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    pdfs = [l.rstrip('\n') for l in open(pdflist) if l.strip()]
    # page images are private; the temporary folder is removed when the run ends
    with tempfile.TemporaryDirectory(prefix='vision_ocr_') as tmp, open(outp, 'w') as out:
        for i, p in enumerate(pdfs):
            txt, npg, err = [], 0, ''
            try:
                d = PDFDocument_.alloc().initWithURL_(NSURL.fileURLWithPath_(p))
                npg = int(d.pageCount()) if d else 0
                for k in range(min(npg, maxpages)):
                    png = os.path.join(tmp, f"p{i}_{k}.png")
                    if page_png(d.pageAtIndex_(k), png):
                        txt.append(ocr_png(png))
                    if os.path.exists(png):
                        os.remove(png)
            except Exception as e:
                err = str(e)[:200]
            t = "\n".join(txt)
            out.write(json.dumps({'pdf': p, 'name': os.path.basename(p),
                                  'pages': npg, 'ocr_pages': min(npg, maxpages),
                                  'chars': len(t.strip()), 'err': err,
                                  'text': t[:400000]}) + "\n")
            print(f"{i+1}/{len(pdfs)} {os.path.basename(p)[:52]} pages={npg} chars={len(t.strip())} {err}", flush=True)


if __name__ == '__main__':
    main()
