"""Tessellate an IFC with IfcOpenShell and render oblique views with a tiny numpy/PIL rasteriser.
usage: render_ifc.py model.ifc out_prefix
"""
import sys, math, time, pickle, os
import numpy as np
import ifcopenshell, ifcopenshell.geom
from PIL import Image, ImageDraw

path, outp = sys.argv[1], sys.argv[2]
cache = outp + '_tess.pkl'
t0 = time.time()
if os.path.exists(cache):
    meshes = pickle.load(open(cache, 'rb'))
else:
    f = ifcopenshell.open(path)
    st = ifcopenshell.geom.settings()
    st.set('use-world-coords', False)
    it = ifcopenshell.geom.iterator(st, f, 8)
    geo = {}
    inst = []
    if it.initialize():
        while True:
            sh = it.get()
            g = sh.geometry
            if g.id not in geo:
                v = np.array(g.verts, dtype=np.float32).reshape(-1, 3)
                fa = np.array(g.faces, dtype=np.int32).reshape(-1, 3)
                mids = np.array(g.material_ids, dtype=np.int32)
                cols = []
                for m in g.materials:
                    d = m.diffuse
                    cols.append((d.r(), d.g(), d.b()) if hasattr(d, 'r') else tuple(d))
                cols = np.array(cols if cols else [(0.7, 0.7, 0.7)], dtype=np.float32)
                fc = cols[np.clip(mids, 0, len(cols)-1)] if len(mids) == len(fa) else np.tile(cols[0], (len(fa), 1))
                geo[g.id] = (v, fa, fc)
            m = np.array(sh.transformation.matrix, dtype=np.float64).reshape(4, 4).T if len(sh.transformation.matrix) == 16 else None
            if m is None:
                mm = np.array(sh.transformation.matrix).reshape(4, 3)
                m = np.eye(4); m[:3, :3] = mm[:3].T; m[:3, 3] = mm[3]
            inst.append((g.id, m, sh.type))
            if not it.next():
                break
    meshes = (geo, inst)
    pickle.dump(meshes, open(cache, 'wb'))
geo, inst = meshes
print('tessellated', len(inst), 'instances', len(geo), 'unique geoms', round(time.time()-t0, 1))


def render(name, eye, target, fov, W=1800, H=1100, bbox=None, skip=()):
    eye = np.array(eye, float); target = np.array(target, float)
    fwd = target - eye; fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 0, 1]); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    fpx = (W/2) / math.tan(math.radians(fov)/2)
    light = np.array([0.4, -0.5, 0.75]); light /= np.linalg.norm(light)
    polys = []
    for gid, m, typ in inst:
        if typ in skip:
            continue
        v, fa, fc = geo[gid]
        wv = v @ m[:3, :3].T + m[:3, 3]
        if bbox is not None:
            mn, mx = wv.min(0), wv.max(0)
            if mx[0] < bbox[0] or mn[0] > bbox[2] or mx[1] < bbox[1] or mn[1] > bbox[3]:
                continue
        rel = wv - eye
        z = rel @ fwd
        if (z <= 1).all():
            continue
        x = rel @ right; y = rel @ up
        zc = np.maximum(z, 1e-3)
        sx = W/2 + fpx * x / zc; sy = H/2 - fpx * y / zc
        tri = fa
        p0, p1, p2 = wv[tri[:, 0]], wv[tri[:, 1]], wv[tri[:, 2]]
        n = np.cross(p1-p0, p2-p0); nl = np.linalg.norm(n, axis=1) + 1e-12; n /= nl[:, None]
        ok = (z[tri] > 1).all(1)
        if wv[:, 2].max() < -0.01:
            continue
        X = sx[tri]; Y = sy[tri]
        ok &= ~((X < 0).all(1) | (X > W).all(1) | (Y < 0).all(1) | (Y > H).all(1))
        area = np.abs((X[:, 1]-X[:, 0])*(Y[:, 2]-Y[:, 0]) - (X[:, 2]-X[:, 0])*(Y[:, 1]-Y[:, 0]))
        ok &= area > 0.02
        if not ok.any():
            continue
        shade = 0.55 + 0.45*np.abs(n @ light)
        col = np.clip(fc * shade[:, None] * 255, 0, 255)
        dep = z[tri].mean(1)
        flat = (wv[:, 2].max() < 0.3)
        for k in np.nonzero(ok)[0]:
            polys.append((dep[k] + (1e9 if flat else 0), [(X[k, 0], Y[k, 0]), (X[k, 1], Y[k, 1]), (X[k, 2], Y[k, 2])], tuple(int(c) for c in col[k])))
    polys.sort(key=lambda p: -p[0])
    im = Image.new('RGB', (W, H), (214, 200, 165))
    d = ImageDraw.Draw(im)
    hz = eye + np.array([fwd[0], fwd[1], 0]) / (np.linalg.norm(fwd[:2]) + 1e-9) * 1e7; hz[2] = 0
    r_ = hz - eye; yh = H/2 - fpx * (r_ @ up) / (r_ @ fwd)
    d.rectangle([0, 0, W, max(0, yh)], fill=(170, 200, 230))
    for _, pts, c in polys:
        d.polygon(pts, fill=c, outline=c)
    im.save(f'{outp}_{name}.png')
    print(name, len(polys), 'tris', round(time.time()-t0, 1))


views = sys.argv[3].split(',') if len(sys.argv) > 3 else ['park', 's6a', 'close']
if 'park' in views:
    render('park', (-4000, -26000, 14000), (-4000, 4000, 0), 50, skip=('IfcPile', 'IfcMember'))
if 's6a' in views:
    render('s6a', (800, -1800, 1300), (1300, 450, 0), 55, bbox=(-3000, -1500, 6000, 4000))
if 'close' in views:
    render('close', (-560, -60, 70), (-330, 230, 0), 60, bbox=(-1200, -400, 400, 900))
if 'table' in views:
    render('table', (-640, 2, 9), (-600, 40, 1), 60, bbox=(-800, -150, -400, 200))
if 'pss' in views:
    render('pss', (2700, 1700, 260), (3170, 2250, 0), 60, bbox=(2200, 1200, 4200, 3000))
