#!/usr/bin/env python3
"""make_fixtures.py - generate the made-up PDFs that tests/run_checks.sh uses.

  usage: python3 make_fixtures.py <output-dir>

Every value in these files is invented. Nothing is read from the machine.
Needs: Pillow (the Python that runs ocrmypdf has it).

  text.pdf            a letter with a real text layer (no OCR needed)
  short_text.pdf      one short line of real text, no image
  scan_text.pdf       an image-only page that carries a made-up statement
  scan_text_b.pdf     the same, with a different first line
  scan_blank.pdf      an image-only page with one character on it
  long_scan_210.pdf   210 image-only pages with nothing on them
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

BODY = ['MADE-UP SAMPLE STATEMENT', 'Example Card Company', 'Page 1 of 1', 'Account ending in 4321',
        'Statement Closing Date 01/15/2030', 'New Balance 1,234.56', 'Minimum Payment Due 35.00',
        'This page is a test fixture. Every value on it is invented.',
        'The quick brown fox jumps over the lazy dog near the river bank.',
        'A second line of filler text so that the page holds well over',
        'two hundred characters once it has been read by the OCR engine.']


def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/System/Library/Fonts/Helvetica.ttc',
                 '/Library/Fonts/Arial.ttf'):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default(size=size)      # Pillow 10.1 or later


def scan(path, lines):
    im = Image.new('RGB', (1700, 2200), 'white')
    d = ImageDraw.Draw(im)
    y = 150
    for line in lines:
        d.text((150, y), line, fill='black', font=font(44))
        y += 80
    im.save(path, 'PDF', resolution=200.0)


def text_pdf(path, lines):
    """A one-page PDF with a real text layer, written by hand: five objects and a cross-reference table."""
    ops = ['BT /F1 11 Tf 72 720 Td 16 TL']
    for line in lines:
        ops.append('(%s) Tj T*' % line.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)'))
    ops.append('ET')
    stream = '\n'.join(ops).encode('latin-1')
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
            b'/Resources << /Font << /F1 5 0 R >> >> >>',
            b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out = b'%PDF-1.4\n'
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % n + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n' % (len(objs) + 1) + b'%010d %05d f \n' % (0, 65535)
    for off in offsets:
        out += b'%010d 00000 n \n' % off
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)
    with open(path, 'wb') as fh:
        fh.write(out)


def main(out):
    os.makedirs(out, exist_ok=True)
    scan(os.path.join(out, 'scan_text.pdf'), BODY)
    scan(os.path.join(out, 'scan_text_b.pdf'), ['SECOND MADE-UP PAGE, VARIANT B'] + BODY[1:])
    scan(os.path.join(out, 'scan_blank.pdf'), ['7'])

    pages = [Image.new('L', (425, 550), 255) for _ in range(210)]
    pages[0].save(os.path.join(out, 'long_scan_210.pdf'), 'PDF', resolution=50.0, save_all=True,
                  append_images=pages[1:])

    text_pdf(os.path.join(out, 'text.pdf'),
             ['Line %d: this made-up letter has a real text layer and needs no OCR at all.' % i for i in range(12)])
    text_pdf(os.path.join(out, 'short_text.pdf'), ['Cover page.'])
    print('6 fixtures written to', out)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
