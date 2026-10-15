"""Pre-tessellate the linked IFC into a compact web scene package (no IFC engine needed in the browser).

usage: export_scene.py model.ifc out_scene.bin
Package = zlib( u32 headerLen | header JSON (utf-8) | binary buffers ), buffers described in header['buffers'].
Coordinates are converted to three.js Y-up: (x, y, z)_ifc -> (x, z, -y).
"""
import sys, json, zlib, struct, time, collections
import numpy as np
import ifcopenshell, ifcopenshell.geom

IFC, OUT = sys.argv[1], sys.argv[2]
t0 = time.time()
f = ifcopenshell.open(IFC)
C = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=np.float64)

buffers = []          # (name, np.array)
blob = bytearray()
def add(name, arr):
    global blob
    arr = np.ascontiguousarray(arr)
    while len(blob) % 4: blob.append(0)
    off = len(blob); blob += arr.tobytes()
    buffers.append({'name': name, 'dtype': arr.dtype.str, 'offset': off, 'count': int(arr.size)})
    return len(buffers) - 1

# ------------------------------------------------------------------ procedural elements (indicative PV rows, conductors)
strip_elems, line_elems = {}, {}
for p in f.by_type('IfcSolarDevice'):
    if (p.Name or '').startswith('Solar Plot P'):
        rows = []
        for rep in p.Representation.Representations:
            for it in rep.Items:
                if it.is_a('IfcExtrudedAreaSolid') and it.SweptArea.is_a('IfcRectangleProfileDef'):
                    x, y, z = it.Position.Location.Coordinates
                    rows.append((x, y, z, it.SweptArea.XDim, it.SweptArea.YDim, it.Depth))
        strip_elems[p.id()] = rows
for p in f.by_type('IfcCableSegment'):
    segs = []
    for rep in p.Representation.Representations:
        for it in rep.Items:
            if it.is_a('IfcExtrudedAreaSolid'):
                a = np.array(it.Position.Location.Coordinates, dtype=float)
                d = np.array(it.Position.Axis.DirectionRatios if it.Position.Axis else (0, 0, 1), dtype=float)
                b = a + d / np.linalg.norm(d) * it.Depth
                segs.append((*a, *b))
    line_elems[p.id()] = segs
proc = set(strip_elems) | set(line_elems)

# ------------------------------------------------------------------ tessellation (shared geometry per representation)
st = ifcopenshell.geom.settings()
st.set('use-world-coords', False)
for k, val in (('mesher-angular-deflection', 0.55), ('mesher-linear-deflection', 0.05)):   # ~12 segments per circle, like web-ifc
    try: st.set(k, val)
    except Exception as ex: print('setting', k, ex)
it = ifcopenshell.geom.iterator(st, f, 8)
geo_index, geos = {}, []
inst_pid, inst_gid, inst_mat = [], [], []
if it.initialize():
    while True:
        sh = it.get()
        pid = sh.id
        if pid not in proc:
            g = sh.geometry
            if g.id not in geo_index:
                v = np.array(g.verts, dtype=np.float64).reshape(-1, 3)
                fa = np.array(g.faces, dtype=np.uint32).reshape(-1, 3)
                nrm = np.array(g.normals, dtype=np.float64).reshape(-1, 3) if len(g.normals) == len(g.verts) else np.zeros_like(v)
                mids = np.array(g.material_ids, dtype=np.int64)
                mats = []
                alpha = 1.0
                for m in g.materials:
                    d = m.diffuse
                    rgb = (d.r(), d.g(), d.b()) if hasattr(d, 'r') else tuple(d)[:3]
                    mats.append(rgb)
                    tr = getattr(m, 'transparency', 0.0) or 0.0
                    if tr == tr and tr > 0.01: alpha = min(alpha, 1 - tr)
                if not mats: mats = [(0.7, 0.7, 0.7)]
                col = np.zeros((len(v), 3), dtype=np.float64) + 0.7
                if len(mids) == len(fa):
                    for k in range(3): col[fa[:, k]] = np.array(mats)[np.clip(mids, 0, len(mats) - 1)]
                else:
                    col[:] = mats[0]
                # flat shading: split vertices per face direction and give each its face normal
                if len(fa):
                    p0, p1, p2 = v[fa[:, 0]], v[fa[:, 1]], v[fa[:, 2]]
                    fn = np.cross(p1 - p0, p2 - p0)
                    fl = np.linalg.norm(fn, axis=1, keepdims=True); fl[fl == 0] = 1; fn = fn / fl
                    tri_v = fa.reshape(-1)
                    tri_n = np.repeat(fn, 3, axis=0)
                    key = np.concatenate([tri_v[:, None].astype(np.float64), np.round(tri_n * 100)], axis=1)
                    uniq, inv = np.unique(key, axis=0, return_inverse=True)
                    first = np.zeros(len(uniq), dtype=np.int64); first[inv.reshape(-1)] = np.arange(len(inv))
                    vi = tri_v[first]
                    v, col, nrm = v[vi], col[vi], tri_n[first]
                    fa = inv.reshape(-1, 3).astype(np.uint32)
                geo_index[g.id] = len(geos)
                geos.append({'v': v, 'f': fa, 'n': nrm, 'c': col, 'a': alpha})
            m = np.array(sh.transformation.matrix, dtype=np.float64)
            if m.size == 16: M = m.reshape(4, 4).T
            else:
                mm = m.reshape(4, 3); M = np.eye(4); M[:3, :3] = mm[:3].T; M[:3, 3] = mm[3]
            inst_pid.append(pid); inst_gid.append(geo_index[g.id]); inst_mat.append((C @ M)[:3, :].reshape(-1))
        if not it.next(): break
