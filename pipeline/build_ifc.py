"""Build the Khavda Hybrid Park + S6a-234MW IFC4 model from features.json."""
import json, math, sys, time, colorsys
import ifcopenshell, ifcopenshell.guid
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union
from shapely import affinity

FEAT, OUT = sys.argv[1], sys.argv[2]
F = json.load(open(FEAT))
t0 = time.time()

f = ifcopenshell.file(schema='IFC4')
G = ifcopenshell.guid.new
C = f.create_entity


# ------------------------------------------------------------------ geometry helpers
_pts = {}
def P3(x, y, z=0.0):
    k = (round(x, 4), round(y, 4), round(z, 4))
    if k not in _pts:
        _pts[k] = C('IfcCartesianPoint', [float(k[0]), float(k[1]), float(k[2])])
    return _pts[k]

def P2(x, y):
    return C('IfcCartesianPoint', [float(round(x, 4)), float(round(y, 4))])

_dirs = {}
def D(*v):
    k = tuple(round(a, 6) for a in v)
    if k not in _dirs:
        _dirs[k] = C('IfcDirection', [float(a) for a in k])
    return _dirs[k]

def A3(x=0, y=0, z=0, axis=None, ref=None):
    return C('IfcAxis2Placement3D', P3(x, y, z), D(*axis) if axis else None, D(*ref) if ref else None)

ORIGIN = A3()
ORIGIN2 = C('IfcAxis2Placement2D', P2(0, 0), None)

def rect_prof(xd, yd, cx=0.0, cy=0.0):
    pos = ORIGIN2 if (cx == 0 and cy == 0) else C('IfcAxis2Placement2D', P2(cx, cy), None)
    return C('IfcRectangleProfileDef', 'AREA', None, pos, float(xd), float(yd))

def circ_prof(r):
    return C('IfcCircleProfileDef', 'AREA', None, ORIGIN2, float(r))

def box_solid(dx, dy, dz, x=0, y=0, z=0, axis=None, ref=None):
    """Box centred in x/y on (x, y), from z upward (in its own placement)."""
    return C('IfcExtrudedAreaSolid', rect_prof(dx, dy), A3(x, y, z, axis, ref), D(0, 0, 1), float(dz))

def cyl(r, h, x=0, y=0, z=0):
    return C('IfcExtrudedAreaSolid', circ_prof(r), A3(x, y, z), D(0, 0, 1), float(h))

def taper(prof0, prof1, h, x=0, y=0, z=0, axis=None, ref=None):
    return C('IfcExtrudedAreaSolidTapered', prof0, A3(x, y, z, axis, ref), D(0, 0, 1), float(h), prof1)

def poly_prof(ext, holes=()):
    def curve(ring):
        pts = [P2(*c) for c in ring] + [None]
        pts[-1] = pts[0]
        return C('IfcPolyline', pts)
    if holes:
        return C('IfcArbitraryProfileDefWithVoids', 'AREA', None, curve(ext), [curve(h) for h in holes])
    return C('IfcArbitraryClosedProfileDef', 'AREA', None, curve(ext))

def split_holes(pg, depth=0):
    """Split a polygon with holes into hole-free polygons (cut through hole centroids)."""
    if pg.is_empty:
        return []
    if pg.geom_type == 'MultiPolygon':
        return [q for g in pg.geoms for q in split_holes(g, depth)]
    if pg.geom_type != 'Polygon':
        return []
    if not pg.interiors or depth > 40:
        return [pg]
    hc = Polygon(pg.interiors[0]).centroid
    minx, miny, maxx, maxy = pg.bounds
    if (maxx - minx) >= (maxy - miny):
        a_, b_ = box(minx-1, miny-1, hc.x, maxy+1), box(hc.x, miny-1, maxx+1, maxy+1)
    else:
        a_, b_ = box(minx-1, miny-1, maxx+1, hc.y), box(minx-1, hc.y, maxx+1, maxy+1)
    out = []
    for half in (pg.intersection(a_), pg.intersection(b_)):
        out += split_holes(half, depth+1)
    return out


def poly_solid(ext, z0, h, holes=()):
    ring = [tuple(c) for c in ext]
    if Polygon(ring).exterior.is_ccw is False:
        ring = ring[::-1]
    hs = []
    for hr in holes:
        hr = [tuple(c) for c in hr]
        if Polygon(hr).exterior.is_ccw:
            hr = hr[::-1]
        hs.append(hr)
    return C('IfcExtrudedAreaSolid', poly_prof(ring, hs), A3(0, 0, z0), D(0, 0, 1), float(h))


# ------------------------------------------------------------------ styles
_styles = {}
def style(name, rgb, transp=0.0, spec=False):
    if name in _styles:
        return _styles[name]
    col = C('IfcColourRgb', name, *[float(c) for c in rgb])
    rend = C('IfcSurfaceStyleRendering', col, float(transp), None, None, None, None,
             C('IfcNormalisedRatioMeasure', 0.6 if spec else 0.2) if True else None,
             C('IfcSpecularExponent', 64.0 if spec else 8.0), 'NOTDEFINED')
    ss = C('IfcSurfaceStyle', name, 'BOTH', [rend])
    _styles[name] = ss
    return ss

def paint(items, st):
    for it in (items if isinstance(items, (list, tuple)) else [items]):
        C('IfcStyledItem', it, [st], None)
    return items

S = {
    'module': style('PV Module glass (S6a, ALMM N-type 625 Wp)', (0.10, 0.26, 0.66), spec=True),
    'module_other': style('PV Module glass (other plots, indicative)', (0.11, 0.25, 0.60), spec=True),
    'steel': style('Galvanised steel', (0.72, 0.74, 0.76)),
    'pile': style('Pile / Post', (0.55, 0.56, 0.58)),
    'concrete': style('Concrete', (0.70, 0.69, 0.66)),
    'road': style('WBM / gravel road', (0.66, 0.60, 0.50)),
    'road_main': style('Asphalt road', (0.17, 0.17, 0.18)),
    'terrain': style('Terrain - desert sand', (0.87, 0.76, 0.58)),
    'gravel': style('Switchyard gravel', (0.62, 0.62, 0.60)),
    'xfmr': style('Transformer (RAL 7032)', (0.66, 0.67, 0.62)),
    'radiator': style('Radiator', (0.45, 0.47, 0.46)),
    'panel': style('Panel / kiosk (RAL 7035)', (0.85, 0.86, 0.84)),
    'inverter': style('String inverter', (0.90, 0.90, 0.92)),
    'canopy': style('Inverter canopy sheet', (0.30, 0.45, 0.65)),
    'wtg': style('WTG white (RAL 7035)', (0.95, 0.95, 0.95), spec=True),
    'wtg_red': style('WTG aviation marking', (0.85, 0.12, 0.10)),
    'bess': style('BESS container', (0.93, 0.93, 0.90)),
    'bess_pcs': style('BESS PCS skid', (0.20, 0.45, 0.70)),
    'fence': style('Chain-link fence', (0.40, 0.42, 0.44), transp=0.35),
    'park_fence': style('Khavda park boundary', (0.10, 0.25, 0.85)),
    'building': style('Building (RCC / PEB)', (0.88, 0.84, 0.76)),
    'roof': style('Roof (PEB sheet)', (0.25, 0.42, 0.62)),
    'gis': style('GIS hall', (0.80, 0.82, 0.86)),
    'svg': style('SVG / HF equipment', (0.55, 0.30, 0.65)),
    'tower': style('Lattice tower', (0.60, 0.62, 0.64)),
    'conductor': style('Conductor', (0.25, 0.25, 0.25)),
    'nogo': style('No-go area', (0.90, 0.35, 0.35), transp=0.55),
    'plot_ground': style('Solar plot ground (graded sand)', (0.80, 0.70, 0.54)),
    'wall': style('Compound wall', (0.75, 0.70, 0.62)),
    'crane': style('Crane hardstand', (0.66, 0.62, 0.55)),
}
block_cols = {}
for i in range(1, 20):
    h = ((i-1) * 0.381966) % 1.0
    block_cols[i] = style(f'ICR Block-{i:02d} zone (graded sand)', colorsys.hsv_to_rgb(0.09 + 0.03*math.sin(i*1.7), 0.30, 0.86 + 0.04*math.cos(i*2.3)))


