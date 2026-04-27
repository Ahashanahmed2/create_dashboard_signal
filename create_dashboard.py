"""
create_dashboard.py
✅ All Tabs with LTP + No Duplicate Date
✅ DSE Market: Sun-Thu 10AM-2:20PM (Bangladesh Time UTC+6)
✅ AI Signals (37 cols) + SWRSI + S/R + MACD + EMA 200 + Daily Buy
"""

import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="12.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI: return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name or COLLECTION_NAME]
    except: return None

# ================================
# Bangladesh Timezone Helper
# ================================
BD_TIMEZONE = timezone(timedelta(hours=6))

def get_bd_time():
    return datetime.now(BD_TIMEZONE)

def is_dse_market_open():
    now = get_bd_time()
    hour, minute, weekday = now.hour, now.minute, now.weekday()
    return (weekday in [6, 0, 1, 2, 3] and 
            ((hour == 10 and minute >= 0) or 
             (10 < hour < 14) or 
             (hour == 14 and minute <= 20)))

# ================================
# API Routes
# ================================
@app.get("/api/health")
async def health():
    col = get_mongo_collection()
    swrsi_col = get_mongo_collection("swrsi_signals") if MONGODB_URI else None
    swrsi_count = swrsi_col.count_documents({}) if swrsi_col else 0
    return {
        "status": "ok", 
        "mongodb": "connected" if col else "not configured",
        "swrsi_signals": swrsi_count,
        "dse_market": "OPEN" if is_dse_market_open() else "CLOSED",
        "bangladesh_time": get_bd_time().strftime('%Y-%m-%d %H:%M:%S')
    }

@app.get("/api/market-status")
async def market_status():
    now = get_bd_time()
    is_open = is_dse_market_open()
    close_time = now.replace(hour=14, minute=20, second=0, microsecond=0)
    time_to_close = (close_time - now).total_seconds()
    alert_10min = is_open and (0 < time_to_close <= 600)
    
    if not is_open:
        weekday = now.weekday()
        if weekday in [3, 4, 5]: next_open = "Sunday 10:00 AM"
        else: next_open = "Tomorrow 10:00 AM"
    else:
        next_open = None
    
    return {
        "is_open": is_open,
        "alert_10min": alert_10min,
        "alert_message": "⚠️ DSE CLOSING IN 10 MINUTES!" if alert_10min else "",
        "next_open": next_open,
        "bangladesh_time": now.strftime('%Y-%m-%d %H:%M:%S')
    }