tri_by_pid = collections.Counter()
for k in range(len(inst_pid)): tri_by_pid[inst_gid[k]] += len(geos[inst_gid[k]]['f'])
top = tri_by_pid.most_common(6)
print('heaviest geometries (tris x instances):', [(g, n, len(geos[g]['f'])) for g, n in top])
print('tessellated', len(inst_pid), 'instances', len(geos), 'geometries', round(time.time() - t0, 1), 's')

geo_meta = []
for g in geos:
    v, fa = g['v'], g['f']
    nv = len(v)
    lo, hi = v.min(0), v.max(0)
    ext = np.maximum(hi - lo, 1e-6)
    q = np.round((v - lo) / ext * 65535).astype(np.uint16)          # 16-bit quantised positions
    n8 = np.clip(np.round(g['n'] * 127), -127, 127).astype(np.int8)
    c8 = np.clip(np.round(g['c'] * 255), 0, 255).astype(np.uint8)
    idx = fa.astype(np.uint16 if nv < 65536 else np.uint32).reshape(-1)
    geo_meta.append({'p': add('p', q.reshape(-1)), 'n': add('n', n8.reshape(-1)), 'c': add('c', c8.reshape(-1)), 'i': add('i', idx),
                     'lo': lo.round(5).tolist(), 'ext': ext.round(5).tolist(), 'a': round(g['a'], 3)})
inst = {'pid': add('ipid', np.array(inst_pid, dtype=np.uint32)), 'gid': add('igid', np.array(inst_gid, dtype=np.uint32)),
        'm': add('imat', np.array(inst_mat, dtype=np.float32).reshape(-1))}

# procedural rows / lines (IFC coordinates, z up)
strips = {'pid': [], 'start': [], 'count': []}
srows = []
for pid, rows in strip_elems.items():
    strips['pid'].append(pid); strips['start'].append(len(srows)); strips['count'].append(len(rows)); srows += rows
strips['rows'] = add('srows', np.array(srows, dtype=np.float32).reshape(-1)) if srows else None
lines = {'pid': [], 'start': [], 'count': []}
lsegs = []
for pid, segs in line_elems.items():
    lines['pid'].append(pid); lines['start'].append(len(lsegs)); lines['count'].append(len(segs)); lsegs += segs
lines['segs'] = add('lsegs', np.array(lsegs, dtype=np.float32).reshape(-1)) if lsegs else None
strip_color = None
for p in f.by_type('IfcSolarDevice'):
    if p.id() in strip_elems:
        for si in f.get_inverse(p.Representation.Representations[0].Items[0]):
            if si.is_a('IfcStyledItem'):
                for s in si.Styles:
                    for r in s.Styles:
                        if r.is_a('IfcSurfaceStyleRendering'):
                            cc = r.SurfaceColour; strip_color = [cc.Red, cc.Green, cc.Blue]
        break

# ------------------------------------------------------------------ metadata
def v(x):
    if x is None: return None
    w = getattr(x, 'wrappedValue', x)
    if isinstance(w, (int, float, str, bool)): return w
    return str(w)

products = {}
geom_pids = set(inst_pid) | proc
for p in f.by_type('IfcProduct'):
    if p.id() in geom_pids:
        products[p.id()] = p
contained = {}
spatial = {}
def node(e):
    if e.id() not in spatial:
        spatial[e.id()] = {'id': e.id(), 'cls': e.is_a(), 'name': e.Name or getattr(e, 'LongName', None) or '', 'parent': None, 'kids': [], 'elems': []}
    return spatial[e.id()]
for r in f.by_type('IfcRelAggregates'):
    if r.RelatingObject.is_a('IfcSpatialStructureElement') or r.RelatingObject.is_a('IfcProject'):
        pn = node(r.RelatingObject)
        for o in r.RelatedObjects:
            if o.is_a('IfcSpatialStructureElement'):
                k = node(o); k['parent'] = pn['id']; pn['kids'].append(k['id'])
for r in f.by_type('IfcRelContainedInSpatialStructure'):
    pn = node(r.RelatingStructure)
    for o in r.RelatedElements:
        if o.id() in products:
            pn['elems'].append(o.id()); contained[o.id()] = pn['id']