# ------------------------------------------------------------------ project setup
def unit(t, n, prefix=None):
    return C('IfcSIUnit', None, t, prefix, n)

units = C('IfcUnitAssignment', [unit('LENGTHUNIT', 'METRE'), unit('AREAUNIT', 'SQUARE_METRE'),
                                unit('VOLUMEUNIT', 'CUBIC_METRE'), unit('PLANEANGLEUNIT', 'RADIAN'),
                                unit('MASSUNIT', 'GRAM', 'KILO'), unit('TIMEUNIT', 'SECOND')])
ctx = C('IfcGeometricRepresentationContext', None, 'Model', 3, 1e-5, ORIGIN, D(0, 1))
body = C('IfcGeometricRepresentationSubContext', 'Body', 'Model', None, None, None, None, ctx, None, 'MODEL_VIEW', None)
project = C('IfcProject', G(), None, 'Khavda Hybrid Renewable Energy Park - S6a-234MW',
            'IFC model generated from 51YY-KPIG-ARY-BES-DE-L-0001 R2 (Overall Plant Array Layout, 18.03.2026)',
            None, 'AGE26AL / Cluster S06a-234MW', 'Design', [ctx], units)
crs = C('IfcProjectedCRS', 'EPSG:32642', 'WGS 84 / UTM zone 42N', 'WGS84', None, 'UTM', '42N',
        None)
C('IfcMapConversion', ctx, crs, F['origin']['E0'], F['origin']['N0'], 0.0, 1.0, 0.0, 1.0)


def pset(name, props, objs):
    vals = []
    for k, v in props.items():
        if isinstance(v, bool):
            nv = C('IfcBoolean', v)
        elif isinstance(v, int):
            nv = C('IfcInteger', v)
        elif isinstance(v, float):
            nv = C('IfcReal', v)
        else:
            nv = C('IfcLabel', str(v))
        vals.append(C('IfcPropertySingleValue', k, None, nv, None))
    ps = C('IfcPropertySet', G(), None, name, None, vals)
    objs = list(objs)
    for i in range(0, len(objs), 20000):
        C('IfcRelDefinesByProperties', G(), None, None, None, objs[i:i+20000], ps)
    return ps


def lp(rel_to, x=0, y=0, z=0, rot=0.0):
    ref = (math.cos(rot), math.sin(rot), 0.0) if rot else None
    return C('IfcLocalPlacement', rel_to, A3(x, y, z, None, ref) if (x or y or z or rot) else ORIGIN)


def spatial(cls, name, parent, parent_pl, desc=None, long_name=None, **kw):
    pl = lp(parent_pl)
    if cls == 'IfcSite':
        e = C('IfcSite', G(), None, name, desc, None, pl, None, long_name, 'ELEMENT',
              kw.get('lat'), kw.get('lon'), kw.get('elev'), None, None)
    else:
        e = C('IfcBuilding', G(), None, name, desc, None, pl, None, long_name, 'ELEMENT', None, None, None)
    C('IfcRelAggregates', G(), None, None, None, parent, [e])
    return e, pl


park, park_pl = spatial('IfcSite', 'Khavda Hybrid Renewable Energy Park', project, None,
                        'Khavda, Kutch, Gujarat - 70,425 acre hybrid park (15,727 MW solar AC + 392 x 5.2 MW WTG)',
                        'Khavda Hybrid Park - Gujarat', lat=[24, 3, 30, 0], lon=[69, 26, 30, 0], elev=5.0)
s6a, s6a_pl = spatial('IfcSite', 'Plot S6a - 234 MW AC / 318.26 MWp', park, park_pl,
                      'AGE26AL - 234MW-MLP T1 PPA - BEST_AGE26AL. EPC: KPI Green Energy Ltd',
                      'Cluster S06a-234MW (713 acre)')
pset('Pset_S6a_PlantData', {
    'BlockArea_acre': 713.0, 'FixedTiltTables_2Px28': 9093, 'ModuleMake': 'ALMM (N-Type)',
    'ModuleRating_Wp': 625, 'ModulesTotal': 509208, 'StringsTotal': 18186,
    'InverterMake': 'WattPower', 'InverterRating_kW': 275, 'InverterQuantity': 883,
    'IDT_Size_MVA': 13.75, 'IDT_Quantity': 19, 'DC_Capacity_MWp': 318.26, 'AC_Capacity_MW': 242.83,
    'PlantOverloading': '31%', 'Pitch_m': 7.5, 'TiltAngle_deg': 17, 'ModuleAzimuth_deg': 0,
    'TotalInternalRoadLength_m': 6000, 'PoolingSubstation': 'PSS-10 / KPS-3',
    'SourceDrawing': '51YY-KPIG-ARY-BES-DE-L-0001 R2'}, [s6a])

contained = {}
def contain(spatial_el, el):
    contained.setdefault(spatial_el, []).append(el)


def product(cls, name, rep, pl, spatial_el, **attrs):
    """Generic element creation. rep = IfcProductDefinitionShape (can be shared)."""
    e = C(cls, G(), None, name, attrs.pop('desc', None), attrs.pop('otype', None), pl, rep, attrs.pop('tag', None), **attrs)
    contain(spatial_el, e)
    return e


def shape(items, rtype='SweptSolid'):
    return C('IfcProductDefinitionShape', None, None,
             [C('IfcShapeRepresentation', body, 'Body', rtype, items if isinstance(items, list) else [items])])


ID_OP = C('IfcCartesianTransformationOperator3D', None, None, P3(0, 0, 0), None, None)
def rmap(items):
    """Representation map + a single shared product shape referencing it."""
    rm = C('IfcRepresentationMap', ORIGIN, C('IfcShapeRepresentation', body, 'Body', 'SweptSolid', items))
    mi = C('IfcMappedItem', rm, ID_OP)
    return rm, C('IfcProductDefinitionShape', None, None, [C('IfcShapeRepresentation', body, 'Body', 'MappedRepresentation', [mi])])


types = {}
def typ(cls, name, rm, objs, props=None, **kw):
    key = (cls, name)
    if key not in types:
        t = C(cls, G(), None, name, None, None, None, [rm] if rm else None, None, None, kw.get('etype'), kw.get('ptype', 'USERDEFINED'))
        if props:
            pset('Pset_' + name.replace(' ', '_')[:40], props, [])  # placeholder removed below
        types[key] = [t, []]
    types[key][1].extend(objs)
    return types[key][0]


# ================================================================== S6a: fixed tilt tables
TILT = math.radians(17.0)
SLOPE = 4.788                               # module plane width up-slope: 2 x 2.384 + 0.020 gap
L_TAB = 32.292
H_LOW = 0.80                                # module lower edge clearance
HC = H_LOW + SLOPE/2*math.sin(TILT)         # mid-height of module plane
nrm = (0.0, -math.sin(TILT), math.cos(TILT))   # module normal (faces south)
along = (1.0, 0.0, 0.0)

