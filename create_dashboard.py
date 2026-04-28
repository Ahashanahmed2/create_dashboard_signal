"""
create_dashboard.py
✅ All Tabs with LTP + No Duplicate Date - FIXED
✅ DSE Market: Sun-Thu 10AM-2:20PM (Bangladesh Time UTC+6)
✅ AI Signals (37 cols) + SWRSI + S/R + MACD + EMA 200 + Daily Buy
✅ Historical dates for ALL tabs - FIXED date matching
✅ LTP Alert Modal with symbol selector + condition
✅ Delete All by Date + Edit buttons
✅ UptimeRobot HEAD endpoint
"""

import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="15.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI: return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name or COLLECTION_NAME]
    except Exception as e:
        print(f"MongoDB Connection Error: {e}")
        return None

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
@app.api_route("/head", methods=["GET", "HEAD"])
async def uptime_robot_head():
    return Response(content="OK", status_code=200, headers={"Cache-Control": "no-cache", "X-Health-Status": "healthy"})

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
    """Get all unique dates from a collection"""
    col = get_mongo_collection(collection)
    if col is None: 
        return JSONResponse({"error": f"MongoDB not configured for {collection}"}, status_code=500)
    
    try:
        dates_set = set()
        
        # Check all possible date fields
        for field in ['analysis_date', 'date', 'latest_date', 'signal_date']:
            try:
                field_dates = col.distinct(field)
                dates_set.update([d for d in field_dates if d])
            except:
                pass
        
        all_dates = sorted(list(dates_set), reverse=True)
        print(f"📅 {collection}: Found {len(all_dates)} dates")  # Debug log
        return all_dates
    except Exception as e:
        print(f"❌ Error getting dates for {collection}: {e}")
        return []

@app.get("/api/collection-symbols")
async def get_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    """Get unique symbols from a collection, optionally filtered by date"""
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": f"Collection {collection} not found"}, status_code=500)
    
    query = {}
    if date:
        query['$or'] = [
            {'analysis_date': date},
            {'date': date},
            {'latest_date': date}
        ]
    
    try:
        symbols = col.distinct('symbol', query)
        symbols = [s for s in symbols if s]  # Remove empty/null
        return sorted(symbols)
    except Exception as e:
        print(f"Error getting symbols: {e}")
        return []

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
    if date: 
        query['analysis_date'] = date
    else:
        latest = list(collection.find({'analysis_date': {'$exists': True, '$ne': None, '$ne': ''}}).sort('analysis_date', -1).limit(1))
        if latest and latest[0].get('analysis_date'):
            query['analysis_date'] = latest[0]['analysis_date']
    
    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}
    
    cursor = collection.find(query, {'_id': 0}).sort('final_combined_score', -1).limit(limit)
    data = list(cursor)
    return {"data": data}

@app.get("/api/swrsi")
async def get_swrsi(date: str = Query(None), symbol: str = Query(None)):
    col = get_mongo_collection("swrsi_signals")
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date: 
        query['analysis_date'] = date
    else:
        latest = list(col.find({'analysis_date': {'$exists': True}}).sort('analysis_date', -1).limit(1))
        if latest and latest[0].get('analysis_date'):
            query['analysis_date'] = latest[0]['analysis_date']
    
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    data = list(col.find(query, {'_id': 0}).sort('composite_score', -1))
    return {"signals": data, "total_signals": len(data), "available_dates": sorted(col.distinct('analysis_date'), reverse=True)}

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
    """Get data from generic collections with PROPER date handling"""
    col = get_mongo_collection(collection)
    if col is None: 
        return JSONResponse({"error": f"Collection {collection} not found"}, status_code=500)
    
    query = {}
    
    if date:
        # IMPORTANT: Build query with all possible date fields
        date_conditions = []
        for field in ['analysis_date', 'date', 'latest_date', 'signal_date']:
            date_conditions.append({field: date})
        query['$or'] = date_conditions
    
    if symbol: 
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    try:
        # Debug: print the query
        print(f"🔍 Querying {collection} with: {query}")
        
        data = list(col.find(query, {'_id': 0}).limit(limit))
        print(f"📊 Found {len(data)} records in {collection} for date={date}")
        
        return {"data": data}
    except Exception as e:
        print(f"❌ Error in generic-data for {collection}: {e}")
        return {"data": [], "error": str(e)}

