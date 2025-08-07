import os
from flask import Flask, render_template, send_from_directory
from flask_caching import Cache
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# Initialize Flask app and cache
app = Flask(__name__)
app.config.update({
  'CACHE_TYPE':        'filesystem',
  'CACHE_DIR':         '/tmp/flask_cache',   # adjust as needed
  'CACHE_DEFAULT_TIMEOUT': 600
})
cache = Cache(app)

cache = Cache(app)

# Use a single session for all requests
session = requests.Session()
session.headers.update({'User-Agent': 'PSX Trends Monitor/1.0'})

# Helper: fetch URL
def get_url(url, **kwargs):
    resp = session.get(url, **kwargs)
    resp.raise_for_status()
    return resp

# 1. Breakouts
@cache.memoize()
def fetch_breakouts(url="https://psxbreakouts.com/"):
    resp = get_url(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    rpt = soup.find(lambda tag: tag.name == 'p' and 'Report Date' in tag.get_text())
    report_date = rpt.get_text(strip=True) if rpt else ''

    table = soup.find('table')
    headers = [th.get_text(strip=True) for th in table.thead.find_all('th')]

    data = []
    for tr in table.tbody.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all('td')]
        if cells:
            data.append(dict(zip(headers, cells)))
    return report_date, data

# 2. Price-to-Earnings
@cache.memoize()
def fetch_pe(url="https://psxbreakouts.com/psxpe"):
    resp = get_url(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    data = []
    for tr in soup.find('table').tbody.find_all('tr'):
        cols = tr.find_all('td')
        lines = list(cols[0].stripped_strings)
        if len(cols) < 5 or len(lines) < 2:
            continue
        sym, pe_comp = lines[0].upper(), lines[1]
        data.append({
            'Symbol': sym,
            'PE_Company': pe_comp,
            'Stock_PE': cols[2].get_text(strip=True),
            'Sector_PE': cols[3].get_text(strip=True),
            'Discount': cols[4].get_text(strip=True)
        })
    return data

# 3. Exponential Moving Averages
@cache.memoize()
def fetch_ema(url="https://psxbreakouts.com/psxema"):
    resp = get_url(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    data = []
    for tr in soup.find('table').tbody.find_all('tr'):
        cols = tr.find_all('td')
        lines = list(cols[0].stripped_strings)
        if len(cols) < 8 or not lines:
            continue
        sym = lines[0].upper()
        data.append({
            'Symbol': sym,
            'Current_Price': cols[2].get_text(strip=True),
            'EMA9': cols[3].get_text(strip=True),
            'EMA21': cols[4].get_text(strip=True),
            'EMA44': cols[5].get_text(strip=True),
            'EMA100': cols[6].get_text(strip=True),
            'EMA200': cols[7].get_text(strip=True)
        })
    return data

# 4. RSI & ADX Analysis
URL_RSI_ADX = "https://psxbreakouts.com/rsi-adx-analysis"
EXCLUDE_HEADERS = {"Symbol", "Sector", "Current Price", "% Change"}

@cache.memoize()
def fetch_rsi_adx():
    resp = get_url(URL_RSI_ADX)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find('table')
    if not table:
        return [], [], {}

    ths = (table.find('thead') or table).find_all('th')
    headers = [th.get_text(strip=True) for th in ths if th.get_text(strip=True) not in EXCLUDE_HEADERS]
    idx_map = [i for i, th in enumerate(ths) if th.get_text(strip=True) not in EXCLUDE_HEADERS]

    temp = {}
    for tr in table.find('tbody').find_all('tr'):
        tds = tr.find_all('td')
        sym = tds[0].get_text(strip=True).upper()
        vals = [tds[i].get_text(strip=True) for i in idx_map if i < len(tds)]
        if vals:
            temp[sym] = vals

    non_adx = [h for h in headers if not h.startswith('ADX')]
    adx = [h for h in headers if h.startswith('ADX')]
    ordered = non_adx + adx
    order_idx = [headers.index(h) for h in ordered]

    rows, rsi_map = [], {}
    for sym, vals in temp.items():
        reordered = [vals[i] for i in order_idx]
        rows.append([sym] + reordered)
        rsi_map[sym] = reordered

    return ordered, rows, rsi_map

# 5. Settlement Analysis
@cache.memoize()
def fetch_settlement(url="https://psxbreakouts.com/settlement-analysis/data?period=week&range=all&sector=all"):
    resp = get_url(url)
    payload = resp.json().get('data', [])
    result = {}
    for rec in payload:
        sym = rec.get('company_code', '').upper()
        if not sym:
            continue
        result[sym] = {
            'Settlement_Ratio_By_Volume': rec.get('avg_volume_percentage', ''),
            'Total_Settlement_Volume': rec.get('total_settlement_volume', '')
        }
    return result

# Final header order
FINAL_BASE_HEADERS = [
    'Sector','Symbol','Company','Close',
    'Daily Status','Weekly Status','Monthly Status',
    'Stock_PE','Sector_PE','Discount',
    'EMA9','EMA21','EMA44','EMA100','EMA200',
    'Total_Settlement_Volume','Settlement_Ratio_By_Volume'
]

# Serve favicon if present
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico')
app.add_url_rule('/favicon.ico', 'favicon', favicon)

@app.route('/')
def index():
    # Fetch all data in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(fetch_breakouts): 'breakouts',
            executor.submit(fetch_pe): 'pe',
            executor.submit(fetch_ema): 'ema',
            executor.submit(fetch_settlement): 'settlement',
            executor.submit(fetch_rsi_adx): 'rsi'
        }
        data = {}
        for fut in as_completed(futures):
            key = futures[fut]
            data[key] = fut.result()

    report_date, bout = data['breakouts']
    pe_map   = {r['Symbol']: r for r in data['pe']}
    ema_map  = {r['Symbol']: r for r in data['ema']}
    settlement_map = data['settlement']
    rsi_headers, _, rsi_map = data['rsi']

    all_headers = FINAL_BASE_HEADERS[:15] + rsi_headers + FINAL_BASE_HEADERS[15:]
    rows = []
    for row in bout:
        sym = row.get('Symbol', '').upper()
        if not sym:
            continue
        combined = {**row, **pe_map.get(sym, {}), **ema_map.get(sym, {}), **settlement_map.get(sym, {})}
        if sym in rsi_map:
            for i, hdr in enumerate(rsi_headers):
                combined[hdr] = rsi_map[sym][i]
        rows.append([combined.get(h, '') for h in all_headers])

    return render_template('index.html', report_date=report_date, headers=all_headers, rows=rows)

if __name__ == '__main__':
    # In production, use Gunicorn or similar WSGI server
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000), debug=False)
