import json, os, re, urllib.request, urllib.parse, ssl, io, sys, time

JSON = r"D:\mutxri-terminal\static_data\_logo_missing2.json"
OUT = r"D:\mutxri-terminal\static_data\logos_img"
RESULT = r"D:\mutxri-terminal\static_data\_logo_results_tv.json"

H = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
     'Referer':'https://www.tradingview.com/','Origin':'https://www.tradingview.com',
     'Accept':'application/json, text/plain, */*'}
UA = {'User-Agent':'Mozilla/5.0'}

def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or UA)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b''
    except Exception as e:
        return None, b''

def tv_search(text):
    url = 'https://symbol-search.tradingview.com/symbol_search/?text=' + urllib.parse.quote(text) + '&type='
    st, data = http_get(url, H)
    if st != 200:
        return []
    try:
        return json.loads(data.decode('utf-8','ignore'))
    except Exception:
        return []

def verify_png(data):
    if not data or len(data) < 500:
        return False
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return False
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.verify()
        return True
    except Exception:
        return False

def base_ticker(sym):
    s = sym
    if '.' in s:
        s = s.split('.')[0]
    return s

TV_EX = {'EGX':'EGX','NSE':'NSE','NGX':'NSENG','JSE':'JSE'}

def find_logoid(entry):
    ex = entry['exchange']
    tv_ex = TV_EX.get(ex, ex)
    bt = base_ticker(entry['sym'])
    nm = (entry.get('name') or '').strip()
    queries = []
    if bt:
        queries.append(bt)
    if nm:
        queries.append(nm[:70])
        # also try first word(s) for long names
        first = nm.split(' ')[0] if nm else ''
        if first and first.lower() != bt.lower():
            queries.append(first)
    seen = {}
    for q in queries:
        for r in tv_search(q):
            if r.get('type') != 'stock':
                continue
            sym = r.get('symbol')
            if not sym or sym in seen:
                continue
            seen[sym] = r
    cands = [r for r in seen.values() if r.get('exchange') == tv_ex]
    if not cands:
        cands = [r for r in seen.values() if (r.get('symbol') or '').upper() == bt.upper()]
    if not cands:
        return None, tv_ex
    # prefer exact symbol match
    for r in cands:
        if (r.get('symbol') or '').upper() == bt.upper():
            return r.get('logoid'), tv_ex
    return cands[0].get('logoid'), tv_ex

def filename_for(sym):
    return sym.replace('.', '_').replace(' ', '_')

def main():
    with open(JSON, encoding='utf-8') as f:
        entries = json.load(f)
    print('total entries:', len(entries))
    os.makedirs(OUT, exist_ok=True)
    results = []
    fail = []
    for i, e in enumerate(entries):
        sym = e['sym']
        fn = filename_for(sym) + '.png'
        path = os.path.join(OUT, fn)
        rec = {'sym': sym, 'found': False, 'filename': fn, 'source_url': ''}
        logoid, tv_ex = find_logoid(e)
        if logoid:
            url = 'https://s3-symbol-logo.tradingview.com/%s--600.png' % logoid
            st, data = http_get(url)
            if verify_png(data):
                with open(path, 'wb') as f:
                    f.write(data)
                rec['found'] = True
                rec['source_url'] = url
            else:
                fail.append((sym, 'TV404', logoid, tv_ex))
        else:
            fail.append((sym, 'no-logoid', None, tv_ex))
        results.append(rec)
        if (i+1) % 10 == 0:
            print('processed', i+1, '/', len(entries), flush=True)
            with open(RESULT, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=1)
        time.sleep(0.05)
    with open(RESULT, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    found = sum(1 for r in results if r['found'])
    print('FOUND', found, '/', len(results))
    print('FAILURES:')
    for f in fail:
        print('  ', f)

if __name__ == '__main__':
    main()
