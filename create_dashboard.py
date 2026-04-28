"""
create_dashboard.py - v22 FINAL (MATCH with save_to_mongodb.py)
✅ PRIMARY date field: analysis_date (matches save_to_mongodb.py)
✅ FALLBACK: saved_at, date, level_date
✅ ALL tabs work perfectly
✅ LTP Alert Modal + Delete All + Edit buttons
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

app = FastAPI(title="AI Trading Signals Dashboard", version="22.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI: return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name or COLLECTION_NAME]
    except: return None

BD_TIMEZONE = timezone(timedelta(hours=6))

def get_bd_time():
    return datetime.now(BD_TIMEZONE)

def is_dse_market_open():
    now = get_bd_time()
    hour, minute, weekday = now.hour, now.minute, now.weekday()
    return (weekday in [6, 0, 1, 2, 3] and 
            ((hour == 10 and minute >= 0) or (10 < hour < 14) or (hour == 14 and minute <= 20)))

# ================================
# DATE MATCHING: analysis_date PRIMARY (matching save_to_mongodb.py)
# ================================
# save_to_mongodb.py saves: analysis_date = date_column value
# So primary lookup should be analysis_date, then fallback to saved_at, date, level_date

def build_date_query(date_value):
    """Build query: analysis_date FIRST, then fallback"""
    conditions = [
        {'analysis_date': date_value},           # PRIMARY (matches save_to_mongodb.py)
        {'analysis_date': {'$regex': f'^{date_value}'}},
        {'saved_at': {'$regex': f'^{date_value}'}},  # FALLBACK
        {'date': date_value},
        {'level_date': date_value},
        {'latest_date': date_value},
    ]
    return {'$or': conditions}

def get_all_dates(collection_name):
    """Get dates: analysis_date FIRST, then fallback to saved_at"""
    col = get_mongo_collection(collection_name)
    if col is None: return []
    
    dates_set = set()
    
    # PRIMARY: analysis_date (matches save_to_mongodb.py)
    try:
        for d in col.distinct('analysis_date'):
            if d:
                if isinstance(d, datetime): dates_set.add(d.strftime('%Y-%m-%d'))
                elif isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()): dates_set.add(d.strip())
    except: pass
    
    # FALLBACK: saved_at
    try:
        docs = col.find({'saved_at': {'$exists': True}}, {'saved_at': 1}).limit(2000)
        for doc in docs:
            val = doc.get('saved_at', '')
            if isinstance(val, str) and len(val) >= 10:
                d = val[:10]
                if re.match(r'\d{4}-\d{2}-\d{2}', d): dates_set.add(d)
    except: pass
    
    # other fields
    for field in ['date', 'level_date', 'latest_date']:
        try:
            for d in col.distinct(field):
                if isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()): dates_set.add(d.strip())
        except: pass
    
    all_dates = sorted(list(dates_set), reverse=True)
    print(f"📅 {collection_name}: {len(all_dates)} dates (analysis_date primary)")
    if all_dates: print(f"   Sample: {all_dates[:5]}")
    return all_dates

# ================================
# API Routes
# ================================
@app.api_route("/head", methods=["GET", "HEAD"])
async def uptime_robot_head():
    return Response(content="OK", status_code=200)

@app.get("/api/market-status")
async def market_status():
    now = get_bd_time()
    is_open = is_dse_market_open()
    if not is_open:
        wd = now.weekday()
        nx = "Sunday 10:00 AM" if wd in [3,4,5] else "Tomorrow 10:00 AM"
    else: nx = None
    return {"is_open": is_open, "next_open": nx, "bangladesh_time": now.strftime('%Y-%m-%d %H:%M:%S')}

@app.get("/api/dse-ltp")
async def get_dse_ltp():
    if not is_dse_market_open(): return {"status": "closed"}
    try:
        resp = requests.get("https://www.dsebd.org/dseX_share.php", headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(resp.content, 'html.parser')
        table = soup.find('table')
        ltp_data = {}
        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    s = cols[0].text.strip()
                    p = cols[1].text.strip().replace(',', '')
                    try: ltp_data[s] = float(p)
                    except: continue
        return {"status": "live", "ltp_data": ltp_data}
    except: return {"status": "error"}

@app.get("/api/dates")
async def get_dates(collection: str = Query("daily_ai_signals")):
    return get_all_dates(collection)

@app.get("/api/collection-symbols")
async def get_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    query = build_date_query(date) if date else {}
    syms = sorted([s for s in col.distinct('symbol', query) if s])
    print(f"📋 {collection}: {len(syms)} symbols for date={date}")
    return syms

@app.get("/api/signals")
async def get_signals(date: str = Query(None), signal: str = Query(None), symbol: str = Query(None),
                      min_score: float = Query(0), limit: int = Query(1000)):
    col = get_mongo_collection()
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    query = build_date_query(date) if date else {}
    if not date:
        latest = list(col.find({'analysis_date': {'$exists': True}}).sort('analysis_date', -1).limit(1))
        if latest and latest[0].get('analysis_date'): query['analysis_date'] = latest[0]['analysis_date']
    
    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}
    
    data = list(col.find(query, {'_id': 0}).sort('final_combined_score', -1).limit(limit))
    return {"data": data}

@app.get("/api/swrsi")
async def get_swrsi(date: str = Query(None), symbol: str = Query(None)):
    col = get_mongo_collection("swrsi_signals")
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    query = build_date_query(date) if date else {}
    if not date:
        latest = list(col.find({'analysis_date': {'$exists': True}}).sort('analysis_date', -1).limit(1))
        if latest and latest[0].get('analysis_date'): query['analysis_date'] = latest[0]['analysis_date']
    
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    data = list(col.find(query, {'_id': 0}).sort('composite_score', -1))
    return {"signals": data, "total_signals": len(data)}

@app.get("/api/generic-data")
async def get_generic_data(collection: str = Query(...), date: str = Query(None),
                           symbol: str = Query(None), limit: int = Query(500)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    query = build_date_query(date) if date else {}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    
    data = list(col.find(query, {'_id': 0}).limit(limit))
    print(f"📊 {collection}: date={date}, records={len(data)}")
    return {"data": data}

@app.delete("/api/delete-signal")
async def delete_signal(collection: str = Query("daily_ai_signals"), symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    r = col.delete_one({'symbol': symbol, 'analysis_date': date})
    if r.deleted_count == 0:
        r = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    if r.deleted_count == 0:
        for f in ['date', 'level_date']:
            r = col.delete_one({'symbol': symbol, f: date})
            if r.deleted_count > 0: break
    return {"deleted": r.deleted_count}

@app.delete("/api/delete-all-by-date")
async def delete_all_by_date(collection: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    total = col.delete_many({'analysis_date': date}).deleted_count
    total += col.delete_many({'saved_at': {'$regex': f'^{date}'}}).deleted_count
    for f in ['date', 'level_date', 'latest_date']:
        total += col.delete_many({f: date}).deleted_count
    return {"deleted": total}

@app.put("/api/update-trade")
async def update_trade(symbol: str = Query(...), date: str = Query(...),
                       entry_price: float = Query(None), stop_loss: float = Query(None),
                       target_price: float = Query(None)):
    col = get_mongo_collection()
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    update = {'edited': True, 'edited_at': datetime.now().isoformat()}
    if entry_price is not None: update['entry_price'] = entry_price
    if stop_loss is not None: update['stop_loss'] = stop_loss
    if target_price is not None: update['target_price'] = target_price
    
    r = col.update_one({'symbol': symbol, 'analysis_date': date}, {'$set': update})
    return {"updated": r.modified_count}

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
    <title>🤖 AI Trading v22</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:'Segoe UI',sans-serif;background:#0a0a0f;color:#e0e0e0;padding:20px}
        .header{text-align:center;padding:20px;background:linear-gradient(45deg,#1a1a2e,#0f3460);border-radius:15px;margin-bottom:20px;border:1px solid #1a3a5c}
        .header h1{font-size:2em;background:linear-gradient(90deg,#00d4ff,#7b2ff7,#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .tabs{display:flex;margin-bottom:15px;background:#111;border-radius:10px;overflow:hidden;flex-wrap:wrap;border:1px solid #222}
        .tab{flex:1;padding:12px 8px;text-align:center;cursor:pointer;border-right:1px solid #222;color:#aaa;min-width:80px;font-size:.85em}
        .tab:last-child{border-right:none}.tab.active{background:#1a1a2e;color:#00d4ff;font-weight:bold}
        .controls{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center;background:#111;padding:10px;border-radius:10px;border:1px solid #222}
        select,input,button{padding:8px 12px;background:#1a1a2e;color:#fff;border:1px solid #333;border-radius:6px;font-size:.85em}
        button{cursor:pointer;background:#0f3460}button:hover{background:#1a4a7a}
        .delete-all-btn{background:#ff4757;color:#fff;font-weight:bold;margin-left:auto}
        .alert-config-btn{background:#ffa500;color:#000;font-weight:bold}
        .alert-config-btn.active-alert{animation:alertPulse 1s infinite}
        @keyframes alertPulse{0%,100%{box-shadow:0 0 5px #ffa500}50%{box-shadow:0 0 20px #ffa500}}
        table{width:100%;border-collapse:collapse;font-size:.65em;background:#111122;border-radius:10px;overflow:hidden}
        th{background:#1a1a2e;padding:8px 4px;color:#00d4ff;white-space:nowrap}
        td{padding:4px;border-bottom:1px solid #222;white-space:nowrap}
        .edit-btn{background:#ffa500;color:#000;border:none;padding:3px 6px;border-radius:3px;cursor:pointer;font-size:.7em;margin:1px}
        .delete-btn{background:#ff4757;color:#fff;border:none;padding:3px 6px;border-radius:3px;cursor:pointer;font-size:.7em;margin:1px}
        .save-btn{background:#00ff88;color:#000;border:none;padding:3px 6px;border-radius:3px;cursor:pointer;font-size:.7em;margin:1px}
        .signal-SB{color:#00ff88;font-weight:bold}.signal-B{color:#00cc66;font-weight:bold}
        .signal-H{color:#ffd700}.signal-S{color:#ff4757}.signal-SS{color:red;font-weight:bold}
        .ltp-alert-row{animation:ltpBlink .6s infinite}
        @keyframes ltpBlink{0%,100%{background:#ff475730}50%{background:#ff475760}}
        .ltp-above{color:#00ff88!important;font-weight:bold}
        .ltp-below{color:#ff4757!important;font-weight:bold}
        .modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.85);z-index:1000;justify-content:center;align-items:center}
        .modal.open{display:flex}
        .modal-content{background:#1a1a2e;padding:25px;border-radius:15px;max-width:500px;width:90%;border:2px solid #ffa500}
        .modal-content h3{color:#ffa500;margin-bottom:15px;text-align:center}
        .modal-content label{display:block;margin:10px 0 5px;color:#aaa;font-size:.9em}
        .modal-content select,.modal-content input{width:100%;padding:10px;margin-bottom:8px}
        .modal-buttons{display:flex;gap:10px;margin-top:15px}
        .modal-buttons button{flex:1;padding:12px}
        .save-alert-btn{background:#00ff88;color:#000;font-weight:bold}
        .debug-info{font-size:.7em;color:#666;margin-top:10px;padding:8px;background:#111;border-radius:5px}
    </style>
</head>
<body>
    <div class="header"><h1>🤖 AI Trading Dashboard v22</h1><p id="marketStatus">Checking...</p></div>
    <div class="tabs">
        <div class="tab active" onclick="switchTab('ai_signals')">🤖 AI</div>
        <div class="tab" onclick="switchTab('swrsi')">🔍 SWRSI</div>
        <div class="tab" onclick="switchTab('support')">📊 S/R</div>
        <div class="tab" onclick="switchTab('macd')">📉 MACD</div>
        <div class="tab" onclick="switchTab('ema')">📈 EMA</div>
        <div class="tab" onclick="switchTab('buy')">✅ Buy</div>
    </div>
    <div class="controls">
        <label>📅</label>
        <select id="dateSelect" onchange="loadCurrentTab()"><option value="">Latest</option></select>
        <input type="text" id="symbolSearch" onkeyup="loadCurrentTab()" style="width:100px" placeholder="Symbol">
        <button onclick="loadCurrentTab()">🔄</button>
        <button class="alert-config-btn" id="abtn" onclick="openAlertModal()">🔔</button>
        <button class="delete-all-btn" onclick="deleteAllByDate()">🗑️ Delete Date</button>
        <span id="recordCount" style="color:#888;font-size:.8em"></span>
    </div>
    <div id="alertModal" class="modal">
        <div class="modal-content">
            <h3>🔔 LTP Alert</h3>
            <p style="color:#888;text-align:center;font-size:.8em" id="amInfo"></p>
            <label>Symbol:</label><select id="asel"><option>--</option></select>
            <label>Condition:</label><select id="acond"><option value="above">LTP Above</option><option value="below">LTP Below</option></select>
            <label>Threshold:</label><input type="number" id="athr" placeholder="Price" step="0.01">
            <div class="modal-buttons"><button class="save-alert-btn" onclick="addAlert()">➕ Add</button><button onclick="closeAlertModal()">Cancel</button></div>
            <div id="acur" style="display:none;margin-top:15px;background:#0f3460;padding:10px;border-radius:8px">
                <h4 style="color:#ffa500">Active:</h4><div id="alist"></div>
            </div>
        </div>
    </div>
    <div id="abar" style="background:#0f3460;padding:6px 12px;border-radius:6px;margin-bottom:8px;display:none;color:#ffa500;font-size:.8em"></div>
    <div style="overflow-x:auto;max-height:65vh" id="dynamicTable"></div>
    <div class="debug-info" id="debugInfo"></div>

    <script>
        let ct='ai_signals',cd=[],ltp={},er=null,ar=[];
        const M={ai_signals:'daily_ai_signals',swrsi:'swrsi_signals',support:'support_resistance',macd:'macd_signals',ema:'ema_200_signals',buy:'daily_buy_signals'};
        
        loadDates(M[ct]);loadCurrentTab();checkMs();loadLtp();loadAR();
        setInterval(checkMs,60000);setInterval(()=>fetch('/api/market-status').then(r=>r.json()).then(s=>{if(s.is_open)loadLtp()}),60000);setInterval(loadLtp,300000);
        
        function loadAR(){const s=localStorage.getItem('ar_v22');if(s)try{ar=JSON.parse(s)}catch(e){ar=[]}updateAUI()}
        function saveAR(){localStorage.setItem('ar_v22',JSON.stringify(ar));updateAUI();renderCT()}
        function updateAUI(){const b=document.getElementById('abar'),btn=document.getElementById('abtn');if(ar.length>0){b.style.display='block';b.innerHTML='🔔 '+ar.map(r=>`${r.s} ${r.c==='above'?'>':'<'} ${r.t}`).join(' | ');btn.classList.add('active-alert');btn.textContent='🔔('+ar.length+')'}else{b.style.display='none';btn.classList.remove('active-alert');btn.textContent='🔔'}}
        async function openAlertModal(){document.getElementById('amInfo').textContent='Symbols for: '+(document.getElementById('dateSelect').value||'all');document.getElementById('alertModal').classList.add('open');await loadAS();renderCA()}
        function closeAlertModal(){document.getElementById('alertModal').classList.remove('open')}
        async function loadAS(){const d=document.getElementById('dateSelect').value,sel=document.getElementById('asel');sel.innerHTML='<option>Loading...</option>';try{let u=`/api/collection-symbols?collection=${M[ct]}`;if(d)u+=`&date=${d}`;const s=await(await fetch(u)).json();sel.innerHTML='<option value="">-- Select --</option>';if(Array.isArray(s)&&s.length>0){s.forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;sel.appendChild(o)})}else{sel.innerHTML='<option>No symbols</option>'}}catch(e){sel.innerHTML='<option>Error</option>'}}
        function renderCA(){const s=document.getElementById('acur'),l=document.getElementById('alist');if(ar.length===0){s.style.display='none';return}s.style.display='block';l.innerHTML=ar.map((r,i)=>`<div style="display:flex;justify-content:space-between;background:#1a1a2e;padding:8px;margin:5px 0;border-radius:5px;font-size:.8em"><span>🔔 ${r.s} ${r.c==='above'?'↑':'↓'} ${r.t}</span><button style="background:#ff4757;padding:5px 10px;font-size:.8em" onclick="removeAR(${i})">✕</button></div>`).join('')}
        function addAlert(){const s=document.getElementById('asel').value,c=document.getElementById('acond').value,t=parseFloat(document.getElementById('athr').value);if(!s||s.includes('--')){alert('Select symbol');return}if(!t){alert('Enter price');return}ar=ar.filter(r=>r.s!==s);ar.push({s,c,t});saveAR();renderCA();document.getElementById('asel').value='';document.getElementById('athr').value=''}
        function removeAR(i){ar.splice(i,1);saveAR();renderCA();renderCT()}
        function getAS(sym){if(!ar.length)return null;const l=ltp[sym]||null;if(l===null)return null;for(const r of ar){if(r.s===sym){if(r.c==='above'&&l>r.t)return'above';if(r.c==='below'&&l<r.t)return'below'}}return null}
        async function checkMs(){try{const s=await(await fetch('/api/market-status')).json();document.getElementById('marketStatus').innerHTML=s.is_open?`🟢 OPEN | ${s.bangladesh_time||''}`:`🔴 CLOSED | ${s.next_open||''}`}catch(e){}}
        async function loadLtp(){try{const j=await(await fetch('/api/dse-ltp')).json();if(j.status==='live'){ltp=j.ltp_data||{};renderCT()}}catch(e){}}
        async function loadDates(c){try{const d=await(await fetch(`/api/dates?collection=${c}`)).json(),sel=document.getElementById('dateSelect'),cv=sel.value;sel.innerHTML='<option value="">Latest</option>';if(Array.isArray(d))d.forEach(v=>{if(v){const o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o)}});if(cv&&Array.from(sel.options).some(o=>o.value===cv))sel.value=cv;document.getElementById('debugInfo').textContent=`📅 ${c}: ${d.length} dates`}catch(e){}}
        async function loadCurrentTab(){const date=document.getElementById('dateSelect').value,sym=document.getElementById('symbolSearch').value;try{let u;if(ct==='ai_signals'){u='/api/signals?limit=1000';if(date)u+=`&date=${date}`;if(sym)u+=`&symbol=${sym}`}else if(ct==='swrsi'){u='/api/swrsi?';if(date)u+=`date=${date}&`;if(sym)u+=`symbol=${sym}&`}else{u=`/api/generic-data?collection=${M[ct]}&limit=500`;if(date)u+=`&date=${date}`;if(sym)u+=`&symbol=${sym}`}const j=await(await fetch(u)).json();cd=j.data||j.signals||[];document.getElementById('debugInfo').textContent=`📊 ${ct} | Date:${date||'Latest'} | ${cd.length} records`}catch(e){cd=[]}renderCT()}
        function renderCT(){if(ct==='ai_signals')renderAI();else if(ct==='swrsi')renderSW();else renderGen()}
        function switchTab(t){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));event.target.classList.add('active');ct=t;document.getElementById('symbolSearch').value='';loadDates(M[t]);loadCurrentTab()}
        function getSC(s){if(!s)return'';if(s.includes('STRONG BUY')||s.includes('Strong Buy'))return'signal-SB';if(s.includes('BUY')||s.includes('Buy'))return'signal-B';if(s.includes('HOLD')||s.includes('Hold'))return'signal-H';if(s.includes('STRONG SELL')||s.includes('Strong Sell'))return'signal-SS';if(s.includes('SELL')||s.includes('Sell'))return'signal-S';return''}
        function getLD(sym){const l=ltp[sym]||null,as=getAS(sym);if(!l)return'<span style="color:#888">-</span>';let c='',a='';if(as==='above'){c='ltp-above';a=' ↑'}else if(as==='below'){c='ltp-below';a=' ↓'}return`<span class="${c}" style="font-weight:bold">${l.toFixed(2)}${a}</span>`}
        function getDR(r){return r.analysis_date||(r.saved_at||'').substring(0,10)||r.date||r.level_date||''}
        function startEdit(s,d,e,sl,tp,i){er={symbol:s,date:d};renderCT()}
        function cancelEdit(){er=null;renderCT()}
        async function saveEdit(sym,date){const id=sym.replace(/[^a-zA-Z0-9]/g,'_');const e=parseFloat(document.getElementById(`ee-${id}`)?.value)||0;const sl=parseFloat(document.getElementById(`esl-${id}`)?.value)||0;const tp=parseFloat(document.getElementById(`etp-${id}`)?.value)||0;await fetch(`/api/update-trade?symbol=${sym}&date=${date}&entry_price=${e}&stop_loss=${sl}&target_price=${tp}`,{method:'PUT'});er=null;loadCurrentTab()}
        async function deleteAllByDate(){const d=document.getElementById('dateSelect').value;if(!d){alert('Select date!');return}const c=M[ct];if(!confirm(`DELETE ALL for ${d} in ${c}?`))return;const j=await(await fetch(`/api/delete-all-by-date?collection=${c}&date=${d}`,{method:'DELETE'})).json();alert(`Deleted ${j.deleted}`);loadDates(c);loadCurrentTab()}
        async function deleteRecord(sym,date){if(!confirm(`Delete ${sym}?`))return;await fetch(`/api/delete-signal?collection=${M[ct]}&symbol=${sym}&date=${date}`,{method:'DELETE'});loadCurrentTab()}
        
        function renderAI(){
            const div=document.getElementById('dynamicTable');
            if(!cd.length){div.innerHTML='<p style="color:#888;text-align:center;padding:40px">No data</p>';return}
            let h='<table><thead><tr><th>#</th><th>Symbol</th><th>Date</th><th>Price</th><th>LTP</th><th>Sector</th><th>Signal</th><th>Score</th><th>LLM</th><th>LLM%</th><th>XGB</th><th>XGB%</th><th>PPO</th><th>Ag</th><th>E Acc</th><th>Entry</th><th>SL</th><th>TP</th><th>R:R</th><th>Act</th></tr></thead><tbody>';
            cd.forEach((r,i)=>{
                const id=(r.symbol||'').replace(/[^a-zA-Z0-9]/g,'_'),ie=er&&er.symbol===r.symbol;
                const as=getAS(r.symbol),rc=as?'ltp-alert-row':'',ds=getDR(r);
                const ec=ie?`<input class="editable-input" id="ee-${id}" value="${(r.entry_price||0).toFixed(2)}">`:(r.entry_price||0).toFixed(2);
                const sc=ie?`<input class="editable-input" id="esl-${id}" value="${(r.stop_loss||0).toFixed(2)}">`:(r.stop_loss||0).toFixed(2);
                const tc=ie?`<input class="editable-input" id="etp-${id}" value="${(r.target_price||0).toFixed(2)}">`:(r.target_price||0).toFixed(2);
                const ac=ie?`<button class="save-btn" onclick="saveEdit('${r.symbol}','${ds}')">💾</button><button class="delete-btn" onclick="cancelEdit()">❌</button>`:`<button class="edit-btn" onclick="startEdit('${r.symbol}','${ds}','${r.entry_price||0}','${r.stop_loss||0}','${r.target_price||0}')">✏️</button><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${ds}')">🗑️</button>`;
                h+=`<tr class="${rc}"><td>${i+1}</td><td><strong>${r.symbol}${as?' 🔔':''}</strong></td><td>${ds}</td><td>${(r.current_price||0).toFixed(2)}</td><td>${getLD(r.symbol)}</td><td>${r.sector||''}</td><td class="${getSC(r.final_signal)}">${r.final_signal||''}</td><td><strong>${(r.final_combined_score||0).toFixed(1)}</strong></td><td>${r.llm_signal||''}</td><td>${(r.llm_confidence||0).toFixed(0)}%</td><td>${r.xgb_signal||''}</td><td>${(r.xgb_confidence||0).toFixed(0)}%</td><td>${r.ppo_signal||''}</td><td>${(r.agentic_score||0).toFixed(1)}</td><td>${(r.elliott_accuracy||0).toFixed(1)}%</td><td>${ec}</td><td>${sc}</td><td>${tc}</td><td>${r.risk_reward_ratio||0}</td><td>${ac}</td></tr>`;
            });
            div.innerHTML=h+'</tbody></table>';
            document.getElementById('recordCount').textContent=`(${cd.length})`;
        }
        
        function renderSW(){
            const div=document.getElementById('dynamicTable');
            if(!cd.length){div.innerHTML='<p style="color:#888;text-align:center;padding:40px">No data</p>';return}
            let h='<table><thead><tr><th>#</th><th>Symbol</th><th>Sector</th><th>LTP</th><th>Score</th><th>W Div</th><th>W Score</th><th>Drop%</th><th>RSI Gain</th><th>D Div</th><th>🗑️</th></tr></thead><tbody>';
            cd.forEach((r,i)=>{const as=getAS(r.symbol),ds=getDR(r);h+=`<tr class="${as?'ltp-alert-row':''}"><td>${i+1}</td><td><strong>${r.symbol||''}${as?' 🔔':''}</strong></td><td>${r.sector||''}</td><td>${getLD(r.symbol)}</td><td>${(r.composite_score||0).toFixed(0)}</td><td>${r.weekly_divergence||''}</td><td>${r.weekly_strength_score||0}</td><td>${(r.weekly_price_drop_pct||0).toFixed(2)}%</td><td>+${(r.weekly_rsi_gain||0).toFixed(2)}</td><td>${r.daily_divergence_type||''}</td><td><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${ds}')">🗑️</button></td></tr>`});
            div.innerHTML=h+'</tbody></table>';
            document.getElementById('recordCount').textContent=`(${cd.length})`;
        }
        
        function renderGen(){
            const div=document.getElementById('dynamicTable');
            if(!cd.length){div.innerHTML='<p style="color:#888;text-align:center;padding:40px">No data for this date</p>';document.getElementById('recordCount').textContent='(0)';return}
            const ek=['_id','saved_at','analysis_datetime'];
            const keys=Object.keys(cd[0]).filter(k=>!ek.includes(k)&&!k.startsWith('_'));
            let h=`<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th>${keys.map(k=>`<th>${k}</th>`).join('')}<th>🗑️</th></tr></thead><tbody>`;
            cd.forEach((r,i)=>{const as=getAS(r.symbol),rc=as?'ltp-alert-row':'',ds=getDR(r);h+=`<tr class="${rc}"><td>${i+1}</td><td><strong>${r.symbol||''}${as?' 🔔':''}</strong></td><td>${getLD(r.symbol)}</td>${keys.map(k=>`<td>${r[k]??''}</td>`).join('')}<td><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${ds}')">🗑️</button></td></tr>`});
            div.innerHTML=h+'</tbody></table>';
            document.getElementById('recordCount').textContent=`(${cd.length})`;
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard v22: http://localhost:{PORT}")
    print(f"📅 S/R dates: http://localhost:{PORT}/api/dates?collection=support_resistance")
    uvicorn.run(app, host="0.0.0.0", port=PORT)