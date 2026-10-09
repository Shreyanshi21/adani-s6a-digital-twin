"""Extract georeferenced features from the Khavda / S6a layout PDF (pages 1 and 3).

Output: features.json with all coordinates in local metres (x = Easting - E0, y = Northing - N0).
"""
import json, pickle, sys, math, collections, re
import numpy as np
from shapely.geometry import Polygon, LineString, MultiPolygon, Point, box
from shapely.ops import unary_union

SCR = sys.argv[1]
E0, N0 = 545000.0, 2662000.0


def fit(pairs):
    A = np.array([[p[0], p[1], 1] for p in pairs])
    cE = np.linalg.lstsq(A, np.array([p[2] for p in pairs]), rcond=None)[0]
    cN = np.linalg.lstsq(A, np.array([p[3] for p in pairs]), rcond=None)[0]
    res = max(np.abs(A @ cE - [p[2] for p in pairs]).max(), np.abs(A @ cN - [p[3] for p in pairs]).max())
    return cE, cN, res


def mk_tf(cE, cN):
    def T(p):
        return (cE[0]*p[0] + cE[1]*p[1] + cE[2] - E0, cN[0]*p[0] + cN[1]*p[1] + cN[2] - N0)
    return T


def item_pts(items):
    pts = []
    for it in items:
        if it[0] == 'l':
            a, b = it[1], it[2]
            if not pts or (abs(pts[-1][0]-a.x) > 1e-6 or abs(pts[-1][1]-a.y) > 1e-6):
                pts.append((a.x, a.y))
            pts.append((b.x, b.y))
        elif it[0] == 'c':
            a, b = it[1], it[4]
            if not pts or (abs(pts[-1][0]-a.x) > 1e-6 or abs(pts[-1][1]-a.y) > 1e-6):
                pts.append((a.x, a.y))
            pts.append((b.x, b.y))
        elif it[0] == 'qu':
            q = it[1]
            pts += [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
        elif it[0] == 're':
            r = it[1]
            pts += [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
    return pts


def segs(items):
    out = []
    for it in items:
        if it[0] == 'l':
            out.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
        elif it[0] == 'c':
            out.append(((it[1].x, it[1].y), (it[4].x, it[4].y)))
        elif it[0] in ('qu', 're'):
            p = item_pts([it]); out += [(p[i], p[(i+1) % 4]) for i in range(4)]
    return out


def poly_out(g, T, simp=0.0, minarea=0.0):
    """shapely (page coords) -> list of {'ext': [...], 'holes': [[...]]} in local metres."""
    res = []
    geoms = [g] if isinstance(g, Polygon) else list(getattr(g, 'geoms', []))
    for p in geoms:
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        ext = [T(c) for c in p.exterior.coords]
        P = Polygon(ext, [[T(c) for c in r.coords] for r in p.interiors])
        if simp:
            P = P.simplify(simp, preserve_topology=True)
        if P.is_empty or P.area < minarea:
            continue
        if isinstance(P, MultiPolygon):
            subs = list(P.geoms)
        else:
            subs = [P]
        for q in subs:
            res.append({'ext': [list(map(lambda v: round(v, 3), c)) for c in q.exterior.coords[:-1]],
                        'holes': [[list(map(lambda v: round(v, 3), c)) for c in r.coords[:-1]] for r in q.interiors
                                  if Polygon(r).area > 50]})
    return res


def grid_cluster(points, cell):
    """Simple connected clustering on a grid (points within ~cell)."""
    cells = collections.defaultdict(list)
    for i, p in enumerate(points):
        cells[(int(p[0]//cell), int(p[1]//cell))].append(i)
    seen, clusters = set(), []
    for c in cells:
        if c in seen:
            continue
        stack, members = [c], []
        seen.add(c)
        while stack:
            k = stack.pop(); members += cells[k]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (k[0]+dx, k[1]+dy)
                    if n in cells and n not in seen:
                        seen.add(n); stack.append(n)
        clusters.append(members)
    return clusters


F = {'origin': {'E0': E0, 'N0': N0, 'epsg': 32642}}

# ---------------------------------------------------------------- page 3 (S6a detail)
dr3, w3 = pickle.load(open(f'{SCR}/p3.pkl', 'rb'))
L3 = collections.defaultdict(list)
for x in dr3:
    L3[x.get('layer')].append(x)

mk = [x for x in L3['ICR MARKING'] if x['rect'].width > 5]
cent = [((x['rect'].x0+x['rect'].x1)/2, (x['rect'].y0+x['rect'].y1)/2, x) for x in mk]
Ew = [w for w in w3 if w[4].startswith('E:')]
Nw = [w for w in w3 if w[4].startswith('N:')]
pairs = []
for e in Ew:
    n = min(Nw, key=lambda n: abs(n[0]-e[0]+4.8)+abs(n[1]-e[1]))
    c = min(cent, key=lambda c: (c[0]-e[0])**2+(c[1]-e[1])**2)
    pairs.append((c[0], c[1], float(e[4][2:]), float(n[4][2:]), c[2]))
cE3, cN3, res3 = fit(pairs)
T3 = mk_tf(cE3, cN3)
print('page3 fit residual m', res3, 'scale', cE3[1])
F['georef_page3'] = {'E': list(cE3), 'N': list(cN3), 'max_residual_m': res3}

# ICR labels -> numbers
icr_labels = {}
for w in w3:
    m = re.match(r'^ICR-(\d+)$', w[4])
    if m:
        icr_labels[int(m.group(1))] = ((w[0]+w[2])/2, (w[1]+w[3])/2)

# ICR blocking polygons (block boundaries)
blocks = []
for x in L3['ICR BLOCKING']:
    if x['rect'].width < 20:
        continue
    pts = item_pts(x['items'])
    P = Polygon(pts).buffer(0)
    if P.area > 500:
        blocks.append(P)
print('ICR block polygons', len(blocks))

# ICR stations: marking rect; number = which block polygon contains it, fallback nearest label
icrs = []
for (cx, cy, E, N, x) in pairs:
    pass
icr_stations = []
for (cx, cy, x) in cent:
    r = x['rect']
    corners = [T3((r.x0, r.y0)), T3((r.x1, r.y0)), T3((r.x1, r.y1)), T3((r.x0, r.y1))]
    icr_stations.append({'page': (cx, cy), 'center': T3((cx, cy)), 'corners': corners})

# station numbering: nearest ICR label
for s_ in icr_stations:
    s_['no'] = min(icr_labels, key=lambda k: (icr_labels[k][0]-s_['page'][0])**2 + (icr_labels[k][1]-s_['page'][1])**2)
nums = collections.Counter(s_['no'] for s_ in icr_stations)
print('station numbering dupes', [k for k, v in nums.items() if v > 1], 'missing', sorted(set(range(1, 20))-set(nums)))
# block polygon label = ICR station inside it, else nearest station
block_out = []
for P in blocks:
    st = [s_['no'] for s_ in icr_stations if P.buffer(2).contains(Point(s_['page']))]
    if not st:
        st = [min(icr_stations, key=lambda s_: P.distance(Point(s_['page'])))['no']]
    block_out.append({'poly': P, 'labels': st[:1]})
print('block polygons', sorted(b_['labels'][0] for b_ in block_out))

# tables
tables = []
for x in L3['table']:
    r = x['rect']
    if r.width > 5:
        continue
    c = T3(((r.x0+r.x1)/2, (r.y0+r.y1)/2))
    tables.append([round(c[0], 3), round(c[1], 3), (r.x0+r.x1)/2, (r.y0+r.y1)/2])
print('tables', len(tables))

# inverters (string inverters)
invs = []
for x in L3['INVERTER BLOCK']:
    r = x['rect']
    if x['items'][0][0] == 'qu' and r.width < 2:
        c = T3(((r.x0+r.x1)/2, (r.y0+r.y1)/2))
        invs.append([round(c[0], 3), round(c[1], 3), (r.x0+r.x1)/2, (r.y0+r.y1)/2])
print('inverters', len(invs))


def block_of(px, py):
    pt = Point(px, py)
    for b_ in block_out:
        if b_['poly'].contains(pt):
            return b_['labels'][0]
    return min(icr_stations, key=lambda s_: math.dist(s_['page'], (px, py)))['no']


for t in tables:
    t.append(block_of(t[2], t[3]))
for v in invs:
    v.append(block_of(v[2], v[3]))
print('tables per block', sorted(collections.Counter(t[4] for t in tables).items()))
print('inverters per block', sorted(collections.Counter(v[4] for v in invs).items()))

# string grouping (20 / 22) polygons -> counts per block (for properties)
F['s6a'] = {
    'tables': [[t[0], t[1], t[4]] for t in tables],
    'inverters': [[v[0], v[1], v[4]] for v in invs],
    'icr_stations': [{'no': s['no'], 'center': s['center'], 'corners': s['corners']} for s in icr_stations],
    'blocks': [{'no': b['labels'][0], 'poly': poly_out(b['poly'], T3)} for b in block_out if len(b['labels']) == 1],
}

# roads (page 3): internal 'Road' (double edge lines) + 'Plant Road' perimeter + WTG roads
def lines_union(layer_list, rad, L, minlen=0.0):
    ls = []
    for ln in layer_list:
        for x in L[ln]:
            for a, b in segs(x['items']):
                if math.dist(a, b) > minlen:
                    ls.append(LineString([a, b]).buffer(rad, cap_style=2, join_style=2))
    return unary_union(ls) if ls else None

road_int = lines_union(['Road'], 1.2, L3).buffer(1.5).buffer(-1.5)        # close dashed double lines into a band
road_plant = lines_union(['Plant Road'], 1.1, L3).buffer(1.5).buffer(-1.5)
road_wtg = lines_union(['5.2MW WTG Road'], 1.0, L3).buffer(1.5).buffer(-1.5)
F['s6a']['roads_internal'] = poly_out(road_int, T3, simp=0.3, minarea=20)
F['s6a']['roads_plant'] = poly_out(road_plant, T3, simp=0.3, minarea=20)
F['s6a']['roads_wtg'] = poly_out(road_wtg, T3, simp=0.3, minarea=20)
print('roads', len(F['s6a']['roads_internal']), len(F['s6a']['roads_plant']), len(F['s6a']['roads_wtg']))

# crane hardstands (filled rects)
cranes = [x for x in L3['5.2MW WTG Crane'] if x['type'] == 'fs' and x['rect'].width > 50]
F['s6a']['crane_pads'] = [q for x in cranes for q in poly_out(Polygon(item_pts(x['items'])).buffer(0), T3, simp=0.5)]

# WTG positions on page 3
def wtg_centers(L, layer, cell):
    blades = [x for x in L[layer] if x['type'] == 'fs']
    pts = []
    for x in blades:
        for p in item_pts(x['items']):
            pts.append(p)
    # cluster blade outlines; hub = vertex that is shared by 3 blades -> use median of cluster bbox centre
    cl = grid_cluster([((x['rect'].x0+x['rect'].x1)/2, (x['rect'].y0+x['rect'].y1)/2) for x in blades], cell)
    out = []
    for members in cl:
        P = [blades[i] for i in members]
        if len(P) < 2:
            continue
        # hub: point that minimises sum of distance to every blade's closest vertex
        allp = [p for b in P for p in item_pts(b['items'])]
        best = None
        for cand in allp:
            s = sum(min(math.dist(cand, q) for q in item_pts(b['items'])) for b in P)
            if best is None or s < best[0]:
                best = (s, cand)
        out.append(best[1])
    return out

w3c = wtg_centers(L3, '5.2MW WTG-AGEL', 30)
F['s6a']['wtg'] = [T3(p) for p in w3c]
print('wtg on p3', len(w3c))

# BESS containers (page 3) - closed outlines
bess = []
for ln in ('BESS_Ph1', 'BESS_Ph2'):
    u = lines_union([ln], 0.6, L3)
    for g in (u.geoms if hasattr(u, 'geoms') else [u]):
        P = Polygon(g.exterior)
        if P.area > 400:
            bb = P.bounds
            bess.append({'layer': ln, 'poly': poly_out(P.buffer(-0.6, join_style=2), T3, simp=0.5)[0], 'page': list(bb)})
F['s6a']['bess_yards'] = bess
print('bess yards', [(b['layer'], [round(v) for v in b['page']]) for b in bess])
# PSS-10 GIS compound
G = [x for x in L3['33-400kV GIS'] if x['rect'].x0 > 1700 and x['rect'].y1 < 2900]
gx0 = min(x['rect'].x0 for x in G); gy0 = min(x['rect'].y0 for x in G); gx1 = max(x['rect'].x1 for x in G); gy1 = max(x['rect'].y1 for x in G)
F['s6a']['pss10'] = {'compound': poly_out(box(gx0, gy0, gx1, gy1), T3)[0],
    'transformers': [T3(((w[0]+w[2])/2, 2626.0)) for w in w3 if w[4] == 'Power' and w[1] < 2700 and w[0] > 1700],
    'gis_hall_center': T3((1856.0, 2658.0)),
    'control_bldg_center': T3((gx1 - 0.12*(gx1-gx0), gy0 + 0.75*(gy1-gy0)))}
S = [x for x in L3['SVG'] if x['rect'].x0 > 1700 and x['rect'].y1 < 2900]
sv = []
rr = [x['rect'] for x in S]
for m in grid_cluster([((r.x0+r.x1)/2, (r.y0+r.y1)/2) for r in rr], 6):
    x0 = min(rr[i].x0 for i in m); y0 = min(rr[i].y0 for i in m); x1 = max(rr[i].x1 for i in m); y1 = max(rr[i].y1 for i in m)
    if (x1-x0)*(y1-y0) > 20:
        sv.append(poly_out(box(x0, y0, x1, y1), T3)[0])
F['s6a']['pss10']['svg_hf'] = sv
print('pss10 compound', [round(v) for v in (gx0, gy0, gx1, gy1)], 'svg/hf boxes', len(sv), 'xfmr', len(F['s6a']['pss10']['transformers']))
print('bess units p3', len(bess))

# texts for PSS-10 internals
for w in w3:
    if w[4] in ('Power', 'SVG', 'HF', 'BESS', 'Xmer'):
        pass
F['s6a']['texts'] = [[w[4], T3(((w[0]+w[2])/2, (w[1]+w[3])/2))] for w in w3 if w[4] in ('Power', 'SVG', 'HF', 'BESS', 'PSS-10', 'KPS-3', 'PSS10')]

# GIS / PSS-10 extents on page 3

# boundary of S6a (Khavda boundary line on page 3) & EPC/cluster boundary
kb = lines_union(['Boundary-Khavda Park'], 0.8, L3)
F['s6a']['khavda_boundary_band'] = poly_out(kb, T3, simp=0.5, minarea=50)
cb = [x for x in L3['Boundary-MW Cluster'] if x['type'] == 'fs']
F['s6a']['cluster_boundary'] = [poly_out(Polygon(item_pts(x['items'])).buffer(0), T3, simp=0.5) for x in cb]

# fence: around union of ICR blocks
ub = unary_union([b['poly'] for b in block_out]).buffer(4, join_style=2).buffer(-2, join_style=2)
F['s6a']['fence'] = poly_out(ub, T3, simp=1.0)

# ---------------------------------------------------------------- page 1 (whole Khavda park)
dr1, w1 = pickle.load(open(f'{SCR}/p1.pkl', 'rb'))
L1 = collections.defaultdict(list)
for x in dr1:
    L1[x.get('layer')].append(x)

circles = [x for x in L1['Coordinates'] if x['items'][0][0] == 'c' and len(x['items']) == 4]
cc = [((x['rect'].x0+x['rect'].x1)/2, (x['rect'].y0+x['rect'].y1)/2) for x in circles]
csegs = [s_ for x in L1['Coordinates'] if x['items'][0][0] == 'l' for s_ in segs(x['items']) if math.dist(*s_) > 5]
nums_ = [w for w in w1 if re.match(r'^\d{6,7}\.\d+$', w[4])]
def wbox_dist(p, w):
    dx = max(w[0]-p[0], 0, p[0]-w[2]); dy = max(w[1]-p[1], 0, p[1]-w[3]); return math.hypot(dx, dy)
snapped = []
for c in cc:
    # follow leader: chain segments starting at the circle centre
    cur, used = c, set()
    for _ in range(4):
        nxt = None
        for i, (p, q) in enumerate(csegs):
            if i in used: continue
            if math.dist(p, cur) < 1.0: nxt = (i, q)
            elif math.dist(q, cur) < 1.0: nxt = (i, p)
            if nxt: break
        if not nxt: break
        used.add(nxt[0]); cur = nxt[1]
    if cur == c: continue
    near = sorted(nums_, key=lambda w: wbox_dist(cur, w))[:2]
    if len(near) < 2 or wbox_dist(cur, near[1]) > 25: continue
    vals = sorted(float(w[4]) for w in near)
    if not (vals[0] < 2e6 < vals[1]): continue
    snapped.append((c[0], c[1], vals[0], vals[1]))
print('page1 control points', snapped)
cE1, cN1, res1 = fit(snapped)
T1 = mk_tf(cE1, cN1)
print('page1 fit residual m', res1, 'scale', cE1[1], 'n', len(snapped))
F['georef_page1'] = {'E': list(cE1), 'N': list(cN1), 'max_residual_m': res1}

# park boundary polygon: union of buffered boundary strokes -> outer shell of the band
kb1 = lines_union(['Boundary-Khavda Park'], 1.5, L1)
parts = [kb1] if isinstance(kb1, Polygon) else list(kb1.geoms)
big = max(parts, key=lambda p: Polygon(p.exterior).area)
F['park'] = {}
outer = Polygon(big.exterior)
F['park']['boundary'] = poly_out(outer, T1, simp=5)
F['park']['boundary_band'] = poly_out(kb1, T1, simp=3, minarea=500)

# plots: region inside boundary split by cluster boundary lines and main corridors
cl_lines = lines_union(['Boundary-MW Cluster', 'Boundary-Khavda Park', '400kV TL Corridor'], 1.2, L1)
plots = outer.buffer(-1).difference(cl_lines)
plist = [p for p in (plots.geoms if hasattr(plots, 'geoms') else [plots]) if p.area > 400]
print('plots', len(plist))
F['park']['plots'] = [poly_out(p, T1, simp=10)[0] for p in plist]

# roads page 1
r1 = lines_union(['Plant Road'], 0.55, L1)
F['park']['roads'] = poly_out(r1, T1, simp=4, minarea=2000)
r2 = lines_union(['400kV TL Corridor'], 0.7, L1)
F['park']['main_corridor'] = poly_out(r2, T1, simp=4, minarea=2000)
F['park']['airstrip_road'] = poly_out(lines_union(['Air Strip Road'], 0.45, L1), T1, simp=3, minarea=500)
print('park roads', len(F['park']['roads']), len(F['park']['main_corridor']))

# 400 kV TL routes -> tower points + spans
tlu = lines_union(['400kV TL Route'], 0.5, L1)
tlm = Polygon()
parts = []
for g in (tlu.geoms if hasattr(tlu, 'geoms') else [tlu]):
    ext = [T1(c) for c in g.exterior.coords]
    parts.append(Polygon(ext, [[T1(c) for c in r.coords] for r in g.interiors]).buffer(0))
tlm = unary_union(parts)
towers = []
SP = 350.0
for g in (tlm.geoms if hasattr(tlm, 'geoms') else [tlm]):
    rings = [g.exterior] + list(g.interiors)
    for r in rings:
        n = int(r.length // 50) + 1
        for i in range(n):
            q = r.interpolate(i*50.0)
            if all(math.dist((q.x, q.y), t) > SP*0.8 for t in towers):
                towers.append((q.x, q.y))
corr = tlm.buffer(25)
spans = []
for i, a_ in enumerate(towers):
    nb = sorted(((math.dist(a_, b_), j) for j, b_ in enumerate(towers) if j > i and math.dist(a_, b_) < SP*1.6))
    for d_, j in nb[:3]:
        if corr.contains(LineString([a_, towers[j]])):
            spans.append((i, j))
F['park']['tl_towers'] = towers
F['park']['tl_spans'] = spans
print('tl towers', len(towers), 'spans', len(spans))

# WTGs page 1
w1c = wtg_centers(L1, '5.2MW WTG-AGEL', 4)
F['park']['wtg'] = [(T1(p)[0]-13.3, T1(p)[1]-6.1) for p in w1c]  # symbol-hub offset measured against sheet 3 WTGs
print('wtg p1', len(w1c))

# switchyards 765/400 kV
F['park']['kps'] = [poly_out(Polygon(item_pts(x['items'])).buffer(0), T1)[0] for x in L1['400-765kV Switchyard'] if len(item_pts(x['items'])) >= 4]

# PSS labels -> GIS cluster
gis1 = [((x['rect'].x0+x['rect'].x1)/2, (x['rect'].y0+x['rect'].y1)/2) for x in L1['33-400kV GIS']]
gcl = grid_cluster(gis1, 3)
gcent = []
for m in gcl:
    if len(m) < 50:
        continue
    xs = [gis1[i][0] for i in m]; ys = [gis1[i][1] for i in m]
    gcent.append(((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (max(xs)-min(xs), max(ys)-min(ys))))
print('gis clusters', len(gcent))
pss = []
used = set()
labs_ = []
for w in w1:
    m = re.match(r'^PSS-?0?(\d+)$', w[4])
    if m and (w[2]-w[0]) > 10:
        labs_.append((w, int(m.group(1))))
cands = sorted(((math.dist(g[:2], ((w[0]+w[2])/2, (w[1]+w[3])/2)), gi, li) for li, (w, n) in enumerate(labs_) for gi, g in enumerate(gcent)))
assign = {}
for d_, gi, li in cands:
    if d_ < 200 and gi not in used and li not in assign:
        assign[li] = gi; used.add(gi)
for li, (w, n) in enumerate(labs_):
    lc = ((w[0]+w[2])/2, (w[1]+w[3])/2)
    kps = [q[4] for q in w1 if q[4].startswith('KPS') and abs(q[0]-w[0]+28.5) < 4 and abs(q[1]-w[1]) < 15]
    pos = T1(gcent[assign[li]][:2]) if li in assign else T1((lc[0]-20, lc[1]))
    pss.append({'name': f'PSS-{n:02d}', 'kps': kps[0] if kps else '', 'pos': pos, 'snap': round(math.dist(gcent[assign[li]][:2], lc), 1) if li in assign else None})
F['park']['pss'] = pss
print('pss', [(p['name'], p['kps'], [round(v) for v in p['pos']], p['snap']) for p in pss])

# infra compounds (thick outlines) and BESS blocks of other plots
inf = []
for x in L1['Infra']:
    if x['type'] == 'fs' and len(x['items']) >= 12 and x['rect'].width + x['rect'].height > 3:
        P = Polygon(item_pts(x['items'])).buffer(0)
        if P.area > 0.5:
            inf += poly_out(P, T1, simp=1)
F['park']['infra_walls'] = inf
bess1 = []
for ln in ('BESS_Ph1', 'BESS_Ph2', 'BESS_Ph3'):
    for x in L1[ln]:
        pts = item_pts(x['items'])
        if len(pts) >= 4:
            P = Polygon(pts).buffer(0)
            if P.area > 0.3:
                bess1.append(poly_out(P.minimum_rotated_rectangle, T1)[0])
F['park']['bess_blocks'] = bess1
print('infra', len(inf), 'bess blocks', len(bess1))

# no-go areas
ng = lines_union(['No Go Area'], 0.8, L1).buffer(2.5).buffer(-2.5)
F['park']['nogo'] = poly_out(ng, T1, simp=10, minarea=20000)

# labels for camps etc. (multi-word phrases)
lab = []
for b in pickle.load(open(f'{SCR}/p1.pkl', 'rb'))[1]:
    pass
F['park']['labels'] = [[w[4], T1(((w[0]+w[2])/2, (w[1]+w[3])/2))] for w in w1 if w[4] in ('Camp-1', 'Camp-2', 'Camp-3', 'Camp-4', 'CCR', 'Wind', 'Yard', 'LC-3', 'LC-3B')]

json.dump(F, open(f'{SCR}/features.json', 'w'))
print('saved')
