"""Link P6 (XER) activities to IFC elements, with VisiLean status, location = P6 WBS (VisiLean location breakdown).

usage: link_schedule.py model_in.ifc schedule.xer model_out.ifc link_report.json [baseline.xer]
Adds: IfcWorkSchedule, IfcTask per WBS node (summary) and per activity, IfcTaskTime, IfcRelNests (location tree),
IfcRelAssignsToControl (tasks -> schedule), IfcRelAssignsToProcess (activity -> model elements), Pset VL_Activity.
"""
import sys, re, json, collections, datetime
import ifcopenshell, ifcopenshell.guid
sys.path.insert(0, __file__.rsplit('\\', 1)[0] if '\\' in __file__ else __file__.rsplit('/', 1)[0])
from xer import parse_xer

IFC_IN, XER, IFC_OUT, REPORT = sys.argv[1:5]
BASE = sys.argv[5] if len(sys.argv) > 5 else None
f = ifcopenshell.open(IFC_IN)
x = parse_xer(XER)
# baseline = planned dates of an earlier XER (P6 resets the planned dates of not-started activities on every update)
base = {t['task_code']: t for t in parse_xer(BASE)['TASK']} if BASE else {}
print('baseline', BASE or 'none', len(base), 'activities')
G = ifcopenshell.guid.new
C = f.create_entity

proj = x['PROJECT'][0]
data_date = (proj.get('next_data_date') or proj.get('last_recalc_date') or '').strip()
DD = datetime.datetime.strptime(data_date[:16], '%Y-%m-%d %H:%M') if data_date else datetime.datetime.now()
print('data date', DD)

W = {w['wbs_id']: w for w in x['PROJWBS']}
root_wbs = [w for w in x['PROJWBS'] if w['proj_node_flag'] == 'Y']
def wbs_chain(wid):
    out = []
    while wid in W:
        out.append(W[wid]); wid = W[wid]['parent_wbs_id']
    return list(reversed(out))
def location(wid):
    return ' > '.join(w['wbs_name'] for w in wbs_chain(wid))

T = x['TASK']
byid = {t['task_id']: t for t in T}

# ---------------------------------------------------------------- VisiLean status from P6
# Complete / Started from P6 status; not started -> "Not Committed" when all logic predecessors are satisfied, else "Not Ready".
preds = collections.defaultdict(list)
for r in x['TASKPRED']:
    preds[r['task_id']].append((r['pred_task_id'], r['pred_type']))
def vl_status(t):
    if t['status_code'] == 'TK_Complete': return 'Complete'
    if t['status_code'] == 'TK_Active': return 'Started'
    for pid, ptype in preds.get(t['task_id'], []):
        p = byid.get(pid)
        if not p: continue
        if ptype in ('PR_SS', 'PR_SF'):
            if p['status_code'] == 'TK_NotStart': return 'Not Ready'
        elif p['status_code'] != 'TK_Complete':
            return 'Not Ready'
    return 'Not Committed'
def pdate(s):
    s = (s or '').strip()
    return datetime.datetime.strptime(s[:16], '%Y-%m-%d %H:%M') if s else None
def iso(d): return d.strftime('%Y-%m-%dT%H:%M:%S') if d else None

# ---------------------------------------------------------------- model elements by block / role
ROLE_BY_NAME = [
    (r' Piles \(', 'pile'), (r' MMS Structure', 'mms'), (r' PV Modules', 'mod'),
    (r' String Inverter', 'inv'), (r' Inverter Structure', 'invs'),
    (r' IDT Station Plinth', 'plinth'), (r' IDT 13\.75', 'idt'), (r' HT Panel', 'ht'), (r' LT Panel', 'lt'),
    (r' Auxiliary Transformer', 'aux'), (r' IDT Fencing', 'fence'), (r' Array Zone', 'zone'),
]
elems = collections.defaultdict(lambda: collections.defaultdict(list))   # block -> role -> [products]
named = {}
for p in f.by_type('IfcProduct'):
    n = p.Name or ''
    named.setdefault(n, p)
    m = re.match(r'^S6a-B(\d+)-', n) or re.match(r'^S6a-ICR-(\d+) ', n) or re.match(r'^Block-(\d+) \(ICR-\d+\) Array Zone', n)
    if not m: continue
    b = int(m.group(1))
    for rx, role in ROLE_BY_NAME:
        if re.search(rx, ' ' + n if n.startswith('Block') else n):
            elems[b][role].append(p); break
