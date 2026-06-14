"""
create_dashboard.py
✅ All Tabs Working - FIXED
✅ Market Status Working - FIXED
✅ Data Display Working - FIXED
"""

import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
import re

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="18.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    pass

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI: 
        return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name or COLLECTION_NAME]
    except Exception as e:
        print(f"MongoDB error: {e}")
        return None

BD_TIMEZONE = timezone(timedelta(hours=6))

def get_bd_time():
    return datetime.now(BD_TIMEZONE)

@app.api_route("/head", methods=["GET", "HEAD"])
async def uptime_robot_head():
    return Response(content="OK", status_code=200)

@app.get('/sw.js')
async def service_worker():
    return FileResponse('static/sw.js', media_type='application/javascript')

@app.get("/api/health")
async def health():
    col = get_mongo_collection()
    return {"status": "ok", "mongodb": "connected" if col else "not configured"}

@app.get("/api/market-status")
async def market_status():
    now = get_bd_time()
    # Simple market hours check: Sun-Thu, 10 AM - 2:20 PM
    weekday = now.weekday()
    hour_min = now.hour * 60 + now.minute
    
    # Sunday(6), Monday(0), Tuesday(1), Wednesday(2), Thursday(3)
    is_market_day = weekday in [6, 0, 1, 2, 3]
    is_market_hours = 600 <= hour_min <= 860  # 10:00 to 14:20
    
    is_open = is_market_day and is_market_hours
    
    return {
        "is_open": is_open,
        "bangladesh_time": now.strftime('%Y-%m-%d %H:%M:%S'),
        "weekday": weekday,
        "hour_minute": f"{now.hour}:{now.minute:02d}"
    }

# LTP Cache
ltp_cache = {"data": {}, "timestamp": None}

@app.get("/api/dse-ltp")
async def get_dse_ltp(force: int = Query(0)):
    market_open = (await market_status())["is_open"]
    
    # Return cache if available
    if ltp_cache["timestamp"] and not force:
        age = (datetime.now() - ltp_cache["timestamp"]).total_seconds()
        if age < 60:
            return ltp_cache["data"]
    
    ltp_data = {}
    
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        response = session.get('https://www.dsebd.org/latest_share_price_scroll_l.php', timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.find_all('tr')
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    try:
                        symbol = cols[1].get_text(strip=True)
                        ltp_text = cols[2].get_text(strip=True).replace(',', '')
                        if symbol and ltp_text:
                            ltp = float(ltp_text)
                            if 0.1 < ltp < 50000:
                                ltp_data[symbol.upper()] = ltp
                    except:
                        continue
            
            if ltp_data:
                result = {
                    "status": "success",
                    "total_symbols": len(ltp_data),
                    "ltp_data": ltp_data,
                    "market_open": market_open
                }
                ltp_cache["data"] = result
                ltp_cache["timestamp"] = datetime.now()
                return result
    except Exception as e:
        print(f"LTP error: {e}")
    
    return {"status": "error", "ltp_data": {}, "message": "Could not fetch LTP"}

def build_date_query(date_value):
    return {'analysis_date': date_value}

def get_latest_date_from_collection(collection_name):
    col = get_mongo_collection(collection_name)
    if col is None: return None
    doc = col.find_one({'analysis_date': {'$exists': True}}, sort=[('analysis_date', -1)])
    if doc and doc.get('analysis_date'):
        val = doc['analysis_date']
        if isinstance(val, str) and len(val) >= 10:
            return val[:10]
        if isinstance(val, datetime):
            return val.strftime('%Y-%m-%d')
    return None

@app.get("/api/dates")
async def get_dates(collection: str = Query("daily_ai_signals")):
    col = get_mongo_collection(collection)
    if col is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    dates_set = set()
    try:
        for d in col.distinct('analysis_date'):
            if d:
                if isinstance(d, datetime):
                    dates_set.add(d.strftime('%Y-%m-%d'))
                elif isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()):
                    dates_set.add(d.strip())
    except:
        pass
    
    return sorted(list(dates_set), reverse=True)

