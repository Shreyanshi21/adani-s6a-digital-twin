"""Read the vector drawings + text of the layout PDF once and cache them (slow step, ~2 min).

usage: cache_pdf.py layout.pdf build_dir
Writes build_dir/p1.pkl (sheet 1, whole Khavda park) and build_dir/p3.pkl (sheet 3, S6a array detail).
Each pickle is (page.get_drawings(), page.get_text('words')) in un-rotated PDF coordinates.
"""
import sys, os, pickle, time
import pymupdf

PDF, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
doc = pymupdf.open(PDF)
for page_no, name in ((0, 'p1.pkl'), (2, 'p3.pkl')):
    t = time.time()
    page = doc[page_no]
    drawings = page.get_drawings()
    words = page.get_text('words')
    with open(os.path.join(OUT, name), 'wb') as fh:
        pickle.dump((drawings, words), fh)
    print(f'sheet {page_no + 1}: {len(drawings):,} drawings, {len(words):,} words -> {name} ({time.time() - t:.0f} s)')
