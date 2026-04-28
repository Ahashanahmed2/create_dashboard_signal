"""
create_dashboard.py - v18 FINAL
✅ FIXED: Use saved_at as primary date field for ALL tabs
✅ FIXED: S/R uses saved_at date extraction
✅ FIXED: Alert modal shows only selected date symbols
✅ All Tabs with proper date filtering from saved_at
✅ DSE Market: Sun-Thu 10AM-2:20PM (Bangladesh Time UTC+6)
✅ LTP Alert Modal with date-filtered symbol selector
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
import re

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="18.0.0")
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
# DATE HELPERS - Extract date from saved_at or other fields
# ================================
def extract_date_string(value):
    """Extract YYYY-MM-DD from any date format"""
    if not value:
        return None
    
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    
    if isinstance(value, str):
        value = value.strip()
        # Already YYYY-MM-DD
        if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
            return value
        # ISO format: 2026-04-27T13:36:39.191723
        if 'T' in value:
            return value.split('T')[0]
        # Other formats
        match = re.search(r'(\d{4}-\d{2}-\d{2})', value)
        if match:
            return match.group(1)
    
    return None

def build_date_query_for_collection(date_value, collection_name):
    """Build MongoDB query that checks saved_at (primary) + other date fields"""
    conditions = []
    
    # PRIMARY: Check saved_at with regex (handles ISO format)
    conditions.append({'saved_at': {'$regex': f'^{date_value}'}})
    
    # SECONDARY: Check other date fields
    other_fields = ['analysis_date', 'date', 'level_date', 'latest_date', 'signal_date', 'p1_date', 'p2_date']
    for field in other_fields:
        conditions.append({field: date_value})
        conditions.append({field: {'$regex': f'^{date_value}'}})
    
    return {'$or': conditions}

def get_all_dates_from_collection(collection_name):
    """Get all unique dates from saved_at field (primary) + other date fields"""
    col = get_mongo_collection(collection_name)
    if col is None:
        return []
    
    dates_set = set()
    
    try:
        # Method 1: Use aggregation to extract date from saved_at
        pipeline = [
            {
                '$project': {
                    'date_str': {'$substr': ['$saved_at', 0, 10]}
                }
            },
            {
                '$group': {
                    '_id': '$date_str'
                }
            }
        ]
        try:
            results = list(col.aggregate(pipeline))
            for r in results:
                if r['_id'] and re.match(r'^\d{4}-\d{2}-\d{2}', str(r['_id'])):
                    dates_set.add(str(r['_id']))
        except:
            pass
        
        # Method 2: Check distinct saved_at (as string prefix matching)
        try:
            samples = list(col.find({'saved_at': {'$exists': True}}, {'saved_at': 1}).limit(1000))
            for s in samples:
                date_str = extract_date_string(s.get('saved_at'))
                if date_str:
                    dates_set.add(date_str)
        except:
            pass
        
        # Method 3: Check other date fields
        other_fields = ['analysis_date', 'date', 'level_date', 'latest_date', 'signal_date']
        for field in other_fields:
            try:
                field_dates = col.distinct(field)
                for d in field_dates:
                    date_str = extract_date_string(d)
                    if date_str:
                        dates_set.add(date_str)
            except:
                pass
        
        all_dates = sorted(list(dates_set), reverse=True)
        print(f"📅 {collection_name}: Found {len(all_dates)} dates (from saved_at + other fields)")
        return all_dates
        
    except Exception as e:
        print(f"❌ Error getting dates for {collection_name}: {e}")
        return []

def get_symbols_for_date(collection_name, date_value):
    """Get symbols from a collection for a specific date (using saved_at)"""
    col = get_mongo_collection(collection_name)
    if col is None:
        return []
    
    try:
        query = build_date_query_for_collection(date_value, collection_name)
        symbols = col.distinct('symbol', query)
        symbols = [s for s in symbols if s]
        result = sorted(symbols)
        print(f"📋 {collection_name}: {len(result)} symbols for date={date_value}")
        return result
    except Exception as e:
        print(f"❌ Error getting symbols: {e}")
        return []

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
    """Get all unique dates from saved_at field (extracted YYYY-MM-DD)"""
    dates = get_all_dates_from_collection(collection)
    return dates

@app.get("/api/collection-symbols")
async def get_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    """Get symbols from a collection, filtered by date (via saved_at)"""
    if not date:
        col = get_mongo_collection(collection)
        if col:
            symbols = col.distinct('symbol')
            return sorted([s for s in symbols if s])
        return []
    
    return get_symbols_for_date(collection, date)

@app.get("/api/signals")
async def get_signals(date: str = Query(None), signal: str = Query(None), symbol: str = Query(None), min_score: float = Query(0), limit: int = Query(1000)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query['$or'] = [
            {'saved_at': {'$regex': f'^{date}'}},
            {'analysis_date': date}
        ]
    else:
        latest = list(collection.find({'saved_at': {'$exists': True}}).sort('saved_at', -1).limit(1))
        if latest and latest[0].get('saved_at'):
            date_str = extract_date_string(latest[0]['saved_at'])
            if date_str:
                query['saved_at'] = {'$regex': f'^{date_str}'}
    
    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}
    
    cursor = collection.find(query, {'_id': 0}).sort('final_combined_score', -1).limit(limit)
    data = list(cursor)
    print(f"🔍 AI Signals: date={date}, found {len(data)} records")
    return {"data": data}

@app.get("/api/swrsi")
async def get_swrsi(date: str = Query(None), symbol: str = Query(None)):
    col = get_mongo_collection("swrsi_signals")
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query['$or'] = [
            {'saved_at': {'$regex': f'^{date}'}},
            {'analysis_date': date}
        ]
    else:
        latest = list(col.find({'saved_at': {'$exists': True}}).sort('saved_at', -1).limit(1))
        if latest and latest[0].get('saved_at'):
            date_str = extract_date_string(latest[0]['saved_at'])
            if date_str:
                query['saved_at'] = {'$regex': f'^{date_str}'}
    
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    data = list(col.find(query, {'_id': 0}).sort('composite_score', -1))
    print(f"🔍 SWRSI: date={date}, found {len(data)} records")
    return {"signals": data, "total_signals": len(data)}

@app.get("/api/generic-data")
async def get_generic_data(collection: str = Query(...), date: str = Query(None), symbol: str = Query(None), limit: int = Query(500)):
    """Get data from generic collections - PRIMARY: saved_at regex match"""
    col = get_mongo_collection(collection)
    if col is None: 
        return JSONResponse({"error": f"Collection {collection} not found"}, status_code=500)
    
    query = {}
    
    if date:
        query = build_date_query_for_collection(date, collection)
        print(f"🔍 {collection}: date={date}")
    
    if symbol: 
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    try:
        data = list(col.find(query, {'_id': 0}).limit(limit))
        print(f"📊 {collection}: found {len(data)} records for date={date}")
        return {"data": data}
    except Exception as e:
        print(f"❌ Error in generic-data: {e}")
        return {"data": [], "error": str(e)}

@app.delete("/api/delete-signal")
async def delete_signal(collection: str = Query("daily_ai_signals"), symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    # Try multiple ways to match
    result = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    if result.deleted_count == 0:
        result = col.delete_one({'symbol': symbol, 'analysis_date': date})
    if result.deleted_count == 0:
        result = col.delete_one({'symbol': symbol, 'date': date})
    if result.deleted_count == 0:
        result = col.delete_one({'symbol': symbol, 'level_date': date})
    
    return {"deleted": result.deleted_count}

@app.delete("/api/delete-all-by-date")
async def delete_all_by_date(collection: str = Query(...), date: str = Query(...)):
    """Delete all records matching a date (via saved_at regex)"""
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    total = 0
    
    # Primary: saved_at regex
    result = col.delete_many({'saved_at': {'$regex': f'^{date}'}})
    total += result.deleted_count
    
    # Secondary: other date fields
    for field in ['analysis_date', 'date', 'level_date', 'latest_date']:
        r = col.delete_many({field: date})
        total += r.deleted_count
    
    return {"deleted": total, "collection": collection, "date": date}

@app.put("/api/update-trade")
async def update_trade(symbol: str = Query(...), date: str = Query(...), entry_price: float = Query(None), stop_loss: float = Query(None), target_price: float = Query(None)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    update_fields = {'edited': True, 'edited_at': datetime.now().isoformat()}
    if entry_price is not None: update_fields['entry_price'] = entry_price
    if stop_loss is not None: update_fields['stop_loss'] = stop_loss
    if target_price is not None: update_fields['target_price'] = target_price
    result = collection.update_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}}, {'$set': update_fields})
    return {"updated": result.modified_count}

# ================================
# HTML Dashboard (same UI, updated API calls)
# ================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>🤖 AI Trading Signals Dashboard v18</title>
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
        .alert-config-btn.active-alert { animation: alertPulse 1s infinite; }
        @keyframes alertPulse { 0%,100% { box-shadow: 0 0 5px #ffa500; } 50% { box-shadow: 0 0 20px #ffa500; } }
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
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; }
        .modal.open { display: flex; }
        .modal-content { background: #1a1a2e; padding: 25px; border-radius: 15px; max-width: 500px; width: 90%; border: 2px solid #ffa500; max-height: 80vh; overflow-y: auto; }
        .modal-content h3 { color: #ffa500; margin-bottom: 15px; font-size: 1.2em; text-align: center; }
        .modal-content label { display: block; margin: 10px 0 5px; color: #aaa; font-size: 0.9em; }
        .modal-content select, .modal-content input { width: 100%; padding: 10px; margin-bottom: 8px; }
        .modal-buttons { display: flex; gap: 10px; margin-top: 15px; }
        .modal-buttons button { flex: 1; padding: 12px; }
        .save-alert-btn { background: #00ff88; color: #000; font-weight: bold; }
        .cancel-alert-btn { background: #666; }
        .remove-alert-btn { background: #ff4757; color: #fff; padding: 5px 10px; font-size: 0.8em; width: auto; }
        .current-alerts { margin-top: 15px; background: #0f3460; padding: 10px; border-radius: 8px; }
        .current-alerts h4 { color: #ffa500; margin-bottom: 8px; font-size: 0.9em; }
        .alert-item { display: flex; justify-content: space-between; align-items: center; background: #1a1a2e; padding: 8px; margin: 5px 0; border-radius: 5px; font-size: 0.8em; }
        .alert-item span { color: #ffa500; }
        .info-text { font-size: 0.75em; color: #888; text-align: center; margin-top: 5px; }
        .debug-info { font-size: 0.7em; color: #666; margin-top: 10px; padding: 8px; background: #111; border-radius: 5px; white-space: pre-wrap; }
        @media (max-width: 768px) { .header h1 { font-size: 1.3em; } .controls { flex-direction: column; } }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Trading Signals Dashboard v18</h1>
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
        <input type="text" id="symbolSearch" onkeyup="loadCurrentTab()" style="width:100px;" placeholder="Filter...">
        <button onclick="loadCurrentTab()">🔄 Refresh</button>
        <button class="alert-config-btn" id="alertConfigBtn" onclick="openAlertModal()">🔔 Alerts</button>
        <button class="delete-all-btn" onclick="deleteAllByDate()">🗑️ Delete Date</button>
        <span id="recordCount" style="color:#888;margin-left:5px;font-size:0.8em;"></span>
    </div>
    
    <div id="alertModal" class="modal">
        <div class="modal-content">
            <h3>🔔 LTP Alert Configuration</h3>
            <p class="info-text" id="alertModalInfo">Select symbol from current date</p>
            <label>📋 Symbol:</label>
            <select id="alertSymbolSelect"><option value="">-- Select date first --</option></select>
            <label>📊 Condition:</label>
            <select id="alertCondition"><option value="above">LTP উপরে গেলে Alert (Above)</option><option value="below">LTP নিচে গেলে Alert (Below)</option></select>
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
        let alertRules = [];
        const COLLECTION_MAP = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };

        loadDates(COLLECTION_MAP[currentTab]);
        loadCurrentTab();
        checkMarketStatus();
        loadDseLtp();
        loadAlertRules();
        setInterval(checkMarketStatus, 60000);
        setInterval(async () => { const s = await (await fetch('/api/market-status')).json(); if (s.is_open) loadDseLtp(); }, 60000);
        setInterval(loadDseLtp, 300000);

        function loadAlertRules() {
            const saved = localStorage.getItem('ltpAlertRules_v18');
            if (saved) { try { alertRules = JSON.parse(saved); } catch(e) { alertRules = []; } }
            updateAlertUI();
        }
        function saveAlertRules() { localStorage.setItem('ltpAlertRules_v18', JSON.stringify(alertRules)); updateAlertUI(); renderCurrentTab(); }
        function updateAlertUI() {
            const bar = document.getElementById('alertStatusBar'), btn = document.getElementById('alertConfigBtn');
            if (alertRules.length > 0) {
                bar.style.display = 'block';
                bar.innerHTML = `🔔 <strong>${alertRules.length} Alert(s):</strong> ` + alertRules.map(r => `${r.symbol} ${r.condition==='above'?'↑>':'↓<'} ${r.threshold}`).join(' | ');
                btn.classList.add('active-alert'); btn.textContent = `🔔 Alerts (${alertRules.length})`;
            } else { bar.style.display = 'none'; btn.classList.remove('active-alert'); btn.textContent = '🔔 Alerts'; }
        }
        async function openAlertModal() {
            const date = document.getElementById('dateSelect').value;
            document.getElementById('alertModalInfo').textContent = date ? `Symbols for: ${date}` : 'Select a date first';
            document.getElementById('alertModal').classList.add('open');
            await loadAlertSymbols(); renderCurrentAlerts();
        }
        function closeAlertModal() { document.getElementById('alertModal').classList.remove('open'); }
        async function loadAlertSymbols() {
            const date = document.getElementById('dateSelect').value;
            const select = document.getElementById('alertSymbolSelect');
            select.innerHTML = '<option value="">Loading...</option>';
            try {
                let url = `/api/collection-symbols?collection=${encodeURIComponent(COLLECTION_MAP[currentTab])}`;
                if (date) url += `&date=${encodeURIComponent(date)}`;
                const symbols = await (await fetch(url)).json();
                select.innerHTML = '<option value="">-- Select Symbol --</option>';
                if (Array.isArray(symbols) && symbols.length > 0) {
                    symbols.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; select.appendChild(o); });
                    document.getElementById('alertModalInfo').textContent = `${symbols.length} symbols for ${date || 'all dates'}`;
                } else {
                    select.innerHTML = '<option value="">No symbols found</option>';
                }
            } catch(e) { select.innerHTML = '<option value="">Error</option>'; }
        }
        function renderCurrentAlerts() {
            const sec = document.getElementById('currentAlertsSection'), list = document.getElementById('currentAlertsList');
            if (alertRules.length === 0) { sec.style.display = 'none'; return; }
            sec.style.display = 'block';
            list.innerHTML = alertRules.map((r,i) => `<div class="alert-item"><span>🔔 ${r.symbol} ${r.condition==='above'?'↑ Above':'↓ Below'} ${r.threshold}</span><button class="remove-alert-btn" onclick="removeAlertRule(${i})">✕</button></div>`).join('');
        }
        function addAlertRule() {
            const symbol = document.getElementById('alertSymbolSelect').value;
            const condition = document.getElementById('alertCondition').value;
            const threshold = parseFloat(document.getElementById('alertThresholdPrice').value);
            if (!symbol || symbol.includes('--')) { alert('Select a symbol'); return; }
            if (!threshold) { alert('Enter threshold price'); return; }
            alertRules = alertRules.filter(r => r.symbol !== symbol);
            alertRules.push({ symbol, condition, threshold });
            saveAlertRules(); renderCurrentAlerts();
            document.getElementById('alertSymbolSelect').value = ''; document.getElementById('alertThresholdPrice').value = '';
        }
        function removeAlertRule(i) { alertRules.splice(i,1); saveAlertRules(); renderCurrentAlerts(); renderCurrentTab(); }
        function getLtpAlertStatus(symbol) {
            if (!alertRules.length) return null;
            const ltp = dseLtpData[symbol] || null;
            if (ltp === null) return null;
            for (const r of alertRules) { if (r.symbol === symbol) { if (r.condition === 'above' && ltp > r.threshold) return 'above'; if (r.condition === 'below' && ltp < r.threshold) return 'below'; } }
            return null;
        }
        async function checkMarketStatus() {
            try {
                const s = await (await fetch('/api/market-status')).json();
                document.getElementById('marketStatus').innerHTML = s.is_open ? `🟢 DSE MARKET OPEN | ${s.bangladesh_time||''}` : `🔴 DSE CLOSED | ${s.next_open||'next session'} | ${s.bangladesh_time||''}`;
                document.getElementById('alertBox').style.display = s.alert_10min ? 'block' : 'none';
            } catch(e) {}
        }
        async function loadDseLtp() {
            try { const j = await (await fetch('/api/dse-ltp')).json(); if (j.status === 'live') { dseLtpData = j.ltp_data || {}; renderCurrentTab(); } } catch(e) {}
        }
        async function loadDates(collection) {
            try {
                const dates = await (await fetch(`/api/dates?collection=${encodeURIComponent(collection)}`)).json();
                const select = document.getElementById('dateSelect'), currentValue = select.value;
                select.innerHTML = '<option value="">Latest</option>';
                if (Array.isArray(dates)) dates.forEach(d => { if (d) { const o = document.createElement('option'); o.value = d; o.textContent = d; select.appendChild(o); } });
                if (currentValue && Array.from(select.options).some(o => o.value === currentValue)) select.value = currentValue;
                document.getElementById('debugInfo').textContent = `📅 ${collection}: ${dates.length} dates`;
            } catch(e) { document.getElementById('debugInfo').textContent = `Error: ${e.message}`; }
        }
        function onDateChange() { loadCurrentTab(); }
        async function loadCurrentTab() {
            const date = document.getElementById('dateSelect').value, symbol = document.getElementById('symbolSearch').value;
            try {
                let url;
                if (currentTab === 'ai_signals') { url = `/api/signals?limit=1000`; if (date) url += `&date=${date}`; if (symbol) url += `&symbol=${symbol}`; }
                else if (currentTab === 'swrsi') { url = '/api/swrsi?'; if (date) url += `date=${date}&`; if (symbol) url += `symbol=${symbol}&`; }
                else { url = `/api/generic-data?collection=${COLLECTION_MAP[currentTab]}&limit=500`; if (date) url += `&date=${date}`; if (symbol) url += `&symbol=${symbol}`; }
                const j = await (await fetch(url)).json();
                currentData = j.data || j.signals || [];
                document.getElementById('debugInfo').textContent = `📊 ${currentTab} | Date: ${date||'Latest'} | Records: ${currentData.length}`;
            } catch(e) { currentData = []; }
            renderCurrentTab();
        }
        function renderCurrentTab() { if (currentTab === 'ai_signals') renderAITable(); else if (currentTab === 'swrsi') renderSWRSITable(); else renderGenericTable(); }
        function switchTab(t) {
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            event.target.classList.add('active');
            currentTab = t; document.getElementById('symbolSearch').value = '';
            loadDates(COLLECTION_MAP[t]); loadCurrentTab();
        }
        function getSignalClass(s) {
            if (!s) return '';
            if (s.includes('STRONG BUY')||s.includes('Strong Buy')) return 'signal-SB';
            if (s.includes('BUY')||s.includes('Buy')) return 'signal-B';
            if (s.includes('HOLD')||s.includes('Hold')) return 'signal-H';
            if (s.includes('STRONG SELL')||s.includes('Strong Sell')) return 'signal-SS';
            if (s.includes('SELL')||s.includes('Sell')) return 'signal-S';
            return '';
        }
        function getLtpDisplay(symbol) {
            const ltp = dseLtpData[symbol] || null, alertStatus = getLtpAlertStatus(symbol);
            if (!ltp) return '<span style="color:#888;">-</span>';
            let cls = '', arrow = '';
            if (alertStatus === 'above') { cls = 'ltp-above'; arrow = ' ↑'; }
            else if (alertStatus === 'below') { cls = 'ltp-below'; arrow = ' ↓'; }
            return `<span class="${cls}" style="font-weight:bold;">${ltp.toFixed(2)}${arrow}</span>`;
        }
        function startEdit(s,d,e,sl,tp,i) { editingRow={symbol:s,date:d,index:i}; renderCurrentTab(); }
        function cancelEdit() { editingRow=null; renderCurrentTab(); }
        async function saveEdit(symbol, date) {
            const safeId = symbol.replace(/[^a-zA-Z0-9]/g,'_');
            const e = parseFloat(document.getElementById(`edit-entry-${safeId}`)?.value)||0;
            const sl = parseFloat(document.getElementById(`edit-sl-${safeId}`)?.value)||0;
            const tp = parseFloat(document.getElementById(`edit-tp-${safeId}`)?.value)||0;
            await fetch(`/api/update-trade?symbol=${symbol}&date=${date}&entry_price=${e}&stop_loss=${sl}&target_price=${tp}`,{method:'PUT'});
            editingRow=null; loadCurrentTab();
        }
        async function deleteAllByDate() {
            const date = document.getElementById('dateSelect').value;
            if (!date) { alert('Select a date first!'); return; }
            const col = COLLECTION_MAP[currentTab];
            if (!confirm(`DELETE ALL for ${date} in ${col}?`)) return;
            const j = await (await fetch(`/api/delete-all-by-date?collection=${col}&date=${date}`,{method:'DELETE'})).json();
            alert(`Deleted ${j.deleted} records`); loadDates(col); loadCurrentTab();
        }
        async function deleteRecord(symbol, date, tab) {
            if (!confirm(`Delete ${symbol}?`)) return;
            await fetch(`/api/delete-signal?collection=${COLLECTION_MAP[tab]||COLLECTION_MAP[currentTab]}&symbol=${symbol}&date=${date}`,{method:'DELETE'});
            loadCurrentTab();
        }
        function renderAITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML='<p style="color:#888;text-align:center;padding:40px;">No data</p>'; return; }
            let h = `<table><thead><tr><th>#</th><th>Symbol</th><th>Date</th><th>Price</th><th>LTP</th><th>Sector</th><th>Signal</th><th>Score</th><th>LLM</th><th>LLM%</th><th>LLM Str</th><th>LLM Bias</th><th>LLM Av</th><th>XGB</th><th>XGB%</th><th>XGB Pr</th><th>AUC</th><th>XGB Av</th><th>PPO</th><th>PPO%</th><th>PPO Av</th><th>PPO Wt</th><th>Agentic</th><th>Ag Bias</th><th>Ag Av</th><th>E Acc</th><th>E Tot</th><th>E Wave</th><th>Sub-Wave</th><th>Cur Wave</th><th>W Conf</th><th>Bull?</th><th>W Pos</th><th>Entry</th><th>SL</th><th>TP</th><th>R:R</th><th>Act</th></tr></thead><tbody>`;
            currentData.forEach((r,i) => {
                const safeId = (r.symbol||'').replace(/[^a-zA-Z0-9]/g,'_'), isEdit = editingRow && editingRow.symbol === r.symbol;
                const alertStatus = getLtpAlertStatus(r.symbol), rowClass = alertStatus ? 'ltp-alert-row' : '';
                const ec = isEdit ? `<input class="editable-input" id="edit-entry-${safeId}" value="${(r.entry_price||0).toFixed(2)}">` : (r.entry_price||0).toFixed(2);
                const sc = isEdit ? `<input class="editable-input" id="edit-sl-${safeId}" value="${(r.stop_loss||0).toFixed(2)}">` : (r.stop_loss||0).toFixed(2);
                const tc = isEdit ? `<input class="editable-input" id="edit-tp-${safeId}" value="${(r.target_price||0).toFixed(2)}">` : (r.target_price||0).toFixed(2);
                const ac = isEdit ? `<button class="save-btn" onclick="saveEdit('${r.symbol}','${r.analysis_date||extractDate(r.saved_at)}')">💾</button><button class="delete-btn" onclick="cancelEdit()">❌</button>` : `<button class="edit-btn" onclick="startEdit('${r.symbol}','${r.analysis_date||''}','${r.entry_price||0}','${r.stop_loss||0}','${r.target_price||0}',${i})">✏️</button><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date||(r.saved_at||'').substring(0,10)}','ai_signals')">🗑️</button>`;
                h += `<tr class="${rowClass}"><td>${i+1}</td><td><strong>${r.symbol}${r.edited?'<span class="edited-badge">✏️</span>':''}${alertStatus?' 🔔':''}</strong></td><td>${r.analysis_date||(r.saved_at||'').substring(0,10)}</td><td>${(r.current_price||0).toFixed(2)}</td><td>${getLtpDisplay(r.symbol)}</td><td>${r.sector||''}</td><td class="${getSignalClass(r.final_signal)}">${r.final_signal||''}</td><td><strong>${(r.final_combined_score||0).toFixed(1)}</strong></td><td>${r.llm_signal||''}</td><td>${(r.llm_confidence||0).toFixed(0)}%</td><td>${r.llm_strength||''}</td><td>${r.llm_bias||''}</td><td>${r.llm_available?'✅':'❌'}</td><td>${r.xgb_signal||''}</td><td>${(r.xgb_confidence||0).toFixed(0)}%</td><td>${(r.xgb_prob_up||0).toFixed(3)}</td><td>${(r.xgb_auc||0).toFixed(3)}</td><td>${r.xgb_available?'✅':'❌'}</td><td>${r.ppo_signal||''}</td><td>${(r.ppo_confidence||0).toFixed(0)}%</td><td>${r.ppo_available?'✅':'❌'}</td><td>${r.ppo_weight||0}</td><td>${(r.agentic_score||0).toFixed(1)}</td><td>${r.agentic_bias||''}</td><td>${r.agentic_available?'✅':'❌'}</td><td>${(r.elliott_accuracy||0).toFixed(1)}%</td><td>${r.elliott_total_predictions||0}</td><td style="font-size:0.6em;">${(r.elliott_wave_count||'').substring(0,12)}</td><td style="font-size:0.6em;">${(r.elliott_sub_waves||'').substring(0,15)}</td><td>${r.elliott_current_wave||''}</td><td>${(r.elliott_wave_confidence||0).toFixed(0)}%</td><td>${r.elliott_is_bullish?'✅':'❌'}</td><td>${r.elliott_wave_position||''}</td><td>${ec}</td><td>${sc}</td><td>${tc}</td><td>${r.risk_reward_ratio||0}</td><td>${ac}</td></tr>`;
            });
            div.innerHTML = h + '</tbody></table>';
            document.getElementById('recordCount').textContent = `(${currentData.length})`;
        }
        function renderSWRSITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML='<p style="color:#888;text-align:center;padding:40px;">No data</p>'; return; }
            let h = `<table><thead><tr><th>#</th><th>Symbol</th><th>Sector</th><th>LTP</th><th>Score</th><th>W Div</th><th>W Label</th><th>W Score</th><th>Prev Low</th><th>Curr Low</th><th>Prev RSI</th><th>Curr RSI</th><th>Drop%</th><th>RSI Gain</th><th>Prev Wk</th><th>Curr Wk</th><th>D Div</th><th>D Str</th><th>D Last RSI</th><th>D Prev RSI</th><th>🗑️</th></tr></thead><tbody>`;
            currentData.forEach((r,i) => { const alertStatus = getLtpAlertStatus(r.symbol); const dateStr = (r.saved_at||'').substring(0,10); h += `<tr class="${alertStatus?'ltp-alert-row':''}"><td>${i+1}</td><td><strong>${r.symbol||''}${alertStatus?' 🔔':''}</strong></td><td>${r.sector||''}</td><td>${getLtpDisplay(r.symbol)}</td><td>${(r.composite_score||0).toFixed(0)}</td><td>${r.weekly_divergence||''}</td><td>${r.weekly_strength_label||''}</td><td>${r.weekly_strength_score||0}</td><td>${(r.weekly_prev_low||0).toFixed(2)}</td><td>${(r.weekly_curr_low||0).toFixed(2)}</td><td>${(r.weekly_prev_rsi||0).toFixed(2)}</td><td>${(r.weekly_curr_rsi||0).toFixed(2)}</td><td>${(r.weekly_price_drop_pct||0).toFixed(2)}%</td><td>+${(r.weekly_rsi_gain||0).toFixed(2)}</td><td>${r.weekly_prev_date||''}</td><td>${r.weekly_curr_date||''}</td><td>${r.daily_divergence_type||''}</td><td>${r.daily_divergence_strength||''}</td><td>${(r.daily_last_rsi||0).toFixed(2)}</td><td>${(r.daily_prev_rsi||0).toFixed(2)}</td><td><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${dateStr}','swrsi')">🗑️</button></td></tr>`; });
            div.innerHTML = h + '</tbody></table>';
            document.getElementById('recordCount').textContent = `(${currentData.length})`;
        }
        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML='<p style="color:#888;text-align:center;padding:40px;">No data for this date</p>'; document.getElementById('recordCount').textContent='(0)'; return; }
            const excludeKeys = ['_id', 'saved_at'];
            const keys = Object.keys(currentData[0]).filter(k => !excludeKeys.includes(k) && !k.startsWith('_'));
            let h = `<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th>${keys.map(k=>`<th>${k}</th>`).join('')}<th>🗑️</th></tr></thead><tbody>`;
            currentData.forEach((r,i) => { const alertStatus = getLtpAlertStatus(r.symbol); const rowClass = alertStatus?'ltp-alert-row':''; const dateStr = r.analysis_date || r.date || r.level_date || (r.saved_at||'').substring(0,10) || ''; h += `<tr class="${rowClass}"><td>${i+1}</td><td><strong>${r.symbol||''}${alertStatus?' 🔔':''}</strong></td><td>${getLtpDisplay(r.symbol)}</td>${keys.map(k=>`<td>${r[k]??''}</td>`).join('')}<td><button class="delete-btn" onclick="deleteRecord('${r.symbol||''}','${dateStr}','${currentTab}')">🗑️</button></td></tr>`; });
            div.innerHTML = h + '</tbody></table>';
            document.getElementById('recordCount').textContent = `(${currentData.length})`;
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard v18: http://localhost:{PORT}")
    print(f"💚 Health: http://localhost:{PORT}/head")
    print(f"📅 Test: http://localhost:{PORT}/api/dates?collection=support_resistance")
    uvicorn.run(app, host="0.0.0.0", port=PORT)