# modules: 2 rows (2P portrait), each 32.292 x 2.384 x 0.035
MOD_W, MOD_L, MOD_GAP = 1.134, 2.384, 0.020
mod_items = []
for s in (-(MOD_L/2 + MOD_GAP/2), (MOD_L/2 + MOD_GAP/2)):          # 2 rows (2P portrait)
    cy, cz = s*math.cos(TILT), HC + s*math.sin(TILT)
    for k in range(28):                                            # 28 modules per row
        mx = -L_TAB/2 + MOD_W/2 + k*(MOD_W + MOD_GAP)
        mod_items.append(C('IfcExtrudedAreaSolid', rect_prof(MOD_W, MOD_L), A3(mx, cy, cz, nrm, along), D(0, 0, 1), 0.035))
paint(mod_items, S['module'])
RM_MOD, PS_MOD = rmap(mod_items)

PILE_X = [-14.5, -8.7, -2.9, 2.9, 8.7, 14.5]
PILE_Y = [-1.55, 1.55]
def z_under(y):  # underside of rafter at y
    return HC + y*math.tan(TILT) - 0.20
mms_items = []
for x in PILE_X:   # rafters (inclined, along slope)
    mms_items.append(C('IfcExtrudedAreaSolid', rect_prof(0.08, SLOPE - 0.2), A3(x, 0, HC - 0.16, nrm, along), D(0, 0, 1), 0.12))
for s in (-1.25, 1.25):   # purlins
    cy, cz = s*math.cos(TILT), HC + s*math.sin(TILT) - 0.06
    mms_items.append(C('IfcExtrudedAreaSolid', rect_prof(L_TAB - 0.2, 0.06), A3(0, cy, cz, nrm, along), D(0, 0, 1), 0.06))
paint(mms_items, S['steel'])
RM_MMS, PS_MMS = rmap(mms_items)

pile_items = []
for x in PILE_X:
    for y in PILE_Y:
        zt = z_under(y)
        pile_items.append(C('IfcExtrudedAreaSolid', rect_prof(0.15, 0.10), A3(x, y, -0.0), D(0, 0, 1), float(zt + 0.04)))
for x in PILE_X:
    for y in PILE_Y:   # concrete collar at ground (auger + concrete)
        pile_items.append(box_solid(0.36, 0.36, 0.12, x, y, 0.0))   # concrete collar
paint(pile_items[:12], S['pile'])
paint(pile_items[12:], S['concrete'])
RM_PILE, PS_PILE = rmap(pile_items)

# ---- string inverter on structure with canopy (footprint ~4.4 m E-W x 1.5 m N-S)
inv_items = paint([box_solid(1.05, 0.40, 0.75, 0, 0.05, 0.95), box_solid(1.05, 0.40, 0.75, 1.3, 0.05, 0.95),
                   box_solid(0.6, 0.30, 0.6, -1.3, 0.05, 1.0)], S['inverter'])
RM_INV, PS_INV = rmap(inv_items)
invs_items = paint([box_solid(0.10, 0.10, 2.55, x, y, 0) for x in (-2.1, 2.1) for y in (-0.6, 0.6)]
                   + [box_solid(4.3, 0.08, 0.10, 0, y, 1.7) for y in (-0.6, 0.6)], S['steel'])
invs_items += paint([C('IfcExtrudedAreaSolid', rect_prof(4.6, 1.8), A3(0, 0, 2.55, (0, -0.17, 0.985), (1, 0, 0)), D(0, 0, 1), 0.04)], S['canopy'])
RM_INVS, PS_INVS = rmap(invs_items)


def phase_of(b):
    if b <= 4: return 'PHASE-1 (50MW)'
    if b <= 8: return 'PHASE-2 (50MW)'
    if b <= 12: return 'PHASE-3 (50MW)'
    if b <= 16: return 'PHASE-4 (50MW)'
    return 'PHASE-5 (34MW)'


blocks_bld = {}
block_pl = {}
for b in range(1, 20):
    bld, pl = spatial('IfcBuilding', f'Block-{b:02d} (ICR-{b:02d})', s6a, s6a_pl,
                      f'Inverter / ICR block {b} - 13.75 MVA IDT', f'BLOCK-{b:02d} | {phase_of(b)}')
    blocks_bld[b], block_pl[b] = bld, pl

tabs_by_block = {}
for i, (x, y, b) in enumerate(F['s6a']['tables']):
    tabs_by_block.setdefault(b, []).append((x, y))
counters = {'tables': 0}
block_elems = {b: [] for b in range(1, 20)}
elems_by_type = {'mod': [], 'mms': [], 'pile': [], 'inv': [], 'invs': []}
for b in sorted(tabs_by_block):
    lst = sorted(tabs_by_block[b], key=lambda p: (-round(p[1] / 7.5), p[0]))
    for k, (x, y) in enumerate(lst, 1):
        pl = lp(block_pl[b], x, y, 0.0)
        tag = f'S6a-B{b:02d}-T{k:04d}'
        e1 = product('IfcPile', f'{tag} Piles (12 nos)', PS_PILE, pl, blocks_bld[b], tag=tag, PredefinedType='BORED', ConstructionType=None)
        e2 = product('IfcMember', f'{tag} MMS Structure FT 2Px28', PS_MMS, pl, blocks_bld[b], tag=tag, PredefinedType='USERDEFINED')
        e2.ObjectType = 'MMS Fixed Tilt 2Px28'
        e3 = product('IfcSolarDevice', f'{tag} PV Modules (56 x 625 Wp)', PS_MOD, pl, blocks_bld[b], tag=tag, PredefinedType='SOLARPANEL')
        block_elems[b] += [e1, e2, e3]
        elems_by_type['pile'].append(e1); elems_by_type['mms'].append(e2); elems_by_type['mod'].append(e3)
        counters['tables'] += 1
print('tables', counters['tables'], round(time.time()-t0, 1))

inv_by_block = {}
for x, y, b in F['s6a']['inverters']:
    inv_by_block.setdefault(b, []).append((x, y))
for b in sorted(inv_by_block):
    for k, (x, y) in enumerate(sorted(inv_by_block[b], key=lambda p: (-p[1], p[0])), 1):
        pl = lp(block_pl[b], x, y, 0.0)
        tag = f'S6a-B{b:02d}-INV{k:02d}'
        e1 = product('IfcTransformer', f'{tag} String Inverter 275 kW (WattPower)', PS_INV, pl, blocks_bld[b], tag=tag, PredefinedType='INVERTER')
        e2 = product('IfcMember', f'{tag} Inverter Structure + Canopy', PS_INVS, pl, blocks_bld[b], tag=tag, PredefinedType='USERDEFINED')
        e2.ObjectType = 'Inverter mounting structure with canopy'
        block_elems[b] += [e1, e2]
        elems_by_type['inv'].append(e1); elems_by_type['invs'].append(e2)
print('inverters', len(elems_by_type['inv']))

