"""
scripts/create_dashboard.py
FastAPI + MongoDB Dashboard for AI Trading Signals
✅ All Collections: AI Signals, Support/Resistance, MACD, EMA 200, Daily Buy
✅ DSE Live LTP Fetching
"""

import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals" # ডিফল্ট

app = FastAPI(title="AI Trading Signals Dashboard", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI: return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name or COLLECTION_NAME]
    except: return None

# ================================
# Existing AI Signal APIs (unchanged)
# ================================
@app.get("/api/health")
async def health():
    col = get_mongo_collection()
    status = "connected" if col is not None else "not configured"
    return {"status": "ok", "mongodb": status}

@app.get("/api/dates")
async def get_dates():
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    dates = collection.distinct('analysis_date')
    return sorted(dates, reverse=True)

@app.get("/api/signals")
async def get_signals(date: str = Query(None), signal: str = Query(None), min_score: float = Query(0), limit: int = Query(500), offset: int = Query(0)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(collection.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']
    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}
    total = collection.count_documents(query)
    cursor = collection.find(query, {'_id': 0}).sort('final_combined_score', -1).skip(offset).limit(limit)
    data = list(cursor)
    return {"total": total, "count": len(data), "offset": offset, "limit": limit, "data": data}

@app.get("/api/stats")
async def get_stats(date: str = Query(None)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(collection.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']
    pipeline = [{'$match': query}, {'$group': {'_id': None, 'total': {'$sum': 1}, 'avg_score': {'$avg': '$final_combined_score'}, 'max_score': {'$max': '$final_combined_score'}, 'buy_count': {'$sum': {'$cond': [{'$regexFind': {'input': '$final_signal', 'regex': 'BUY'}}, 1, 0]}}, 'sell_count': {'$sum': {'$cond': [{'$regexFind': {'input': '$final_signal', 'regex': 'SELL'}}, 1, 0]}}}}]
    result = list(collection.aggregate(pipeline))
    if result: return {k: v for k, v in result[0].items() if k != '_id'}
    return {"total": 0, "avg_score": 0, "max_score": 0, "buy_count": 0, "sell_count": 0}

# ================================
# NEW APIs for Other Collections
# ================================
@app.get("/api/support-resistance")
async def get_support_resistance(symbol: str = Query(None)):
    collection = get_mongo_collection("support_resistance")
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if symbol: query['symbol'] = symbol
    data = list(collection.find(query, {'_id': 0}).limit(100))
    return {"count": len(data), "data": data}

@app.get("/api/macd-signals")
async def get_macd_signals():
    collection = get_mongo_collection("macd_signals")
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    data = list(collection.find({}, {'_id': 0}).limit(100))
    return {"count": len(data), "data": data}

@app.get("/api/ema-200")
async def get_ema_200():
    collection = get_mongo_collection("ema_200_signals")
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    data = list(collection.find({}, {'_id': 0}).limit(100))
    return {"count": len(data), "data": data}

@app.get("/api/daily-buy")
async def get_daily_buy():
    collection = get_mongo_collection("daily_buy_signals")
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    data = list(collection.find({}, {'_id': 0}).limit(100))
    return {"count": len(data), "data": data}

# ================================
# DSE Live LTP API
# ================================
@app.get("/api/dse-ltp")
async def get_dse_ltp():
    """DSE থেকে লাইভ LTP স্ক্র্যাপ করে রিটার্ন করে"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    weekday = now.weekday()
    is_open = (weekday <= 4 and ((hour == 10) or (10 < hour < 14) or (hour == 14 and minute <= 20)))
    if not is_open:
        return {"status": "closed", "message": "Market Closed", "timestamp": now.isoformat()}
    try:
        response = requests.get("https://www.dsebd.org/dseX_share.php", headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        table = soup.find('table')
        ltp_data = {}
        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    symbol = cols[0].text.strip()
                    ltp = cols[1].text.strip().replace(',', '')
                    try: ltp_data[symbol] = float(ltp)
                    except: continue
        return {"status": "live", "market": "OPEN", "total_symbols": len(ltp_data), "ltp_data": ltp_data, "timestamp": now.isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ================================
# ROOT HTML (Upgraded with Tabs)
# ================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Trading Signals</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 30px; background: linear-gradient(45deg, #1a1a2e, #0f3460); border-radius: 15px; margin-bottom: 20px; }
        .header h1 { font-size: 2.5em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .tabs { display: flex; margin-bottom: 20px; background: #111; border-radius: 10px; overflow: hidden; }
        .tab { flex: 1; padding: 15px; text-align: center; cursor: pointer; border-right: 1px solid #222; color: #aaa; }
        .tab:last-child { border-right: none; }
        .tab.active { background: #1a1a2e; color: #00d4ff; font-weight: bold; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-card { background: #111122; border: 1px solid #222; border-radius: 10px; padding: 20px; text-align: center; }
        .stat-card h3 { color: #888; font-size: 0.9em; }
        .stat-card .value { font-size: 2em; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; font-size: 0.8em; background: #111122; border-radius: 10px; overflow: hidden; }
        th { background: #1a1a2e; padding: 12px; color: #00d4ff; }
        td { padding: 8px; border-bottom: 1px solid #222; }
        button { padding: 10px 15px; background: #0f3460; color: #fff; border: none; border-radius: 8px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="header"><h1>🤖 AI Trading Signals</h1><p id="marketStatus">Checking market status...</p></div>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('ai_signals')">🤖 AI Signals</div>
        <div class="tab" onclick="switchTab('support')">📊 Support/Resistance</div>
        <div class="tab" onclick="switchTab('macd')">📉 MACD</div>
        <div class="tab" onclick="switchTab('ema')">📈 EMA 200</div>
        <div class="tab" onclick="switchTab('buy')">✅ Daily Buy</div>
    </div>

    <div id="tab-ai_signals">
        <div class="stats">
            <div class="stat-card"><h3>📊 Total</h3><div class="value" id="statTotal">-</div></div>
            <div class="stat-card" style="border-left:3px solid #00ff88;"><h3>🟢 Buy</h3><div class="value" id="statBuy">-</div></div>
            <div class="stat-card" style="border-left:3px solid #ff4757;"><h3>🔴 Sell</h3><div class="value" id="statSell">-</div></div>
            <div class="stat-card"><h3>📈 Avg Score</h3><div class="value" id="statAvg">-</div></div>
        </div>
        <div class="controls">
            <label>📅 Date:</label>
            <select id="dateSelect" onchange="loadData(this.value)"><option value="">Latest</option></select>
            <label>📈 Signal:</label>
            <select id="signalFilter" onchange="renderTable()"><option value="">All</option><option value="BUY">Buy</option><option value="SELL">Sell</option></select>
            <button onclick="loadData()">🔄 Refresh</button>
        </div>
        <h2>📋 Signals <span id="tableCount"></span></h2>
        <div style="overflow-x:auto;" id="dynamicTable"></div>
    </div>

    <div id="tab-support" style="display:none;"><h2>📊 Support/Resistance</h2><div id="supportTable"></div></div>
    <div id="tab-macd" style="display:none;"><h2>📉 MACD Signals</h2><div id="macdTable"></div></div>
    <div id="tab-ema" style="display:none;"><h2>📈 EMA 200</h2><div id="emaTable"></div></div>
    <div id="tab-buy" style="display:none;"><h2>✅ Daily Buy</h2><div id="buyTable"></div></div>

    <script>
        let currentData = [];
        async function loadDates() {
            const res = await fetch('/api/dates'); const dates = await res.json();
            const s = document.getElementById('dateSelect');
            s.innerHTML = '<option value="">Latest</option>';
            dates.forEach(d => { const o = document.createElement('option'); o.value = d; o.textContent = d; s.appendChild(o); });
        }
        async function loadData(date = '') {
            const url = date ? `/api/signals?date=${date}&limit=1000` : '/api/signals?limit=1000';
            const res = await fetch(url); const json = await res.json();
            currentData = json.data || [];
            document.getElementById('statTotal').textContent = currentData.length;
            document.getElementById('statBuy').textContent = currentData.filter(r=>r.final_signal?.includes('BUY')).length;
            document.getElementById('statSell').textContent = currentData.filter(r=>r.final_signal?.includes('SELL')).length;
            document.getElementById('statAvg').textContent = (currentData.reduce((s,r)=>s+(r.final_combined_score||0),0)/currentData.length||0).toFixed(1);
            renderAiTable();
        }
        function renderAiTable() {
            const div = document.getElementById('dynamicTable');
            if(!currentData.length) { div.innerHTML = "No data"; return; }
            let html = '<table><thead><tr><th>Symbol</th><th>Date</th><th>Price</th><th>Signal</th><th>Score</th><th>LLM</th><th>XGB</th><th>Entry</th><th>SL</th><th>TP</th></tr></thead><tbody>';
            currentData.forEach(r => {
                html += `<tr><td>${r.symbol}</td><td>${r.analysis_date||''}</td><td>${r.current_price||0}</td><td>${r.final_signal||''}</td><td>${r.final_combined_score||0}</td><td>${r.llm_signal||''}</td><td>${r.xgb_signal||''}</td><td>${r.entry_price||0}</td><td>${r.stop_loss||0}</td><td>${r.target_price||0}</td></tr>`;
            });
            html += '</tbody></table>'; div.innerHTML = html;
        }
        async function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('[id^="tab-"]').forEach(d => d.style.display = 'none');
            document.getElementById('tab-' + tab).style.display = 'block';
            if(tab === 'ai_signals') { loadData(); }
            else if(tab === 'support') { loadGeneric('/api/support-resistance', 'supportTable'); }
            else if(tab === 'macd') { loadGeneric('/api/macd-signals', 'macdTable'); }
            else if(tab === 'ema') { loadGeneric('/api/ema-200', 'emaTable'); }
            else if(tab === 'buy') { loadGeneric('/api/daily-buy', 'buyTable'); }
        }
        async function loadGeneric(url, divId) {
            const res = await fetch(url); const json = await res.json();
            const data = json.data || [];
            let html = `<table><thead><tr>${Object.keys(data[0]||{}).map(k=>`<th>${k}</th>`).join('')}</tr></thead><tbody>`;
            data.forEach(r => { html += '<tr>' + Object.values(r).map(v => `<td>${v??''}</td>`).join('') + '</tr>'; });
            html += '</tbody></table>';
            document.getElementById(divId).innerHTML = html;
        }
        loadDates(); loadData();
    </script>
</body>
</html>
"""
def get_signal_class(signal):
    if not signal: return ''
    if 'STRONG BUY' in signal: return 'signal-SB'
    elif 'BUY' in signal: return 'signal-B'
    elif 'HOLD' in signal: return 'signal-H'
    elif 'STRONG SELL' in signal: return 'signal-SS'
    elif 'SELL' in signal: return 'signal-S'
    return ''

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)