print({b: {r: len(v) for r, v in d.items()} for b, d in sorted(elems.items())[:2]})

# activity (name without "Block-xx -") -> element role
ACT_ROLE = [
    (r'^Piling - MMS|^Pile Capping|^Array Earthing', 'pile'),
    (r'^MMS|^Robotic Structure|^Robot Installation|^Piling - Robotic', 'mms'),
    (r'^Module|^DC Cable|^VOC', 'mod'),
    (r'^Piling - Inverters', 'invs'),
    (r'^Inverter Installation|^LT Cable Terminations - Inverter', 'inv'),
    (r'^IDT Foundation|^HT & LT Station - Slab|^NIFPS Foundation|^BOT Foundation|^Aux Transformer Foundation', 'plinth'),
    (r'^IDT (Erection|Filtration|Testing)|^NIFPS - Installation|^HT Cable Terminations|^LT Cable Terminations - LT Panel To IDT', 'idt'),
    (r'^HT & LT Station - (Shed|Sheeting)|^HT LT Station - Staircase|^HT Panel', 'ht'),
    (r'^LT Panel|^ACDB|^SCADA', 'lt'),
    (r'^Aux Transformer', 'aux'),
    (r'^IDT Area', 'fence'),
    (r'.', 'zone'),            # cabling, pre-commissioning, commissioning, HOTO -> whole block area
]
COMMON = {   # site-wide activities -> named elements
    'PR-CI-A-010': ['S6a Plant Boundary Fence (chain-link 2.4 m)'],
    'PR-CI-A-150': ['Air Strip Road'],
    'PR-LM-A-010': ['TL Corridor + Main Roads'],
}

# ---------------------------------------------------------------- IFC schedule entities
project = f.by_type('IfcProject')[0]
ws = C('IfcWorkSchedule', G(), None, f"{proj['proj_short_name']} – S6a Schedule (P6 / VisiLean)",
       f"Linked from {XER.split('/')[-1].split(chr(92))[-1]} · data date {DD:%d %b %Y}", 'VISILEAN', proj['proj_short_name'],
       iso(datetime.datetime.now()), None, 'VisiLean status from P6 progress and logic', None, None,
       iso(pdate(proj.get('plan_start_date'))) or iso(DD), iso(pdate(proj.get('scd_end_date'))), 'PLANNED')
C('IfcRelDeclares', G(), None, None, None, project, [ws])

def val(v):
    if isinstance(v, bool): return C('IfcBoolean', v)
    if isinstance(v, (int, float)): return C('IfcReal', float(v))
    return C('IfcLabel', str(v))
def pset(name, props, obj):
    ps = C('IfcPropertySet', G(), None, name, None,
           [C('IfcPropertySingleValue', k, None, val(v), None) for k, v in props.items() if v not in (None, '')])
    C('IfcRelDefinesByProperties', G(), None, None, None, [obj], ps)

# summary tasks = WBS nodes (the VisiLean location tree)
wbs_task = {}
for w in x['PROJWBS']:
    loc = location(w['wbs_id'])
    wbs_task[w['wbs_id']] = C('IfcTask', G(), None, w['wbs_name'], loc, 'VisiLean Location', w['wbs_short_name'], None,
                              None, None, False, None, None, 'NOTDEFINED')
nest = collections.defaultdict(list)
for w in x['PROJWBS']:
    if w['parent_wbs_id'] in wbs_task: nest[w['parent_wbs_id']].append(wbs_task[w['wbs_id']])