# ---- ICR / IDT stations (footprint ~23.6 m E-W x 10.1 m N-S)
plinth = paint([box_solid(23.6, 10.1, 0.3)], S['concrete'])
RM_PL, PS_PL = rmap(plinth)
idt = paint([box_solid(4.6, 3.2, 3.6, 0, 0, 0.3), box_solid(1.2, 0.5, 0.8, 0, -0.4, 4.2)], S['xfmr'])
idt += paint([box_solid(0.25, 2.8, 2.6, xx, 0, 0.8) for xx in (-2.9, -2.6, 2.6, 2.9)], S['radiator'])
idt += paint([cyl(0.10, 1.1, xx, 1.0, 3.9) for xx in (-1.2, 0, 1.2)] + [cyl(0.35, 2.4, 0, -1.1, 4.4)], S['panel'])
RM_IDT, PS_IDT = rmap(idt)
ht = paint([box_solid(6.0, 2.6, 2.9, 0, 0, 0.3)], S['panel']) + paint([box_solid(6.3, 2.9, 0.12, 0, 0, 3.2)], S['roof'])
RM_HT, PS_HT = rmap(ht)
aux = paint([box_solid(1.6, 1.2, 1.8, 0, 0, 0.3)], S['xfmr'])
RM_AUX, PS_AUX = rmap(aux)
fz = []
for (x0, y0, x1, y1) in [(-11.6, -4.85, 11.6, -4.85), (11.6, -4.85, 11.6, 4.85), (11.6, 4.85, -11.6, 4.85), (-11.6, 4.85, -11.6, -4.85)]:
    L = math.dist((x0, y0), (x1, y1))
    fz.append(box_solid(L, 0.05, 2.4, (x0+x1)/2, (y0+y1)/2, 0.3, None, ((x1-x0)/L, (y1-y0)/L, 0)))
paint(fz, S['fence'])
RM_ICRF, PS_ICRF = rmap(fz)

for st in F['s6a']['icr_stations']:
    b = st['no']
    cx, cy = st['center']
    c = st['corners']
    rot = math.atan2(c[1][1]-c[0][1], c[1][0]-c[0][0])
    # long side of marking runs E-W; orient station along it
    ux, uy = math.cos(rot), math.sin(rot)
    if abs(ux) < abs(uy):
        rot += math.pi/2
    pl0 = lp(block_pl[b], cx, cy, 0.0, rot)
    def sub(dx, dy):
        return C('IfcLocalPlacement', pl0, A3(dx, dy, 0))
    tag = f'S6a-ICR-{b:02d}'
    els = [product('IfcSlab', f'{tag} IDT Station Plinth', PS_PL, pl0, blocks_bld[b], tag=tag, PredefinedType='BASESLAB'),
           product('IfcTransformer', f'{tag} IDT 13.75 MVA 33/0.8 kV (ONAN)', PS_IDT, sub(-2.5, 0.2), blocks_bld[b], tag=tag, PredefinedType='VOLTAGE'),
           product('IfcElectricDistributionBoard', f'{tag} HT Panel (33 kV RMU/VCB)', PS_HT, sub(6.5, 2.4), blocks_bld[b], tag=tag, PredefinedType='SWITCHBOARD'),
           product('IfcElectricDistributionBoard', f'{tag} LT Panel / ACDB', PS_HT, sub(6.5, -2.4), blocks_bld[b], tag=tag, PredefinedType='DISTRIBUTIONBOARD'),
           product('IfcTransformer', f'{tag} Auxiliary Transformer', PS_AUX, sub(-9.2, 2.5), blocks_bld[b], tag=tag, PredefinedType='VOLTAGE'),
           product('IfcRailing', f'{tag} IDT Fencing & Gate', PS_ICRF, pl0, blocks_bld[b], tag=tag, PredefinedType='USERDEFINED')]
    els[-1].ObjectType = 'FENCE'
    block_elems[b] += els

# ---- ICR block zones (coloured ground patch derived from table footprints)
zones = {}
for b, lst in tabs_by_block.items():
    geoms = [box(x-16.6, y-3.4, x+16.6, y+3.4) for x, y in lst]
    u = unary_union(geoms).buffer(4, join_style=2).buffer(-4, join_style=2)
    u = u.simplify(0.5)
    items = []
    for g in (u.geoms if hasattr(u, 'geoms') else [u]):
        if g.area < 300:
            continue
        for q in split_holes(Polygon(g.exterior, [r for r in g.interiors if Polygon(r).area > 200])):
            if q.area > 5 and q.geom_type == 'Polygon':
                items.append(poly_solid(list(q.exterior.coords)[:-1], 0.0, 0.04))
    paint(items, block_cols[b])
    z = product('IfcGeographicElement', f'Block-{b:02d} (ICR-{b:02d}) Array Zone', shape(items), lp(block_pl[b]), blocks_bld[b], PredefinedType='USERDEFINED')
    z.ObjectType = 'ICR block zone (ground marking)'
    block_elems[b].append(z)
    zones[b] = u

for b in range(1, 20):
    n_t = len(tabs_by_block.get(b, []))
    n_i = len(inv_by_block.get(b, []))
    pset('VL_Location', {'Project': 'S06A', 'Plot': 'S6a-234MW', 'Phase': phase_of(b), 'Block': f'BLOCK-{b:02d}',
                         'ICR': f'ICR-{b:02d}', 'TablesInBlock': n_t, 'InvertersInBlock': n_i,
                         'ModulesInBlock': n_t*56, 'DC_Capacity_kWp': round(n_t*56*0.625, 1)},
         block_elems[b] + [blocks_bld[b]])

# type objects & type property sets
def make_type(cls, name, rm, objs, ptype, props):
    t = C(cls, G(), None, name, None, None, None, [rm], None, name, ptype)
    if props:
        vals = []
        for k, v in props.items():
            nv = C('IfcLabel', str(v)) if isinstance(v, str) else (C('IfcReal', v) if isinstance(v, float) else C('IfcInteger', v))
            vals.append(C('IfcPropertySingleValue', k, None, nv, None))
        t.HasPropertySets = [C('IfcPropertySet', G(), None, 'Pset_' + name.split(' ')[0] + '_Spec', None, vals)]
    for i in range(0, len(objs), 20000):
        C('IfcRelDefinesByType', G(), None, None, None, objs[i:i+20000], t)
    return t

make_type('IfcSolarDeviceType', 'PV Module Row 2Px28 (ALMM N-type 625 Wp)', RM_MOD, elems_by_type['mod'], 'SOLARPANEL',
          {'ModuleRating_Wp': 625, 'ModulesPerTable': 56, 'ModuleDimensions_mm': '2384 x 1134 x 35', 'Orientation': 'PORTRAIT',
           'TiltAngle_deg': 17.0, 'Azimuth_deg': 0.0, 'ModulesPerString': 28, 'StringsPerTable': 2, 'TableDC_kWp': 35.0})
make_type('IfcMemberType', 'MMS Fixed Tilt Table FT-2Px28 (32.292 x 4.788 m)', RM_MMS, elems_by_type['mms'], 'USERDEFINED',
          {'TableLength_m': 32.292, 'TableWidth_m': 4.788, 'Pitch_m': 7.5, 'Configuration': '2Px28', 'Rafters': 6, 'Purlins': 2})
make_type('IfcPileType', 'MMS Pile (augured + concreted) 12 nos/table', RM_PILE, elems_by_type['pile'], 'BORED',
          {'PilesPerTable': 12, 'Columns': 6, 'Rows': 2, 'Method': 'Marking, Auguring & Concreting'})
make_type('IfcTransformerType', 'String Inverter 275 kW WattPower', RM_INV, elems_by_type['inv'], 'INVERTER',
          {'Make': 'WattPower', 'Rating_kW': 275.0, 'Quantity_S6a': 883})
make_type('IfcMemberType', 'Inverter Structure with Canopy', RM_INVS, elems_by_type['invs'], 'USERDEFINED', None)
print('S6a array done', round(time.time()-t0, 1))

