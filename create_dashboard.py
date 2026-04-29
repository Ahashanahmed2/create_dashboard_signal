"""
create_dashboard.py
✅ All Tabs with LTP + No Duplicate Date
✅ DSE Market: Sun-Thu 10AM-2:20PM (Bangladesh Time UTC+6)
✅ AI Signals (37 cols) + SWRSI + S/R + MACD + EMA 200 + Daily Buy
✅ S/R date selector FIXED (uses analysis_date like all other tabs)
✅ LTP Alert Modal + Delete All + Edit buttons
✅ UptimeRobot HEAD endpoint
"""

import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
import re

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
a# এই ফাংশনটি আপনার create_dashboard.py-তে রিপ্লেস করুন
@app.get("/api/dse-ltp")
async def get_dse_ltp():
    now = get_bd_time()
    if not is_dse_market_open():
        return {"status": "closed", "message": "DSE Closed"}

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
        }
        
        ltp_data = {}
        
        # চেষ্টা ১: main page থেকে table scrape
        response = requests.get(
            "https://www.dsebd.org/dseX_share.php",
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # DSE-র পেজে ডেটা row গুলো খুঁজুন
            # নতুন পদ্ধতি: সব টেক্সট স্ক্যান করে symbol-LTP pair বের করুন
            all_text = soup.get_text()
            lines = all_text.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Pattern: SYMBOL followed by numbers (price, change)
                # যেমন: "JANATAMF 3.10 0.10 3.33%"
                parts = line.split()
                
                # কমপক্ষে 2 টি অংশ থাকতে হবে (symbol + price)
                if len(parts) >= 2:
                    symbol = parts[0]
                    
                    # শুধু valid symbol check (all caps, min 2 chars, max 20 chars)
                    if (symbol.isupper() or symbol.replace('-','').replace('.','').isupper()) and \
                       2 <= len(symbol) <= 20 and \
                       not symbol.startswith('%') and \
                       not symbol.startswith('*') and \
                       not symbol.startswith('×') and \
                       not symbol.startswith('>>'):
                        
                        try:
                            # প্রথম সংখ্যাটি LTP
                            ltp_val = float(parts[1])
                            if 0.1 <= ltp_val <= 10000:  # Valid price range
                                ltp_data[symbol] = ltp_val
                        except ValueError:
                            continue
            
            print(f"🎯 Method 1: Extracted {len(ltp_data)} symbols from text")
            
            # Method 2: Parse tables directly
            if len(ltp_data) < 10:
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            try:
                                sym = cells[0].get_text(strip=True)
                                price_text = cells[1].get_text(strip=True).replace(',', '')
                                
                                # Clean symbol
                                sym = sym.replace('#', '').strip()
                                if sym and len(sym) <= 20 and not sym.startswith('TRADING'):
                                    price_val = float(price_text)
                                    if 0.1 <= price_val <= 10000 and sym not in ltp_data:
                                        ltp_data[sym] = price_val
                            except (ValueError, IndexError):
                                continue
                    
                    if len(ltp_data) > 10:
                        break
                
                print(f"🎯 Method 2 (tables): Total {len(ltp_data)} symbols")
        
        # Minimum symbol threshold check
        if len(ltp_data) >= 20:
            sample = list(ltp_data.items())[:3]
            print(f"✅ Sample LTP: {sample}")
            return {"status": "live", "total_symbols": len(ltp_data), "ltp_data": ltp_data}
        else:
            print(f"⚠️ Only found {len(ltp_data)} symbols, trying alternative...")
            
            # Fallback: DSE API
            try:
                api_resp = requests.get(
                    "https://www.dsebd.org/latest_share_price_scroll_l.php",
                    headers=headers,
                    timeout=10
                )
                if api_resp.status_code == 200:
                    soup = BeautifulSoup(api_resp.content, 'html.parser')
                    rows = soup.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            try:
                                sym = cells[0].get_text(strip=True).replace('#', '')
                                price = float(cells[1].get_text(strip=True).replace(',', ''))
                                if 0.1 <= price <= 10000 and sym and sym not in ltp_data:
                                    ltp_data[sym] = price
                            except: continue
                    
                    print(f"🎯 Fallback: Got {len(ltp_data)} symbols")
            except Exception as e:
                print(f"⚠️ Fallback failed: {e}")
        
        if len(ltp_data) > 0:
            return {"status": "live", "total_symbols": len(ltp_data), "ltp_data": ltp_data}
        else:
            return {"status": "error", "message": "No LTP data found"}
            
    except Exception as e:
        print(f"❌ LTP Error: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
# ================================
# FIXED: ALL collections use analysis_date
# ================================
def build_date_query(date_value):
    """Simple query: analysis_date primary, saved_at fallback"""
    return {'$or': [
        {'analysis_date': date_value},
        {'analysis_date': {'$regex': f'^{date_value}'}},
        {'saved_at': {'$regex': f'^{date_value}'}},
    ]}

def get_latest_date_from_collection(collection_name):
    """Get latest analysis_date from any collection"""
    col = get_mongo_collection(collection_name)
    if col is None: return None
    
    doc = col.find_one(
        {'analysis_date': {'$exists': True, '$ne': None, '$ne': ''}}, 
        sort=[('analysis_date', -1)]
    )
    if doc and doc.get('analysis_date'):
        val = doc['analysis_date']
        if isinstance(val, str) and len(val) >= 10:
            return val[:10]
        if isinstance(val, datetime):
            return val.strftime('%Y-%m-%d')
    
    doc = col.find_one({'saved_at': {'$exists': True}}, sort=[('saved_at', -1)])
    if doc and doc.get('saved_at'):
        val = doc['saved_at']
        if isinstance(val, str) and len(val) >= 10:
            return val[:10]
    return None

@app.get("/api/dates")
async def get_dates(collection: str = Query("daily_ai_signals")):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    dates_set = set()
    
    # analysis_date
    try:
        for d in col.distinct('analysis_date'):
            if d:
                if isinstance(d, datetime): dates_set.add(d.strftime('%Y-%m-%d'))
                elif isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()): dates_set.add(d.strip())
    except: pass
    
    # saved_at
    try:
        for doc in col.find({'saved_at': {'$exists': True}}, {'saved_at': 1}).limit(2000):
            val = doc.get('saved_at', '')
            if isinstance(val, str) and len(val) >= 10:
                d = val[:10]
                if re.match(r'\d{4}-\d{2}-\d{2}', d): dates_set.add(d)
    except: pass
    
    return sorted(list(dates_set), reverse=True)

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
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection("daily_ai_signals")
        if latest_date:
            query = build_date_query(latest_date)
    
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
    if date:
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection("swrsi_signals")
        if latest_date:
            query = build_date_query(latest_date)
    
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    data = list(col.find(query, {'_id': 0}).sort('composite_score', -1))
    all_dates = sorted(col.distinct('analysis_date'), reverse=True)
    return {"signals": data, "total_signals": len(data), "available_dates": all_dates}

@app.get("/api/stats")
async def get_stats(date: str = Query(None)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date: 
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection("daily_ai_signals")
        if latest_date:
            query = build_date_query(latest_date)
    
    pipeline = [{'$match': query}, {'$group': {'_id': None, 'total': {'$sum': 1}, 'avg_score': {'$avg': '$final_combined_score'}}}]
    result = list(collection.aggregate(pipeline))
    if result: return {k: v for k, v in result[0].items() if k != '_id'}
    return {"total": 0, "avg_score": 0}

@app.get("/api/generic-data")
async def get_generic_data(collection: str = Query(...), date: str = Query(None), symbol: str = Query(None), limit: int = Query(500)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection(collection)
        if latest_date:
            query = build_date_query(latest_date)
    
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    data = list(col.find(query, {'_id': 0}).limit(limit))
    return {"data": data}

@app.delete("/api/delete-signal")
async def delete_signal(collection: str = Query("daily_ai_signals"), symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    result = col.delete_one({'symbol': symbol, 'analysis_date': date})
    if result.deleted_count == 0:
        result = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    return {"deleted": result.deleted_count}

@app.delete("/api/delete-all-by-date")
async def delete_all_by_date(collection: str = Query(...), date: str = Query(...)):
    """Delete ALL records for a specific date in a collection"""
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    result1 = col.delete_many({'analysis_date': date})
    result2 = col.delete_many({'saved_at': {'$regex': f'^{date}'}})
    total = result1.deleted_count + result2.deleted_count
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

@app.get("/api/collection-symbols")
async def get_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection(collection)
        if latest_date:
            query = build_date_query(latest_date)
    
    symbols = col.distinct('symbol', query)
    return sorted([s for s in symbols if s])

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
        .delete-all-btn { background: #ff4757; color: #fff; font-weight: bold; }
        .alert-config-btn { background: #ffa500; color: #000; font-weight: bold; }
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
        .ltp-alert-row { animation: ltpBlink 0.6s infinite; }
        @keyframes ltpBlink { 0%,100% { background: #ff475730; } 50% { background: #ff475760; } }
        .ltp-above { color: #00ff88 !important; font-weight: bold; }
        .ltp-below { color: #ff4757 !important; font-weight: bold; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; }
        .modal.open { display: flex; }
        .modal-content { background: #1a1a2e; padding: 25px; border-radius: 15px; max-width: 500px; width: 90%; border: 2px solid #ffa500; }
        .modal-content h3 { color: #ffa500; margin-bottom: 15px; }
        .modal-content select, .modal-content input { width: 100%; padding: 10px; margin-bottom: 10px; }
        .modal-buttons { display: flex; gap: 10px; margin-top: 15px; }
        .modal-buttons button { flex: 1; }
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
        <button class="alert-config-btn" onclick="openAlertModal()">🔔 Alerts</button>
        <button class="delete-all-btn" onclick="deleteAllByDate()">🗑️ Delete All (Date)</button>
        <span id="recordCount" style="color:#888;"></span>
    </div>
    
    <div id="alertModal" class="modal">
        <div class="modal-content">
            <h3>🔔 Configure LTP Alerts</h3>
            <label>📋 Select Symbol:</label>
            <select id="alertSymbolSelect"><option value="">-- Loading... --</option></select>
            <label>📊 Condition:</label>
            <select id="alertCondition">
                <option value="above">LTP উপরে গেলে Alert</option>
                <option value="below">LTP নিচে গেলে Alert</option>
            </select>
            <label>💰 Threshold Price:</label>
            <input type="number" id="alertThresholdPrice" placeholder="Enter price..." step="0.01">
            <div class="modal-buttons">
                <button class="save-btn" onclick="addAlertRule()">➕ Add Alert</button>
                <button onclick="closeAlertModal()">Cancel</button>
            </div>
            <div id="currentAlertsSection" style="margin-top:15px;background:#0f3460;padding:10px;border-radius:8px;display:none;">
                <h4 style="color:#ffa500;">Active Alerts:</h4>
                <div id="currentAlertsList"></div>
            </div>
        </div>
    </div>
    
    <div id="alertStatusBar" style="background:#0f3460;padding:6px 12px;border-radius:6px;margin-bottom:8px;display:none;color:#ffa500;font-size:0.8em;"></div>
    <div style="overflow-x:auto;" id="dynamicTable"></div>

    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let dseLtpData = {};
        let editingRow = null;
        let alertRules = [];

        const COLLECTION_MAP = { 
            ai_signals: 'daily_ai_signals', 
            swrsi: 'swrsi_signals', 
            support: 'support_resistance', 
            macd: 'macd_signals', 
            ema: 'ema_200_signals', 
            buy: 'daily_buy_signals' 
        };

        loadDates(COLLECTION_MAP[currentTab]);
        loadCurrentTab();
        checkMarketStatus();
        loadDseLtp();
        loadAlertRules();
        setInterval(checkMarketStatus, 60000);
        setInterval(async () => {
            const res = await fetch('/api/market-status');
            const status = await res.json();
            if (status.is_open) loadDseLtp();
        }, 60000);

        function loadAlertRules() {
            const saved = localStorage.getItem('ltpAlertRules_v27');
            if (saved) { try { alertRules = JSON.parse(saved); } catch(e) { alertRules = []; } }
            updateAlertUI();
        }
        
        function saveAlertRules() { 
            localStorage.setItem('ltpAlertRules_v27', JSON.stringify(alertRules)); 
            updateAlertUI(); 
            renderCurrentTab(); 
        }
        
        function updateAlertUI() {
            const bar = document.getElementById('alertStatusBar');
            if (alertRules.length > 0) {
                bar.style.display = 'block';
                bar.innerHTML = '🔔 <strong>' + alertRules.length + ' Alert(s):</strong> ' + 
                    alertRules.map(r => r.symbol + ' ' + (r.condition === 'above' ? '↑>' : '↓<') + ' ' + r.threshold).join(' | ');
            } else {
                bar.style.display = 'none';
            }
        }

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
            if (Array.isArray(d)) {
                d.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; s.appendChild(o); }); 
            }
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

        function getLtpAlertStatus(symbol) {
            if (!alertRules.length) return null;
            const ltp = dseLtpData[symbol] || null;
            if (ltp === null) return null;
            for (const rule of alertRules) {
                if (rule.symbol === symbol) {
                    if (rule.condition === 'above' && ltp > rule.threshold) return 'above';
                    if (rule.condition === 'below' && ltp < rule.threshold) return 'below';
                }
            }
            return null;
        }

        function getLtpDisplay(symbol) {
            const ltp = dseLtpData[symbol] || null;
            const alertStatus = getLtpAlertStatus(symbol);
            if (!ltp) return '<span style="color:#888;">-</span>';
            let cls = '', arrow = '';
            if (alertStatus === 'above') { cls = 'ltp-above'; arrow = ' ↑'; }
            else if (alertStatus === 'below') { cls = 'ltp-below'; arrow = ' ↓'; }
            return `<span class="${cls}" style="font-weight:bold;">${ltp.toFixed(2)}${arrow}</span>`;
        }

        function startEdit(symbol, date, entry, sl, tp, i) { editingRow = { symbol, date, rowIndex: i }; renderAITable(); }
        function cancelEdit() { editingRow = null; renderAITable(); }

        async function saveEdit(symbol, date) {
            const safeId = symbol.replace(/[^a-zA-Z0-9]/g, '_');
            const entry = parseFloat(document.getElementById(`edit-entry-${safeId}`).value) || 0;
            const sl = parseFloat(document.getElementById(`edit-sl-${safeId}`).value) || 0;
            const tp = parseFloat(document.getElementById(`edit-tp-${safeId}`).value) || 0;
            const params = new URLSearchParams({ symbol, date, entry_price: entry, stop_loss: sl, target_price: tp });
            await fetch(`/api/update-trade?${params}`, { method: 'PUT' });
            editingRow = null;
            loadCurrentTab();
        }

        // ===== ALERT MODAL =====
        async function openAlertModal() {
            document.getElementById('alertModal').classList.add('open');
            await loadAlertSymbols();
            renderCurrentAlerts();
        }
        function closeAlertModal() { document.getElementById('alertModal').classList.remove('open'); }

        async function loadAlertSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTION_MAP[currentTab];
            const select = document.getElementById('alertSymbolSelect');
            select.innerHTML = '<option value="">Loading...</option>';
            try {
                let url = `/api/collection-symbols?collection=${collection}`;
                if (date) url += `&date=${date}`;
                const symbols = await (await fetch(url)).json();
                select.innerHTML = '<option value="">-- Select Symbol --</option>';
                if (symbols.length > 0) {
                    symbols.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; select.appendChild(o); });
                }
            } catch(e) { select.innerHTML = '<option value="">Error</option>'; }
        }

        function renderCurrentAlerts() {
            const section = document.getElementById('currentAlertsSection');
            const list = document.getElementById('currentAlertsList');
            if (alertRules.length === 0) { section.style.display = 'none'; return; }
            section.style.display = 'block';
            list.innerHTML = alertRules.map((r, i) => 
                `<div style="display:flex;justify-content:space-between;background:#1a1a2e;padding:8px;margin:5px 0;border-radius:5px;"><span>🔔 ${r.symbol} ${r.condition==='above'?'↑ Above':'↓ Below'} ${r.threshold}</span><button onclick="removeAlertRule(${i})" style="background:#ff4757;padding:5px;border:none;color:#fff;border-radius:4px;">✕</button></div>`
            ).join('');
        }

        function addAlertRule() {
            const symbol = document.getElementById('alertSymbolSelect').value;
            const condition = document.getElementById('alertCondition').value;
            const threshold = parseFloat(document.getElementById('alertThresholdPrice').value);
            if (!symbol || symbol.includes('--')) return;
            if (!threshold) return;
            alertRules = alertRules.filter(r => r.symbol !== symbol);
            alertRules.push({ symbol, condition, threshold });
            saveAlertRules();
            document.getElementById('alertSymbolSelect').value = '';
            document.getElementById('alertThresholdPrice').value = '';
        }

        function removeAlertRule(i) { alertRules.splice(i, 1); saveAlertRules(); renderCurrentTab(); }

        async function deleteAllByDate() {
            const date = document.getElementById('dateSelect').value;
            if (!date) { alert('Select a date first!'); return; }
            if (!confirm(`DELETE ALL records for ${date}?`)) return;
            const collection = COLLECTION_MAP[currentTab];
            const r = await fetch(`/api/delete-all-by-date?collection=${collection}&date=${date}`, { method: 'DELETE' });
            const result = await r.json();
            alert(`Deleted ${result.deleted} records`);
            loadDates(collection);
            loadCurrentTab();
        }

        async function deleteRecord(symbol, date, tab = 'ai_signals') {
            if (!confirm(`Delete ${symbol}?`)) return;
            const map = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_200_signals', buy: 'daily_buy_signals' };
            await fetch(`/api/delete-signal?collection=${map[tab]}&symbol=${symbol}&date=${date}`, { method: 'DELETE' });
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
                const safeId = (r.symbol || '').replace(/[^a-zA-Z0-9]/g, '_');
                const isEditing = editingRow && editingRow.symbol === r.symbol && editingRow.date === r.analysis_date;
                const isEdited = r.edited === true;
                const ltpDisplay = getLtpDisplay(r.symbol);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const alertRowClass = (alertStatus === 'above' || alertStatus === 'below') ? 'ltp-alert-row' : '';
                
                const entryCell = isEditing ? `<input class="editable-input" id="edit-entry-${safeId}" value="${(r.entry_price||0).toFixed(2)}">` : (r.entry_price||0).toFixed(2);
                const slCell = isEditing ? `<input class="editable-input" id="edit-sl-${safeId}" value="${(r.stop_loss||0).toFixed(2)}">` : (r.stop_loss||0).toFixed(2);
                const tpCell = isEditing ? `<input class="editable-input" id="edit-tp-${safeId}" value="${(r.target_price||0).toFixed(2)}">` : (r.target_price||0).toFixed(2);
                const actionCell = isEditing 
                    ? `<button class="save-btn" onclick="saveEdit('${r.symbol}','${r.analysis_date}')">💾</button><button class="delete-btn" onclick="cancelEdit()">❌</button>`
                    : `<button class="edit-btn" onclick="startEdit('${r.symbol}','${r.analysis_date}','${r.entry_price||0}','${r.stop_loss||0}','${r.target_price||0}',${i})">✏️</button><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}')">🗑️</button>`;
                
                html += `<tr class="${alertRowClass}">
                    <td>${i+1}</td><td><strong>${r.symbol}${isEdited ? '<span class="edited-badge">✏️</span>' : ''}${alertStatus ? ' 🔔' : ''}</strong></td>
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
                const alertStatus = getLtpAlertStatus(r.symbol);
                const alertRowClass = (alertStatus === 'above' || alertStatus === 'below') ? 'ltp-alert-row' : '';
                
                html += `<tr class="${alertRowClass}">
                    <td>${i+1}</td><td><strong>${r.symbol || ''}${alertStatus ? ' 🔔' : ''}</strong></td><td>${r.sector || ''}</td>
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
            
            const excludeKeys = ['_id', 'saved_at', 'analysis_date', 'latest_date', 'analysis_datetime', 'date'];
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
                const recordDate = r.analysis_date || r.date || r.level_date || (r.saved_at||'').substring(0,10) || '';
                
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
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
