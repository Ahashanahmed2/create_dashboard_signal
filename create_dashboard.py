"""
create_dashboard.py
✅ All Tabs with LTP + No Duplicate Date
✅ DSE Market: Sun-Thu 10AM-2:20PM (Bangladesh Time UTC+6)
✅ DSE Website Market Status Check - FIXED
✅ AI Signals (37 cols) + SWRSI + S/R + EMA 21 + Daily Buy
✅ S/R date selector FIXED (uses analysis_date like all other tabs)
✅ LTP Alert Modal + Delete All + Edit buttons
✅ Trade Management Modal with Entry/SL/TP/Exposure/Risk%
✅ Auto-calculated RRR column in all tabs
✅ UptimeRobot HEAD endpoint
✅ LTP > High Breakout Row Highlight (GREEN)
✅ Default Sort: diff ASC, gape DESC
✅ LTP Data Available Even When Market Closed
✅ Tabs working fixed
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
import time

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="18.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

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

# ================================
# DSE WEBSITE MARKET STATUS
# ================================
def is_dse_market_open():
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
        try:
            response = session.get('https://www.dsebd.org/', timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                text = soup.get_text()
                if 'Market Closed' in text or 'CLOSED' in text.upper():
                    return False
                if 'Market Open' in text or 'OPEN' in text.upper():
                    return True
        except:
            pass
        return _is_dse_market_open_by_time()
    except:
        return _is_dse_market_open_by_time()

def _is_dse_market_open_by_time():
    now = get_bd_time()
    hour, minute, weekday = now.hour, now.minute, now.weekday()
    if weekday in [4, 5]:
        return False
    if weekday in [6, 0, 1, 2, 3]:
        current_time = hour * 60 + minute
        market_open_time = 10 * 60
        market_close_time = 14 * 60 + 20
        if market_open_time <= current_time <= market_close_time:
            return True
    return False

# ================================
# API Routes
# ================================
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
    is_open = is_dse_market_open()
    return {
        "is_open": is_open,
        "bangladesh_time": now.strftime('%Y-%m-%d %H:%M:%S')
    }

# ================================
# LTP DATA
# ================================
ltp_cache = {"data": {}, "timestamp": None}

@app.get("/api/dse-ltp")
async def get_dse_ltp(force: int = Query(None)):
    market_is_open = is_dse_market_open()
    force_refresh = force is not None

    if not force_refresh and ltp_cache["timestamp"]:
        age = (get_bd_time() - ltp_cache["timestamp"]).total_seconds()
        if market_is_open:
            if age < 30 and ltp_cache["data"]:
                print(f"[LTP] Using cache ({age:.0f}s old)")
                return ltp_cache["data"]
        else:
            if age < 300 and ltp_cache["data"]:
                print(f"[LTP] Using cache ({age:.0f}s old) - market closed")
                return ltp_cache["data"]

    ltp_data = {}
    data_fetched = False
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cache-Control': 'no-cache',
    })

    # PRIMARY: DSEX Share Page
    try:
        print("[LTP] Trying DSEX Share page...")
        response = session.get('https://www.dsebd.org/dseX_share.php', timeout=15)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find table
            table = soup.find('table', class_='shares-table')
            if not table:
                table = soup.find('table', class_='table-bordered')
            if not table:
                tables = soup.find_all('table')
                for t in tables:
                    if len(t.find_all('tr')) > 10:
                        table = t
                        break

            if table:
                rows = table.find_all('tr')
                print(f"[LTP] DSEX page: Found {len(rows)} rows")

                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 3:
                        try:
                            symbol = None
                            a_tag = cols[1].find('a')
                            if a_tag:
                                symbol = a_tag.text.strip()
                            else:
                                text = cols[1].get_text(strip=True)
                                match = re.match(r'^([A-Za-z0-9\-\.\(\)]+)', text)
                                if match:
                                    symbol = match.group(1)

                            if symbol and len(symbol) >= 2:
                                ltp_text = cols[2].get_text(strip=True)
                                ltp_text = re.sub(r'[^\d.]', '', ltp_text)
                                if ltp_text:
                                    ltp = float(ltp_text)
                                    if 0.1 < ltp < 50000:
                                        ltp_data[symbol.upper()] = ltp
                                        data_fetched = True
                        except:
                            continue

                if data_fetched:
                    print(f"[LTP] ✅ DSEX Page: {len(ltp_data)} symbols")
                    result = {
                        "status": "live" if market_is_open else "closed_with_data",
                        "total_symbols": len(ltp_data),
                        "ltp_data": ltp_data,
                        "source": "dsex_share_page"
                    }
                    ltp_cache["data"] = result
                    ltp_cache["timestamp"] = get_bd_time()
                    return result

    except Exception as e:
        print(f"[LTP] DSEX method failed: {e}")

    # FALLBACK 1: AJAX Scroller
    if not data_fetched:
        try:
            print("[LTP] Trying AJAX scroller...")
            response = session.get(
                'https://www.dsebd.org/latest_share_price_scroll_l.php',
                headers={'X-Requested-With': 'XMLHttpRequest'},
                timeout=10
            )

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                for table in soup.find_all('table'):
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 3:
                            try:
                                symbol = None
                                a_tag = cols[1].find('a')
                                if a_tag:
                                    symbol = a_tag.text.strip()
                                else:
                                    text = cols[1].get_text(strip=True)
                                    if text and len(text) >= 2:
                                        symbol = text

                                if symbol:
                                    ltp_text = cols[2].get_text(strip=True).replace(',', '')
                                    ltp = float(ltp_text)
                                    if 0.1 < ltp < 50000:
                                        ltp_data[symbol.upper()] = ltp
                                        data_fetched = True
                            except:
                                continue

                if data_fetched:
                    print(f"[LTP] ✅ AJAX: {len(ltp_data)} symbols")
                    result = {
                        "status": "live" if market_is_open else "closed_with_data",
                        "total_symbols": len(ltp_data),
                        "ltp_data": ltp_data,
                        "source": "ajax_scroller"
                    }
                    ltp_cache["data"] = result
                    ltp_cache["timestamp"] = get_bd_time()
                    return result

        except Exception as e:
            print(f"[LTP] AJAX failed: {e}")

    # FALLBACK 2: Mobile API
    if not data_fetched:
        try:
            print("[LTP] Trying mobile API...")
            response = session.get('https://www.dsebd.org/mobile.php', timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                for table in soup.find_all('table'):
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            try:
                                symbol = cols[0].get_text(strip=True)
                                ltp_text = cols[1].get_text(strip=True).replace(',', '')
                                ltp = float(ltp_text)
                                if symbol and ltp and 0.1 < ltp < 50000:
                                    ltp_data[symbol.upper()] = ltp
                                    data_fetched = True
                            except:
                                continue

                if data_fetched:
                    print(f"[LTP] ✅ Mobile: {len(ltp_data)} symbols")
                    result = {
                        "status": "live" if market_is_open else "closed_with_data",
                        "total_symbols": len(ltp_data),
                        "ltp_data": ltp_data,
                        "source": "mobile_api"
                    }
                    ltp_cache["data"] = result
                    ltp_cache["timestamp"] = get_bd_time()
                    return result

        except Exception as e:
            print(f"[LTP] Mobile failed: {e}")

    # Cache fallback
    if ltp_cache["data"] and ltp_cache["data"].get("ltp_data"):
        print(f"[LTP] ⚠️ Using cached data")
        cached = ltp_cache["data"].copy()
        cached["source"] = "cache_fallback"
        return cached

    print("[LTP] ❌ All methods failed")
    return {
        "status": "error",
        "message": "DSE থেকে LTP ডাটা পাওয়া যায়নি",
        "ltp_data": {},
        "source": "none",
        "total_symbols": 0
    }

# ================================
# MongoDB Query Helpers
# ================================
def build_date_query(date_value):
    return {'$or': [
        {'analysis_date': date_value},
        {'analysis_date': {'$regex': f'^{date_value}'}},
        {'saved_at': {'$regex': f'^{date_value}'}},
    ]}

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
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    dates_set = set()
    try:
        for d in col.distinct('analysis_date'):
            if d:
                if isinstance(d, datetime): dates_set.add(d.strftime('%Y-%m-%d'))
                elif isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()): dates_set.add(d.strip())
    except: pass
    return sorted(list(dates_set), reverse=True)

@app.get("/api/swrsi/dates")
async def get_swrsi_dates():
    col = get_mongo_collection("swrsi_signals")
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    dates = col.distinct('analysis_date')
    return sorted(dates, reverse=True)

@app.get("/api/signals")
async def get_signals(
    date: str = Query(None), 
    signal: str = Query(None), 
    symbol: str = Query(None), 
    min_score: float = Query(0), 
    limit: int = Query(1000),
    sort_by: str = Query(None),
    sort_order: str = Query("asc")
):
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
    sort_criteria = []
    if sort_by:
        sort_dir = -1 if sort_order == "desc" else 1
        sort_criteria.append((sort_by, sort_dir))
    else:
        sort_criteria = [('diff', 1), ('gape', -1)]
    cursor = collection.find(query, {'_id': 0})
    if sort_criteria:
        cursor = cursor.sort(sort_criteria)
    cursor = cursor.limit(limit)
    return {"data": list(cursor)}

@app.get("/api/swrsi")
async def get_swrsi(
    date: str = Query(None), 
    symbol: str = Query(None),
    sort_by: str = Query(None),
    sort_order: str = Query("asc")
):
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
    sort_criteria = []
    if sort_by:
        sort_dir = -1 if sort_order == "desc" else 1
        sort_criteria.append((sort_by, sort_dir))
    else:
        sort_criteria = [('diff', 1), ('gape', -1)]
    cursor = col.find(query, {'_id': 0})
    if sort_criteria:
        cursor = cursor.sort(sort_criteria)
    data = list(cursor)
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
async def get_generic_data(
    collection: str = Query(...), 
    date: str = Query(None), 
    symbol: str = Query(None), 
    limit: int = Query(500),
    sort_by: str = Query(None),
    sort_order: str = Query("asc")
):
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
    sort_criteria = []
    if sort_by:
        sort_dir = -1 if sort_order == "desc" else 1
        sort_criteria.append((sort_by, sort_dir))
    else:
        sort_criteria = [('diff', 1), ('gape', -1)]
    cursor = col.find(query, {'_id': 0})
    if sort_criteria:
        cursor = cursor.sort(sort_criteria)
    data = list(cursor.limit(limit))
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
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    result1 = col.delete_many({'analysis_date': date})
    result2 = col.delete_many({'saved_at': {'$regex': f'^{date}'}})
    total = result1.deleted_count + result2.deleted_count
    return {"deleted": total, "collection": collection, "date": date}

@app.put("/api/update-trade")
async def update_trade(
    collection: str = Query("daily_ai_signals"),
    symbol: str = Query(...), 
    date: str = Query(...), 
    entry_price: float = Query(None), 
    stop_loss: float = Query(None), 
    target_price: float = Query(None),
    total_exposure: float = Query(None),
    risk_percent: float = Query(None)
):
    col = get_mongo_collection(collection)
    if col is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    update_fields = {'edited': True, 'edited_at': datetime.now().isoformat()}
    if entry_price is not None: update_fields['entry_price'] = entry_price
    if stop_loss is not None: update_fields['stop_loss'] = stop_loss
    if target_price is not None: update_fields['target_price'] = target_price
    if total_exposure is not None: update_fields['total_exposure'] = total_exposure
    if risk_percent is not None: update_fields['risk_percent'] = risk_percent
    if entry_price and stop_loss and target_price:
        risk = abs(entry_price - stop_loss)
        reward = abs(target_price - entry_price)
        if risk > 0:
            update_fields['risk_reward_ratio'] = round(reward / risk, 2)
    result = col.update_one({'symbol': symbol, 'analysis_date': date}, {'$set': update_fields})
    if result.matched_count == 0:
        result = col.update_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}}, {'$set': update_fields})
    return {"updated": result.modified_count, "matched": result.matched_count}

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
    <link rel="manifest" href="/static/manifest.json">
    <meta name="theme-color" content="#00d4ff">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="AI Signals">
    <link rel="icon" href="/static/icon-192.png">
    <link rel="apple-touch-icon" href="/static/icon-192.png">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 30px; background: linear-gradient(45deg, #1a1a2e, #0f3460); border-radius: 15px; margin-bottom: 20px; }
        .header h1 { font-size: 2.2em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .alert-box { background: #ff4757; color: #fff; padding: 15px; border-radius: 10px; margin: 15px 0; text-align: center; font-size: 1.3em; font-weight: bold; display: none; animation: pulse 1s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
        .tabs { display: flex; margin-bottom: 20px; background: #111; border-radius: 10px; overflow: hidden; flex-wrap: wrap; }
        .tab { flex: 1; padding: 12px 8px; text-align: center; cursor: pointer; border-right: 1px solid #222; color: #aaa; min-width: 80px; font-size: 13px; }
        .tab:last-child { border-right: none; }
        .tab.active { background: #1a1a2e; color: #00d4ff; font-weight: bold; }
        .controls { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }
        select, input, button { padding: 10px 15px; background: #1a1a2e; color: #fff; border: 1px solid #333; border-radius: 8px; }
        button { cursor: pointer; background: #0f3460; }
        .delete-all-btn { background: #ff4757; color: #fff; font-weight: bold; }
        .alert-config-btn { background: #ffa500; color: #000; font-weight: bold; }
        .trade-btn { background: #00cc66; color: #000; font-weight: bold; margin-left: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 0.7em; background: #111122; border-radius: 10px; }
        th { background: #1a1a2e; padding: 10px 5px; color: #00d4ff; white-space: nowrap; cursor: pointer; user-select: none; }
        th:hover { background: #1e1e38; }
        th.sorted { color: #ffa500; }
        .sort-indicator { font-size: 0.8em; margin-left: 3px; }
        td { padding: 5px; border-bottom: 1px solid #222; white-space: nowrap; }
        .edit-btn { background: #ffa500; color: #000; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-size: 0.7em; }
        .delete-btn { background: #ff4757; color: #fff; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-size: 0.7em; }
        .save-btn { background: #00ff88; color: #000; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-size: 0.7em; }
        .trade-edit-btn { background: #7b2ff7; color: #fff; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-size: 0.7em; font-weight: bold; min-width: 50px; }
        .edited-badge { background: #ffa500; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px; }
        .trade-badge { background: #cc00cc; color: #fff; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px; }
        .editable-input { background: #1a1a2e; color: #fff; border: 1px solid #ffa500; padding: 3px; width: 65px; border-radius: 4px; font-size: 0.9em; }
        .signal-SB { color: #00ff88; font-weight: bold; }
        .signal-B { color: #00cc66; font-weight: bold; }
        .signal-H { color: #ffd700; }
        .signal-S { color: #ff4757; }
        .ltp-above { color: #00ff88 !important; font-weight: bold; }
        .ltp-below { color: #ff4757 !important; font-weight: bold; }
        .ltp-break-high { background: #00ff8818; border-left: 4px solid #00ff88; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; }
        .modal.open { display: flex; }
        .modal-content { background: #1a1a2e; padding: 25px; border-radius: 15px; max-width: 500px; width: 90%; }
        .trade-summary { background: #0f3460; padding: 15px; border-radius: 10px; margin: 15px 0; }
        .rrr-high { color: #00ff88; font-weight: bold; }
        .rrr-medium { color: #ffd700; }
        .rrr-low { color: #ff4757; }
        @media (max-width: 768px) { .header h1 { font-size: 1.5em; } }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Trading Signals Dashboard</h1>
        <p id="marketStatus">Checking DSE status...</p>
        <button id="installBtn" onclick="installApp()" style="display:none; background:#00d4ff; color:#000; border:none; padding:10px 20px; border-radius:8px; cursor:pointer; font-weight:bold; margin-top:10px;">📲 Install App</button>
    </div>
    <div id="alertBox" class="alert-box">⚠️ DSE CLOSING IN 10 MINUTES!</div>
    <div class="tabs">
        <div class="tab active" data-tab="ai_signals">🤖 AI Signals</div>
        <div class="tab" data-tab="swrsi">🔍 SWRSI</div>
        <div class="tab" data-tab="support">📊 S/R</div>
        <div class="tab" data-tab="ema">📈 EMA 21</div>
        <div class="tab" data-tab="buy">✅ Daily Buy</div>
    </div>
    <div class="controls">
        <label>📅 Date:</label>
        <select id="dateSelect" onchange="loadCurrentTab()"><option value="">Latest</option></select>
        <label>🔍 Symbol:</label>
        <input type="text" id="symbolSearch" onkeyup="loadCurrentTab()" style="width:120px;">
        <button onclick="loadCurrentTab()">🔄 Refresh</button>
        <button class="alert-config-btn" onclick="openAlertModal()">🔔 Alerts</button>
        <button class="delete-all-btn" onclick="deleteAllByDate()">🗑️ Delete All</button>
        <button class="trade-btn" onclick="openTradeModal()">💰 Trade</button>
        <button onclick="resetSort()" style="background:#555;">↺ Reset Sort</button>
        <span id="recordCount" style="color:#888;"></span>
    </div>
    
    <div id="alertModal" class="modal"><div class="modal-content"><h3>🔔 Configure LTP Alerts</h3><label>Select Symbol:</label><select id="alertSymbolSelect"></select><label>Condition:</label><select id="alertCondition"><option value="above">LTP Above</option><option value="below">LTP Below</option></select><label>Threshold Price:</label><input type="number" id="alertThresholdPrice" step="0.01"><div><button class="save-btn" onclick="addAlertRule()">Add Alert</button><button onclick="closeAlertModal()">Cancel</button></div><div id="currentAlertsSection" style="margin-top:15px;display:none;"><h4>Active Alerts:</h4><div id="currentAlertsList"></div></div></div></div>
    
    <div id="tradeModal" class="modal"><div class="modal-content"><h3>💰 Trade Management</h3><label>Select Symbol:</label><select id="tradeSymbolSelect" onchange="onTradeSymbolChange()"></select><label>Entry Price:</label><input type="number" id="tradeEntryPrice" step="0.01" oninput="calculateTradeStats()"><label>Stop Loss:</label><input type="number" id="tradeStopLoss" step="0.01" oninput="calculateTradeStats()"><label>Target Price:</label><input type="number" id="tradeTargetPrice" step="0.01" oninput="calculateTradeStats()"><label>Total Exposure (Taka):</label><input type="number" id="tradeTotalExposure" step="0.01" oninput="calculateTradeStats()"><label>Risk %:</label><input type="number" id="tradeRiskPercent" step="0.01" oninput="calculateTradeStats()"><div class="trade-summary" id="tradeSummary" style="display:none;"><span>RRR: <span id="tradeRRR">-</span></span><span>Risk: <span id="tradeRiskAmount">0</span></span><span>Profit: <span id="tradeProfitAmount">0</span></span><span>Qty: <span id="tradeQuantity">0</span></span></div><div><button class="save-btn" onclick="saveTrade()">Save Trade</button><button onclick="closeTradeModal()">Cancel</button></div></div></div>
    
    <div id="alertStatusBar" style="background:#0f3460;padding:6px 12px;border-radius:6px;margin-bottom:8px;display:none;"></div>
    <div id="sortStatus" style="background:#1a1a2e;padding:6px 12px;border-radius:6px;margin-bottom:8px;"></div>
    <div style="overflow-x:auto;" id="dynamicTable"></div>

    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let dseLtpData = {};
        let editingRow = null;
        let alertRules = [];
        let currentSort = { field: null, order: null };

        const COLLECTION_MAP = { 
            ai_signals: 'daily_ai_signals', 
            swrsi: 'swrsi_signals', 
            support: 'support_resistance', 
            ema: 'ema_21_signals', 
            buy: 'daily_buy_signals' 
        };

        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('.tab').forEach(tab => {
                tab.addEventListener('click', function() {
                    const tabId = this.getAttribute('data-tab');
                    if (tabId) switchTab(tabId);
                });
            });
            loadDates(COLLECTION_MAP[currentTab]);
            loadCurrentTab();
            checkMarketStatus();
            loadDseLtp();
            loadAlertRules();
            setInterval(checkMarketStatus, 60000);
            setInterval(function(){loadDseLtp(true);}, 30000);
            updateSortStatus();
        });

        function switchTab(tabId) {
            currentTab = tabId;
            document.querySelectorAll('.tab').forEach(tab => {
                if (tab.getAttribute('data-tab') === tabId) tab.classList.add('active');
                else tab.classList.remove('active');
            });
            document.getElementById('symbolSearch').value = '';
            resetSort();
            loadDates(COLLECTION_MAP[tabId]);
            loadCurrentTab();
        }

        function loadAlertRules() {
            const saved = localStorage.getItem('ltpAlertRules');
            if (saved) { try { alertRules = JSON.parse(saved); } catch(e) { alertRules = []; } }
            updateAlertUI();
        }
        
        function saveAlertRules() { 
            localStorage.setItem('ltpAlertRules', JSON.stringify(alertRules)); 
            updateAlertUI(); 
            renderCurrentTab(); 
        }
        
        function updateAlertUI() {
            const bar = document.getElementById('alertStatusBar');
            if (alertRules.length > 0) {
                bar.style.display = 'block';
                bar.innerHTML = alertRules.length + ' Alert(s): ' + alertRules.map(r => r.symbol + ' ' + (r.condition==='above'?'>':'<') + ' ' + r.threshold).join(' | ');
            } else {
                bar.style.display = 'none';
            }
        }

        function updateSortStatus() {
            const statusDiv = document.getElementById('sortStatus');
            if (currentSort.field) {
                statusDiv.innerHTML = 'Sorted: ' + currentSort.field + ' (' + currentSort.order.toUpperCase() + ') | <span style="cursor:pointer;color:#ffa500;" onclick="resetSort()">Reset</span>';
            } else {
                statusDiv.innerHTML = 'Default Sort: diff ASC, gape DESC';
            }
        }

        function handleSort(field) {
            if (currentSort.field === field) {
                currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.field = field;
                currentSort.order = (field === 'diff') ? 'asc' : (field === 'gape' ? 'desc' : 'asc');
            }
            updateSortStatus();
            loadCurrentTab();
        }

        function resetSort() {
            currentSort = { field: null, order: null };
            updateSortStatus();
            loadCurrentTab();
        }

        function getSortIndicator(field) {
            if (currentSort.field === field) {
                return currentSort.order === 'asc' ? ' ▲' : ' ▼';
            }
            return '';
        }

        async function checkMarketStatus() {
            const res = await fetch('/api/market-status');
            const s = await res.json();
            document.getElementById('marketStatus').innerHTML = s.is_open ? '🟢 DSE MARKET OPEN' : '🔴 DSE CLOSED';
        }

        async function loadDseLtp(forceRefresh) {
            try { 
                let url = '/api/dse-ltp?_=' + Date.now();
                if (forceRefresh) url += '&force=1';
                const r = await fetch(url); 
                const j = await r.json();
                if (j.ltp_data && Object.keys(j.ltp_data).length > 0) {
                    dseLtpData = j.ltp_data;
                    renderCurrentTab();
                }
            } catch(e) {
                console.error('LTP error:', e);
            }
        }

        async function loadDates(c) { 
            const r = await fetch('/api/dates?collection=' + c); 
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
            let sortParam = '';
            if (currentSort.field) {
                sortParam = '&sort_by=' + currentSort.field + '&sort_order=' + currentSort.order;
            }
            
            if (currentTab === 'ai_signals') {
                let url = '/api/signals?date=' + date + '&limit=1000' + sortParam;
                if (symbol) url += '&symbol=' + symbol;
                const r = await fetch(url); const j = await r.json();
                currentData = j.data || [];
            } else if (currentTab === 'swrsi') {
                let url = '/api/swrsi?' + sortParam;
                if (date) url += '&date=' + date;
                if (symbol) url += '&symbol=' + symbol;
                const r = await fetch(url); const j = await r.json();
                currentData = j.signals || [];
            } else {
                const map = { support: 'support_resistance', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
                let url = '/api/generic-data?collection=' + map[currentTab] + '&limit=500' + sortParam;
                if (date) url += '&date=' + date;
                if (symbol) url += '&symbol=' + symbol;
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

        function getSignalClass(s) {
            if (!s) return '';
            if (s.includes('STRONG BUY')) return 'signal-SB';
            if (s.includes('BUY')) return 'signal-B';
            if (s.includes('HOLD')) return 'signal-H';
            if (s.includes('SELL')) return 'signal-S';
            return '';
        }

        function isLtpAboveHigh(symbol, highPrice) {
            const ltp = dseLtpData[symbol] || null;
            if (!ltp || !highPrice || highPrice <= 0) return false;
            return ltp > highPrice;
        }

        function getLtpDisplay(symbol, highPrice) {
            const ltp = dseLtpData[symbol] || null;
            if (!ltp) return '-';
            let cls = '', arrow = '';
            if (highPrice && ltp > highPrice) {
                cls = 'ltp-above';
                arrow = ' 🚀';
            }
            return '<span class="' + cls + '">' + ltp.toFixed(2) + arrow + '</span>';
        }

        function getRowClass(symbol, highPrice) {
            if (isLtpAboveHigh(symbol, highPrice)) return 'ltp-break-high';
            return '';
        }

        function getRRRClass(rrr) {
            if (!rrr) return '';
            if (rrr >= 2) return 'rrr-high';
            if (rrr >= 1) return 'rrr-medium';
            return 'rrr-low';
        }

        function calculateTradeStats() {
            const entry = parseFloat(document.getElementById('tradeEntryPrice').value) || 0;
            const sl = parseFloat(document.getElementById('tradeStopLoss').value) || 0;
            const tp = parseFloat(document.getElementById('tradeTargetPrice').value) || 0;
            const exposure = parseFloat(document.getElementById('tradeTotalExposure').value) || 0;
            const riskPct = parseFloat(document.getElementById('tradeRiskPercent').value) || 0;
            const summary = document.getElementById('tradeSummary');
            if (entry > 0 && sl > 0 && tp > 0) {
                summary.style.display = 'block';
                const risk = Math.abs(entry - sl);
                const reward = Math.abs(tp - entry);
                const rrr = risk > 0 ? (reward / risk).toFixed(2) : '0';
                document.getElementById('tradeRRR').textContent = rrr;
                if (exposure > 0 && riskPct > 0) {
                    const riskAmount = (exposure * riskPct) / 100;
                    const quantity = risk > 0 ? Math.floor(riskAmount / risk) : 0;
                    const profitAmount = quantity * reward;
                    document.getElementById('tradeRiskAmount').textContent = riskAmount.toFixed(2);
                    document.getElementById('tradeProfitAmount').textContent = profitAmount.toFixed(2);
                    document.getElementById('tradeQuantity').textContent = quantity;
                }
            } else {
                summary.style.display = 'none';
            }
        }

        async function onTradeSymbolChange() {
            const symbol = document.getElementById('tradeSymbolSelect').value;
            const record = currentData.find(r => r.symbol === symbol);
            if (record) {
                document.getElementById('tradeEntryPrice').value = record.entry_price || '';
                document.getElementById('tradeStopLoss').value = record.stop_loss || '';
                document.getElementById('tradeTargetPrice').value = record.target_price || '';
                document.getElementById('tradeTotalExposure').value = record.total_exposure || '';
                document.getElementById('tradeRiskPercent').value = record.risk_percent || '';
            }
            calculateTradeStats();
        }

        async function openTradeModal() {
            document.getElementById('tradeModal').classList.add('open');
            await loadTradeSymbols();
        }
        
        function closeTradeModal() { document.getElementById('tradeModal').classList.remove('open'); }

        async function loadTradeSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTION_MAP[currentTab];
            const select = document.getElementById('tradeSymbolSelect');
            select.innerHTML = '<option value="">Loading...</option>';
            try {
                let url = '/api/collection-symbols?collection=' + collection;
                if (date) url += '&date=' + date;
                const symbols = await (await fetch(url)).json();
                select.innerHTML = '<option value="">-- Select --</option>';
                symbols.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; select.appendChild(o); });
            } catch(e) { select.innerHTML = '<option value="">Error</option>'; }
        }

        async function saveTrade() {
            const symbol = document.getElementById('tradeSymbolSelect').value;
            if (!symbol) { alert('Select a symbol!'); return; }
            const entry = parseFloat(document.getElementById('tradeEntryPrice').value) || 0;
            const sl = parseFloat(document.getElementById('tradeStopLoss').value) || 0;
            const tp = parseFloat(document.getElementById('tradeTargetPrice').value) || 0;
            const exposure = parseFloat(document.getElementById('tradeTotalExposure').value) || 0;
            const riskPct = parseFloat(document.getElementById('tradeRiskPercent').value) || 0;
            const record = currentData.find(r => r.symbol === symbol);
            const date = record ? (record.analysis_date || record.date || '') : '';
            if (!date) { alert('No date found!'); return; }
            const collection = COLLECTION_MAP[currentTab];
            let params = 'collection=' + collection + '&symbol=' + symbol + '&date=' + date;
            if (entry) params += '&entry_price=' + entry;
            if (sl) params += '&stop_loss=' + sl;
            if (tp) params += '&target_price=' + tp;
            if (exposure) params += '&total_exposure=' + exposure;
            if (riskPct) params += '&risk_percent=' + riskPct;
            try {
                await fetch('/api/update-trade?' + params, { method: 'PUT' });
                alert('Trade saved!');
                closeTradeModal();
                loadCurrentTab();
            } catch(e) { alert('Failed: ' + e.message); }
        }

        function startEdit(symbol, date) { editingRow = { symbol: symbol, date: date }; renderCurrentTab(); }
        function cancelEdit() { editingRow = null; renderCurrentTab(); }

        async function saveEdit(symbol, date) {
            const safeId = symbol.replace(/[^a-zA-Z0-9]/g, '_');
            const entry = parseFloat(document.getElementById('edit-entry-' + safeId).value) || 0;
            const sl = parseFloat(document.getElementById('edit-sl-' + safeId).value) || 0;
            const tp = parseFloat(document.getElementById('edit-tp-' + safeId).value) || 0;
            let params = 'collection=' + COLLECTION_MAP[currentTab] + '&symbol=' + symbol + '&date=' + date;
            params += '&entry_price=' + entry + '&stop_loss=' + sl + '&target_price=' + tp;
            await fetch('/api/update-trade?' + params, { method: 'PUT' });
            editingRow = null;
            loadCurrentTab();
        }

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
                let url = '/api/collection-symbols?collection=' + collection;
                if (date) url += '&date=' + date;
                const symbols = await (await fetch(url)).json();
                select.innerHTML = '<option value="">-- Select --</option>';
                symbols.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; select.appendChild(o); });
            } catch(e) { select.innerHTML = '<option value="">Error</option>'; }
        }

        function renderCurrentAlerts() {
            const section = document.getElementById('currentAlertsSection');
            const list = document.getElementById('currentAlertsList');
            if (alertRules.length === 0) { section.style.display = 'none'; return; }
            section.style.display = 'block';
            list.innerHTML = alertRules.map((r, i) => '<div>' + r.symbol + ' ' + (r.condition==='above'?'Above':'Below') + ' ' + r.threshold + ' <button onclick="removeAlertRule(' + i + ')">✕</button></div>').join('');
        }

        function addAlertRule() {
            const symbol = document.getElementById('alertSymbolSelect').value;
            const condition = document.getElementById('alertCondition').value;
            const threshold = parseFloat(document.getElementById('alertThresholdPrice').value);
            if (!symbol || !threshold) return;
            alertRules = alertRules.filter(r => r.symbol !== symbol);
            alertRules.push({ symbol: symbol, condition: condition, threshold: threshold });
            saveAlertRules();
        }

        function removeAlertRule(i) { alertRules.splice(i, 1); saveAlertRules(); renderCurrentTab(); }

        async function deleteAllByDate() {
            const date = document.getElementById('dateSelect').value;
            if (!date) { alert('Select a date!'); return; }
            if (!confirm('Delete ALL for ' + date + '?')) return;
            const collection = COLLECTION_MAP[currentTab];
            const r = await fetch('/api/delete-all-by-date?collection=' + collection + '&date=' + date, { method: 'DELETE' });
            const result = await r.json();
            alert('Deleted ' + result.deleted + ' records');
            loadDates(collection);
            loadCurrentTab();
        }

        async function deleteRecord(symbol, date, tab) {
            tab = tab || currentTab;
            if (!confirm('Delete ' + symbol + '?')) return;
            await fetch('/api/delete-signal?collection=' + COLLECTION_MAP[tab] + '&symbol=' + symbol + '&date=' + date, { method: 'DELETE' });
            loadCurrentTab();
        }

        function renderAITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="text-align:center;padding:40px;">No data</p>'; return; }
            
            let html = '<table><thead><tr><th>#</th><th onclick="handleSort(\'symbol\')">Symbol' + getSortIndicator('symbol') + '</th><th>Date</th><th>Price</th><th>LTP</th><th>Sector</th><th>Signal</th><th>Score</th><th>LLM</th><th>LLM%</th><th>XGB</th><th>XGB%</th><th>PPO</th><th>PPO%</th><th>Agentic</th><th onclick="handleSort(\'diff\')">Diff' + getSortIndicator('diff') + '</th><th onclick="handleSort(\'gape\')">Gape' + getSortIndicator('gape') + '</th><th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Act</th></tr></thead><tbody>';
            
            for (let i = 0; i < currentData.length; i++) {
                const r = currentData[i];
                const safeId = (r.symbol || '').replace(/[^a-zA-Z0-9]/g, '_');
                const isEditing = editingRow && editingRow.symbol === r.symbol;
                const isEdited = r.edited;
                const hasTrade = r.entry_price || r.stop_loss || r.target_price;
                const highPrice = r.high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const rrr = r.risk_reward_ratio || 0;
                const rrrClass = getRRRClass(rrr);
                const breakBadge = isLtpAboveHigh(r.symbol, highPrice) ? ' 🚀' : '';
                const entryCell = isEditing ? '<input class="editable-input" id="edit-entry-' + safeId + '" value="' + ((r.entry_price||0).toFixed(2)) + '">' : (r.entry_price ? r.entry_price.toFixed(2) : '-');
                const slCell = isEditing ? '<input class="editable-input" id="edit-sl-' + safeId + '" value="' + ((r.stop_loss||0).toFixed(2)) + '">' : (r.stop_loss ? r.stop_loss.toFixed(2) : '-');
                const tpCell = isEditing ? '<input class="editable-input" id="edit-tp-' + safeId + '" value="' + ((r.target_price||0).toFixed(2)) + '">' : (r.target_price ? r.target_price.toFixed(2) : '-');
                const actionCell = isEditing ? '<button class="save-btn" onclick="saveEdit(\'' + r.symbol + '\',\'' + r.analysis_date + '\')">💾</button><button onclick="cancelEdit()">❌</button>' : '<button class="edit-btn" onclick="startEdit(\'' + r.symbol + '\',\'' + r.analysis_date + '\')">✏️</button><button class="trade-edit-btn" onclick="openTradeForSymbol(\'' + r.symbol + '\')">💰</button><button class="delete-btn" onclick="deleteRecord(\'' + r.symbol + '\',\'' + r.analysis_date + '\')">🗑️</button>';
                
                html += '<tr class="' + rowClass + '"><td>' + (i+1) + '</td><td><strong>' + (r.symbol||'') + (isEdited?' ✏️':'') + (hasTrade?' 💰':'') + breakBadge + '</strong></td><td>' + (r.analysis_date||'') + '</td><td>' + ((r.current_price||0).toFixed(2)) + '</td><td>' + ltpDisplay + '</td><td>' + (r.sector||'') + '</td><td class="' + getSignalClass(r.final_signal) + '">' + (r.final_signal||'') + '</td><td>' + ((r.final_combined_score||0).toFixed(1)) + '</td><td>' + (r.llm_signal||'') + '</td><td>' + ((r.llm_confidence||0).toFixed(0)) + '%</td><td>' + (r.xgb_signal||'') + '</td><td>' + ((r.xgb_confidence||0).toFixed(0)) + '%</td><td>' + (r.ppo_signal||'') + '</td><td>' + ((r.ppo_confidence||0).toFixed(0)) + '%</td><td>' + ((r.agentic_score||0).toFixed(1)) + '</td><td>' + (r.diff!==undefined?(r.diff>0?'+':'')+r.diff.toFixed(2):'-') + '</td><td>' + (r.gape!==undefined?r.gape.toFixed(2):'-') + '</td><td>' + entryCell + '</td><td>' + slCell + '</td><td>' + tpCell + '</td><td class="' + rrrClass + '"><strong>' + rrr.toFixed(2) + '</strong></td><td>' + actionCell + '</td></tr>';
            }
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = '(' + currentData.length + ' signals)';
        }

        function renderSWRSITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="text-align:center;padding:40px;">No SWRSI signals</p>'; return; }
            
            let html = '<table><thead><tr><th>#</th><th>Symbol</th><th>Sector</th><th>LTP</th><th>Score</th><th>Weekly</th><th>Diff</th><th>Gape</th><th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Act</th></tr></thead><tbody>';
            
            for (let i = 0; i < currentData.length; i++) {
                const r = currentData[i];
                const highPrice = r.high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const hasTrade = r.entry_price || r.stop_loss || r.target_price;
                const rrr = r.risk_reward_ratio || 0;
                const rrrClass = getRRRClass(rrr);
                const breakBadge = isLtpAboveHigh(r.symbol, highPrice) ? '🚀' : '';
                
                html += '<tr class="' + rowClass + '"><td>' + (i+1) + '</td><td><strong>' + (r.symbol||'') + (hasTrade?' 💰':'') + breakBadge + '</strong></td><td>' + (r.sector||'') + '</td><td>' + ltpDisplay + '</td><td>' + ((r.composite_score||0).toFixed(0)) + '</td><td>' + (r.weekly_strength_label||'') + '</td><td>' + (r.diff!==undefined?(r.diff>0?'+':'')+r.diff.toFixed(2):'-') + '</td><td>' + (r.gape!==undefined?r.gape.toFixed(2):'-') + '</td><td>' + (r.entry_price?r.entry_price.toFixed(2):'-') + '</td><td>' + (r.stop_loss?r.stop_loss.toFixed(2):'-') + '</td><td>' + (r.target_price?r.target_price.toFixed(2):'-') + '</td><td class="' + rrrClass + '"><strong>' + rrr.toFixed(2) + '</strong></td><td><button class="trade-edit-btn" onclick="openTradeForSymbol(\'' + r.symbol + '\')">💰</button><button class="delete-btn" onclick="deleteRecord(\'' + r.symbol + '\',\'' + (r.analysis_date||'') + '\',\'swrsi\')">🗑️</button></td></tr>';
            }
            html += '</tbody></table>';
            div.innerHTML = html;
        }

        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="text-align:center;padding:40px;">No data</p>'; return; }
            
            const keys = Object.keys(currentData[0]).filter(k => !['_id', 'saved_at', 'analysis_date', 'date', 'symbol', 'entry_price', 'stop_loss', 'target_price', 'risk_reward_ratio', 'total_exposure', 'risk_percent', 'edited', 'edited_at'].includes(k));
            
            let html = '<table><thead><tr><th>#</th><th>Symbol</th><th>LTP</th>' + keys.map(k => '<th>' + k + '</th>').join('') + '<th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Act</th></tr></thead><tbody>';
            
            for (let i = 0; i < currentData.length; i++) {
                const r = currentData[i];
                const highPrice = r.high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const hasTrade = r.entry_price || r.stop_loss || r.target_price;
                const rrr = r.risk_reward_ratio || 0;
                const rrrClass = getRRRClass(rrr);
                const breakBadge = isLtpAboveHigh(r.symbol, highPrice) ? '🚀' : '';
                
                html += '<tr class="' + rowClass + '"><td>' + (i+1) + '</td><td><strong>' + (r.symbol||'') + (hasTrade?' 💰':'') + breakBadge + '</strong></td><td>' + ltpDisplay + '</td>';
                for (let k of keys) {
                    let val = r[k];
                    if (val === undefined || val === null) val = '';
                    if (typeof val === 'number') val = val.toFixed(2);
                    html += '<td>' + val + '</td>';
                }
                html += '<td>' + (r.entry_price?r.entry_price.toFixed(2):'-') + '</td><td>' + (r.stop_loss?r.stop_loss.toFixed(2):'-') + '</td><td>' + (r.target_price?r.target_price.toFixed(2):'-') + '</td><td class="' + rrrClass + '"><strong>' + rrr.toFixed(2) + '</strong></td><td><button class="trade-edit-btn" onclick="openTradeForSymbol(\'' + r.symbol + '\')">💰</button><button class="delete-btn" onclick="deleteRecord(\'' + r.symbol + '\',\'' + (r.analysis_date||r.date||'') + '\',\'' + currentTab + '\')">🗑️</button></td></tr>';
            }
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = '(' + currentData.length + ' records)';
        }

        async function openTradeForSymbol(symbol) {
            const select = document.getElementById('tradeSymbolSelect');
            await loadTradeSymbols();
            select.value = symbol;
            onTradeSymbolChange();
            openTradeModal();
        }

        let deferredPrompt;
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
            document.getElementById('installBtn').style.display = 'inline-block';
        });

        function installApp() {
            if (deferredPrompt) {
                deferredPrompt.prompt();
                deferredPrompt = null;
                document.getElementById('installBtn').style.display = 'none';
            }
        }

        if ('serviceWorker' in navigator) {
            window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js'); });
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