# ================================================================== S6a common: roads, fence, cranes
s6c, s6c_pl = spatial('IfcBuilding', 'S6a Common Infrastructure', s6a, s6a_pl, 'Internal roads, plant boundary fence, WTG crane pads')
def poly_el(cls, name, polys, z0, h, st, sp, sp_pl, ptype='USERDEFINED', otype=None, min_area=1.0):
    items = []
    for p in polys:
        if len(p['ext']) < 3 or Polygon(p['ext']).area < min_area:
            continue
        pg = Polygon(p['ext'], p.get('holes', [])).buffer(0)
        for q in split_holes(pg):
            if q.area < 1.0:
                continue
            q = q.simplify(0.05)
            if q.is_empty or q.geom_type != 'Polygon':
                continue
            items.append(poly_solid(list(q.exterior.coords)[:-1], z0, h))
    if not items:
        return None
    paint(items, st)
    kw = {'PredefinedType': ptype} if cls not in ('IfcCivilElement', 'IfcBuildingElementProxy') else {}
    if cls == 'IfcBuildingElementProxy':
        kw = {'PredefinedType': 'USERDEFINED'}
    e = product(cls, name, shape(items), lp(sp_pl), sp, **kw)
    if otype:
        e.ObjectType = otype
    return e

poly_el('IfcCivilElement', 'S6a Internal Roads (ICR access)', F['s6a']['roads_internal'], 0.0, 0.25, S['road'], s6c, s6c_pl, otype='ROAD')
poly_el('IfcCivilElement', 'S6a Peripheral Plant Road', F['s6a']['roads_plant'], 0.0, 0.25, S['road_main'], s6c, s6c_pl, otype='ROAD')
poly_el('IfcCivilElement', 'WTG Access Roads (S6a area)', F['s6a']['roads_wtg'], 0.0, 0.22, S['road'], s6c, s6c_pl, otype='ROAD')
poly_el('IfcCivilElement', 'WTG Crane Hardstands (S6a area)', F['s6a']['crane_pads'], 0.0, 0.2, S['crane'], s6c, s6c_pl, otype='HARDSTAND')
# fence along the S6a array envelope
fence_poly = unary_union(list(zones.values())).buffer(25, join_style=2).buffer(-12, join_style=2)
fence_poly = max(getattr(fence_poly, 'geoms', [fence_poly]), key=lambda g: g.area)
ring = fence_poly.exterior.simplify(1.0)
fitems = []
cs = list(ring.coords)
for a, b2 in zip(cs[:-1], cs[1:]):
    L = math.dist(a, b2)
    if L < 0.5: continue
    fitems.append(box_solid(L, 0.08, 2.4, (a[0]+b2[0])/2, (a[1]+b2[1])/2, 0, None, ((b2[0]-a[0])/L, (b2[1]-a[1])/L, 0)))
paint(fitems, S['fence'])
fe = product('IfcRailing', 'S6a Plant Boundary Fence (chain-link 2.4 m)', shape(fitems), lp(s6c_pl), s6c, PredefinedType='USERDEFINED')
fe.ObjectType = 'FENCE'
print('fence length m', round(ring.length))

# ================================================================== PSS-10 (33/400 kV GIS) + BESS
pss10, pss10_pl = spatial('IfcBuilding', 'PSS-10 / KPS-3 - 33/400 kV GIS Pooling Substation', s6a, s6a_pl,
                          'Pooling substation for S6a (and adjoining plots) with power transformers, SVG, HF and BESS')
P10 = F['s6a']['pss10']
poly_el('IfcSlab', 'PSS-10 Switchyard Gravel Pad', [P10['compound']], 0.0, 0.15, S['gravel'], pss10, pss10_pl, ptype='BASESLAB')
cp = Polygon(P10['compound']['ext'])
cring = list(cp.exterior.coords)
fitems = []
for a, b2 in zip(cring[:-1], cring[1:]):
    L = math.dist(a, b2)
    fitems.append(box_solid(L, 0.25, 2.8, (a[0]+b2[0])/2, (a[1]+b2[1])/2, 0, None, ((b2[0]-a[0])/L, (b2[1]-a[1])/L, 0)))
paint(fitems, S['wall'])
product('IfcWall', 'PSS-10 Compound Wall', shape(fitems), lp(pss10_pl), pss10, PredefinedType='USERDEFINED').ObjectType = 'BOUNDARY WALL'

# Power transformer 400/33 kV (~250 MVA)
ptx = paint([box_solid(10.0, 5.0, 5.2, 0, 0, 0.6)], S['xfmr'])
ptx += paint([box_solid(10.4, 5.4, 0.6, 0, 0, 0.0)], S['concrete'])
ptx += paint([box_solid(0.4, 4.0, 3.8, xx, yy, 1.0) for xx in (-3, -1, 1, 3) for yy in (-3.0, 3.0)], S['radiator'])
ptx += paint([cyl(0.9, 6.5, 0, 0, 5.8), cyl(0.25, 4.0, -3.2, 1.2, 5.8), cyl(0.25, 4.0, -3.2, -1.2, 5.8)], S['panel'])
ptx += paint([C('IfcExtrudedAreaSolid', circ_prof(0.6), A3(-3.2, 0, 7.2, (0, 1, 0), (1, 0, 0)), D(0, 0, 1), 4.0)], S['xfmr'])
RM_PTX, PS_PTX = rmap(ptx)
for i, (x, y) in enumerate(P10['transformers'], 1):
    product('IfcTransformer', f'PSS-10 Power Transformer {i} (400/33 kV)', PS_PTX, lp(pss10_pl, x, y, 0, math.pi/2), pss10, PredefinedType='VOLTAGE')
