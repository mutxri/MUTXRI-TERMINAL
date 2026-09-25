#!/usr/bin/env python3
"""fill_egx_mubasher_income.py - fill the remaining EGX statement gaps from the
Mubasher English EGX page.

The existing Mubasher pull captured balance + cashflow only (its 2-row income
summary was skipped). This adds income (Gross Profit + Net Income or Loss) and
re-fetches every ACTIVE EGX common security still missing income, balance or
cashflow.

POSITIONAL parsing: a dash '-' in a column is kept as a None (a gap), never
dropped, so values stay aligned to their years. A statement is only written for
the years where its identity rows are all present, and the identity is checked
(A-L=E for balance, O+I+F=NetChange for cashflow). Figures are published in EGP
thousands and stored in absolute EGP (x 1000), matching existing files.

Only MISSING statement types are written - a fuller existing file is never
overwritten.
"""
import json, os, re, time, requests

BASE = 'static_data'
FIN = os.path.join(BASE, 'financials')
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'}

def load(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)

def collapse(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', s.lower())).strip()

def num(s):
    s = s.strip().replace(',', '').replace('\u00a0', '')
    neg = s.startswith('(') and s.endswith(')')
    s = s.strip('()')
    if not s or s == '-':
        return None
    try:
        v = float(s)
    except Exception:
        return None
    return -v if neg else v

def close(a, b):
    if a is None or b is None:
        return False
    m = max(abs(a), abs(b))
    return m == 0 or abs(a - b) / m <= 0.01

BAL = {
 'total assets': 'Total Assets',
 'total liabilities': 'Total Liabilities',
 'total liabilities & shareholders equity': 'Total Liabilities',
 'total owners equity minority interest equity': 'Total Equity',
 'total owners equity and minority interest equity': 'Total Equity',
 'total owners equity & minority interest equity': 'Total Equity',
 'total shareholders equity': 'Total Equity',
 'total equity': 'Total Equity',
 'non current assets': 'Non-current Assets',
 'current assets': 'Current Assets',
 'non current liabilities': 'Non-current Liabilities',
 'current liabilities': 'Current Liabilities',
 'cash and cash equivalents': 'Cash & Equivalents',
}
CAS = {
 'net cash flow from used in operating activities': 'Operating Cash Flow',
 'net cash flow from operating activities': 'Operating Cash Flow',
 'net cash from operating activities': 'Operating Cash Flow',
 'net cash flow from used in investing activities': 'Investing Cash Flow',
 'net cash flow from investing activities': 'Investing Cash Flow',
 'net cash from investing activities': 'Investing Cash Flow',
 'net cash flow from used in financing activities': 'Financing Cash Flow',
 'net cash flow from financing activities': 'Financing Cash Flow',
 'net cash from financing activities': 'Financing Cash Flow',
 'net change in cash and cash equivalents': 'Net Change in Cash',
 'net change in cash': 'Net Change in Cash',
 'net change in cash & cash equivalents': 'Net Change in Cash',
 'net increase decrease in cash and cash equivalents': 'Net Change in Cash',
}
INC = {
 'gross profit': 'Gross Profit',
 'net income or loss': 'Net Profit',
 'net income': 'Net Profit',
 'net profit': 'Net Profit',
}
BAL_ORDER = ['Total Assets', 'Total Liabilities', 'Total Equity', 'Non-current Assets',
             'Current Assets', 'Non-current Liabilities', 'Current Liabilities', 'Cash & Equivalents']
CAS_ORDER = ['Operating Cash Flow', 'Investing Cash Flow', 'Financing Cash Flow', 'Net Change in Cash']
INC_ORDER = ['Gross Profit', 'Net Profit']

def parse(md):
    """Positional parse: rows -> {label: [val_or_None, ...]} aligned to header years."""
    years = None
    bal, cas, inc = {}, {}, {}
    for line in md.split('\n'):
        s = line.strip()
        if not s.startswith('|') or s.startswith('|---') or s.startswith('| ---'):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        cells = [c for c in cells if not c.startswith('[](http')]
        if len(cells) < 2:
            continue
        yrs = []
        for c in cells[1:]:
            tok = c.split()[0] if c.split() else ''
            if re.fullmatch(r'\d{4}', tok):
                yrs.append(int(tok))
        if len(yrs) >= 2:
            years = yrs
            continue
        if years is None:
            continue
        lab = cells[0]
        if not lab or re.fullmatch(r'[\d,.\-()\s]+', lab):
            continue
        if collapse(lab) in ('balance sheet', 'income statement', 'cash flow'):
            continue
        n = collapse(lab)
        if n not in BAL and n not in CAS and n not in INC:
            continue
        raw = [num(c) for c in cells[1:]]
        # pad/trim to the year count (trailing empty cells after the url cell)
        if len(raw) > len(years):
            raw = raw[:len(years)]
        while len(raw) < len(years):
            raw.append(None)
        if not any(v is not None for v in raw):
            continue
        if n in BAL:
            bal.setdefault(BAL[n], raw)
        elif n in CAS:
            cas.setdefault(CAS[n], raw)
        else:
            inc.setdefault(INC[n], raw)
    return years, bal, cas, inc

def common_years(rows, labels):
    """index positions where ALL requested labels are non-None"""
    idxs = list(range(len(rows[labels[0]]))) if labels and labels[0] in rows else []
    for lab in labels[1:]:
        if lab not in rows:
            return []
        idxs = [i for i in idxs if rows[lab][i] is not None]
    return idxs

def have_file(tk, typ):
    return os.path.exists(os.path.join(FIN, f'{tk}__{typ}.json'))

def targets():
    have = {}
    for f in os.listdir(FIN):
        if not f.endswith('.json') or '__' not in f:
            continue
        k, s = f[:-5].rsplit('__', 1)
        have.setdefault(k.upper(), set()).add(s)
    out = []
    for r in load(os.path.join(BASE, 'listing_EGX.json'))['stocks']:
        if r.get('instrument') != 'common':
            continue
        tk = str(r.get('ticker') or r.get('sym') or '').upper()
        if not tk:
            continue
        ks = set()
        for fld in ('ticker', 'sym', 'code', 'short'):
            v = r.get(fld)
            if v:
                ks.add(str(v).upper())
                ks.add(str(v).upper().split('.')[0])
        got = set()
        for k in ks:
            got |= have.get(k, set())
        missi = 'income' not in got
        missb = 'balance' not in got
        missc = 'cashflow' not in got
        if not (missi or missb or missc):
            continue
        vd = str(r.get('volDate') or '')
        active = ('2026' in vd) or ('2025' in vd) or (r.get('price') is not None)
        if not active:
            continue
        out.append((tk, missi, missb, missc))
    return out

def rec_for(tk):
    for r in load(os.path.join(BASE, 'listing_EGX.json'))['stocks']:
        if str(r.get('ticker') or '').upper() == tk or str(r.get('sym') or '').upper() == tk:
            return r
    return {}

def main():
    todo = targets()
    print('ACTIVE EGX targets missing a statement:', len(todo), flush=True)
    wrote = skipped = 0
    result = {'wrote': [], 'skipped': []}
    for i, (tk, missi, missb, missc) in enumerate(todo, 1):
        url = 'https://r.jina.ai/https://english.mubasher.info/markets/EGX/stocks/%s/financial-statements' % tk
        md = None
        for attempt in range(3):
            try:
                r = requests.get(url, headers=H, timeout=70)
            except Exception:
                time.sleep(8)
                continue
            if r.status_code == 200 and len(r.text) > 6000 and 'Warning: Target URL returned error' not in r.text[:800]:
                md = r.text
                break
            time.sleep(10)
        if not md:
            skipped += 1
            result['skipped'].append([tk, 'no page'])
            print('%-10s NO PAGE' % tk, flush=True)
            time.sleep(2)
            continue
        years, bal, cas, inc = parse(md)
        if not years:
            skipped += 1
            result['skipped'].append([tk, 'no table'])
            print('%-10s NO TABLE' % tk, flush=True)
            time.sleep(2)
            continue
        rec = rec_for(tk)
        name = rec.get('name') or tk
        sym = rec.get('sym')
        keys = [tk]
        if sym:
            su = str(sym).upper()
            if su != tk:
                keys.append(su)
        else:
            keys.append(tk + '.CA')
        src = 'Mubasher (english.mubasher.info) EGX financial statements summary'
        surl = 'https://english.mubasher.info/markets/EGX/stocks/%s/financial-statements' % tk
        made = []

        if missb and all(l in bal for l in ('Total Assets', 'Total Liabilities', 'Total Equity')):
            idxs = common_years(bal, ['Total Assets', 'Total Liabilities', 'Total Equity'])
            ta, tl, te = bal['Total Assets'], bal['Total Liabilities'], bal['Total Equity']
            okidx = [i for i in idxs if close(ta[i] - tl[i], te[i])]
            present = [L for L in BAL_ORDER if L in bal]
            okidx = [i for i in okidx if all(bal[L][i] is not None for L in present)]
            if okidx:
                periods = ['FY%d' % years[i] for i in okidx]
                rows = [{'label': L, 'values': [bal[L][i] * 1000 for i in okidx]}
                        for L in BAL_ORDER if L in bal and any(bal[L][i] is not None for i in okidx)]
                for k in keys:
                    obj = {'ticker': k, 'name': name, 'currency': 'EGP', 'periods': periods, 'rows': rows,
                           'source': src, 'source_url': surl, 'asOf': periods[0], 'period': 'annual',
                           'available': True, 'statement': 'balance', 'statementTitle': 'Balance Sheet'}
                    with open(os.path.join(FIN, k + '__balance.json'), 'w', encoding='utf-8') as f:
                        json.dump(obj, f)
                made.append('balance')
        if missc and all(l in cas for l in ('Operating Cash Flow', 'Investing Cash Flow', 'Financing Cash Flow', 'Net Change in Cash')):
            idxs = common_years(cas, ['Operating Cash Flow', 'Investing Cash Flow', 'Financing Cash Flow', 'Net Change in Cash'])
            op, iv, fi, nc = cas['Operating Cash Flow'], cas['Investing Cash Flow'], cas['Financing Cash Flow'], cas['Net Change in Cash']
            okidx = [i for i in idxs if close(op[i] + iv[i] + fi[i], nc[i])]
            present = [L for L in CAS_ORDER if L in cas]
            okidx = [i for i in okidx if all(cas[L][i] is not None for L in present)]
            if okidx:
                periods = ['FY%d' % years[i] for i in okidx]
                rows = [{'label': L, 'values': [cas[L][i] * 1000 for i in okidx]}
                        for L in CAS_ORDER if L in cas and any(cas[L][i] is not None for i in okidx)]
                for k in keys:
                    obj = {'ticker': k, 'name': name, 'currency': 'EGP', 'periods': periods, 'rows': rows,
                           'source': src, 'source_url': surl, 'asOf': periods[0], 'period': 'annual',
                           'available': True, 'statement': 'cashflow', 'statementTitle': 'Cash Flow'}
                    with open(os.path.join(FIN, k + '__cashflow.json'), 'w', encoding='utf-8') as f:
                        json.dump(obj, f)
                made.append('cashflow')
        if missi and 'Net Profit' in inc:
            np_ = inc['Net Profit']
            present = [L for L in INC_ORDER if L in inc]
            idxs = [i for i in range(len(np_)) if all(inc[L][i] is not None for L in present)]
            if idxs:
                periods = ['FY%d' % years[i] for i in idxs]
                rows = [{'label': L, 'values': [inc[L][i] * 1000 for i in idxs]}
                        for L in INC_ORDER if L in inc and any(inc[L][i] is not None for i in idxs)]
                for k in keys:
                    obj = {'ticker': k, 'name': name, 'currency': 'EGP', 'periods': periods, 'rows': rows,
                           'source': src, 'source_url': surl, 'asOf': periods[0], 'period': 'annual',
                           'available': True, 'statement': 'income', 'statementTitle': 'Income Statement',
                           'source_note': 'Income summary read from the Mubasher English EGX statement page; it publishes only Gross Profit and Net Income or Loss (no revenue or cost lines), so the fuller rows stay empty.'}
                    with open(os.path.join(FIN, k + '__income.json'), 'w', encoding='utf-8') as f:
                        json.dump(obj, f)
                made.append('income')
        if made:
            wrote += 1
            result['wrote'].append([tk, made])
            print('%-10s filled %s (years %s)' % (tk, made, years), flush=True)
        else:
            skipped += 1
            result['skipped'].append([tk, 'identity failed or rows absent (bal=%s cas=%s inc=%s)' % (missb, missc, missi)])
            print('%-10s SKIP' % tk, flush=True)
        time.sleep(3)
    json.dump(result, open('_mubasher_income_result.json', 'w'), indent=1)
    print('DONE: wrote %d, skipped %d' % (wrote, skipped), flush=True)

if __name__ == '__main__':
    main()