@app.get("/api/dse-ltp")
async def get_dse_ltp():
    now = get_bd_time()
    if not is_dse_market_open():
        return {"status": "closed", "message": "DSE Closed"}
    
    try:
        response = requests.get("https://www.dsebd.org/dseX_share.php", 
                               headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
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
        return {"status": "live", "total_symbols": len(ltp_data), "ltp_data": ltp_data}
    except Exception as e: 
        return {"status": "error", "message": str(e)}

@app.get("/api/dates")
async def get_dates(collection: str = Query("daily_ai_signals")):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    dates = col.distinct('analysis_date')
    return sorted(dates, reverse=True)

@app.get("/api/swrsi/dates")
async def get_swrsi_dates():
    col = get_mongo_collection("swrsi_signals")
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

@app.get("/api/swrsi")
async def get_swrsi(date: str = Query(None), symbol: str = Query(None)):
    col = get_mongo_collection("swrsi_signals")
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(col.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    data = list(col.find(query, {'_id': 0}).sort('composite_score', -1))
    all_dates = sorted(col.distinct('analysis_date'), reverse=True)
    return {"signals": data, "total_signals": len(data), "available_dates": all_dates}

@app.get("/api/stats")
async def get_stats(date: str = Query(None)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(collection.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']
    pipeline = [{'$match': query}, {'$group': {'_id': None, 'total': {'$sum': 1}, 'avg_score': {'$avg': '$final_combined_score'}}}]
    result = list(collection.aggregate(pipeline))
    if result: return {k: v for k, v in result[0].items() if k != '_id'}
    return {"total": 0, "avg_score": 0}

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

@app.put("/api/update-trade")
async def update_trade(symbol: str = Query(...), date: str = Query(...), entry_price: float = Query(None), stop_loss: float = Query(None), target_price: float = Query(None)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    update_fields = {'edited': True, 'edited_at': datetime.now().isoformat()}
    if entry_price is not None: update_fields['entry_price'] = entry_price
    if stop_loss is not None: update_fields['stop_loss'] = stop_loss
    if target_price is not None: update_fields['target_price'] = target_price
    result = collection.update_one({'symbol': symbol, 'analysis_date': date}, {'$set': update_fields})
    return {"updated": result.modified_count}

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
    <title>🤖 AI Trading Signals</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 30px; background: linear-gradient(45deg, #1a1a2e, #0f3460); border-radius: 15px; margin-bottom: 20px; }
        .header h1 { font-size: 2.2em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .alert-box { background: #ff4757; color: #fff; padding: 15px; border-radius: 10px; margin: 15px 0; text-align: center; font-size: 1.3em; font-weight: bold; display: none; animation: pulse 1s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
        .tabs { display: flex; margin-bottom: 20px; background: #111; border-radius: 10px; overflow: hidden; flex-wrap: wrap; }
        .tab { flex: 1; padding: 15px; text-align: center; cursor: pointer; border-right: 1px solid #222; color: #aaa; min-width: 100px; }
        .tab:last-child { border-right: none; }
        .tab.active { background: #1a1a2e; color: #00d4ff; font-weight: bold; }
        .controls { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }
        select, input, button { padding: 10px 15px; background: #1a1a2e; color: #fff; border: 1px solid #333; border-radius: 8px; }
        button { cursor: pointer; background: #0f3460; }
        table { width: 100%; border-collapse: collapse; font-size: 0.7em; background: #111122; border-radius: 10px; overflow: hidden; }
        th { background: #1a1a2e; padding: 10px 5px; color: #00d4ff; white-space: nowrap; }
        td { padding: 5px; border-bottom: 1px solid #222; white-space: nowrap; }
        .edit-btn { background: #ffa500; color: #000; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-size: 0.7em; }
        .delete-btn { background: #ff4757; color: #fff; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-size: 0.7em; }
        .save-btn { background: #00ff88; color: #000; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-size: 0.7em; }
        .edited-badge { background: #ffa500; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px; }
        .editable-input { background: #1a1a2e; color: #fff; border: 1px solid #ffa500; padding: 3px; width: 65px; border-radius: 4px; font-size: 0.9em; }
        .signal-SB { color: #00ff88; font-weight: bold; }
        .signal-B { color: #00cc66; font-weight: bold; }
        .signal-H { color: #ffd700; }
        .signal-S { color: #ff4757; }
        .signal-SS { color: #ff0000; font-weight: bold; }
        @media (max-width: 768px) { .header h1 { font-size: 1.5em; } }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Trading Signals Dashboard</h1>
        <p id="marketStatus">Checking DSE status...</p>
    </div>
    <div id="alertBox" class="alert-box">⚠️ DSE CLOSING IN 10 MINUTES!</div>
    <div class="tabs">
        <div class="tab active" onclick="switchTab('ai_signals')">🤖 AI Signals</div>
        <div class="tab" onclick="switchTab('swrsi')">🔍 SWRSI</div>
        <div class="tab" onclick="switchTab('support')">📊 S/R</div>
        <div class="tab" onclick="switchTab('macd')">📉 MACD</div>
        <div class="tab" onclick="switchTab('ema')">📈 EMA 200</div>
        <div class="tab" onclick="switchTab('buy')">✅ Daily Buy</div>
    </div>
    <div class="controls" id="allControls">
        <label>📅 Date:</label>
        <select id="dateSelect" onchange="loadCurrentTab()"><option value="">Latest</option></select>
        <label>🔍 Symbol:</label>
        <input type="text" id="symbolSearch" onkeyup="loadCurrentTab()" style="width:120px;">
        <button onclick="loadCurrentTab()">🔄 Refresh</button>
        <span id="recordCount" style="color:#888;"></span>
    </div>
    <div style="overflow-x:auto;" id="dynamicTable"></div>

    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let dseLtpData = {};
        let editingRow = null;

        loadDates('daily_ai_signals');
        loadCurrentTab();
        checkMarketStatus();
        loadDseLtp();
        setInterval(checkMarketStatus, 60000);
        setInterval(async () => {
            const res = await fetch('/api/market-status');
            const status = await res.json();
            if (status.is_open) loadDseLtp();
        }, 60000);

        async function checkMarketStatus() {
            const res = await fetch('/api/market-status');
            const s = await res.json();
            document.getElementById('marketStatus').innerHTML = s.is_open 
                ? `🟢 DSE MARKET OPEN | ${s.bangladesh_time || ''}`
                : `🔴 DSE CLOSED | Opens ${s.next_open || 'next session'} | ${s.bangladesh_time || ''}`;
            document.getElementById('alertBox').style.display = s.alert_10min ? 'block' : 'none';
        }

        async function loadDseLtp() {
            try { 
                const r = await fetch('/api/dse-ltp'); 
                const j = await r.json(); 
                if (j.status === 'live') dseLtpData = j.ltp_data || {}; 
                else dseLtpData = {}; 
                renderCurrentTab();
            } catch(e) {}
        }

        async function loadDates(c) { 
            const r = await fetch(`/api/dates?collection=${c}`); 
            const d = await r.json(); 
            const s = document.getElementById('dateSelect'); 
            s.innerHTML = '<option value="">Latest</option>'; 
            d.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; s.appendChild(o); }); 
        }

        async function loadCurrentTab() {
            const date = document.getElementById('dateSelect').value;
            const symbol = document.getElementById('symbolSearch').value;
            
            if (currentTab === 'ai_signals') {
                let url = `/api/signals?date=${date}&limit=1000`;
                if (symbol) url += `&symbol=${symbol}`;
                const r = await fetch(url); const j = await r.json();
                currentData = j.data || [];
            } else if (currentTab === 'swrsi') {
                let url = '/api/swrsi?';
                if (date) url += `date=${date}&`;
                if (symbol) url += `symbol=${symbol}&`;
                const r = await fetch(url); const j = await r.json();
                currentData = j.signals || [];
            } else {
                const map = { support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };
                let url = `/api/generic-data?collection=${map[currentTab]}&limit=500`;
                if (date) url += `&date=${date}`;
                if (symbol) url += `&symbol=${symbol}`;
                const r = await fetch(url); const j = await r.json();
                currentData = j.data || [];
            }
            renderCurrentTab();
        }

        function renderCurrentTab() {
            if (currentTab === 'ai_signals') renderAITable();
            else if (currentTab === 'swrsi') renderSWRSITable();
            else renderGenericTable();
        }

        function switchTab(t) {
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            event.target.classList.add('active');
            currentTab = t;
            document.getElementById('symbolSearch').value = '';
            const map = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };
            loadDates(map[t]);
            loadCurrentTab();
        }

        function getSignalClass(s) {
            if (!s) return '';
            if (s.includes('STRONG BUY')) return 'signal-SB';
            if (s.includes('BUY')) return 'signal-B';
            if (s.includes('HOLD')) return 'signal-H';
            if (s.includes('STRONG SELL')) return 'signal-SS';
            if (s.includes('SELL')) return 'signal-S';
            return '';
        }

        function getLtpDisplay(symbol) {
            const ltp = dseLtpData[symbol] || null;
            return ltp ? `<span style="color:#00ff88;font-weight:bold;">${ltp.toFixed(2)}</span>` : '<span style="color:#888;">-</span>';
        }

        function startEdit(symbol, date, entry, sl, tp, i) { editingRow = { symbol, date, rowIndex: i }; renderAITable(); }
        function cancelEdit() { editingRow = null; renderAITable(); }

        async function saveEdit(symbol, date) {
            const entry = parseFloat(document.getElementById(`edit-entry-${symbol}`).value) || 0;
            const sl = parseFloat(document.getElementById(`edit-sl-${symbol}`).value) || 0;
            const tp = parseFloat(document.getElementById(`edit-tp-${symbol}`).value) || 0;
            const params = new URLSearchParams({ symbol, date, entry_price: entry, stop_loss: sl, target_price: tp });
            await fetch(`/api/update-trade?${params}`, { method: 'PUT' });
            editingRow = null;
            loadCurrentTab();
        }

        function renderAITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data</p>'; return; }
            
            let html = `<table><thead><tr>
                <th>#</th><th>Symbol</th><th>Date</th><th>Price</th><th>LTP</th><th>Sector</th>
                <th>Signal</th><th>Score</th><th>LLM</th><th>LLM%</th><th>LLM Str</th>
                <th>LLM Bias</th><th>LLM Av</th><th>XGB</th><th>XGB%</th><th>XGB Pr</th><th>AUC</th>
                <th>XGB Av</th><th>PPO</th><th>PPO%</th><th>PPO Av</th><th>PPO Wt</th>
                <th>Agentic</th><th>Ag Bias</th><th>Ag Av</th>
                <th>E Acc</th><th>E Tot</th><th>E Wave</th><th>Sub-Wave</th>
                <th>Cur Wave</th><th>W Conf</th><th>Bull?</th><th>W Pos</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>R:R</th>
                <th>Act</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const isEditing = editingRow && editingRow.symbol === r.symbol && editingRow.date === r.analysis_date;
                const isEdited = r.edited === true;
                const ltpDisplay = getLtpDisplay(r.symbol);
                const entryCell = isEditing ? `<input class="editable-input" id="edit-entry-${r.symbol}" value="${(r.entry_price||0).toFixed(2)}">` : (r.entry_price||0).toFixed(2);
                const slCell = isEditing ? `<input class="editable-input" id="edit-sl-${r.symbol}" value="${(r.stop_loss||0).toFixed(2)}">` : (r.stop_loss||0).toFixed(2);
                const tpCell = isEditing ? `<input class="editable-input" id="edit-tp-${r.symbol}" value="${(r.target_price||0).toFixed(2)}">` : (r.target_price||0).toFixed(2);
                const actionCell = isEditing 
                    ? `<button class="save-btn" onclick="saveEdit('${r.symbol}','${r.analysis_date}')">💾</button><button class="delete-btn" onclick="cancelEdit()">❌</button>`
                    : `<button class="edit-btn" onclick="startEdit('${r.symbol}','${r.analysis_date}','${r.entry_price||0}','${r.stop_loss||0}','${r.target_price||0}',${i})">✏️</button><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}')">🗑️</button>`;
                
                html += `<tr>
                    <td>${i+1}</td><td><strong>${r.symbol}${isEdited ? '<span class="edited-badge">✏️</span>' : ''}</strong></td>
                    <td>${r.analysis_date||''}</td><td>${(r.current_price||0).toFixed(2)}</td><td>${ltpDisplay}</td>
                    <td>${r.sector||''}</td><td class="${getSignalClass(r.final_signal)}">${r.final_signal||''}</td>
                    <td><strong>${(r.final_combined_score||0).toFixed(1)}</strong></td>
                    <td>${r.llm_signal||''}</td><td>${(r.llm_confidence||0).toFixed(0)}%</td>
                    <td>${r.llm_strength||''}</td><td>${r.llm_bias||''}</td><td>${r.llm_available ? '✅' : '❌'}</td>
                    <td>${r.xgb_signal||''}</td><td>${(r.xgb_confidence||0).toFixed(0)}%</td>
                    <td>${(r.xgb_prob_up||0).toFixed(3)}</td><td>${(r.xgb_auc||0).toFixed(3)}</td>
                    <td>${r.xgb_available ? '✅' : '❌'}</td>
                    <td>${r.ppo_signal||''}</td><td>${(r.ppo_confidence||0).toFixed(0)}%</td>
                    <td>${r.ppo_available ? '✅' : '❌'}</td><td>${r.ppo_weight||0}</td>
                    <td>${(r.agentic_score||0).toFixed(1)}</td><td>${r.agentic_bias||''}</td>
                    <td>${r.agentic_available ? '✅' : '❌'}</td>
                    <td>${(r.elliott_accuracy||0).toFixed(1)}%</td><td>${r.elliott_total_predictions||0}</td>
                    <td style="font-size:0.65em;">${(r.elliott_wave_count||'').substring(0,15)}</td>
                    <td style="font-size:0.65em;max-width:100px;overflow:hidden;">${(r.elliott_sub_waves||'').substring(0,20)}</td>
                    <td>${r.elliott_current_wave||''}</td><td>${(r.elliott_wave_confidence||0).toFixed(0)}%</td>
                    <td>${r.elliott_is_bullish ? '✅' : '❌'}</td><td>${r.elliott_wave_position||''}</td>
                    <td>${entryCell}</td><td>${slCell}</td><td>${tpCell}</td>
                    <td>${r.risk_reward_ratio||0}</td><td>${actionCell}</td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} signals)`;
        }

        function renderSWRSITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No SWRSI signals found</p>'; return; }
            
            let html = `<table><thead><tr>
                <th>#</th><th>Symbol</th><th>Sector</th><th>LTP</th><th>Composite Score</th>
                <th>Weekly Div</th><th>Weekly Label</th><th>Weekly Score</th>
                <th>Prev Low</th><th>Curr Low</th><th>Prev RSI</th><th>Curr RSI</th>
                <th>Price Drop%</th><th>RSI Gain</th>
                <th>Prev Week</th><th>Curr Week</th>
                <th>Daily Div</th><th>Daily Strength</th>
                <th>Daily Last RSI</th><th>Daily Prev RSI</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const ltpDisplay = getLtpDisplay(r.symbol);
                html += `<tr>
                    <td>${i+1}</td><td><strong>${r.symbol || ''}</strong></td><td>${r.sector || ''}</td>
                    <td>${ltpDisplay}</td>
                    <td>${(r.composite_score || 0).toFixed(0)}</td>
                    <td>${r.weekly_divergence || ''}</td><td>${r.weekly_strength_label || ''}</td>
                    <td>${r.weekly_strength_score || 0}</td>
                    <td>${(r.weekly_prev_low || 0).toFixed(2)}</td><td>${(r.weekly_curr_low || 0).toFixed(2)}</td>
                    <td>${(r.weekly_prev_rsi || 0).toFixed(2)}</td><td>${(r.weekly_curr_rsi || 0).toFixed(2)}</td>
                    <td>${(r.weekly_price_drop_pct || 0).toFixed(2)}%</td><td>+${(r.weekly_rsi_gain || 0).toFixed(2)}</td>
                    <td>${r.weekly_prev_date || ''}</td><td>${r.weekly_curr_date || ''}</td>
                    <td>${r.daily_divergence_type || ''}</td><td>${r.daily_divergence_strength || ''}</td>
                    <td>${(r.daily_last_rsi || 0).toFixed(2)}</td><td>${(r.daily_prev_rsi || 0).toFixed(2)}</td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
        }

        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p>No data</p>'; return; }
            
            // ✅ Filter out unwanted columns (saved_at, analysis_date, date duplicates)
            const excludeKeys = ['_id', 'saved_at', 'analysis_date', 'latest_date', 'analysis_datetime', 'saved_at','symbol','date'];
            const keys = Object.keys(currentData[0]).filter(k => !excludeKeys.includes(k) && !k.startsWith('_'));
            
            let html = `<table><thead><tr>
                <th>#</th><th>Symbol</th><th>LTP</th>
                ${keys.map(k => `<th>${k}</th>`).join('')}
                <th>🗑️</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const ltpDisplay = getLtpDisplay(r.symbol);
                html += `<tr>
                    <td>${i+1}</td>
                    <td><strong>${r.symbol || ''}</strong></td>
                    <td>${ltpDisplay}</td>
                    ${keys.map(k => `<td>${r[k]??''}</td>`).join('')}
                    <td><button class="delete-btn" onclick="deleteRecord('${r.symbol||''}','${r.analysis_date||''}','${currentTab}')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} records)`;
        }

        async function deleteRecord(symbol, date, tab = 'ai_signals') {
            if (!confirm(`Delete ${symbol}?`)) return;
            const map = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };
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