act_task = {}
status_count = collections.Counter(); link_count = collections.Counter(); delayed_n = 0
assign = []
report = []
for t in T:
    st = vl_status(t)
    ps, pf = pdate(t['target_start_date']), pdate(t['target_end_date'])
    es, ef = pdate(t.get('early_start_date')), pdate(t.get('early_end_date'))
    ls_, lf = pdate(t.get('late_start_date')), pdate(t.get('late_end_date'))
    as_, af = pdate(t['act_start_date']), pdate(t['act_end_date'])
    pct = float(t['phys_complete_pct'] or 0)
    delayed = (st != 'Complete' and pf is not None and pf < DD) or (st in ('Not Ready', 'Not Committed') and ps is not None and ps < DD)
    delayed_n += delayed
    loc = location(t['wbs_id'])
    tt = C('IfcTaskTime', None, None, None, 'WORKTIME', None, iso(ps), iso(pf), iso(es), iso(ef), iso(ls_), iso(lf),
           None, None, None, iso(DD), None, iso(as_), iso(af), None, (pct / 100.0) if pct > 0 else None)
    is_mile = t['task_type'] in ('TT_Mile', 'TT_FinMile')
    task = C('IfcTask', G(), None, t['task_name'], loc, 'VisiLean Activity', t['task_code'], None, st, None, is_mile, None, tt,
             'CONSTRUCTION' if loc.startswith('CONSTRUCTION') else 'NOTDEFINED')
    act_task[t['task_id']] = task
    nest[t['wbs_id']].append(task)
    status_count[st] += 1
    tf = t.get('total_float_hr_cnt')
    b = base.get(t['task_code'])
    bs, bf = (pdate(b['target_start_date']), pdate(b['target_end_date'])) if b else (ps, pf)
    pset('VL_Activity', {'ActivityID': t['task_code'], 'VisiLeanLocation': loc, 'VisiLeanStatus': st,
                         'P6Status': t['status_code'].replace('TK_', ''), 'PercentComplete': pct, 'Delayed': bool(delayed),
                         'TotalFloat_days': round(float(tf) / 8.0, 1) if tf not in (None, '') else None,
                         'DataDate': DD.strftime('%d %b %Y'), 'BaselineStart': iso(bs), 'BaselineFinish': iso(bf),
                         'BaselineSource': BASE.replace(chr(92), '/').split('/')[-1] if b else 'current XER (not in baseline)'}, task)
    # ---- element links
    objs = []
    chain = [w['wbs_name'] for w in wbs_chain(t['wbs_id'])]
    blk = next((int(m.group(1)) for c in chain for m in [re.match(r'BLOCK-(\d+)', c.upper())] if m), None)
    if blk is not None:
        short = re.sub(r'^Block-\d+\s*-\s*', '', t['task_name']).strip()
        role = next(r for rx, r in ACT_ROLE if re.search(rx, short, re.I))
        objs = elems[blk].get(role) or elems[blk].get('zone') or []
        link_count[role] += 1
    elif t['task_code'] in COMMON:
        objs = [named[n] for n in COMMON[t['task_code']] if n in named]
        link_count['common'] += 1
    if objs:
        for i in range(0, len(objs), 20000):
            C('IfcRelAssignsToProcess', G(), None, None, None, objs[i:i + 20000], None, task, None)
    report.append({'id': t['task_code'], 'name': t['task_name'], 'status': st, 'location': loc, 'elements': len(objs),
                   'delayed': bool(delayed)})

for wid, kids in nest.items():
    if wid in wbs_task and kids:
        C('IfcRelNests', G(), None, None, None, wbs_task[wid], kids)
top = [wbs_task[w['wbs_id']] for w in x['PROJWBS'] if w['parent_wbs_id'] not in wbs_task]
C('IfcRelAssignsToControl', G(), None, None, None, list(wbs_task.values()) + list(act_task.values()), None, ws)

f.write(IFC_OUT)
linked = sum(1 for r in report if r['elements'])
print('activities', len(T), 'linked to elements', linked, 'status', dict(status_count), 'delayed', delayed_n)
print('links by role', dict(link_count))
json.dump({'data_date': DD.isoformat(), 'status': status_count, 'delayed': delayed_n, 'linked': linked, 'activities': report},
          open(REPORT, 'w'), indent=1)
