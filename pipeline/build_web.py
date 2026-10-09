"""Build the single-file web edition (claude.ai page) from the master viewer + scene package.
usage: build_web.py master_index.html scene.bin out.html"""
import sys, base64
src, scene, dst = sys.argv[1:4]
s = open(src, encoding='utf-8').read()
for a in ['<!doctype html>\n', '<html lang="en">\n', '<head>\n', '<meta charset="utf-8">\n',
          '<meta name="viewport" content="width=device-width, initial-scale=1">\n', '</head>\n', '<body>\n', '</body>\n', '</html>\n']:
    assert a in s, a
    s = s.replace(a, '', 1)
s = s.replace('<title>IFC Viewer – Khavda S6a</title>', '<title>Khavda S6a 4D Model</title>')
old_root = """  :root {
    --bg: #f4f5f7; --panel: #ffffff; --line: #e1e4e8; --text: #1f2328; --muted: #6a737d;
    --accent: #0b6bcb; --accent-soft: #e6f0fb; --top: #14213d; --top-text: #ffffff; --sel: #ff8a00;
  }"""
assert old_root in s
s = s.replace(old_root, """  /* Full-bleed 3D workspace in one light look: navy toolbar, white panels, colour reserved for VisiLean status */
  :root {
    color-scheme: light;
    --bg: #f4f5f7; --panel: #ffffff; --line: #e1e4e8; --text: #1f2328; --muted: #6a737d;
    --accent: #0b6bcb; --accent-soft: #e6f0fb; --top: #14213d; --top-text: #ffffff; --sel: #ff8a00;
  }""")
b64 = base64.b64encode(open(scene, 'rb').read()).decode()
# the data block goes last: a multi-MB script near the top of the file stops the page from showing on claude.ai
s = s.rstrip('\n') + '\n<!-- prepared 3D package (deflate, base64), read by the viewer module after parsing -->\n' + \
    '<script>window.SCENE_NAME="Khavda Hybrid Park – S6a-234MW";window.SCENE_B64="' + b64 + '";</script>\n'
open(dst, 'w', encoding='utf-8').write(s)
print(round(len(s) / 1e6, 2), 'MB')
