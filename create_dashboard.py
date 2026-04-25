"""
scripts/create_dashboard.py
✅ AI Signals (৩৮ কলাম + LTP) + Support/Resistance + MACD + EMA 200 + Daily Buy
✅ Market Close Alert (10 min before)
✅ All Tabs: Date Selector + Symbol Search + Delete
"""

import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="7.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI: return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name or COLLECTION_NAME]
    except: return None

# ================================
# Market Status API
# ================================
@app.get("/api/market-status")
async def market_status():
    now = datetime.now()
    hour, minute, weekday = now.hour, now.minute, now.weekday()
    
    is_open = (weekday <= 4 and ((hour == 10) or (10 < hour < 14) or (hour == 14 and minute <= 20)))
    
    close_time = now.replace(hour=14, minute=20, second=0, microsecond=0)
    time_to_close = (close_time - now).total_seconds()
    alert_10min = is_open and (0 < time_to_close <= 600)
    
    return {
        "is_open": is_open,
        "alert_10min": alert_10min,
        "alert_message": "⚠️ MARKET CLOSING IN 10 MINUTES! Review your positions." if alert_10min else "",
        "timestamp": now.isoformat()
    }

# ================================
# DSE Live LTP API
# ================================
@app.get("/api/dse-ltp")
async def get_dse_ltp():
    now = datetime.now()
    hour, minute, weekday = now.hour, now.minute, now.weekday()
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
# AI Signals APIs
# ================================
@app.get("/api/health")
async def health():
    col = get_mongo_collection()
    return {"status": "ok", "mongodb": "connected" if col else "not configured"}

@app.get("/api/dates")
async def get_dates(collection: str = Query("daily_ai_signals")):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    dates = col.distinct('analysis_date')
    return sorted(dates, reverse=True)

