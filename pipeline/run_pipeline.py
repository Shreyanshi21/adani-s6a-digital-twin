"""Run the whole Khavda S6a digital-twin pipeline: PDF + P6 schedule -> IFC (4D) -> web viewer.

usage:
  python pipeline/run_pipeline.py                      # everything, reusing cached steps
  python pipeline/run_pipeline.py --from link          # re-run from a step (pdf, extract, ifc, link, scene, dist, web)
  python pipeline/run_pipeline.py --xer "data/schedule/FY26-P18 S6a 01.10.2026.xer"

Outputs (all git-ignored):
  build/   intermediate files (PDF cache, features.json, base IFC, link report, scene.bin)
  dist/    ready-to-serve viewer: index.html, IFC, .ifczip, scene.bin, scene-data.js, model-data.js, web-ifc.wasm
  dist/web/khavda-s6a-4d.html   single-file web edition (the page published on claude.ai)
"""
import argparse, base64, glob, os, re, shutil, subprocess, sys, time, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, 'pipeline')
BUILD = os.path.join(ROOT, 'build')
DIST = os.path.join(ROOT, 'dist')
STEPS = ['pdf', 'extract', 'ifc', 'link', 'scene', 'dist', 'web']
MODEL = 'Khavda_Hybrid_Park_S6a-234MW'


def latest_xer():
    """Newest schedule: by the dd.mm.yyyy date in the file name (e.g. 'FY26-P18 S6a 01.10.2026.xer'), else file time."""
    files = glob.glob(os.path.join(ROOT, 'data', 'schedule', '*.xer'))
    if not files: sys.exit('No .xer found in data/schedule')
    def key(p):
        m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', os.path.basename(p))
        return (m.group(3), m.group(2), m.group(1)) if m else ('0000', '00', '00') + (str(os.path.getmtime(p)),)
    return max(files, key=key)


def run(script, *args):
    t = time.time()
    print(f'\n>>> {script} ' + ' '.join(f'"{a}"' for a in args), flush=True)
    subprocess.run([sys.executable, os.path.join(PIPE, script), *args], check=True)
    print(f'    done in {time.time() - t:.0f} s', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='start', choices=STEPS, default=None, help='force re-run from this step')
    ap.add_argument('--pdf', default=glob.glob(os.path.join(ROOT, 'data', 'drawings', '*.pdf'))[0] if glob.glob(os.path.join(ROOT, 'data', 'drawings', '*.pdf')) else None)
    ap.add_argument('--xer', default=None, help='P6 schedule (default: newest file in data/schedule)')
    a = ap.parse_args()
    xer = a.xer or latest_xer()
    os.makedirs(BUILD, exist_ok=True)
    force = set(STEPS[STEPS.index(a.start):]) if a.start else set()
    out = lambda *p: os.path.join(BUILD, *p)
    need = lambda step, path: step in force or not os.path.exists(path)

    print(f'PDF : {a.pdf}\nXER : {xer}')
    if need('pdf', out('p3.pkl')): run('cache_pdf.py', a.pdf, BUILD)
    if need('extract', out('features.json')): run('extract.py', BUILD)
    if need('ifc', out(f'{MODEL}_base.ifc')): run('build_ifc.py', out('features.json'), out(f'{MODEL}_base.ifc'))
    if need('link', out(f'{MODEL}.ifc')): run('link_schedule.py', out(f'{MODEL}_base.ifc'), xer, out(f'{MODEL}.ifc'), out('link_report.json'))
    if need('scene', out('scene.bin')): run('export_scene.py', out(f'{MODEL}.ifc'), out('scene.bin'))

    if 'dist' in force or not os.path.exists(os.path.join(DIST, 'index.html')) or a.start is None:
        print('\n>>> assembling dist/')
        os.makedirs(DIST, exist_ok=True)
        for f in ('index.html', 'web-ifc.wasm'): shutil.copy2(os.path.join(ROOT, 'viewer', f), DIST)
        shutil.copy2(out(f'{MODEL}.ifc'), DIST)
        shutil.copy2(out('scene.bin'), DIST)
        with zipfile.ZipFile(os.path.join(DIST, f'{MODEL}.ifczip'), 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.write(out(f'{MODEL}.ifc'), f'{MODEL}.ifc')
        # script versions of the data so index.html also works when opened straight from disk (file://)
        b = base64.b64encode(open(out('scene.bin'), 'rb').read()).decode()
        open(os.path.join(DIST, 'scene-data.js'), 'w').write(f'window.SCENE_NAME="Khavda Hybrid Park – S6a-234MW";\nwindow.SCENE_B64="{b}";\n')
        b = base64.b64encode(open(os.path.join(DIST, f'{MODEL}.ifczip'), 'rb').read()).decode()
        open(os.path.join(DIST, 'model-data.js'), 'w').write(f'window.IFC_MODEL_NAME="{MODEL}.ifczip";\nwindow.IFC_MODEL_B64="{b}";\n')
        print('    dist/ ready')

    if 'web' in force or not os.path.exists(os.path.join(DIST, 'web', 'khavda-s6a-4d.html')) or a.start is None:
        os.makedirs(os.path.join(DIST, 'web'), exist_ok=True)
        run('build_web.py', os.path.join(ROOT, 'viewer', 'index.html'), out('scene.bin'), os.path.join(DIST, 'web', 'khavda-s6a-4d.html'))
    print('\nAll done. Serve the viewer with:  python -m http.server 8765 --directory dist')


if __name__ == '__main__':
    main()