proj = f.by_type('IfcProject')[0]; node(proj)

psets, pset_index = [], {}
def pset_id(ps):
    if ps.id() in pset_index: return pset_index[ps.id()]
    props = []
    for pr in getattr(ps, 'HasProperties', None) or getattr(ps, 'Quantities', None) or []:
        val = getattr(pr, 'NominalValue', None)
        props.append([pr.Name, v(val)])
    pset_index[ps.id()] = len(psets); psets.append({'name': ps.Name, 'props': props})
    return pset_index[ps.id()]
elem_ps = collections.defaultdict(list)
for r in f.by_type('IfcRelDefinesByProperties'):
    d = r.RelatingPropertyDefinition
    if not d.is_a('IfcPropertySet'): continue
    for o in r.RelatedObjects:
        if o.id() in products: elem_ps[o.id()].append(pset_id(d))
types, type_index, elem_type = [], {}, {}
for r in f.by_type('IfcRelDefinesByType'):
    t = r.RelatingType
    if t.id() not in type_index:
        type_index[t.id()] = len(types)
        types.append({'name': t.Name, 'cls': t.is_a(), 'ps': [pset_id(p) for p in (t.HasPropertySets or []) if p.is_a('IfcPropertySet')]})
    for o in r.RelatedObjects:
        if o.id() in products: elem_type[o.id()] = type_index[t.id()]

elements = []
for pid, p in products.items():
    elements.append([pid, p.GlobalId, p.is_a(), p.Name or '', getattr(p, 'Tag', None) or '', getattr(p, 'ObjectType', None) or '',
                     str(getattr(p, 'PredefinedType', '') or ''), p.Description or '', contained.get(pid), elem_type.get(pid), elem_ps.get(pid, [])])

# georef
E0 = N0 = 0.0; crs = ''
mc = f.by_type('IfcMapConversion')
if mc: E0, N0 = mc[0].Eastings, mc[0].Northings; crs = mc[0].TargetCRS.Name

# schedule
tasks = []
ws = f.by_type('IfcWorkSchedule')
task_idx = {}
def vl_pset(t):
    for r in t.IsDefinedBy or []:
        if r.is_a('IfcRelDefinesByProperties') and r.RelatingPropertyDefinition.Name == 'VL_Activity':
            return {p.Name: p.NominalValue.wrappedValue for p in r.RelatingPropertyDefinition.HasProperties if p.NominalValue}
    return {}


for t in f.by_type('IfcTask'):
    if (t.ObjectType or '') != 'VisiLean Activity': continue
    tt = t.TaskTime
    vp = vl_pset(t)
    task_idx[t.id()] = len(tasks)
    tasks.append({'id': t.id(), 'code': t.Identification or '', 'name': t.Name or '', 'loc': t.Description or '', 'status': t.Status or '',
                  'ps': tt.ScheduleStart if tt else None, 'pf': tt.ScheduleFinish if tt else None,
                  'as': tt.ActualStart if tt else None, 'af': tt.ActualFinish if tt else None,
                  'es': tt.EarlyStart if tt else None, 'ef': tt.EarlyFinish if tt else None,
                  'bs': vp.get('BaselineStart'), 'bf': vp.get('BaselineFinish'),
                  'pct': round((tt.Completion or 0) * 100) if tt else 0, 'dd': tt.StatusTime if tt else None,
                  'mile': bool(t.IsMilestone), 'elems': []})
for r in f.by_type('IfcRelAssignsToProcess'):
    k = task_idx.get(r.RelatingProcess.id())
    if k is None: continue
    tasks[k]['elems'] += [o.id() for o in r.RelatedObjects if o.id() in products]

header = {'version': 1, 'name': proj.Name, 'georef': {'E0': E0, 'N0': N0, 'crs': crs},
          'geos': geo_meta, 'inst': inst, 'strips': strips, 'stripColor': strip_color, 'lines': lines,
          'elements': elements, 'spatial': list(spatial.values()), 'root': proj.id(), 'psets': psets, 'types': types,
          'schedule': {'name': ws[0].Name if ws else '', 'tasks': tasks}, 'buffers': buffers}
hj = json.dumps(header, separators=(',', ':')).encode('utf-8')
hj += b' ' * ((-(4 + len(hj))) % 4)          # keep the binary section 4-byte aligned
raw = struct.pack('<I', len(hj)) + hj + bytes(blob)
comp = zlib.compress(raw, 9)
open(OUT, 'wb').write(comp)
print('header', round(len(hj) / 1e6, 2), 'MB · binary', round(len(blob) / 1e6, 2), 'MB · compressed', round(len(comp) / 1e6, 2), 'MB',
      '· elements', len(elements), '· tasks', len(tasks), '· strips', len(srows), '· line segs', len(lsegs), round(time.time() - t0, 1), 's')
