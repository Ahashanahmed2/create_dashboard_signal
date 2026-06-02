"""
create_dashboard.py
✅ All Tabs with LTP + No Duplicate Date
✅ DSE Market: Sun-Thu 10AM-2:20PM (Bangladesh Time UTC+6)
✅ DSE Website Market Status Check - FIXED
✅ AI Signals (37 cols) + SWRSI + S/R + MACD + EMA 21 + Daily Buy
✅ S/R date selector FIXED (uses analysis_date like all other tabs)
✅ LTP Alert Modal + Delete All + Edit buttons
✅ Trade Management Modal with Entry/SL/TP/Exposure/Risk%
✅ Auto-calculated RRR column in all tabs
✅ UptimeRobot HEAD endpoint
✅ LTP > High Breakout Row Highlight (GREEN)
✅ Default Sort: diff ASC, gape DESC
✅ LTP Fetch: Only when market open (every 2 min), if closed fetch once only
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
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="18.0.2")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI: 
        return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[collection_name or COLLECTION_NAME]
    except Exception as e:
        logger.error(f"MongoDB connection error: {e}")
        return None

# ================================
# Bangladesh Timezone Helper
# ================================
BD_TIMEZONE = timezone(timedelta(hours=6))

def get_bd_time():
    return datetime.now(BD_TIMEZONE)

# ================================
# DSE WEBSITE MARKET STATUS - FIXED VERSION
# ================================
def is_dse_market_open():
    """
    DSE ওয়েবসাইট থেকে মার্কেট স্ট্যাটাস চেক - একাধিক মেথড সহ
    """
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
            'Connection': 'keep-alive',
        })

        # Method 1: DSE হোমপেজ স্ক্র্যাপিং
        try:
            response = session.get('https://www.dsebd.org/', timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                text = soup.get_text()
                if re.search(r'Market\s+Status\s*:\s*Open', text, re.I):
                    logger.info("[DSE] MARKET OPEN (Homepage)")
                    return True
                if re.search(r'Market\s+Status\s*:\s*Closed', text, re.I):
                    logger.info("[DSE] MARKET CLOSED (Homepage)")
                    return False
        except Exception as e:
            logger.error(f"[DSE] Method 1 failed: {e}")

        # Method 2: LTP AJAX API চেক
        try:
            response = session.get(
                'https://www.dsebd.org/latest_share_price_scroll_l.php',
                headers={'X-Requested-With': 'XMLHttpRequest'},
                timeout=15
            )
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                rows = soup.find_all('tr')
                data_rows = 0
                for row in rows:
                    tds = row.find_all('td')
                    if len(tds) >= 3:
                        try:
                            ltp_text = tds[2].get_text(strip=True).replace(',', '')
                            ltp = float(ltp_text)
                            if ltp > 0:
                                data_rows += 1
                        except:
                            pass
                if data_rows > 10:
                    logger.info(f"[DSE] MARKET OPEN (LTP Data: {data_rows} stocks)")
                    return True
                elif data_rows > 0:
                    return True
        except Exception as e:
            logger.error(f"[DSE] Method 2 failed: {e}")

        # Method 3: টাইম-বেসড ফলব্যাক
        logger.info("[DSE] Using time-based fallback")
        return _is_dse_market_open_by_time()

    except Exception as e:
        logger.error(f"[DSE] Market check failed: {e}")
        return _is_dse_market_open_by_time()

def _is_dse_market_open_by_time():
    now = get_bd_time()
    hour, minute, weekday = now.hour, now.minute, now.weekday()
    
    if weekday in [4, 5]:  # Friday, Saturday
        return False
    
    if weekday in [6, 0, 1, 2, 3]:  # Sunday to Thursday
        current_time = hour * 60 + minute
        market_open = 10 * 60
        market_close = 14 * 60 + 20
        return market_open <= current_time <= market_close
    
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
    return {
        "status": "ok",
        "mongodb": "connected" if col else "not configured",
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
        if weekday in [4, 5]:
            next_open = "Sunday 10:00 AM"
        else:
            next_open = "Tomorrow 10:00 AM"
    else:
        next_open = None

    return {
        "is_open": is_open,
        "alert_10min": alert_10min,
        "alert_message": "⚠️ DSE CLOSING IN 10 MINUTES!" if alert_10min else "",
        "next_open": next_open,
        "bangladesh_time": now.strftime('%Y-%m-%d %H:%M:%S')
    }

# LTP Cache
ltp_cache = {"data": {}, "timestamp": None, "fetched_once_when_closed": False}

@app.get("/api/dse-ltp")
async def get_dse_ltp():
    """DSE থেকে LTP ডাটা ফেচ করুন - মার্কেট ওপেন থাকলে ২ মিনিট পর পর, ক্লোজ থাকলে একবার"""
    
    market_open = is_dse_market_open()
    
    # Check cache
    if ltp_cache["timestamp"]:
        age = (get_bd_time() - ltp_cache["timestamp"]).total_seconds()
        
        if market_open:
            if age < 120 and ltp_cache["data"]:
                logger.info(f"[LTP] Cache hit, age: {age:.0f}s")
                return ltp_cache["data"]
        else:
            if ltp_cache["data"] and ltp_cache.get("fetched_once_when_closed", False):
                logger.info("[LTP] Using cached data (market closed, fetched once)")
                result = ltp_cache["data"]
                if isinstance(result, dict):
                    result["status"] = "closed"
                return result
    
    # Don't fetch again if market closed and already fetched once
    if not market_open and ltp_cache.get("fetched_once_when_closed", False):
        if ltp_cache["data"]:
            logger.info("[LTP] Market closed, already fetched once. Returning cached data.")
            result = ltp_cache["data"]
            if isinstance(result, dict):
                result["status"] = "closed"
            return result
    
    # Fetch LTP data
    logger.info(f"[LTP] Fetching LTP data (market open: {market_open})")
    ltp_data = {}
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })

    # Try multiple pages
    try:
        for page in range(1, 4):
            try:
                response = session.get(
                    f'https://www.dsebd.org/latest_share_price_scroll_l.php?page={page}',
                    headers={'X-Requested-With': 'XMLHttpRequest'},
                    timeout=10
                )
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    tables = soup.find_all('table')
                    for table in tables:
                        rows = table.find_all('tr')
                        for row in rows:
                            cols = row.find_all('td')
                            if len(cols) >= 3:
                                try:
                                    # Find symbol
                                    symbol = None
                                    for col_idx in [1, 0]:
                                        if len(cols) > col_idx:
                                            link = cols[col_idx].find('a')
                                            if link:
                                                symbol = link.text.strip()
                                                break
                                            text = cols[col_idx].get_text(strip=True)
                                            if text and len(text) >= 2 and text[0].isalpha():
                                                symbol = text
                                                break
                                    
                                    # Find LTP
                                    ltp = None
                                    for col_idx in [2, 3, 4]:
                                        if len(cols) > col_idx:
                                            ltp_text = cols[col_idx].get_text(strip=True).replace(',', '')
                                            try:
                                                ltp = float(ltp_text)
                                                if 0.1 < ltp < 50000:
                                                    break
                                            except:
                                                continue
                                    
                                    if symbol and ltp:
                                        ltp_data[symbol.upper()] = ltp
                                except:
                                    continue
            except:
                break
        
        if ltp_data:
            result = {
                "status": "live" if market_open else "closed",
                "total_symbols": len(ltp_data),
                "ltp_data": ltp_data,
                "source": "dse_api"
            }
            ltp_cache["data"] = result
            ltp_cache["timestamp"] = get_bd_time()
            ltp_cache["fetched_once_when_closed"] = not market_open
            logger.info(f"[LTP] Fetched {len(ltp_data)} symbols")
            return result
    except Exception as e:
        logger.error(f"[LTP] Fetch failed: {e}")

    # Return cached data if available
    if ltp_cache["data"]:
        result = ltp_cache["data"]
        if isinstance(result, dict):
            result["status"] = "cached"
        return result
    
    return {
        "status": "error",
        "message": "Unable to fetch LTP data",
        "ltp_data": {}
    }

# ================================
# Database Query Helpers
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

# ================================
# Main API Endpoints
# ================================
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

    try:
        for doc in col.find({'saved_at': {'$exists': True}}, {'saved_at': 1}).limit(2000):
            val = doc.get('saved_at', '')
            if isinstance(val, str) and len(val) >= 10:
                d = val[:10]
                if re.match(r'\d{4}-\d{2}-\d{2}', d):
                    dates_set.add(d)
    except:
        pass

    return sorted(list(dates_set), reverse=True)

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
    if collection is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    query = {}
    if date: 
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection("daily_ai_signals")
        if latest_date:
            query = build_date_query(latest_date)

    if signal: 
        query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol: 
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0: 
        query['final_combined_score'] = {'$gte': min_score}

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
    if col is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection("swrsi_signals")
        if latest_date:
            query = build_date_query(latest_date)

    if symbol: 
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}

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
    if col is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest_date = get_latest_date_from_collection(collection)
        if latest_date:
            query = build_date_query(latest_date)

    if symbol: 
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}

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
    if col is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    result = col.delete_one({'symbol': symbol, 'analysis_date': date})
    if result.deleted_count == 0:
        result = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    return {"deleted": result.deleted_count}

@app.delete("/api/delete-all-by-date")
async def delete_all_by_date(collection: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
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
    if col is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    update_fields = {
        'edited': True, 
        'edited_at': datetime.now().isoformat()
    }

    if entry_price is not None: 
        update_fields['entry_price'] = entry_price
    if stop_loss is not None: 
        update_fields['stop_loss'] = stop_loss
    if target_price is not None: 
        update_fields['target_price'] = target_price
    if total_exposure is not None: 
        update_fields['total_exposure'] = total_exposure
    if risk_percent is not None: 
        update_fields['risk_percent'] = risk_percent

    if entry_price and stop_loss and target_price:
        risk = abs(entry_price - stop_loss)
        reward = abs(target_price - entry_price)
        if risk > 0:
            update_fields['risk_reward_ratio'] = round(reward / risk, 2)

    result = col.update_one(
        {'symbol': symbol, 'analysis_date': date}, 
        {'$set': update_fields}
    )

    if result.matched_count == 0:
        result = col.update_one(
            {'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}}, 
            {'$set': update_fields}
        )

    return {"updated": result.modified_count, "matched": result.matched_count}

@app.get("/api/collection-symbols")
async def get_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None: 
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

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
    return '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>🤖 AI Trading Signals</title>
    <link rel="manifest" href="/static/manifest.json">
    <meta name="theme-color" content="#00d4ff">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 30px; background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%); border-radius: 15px; margin-bottom: 20px; }
        .header h1 { font-size: 2em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .market-status { margin-top: 10px; font-size: 0.9em; }
        .market-open { color: #00ff88; }
        .market-closed { color: #ff4757; }
        .alert-box { background: #ff4757; color: #fff; padding: 15px; border-radius: 10px; margin: 15px 0; text-align: center; font-size: 1.2em; font-weight: bold; display: none; animation: pulse 1s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
        .tabs { display: flex; margin-bottom: 20px; background: #111; border-radius: 10px; overflow-x: auto; flex-wrap: wrap; }
        .tab { padding: 12px 20px; text-align: center; cursor: pointer; color: #aaa; min-width: 100px; }
        .tab.active { background: #1a1a2e; color: #00d4ff; font-weight: bold; border-bottom: 2px solid #00d4ff; }
        .controls { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }
        select, input, button { padding: 8px 12px; background: #1a1a2e; color: #fff; border: 1px solid #333; border-radius: 6px; font-size: 0.9em; }
        button { cursor: pointer; background: #0f3460; transition: all 0.2s; }
        button:hover { opacity: 0.8; transform: translateY(-1px); }
        .delete-all-btn { background: #ff4757; color: #fff; }
        .alert-config-btn { background: #ffa500; color: #000; }
        .trade-btn { background: #00cc66; color: #000; }
        table { width: 100%; border-collapse: collapse; font-size: 0.7em; background: #111122; border-radius: 10px; overflow: auto; display: block; }
        th { background: #1a1a2e; padding: 10px 5px; color: #00d4ff; white-space: nowrap; cursor: pointer; position: sticky; top: 0; }
        th:hover { background: #1e1e38; }
        td { padding: 6px 5px; border-bottom: 1px solid #222; white-space: nowrap; }
        .edit-btn { background: #ffa500; color: #000; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; margin: 0 2px; }
        .delete-btn { background: #ff4757; color: #fff; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; margin: 0 2px; }
        .trade-edit-btn { background: #7b2ff7; color: #fff; border: none; padding: 3px 6px; border-radius: 4px; cursor: pointer; margin: 0 2px; }
        .edited-badge { background: #ffa500; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px; }
        .trade-badge { background: #cc00cc; color: #fff; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px; }
        .signal-SB { color: #00ff88; font-weight: bold; }
        .signal-B { color: #00cc66; font-weight: bold; }
        .signal-H { color: #ffd700; }
        .signal-S { color: #ff4757; }
        .signal-SS { color: #ff0000; font-weight: bold; }
        .ltp-alert-row { animation: blink 0.6s infinite; }
        @keyframes blink { 0%,100% { background: #ff475730; } 50% { background: #ff475760; } }
        .ltp-above { color: #00ff88 !important; font-weight: bold; }
        .ltp-below { color: #ff4757 !important; font-weight: bold; }
        .ltp-break-high { background: linear-gradient(90deg, #00ff8818, #0a0a0f) !important; border-left: 3px solid #00ff88; }
        .ltp-break-badge { background: #00ff88; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px; font-weight: bold; }
        .rrr-high { color: #00ff88; font-weight: bold; }
        .rrr-medium { color: #ffd700; }
        .rrr-low { color: #ff4757; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 1000; justify-content: center; align-items: center; }
        .modal.open { display: flex; }
        .modal-content { background: #1a1a2e; padding: 25px; border-radius: 15px; max-width: 500px; width: 90%; border: 2px solid #ffa500; max-height: 90vh; overflow-y: auto; }
        .trade-modal-content { border-color: #00cc66; }
        .modal-content h3 { margin-bottom: 15px; }
        .modal-content input, .modal-content select { width: 100%; padding: 8px; margin-bottom: 10px; background: #0a0a0f; color: #fff; border: 1px solid #333; border-radius: 5px; }
        .modal-buttons { display: flex; gap: 10px; margin-top: 15px; }
        .modal-buttons button { flex: 1; }
        .trade-summary { background: #0f3460; padding: 15px; border-radius: 10px; margin: 15px 0; }
        .sort-indicator { font-size: 0.8em; margin-left: 3px; }
        @media (max-width: 768px) { body { padding: 10px; } .header h1 { font-size: 1.3em; } .tab { padding: 8px 12px; font-size: 0.8em; } }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Trading Signals Dashboard</h1>
        <div class="market-status" id="marketStatus">Checking DSE status...</div>
        <button id="installBtn" onclick="installApp()" style="display:none; margin-top:10px; background:#00d4ff; color:#000;">📲 Install App</button>
    </div>
    <div id="alertBox" class="alert-box">⚠️ DSE CLOSING IN 10 MINUTES!</div>
    
    <div class="tabs">
        <div class="tab active" onclick="switchTab('ai_signals')">🤖 AI Signals</div>
        <div class="tab" onclick="switchTab('swrsi')">🔍 SWRSI</div>
        <div class="tab" onclick="switchTab('support')">📊 S/R</div>
        <div class="tab" onclick="switchTab('macd')">📉 MACD</div>
        <div class="tab" onclick="switchTab('ema')">📈 EMA 21</div>
        <div class="tab" onclick="switchTab('buy')">✅ Daily Buy</div>
    </div>
    
    <div class="controls">
        <select id="dateSelect" onchange="loadCurrentTab()"><option value="">Latest</option></select>
        <input type="text" id="symbolSearch" placeholder="Symbol..." onkeyup="loadCurrentTab()" style="width:120px;">
        <button onclick="loadCurrentTab()">🔄 Refresh</button>
        <button class="alert-config-btn" onclick="openAlertModal()">🔔 Alerts</button>
        <button class="delete-all-btn" onclick="deleteAllByDate()">🗑️ Delete All</button>
        <button class="trade-btn" onclick="openTradeModal()">💰 Trade</button>
        <button onclick="resetSort()">↺ Reset Sort</button>
        <span id="recordCount" style="color:#888;"></span>
    </div>
    
    <div id="alertStatusBar" style="background:#0f3460;padding:6px 12px;border-radius:6px;margin-bottom:8px;display:none;"></div>
    <div id="sortStatus" style="background:#1a1a2e;padding:6px 12px;border-radius:6px;margin-bottom:8px;"></div>
    <div style="overflow-x:auto;" id="dynamicTable"></div>

    <!-- Alert Modal -->
    <div id="alertModal" class="modal">
        <div class="modal-content">
            <h3>🔔 LTP Alert Configuration</h3>
            <select id="alertSymbolSelect"><option>Loading...</option></select>
            <select id="alertCondition">
                <option value="above">LTP Above</option>
                <option value="below">LTP Below</option>
            </select>
            <input type="number" id="alertThresholdPrice" placeholder="Threshold Price">
            <div class="modal-buttons">
                <button onclick="addAlertRule()">➕ Add Alert</button>
                <button onclick="closeAlertModal()">Close</button>
            </div>
            <div id="currentAlertsList" style="margin-top:15px;"></div>
        </div>
    </div>

    <!-- Trade Modal -->
    <div id="tradeModal" class="modal">
        <div class="modal-content trade-modal-content">
            <h3>💰 Trade Management</h3>
            <select id="tradeSymbolSelect" onchange="onTradeSymbolChange()"><option>Loading...</option></select>
            <input type="number" id="tradeEntryPrice" placeholder="Entry Price" oninput="calculateTradeStats()">
            <input type="number" id="tradeStopLoss" placeholder="Stop Loss" oninput="calculateTradeStats()">
            <input type="number" id="tradeTargetPrice" placeholder="Target Price" oninput="calculateTradeStats()">
            <input type="number" id="tradeTotalExposure" placeholder="Total Exposure (Taka)" oninput="calculateTradeStats()">
            <input type="number" id="tradeRiskPercent" placeholder="Risk %" oninput="calculateTradeStats()">
            <div class="trade-summary" id="tradeSummary" style="display:none;">
                <div>📊 RRR: <strong id="tradeRRR">-</strong></div>
                <div>💸 Risk Amount: ৳<span id="tradeRiskAmount">0</span></div>
                <div>🎯 Profit: ৳<span id="tradeProfitAmount">0</span></div>
                <div>📈 Quantity: <span id="tradeQuantity">0</span></div>
            </div>
            <div class="modal-buttons">
                <button onclick="saveTrade()">💾 Save</button>
                <button onclick="closeTradeModal()">Cancel</button>
            </div>
        </div>
    </div>

    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let dseLtpData = {};
        let alertRules = [];
        let currentSort = { field: null, order: null };
        
        const COLLECTION_MAP = { 
            ai_signals: 'daily_ai_signals', 
            swrsi: 'swrsi_signals', 
            support: 'support_resistance', 
            macd: 'macd_signals', 
            ema: 'ema_21_signals', 
            buy: 'daily_buy_signals' 
        };
        
        // Load initial data
        loadDates(COLLECTION_MAP.ai_signals);
        loadCurrentTab();
        checkMarketAndLtp();
        loadAlertRules();
        setInterval(checkMarketAndLtp, 60000);
        setInterval(() => { loadDseLtp(); }, 120000);
        
        async function checkMarketAndLtp() {
            const res = await fetch('/api/market-status');
            const s = await res.json();
            const statusText = s.is_open ? '🟢 MARKET OPEN' : '🔴 MARKET CLOSED';
            const timeText = s.bangladesh_time ? ` | ${s.bangladesh_time}` : '';
            document.getElementById('marketStatus').innerHTML = `${statusText}${timeText}`;
            document.getElementById('alertBox').style.display = s.alert_10min ? 'block' : 'none';
            await loadDseLtp();
        }
        
        async function loadDseLtp() {
            try {
                const res = await fetch('/api/dse-ltp');
                const data = await res.json();
                if (data.ltp_data) {
                    dseLtpData = data.ltp_data;
                    renderCurrentTab();
                }
            } catch(e) { console.error('LTP error:', e); }
        }
        
        async function loadDates(collection) {
            const res = await fetch(`/api/dates?collection=${collection}`);
            const dates = await res.json();
            const select = document.getElementById('dateSelect');
            select.innerHTML = '<option value="">Latest</option>';
            if (Array.isArray(dates)) {
                dates.forEach(d => {
                    const option = document.createElement('option');
                    option.value = d;
                    option.textContent = d;
                    select.appendChild(option);
                });
            }
        }
        
        async function loadCurrentTab() {
            const date = document.getElementById('dateSelect').value;
            const symbol = document.getElementById('symbolSearch').value;
            let sortParam = currentSort.field ? `&sort_by=${currentSort.field}&sort_order=${currentSort.order}` : '';
            
            if (currentTab === 'ai_signals') {
                let url = `/api/signals?date=${date}&limit=2000${sortParam}`;
                if (symbol) url += `&symbol=${symbol}`;
                const res = await fetch(url);
                const data = await res.json();
                currentData = data.data || [];
            } else if (currentTab === 'swrsi') {
                let url = `/api/swrsi?${sortParam}`;
                if (date) url += `&date=${date}`;
                if (symbol) url += `&symbol=${symbol}`;
                const res = await fetch(url);
                const data = await res.json();
                currentData = data.signals || [];
            } else {
                const map = { support: 'support_resistance', macd: 'macd_signals', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
                let url = `/api/generic-data?collection=${map[currentTab]}&limit=2000${sortParam}`;
                if (date) url += `&date=${date}`;
                if (symbol) url += `&symbol=${symbol}`;
                const res = await fetch(url);
                const data = await res.json();
                currentData = data.data || [];
            }
            renderCurrentTab();
        }
        
        function renderCurrentTab() {
            if (currentTab === 'ai_signals') renderAITable();
            else if (currentTab === 'swrsi') renderSWRSITable();
            else renderGenericTable();
        }
        
        function getLtpDisplay(symbol, highPrice) {
            const ltp = dseLtpData[symbol] || null;
            if (!ltp) return '<span style="color:#888;">-</span>';
            let cls = '';
            let arrow = '';
            const alertStatus = getAlertStatus(symbol);
            if (highPrice && ltp > highPrice) {
                cls = 'ltp-above';
                arrow = ' 🚀';
            } else if (alertStatus === 'above') {
                cls = 'ltp-above';
                arrow = ' ↑';
            } else if (alertStatus === 'below') {
                cls = 'ltp-below';
                arrow = ' ↓';
            }
            return `<span class="${cls}" style="font-weight:bold;">${ltp.toFixed(2)}${arrow}</span>`;
        }
        
        function getAlertStatus(symbol) {
            for (const rule of alertRules) {
                if (rule.symbol === symbol) {
                    const ltp = dseLtpData[symbol];
                    if (ltp && rule.condition === 'above' && ltp > rule.threshold) return 'above';
                    if (ltp && rule.condition === 'below' && ltp < rule.threshold) return 'below';
                }
            }
            return null;
        }
        
        function getRowClass(symbol, highPrice) {
            const alertStatus = getAlertStatus(symbol);
            const ltp = dseLtpData[symbol];
            if (ltp && highPrice && ltp > highPrice) return 'ltp-break-high';
            if (alertStatus) return 'ltp-alert-row';
            return '';
        }
        
        function getRRRClass(rrr) {
            if (!rrr) return '';
            if (rrr >= 2) return 'rrr-high';
            if (rrr >= 1) return 'rrr-medium';
            return 'rrr-low';
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
        
        function renderAITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) {
                div.innerHTML = '<p style="text-align:center;padding:40px;">No data available</p>';
                document.getElementById('recordCount').textContent = '(0)';
                return;
            }
            
            let html = `<table><thead><tr>
                <th>#</th><th onclick="handleSort('symbol')">Symbol</th><th>Date</th>
                <th onclick="handleSort('current_price')">Price</th><th>LTP</th><th>Sector</th>
                <th onclick="handleSort('final_signal')">Signal</th>
                <th onclick="handleSort('final_combined_score')">Score</th>
                <th>LLM</th><th>LLM%</th><th>XGB</th><th>XGB%</th>
                <th>PPO</th><th>PPO%</th><th>Agentic</th>
                <th onclick="handleSort('diff')">Diff</th>
                <th onclick="handleSort('gape')">Gape</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th>
                <th>Exposure</th><th>Risk%</th><th>Actions</th>
             </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const highPrice = r.high || r.current_high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const alertStatus = getAlertStatus(r.symbol);
                const ltpBreakHigh = (dseLtpData[r.symbol] && highPrice && dseLtpData[r.symbol] > highPrice);
                const rrr = r.risk_reward_ratio || 0;
                
                html += `<tr class="${rowClass}">
                    <td>${i+1}</td>
                    <td><strong>${r.symbol}${r.edited ? '<span class="edited-badge">✏️</span>' : ''}${alertStatus ? ' 🔔' : ''}${ltpBreakHigh ? '<span class="ltp-break-badge">HIGH</span>' : ''}</strong></td>
                    <td>${r.analysis_date || ''}</td>
                    <td>${(r.current_price || 0).toFixed(2)}</td>
                    <td>${ltpDisplay}</td>
                    <td>${r.sector || ''}</td>
                    <td class="${getSignalClass(r.final_signal)}">${r.final_signal || ''}</td>
                    <td><strong>${(r.final_combined_score || 0).toFixed(1)}</strong></td>
                    <td>${r.llm_signal || ''}</td><td>${((r.llm_confidence || 0)).toFixed(0)}%</td>
                    <td>${r.xgb_signal || ''}</td><td>${((r.xgb_confidence || 0)).toFixed(0)}%</td>
                    <td>${r.ppo_signal || ''}</td><td>${((r.ppo_confidence || 0)).toFixed(0)}%</td>
                    <td>${(r.agentic_score || 0).toFixed(1)}</td>
                    <td style="color:#ffd700;">${r.diff !== undefined ? (r.diff > 0 ? '+' : '') + r.diff.toFixed(2) : '-'}</td>
                    <td style="color:#00d4ff;">${r.gape !== undefined ? r.gape.toFixed(2) : '-'}</td>
                    <td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>
                    <td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>
                    <td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>
                    <td class="${getRRRClass(rrr)}"><strong>${rrr.toFixed(2)}</strong></td>
                    <td>${r.total_exposure ? '৳'+r.total_exposure.toLocaleString() : '-'}</td>
                    <td>${r.risk_percent ? r.risk_percent.toFixed(1)+'%' : '-'}</td>
                    <td>
                        <button class="edit-btn" onclick="editTrade('${r.symbol}','${r.analysis_date}')">✏️</button>
                        <button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button>
                        <button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}')">🗑️</button>
                    </td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} records)`;
        }
        
        function renderSWRSITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) {
                div.innerHTML = '<p style="text-align:center;padding:40px;">No SWRSI data</p>';
                return;
            }
            
            let html = `<table><thead><tr>
                <th>#</th><th onclick="handleSort('symbol')">Symbol</th><th>Sector</th><th>LTP</th>
                <th onclick="handleSort('composite_score')">Score</th>
                <th>Weekly Div</th><th>Weekly Label</th>
                <th onclick="handleSort('diff')">Diff</th><th onclick="handleSort('gape')">Gape</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Actions</th>
             </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const highPrice = r.high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const alertStatus = getAlertStatus(r.symbol);
                const rrr = r.risk_reward_ratio || 0;
                
                html += `<tr>
                    <td>${i+1}</td>
                    <td><strong>${r.symbol}${alertStatus ? ' 🔔' : ''}</strong></td>
                    <td>${r.sector || ''}</td>
                    <td>${ltpDisplay}</td>
                    <td>${(r.composite_score || 0).toFixed(0)}</td>
                    <td>${r.weekly_divergence || ''}</td>
                    <td>${r.weekly_strength_label || ''}</td>
                    <td style="color:#ffd700;">${r.diff !== undefined ? (r.diff > 0 ? '+' : '') + r.diff.toFixed(2) : '-'}</td>
                    <td style="color:#00d4ff;">${r.gape !== undefined ? r.gape.toFixed(2) : '-'}</td>
                    <td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>
                    <td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>
                    <td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>
                    <td class="${getRRRClass(rrr)}"><strong>${rrr.toFixed(2)}</strong></td>
                    <td><button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button>
                        <button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date || ''}','swrsi')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
        }
        
        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) {
                div.innerHTML = '<p style="text-align:center;padding:40px;">No data</p>';
                return;
            }
            
            let html = `<table><thead><tr>
                <th>#</th><th onclick="handleSort('symbol')">Symbol</th><th>LTP</th>
                <th onclick="handleSort('diff')">Diff</th><th onclick="handleSort('gape')">Gape</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Actions</th>
             </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const highPrice = r.high || r.current_high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const alertStatus = getAlertStatus(r.symbol);
                const rrr = r.risk_reward_ratio || 0;
                
                html += `<tr>
                    <td>${i+1}</td>
                    <td><strong>${r.symbol}${alertStatus ? ' 🔔' : ''}</strong></td>
                    <td>${ltpDisplay}</td>
                    <td style="color:#ffd700;">${r.diff !== undefined ? (r.diff > 0 ? '+' : '') + r.diff.toFixed(2) : '-'}</td>
                    <td style="color:#00d4ff;">${r.gape !== undefined ? r.gape.toFixed(2) : '-'}</td>
                    <td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>
                    <td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>
                    <td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>
                    <td class="${getRRRClass(rrr)}"><strong>${rrr.toFixed(2)}</strong></td>
                    <td><button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button>
                        <button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date || r.date || ''}','${currentTab}')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
        }
        
        function handleSort(field) {
            if (currentSort.field === field) {
                currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.field = field;
                currentSort.order = (field === 'diff') ? 'asc' : (field === 'gape') ? 'desc' : 'asc';
            }
            updateSortStatus();
            loadCurrentTab();
        }
        
        function resetSort() {
            currentSort = { field: null, order: null };
            updateSortStatus();
            loadCurrentTab();
        }
        
        function updateSortStatus() {
            const div = document.getElementById('sortStatus');
            if (currentSort.field) {
                div.innerHTML = `📊 Sorted by: ${currentSort.field} (${currentSort.order.toUpperCase()}) | <span style="cursor:pointer;color:#ffa500;" onclick="resetSort()">↺ Reset</span>`;
            } else {
                div.innerHTML = '📊 Default: diff ASC (low first), gape DESC (high first)';
            }
        }
        
        function switchTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('symbolSearch').value = '';
            const map = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
            loadDates(map[tab]);
            loadCurrentTab();
        }
        
        async function deleteRecord(symbol, date, collection = 'ai_signals') {
            if (!confirm(`Delete ${symbol}?`)) return;
            const map = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
            await fetch(`/api/delete-signal?collection=${map[collection]}&symbol=${symbol}&date=${date}`, { method: 'DELETE' });
            loadCurrentTab();
        }
        
        async function deleteAllByDate() {
            const date = document.getElementById('dateSelect').value;
            if (!date) { alert('Select a date first!'); return; }
            if (!confirm(`Delete ALL records for ${date}?`)) return;
            const collection = COLLECTION_MAP[currentTab];
            await fetch(`/api/delete-all-by-date?collection=${collection}&date=${date}`, { method: 'DELETE' });
            loadDates(collection);
            loadCurrentTab();
        }
        
        function editTrade(symbol, date) {
            const record = currentData.find(r => r.symbol === symbol);
            if (record) {
                document.getElementById('tradeSymbolSelect').value = symbol;
                onTradeSymbolChange();
                openTradeModal();
            }
        }
        
        async function openTradeForSymbol(symbol) {
            await loadTradeSymbols();
            document.getElementById('tradeSymbolSelect').value = symbol;
            onTradeSymbolChange();
            openTradeModal();
        }
        
        async function loadTradeSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTION_MAP[currentTab];
            const res = await fetch(`/api/collection-symbols?collection=${collection}&date=${date}`);
            const symbols = await res.json();
            const select = document.getElementById('tradeSymbolSelect');
            select.innerHTML = '<option value="">Select Symbol</option>';
            symbols.forEach(s => {
                const option = document.createElement('option');
                option.value = s;
                option.textContent = s;
                select.appendChild(option);
            });
        }
        
        function onTradeSymbolChange() {
            const symbol = document.getElementById('tradeSymbolSelect').value;
            const record = currentData.find(r => r.symbol === symbol);
            if (record) {
                document.getElementById('tradeEntryPrice').value = record.entry_price || '';
                document.getElementById('tradeStopLoss').value = record.stop_loss || '';
                document.getElementById('tradeTargetPrice').value = record.target_price || '';
                document.getElementById('tradeTotalExposure').value = record.total_exposure || '';
                document.getElementById('tradeRiskPercent').value = record.risk_percent || '';
                calculateTradeStats();
            }
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
        
        async function saveTrade() {
            const symbol = document.getElementById('tradeSymbolSelect').value;
            if (!symbol) { alert('Select symbol'); return; }
            const entry = parseFloat(document.getElementById('tradeEntryPrice').value) || 0;
            const sl = parseFloat(document.getElementById('tradeStopLoss').value) || 0;
            const tp = parseFloat(document.getElementById('tradeTargetPrice').value) || 0;
            const exposure = parseFloat(document.getElementById('tradeTotalExposure').value) || 0;
            const riskPct = parseFloat(document.getElementById('tradeRiskPercent').value) || 0;
            
            const record = currentData.find(r => r.symbol === symbol);
            const date = record ? (record.analysis_date || record.date || '') : '';
            if (!date) { alert('Date not found'); return; }
            
            const params = new URLSearchParams({
                collection: COLLECTION_MAP[currentTab],
                symbol, date,
                entry_price: entry, stop_loss: sl, target_price: tp,
                total_exposure: exposure, risk_percent: riskPct
            });
            
            await fetch(`/api/update-trade?${params}`, { method: 'PUT' });
            closeTradeModal();
            loadCurrentTab();
        }
        
        // Alert functions
        function loadAlertRules() {
            const saved = localStorage.getItem('ltpAlertRules');
            if (saved) alertRules = JSON.parse(saved);
            updateAlertUI();
        }
        
        function saveAlertRules() {
            localStorage.setItem('ltpAlertRules', JSON.stringify(alertRules));
            updateAlertUI();
            renderCurrentTab();
        }
        
        function updateAlertUI() {
            const bar = document.getElementById('alertStatusBar');
            const list = document.getElementById('currentAlertsList');
            if (alertRules.length > 0) {
                bar.style.display = 'block';
                bar.innerHTML = `🔔 ${alertRules.length} Active Alert(s): ` + alertRules.map(r => `${r.symbol} ${r.condition === 'above' ? '↑>' : '↓<'} ${r.threshold}`).join(' | ');
                list.innerHTML = alertRules.map((r, i) => `<div style="background:#1a1a2e;padding:8px;margin:5px 0;border-radius:5px;">🔔 ${r.symbol} ${r.condition==='above'?'↑ Above':'↓ Below'} ${r.threshold} <button onclick="removeAlertRule(${i})" style="float:right;background:#ff4757;border:none;padding:2px 8px;border-radius:4px;">✕</button></div>`).join('');
            } else {
                bar.style.display = 'none';
                list.innerHTML = '';
            }
        }
        
        async function openAlertModal() {
            await loadAlertSymbols();
            document.getElementById('alertModal').classList.add('open');
            updateAlertUI();
        }
        
        function closeAlertModal() {
            document.getElementById('alertModal').classList.remove('open');
        }
        
        async function loadAlertSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTION_MAP[currentTab];
            const res = await fetch(`/api/collection-symbols?collection=${collection}&date=${date}`);
            const symbols = await res.json();
            const select = document.getElementById('alertSymbolSelect');
            select.innerHTML = '<option value="">Select Symbol</option>';
            symbols.forEach(s => {
                const option = document.createElement('option');
                option.value = s;
                option.textContent = s;
                select.appendChild(option);
            });
        }
        
        function addAlertRule() {
            const symbol = document.getElementById('alertSymbolSelect').value;
            const condition = document.getElementById('alertCondition').value;
            const threshold = parseFloat(document.getElementById('alertThresholdPrice').value);
            if (!symbol || !threshold) { alert('Select symbol and enter threshold'); return; }
            alertRules = alertRules.filter(r => r.symbol !== symbol);
            alertRules.push({ symbol, condition, threshold });
            saveAlertRules();
            document.getElementById('alertThresholdPrice').value = '';
            closeAlertModal();
        }
        
        function removeAlertRule(index) {
            alertRules.splice(index, 1);
            saveAlertRules();
            renderCurrentTab();
        }
        
        function openTradeModal() {
            document.getElementById('tradeModal').classList.add('open');
        }
        
        function closeTradeModal() {
            document.getElementById('tradeModal').classList.remove('open');
        }
        
        // PWA Install
        let deferredPrompt;
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
            document.getElementById('installBtn').style.display = 'inline-block';
        });
        
        function installApp() {
            if (deferredPrompt) {
                deferredPrompt.prompt();
                deferredPrompt.userChoice.then(() => {
                    deferredPrompt = null;
                    document.getElementById('installBtn').style.display = 'none';
                });
            }
        }
        
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js');
        }
    </script>
</body>
</html>
'''

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)