@app.delete("/api/delete-signal")
async def delete_signal(collection: str = Query("daily_ai_signals"), symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    # Try all possible date fields
    for field in ['analysis_date', 'date', 'latest_date', 'signal_date']:
        result = col.delete_one({'symbol': symbol, field: date})
        if result.deleted_count > 0:
            return {"deleted": result.deleted_count}
    
    return {"deleted": 0}

@app.delete("/api/delete-all-by-date")
async def delete_all_by_date(collection: str = Query(...), date: str = Query(...)):
    """Delete ALL records for a specific date in a collection"""
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    total = 0
    # Delete from all possible date fields
    for field in ['analysis_date', 'date', 'latest_date', 'signal_date']:
        result = col.delete_many({field: date})
        total += result.deleted_count
    
    return {"deleted": total, "collection": collection, "date": date}

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
    <title>🤖 AI Trading Signals Dashboard v15</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 20px; background: linear-gradient(45deg, #1a1a2e, #0f3460); border-radius: 15px; margin-bottom: 20px; border: 1px solid #1a3a5c; }
        .header h1 { font-size: 2em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .alert-box { background: #ff4757; color: #fff; padding: 10px; border-radius: 10px; margin: 10px 0; text-align: center; font-size: 1.1em; font-weight: bold; display: none; animation: pulse 1s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
        .tabs { display: flex; margin-bottom: 15px; background: #111; border-radius: 10px; overflow: hidden; flex-wrap: wrap; border: 1px solid #222; }
        .tab { flex: 1; padding: 12px 8px; text-align: center; cursor: pointer; border-right: 1px solid #222; color: #aaa; min-width: 80px; font-size: 0.85em; transition: all 0.3s; }
        .tab:last-child { border-right: none; }
        .tab.active { background: #1a1a2e; color: #00d4ff; font-weight: bold; }
        .tab:hover { background: #1a1a2e; }
        .controls { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; background: #111; padding: 10px; border-radius: 10px; border: 1px solid #222; }
        select, input, button { padding: 8px 12px; background: #1a1a2e; color: #fff; border: 1px solid #333; border-radius: 6px; font-size: 0.85em; }
        button { cursor: pointer; background: #0f3460; transition: all 0.2s; }
        button:hover { background: #1a4a7a; }
        .delete-all-btn { background: #ff4757; color: #fff; font-weight: bold; margin-left: auto; }
        .delete-all-btn:hover { background: #ff2840; }
        .alert-config-btn { background: #ffa500; color: #000; font-weight: bold; }
        .alert-config-btn:hover { background: #ffb732; }
        .alert-active-indicator { display: inline-block; width: 8px; height: 8px; background: #ff4757; border-radius: 50%; margin-right: 5px; animation: pulse 1s infinite; }
        table { width: 100%; border-collapse: collapse; font-size: 0.65em; background: #111122; border-radius: 10px; overflow: hidden; border: 1px solid #222; }
        th { background: #1a1a2e; padding: 8px 4px; color: #00d4ff; white-space: nowrap; font-size: 0.9em; position: sticky; top: 0; z-index: 10; }
        td { padding: 4px; border-bottom: 1px solid #222; white-space: nowrap; }
        tr:hover { background: #1a1a2e40; }
        .edit-btn { background: #ffa500; color: #000; border: none; padding: 3px 6px; border-radius: 3px; cursor: pointer; font-size: 0.7em; margin: 1px; }
        .delete-btn { background: #ff4757; color: #fff; border: none; padding: 3px 6px; border-radius: 3px; cursor: pointer; font-size: 0.7em; margin: 1px; }
        .save-btn { background: #00ff88; color: #000; border: none; padding: 3px 6px; border-radius: 3px; cursor: pointer; font-size: 0.7em; margin: 1px; }
        .edited-badge { background: #ffa500; color: #000; padding: 1px 4px; border-radius: 8px; font-size: 0.6em; margin-left: 3px; }
        .editable-input { background: #1a1a2e; color: #fff; border: 1px solid #ffa500; padding: 2px; width: 55px; border-radius: 3px; font-size: 0.8em; }
        .signal-SB { color: #00ff88; font-weight: bold; }
        .signal-B { color: #00cc66; font-weight: bold; }
        .signal-H { color: #ffd700; }
        .signal-S { color: #ff4757; }
        .signal-SS { color: #ff0000; font-weight: bold; }
        .ltp-alert-row { animation: ltpBlink 0.6s infinite; }
        @keyframes ltpBlink { 0%,100% { background: #ff475730; } 50% { background: #ff475760; } }
        .ltp-above { color: #00ff88 !important; font-weight: bold; }
        .ltp-below { color: #ff4757 !important; font-weight: bold; }
        /* Modal Styles */
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; }
        .modal.open { display: flex; }
        .modal-content { background: #1a1a2e; padding: 25px; border-radius: 15px; max-width: 500px; width: 90%; border: 2px solid #ffa500; max-height: 80vh; overflow-y: auto; }
        .modal-content h3 { color: #ffa500; margin-bottom: 20px; font-size: 1.2em; text-align: center; }
        .modal-content label { display: block; margin: 12px 0 5px; color: #aaa; font-size: 0.9em; }
        .modal-content select, .modal-content input { width: 100%; padding: 10px; margin-bottom: 10px; }
        .modal-buttons { display: flex; gap: 10px; margin-top: 20px; }
        .modal-buttons button { flex: 1; padding: 12px; }
        .save-alert-btn { background: #00ff88; color: #000; font-weight: bold; }
        .cancel-alert-btn { background: #666; }
        .remove-alert-btn { background: #ff4757; color: #fff; padding: 5px 10px; font-size: 0.8em; width: auto; }
        .current-alerts { margin-top: 15px; background: #0f3460; padding: 10px; border-radius: 8px; }
        .current-alerts h4 { color: #ffa500; margin-bottom: 8px; font-size: 0.9em; }
        .alert-item { display: flex; justify-content: space-between; align-items: center; background: #1a1a2e; padding: 8px; margin: 5px 0; border-radius: 5px; font-size: 0.8em; }
        .alert-item span { color: #ffa500; }
        .debug-info { font-size: 0.7em; color: #666; margin-top: 10px; padding: 8px; background: #111; border-radius: 5px; }
        @media (max-width: 768px) { .header h1 { font-size: 1.3em; } .controls { flex-direction: column; } }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Trading Signals Dashboard v15</h1>
        <p id="marketStatus" style="font-size:0.85em;margin-top:5px;">Checking DSE status...</p>
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
    
    <div class="controls">
        <label>📅 Date:</label>
        <select id="dateSelect" onchange="onDateChange()"><option value="">Latest</option></select>
        <label>🔍 Symbol:</label>
        <input type="text" id="symbolSearch" onkeyup="loadCurrentTab()" style="width:100px;">
        <button onclick="loadCurrentTab()">🔄 Refresh</button>
        <button class="alert-config-btn" onclick="openAlertModal()">🔔 Configure Alerts</button>
        <button class="delete-all-btn" onclick="deleteAllByDate()">🗑️ Delete All (Date)</button>
        <span id="recordCount" style="color:#888;margin-left:5px;font-size:0.8em;"></span>
    </div>
    
    <!-- Alert Modal -->
    <div id="alertModal" class="modal">
        <div class="modal-content">
            <h3>🔔 Configure LTP Alerts</h3>
            <label>📋 Select Symbol:</label>
            <select id="alertSymbolSelect">
                <option value="">-- Choose Symbol --</option>
            </select>
            <label>📊 Condition:</label>
            <select id="alertCondition">
                <option value="above">LTP উপরে গেলে Alert</option>
                <option value="below">LTP নিচে গেলে Alert</option>
            </select>
            <label>💰 Threshold Price:</label>
            <input type="number" id="alertThresholdPrice" placeholder="Enter price..." step="0.01">
            <div class="modal-buttons">
                <button class="save-alert-btn" onclick="addAlertRule()">➕ Add Alert</button>
                <button class="cancel-alert-btn" onclick="closeAlertModal()">Cancel</button>
            </div>
            <div class="current-alerts" id="currentAlertsSection" style="display:none;">
                <h4>📋 Active Alerts:</h4>
                <div id="currentAlertsList"></div>
            </div>
        </div>
    </div>
    
    <div id="alertStatusBar" style="background:#0f3460;padding:6px 12px;border-radius:6px;margin-bottom:8px;display:none;color:#ffa500;font-size:0.8em;"></div>
    
    <div style="overflow-x:auto;max-height:65vh;" id="dynamicTable"></div>
    
    <div class="debug-info" id="debugInfo"></div>

    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let dseLtpData = {};
        let editingRow = null;
        let alertRules = []; // Array of {symbol, condition, threshold}

        const COLLECTION_MAP = { 
            ai_signals: 'daily_ai_signals', 
            swrsi: 'swrsi_signals', 
            support: 'support_resistance', 
            macd: 'macd_signals', 
            ema: 'ema_200_signals', 
            buy: 'daily_buy_signals' 
        };

        // Initialize
        loadDates(COLLECTION_MAP[currentTab]);
        loadCurrentTab();
        checkMarketStatus();
        loadDseLtp();
        loadAlertRules();
        
        // Refresh intervals
        setInterval(checkMarketStatus, 60000);
        setInterval(async () => {
            const res = await fetch('/api/market-status');
            const status = await res.json();
            if (status.is_open) loadDseLtp();
        }, 60000);
        setInterval(loadDseLtp, 300000);

        // ===== ALERT SYSTEM =====
        function loadAlertRules() {
            const saved = localStorage.getItem('ltpAlertRules_v15');
            if (saved) {
                try { alertRules = JSON.parse(saved); } catch(e) { alertRules = []; }
            }
            updateAlertStatusBar();
        }

        function saveAlertRules() {
            localStorage.setItem('ltpAlertRules_v15', JSON.stringify(alertRules));
            updateAlertStatusBar();
            renderCurrentTab();
        }

        function updateAlertStatusBar() {
            const bar = document.getElementById('alertStatusBar');
            if (alertRules.length > 0) {
                bar.style.display = 'block';
                bar.innerHTML = `<span class="alert-active-indicator"></span> <strong>${alertRules.length} Alert(s) Active:</strong> ` + 
                    alertRules.map(r => `${r.symbol} ${r.condition === 'above' ? '>' : '<'} ${r.threshold}`).join(' | ');
            } else {
                bar.style.display = 'none';
            }
        }

        function openAlertModal() {
            document.getElementById('alertModal').classList.add('open');
            loadAlertSymbols();
            renderCurrentAlerts();
        }

        function closeAlertModal() {
            document.getElementById('alertModal').classList.remove('open');
        }

        async function loadAlertSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTION_MAP[currentTab];
            const select = document.getElementById('alertSymbolSelect');
            select.innerHTML = '<option value="">-- Choose Symbol --</option>';
            
            try {
                let url = `/api/collection-symbols?collection=${encodeURIComponent(collection)}`;
                if (date) url += `&date=${encodeURIComponent(date)}`;
                const r = await fetch(url);
                const symbols = await r.json();
                
                if (Array.isArray(symbols)) {
                    symbols.forEach(sym => {
                        const opt = document.createElement('option');
                        opt.value = sym;
                        opt.textContent = sym;
                        select.appendChild(opt);
                    });
                }
            } catch(e) {
                console.error('Load symbols error:', e);
            }
        }

        function renderCurrentAlerts() {
            const section = document.getElementById('currentAlertsSection');
            const list = document.getElementById('currentAlertsList');
            
            if (alertRules.length === 0) {
                section.style.display = 'none';
                return;
            }
            
            section.style.display = 'block';
            list.innerHTML = alertRules.map((rule, i) => `
                <div class="alert-item">
                    <span>🔔 ${rule.symbol} ${rule.condition === 'above' ? '↑ উপরে' : '↓ নিচে'} ${rule.threshold}</span>
                    <button class="remove-alert-btn" onclick="removeAlertRule(${i})">✕ Remove</button>
                </div>
            `).join('');
        }

        function addAlertRule() {
            const symbol = document.getElementById('alertSymbolSelect').value;
            const condition = document.getElementById('alertCondition').value;
            const threshold = parseFloat(document.getElementById('alertThresholdPrice').value);
            
            if (!symbol) { alert('Please select a symbol'); return; }
            if (!threshold || isNaN(threshold)) { alert('Please enter a valid threshold price'); return; }
            
            // Remove existing rule for same symbol
            alertRules = alertRules.filter(r => r.symbol !== symbol);
            
            // Add new rule
            alertRules.push({ symbol, condition, threshold });
            
            // Save and update
            saveAlertRules();
            renderCurrentAlerts();
            
            // Clear inputs
            document.getElementById('alertSymbolSelect').value = '';
            document.getElementById('alertThresholdPrice').value = '';
            
            // Reload table to show alerts
            renderCurrentTab();
        }

        function removeAlertRule(index) {
            alertRules.splice(index, 1);
            saveAlertRules();
            renderCurrentAlerts();
            renderCurrentTab();
        }

        function getLtpAlertStatus(symbol) {
            if (!alertRules.length) return null;
            
            const ltp = dseLtpData[symbol] || null;
            if (ltp === null) return null;
            
            // Check all rules for this symbol
            for (const rule of alertRules) {
                if (rule.symbol === symbol) {
                    if (rule.condition === 'above' && ltp > rule.threshold) return 'above';
                    if (rule.condition === 'below' && ltp < rule.threshold) return 'below';
                }
            }
            return null;
        }

        // ===== DATE & DATA FUNCTIONS =====
        async function checkMarketStatus() {
            try {
                const res = await fetch('/api/market-status');
                const s = await res.json();
                document.getElementById('marketStatus').innerHTML = s.is_open 
                    ? `🟢 DSE MARKET OPEN | ${s.bangladesh_time || ''}`
                    : `🔴 DSE CLOSED | Opens ${s.next_open || 'next session'} | ${s.bangladesh_time || ''}`;
                document.getElementById('alertBox').style.display = s.alert_10min ? 'block' : 'none';
            } catch(e) {}
        }

        async function loadDseLtp() {
            try { 
                const r = await fetch('/api/dse-ltp'); 
                const j = await r.json(); 
                if (j.status === 'live') {
                    dseLtpData = j.ltp_data || {};
                    renderCurrentTab();
                }
            } catch(e) {}
        }

        async function loadDates(collection) {
            try {
                const r = await fetch(`/api/dates?collection=${encodeURIComponent(collection)}`); 
                const dates = await r.json(); 
                const select = document.getElementById('dateSelect'); 
                const currentValue = select.value;
                select.innerHTML = '<option value="">Latest</option>'; 
                
                if (Array.isArray(dates) && dates.length > 0) {
                    dates.forEach(date => { 
                        if (date) {
                            const option = document.createElement('option'); 
                            option.value = date; 
                            option.textContent = date; 
                            select.appendChild(option); 
                        }
                    });
                }
                
                if (currentValue && Array.from(select.options).some(o => o.value === currentValue)) {
                    select.value = currentValue;
                }
                
                document.getElementById('debugInfo').textContent = 
                    `📅 Collection: ${collection} | Dates: ${dates.length} | Tab: ${currentTab}`;
            } catch(e) {
                console.error('Load dates error:', e);
            }
        }

        function onDateChange() {
            loadCurrentTab();
        }

        async function loadCurrentTab() {
            const date = document.getElementById('dateSelect').value;
            const symbol = document.getElementById('symbolSearch').value;
            
            try {
                if (currentTab === 'ai_signals') {
                    let url = '/api/signals?limit=1000';
                    if (date) url += `&date=${encodeURIComponent(date)}`;
                    if (symbol) url += `&symbol=${encodeURIComponent(symbol)}`;
                    const r = await fetch(url); 
                    const j = await r.json();
                    currentData = j.data || [];
                } else if (currentTab === 'swrsi') {
                    let url = '/api/swrsi?';
                    if (date) url += `date=${encodeURIComponent(date)}&`;
                    if (symbol) url += `symbol=${encodeURIComponent(symbol)}&`;
                    const r = await fetch(url); 
                    const j = await r.json();
                    currentData = j.signals || [];
                } else {
                    const collection = COLLECTION_MAP[currentTab];
                    let url = `/api/generic-data?collection=${encodeURIComponent(collection)}&limit=500`;
                    if (date) url += `&date=${encodeURIComponent(date)}`;
                    if (symbol) url += `&symbol=${encodeURIComponent(symbol)}`;
                    const r = await fetch(url); 
                    const j = await r.json();
                    currentData = j.data || [];
                }
                
                const dateInfo = date || 'Latest';
                document.getElementById('debugInfo').textContent = 
                    `📊 Tab: ${currentTab} | Date: ${dateInfo} | Records: ${currentData.length}`;
            } catch(e) {
                console.error('Load data error:', e);
                currentData = [];
            }
            
            renderCurrentTab();
        }

        function renderCurrentTab() {
            if (currentTab === 'ai_signals') renderAITable();
            else if (currentTab === 'swrsi') renderSWRSITable();
            else renderGenericTable();
        }

        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            currentTab = tabName;
            document.getElementById('symbolSearch').value = '';
            
            const collection = COLLECTION_MAP[tabName];
            loadDates(collection);
            loadCurrentTab();
        }

        function getSignalClass(signal) {
            if (!signal) return '';
            if (signal.includes('STRONG BUY')) return 'signal-SB';
            if (signal.includes('BUY')) return 'signal-B';
            if (signal.includes('HOLD')) return 'signal-H';
            if (signal.includes('STRONG SELL')) return 'signal-SS';
            if (signal.includes('SELL')) return 'signal-S';
            return '';
        }

        function getLtpDisplay(symbol) {
            const ltp = dseLtpData[symbol] || null;
            const alertStatus = getLtpAlertStatus(symbol);
            
            if (!ltp) return '<span style="color:#888;">-</span>';
            
            let cssClass = '';
            let arrow = '';
            if (alertStatus === 'above') {
                cssClass = 'ltp-above';
                arrow = ' ↑';
            } else if (alertStatus === 'below') {
                cssClass = 'ltp-below';
                arrow = ' ↓';
            }
            
            return `<span class="${cssClass}" style="font-weight:bold;">${ltp.toFixed(2)}${arrow}</span>`;
        }

        function startEdit(symbol, date, entry, sl, tp, index) { 
            editingRow = { symbol, date, rowIndex: index }; 
            renderCurrentTab(); 
        }
        
        function cancelEdit() { 
            editingRow = null; 
            renderCurrentTab(); 
        }

        async function saveEdit(symbol, date) {
            const safeId = symbol.replace(/[^a-zA-Z0-9]/g, '_');
            const entryEl = document.getElementById(`edit-entry-${safeId}`);
            const slEl = document.getElementById(`edit-sl-${safeId}`);
            const tpEl = document.getElementById(`edit-tp-${safeId}`);
            
            const entry = entryEl ? parseFloat(entryEl.value) || 0 : 0;
            const sl = slEl ? parseFloat(slEl.value) || 0 : 0;
            const tp = tpEl ? parseFloat(tpEl.value) || 0 : 0;
            
            const params = new URLSearchParams({ 
                symbol, date, 
                entry_price: entry, 
                stop_loss: sl, 
                target_price: tp 
            });
            
            try {
                await fetch(`/api/update-trade?${params}`, { method: 'PUT' });
                editingRow = null;
                loadCurrentTab();
            } catch(e) {
                alert('Save failed: ' + e.message);
            }
        }

        async function deleteAllByDate() {
            const date = document.getElementById('dateSelect').value;
            if (!date) {
                alert('⚠️ Please select a date first!');
                return;
            }
            
            const collection = COLLECTION_MAP[currentTab];
            if (!confirm(`⚠️ DELETE ALL records for ${date}\\nCollection: ${collection}\\n\\nThis cannot be undone!`)) return;
            
            try {
                const r = await fetch(`/api/delete-all-by-date?collection=${encodeURIComponent(collection)}&date=${encodeURIComponent(date)}`, { method: 'DELETE' });
                const result = await r.json();
                alert(`✅ Deleted ${result.deleted} records for ${date}`);
                loadDates(collection);
                loadCurrentTab();
            } catch(e) {
                alert('Delete failed: ' + e.message);
            }
        }

        function renderAITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { 
                div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data for selected date</p>'; 
                document.getElementById('recordCount').textContent = '(0 signals)';
                return; 
            }
            
            let html = `<table><thead><tr>
                <th>#</th><th>Symbol</th><th>Date</th><th>Price</th><th>LTP</th><th>Sector</th>
                <th>Signal</th><th>Score</th><th>LLM</th><th>LLM%</th><th>LLM Str</th>
                <th>LLM Bias</th><th>LLM Av</th><th>XGB</th><th>XGB%</th><th>XGB Pr</th><th>AUC</th>
                <th>XGB Av</th><th>PPO</th><th>PPO%</th><th>PPO Av</th><th>PPO Wt</th>
                <th>Agentic</th><th>Ag Bias</th><th>Ag Av</th>
                <th>E Acc</th><th>E Tot</th><th>E Wave</th><th>Sub-Wave</th>
                <th>Cur Wave</th><th>W Conf</th><th>Bull?</th><th>W Pos</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>R:R</th>
                <th>✏️ Act</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const safeId = (r.symbol || '').replace(/[^a-zA-Z0-9]/g, '_');
                const isEditing = editingRow && editingRow.symbol === r.symbol;
                const isEdited = r.edited === true;
                const ltpDisplay = getLtpDisplay(r.symbol);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const alertRowClass = (alertStatus === 'above' || alertStatus === 'below') ? 'ltp-alert-row' : '';
                
                const entryCell = isEditing 
                    ? `<input class="editable-input" id="edit-entry-${safeId}" value="${(r.entry_price||0).toFixed(2)}">` 
                    : (r.entry_price||0).toFixed(2);
                const slCell = isEditing 
                    ? `<input class="editable-input" id="edit-sl-${safeId}" value="${(r.stop_loss||0).toFixed(2)}">` 
                    : (r.stop_loss||0).toFixed(2);
                const tpCell = isEditing 
                    ? `<input class="editable-input" id="edit-tp-${safeId}" value="${(r.target_price||0).toFixed(2)}">` 
                    : (r.target_price||0).toFixed(2);
                
                const actionCell = isEditing 
                    ? `<button class="save-btn" onclick="saveEdit('${r.symbol}','${r.analysis_date}')">💾Save</button>
                       <button class="delete-btn" onclick="cancelEdit()">❌Cancel</button>`
                    : `<button class="edit-btn" onclick="startEdit('${r.symbol}','${r.analysis_date}','${r.entry_price||0}','${r.stop_loss||0}','${r.target_price||0}',${i})">✏️Edit</button>
                       <button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}','ai_signals')">🗑️</button>`;
                
                html += `<tr class="${alertRowClass}">
                    <td>${i+1}</td>
                    <td><strong>${r.symbol}${isEdited ? '<span class="edited-badge">✏️</span>' : ''}${alertStatus ? ' 🔔' : ''}</strong></td>
                    <td>${r.analysis_date||''}</td>
                    <td>${(r.current_price||0).toFixed(2)}</td>
                    <td>${ltpDisplay}</td>
                    <td>${r.sector||''}</td>
                    <td class="${getSignalClass(r.final_signal)}">${r.final_signal||''}</td>
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
                    <td style="font-size:0.6em;">${(r.elliott_wave_count||'').substring(0,12)}</td>
                    <td style="font-size:0.6em;max-width:80px;overflow:hidden;">${(r.elliott_sub_waves||'').substring(0,15)}</td>
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
            if (!currentData.length) { 
                div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No SWRSI signals for selected date</p>'; 
                document.getElementById('recordCount').textContent = '(0 signals)';
                return; 
            }
            
            let html = `<table><thead><tr>
                <th>#</th><th>Symbol</th><th>Sector</th><th>LTP</th><th>Composite Score</th>
                <th>Weekly Div</th><th>Weekly Label</th><th>Weekly Score</th>
                <th>Prev Low</th><th>Curr Low</th><th>Prev RSI</th><th>Curr RSI</th>
                <th>Price Drop%</th><th>RSI Gain</th>
                <th>Prev Week</th><th>Curr Week</th>
                <th>Daily Div</th><th>Daily Strength</th>
                <th>Daily Last RSI</th><th>Daily Prev RSI</th>
                <th>🗑️</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const ltpDisplay = getLtpDisplay(r.symbol);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const alertRowClass = (alertStatus === 'above' || alertStatus === 'below') ? 'ltp-alert-row' : '';
                
                html += `<tr class="${alertRowClass}">
                    <td>${i+1}</td>
                    <td><strong>${r.symbol || ''}${alertStatus ? ' 🔔' : ''}</strong></td>
                    <td>${r.sector || ''}</td><td>${ltpDisplay}</td>
                    <td>${(r.composite_score || 0).toFixed(0)}</td>
                    <td>${r.weekly_divergence || ''}</td><td>${r.weekly_strength_label || ''}</td>
                    <td>${r.weekly_strength_score || 0}</td>
                    <td>${(r.weekly_prev_low || 0).toFixed(2)}</td><td>${(r.weekly_curr_low || 0).toFixed(2)}</td>
                    <td>${(r.weekly_prev_rsi || 0).toFixed(2)}</td><td>${(r.weekly_curr_rsi || 0).toFixed(2)}</td>
                    <td>${(r.weekly_price_drop_pct || 0).toFixed(2)}%</td><td>+${(r.weekly_rsi_gain || 0).toFixed(2)}</td>
                    <td>${r.weekly_prev_date || ''}</td><td>${r.weekly_curr_date || ''}</td>
                    <td>${r.daily_divergence_type || ''}</td><td>${r.daily_divergence_strength || ''}</td>
                    <td>${(r.daily_last_rsi || 0).toFixed(2)}</td><td>${(r.daily_prev_rsi || 0).toFixed(2)}</td>
                    <td><button class="delete-btn" onclick="deleteRecord('${r.symbol||''}','${r.analysis_date||r.date||''}','swrsi')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} signals)`;
        }

        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { 
                div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data for selected date</p>'; 
                document.getElementById('recordCount').textContent = '(0 records)';
                return; 
            }
            
            const excludeKeys = ['_id', 'saved_at', 'analysis_date', 'latest_date', 'analysis_datetime', 'saved_at', 'date', 'signal_date'];
            const keys = Object.keys(currentData[0]).filter(k => !excludeKeys.includes(k) && !k.startsWith('_'));
            
            let html = `<table><thead><tr>
                <th>#</th><th>Symbol</th><th>LTP</th>
                ${keys.map(k => `<th>${k}</th>`).join('')}
                <th>🗑️</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const ltpDisplay = getLtpDisplay(r.symbol);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const alertRowClass = (alertStatus === 'above' || alertStatus === 'below') ? 'ltp-alert-row' : '';
                const recordDate = r.analysis_date || r.date || r.latest_date || r.signal_date || '';
                
                html += `<tr class="${alertRowClass}">
                    <td>${i+1}</td>
                    <td><strong>${r.symbol || ''}${alertStatus ? ' 🔔' : ''}</strong></td>
                    <td>${ltpDisplay}</td>
                    ${keys.map(k => `<td>${r[k]??''}</td>`).join('')}
                    <td><button class="delete-btn" onclick="deleteRecord('${r.symbol||''}','${recordDate}','${currentTab}')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} records)`;
        }

        async function deleteRecord(symbol, date, tab) {
            if (!confirm(`Delete ${symbol}?`)) return;
            const collection = COLLECTION_MAP[tab] || COLLECTION_MAP[currentTab];
            try {
                await fetch(`/api/delete-signal?collection=${encodeURIComponent(collection)}&symbol=${encodeURIComponent(symbol)}&date=${encodeURIComponent(date)}`, { method: 'DELETE' });
                loadCurrentTab();
            } catch(e) {
                alert('Delete failed: ' + e.message);
            }
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard v15: http://localhost:{PORT}")
    print(f"💚 Health Check: http://localhost:{PORT}/head")
    uvicorn.run(app, host="0.0.0.0", port=PORT)