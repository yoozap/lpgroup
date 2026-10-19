#!/usr/bin/env python3
"""Subset and re-encode web/fonts/ as WOFF2.

The three faces shipped as TTF/OTF - 375 KB that `serve.py` did not even
compress, because `.ttf` was not in its gzip list - and every byte of them
is on the critical path: the page blocks its first paint on `font-display:
swap` only in the sense that it repaints when they land, and a Georgian
headline reflowing a second in is exactly what a visitor reads as "slow".

Two things are done here, in this order:

* **Subset to what `site.css` declares.** `unicode-range` tells the browser
  when to USE a face; it does not make the file smaller. Noto Sans Georgian
  carried 283 Latin glyphs that the declaration can never reach - the Latin
  inside a Georgian line is picked per character and stays in Jost - so they
  were pure weight. Jost keeps Latin and the symbols the page sets (m2, the
  arrows, the quotes); everything past that goes.
* **Pin the axes nothing varies.** Noto ships `wght` and `wdth`; the CSS
  asks for `font-weight: 100 900` and never touches `font-stretch`, so
  `wdth` is instanced out at 100 and only the weight axis survives.

Then WOFF2, which is Brotli with a font-aware preprocessor - better than
anything a server will do to a TTF on the fly, and it arrives compressed
whatever the host is configured like.

    python3 tools/slim_fonts.py            # writes web/fonts/*.woff2

The originals are kept: they are the source these are cut from, and the
licences beside them require the files be redistributable.

The ranges are wider than the page's own copy on purpose - Latin Extended
and the combining marks go in whole rather than character by character, so
adding a word of copy cannot silently fall off the font. Two glyphs the
page DOES set are missing from these faces and always were, before any
subsetting: the back arrow U+2190 and the close cross U+2715 are not in
Jost at all and come from a system font either way.
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, '..', 'web', 'fonts')

# The ranges `web/site.css` declares for each face, plus - for Jost, which
# has no `unicode-range` and sets the whole page - Latin and the symbols
# the copy actually uses.
LATIN = 'U+0020-007E,U+00A0-00FF,U+0100-024F,U+02BB-02BC,U+02C6,' \
        'U+02DA,U+02DC,U+0300-036F,U+2000-206F,U+2070-209F,' \
        'U+20A0-20BF,U+2122,U+2190-2193,U+2212,U+2215,U+2260,U+2264-2265,' \
        'U+25A0-25CF,U+FEFF,U+FFFD'
GEORGIAN = 'U+10A0-10FF,U+1C90-1CBF,U+2D00-2D2F'

JOBS = [
    # file,                     unicode ranges,        axes to pin
    ('Jost.ttf',                LATIN,                 []),
    ('NotoSansGeorgian.ttf',    GEORGIAN,              ['wdth=100']),
    ('BPGNinoMtavruli.otf',     'U+10D0-10FF,' + LATIN, []),
]


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        sys.exit('failed: %s\n%s%s' % (' '.join(args), r.stdout, r.stderr))


def main():
    try:
        import fontTools, brotli           # noqa: F401
    except ImportError:
        sys.exit('needs fonttools and brotli: pip3 install fonttools brotli')
    total_before = total_after = 0
    for name, ranges, pins in JOBS:
        src = os.path.join(FONTS, name)
        if not os.path.exists(src):
            print('  %-24s missing, skipped' % name)
            continue
        stem = os.path.splitext(name)[0]
        out = os.path.join(FONTS, stem + '.woff2')
        work = src
        if pins:
            work = os.path.join(FONTS, stem + '.__pinned.ttf')
            run([sys.executable, '-m', 'fontTools.varLib.instancer',
                 src, *pins, '-o', work])
        run([sys.executable, '-m', 'fontTools.subset', work,
             '--unicodes=' + ranges,
             '--layout-features=*', '--flavor=woff2',
             '--no-hinting', '--desubroutinize',
             '--drop-tables+=DSIG', '--name-IDs=*',
             '--output-file=' + out])
        if work != src:
            os.remove(work)
        a, b = os.path.getsize(src), os.path.getsize(out)
        total_before += a
        total_after += b
        print('  %-24s %7d -> %7d  (%d%%)' % (name, a, b, round(100 * b / a)))
    print('  %-24s %7d -> %7d  (%d%%)' % ('total', total_before, total_after,
          round(100 * total_after / max(1, total_before))))


if __name__ == '__main__':
    main()