gx, gy = P10['gis_hall_center']
gis = paint([box_solid(18.0, 95.0, 14.0, 0, 0, 0)], S['gis']) + paint([box_solid(19.0, 96.0, 0.6, 0, 0, 14.0)], S['roof'])
product('IfcBuildingElementProxy', 'PSS-10 400 kV GIS Hall', shape(gis), lp(pss10_pl, gx, gy, 0), pss10, PredefinedType='USERDEFINED').ObjectType = 'GIS BUILDING'
cx_, cy_ = P10['control_bldg_center']
ctrl = paint([box_solid(40, 18, 6.5, 0, 0, 0)], S['building']) + paint([box_solid(41, 19, 0.4, 0, 0, 6.5)], S['roof'])
product('IfcBuildingElementProxy', 'PSS-10 Control Room & 33 kV Switchgear Building', shape(ctrl), lp(pss10_pl, cx_, cy_, 0), pss10, PredefinedType='USERDEFINED').ObjectType = 'CONTROL BUILDING'
for i, p in enumerate(P10['svg_hf'], 1):
    pg = Polygon(p['ext']); minx, miny, maxx, maxy = pg.bounds
    # gravel pad + rows of SVG/HF equipment cabinets
    poly_el('IfcSlab', f'PSS-10 SVG/HF Yard {i} Pad', [p], 0.0, 0.15, S['gravel'], pss10, pss10_pl, ptype='BASESLAB')
    items = []
    nx = max(1, int((maxx-minx-6) // 9))
    for k in range(nx):
        xx = minx + 5 + k*9
        for yy in ((miny+maxy)/2 - 6, (miny+maxy)/2 + 6):
            items.append(box_solid(6.0, 3.0, 3.2, xx, yy, 0.15))
    paint(items, S['svg'])
    product('IfcBuildingElementProxy', f'PSS-10 SVG + Harmonic Filter Bay {i}', shape(items), lp(pss10_pl), pss10, PredefinedType='USERDEFINED').ObjectType = 'SVG / HARMONIC FILTER'

# BESS containers
bcont = paint([box_solid(12.2, 2.45, 2.9, 0, 0, 0.3)], S['bess']) + paint([box_solid(12.6, 2.8, 0.3, 0, 0, 0)], S['concrete'])
RM_BC, PS_BC = rmap(bcont)
pcs = paint([box_solid(6.1, 2.45, 2.9, 0, 0, 0.3)], S['bess_pcs']) + paint([box_solid(6.4, 2.8, 0.3, 0, 0, 0)], S['concrete'])
RM_PCS, PS_PCS = rmap(pcs)
bess_bld, bess_pl = spatial('IfcBuilding', 'BESS - PSS-10', s6a, s6a_pl, 'Battery Energy Storage System yards adjoining PSS-10')
bc_all, pcs_all = [], []
for yi, yard in enumerate(F['s6a']['bess_yards'], 1):
    pg = Polygon(yard['poly']['ext'])
    nm = 'BESS Yard %d (%s)' % (yi, 'Phase-1' if yard['layer'] == 'BESS_Ph1' else 'Phase-2 / BESS Area PSS10 39.04 acre')
    poly_el('IfcSlab', nm + ' - Gravel Pad', [yard['poly']], 0.0, 0.12, S['gravel'], bess_bld, bess_pl, ptype='BASESLAB')
    minx, miny, maxx, maxy = pg.buffer(-8).bounds
    y = miny + 2
    row = 0
    while y < maxy - 2:
        x = minx + 6.5
        col = 0
        while x < maxx - 6.5:
            if pg.buffer(-6).contains(box(x-6.5, y-1.5, x+6.5, y+1.5)):
                if col % 5 == 4:
                    e = product('IfcElectricFlowStorageDevice', f'{nm} PCS/MVT Skid R{row+1:02d}-{col+1:02d}', PS_PCS, lp(bess_pl, x, y, 0), bess_bld, PredefinedType='USERDEFINED')
                    e.ObjectType = 'PCS / MV TRANSFORMER SKID'; pcs_all.append(e)
                else:
                    e = product('IfcElectricFlowStorageDevice', f'{nm} Battery Container R{row+1:02d}-{col+1:02d}', PS_BC, lp(bess_pl, x, y, 0), bess_bld, PredefinedType='BATTERY')
                    bc_all.append(e)
            x += 14.5
            col += 1
        y += 9.0
        row += 1
make_type('IfcElectricFlowStorageDeviceType', 'BESS Battery Container 40ft', RM_BC, bc_all, 'BATTERY', {'Length_m': 12.2, 'Width_m': 2.45, 'Height_m': 2.9})
make_type('IfcElectricFlowStorageDeviceType', 'BESS PCS / MVT Skid', RM_PCS, pcs_all, 'USERDEFINED', None)
print('bess containers', len(bc_all), 'pcs', len(pcs_all))

# ================================================================== Wind farm (392 x 5.2 MW W2E, HH 120 m, RD 160 m)
wind, wind_pl = spatial('IfcBuilding', 'Wind Farm - 392 x 5.2 MW WTG (W2E)', park, park_pl,
                        'WTG 5.2 MW (W2E make), Hub height 120 m, Rotor diameter 160 m. Total wind capacity 2038.4 MW')
HH, RB = 120.0, 80.0
wt = []
wt += paint([cyl(9.0, 0.6, 0, 0, 0), cyl(3.2, 1.2, 0, 0, 0.6)], S['concrete'])
NSEG = 8
seg_h = (HH - 3.5) / NSEG
wt += paint([cyl(2.4 - (2.4-1.55)*k/(NSEG-1), seg_h + 0.02, 0, 0, 1.8 + k*seg_h) for k in range(NSEG)], S['wtg'])
wt += paint([box_solid(4.2, 13.0, 4.4, 0, 3.5, HH - 2.2)], S['wtg'])           # nacelle (rotor faces -y)
RM_WTG, PS_WTG = rmap(wt)
# rotor (hub + 3 blades) in its own map, local origin = hub centre, rotor axis = local Y
HUB = (0.0, -3.6, HH)
rt = []
rt += paint([C('IfcExtrudedAreaSolid', circ_prof(r), A3(0, 0.6 - k*1.4, 0, (0, -1, 0), (1, 0, 0)), D(0, 0, 1), 1.45) for k, r in enumerate((2.0, 1.5, 0.9))], S['wtg'])  # spinner
for k in range(3):
    ang = math.radians(90 + 120*k)
    ax = (math.cos(ang), 0.0, math.sin(ang))
    root = (2.0*ax[0], 0.0, 2.0*ax[2])
    segs_ = [(0.0, 12.0, 0.8, 3.6), (12.0, 22.0, 0.55, 3.0), (34.0, 22.0, 0.35, 2.0), (56.0, RB - 58.0, 0.2, 1.1)]
    for r0, ln, th, ch in segs_:
        o = (root[0] + ax[0]*r0, 0.0, root[2] + ax[2]*r0)
        rt += paint([C('IfcExtrudedAreaSolid', rect_prof(th, ch), A3(*o, ax, (0, 1, 0)), D(0, 0, 1), ln + 0.02)], S['wtg'])
    o = (root[0] + ax[0]*(RB-6), 0.0, root[2] + ax[2]*(RB-6))
    rt += paint([C('IfcExtrudedAreaSolid', rect_prof(0.21, 1.12), A3(*o, ax, (0, 1, 0)), D(0, 0, 1), 4.0)], S['wtg_red'])
RM_ROT, PS_ROT = rmap(rt)
rotors = []
YAW = math.radians(225 - 270)  # rotor facing the prevailing SW wind
s6a_wtg = F['s6a']['wtg']
wtgs = []
allw = list(s6a_wtg) + [w for w in F['park']['wtg'] if min(math.dist(w, q) for q in s6a_wtg) > 60]
allw.sort(key=lambda p: (-p[1], p[0]))
for i, (x, y) in enumerate(allw, 1):
    in_s6a = min(math.dist((x, y), q) for q in s6a_wtg) < 1
    e = product('IfcElectricGenerator', f'WTG-{i:03d} 5.2 MW' + (' (within S6a plot)' if in_s6a else ''), PS_WTG,
                lp(wind_pl, x, y, 0, YAW), wind, tag=f'WTG-{i:03d}', PredefinedType='USERDEFINED')
    e.ObjectType = 'WIND TURBINE GENERATOR'
    wtgs.append(e)
    r_ = product('IfcBuildingElementProxy', f'WTG-{i:03d} Rotor (3 blades, D160 m)', PS_ROT,
                 C('IfcLocalPlacement', e.ObjectPlacement, A3(*HUB)), wind, tag=f'WTG-{i:03d}', PredefinedType='USERDEFINED')
    r_.ObjectType = 'WTG ROTOR'
    rotors.append(r_)
    C('IfcRelAggregates', G(), None, None, None, e, [r_])
make_type('IfcElectricGeneratorType', 'WTG 5.2 MW W2E HH120 RD160', RM_WTG, wtgs, 'USERDEFINED',
          {'Make': 'W2E', 'Rating_MW': 5.2, 'HubHeight_m': 120.0, 'RotorDiameter_m': 160.0})
make_type('IfcBuildingElementProxyType', 'WTG Rotor 160 m (hub + 3 blades)', RM_ROT, rotors, 'USERDEFINED', {'RotorDiameter_m': 160.0, 'Blades': 3})
print('wtg', len(wtgs))

# ================================================================== 400 kV transmission
tlb, tlb_pl = spatial('IfcBuilding', '400 kV Transmission Lines (PSS to KPS)', park, park_pl, '400 kV double-circuit overhead lines')
towers = F['park']['tl_towers']; spans = F['park']['tl_spans']
nbr = {i: [] for i in range(len(towers))}
for a, b2 in spans:
    nbr[a].append(b2); nbr[b2].append(a)
tw = []
for sx in (-1, 1):
    for sy in (-1, 1):
        base, top = (sx*5.0, sy*5.0, 0.0), (sx*1.2, sy*1.2, 44.0)
        v = [top[i]-base[i] for i in range(3)]; L = math.sqrt(sum(c*c for c in v)); v = [c/L for c in v]
        tw.append(C('IfcExtrudedAreaSolid', rect_prof(0.35, 0.35), A3(*base, v, (v[2], 0, -v[0]) if abs(v[0]) > 1e-6 else (1, 0, 0)), D(0, 0, 1), L))
for zz, w in ((30.0, 26.0), (37.0, 22.0), (44.0, 18.0)):
    tw.append(box_solid(w, 1.4, 1.2, 0, 0, zz))
tw += [box_solid(2.4 - 0.7*k, 2.4 - 0.7*k, 3.0, 0, 0, 44.0 + 3*k) for k in range(3)]
for zz in (8.0, 16.0, 24.0):
    s_ = 5.0 - (5.0-1.2)*zz/44.0
    tw += [box_solid(2*s_, 0.2, 0.2, 0, yy, zz) for yy in (-s_, s_)] + [box_solid(0.2, 2*s_, 0.2, xx, 0, zz) for xx in (-s_, s_)]
paint(tw, S['tower'])
RM_TW, PS_TW = rmap(tw)
tw_el = []
for i, (x, y) in enumerate(towers):
    if nbr[i]:
        j = nbr[i][0]
        ang = math.atan2(towers[j][1]-y, towers[j][0]-x) + math.pi/2
    else:
        ang = 0.0
    e = product('IfcBuildingElementProxy', f'TL-400kV Tower {i+1:03d}', PS_TW, lp(tlb_pl, x, y, 0, ang), tlb, tag=f'TWR-{i+1:03d}', PredefinedType='USERDEFINED')
    e.ObjectType = '400 kV LATTICE TOWER'
    tw_el.append(e)
cond_items = []
for a, b2 in spans:
    (x0, y0), (x1, y1) = towers[a], towers[b2]
    L = math.dist((x0, y0), (x1, y1))
    if L < 1: continue
    ux, uy = (x1-x0)/L, (y1-y0)/L
    nx_, ny_ = -uy, ux
    for off, zz in ((-12, 30.0), (12, 30.0), (-10, 37.0), (10, 37.0), (-8, 44.0), (8, 44.0)):
        pts = []
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            sag = 9.0 * 4*t*(1-t)
            pts.append((x0 + ux*L*t + nx_*off, y0 + uy*L*t + ny_*off, zz - 0.6 - sag))
        for pa, pb in zip(pts[:-1], pts[1:]):
            dv = [pb[i]-pa[i] for i in range(3)]; dl = math.sqrt(sum(c*c for c in dv)); dv = [c/dl for c in dv]
            ref = (-dv[1], dv[0], 0.0) if abs(dv[2]) < 0.99 else (1.0, 0.0, 0.0)
            rn = math.hypot(ref[0], ref[1]) or 1.0
            cond_items.append(C('IfcExtrudedAreaSolid', circ_prof(0.12), A3(*pa, dv, (ref[0]/rn, ref[1]/rn, 0.0)), D(0, 0, 1), dl))
paint(cond_items, S['conductor'])
for i in range(0, len(cond_items), 1200):
    product('IfcCableSegment', f'400 kV Conductors (set {i//1200+1})', shape(cond_items[i:i+1200]),
            lp(tlb_pl), tlb, PredefinedType='CONDUCTORSEGMENT')
print('towers', len(tw_el), 'conductor spans', len(cond_items)//24)

# ================================================================== Pooling substations & KPS
subs, subs_pl = spatial('IfcBuilding', 'Pooling Substations (PSS) & 765/400 kV KPS', park, park_pl, '33/400 kV GIS pooling substations and 765/400 kV KPS switchyards')
pad = paint([box_solid(260, 180, 0.15)], S['gravel'])
RM_PAD, PS_PAD = rmap(pad)
for p in F['park']['pss']:
    if p['name'] == 'PSS-10':
        continue  # modelled in detail within S6a
    x, y = p['pos']
    base = lp(subs_pl, x, y, 0)
    def at(dx, dy, rot=0.0):
        return C('IfcLocalPlacement', base, A3(dx, dy, 0, None, (math.cos(rot), math.sin(rot), 0) if rot else None))
    nm = f"{p['name']} ({p['kps']}) 33/400 kV GIS"
    product('IfcSlab', f'{nm} - Switchyard Pad', PS_PAD, base, subs, PredefinedType='BASESLAB')
    product('IfcBuildingElementProxy', f'{nm} - GIS Hall', shape(paint([box_solid(95, 18, 14, 0, 0, 0)], S['gis']) + paint([box_solid(96, 19, 0.6, 0, 0, 14)], S['roof'])),
            at(10, 45), subs, PredefinedType='USERDEFINED').ObjectType = 'GIS BUILDING'
    for k, dx in enumerate((-75, -45, -15, 15), 1):
        product('IfcTransformer', f'{nm} - Power Transformer {k}', PS_PTX, at(dx, -10), subs, PredefinedType='VOLTAGE')
    product('IfcBuildingElementProxy', f'{nm} - Control Building', shape(paint([box_solid(40, 18, 6.5, 0, 0, 0)], S['building']) + paint([box_solid(41, 19, 0.4, 0, 0, 6.5)], S['roof'])),
            at(90, -50), subs, PredefinedType='USERDEFINED').ObjectType = 'CONTROL BUILDING'
    product('IfcBuildingElementProxy', f'{nm} - SVG / HF Yard', shape(paint([box_solid(6, 3, 3.2, xx, yy, 0.15) for xx in range(-100, 40, 10) for yy in (-60, -72)], S['svg'])),
            at(0, 0), subs, PredefinedType='USERDEFINED').ObjectType = 'SVG / HARMONIC FILTER'
for i, k in enumerate(F['park']['kps'], 1):
    pg = Polygon(k['ext'])
    poly_el('IfcSlab', f'KPS 765/400 kV Switchyard {i} - Gravel Pad', [k], 0.0, 0.2, S['gravel'], subs, subs_pl, ptype='BASESLAB')
    c = pg.centroid
    base = lp(subs_pl, c.x, c.y, 0)
    items = []
    for gx_ in range(-300, 301, 120):
        for gy_ in range(-200, 201, 100):
            if pg.contains(Point(c.x+gx_, c.y+gy_)):
                items += [box_solid(1.2, 1.2, 22, gx_-15, gy_, 0), box_solid(1.2, 1.2, 22, gx_+15, gy_, 0), box_solid(32, 1.0, 1.5, gx_, gy_, 22)]
    paint(items, S['tower'])
    product('IfcBuildingElementProxy', f'KPS Switchyard {i} - Gantries & Bays', shape(items), base, subs, PredefinedType='USERDEFINED').ObjectType = 'SWITCHYARD GANTRY'
    for j, dx in enumerate((-200, -120, -40, 40, 120, 200), 1):
        if pg.contains(Point(c.x+dx, c.y-260)):
            product('IfcTransformer', f'KPS Switchyard {i} - 765/400 kV ICT {j}', PS_PTX, C('IfcLocalPlacement', base, A3(dx, -260, 0)), subs, PredefinedType='VOLTAGE')
print('substations done', round(time.time()-t0, 1))

# ================================================================== Park infrastructure
infra, infra_pl = spatial('IfcBuilding', 'Park Infrastructure - Roads, Corridors, Camps', park, park_pl,
                          'Main roads with 33/400 kV TL corridors, plant roads, air-strip road, compounds, BESS of other plots')
poly_el('IfcCivilElement', 'Park Internal Plant Roads', F['park']['roads'], 0.0, 0.2, S['road_main'], infra, infra_pl, otype='ROAD', min_area=500)
poly_el('IfcCivilElement', 'TL Corridor + Main Roads', F['park']['main_corridor'], 0.0, 0.22, S['road_main'], infra, infra_pl, otype='ROAD', min_area=500)
poly_el('IfcCivilElement', 'Air Strip Road', F['park']['airstrip_road'], 0.0, 0.22, S['road_main'], infra, infra_pl, otype='ROAD')
poly_el('IfcWall', 'Camps / O&M Township / Batching Plant Compound Walls', F['park']['infra_walls'], 0.0, 2.5, S['wall'], infra, infra_pl)
poly_el('IfcGeographicElement', 'No-Go Areas', F['park']['nogo'], 0.0, 0.05, S['nogo'], infra, infra_pl, ptype='USERDEFINED', otype='NO GO AREA', min_area=1000)
bb_items = []
for k in F['park']['bess_blocks']:
    pg = Polygon(k['ext'])
    if pg.area < 30: continue
    c = pg.centroid
    mrr = pg.minimum_rotated_rectangle
    cs = list(mrr.exterior.coords)
    e1 = (cs[1][0]-cs[0][0], cs[1][1]-cs[0][1]); e2 = (cs[2][0]-cs[1][0], cs[2][1]-cs[1][1])
    if math.hypot(*e1) < math.hypot(*e2): e1, e2 = e2, e1
    Lx, Ly = math.hypot(*e1), math.hypot(*e2)
    ang = math.atan2(e1[1], e1[0])
    nx_ = max(1, int(Lx // 14.5)); ny_ = max(1, int(Ly // 6))
    for i in range(nx_):
        for j in range(ny_):
            lx = -Lx/2 + 7.25 + i*14.5; ly = -Ly/2 + 3 + j*6
            gx_ = c.x + lx*math.cos(ang) - ly*math.sin(ang); gy_ = c.y + lx*math.sin(ang) + ly*math.cos(ang)
            bb_items.append(box_solid(12.2, 2.45, 2.9, gx_, gy_, 0.0, None, (math.cos(ang), math.sin(ang), 0)))
paint(bb_items, S['bess'])
if bb_items:
    product('IfcElectricFlowStorageDevice', 'BESS Containers - other plots (indicative)', shape(bb_items), lp(infra_pl), infra, PredefinedType='BATTERY')
print('other-plot BESS containers', len(bb_items))

# park boundary fence + terrain
bpoly = Polygon(F['park']['boundary'][0]['ext'])
cs = list(bpoly.exterior.simplify(3).coords)
fitems = []
for a, b2 in zip(cs[:-1], cs[1:]):
    L = math.dist(a, b2)
    if L < 1: continue
    fitems.append(box_solid(L, 4.0, 3.0, (a[0]+b2[0])/2, (a[1]+b2[1])/2, 0, None, ((b2[0]-a[0])/L, (b2[1]-a[1])/L, 0)))
paint(fitems, S['park_fence'])
pf = product('IfcRailing', 'Khavda Plot Boundary (fence line)', shape(fitems), lp(infra_pl), infra, PredefinedType='USERDEFINED')
pf.ObjectType = 'FENCE'
minx, miny, maxx, maxy = bpoly.bounds
ter = paint([box_solid(maxx-minx+8000, maxy-miny+8000, 1.0, (minx+maxx)/2, (miny+maxy)/2, -1.02)], S['terrain'])
product('IfcGeographicElement', 'Terrain - Khavda (Great Rann of Kutch)', shape(ter), lp(park_pl), park, PredefinedType='TERRAIN')

# ================================================================== Other solar plots - indicative HSAT rows
oth, oth_pl = spatial('IfcBuilding', 'Other Solar Plots - indicative PV arrays', park, park_pl,
                      'Plots of the 15,727 MW solar park other than S6a, modelled indicatively as HSAT rows (5.5 m pitch) clipped to plot boundaries')
excl = [Polygon(p['ext'], p.get('holes', [])).buffer(0) for p in F['park']['roads'] + F['park']['main_corridor'] + F['park']['nogo'] + F['park']['infra_walls'] if len(p['ext']) > 2]
excl = [e.buffer(12) for e in excl]
excl += [Point(p['pos']).buffer(260) for p in F['park']['pss']]
excl += [Polygon(k['ext']).buffer(30) for k in F['park']['kps']]
excl += [Polygon(k['ext']).buffer(10) for k in F['park']['bess_blocks'] if len(k['ext']) > 2]
excl += [Point(w).buffer(45) for w in allw]
s6a_env = unary_union([Polygon(fence_poly.exterior).buffer(60)] + [Polygon(y['poly']['ext']).buffer(40) for y in F['s6a']['bess_yards']] + [cp.buffer(60)])
excl.append(s6a_env.convex_hull.buffer(0) if False else s6a_env)
EX = unary_union(excl)
row_prof = rect_prof(2.4, 1.0)
pitch = 5.5
nplots = 0; nstrips = 0
for pi, p in enumerate(F['park']['plots'], 1):
    pg = Polygon(p['ext'], p.get('holes', [])).buffer(-15)
    if pg.is_empty or pg.area < 20000:
        continue
    pg = pg.difference(EX)
    if pg.is_empty:
        continue
    minx, miny, maxx, maxy = pg.bounds
    items = []
    x = math.floor(minx / pitch) * pitch
    while x <= maxx:
        seg = pg.intersection(LineString([(x, miny-1), (x, maxy+1)]))
        for s_ in getattr(seg, 'geoms', [seg]):
            if s_.is_empty or s_.geom_type != 'LineString' or s_.length < 25:
                continue
            (xa, ya), (xb, yb) = s_.coords[0], s_.coords[-1]
            y0_, y1_ = min(ya, yb), max(ya, yb)
            items.append(C('IfcExtrudedAreaSolid', rect_prof(2.4, y1_-y0_), A3(x, (y0_+y1_)/2, 2.1), D(0, 0, 1), 0.04))
        x += pitch
    if not items:
        continue
    paint(items, S['module_other'])
    e = product('IfcSolarDevice', f'Solar Plot P{pi:02d} - indicative HSAT PV array', shape(items), lp(oth_pl), oth, PredefinedType='SOLARPANEL')
    gp = [{'ext': list(g.exterior.coords)[:-1], 'holes': [list(r.coords)[:-1] for r in g.interiors]}
          for g in getattr(pg.buffer(3), 'geoms', [pg.buffer(3)]) if g.area > 2000]
    poly_el('IfcGeographicElement', f'Solar Plot P{pi:02d} - array ground (indicative)', gp, 0.0, 0.03, S['plot_ground'], oth, oth_pl, ptype='USERDEFINED', otype='PV ARRAY GROUND')
    nplots += 1; nstrips += len(items)
print('other plots', nplots, 'rows', nstrips, round(time.time()-t0, 1))

# ================================================================== containment relations
for sp, els in contained.items():
    for i in range(0, len(els), 20000):
        C('IfcRelContainedInSpatialStructure', G(), None, None, None, els[i:i+20000], sp)

f.write(OUT)
print('written', OUT, round(time.time()-t0, 1), 's')
