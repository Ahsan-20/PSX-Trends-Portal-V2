import os
from flask import Flask, render_template, send_from_directory
import requests
from bs4 import BeautifulSoup

# Define paths for templates and static assets

app = Flask(__name__)

# 1. Breakouts
def fetch_breakouts(url="https://psxbreakouts.com/"):
    resp = requests.get(url); resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rpt = soup.find(lambda tag: tag.name == 'p' and 'Report Date' in tag.get_text())
    report_date = rpt.get_text(strip=True) if rpt else ''

    table = soup.find('table')
    global breakout_headers
    breakout_headers = [th.get_text(strip=True) for th in table.thead.find_all('th')]

    data = []
    for tr in table.tbody.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all('td')]
        if cells:
            data.append(dict(zip(breakout_headers, cells)))
    return report_date, data

# 2. Price-to-Earnings
def fetch_pe(url="https://psxbreakouts.com/psxpe"):
    resp = requests.get(url); resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    data = []
    for tr in soup.find('table').tbody.find_all('tr'):
        cols = tr.find_all('td')
        lines = list(cols[0].stripped_strings)
        if len(cols) < 5 or len(lines) < 2:
            continue
        symbol, pe_company = lines[0].upper(), lines[1]
        data.append({
            'Symbol': symbol,
            'PE_Company': pe_company,
            'Stock_PE': cols[2].get_text(strip=True),
            'Sector_PE': cols[3].get_text(strip=True),
            'Discount': cols[4].get_text(strip=True)
        })
    return data

# 3. Exponential Moving Averages
def fetch_ema(url="https://psxbreakouts.com/psxema"):
    resp = requests.get(url); resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    data = []
    for tr in soup.find('table').tbody.find_all('tr'):
        cols = tr.find_all('td')
        lines = list(cols[0].stripped_strings)
        if len(cols) < 8 or not lines:
            continue
        symbol = lines[0].upper()
        data.append({
            'Symbol': symbol,
            'Current_Price': cols[2].get_text(strip=True),
            'EMA9': cols[3].get_text(strip=True),
            'EMA21': cols[4].get_text(strip=True),
            'EMA44': cols[5].get_text(strip=True),
            'EMA100': cols[6].get_text(strip=True),
            'EMA200': cols[7].get_text(strip=True),
        })
    return data

# 4. RSI & ADX Analysis
URL_RSI_ADX = "https://psxbreakouts.com/rsi-adx-analysis"
EXCLUDE_HEADERS = {"Symbol", "Sector", "Current Price", "% Change"}

def fetch_rsi_adx():
    resp = requests.get(URL_RSI_ADX); resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        return [], [], {}

    thead = table.find("thead")
    ths = thead.find_all("th") if thead else table.find_all("tr")[0].find_all("th")

    all_headers, all_idx_map = [], []
    for idx, th in enumerate(ths):
        txt = th.get_text(strip=True)
        if txt not in EXCLUDE_HEADERS:
            all_headers.append(txt)
            all_idx_map.append(idx)

    temp_map = {}
    for tr in table.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        symbol = tds[0].get_text(strip=True).upper()
        values = [tds[i].get_text(strip=True) for i in all_idx_map if i < len(tds)]
        if values:
            temp_map[symbol] = values

    non_adx = [h for h in all_headers if not h.startswith("ADX")]
    adx = [h for h in all_headers if h.startswith("ADX")]
    new_headers = non_adx + adx
    reorder_idx = [all_headers.index(h) for h in new_headers]

    rows, rsi_map = [], {}
    for symbol, vals in temp_map.items():
        reordered_vals = [vals[i] for i in reorder_idx]
        rows.append([symbol] + reordered_vals)
        rsi_map[symbol] = reordered_vals

    return new_headers, rows, rsi_map

# 5. Settlement Analysis
def fetch_settlement(url="https://psxbreakouts.com/settlement-analysis/data?period=week&range=all&sector=all"):
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}); resp.raise_for_status()
    payload = resp.json().get("data", [])

    settlement_map = {}
    for rec in payload:
        sym = rec.get("company_code", "").upper()
        if not sym:
            continue
        settlement_map[sym] = {
            'Settlement_Ratio_By_Volume': rec.get('avg_volume_percentage', ''),
            'Total_Settlement_Volume': rec.get('total_settlement_volume', '')
        }
    return settlement_map

# Final header order
FINAL_BASE_HEADERS = [
    'Sector','Symbol','Company','Close',
    'Daily Status','Weekly Status','Monthly Status',
    'Stock_PE','Sector_PE','Discount',
    'EMA9','EMA21','EMA44','EMA100','EMA200',
    'Total_Settlement_Volume','Settlement_Ratio_By_Volume'
]

# Serve favicon.ico if present
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico')
app.add_url_rule('/favicon.ico', 'favicon', favicon)

@app.route('/')
def index():
    report_date, bout = fetch_breakouts()
    pe_map = {r['Symbol']: r for r in fetch_pe()}
    ema_map = {r['Symbol']: r for r in fetch_ema()}
    settlement_map = fetch_settlement()
    rsi_headers, rsi_rows, rsi_map = fetch_rsi_adx()

    all_headers = FINAL_BASE_HEADERS[:15] + rsi_headers + FINAL_BASE_HEADERS[15:]

    rows = []
    for row in bout:
        sym = row.get('Symbol', '').upper()
        if not sym:
            continue
        combined = row.copy()
        combined.update(pe_map.get(sym, {}))
        combined.update(ema_map.get(sym, {}))
        combined.update(settlement_map.get(sym, {}))
        if sym in rsi_map:
            for i, hdr in enumerate(rsi_headers):
                combined[hdr] = rsi_map[sym][i]
        rows.append([combined.get(h, '') for h in all_headers])

    return render_template('index.html', report_date=report_date, headers=all_headers, rows=rows)

if __name__ == "__main__":
    app.run(debug=True) 