@app.get("/api/signals")
async def get_signals(date: str = Query(None), signal: str = Query(None), symbol: str = Query(None), min_score: float = Query(0), limit: int = Query(1000)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(collection.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']
    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}
    cursor = collection.find(query, {'_id': 0}).sort('final_combined_score', -1).limit(limit)
    return {"data": list(cursor)}

@app.get("/api/stats")
async def get_stats(date: str = Query(None)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(collection.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']
    pipeline = [{'$match': query}, {'$group': {'_id': None, 'total': {'$sum': 1}, 'avg_score': {'$avg': '$final_combined_score'}, 'buy_count': {'$sum': {'$cond': [{'$regexFind': {'input': '$final_signal', 'regex': 'BUY'}}, 1, 0]}}, 'sell_count': {'$sum': {'$cond': [{'$regexFind': {'input': '$final_signal', 'regex': 'SELL'}}, 1, 0]}}}}]
    result = list(collection.aggregate(pipeline))
    if result: return {k: v for k, v in result[0].items() if k != '_id'}
    return {"total": 0, "avg_score": 0, "buy_count": 0, "sell_count": 0}

@app.get("/api/generic-data")
async def get_generic_data(collection: str = Query(...), date: str = Query(None), symbol: str = Query(None), limit: int = Query(500)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date: query['analysis_date'] = date
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    data = list(col.find(query, {'_id': 0}).limit(limit))
    return {"data": data}

@app.delete("/api/delete-signal")
async def delete_signal(collection: str = Query("daily_ai_signals"), symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    result = col.delete_one({'symbol': symbol, 'analysis_date': date})
    return {"deleted": result.deleted_count}

# ================================
# HTML Dashboard
# ================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Trading Signals Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 30px; background: linear-gradient(45deg, #1a1a2e, #0f3460); border-radius: 15px; margin-bottom: 20px; }
        .header h1 { font-size: 2.2em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .alert-box { background: #ff4757; color: #fff; padding: 15px; border-radius: 10px; margin: 15px 0; text-align: center; font-size: 1.3em; font-weight: bold; display: none; animation: pulse 1s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
        .tabs { display: flex; margin-bottom: 20px; background: #111; border-radius: 10px; overflow: hidden; }
        .tab { flex: 1; padding: 15px; text-align: center; cursor: pointer; border-right: 1px solid #222; color: #aaa; }
        .tab:last-child { border-right: none; }
        .tab.active { background: #1a1a2e; color: #00d4ff; font-weight: bold; }
        .controls { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }
        select, input, button { padding: 10px 15px; background: #1a1a2e; color: #fff; border: 1px solid #333; border-radius: 8px; }
        button { cursor: pointer; background: #0f3460; }
        table { width: 100%; border-collapse: collapse; font-size: 0.75em; background: #111122; border-radius: 10px; overflow: hidden; }
        th { background: #1a1a2e; padding: 10px 6px; color: #00d4ff; white-space: nowrap; }
        td { padding: 6px; border-bottom: 1px solid #222; white-space: nowrap; }
        .delete-btn { background: #ff4757; color: #fff; border: none; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 0.7em; }
        .signal-SB { color: #00ff88; font-weight: bold; }
        .signal-B { color: #00cc66; font-weight: bold; }
        .signal-H { color: #ffd700; }
        .signal-S { color: #ff4757; }
        .signal-SS { color: #ff0000; font-weight: bold; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Trading Signals Dashboard</h1>
        <p id="marketStatus">Checking market status...</p>
    </div>
    
    <div id="alertBox" class="alert-box">⚠️ MARKET CLOSING IN 10 MINUTES! Review your positions.</div>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('ai_signals')">🤖 AI Signals (38 cols)</div>
        <div class="tab" onclick="switchTab('support')">📊 Support/Resistance</div>
        <div class="tab" onclick="switchTab('macd')">📉 MACD</div>
        <div class="tab" onclick="switchTab('ema')">📈 EMA 200</div>
        <div class="tab" onclick="switchTab('buy')">✅ Daily Buy</div>
    </div>

    <div class="controls">
        <label>📅 Date:</label>
        <select id="dateSelect" onchange="loadCurrentTab()"><option value="">Latest</option></select>
        <label>🔍 Symbol:</label>
        <input type="text" id="symbolSearch" placeholder="Symbol..." onkeyup="loadCurrentTab()" style="width:120px;">
        <button onclick="loadCurrentTab()">🔄 Refresh</button>
        <span id="recordCount" style="color:#888;"></span>
    </div>

    <div style="overflow-x:auto;" id="dynamicTable"></div>

    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let dseLtpData = {};

        // Initialize
        loadDates('daily_ai_signals');
        loadCurrentTab();
        checkMarketStatus();
        loadDseLtp();
        
        // Check every 60 seconds
        setInterval(checkMarketStatus, 60000);
        setInterval(loadDseLtp, 60000);
        setInterval(() => { if (currentTab === 'ai_signals') renderTable(); }, 60000);

        async function checkMarketStatus() {
            const res = await fetch('/api/market-status');
            const status = await res.json();
            
            if (status.is_open) {
                document.getElementById('marketStatus').innerHTML = '<span style="color:#00ff88;">🟢 MARKET OPEN</span>';
            } else {
                document.getElementById('marketStatus').innerHTML = '<span style="color:#ff4757;">🔴 MARKET CLOSED</span>';
            }
            
            const alertBox = document.getElementById('alertBox');
            alertBox.style.display = status.alert_10min ? 'block' : 'none';
        }

        async function loadDseLtp() {
            try {
                const res = await fetch('/api/dse-ltp');
                const json = await res.json();
                if (json.status === 'live') dseLtpData = json.ltp_data || {};
                else dseLtpData = {};
                if (currentTab === 'ai_signals') renderTable();
            } catch(e) {}
        }

        async function loadDates(collection) {
            const res = await fetch(`/api/dates?collection=${collection}`);
            const dates = await res.json();
            const s = document.getElementById('dateSelect');
            s.innerHTML = '<option value="">Latest</option>';
            dates.forEach(d => { const o = document.createElement('option'); o.value = d; o.textContent = d; s.appendChild(o); });
        }

        async function loadCurrentTab() {
            const date = document.getElementById('dateSelect').value;
            const symbol = document.getElementById('symbolSearch').value;
            
            if (currentTab === 'ai_signals') {
                let url = `/api/signals?date=${date}&limit=1000`;
                if (symbol) url += `&symbol=${symbol}`;
                const res = await fetch(url); const json = await res.json();
                currentData = json.data || [];
                renderTable();
                document.getElementById('recordCount').textContent = `(${currentData.length} signals)`;
            } else {
                const map = { support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };
                let url = `/api/generic-data?collection=${map[currentTab]}&limit=500`;
                if (date) url += `&date=${date}`;
                if (symbol) url += `&symbol=${symbol}`;
                const res = await fetch(url); const json = await res.json();
                currentData = json.data || [];
                renderGenericTable();
                document.getElementById('recordCount').textContent = `(${currentData.length} records)`;
            }
        }

        async function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            currentTab = tab;
            document.getElementById('symbolSearch').value = '';
            const map = { ai_signals: 'daily_ai_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };
            loadDates(map[tab]);
            loadCurrentTab();
        }

        function getSignalClass(signal) {
            if (!signal) return '';
            if (signal.includes('STRONG BUY')) return 'signal-SB';
            if (signal.includes('BUY') && !signal.includes('STRONG')) return 'signal-B';
            if (signal.includes('HOLD')) return 'signal-H';
            if (signal.includes('STRONG SELL')) return 'signal-SS';
            if (signal.includes('SELL') && !signal.includes('STRONG')) return 'signal-S';
            return '';
        }

        function renderTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data found</p>'; return; }
            
            let html = `<table><thead><tr>
                <th>#</th><th>Symbol</th><th>Date</th><th>Price</th><th>LTP</th><th>Sector</th>
                <th>Final Signal</th><th>Score</th><th>LLM</th><th>LLM%</th><th>LLM Str</th>
                <th>LLM Bias</th><th>LLM Avail</th><th>XGB</th><th>XGB%</th><th>XGB Prob</th><th>AUC</th>
                <th>XGB Avail</th><th>PPO</th><th>PPO%</th><th>PPO Avail</th><th>PPO Wt</th>
                <th>Agentic</th><th>Agentic Bias</th><th>Agentic Avail</th>
                <th>Elliott Acc</th><th>Elliott Total</th><th>Elliott Wave</th><th>Sub-Waves</th>
                <th>Current Wave</th><th>Wave Conf</th><th>Bullish?</th><th>Wave Pos</th>
                <th>Models</th><th>Entry</th><th>SL</th><th>TP</th><th>R:R</th><th>🗑️</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const ltp = dseLtpData[r.symbol] || null;
                const ltpDisplay = ltp ? `<span style="color:#00ff88;font-weight:bold;">${ltp.toFixed(2)}</span>` : '<span style="color:#888;">-</span>';
                
                html += `<tr>
                    <td>${i + 1}</td>
                    <td><strong>${r.symbol}</strong></td>
                    <td>${r.analysis_date || r.date || ''}</td>
                    <td>${(r.current_price || 0).toFixed(2)}</td>
                    <td>${ltpDisplay}</td>
                    <td>${r.sector || 'N/A'}</td>
                    <td class="${getSignalClass(r.final_signal)}">${r.final_signal || 'N/A'}</td>
                    <td><strong>${(r.final_combined_score || 0).toFixed(1)}</strong></td>
                    <td>${r.llm_signal || 'N/A'}</td>
                    <td>${(r.llm_confidence || 0).toFixed(0)}%</td>
                    <td>${r.llm_strength || 'N/A'}</td>
                    <td>${r.llm_bias || 'N/A'}</td>
                    <td>${r.llm_available ? '✅' : '❌'}</td>
                    <td>${r.xgb_signal || 'N/A'}</td>
                    <td>${(r.xgb_confidence || 0).toFixed(0)}%</td>
                    <td>${(r.xgb_prob_up || 0).toFixed(3)}</td>
                    <td>${(r.xgb_auc || 0).toFixed(3)}</td>
                    <td>${r.xgb_available ? '✅' : '❌'}</td>
                    <td>${r.ppo_signal || 'N/A'}</td>
                    <td>${(r.ppo_confidence || 0).toFixed(0)}%</td>
                    <td>${r.ppo_available ? '✅' : '❌'}</td>
                    <td>${r.ppo_weight || 0}</td>
                    <td>${(r.agentic_score || 0).toFixed(1)}</td>
                    <td>${r.agentic_bias || 'N/A'}</td>
                    <td>${r.agentic_available ? '✅' : '❌'}</td>
                    <td>${(r.elliott_accuracy || 0).toFixed(1)}%</td>
                    <td>${r.elliott_total_predictions || 0}</td>
                    <td style="font-size:0.7em;">${r.elliott_wave_count || 'N/A'}</td>
                    <td style="font-size:0.65em;max-width:150px;overflow:hidden;text-overflow:ellipsis;">${r.elliott_sub_waves || 'N/A'}</td>
                    <td>${r.elliott_current_wave || 'N/A'}</td>
                    <td>${(r.elliott_wave_confidence || 0).toFixed(0)}%</td>
                    <td>${r.elliott_is_bullish ? '✅' : '❌'}</td>
                    <td>${r.elliott_wave_position || 'N/A'}</td>
                    <td>${r.model_availability || 'N/A'}</td>
                    <td>${(r.entry_price || 0).toFixed(2)}</td>
                    <td>${(r.stop_loss || 0).toFixed(2)}</td>
                    <td>${(r.target_price || 0).toFixed(2)}</td>
                    <td>${r.risk_reward_ratio || 0}</td>
                    <td><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
        }

        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data found</p>'; return; }
            
            const keys = Object.keys(currentData[0]).filter(k => k !== '_id');
            let html = `<table><thead><tr>${keys.map(k => `<th>${k}</th>`).join('')}<th>🗑️</th></tr></thead><tbody>`;
            currentData.forEach(r => {
                html += '<tr>' + keys.map(k => `<td>${r[k]??''}</td>`).join('');
                html += `<td><button class="delete-btn" onclick="deleteRecord('${r.symbol||''}','${r.analysis_date||''}','${currentTab}')">🗑️</button></td></tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
        }

        async function deleteRecord(symbol, date, tab = 'ai_signals') {
            if (!confirm(`Delete ${symbol} from ${date}?`)) return;
            const map = { ai_signals: 'daily_ai_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };
            await fetch(`/api/delete-signal?collection=${map[tab]}&symbol=${symbol}&date=${date}`, { method: 'DELETE' });
            loadCurrentTab();
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)