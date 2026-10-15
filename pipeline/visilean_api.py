"""Fetch the S6a activities from the VisiLean API: status, % complete, baseline / planned / actual dates.

usage: visilean_api.py out.json
The token is never committed. It is read, in this order, from
  1. env VL_TOKEN_ADANI
  2. env VL_TOKENS_JSON            {"adani": "<token>"}
  3. data/visilean/token.txt       (git-ignored; the token alone, or the whole API address it came in)
Without a token the step is skipped and the schedule falls back to the P6 XER.
"""
import sys, os, json, datetime, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(ROOT, 'data', 'visilean', 'token.txt')
PROJECT = os.environ.get('VL_PROJECT_ID', '8E1DC8F3-B98D-7466-372B-A885DE53F1BB')     # Adani Green Energy S6a (234 MW)
BASE = 'https://app.visilean.net/pb/PowerBiAPI/resource/powerBi/getData/visilean'
KEEP = ['taskId', 'externalId', 'taskName', 'status', 'percentComplete', 'parent',
        'baselineStartDate', 'baselineEndDate', 'plannedStartDate', 'plannedEndDate', 'actualStartDate', 'actualEndDate']


def clean(raw):
    """The token alone, even when the whole address it was handed over in was pasted."""
    tok = (raw or '').strip().strip('"').strip("'")
    if 'accessToken=' in tok:
        tok = tok.split('accessToken=', 1)[1]
    for sep in ('&', '?', '#', ' ', '\n', '\r'):
        tok = tok.split(sep, 1)[0]
    return tok


def token():
    if os.environ.get('VL_TOKEN_ADANI'):
        return clean(os.environ['VL_TOKEN_ADANI']), 'VL_TOKEN_ADANI'
    if os.environ.get('VL_TOKENS_JSON'):
        try:
            t = json.loads(os.environ['VL_TOKENS_JSON']).get('adani')
            if t: return clean(t), 'VL_TOKENS_JSON'
        except ValueError:
            pass
    if os.path.exists(TOKEN_FILE):
        t = clean(open(TOKEN_FILE, encoding='utf-8').read())
        if t: return t, 'data/visilean/token.txt'
    return None, None


def main(out):
    tok, src = token()
    if not tok:
        print('no VisiLean token (set VL_TOKEN_ADANI or create data/visilean/token.txt) - skipped, using the P6 XER only')
        if os.path.exists(out): os.remove(out)              # never link stale API data
        return
    url = f'{BASE}?accessToken={tok}&projectId={PROJECT}&type=task'
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'S6a-digital-twin'}), timeout=180).read()
    except urllib.error.HTTPError as e:
        sys.exit(f'VisiLean API refused the token from {src}: HTTP {e.code}. Check that it is the S6a project token.')
    tasks = json.loads(raw.decode('utf-8', errors='replace'))
    seen, rows = set(), []
    for t in tasks:                               # the feed repeats some tasks; taskId is unique
        k = str(t.get('taskId') or t.get('guid') or '')
        if k in seen: continue
        seen.add(k); rows.append({f: t.get(f) for f in KEEP})
    with_ext = sum(1 for r in rows if r['externalId'])
    with_base = sum(1 for r in rows if r['baselineStartDate'])
    json.dump({'fetched': datetime.datetime.now().isoformat(timespec='seconds'), 'projectId': PROJECT, 'tasks': rows},
              open(out, 'w', encoding='utf-8'), indent=0)
    print(f'VisiLean API ({src}): {len(rows)} tasks, {with_ext} with an External Id, {with_base} with baseline dates -> {out}')


if __name__ == '__main__':
    main(sys.argv[1])
