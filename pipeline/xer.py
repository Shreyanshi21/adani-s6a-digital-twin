def parse_xer(p):
    t = {}; cur = None; f = None
    for line in open(p, encoding='cp1252', errors='replace'):
        parts = line.rstrip('\r\n').split('\t')
        if parts[0] == '%T': cur = parts[1]; t[cur] = []
        elif parts[0] == '%F': f = parts[1:]
        elif parts[0] == '%R': t[cur].append(dict(zip(f, parts[1:])))
    return t