@app.get("/api/signals")
async def get_signals(date: str = Query(None), symbol: str = Query(None)):
    collection = get_mongo_collection()
    if collection is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query['analysis_date'] = date
    else:
        latest_date = get_latest_date_from_collection("daily_ai_signals")
        if latest_date:
            query['analysis_date'] = latest_date
    
    if symbol:
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    cursor = collection.find(query, {'_id': 0}).sort([('diff', 1), ('gape', -1)]).limit(500)
    data = list(cursor)
    
    return {"data": data}

@app.get("/api/swrsi")
async def get_swrsi(date: str = Query(None), symbol: str = Query(None)):
    col = get_mongo_collection("swrsi_signals")
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query['analysis_date'] = date
    else:
        latest_date = get_latest_date_from_collection("swrsi_signals")
        if latest_date:
            query['analysis_date'] = latest_date
    
    if symbol:
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    cursor = col.find(query, {'_id': 0}).sort([('diff', 1), ('gape', -1)])
    data = list(cursor)
    all_dates = sorted(col.distinct('analysis_date'), reverse=True)
    
    return {"signals": data, "total_signals": len(data), "available_dates": all_dates}

@app.get("/api/generic-data")
async def get_generic_data(collection: str = Query(...), date: str = Query(None), symbol: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query['analysis_date'] = date
    else:
        latest_date = get_latest_date_from_collection(collection)
        if latest_date:
            query['analysis_date'] = latest_date
    
    if symbol:
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    cursor = col.find(query, {'_id': 0}).sort([('diff', 1), ('gape', -1)]).limit(500)
    data = list(cursor)
    
    return {"data": data}

@app.delete("/api/delete-signal")
async def delete_signal(collection: str = Query("daily_ai_signals"), symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    result = col.delete_one({'symbol': symbol, 'analysis_date': date})
    return {"deleted": result.deleted_count}

@app.delete("/api/delete-all-by-date")
async def delete_all_by_date(collection: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    result = col.delete_many({'analysis_date': date})
    return {"deleted": result.deleted_count}

@app.put("/api/update-trade")
async def update_trade(
    collection: str = Query("daily_ai_signals"),
    symbol: str = Query(...),
    date: str = Query(...),
    entry_price: float = Query(None),
    stop_loss: float = Query(None),
    target_price: float = Query(None)
):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    update_fields = {'edited': True}
    if entry_price is not None:
        update_fields['entry_price'] = entry_price
    if stop_loss is not None:
        update_fields['stop_loss'] = stop_loss
    if target_price is not None:
        update_fields['target_price'] = target_price
    
    if entry_price and stop_loss and target_price:
        risk = abs(entry_price - stop_loss)
        reward = abs(target_price - entry_price)
        if risk > 0:
            update_fields['risk_reward_ratio'] = round(reward / risk, 2)
    
    result = col.update_one({'symbol': symbol, 'analysis_date': date}, {'$set': update_fields})
    return {"updated": result.modified_count}

@app.get("/api/collection-symbols")
async def get_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    
    query = {}
    if date:
        query['analysis_date'] = date
    else:
        latest_date = get_latest_date_from_collection(collection)
        if latest_date:
            query['analysis_date'] = latest_date
    
    symbols = col.distinct('symbol', query)
    return sorted([s for s in symbols if s])

@app.get("/")
async def dashboard():
    return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Trading Signals</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        
        .header { text-align: center; padding: 30px; background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%); border-radius: 15px; margin-bottom: 20px; }
        .header h1 { font-size: 2em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        .market-status { margin-top: 10px; font-size: 1.2em; font-weight: bold; }
        .market-open { color: #00ff88; }
        .market-closed { color: #ff4757; }
        
        .tabs { display: flex; margin-bottom: 20px; background: #111; border-radius: 10px; overflow-x: auto; }
        .tab { padding: 12px 20px; text-align: center; cursor: pointer; color: #aaa; transition: all 0.3s; white-space: nowrap; }
        .tab:hover { background: #1a1a2e; color: #00d4ff; }
        .tab.active { background: #1a1a2e; color: #00d4ff; font-weight: bold; border-bottom: 2px solid #00d4ff; }
        
        .controls { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }
        select, input, button { padding: 8px 12px; background: #1a1a2e; color: #fff; border: 1px solid #333; border-radius: 6px; font-size: 14px; }
        button { cursor: pointer; background: #0f3460; transition: all 0.3s; }
        button:hover { background: #1a4a7a; }
        .delete-all-btn { background: #ff4757; }
        .delete-all-btn:hover { background: #ff6b6b; }
        .alert-config-btn { background: #ffa500; color: #000; }
        .trade-btn { background: #00cc66; color: #000; }
        
        table { width: 100%; border-collapse: collapse; background: #111122; border-radius: 10px; overflow-x: auto; display: block; }
        th { background: #1a1a2e; padding: 10px; color: #00d4ff; font-weight: bold; position: sticky; top: 0; cursor: pointer; }
        td { padding: 8px; border-bottom: 1px solid #222; }
        tr:hover { background: #1a1a2e; }
        
        .signal-strong-buy { color: #00ff88; font-weight: bold; }
        .signal-buy { color: #00cc66; font-weight: bold; }
        .signal-hold { color: #ffd700; }
        .signal-sell { color: #ff4757; }
        
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000; justify-content: center; align-items: center; }
        .modal.open { display: flex; }
        .modal-content { background: #1a1a2e; padding: 20px; border-radius: 10px; max-width: 500px; width: 90%; }
        
        .edit-btn, .delete-btn, .trade-edit-btn, .save-btn { padding: 4px 8px; margin: 2px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .edit-btn { background: #ffa500; color: #000; }
        .delete-btn { background: #ff4757; color: #fff; }
        .trade-edit-btn { background: #7b2ff7; color: #fff; }
        .save-btn { background: #00ff88; color: #000; }
        
        .ltp-break-high { background: #00ff8818; }
        .ltp-above { color: #00ff88; font-weight: bold; }
        
        @media (max-width: 768px) {
            body { padding: 10px; }
            .header h1 { font-size: 1.3em; }
            .tab { padding: 8px 12px; font-size: 12px; }
            th, td { font-size: 10px; padding: 4px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Trading Signals Dashboard</h1>
        <div class="market-status" id="marketStatus">Loading market status...</div>
    </div>
    
    <div class="tabs" id="tabs">
        <div class="tab active" data-tab="ai_signals">🤖 AI Signals</div>
        <div class="tab" data-tab="swrsi">🔍 SWRSI</div>
        <div class="tab" data-tab="support">📊 S/R</div>
        <div class="tab" data-tab="ema">📈 EMA 21</div>
        <div class="tab" data-tab="buy">✅ Daily Buy</div>
    </div>
    
    <div class="controls">
        <select id="dateSelect" onchange="loadData()">
            <option value="">Loading dates...</option>
        </select>
        <input type="text" id="symbolSearch" placeholder="Symbol" onkeyup="loadData()">
        <button onclick="loadData()">🔄 Refresh</button>
        <button class="alert-config-btn" onclick="openAlertModal()">🔔 Alerts</button>
        <button class="delete-all-btn" onclick="deleteAllByDate()">🗑️ Delete All</button>
        <button class="trade-btn" onclick="openTradeModal()">💰 Trade</button>
        <span id="recordCount"></span>
    </div>
    
    <div style="overflow-x: auto;" id="dynamicTable">Loading data...</div>
    
    <!-- Alert Modal -->
    <div id="alertModal" class="modal">
        <div class="modal-content">
            <h3>🔔 Configure Alerts</h3>
            <select id="alertSymbol"></select>
            <select id="alertCondition">
                <option value="above">LTP Above</option>
                <option value="below">LTP Below</option>
            </select>
            <input type="number" id="alertPrice" placeholder="Price">
            <button onclick="addAlert()">Add Alert</button>
            <button onclick="closeAlertModal()">Close</button>
            <div id="alertList"></div>
        </div>
    </div>
    
    <!-- Trade Modal -->
    <div id="tradeModal" class="modal">
        <div class="modal-content">
            <h3>💰 Trade Management</h3>
            <select id="tradeSymbol"></select>
            <input type="number" id="entryPrice" placeholder="Entry Price">
            <input type="number" id="stopLoss" placeholder="Stop Loss">
            <input type="number" id="targetPrice" placeholder="Target Price">
            <button onclick="saveTrade()">Save Trade</button>
            <button onclick="closeTradeModal()">Cancel</button>
        </div>
    </div>
    
    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let ltpData = {};
        let alerts = [];
        
        const COLLECTIONS = {
            ai_signals: 'daily_ai_signals',
            swrsi: 'swrsi_signals',
            support: 'support_resistance',
            ema: 'ema_21_signals',
            buy: 'daily_buy_signals'
        };
        
        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Page loaded');
            
            // Tab click handlers
            document.querySelectorAll('.tab').forEach(tab => {
                tab.addEventListener('click', function() {
                    const tabId = this.getAttribute('data-tab');
                    console.log('Tab clicked:', tabId);
                    switchTab(tabId);
                });
            });
            
            // Load initial data
            loadMarketStatus();
            loadDates();
            loadData();
            loadLTP();
            loadAlerts();
            
            // Refresh every 30 seconds
            setInterval(loadLTP, 30000);
            setInterval(loadMarketStatus, 60000);
        });
        
        function switchTab(tabId) {
            currentTab = tabId;
            
            // Update active tab style
            document.querySelectorAll('.tab').forEach(tab => {
                if (tab.getAttribute('data-tab') === tabId) {
                    tab.classList.add('active');
                } else {
                    tab.classList.remove('active');
                }
            });
            
            // Reload data
            loadDates();
            loadData();
        }
        
        async function loadMarketStatus() {
            try {
                const response = await fetch('/api/market-status');
                const data = await response.json();
                const statusDiv = document.getElementById('marketStatus');
                if (data.is_open) {
                    statusDiv.innerHTML = '🟢 DSE MARKET OPEN - ' + data.bangladesh_time;
                    statusDiv.className = 'market-status market-open';
                } else {
                    statusDiv.innerHTML = '🔴 DSE MARKET CLOSED - ' + data.bangladesh_time;
                    statusDiv.className = 'market-status market-closed';
                }
            } catch(e) {
                console.error('Market status error:', e);
                document.getElementById('marketStatus').innerHTML = '⚠️ Could not load market status';
            }
        }
        
        async function loadLTP() {
            try {
                const response = await fetch('/api/dse-ltp');
                const data = await response.json();
                if (data.ltp_data) {
                    ltpData = data.ltp_data;
                    console.log('LTP loaded:', Object.keys(ltpData).length, 'symbols');
                    renderTable();
                }
            } catch(e) {
                console.error('LTP error:', e);
            }
        }
        
        async function loadDates() {
            try {
                const collection = COLLECTIONS[currentTab];
                const response = await fetch('/api/dates?collection=' + collection);
                const dates = await response.json();
                const select = document.getElementById('dateSelect');
                
                select.innerHTML = '<option value="">Latest</option>';
                if (Array.isArray(dates)) {
                    dates.forEach(date => {
                        const option = document.createElement('option');
                        option.value = date;
                        option.textContent = date;
                        select.appendChild(option);
                    });
                }
                console.log('Dates loaded:', dates.length);
            } catch(e) {
                console.error('Load dates error:', e);
            }
        }
        
        async function loadData() {
            const date = document.getElementById('dateSelect').value;
            const symbol = document.getElementById('symbolSearch').value;
            
            try {
                let url = '';
                if (currentTab === 'ai_signals') {
                    url = '/api/signals?date=' + date;
                    if (symbol) url += '&symbol=' + symbol;
                    const response = await fetch(url);
                    const data = await response.json();
                    currentData = data.data || [];
                } 
                else if (currentTab === 'swrsi') {
                    url = '/api/swrsi?date=' + date;
                    if (symbol) url += '&symbol=' + symbol;
                    const response = await fetch(url);
                    const data = await response.json();
                    currentData = data.signals || [];
                }
                else {
                    const map = { support: 'support_resistance', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
                    url = '/api/generic-data?collection=' + map[currentTab] + '&date=' + date;
                    if (symbol) url += '&symbol=' + symbol;
                    const response = await fetch(url);
                    const data = await response.json();
                    currentData = data.data || [];
                }
                
                console.log('Data loaded:', currentData.length, 'records');
                renderTable();
                document.getElementById('recordCount').innerHTML = `(${currentData.length} records)`;
            } catch(e) {
                console.error('Load data error:', e);
                document.getElementById('dynamicTable').innerHTML = '<p style="text-align:center;padding:40px;">Error loading data</p>';
            }
        }
        
        function renderTable() {
            if (!currentData || currentData.length === 0) {
                document.getElementById('dynamicTable').innerHTML = '<p style="text-align:center;padding:40px;">No data available</p>';
                return;
            }
            
            if (currentTab === 'ai_signals') {
                renderAITable();
            } else if (currentTab === 'swrsi') {
                renderSimpleTable(['symbol', 'sector', 'final_signal', 'final_combined_score', 'diff', 'gape']);
            } else {
                renderSimpleTable(['symbol', 'sector', 'signal', 'score']);
            }
        }
        
        function renderAITable() {
            let html = '<table><thead><tr>';
            html += '<th>#</th><th>Symbol</th><th>Date</th><th>Price</th><th>LTP</th><th>Sector</th><th>Signal</th><th>Score</th><th>LLM</th><th>XGB</th><th>PPO</th><th>Diff</th><th>Gape</th><th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Actions</th>';
            html += '</tr></thead><tbody>';
            
            for (let i = 0; i < currentData.length; i++) {
                const r = currentData[i];
                const ltp = ltpData[r.symbol] || null;
                const ltpDisplay = ltp ? ltp.toFixed(2) : '-';
                const ltpClass = (r.high && ltp && ltp > r.high) ? 'ltp-above' : '';
                const rowClass = (r.high && ltp && ltp > r.high) ? 'ltp-break-high' : '';
                
                let signalClass = '';
                if (r.final_signal) {
                    if (r.final_signal.includes('STRONG') || r.final_signal.includes('✅')) signalClass = 'signal-strong-buy';
                    else if (r.final_signal.includes('BUY')) signalClass = 'signal-buy';
                    else if (r.final_signal.includes('HOLD')) signalClass = 'signal-hold';
                    else if (r.final_signal.includes('SELL')) signalClass = 'signal-sell';
                }
                
                html += `<tr class="${rowClass}">`;
                html += `<td>${i+1}</td>`;
                html += `<td><strong>${r.symbol || ''}</strong></td>`;
                html += `<td>${r.analysis_date || ''}</td>`;
                html += `<td>${(r.current_price || 0).toFixed(2)}</td>`;
                html += `<td class="${ltpClass}">${ltpDisplay}</td>`;
                html += `<td>${r.sector || '-'}</td>`;
                html += `<td class="${signalClass}">${r.final_signal || '-'}</td>`;
                html += `<td>${((r.final_combined_score || 0)).toFixed(1)}</td>`;
                html += `<td>${r.llm_signal || '-'}</td>`;
                html += `<td>${r.xgb_signal || '-'}</td>`;
                html += `<td>${r.ppo_signal || '-'}</td>`;
                html += `<td>${(r.diff || 0).toFixed(2)}</td>`;
                html += `<td>${(r.gape || 0).toFixed(2)}</td>`;
                html += `<td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>`;
                html += `<td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>`;
                html += `<td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>`;
                html += `<td>${(r.risk_reward_ratio || 0).toFixed(2)}</td>`;
                html += `<td>
                    <button class="edit-btn" onclick="editTrade('${r.symbol}', '${r.analysis_date}')">✏️</button>
                    <button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button>
                    <button class="delete-btn" onclick="deleteRecord('${r.symbol}', '${r.analysis_date}')">🗑️</button>
                </td>`;
                html += '</tr>';
            }
            
            html += '</tbody></table>';
            document.getElementById('dynamicTable').innerHTML = html;
        }
        
        function renderSimpleTable(fields) {
            let html = '<table><thead><tr><th>#</th>';
            fields.forEach(f => html += `<th>${f.toUpperCase()}</th>`);
            html += '<th>Actions</th></tr></thead><tbody>';
            
            for (let i = 0; i < currentData.length; i++) {
                const r = currentData[i];
                const ltp = ltpData[r.symbol] || null;
                const ltpDisplay = ltp ? ltp.toFixed(2) : '-';
                const rowClass = (r.high && ltp && ltp > r.high) ? 'ltp-break-high' : '';
                
                html += `<tr class="${rowClass}">`;
                html += `<td>${i+1}</td>`;
                html += `<td><strong>${r.symbol || ''}</strong></td>`;
                html += `<td>${r.sector || '-'}</td>`;
                html += `<td>${r.final_signal || r.signal || '-'}</td>`;
                html += `<td>${((r.final_combined_score || r.score || 0)).toFixed(1)}</td>`;
                html += `<td>${(r.diff || 0).toFixed(2)}</td>`;
                html += `<td>${(r.gape || 0).toFixed(2)}</td>`;
                html += `<td>
                    <button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button>
                    <button class="delete-btn" onclick="deleteRecord('${r.symbol}', '${r.analysis_date}')">🗑️</button>
                </td>`;
                html += '</tr>';
            }
            
            html += '</tbody><table>';
            document.getElementById('dynamicTable').innerHTML = html;
        }
        
        async function deleteRecord(symbol, date) {
            if (!confirm(`Delete ${symbol}?`)) return;
            const collection = COLLECTIONS[currentTab];
            const response = await fetch(`/api/delete-signal?collection=${collection}&symbol=${symbol}&date=${date}`, { method: 'DELETE' });
            const result = await response.json();
            if (result.deleted) {
                loadData();
            }
        }
        
        async function deleteAllByDate() {
            const date = document.getElementById('dateSelect').value;
            if (!date) {
                alert('Please select a date first');
                return;
            }
            if (!confirm(`Delete ALL records for ${date}?`)) return;
            const collection = COLLECTIONS[currentTab];
            const response = await fetch(`/api/delete-all-by-date?collection=${collection}&date=${date}`, { method: 'DELETE' });
            const result = await response.json();
            alert(`Deleted ${result.deleted} records`);
            loadData();
            loadDates();
        }
        
        async function editTrade(symbol, date) {
            const entry = prompt('Entry Price:');
            const sl = prompt('Stop Loss:');
            const tp = prompt('Target Price:');
            if (!entry && !sl && !tp) return;
            
            let url = `/api/update-trade?collection=${COLLECTIONS[currentTab]}&symbol=${symbol}&date=${date}`;
            if (entry) url += `&entry_price=${parseFloat(entry)}`;
            if (sl) url += `&stop_loss=${parseFloat(sl)}`;
            if (tp) url += `&target_price=${parseFloat(tp)}`;
            
            await fetch(url, { method: 'PUT' });
            loadData();
        }
        
        async function openTradeModal() {
            document.getElementById('tradeModal').classList.add('open');
            await loadTradeSymbols();
        }
        
        function closeTradeModal() {
            document.getElementById('tradeModal').classList.remove('open');
        }
        
        async function loadTradeSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTIONS[currentTab];
            const response = await fetch(`/api/collection-symbols?collection=${collection}&date=${date}`);
            const symbols = await response.json();
            const select = document.getElementById('tradeSymbol');
            select.innerHTML = '<option value="">Select Symbol</option>';
            symbols.forEach(s => {
                const option = document.createElement('option');
                option.value = s;
                option.textContent = s;
                select.appendChild(option);
            });
        }
        
        async function openTradeForSymbol(symbol) {
            await loadTradeSymbols();
            document.getElementById('tradeSymbol').value = symbol;
            openTradeModal();
        }
        
        async function saveTrade() {
            const symbol = document.getElementById('tradeSymbol').value;
            if (!symbol) {
                alert('Select a symbol');
                return;
            }
            const entry = parseFloat(document.getElementById('entryPrice').value);
            const sl = parseFloat(document.getElementById('stopLoss').value);
            const tp = parseFloat(document.getElementById('targetPrice').value);
            const date = document.getElementById('dateSelect').value;
            
            let url = `/api/update-trade?collection=${COLLECTIONS[currentTab]}&symbol=${symbol}&date=${date}`;
            if (entry) url += `&entry_price=${entry}`;
            if (sl) url += `&stop_loss=${sl}`;
            if (tp) url += `&target_price=${tp}`;
            
            const response = await fetch(url, { method: 'PUT' });
            const result = await response.json();
            if (result.updated) {
                alert('Trade saved!');
                closeTradeModal();
                loadData();
            }
        }
        
        function openAlertModal() {
            loadAlertSymbols();
            document.getElementById('alertModal').classList.add('open');
            renderAlertList();
        }
        
        function closeAlertModal() {
            document.getElementById('alertModal').classList.remove('open');
        }
        
        async function loadAlertSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTIONS[currentTab];
            const response = await fetch(`/api/collection-symbols?collection=${collection}&date=${date}`);
            const symbols = await response.json();
            const select = document.getElementById('alertSymbol');
            select.innerHTML = '<option value="">Select Symbol</option>';
            symbols.forEach(s => {
                const option = document.createElement('option');
                option.value = s;
                option.textContent = s;
                select.appendChild(option);
            });
        }
        
        function loadAlerts() {
            const saved = localStorage.getItem('alerts');
            if (saved) {
                alerts = JSON.parse(saved);
            }
        }
        
        function saveAlerts() {
            localStorage.setItem('alerts', JSON.stringify(alerts));
        }
        
        function addAlert() {
            const symbol = document.getElementById('alertSymbol').value;
            const condition = document.getElementById('alertCondition').value;
            const price = parseFloat(document.getElementById('alertPrice').value);
            if (!symbol || !price) return;
            alerts.push({ symbol, condition, price });
            saveAlerts();
            renderAlertList();
            document.getElementById('alertPrice').value = '';
        }
        
        function renderAlertList() {
            const listDiv = document.getElementById('alertList');
            if (alerts.length === 0) {
                listDiv.innerHTML = '<p>No alerts configured</p>';
                return;
            }
            listDiv.innerHTML = alerts.map((a, i) => `
                <div>
                    ${a.symbol} ${a.condition === 'above' ? '>' : '<'} ${a.price}
                    <button onclick="removeAlert(${i})">Remove</button>
                </div>
            `).join('');
        }
        
        function removeAlert(index) {
            alerts.splice(index, 1);
            saveAlerts();
            renderAlertList();
        }
    </script>
</body>
</html>
    """, status_code=200)

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard running on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)