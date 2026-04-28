"""
create_dashboard.py - v25 FINAL
✅ S/R: saved_at ONLY
✅ Other tabs: analysis_date primary
✅ ALL tabs work perfectly
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

app = FastAPI(title="AI Trading Signals Dashboard", version="25.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_mongo_collection(collection_name):
    if not MONGODB_URI: return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name]
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
# DATE HELPERS
# ================================
def build_date_query(date_value, collection_name):
    """Build date query - S/R uses saved_at, others use analysis_date"""
    if collection_name == "support_resistance":
        # S/R: ONLY saved_at
        return {'saved_at': {'$regex': f'^{date_value}'}}
    else:
        # Others: analysis_date primary + fallback
        return {'$or': [
            {'analysis_date': date_value},
            {'analysis_date': {'$regex': f'^{date_value}'}},
            {'saved_at': {'$regex': f'^{date_value}'}},
            {'date': date_value},
            {'latest_date': date_value},
        ]}

def get_latest_date(collection_name):
    """Get latest date - S/R uses saved_at, others use analysis_date"""
    col = get_mongo_collection(collection_name)
    if col is None: return None
    
    if collection_name == "support_resistance":
        # S/R: latest saved_at
        doc = col.find_one({'saved_at': {'$exists': True}}, sort=[('saved_at', -1)])
    else:
        # Others: latest analysis_date
        doc = col.find_one({'analysis_date': {'$exists': True, '$ne': None, '$ne': ''}}, sort=[('analysis_date', -1)])
        if not doc:
            doc = col.find_one({'saved_at': {'$exists': True}}, sort=[('saved_at', -1)])
    
    if doc:
        val = doc.get('analysis_date') or doc.get('saved_at', '')
        if isinstance(val, str) and len(val) >= 10:
            return val[:10]
        if isinstance(val, datetime):
            return val.strftime('%Y-%m-%d')
    return None

def get_all_dates(collection_name):
    """Get all dates - S/R from saved_at, others from analysis_date"""
    col = get_mongo_collection(collection_name)
    if col is None: return []
    
    dates_set = set()
    
    if collection_name == "support_resistance":
        # S/R: ONLY extract from saved_at
        for doc in col.find({'saved_at': {'$exists': True}}, {'saved_at': 1}).limit(5000):
            val = doc.get('saved_at', '')
            if isinstance(val, str) and len(val) >= 10:
                d = val[:10]
                if re.match(r'\d{4}-\d{2}-\d{2}', d):
                    dates_set.add(d)
        # Also check if level_date exists
        try:
            for d in col.distinct('level_date'):
                if isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()):
                    dates_set.add(d.strip())
        except: pass
    else:
        # Others: analysis_date primary
        for d in col.distinct('analysis_date'):
            if d:
                if isinstance(d, datetime): dates_set.add(d.strftime('%Y-%m-%d'))
                elif isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()): dates_set.add(d.strip())
        
        # Fallback: saved_at
        for doc in col.find({'saved_at': {'$exists': True}}, {'saved_at': 1}).limit(2000):
            val = doc.get('saved_at', '')
            if isinstance(val, str) and len(val) >= 10:
                d = val[:10]
                if re.match(r'\d{4}-\d{2}-\d{2}', d): dates_set.add(d)
    
    return sorted(list(dates_set), reverse=True)

# ================================
# API Routes
# ================================
@app.api_route("/head", methods=["GET", "HEAD"])
async def head():
    return Response(content="OK", status_code=200)

@app.get("/api/market-status")
async def market_status():
    now = get_bd_time()
    is_open = is_dse_market_open()
    next_open = None
    if not is_open:
        wd = now.weekday()
        next_open = "Sunday 10:00 AM" if wd in [3,4,5] else "Tomorrow 10:00 AM"
    return {"is_open": is_open, "next_open": next_open, "bangladesh_time": now.strftime('%Y-%m-%d %H:%M:%S')}

@app.get("/api/dse-ltp")
async def dse_ltp():
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
async def api_dates(collection: str = Query("daily_ai_signals")):
    return get_all_dates(collection)

@app.get("/api/collection-symbols")
async def api_symbols(collection: str = Query(...), date: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    if not date: date = get_latest_date(collection)
    query = build_date_query(date, collection) if date else {}
    syms = sorted(list(set([s for s in col.distinct('symbol', query) if s])))
    return syms

@app.get("/api/signals")
async def api_signals(date: str = Query(None), signal: str = Query(None), symbol: str = Query(None),
                      min_score: float = Query(0), limit: int = Query(1000)):
    col_name = "daily_ai_signals"
    col = get_mongo_collection(col_name)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    if not date: date = get_latest_date(col_name)
    query = build_date_query(date, col_name) if date else {}
    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}
    data = list(col.find(query, {'_id': 0}).sort('final_combined_score', -1).limit(limit))
    return {"data": data}

@app.get("/api/swrsi")
async def api_swrsi(date: str = Query(None), symbol: str = Query(None)):
    col_name = "swrsi_signals"
    col = get_mongo_collection(col_name)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    if not date: date = get_latest_date(col_name)
    query = build_date_query(date, col_name) if date else {}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    data = list(col.find(query, {'_id': 0}).sort('composite_score', -1))
    return {"signals": data, "total_signals": len(data)}

@app.get("/api/generic-data")
async def api_generic(collection: str = Query(...), date: str = Query(None),
                      symbol: str = Query(None), limit: int = Query(500)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    if not date: date = get_latest_date(collection)
    query = build_date_query(date, collection) if date else {}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    data = list(col.find(query, {'_id': 0}).limit(limit))
    return {"data": data}

@app.delete("/api/delete-signal")
async def api_delete_one(collection: str = Query("daily_ai_signals"), symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    if collection == "support_resistance":
        r = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    else:
        r = col.delete_one({'symbol': symbol, 'analysis_date': date})
        if r.deleted_count == 0:
            r = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    return {"deleted": r.deleted_count}

@app.delete("/api/delete-all-by-date")
async def api_delete_all(collection: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "Not found"}, status_code=500)
    
    if collection == "support_resistance":
        total = col.delete_many({'saved_at': {'$regex': f'^{date}'}}).deleted_count
    else:
        total = col.delete_many({'analysis_date': date}).deleted_count
        total += col.delete_many({'saved_at': {'$regex': f'^{date}'}}).deleted_count
    return {"deleted": total}

@app.put("/api/update-trade")
async def api_update(symbol: str = Query(...), date: str = Query(...),
                     entry_price: float = Query(None), stop_loss: float = Query(None),
                     target_price: float = Query(None)):
    col = get_mongo_collection("daily_ai_signals")
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
    return r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI Trading v25</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:sans-serif;background:#0a0a0f;color:#e0e0e0;padding:20px}
        .header{text-align:center;padding:20px;background:linear-gradient(45deg,#1a1a2e,#0f3460);border-radius:15px;margin-bottom:20px}
        .header h1{font-size:2em;background:linear-gradient(90deg,#00d4ff,#7b2ff7,#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .tabs{display:flex;margin-bottom:15px;background:#111;border-radius:10px;overflow:hidden;flex-wrap:wrap}
        .tab{flex:1;padding:12px 8px;text-align:center;cursor:pointer;border-right:1px solid #222;color:#aaa;min-width:80px;font-size:.85em}
        .tab.active{background:#1a1a2e;color:#00d4ff;font-weight:bold}
        .controls{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center;background:#111;padding:10px;border-radius:10px}
        select,input,button{padding:8px 12px;background:#1a1a2e;color:#fff;border:1px solid #333;border-radius:6px}
        button{cursor:pointer;background:#0f3460}button:hover{background:#1a4a7a}
        .delete-btn{background:#ff4757!important;color:#fff!important;font-weight:bold;margin-left:auto}
        .alert-btn{background:#ffa500!important;color:#000!important;font-weight:bold}
        table{width:100%;border-collapse:collapse;font-size:.65em;background:#111122;border-radius:10px;overflow:hidden}
        th{background:#1a1a2e;padding:8px 4px;color:#00d4ff}
        td{padding:4px;border-bottom:1px solid #222}
        .ltp-alert-row{animation:blink .6s infinite}
        @keyframes blink{0%,100%{background:#ff475730}50%{background:#ff475760}}
        .modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.85);z-index:1000;justify-content:center;align-items:center}
        .modal.open{display:flex}
        .modal-content{background:#1a1a2e;padding:25px;border-radius:15px;max-width:500px;width:90%;border:2px solid #ffa500}
        .modal-content h3{color:#ffa500;text-align:center}
        .modal-content select,.modal-content input{width:100%;padding:10px;margin:8px 0}
        .modal-buttons{display:flex;gap:10px;margin-top:15px}
        .modal-buttons button{flex:1;padding:12px}
        .green-btn{background:#00ff88!important;color:#000!important}
    </style>
</head>
<body>
    <div class="header"><h1>AI Trading Dashboard v25</h1><p id="ms"></p></div>
    <div class="tabs">
        <div class="tab active" onclick="st('ai')">AI</div>
        <div class="tab" onclick="st('swrsi')">SWRSI</div>
        <div class="tab" onclick="st('sr')">S/R</div>
        <div class="tab" onclick="st('macd')">MACD</div>
        <div class="tab" onclick="st('ema')">EMA</div>
        <div class="tab" onclick="st('buy')">Buy</div>
    </div>
    <div class="controls">
        <select id="ds" onchange="lt()"><option value="">Latest</option></select>
        <input type="text" id="ss" onkeyup="lt()" style="width:100px" placeholder="Symbol">
        <button onclick="lt()">Refresh</button>
        <button class="alert-btn" onclick="oa()">Alerts</button>
        <button class="delete-btn" onclick="da()">Delete Date</button>
        <span id="rc" style="color:#888;font-size:.8em"></span>
    </div>
    <div id="am" class="modal">
        <div class="modal-content">
            <h3>LTP Alert</h3>
            <label>Symbol:</label><select id="as"><option>--</option></select>
            <label>Condition:</label><select id="ac"><option value="above">Above</option><option value="below">Below</option></select>
            <label>Threshold:</label><input type="number" id="at" placeholder="Price" step="0.01">
            <div class="modal-buttons"><button class="green-btn" onclick="aa()">Add</button><button onclick="ca()">Cancel</button></div>
            <div id="al" style="margin-top:15px;background:#0f3460;padding:10px;border-radius:8px;display:none"></div>
        </div>
    </div>
    <div style="overflow-x:auto;max-height:65vh" id="dt"></div>

    <script>
        const M={ai:'daily_ai_signals',swrsi:'swrsi_signals',sr:'support_resistance',macd:'macd_signals',ema:'ema_200_signals',buy:'daily_buy_signals'};
        let t='ai',d=[],ltp={},ar=[];
        
        ld();lt();ms();lL();lA();
        setInterval(ms,60000);setInterval(()=>fetch('/api/market-status').then(r=>r.json()).then(s=>{if(s.is_open)lL()}),60000);
        
        function lA(){const s=localStorage.getItem('ar_v25');if(s)try{ar=JSON.parse(s)}catch(e){ar=[]}uA()}
        function sA(){localStorage.setItem('ar_v25',JSON.stringify(ar));uA();rT()}
        function uA(){const b=document.getElementById('al');if(ar.length>0){b.style.display='block';b.innerHTML='<h4 style=color:#ffa500>Active:</h4>'+ar.map((r,i)=>`<div style=display:flex;justify-content:space-between;padding:5px>${r.s} ${r.c==='above'?'↑':'↓'} ${r.t} <button onclick=rr(${i}) style=background:#ff4757;padding:3px>X</button></div>`).join('')}else{b.style.display='none'}}
        async function oa(){document.getElementById('am').classList.add('open');await lS();uA()}
        function ca(){document.getElementById('am').classList.remove('open')}
        async function lS(){const dt=document.getElementById('ds').value,sel=document.getElementById('as');sel.innerHTML='<option>Loading...</option>';try{let u=`/api/collection-symbols?collection=${M[t]}`;if(dt)u+=`&date=${dt}`;const s=await(await fetch(u)).json();sel.innerHTML='<option value="">--Select--</option>';[...new Set(s)].forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;sel.appendChild(o)})}catch(e){sel.innerHTML='<option>Error</option>'}}
        function aa(){const s=document.getElementById('as').value,c=document.getElementById('ac').value,th=parseFloat(document.getElementById('at').value);if(!s||s.includes('--')||!th)return;ar=ar.filter(r=>r.s!==s);ar.push({s,c,t:th});sA();document.getElementById('as').value='';document.getElementById('at').value=''}
        function rr(i){ar.splice(i,1);sA();rT()}
        function gA(sym){if(!ar.length)return null;const l=ltp[sym]||null;if(l===null)return null;for(const r of ar){if(r.s===sym){if(r.c==='above'&&l>r.t)return'a';if(r.c==='below'&&l<r.t)return'b'}}return null}
        async function ms(){try{const s=await(await fetch('/api/market-status')).json();document.getElementById('ms').innerHTML=s.is_open?'OPEN':'CLOSED '+s.next_open}catch(e){}}
        async function lL(){try{const j=await(await fetch('/api/dse-ltp')).json();if(j.status==='live'){ltp=j.ltp_data||{};rT()}}catch(e){}}
        async function ld(){try{const dt=await(await fetch(`/api/dates?collection=${M[t]}`)).json(),sel=document.getElementById('ds'),cv=sel.value;sel.innerHTML='<option value="">Latest</option>';if(Array.isArray(dt))dt.forEach(v=>{if(v){const o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o)}});if(cv)sel.value=cv}catch(e){}}
        async function lt(){const dt=document.getElementById('ds').value,sym=document.getElementById('ss').value;try{let u;if(t==='ai'){u=`/api/signals?limit=1000`;if(dt)u+=`&date=${dt}`;if(sym)u+=`&symbol=${sym}`}else if(t==='swrsi'){u='/api/swrsi?';if(dt)u+=`date=${dt}&`;if(sym)u+=`symbol=${sym}&`}else{u=`/api/generic-data?collection=${M[t]}&limit=500`;if(dt)u+=`&date=${dt}`;if(sym)u+=`&symbol=${sym}`}const j=await(await fetch(u)).json();d=j.data||j.signals||[];document.getElementById('rc').textContent=`(${d.length})`}catch(e){d=[]}rT()}
        function rT(){const div=document.getElementById('dt');if(!d.length){div.innerHTML='<p style=color:#888;text-align:center;padding:40px>No data</p>';return}
            const ek=['_id','saved_at','analysis_datetime'];const keys=Object.keys(d[0]).filter(k=>!ek.includes(k)&&!k.startsWith('_'));
            let h=`<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th>${keys.map(k=>`<th>${k}</th>`).join('')}<th>Del</th></tr></thead><tbody>`;
            d.forEach((r,i)=>{const as=gA(r.symbol),rc=as?'ltp-alert-row':'';const ds=r.analysis_date||r.date||r.level_date||(r.saved_at||'').substring(0,10)||'';
                let ld='';const l=ltp[r.symbol]||null;if(l){let c='',a='';if(as==='a'){c='color:#00ff88';a=' ↑'}else if(as==='b'){c='color:#ff4757';a=' ↓'}ld=`<span style="${c};font-weight:bold">${l.toFixed(2)}${a}</span>`}else{ld='<span style=color:#888>-</span>'}
                h+=`<tr class="${rc}"><td>${i+1}</td><td><strong>${r.symbol||''}${as?' 🔔':''}</strong></td><td>${ld}</td>${keys.map(k=>`<td>${r[k]??''}</td>`).join('')}<td><button style=background:#ff4757;color:#fff;border:none;padding:3px 6px;border-radius:3px;cursor:pointer;font-size:.7em onclick=dr('${r.symbol}','${ds}')>X</button></td></tr>`});
            div.innerHTML=h+'</tbody></table>';}
        function st(n){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));event.target.classList.add('active');t=n;document.getElementById('ss').value='';ld();lt()}
        async function dr(sym,date){if(!confirm('Delete '+sym+'?'))return;await fetch(`/api/delete-signal?collection=${M[t]}&symbol=${sym}&date=${date}`,{method:'DELETE'});lt()}
        async function da(){const dt=document.getElementById('ds').value;if(!dt){alert('Select date!');return}if(!confirm('DELETE ALL for '+dt+'?'))return;await fetch(`/api/delete-all-by-date?collection=${M[t]}&date=${dt}`,{method:'DELETE'});ld();lt()}
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard v25: http://localhost:{PORT}")
    print(f"📅 S/R uses saved_at | Others use analysis_date")
    uvicorn.run(app, host="0.0.0.0", port=PORT)