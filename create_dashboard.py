"""
create_dashboard.py
✅ 100% new.dsebd.org — old site puropuri baad
✅ LTP from tickerInitial JSON (388 symbols)
✅ Market status from DSE header time (BST/UTC+6)
✅ MongoDB theke high/low merge kore breakout highlight
✅ All Tabs (AI Signals, SWRSI, S/R, RSI, Daily Buy)
✅ Sector cache via MongoDB aggregation
✅ Trade Modal, LTP Alert, RRR, UptimeRobot HEAD
✅ Default Sort: diff ASC, gape DESC
"""

import os
import re
import json
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="22.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

try:
    if os.path.isdir("static"):
        app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass

# =========================================
# ONLY new.dsebd.org
# =========================================
DSE_BASE = "https://new.dsebd.org"
DSE_LATEST = f"{DSE_BASE}/markets/latest-share-price"

# =========================================
# Sector Cache
# =========================================
sector_cache = {"data": {}, "timestamp": None, "expiry_seconds": 300}

def get_mongo_collection(collection_name=None):
    if not MONGODB_URI:
        return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        return client[DATABASE_NAME][collection_name or COLLECTION_NAME]
    except Exception:
        return None

# =========================================
# Bangladesh Timezone (BST = UTC+6)
# =========================================
BD_TIMEZONE = timezone(timedelta(hours=6))

def get_bd_time():
    return datetime.now(BD_TIMEZONE)

# =========================================
# Session
# =========================================
def make_session():
    s = requests.Session()
    s.verify = False
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
    })
    return s

# =========================================
# Market status
# =========================================
def _fetch_dse_header_time(session):
    try:
        r = session.get(DSE_LATEST, timeout=15)
        if r.status_code != 200:
            return None
        html = r.text

        m = re.search(r'On\s+(\w+ \d{1,2}, \d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)', html)
        if m:
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)}",
                                         "%b %d, %Y %I:%M %p").replace(tzinfo=BD_TIMEZONE)
            except ValueError:
                pass

        m = re.search(r'On\s+\w+,\s+(\w+ \d{1,2}, \d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)', html)
        if m:
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)}",
                                         "%B %d, %Y %I:%M %p").replace(tzinfo=BD_TIMEZONE)
            except ValueError:
                pass

        return None
    except Exception as e:
        print(f"[DSE] header time parse error: {e}")
        return None


def _is_dse_market_open_by_time():
    now = get_bd_time()
    wd = now.weekday()
    if wd in [4, 5]:
        print(f"[DSE] ❌ CLOSED (weekend day={wd})")
        return False
    minutes = now.hour * 60 + now.minute
    if 10 * 60 <= minutes <= 14 * 60 + 20:
        print(f"[DSE] ✅ OPEN (time {now.strftime('%H:%M')} BST)")
        return True
    print(f"[DSE] ❌ CLOSED (time {now.strftime('%H:%M')} BST)")
    return False


def is_dse_market_open():
    session = make_session()

    dse_time = _fetch_dse_header_time(session)
    if dse_time is not None:
        now_dse = get_bd_time()
        if dse_time.date() == now_dse.date():
            print(f"[DSE] ✅ OPEN (header {dse_time.strftime('%Y-%m-%d %H:%M')})")
            return True
        print(f"[DSE] ❌ CLOSED (header date {dse_time.date()} != today {now_dse.date()})")
        return False

    try:
        r = session.get(DSE_LATEST, timeout=15)
        if r.status_code == 200:
            text = r.text
            if re.search(r'Market\s+closed', text, re.IGNORECASE):
                print("[DSE] ❌ CLOSED (page text)")
                return False
            if re.search(r'Market\s+open', text, re.IGNORECASE):
                print("[DSE] ✅ OPEN (page text)")
                return True
    except Exception as e:
        print(f"[DSE] page text check failed: {e}")

    print("[DSE] ⚠️ using time fallback")
    return _is_dse_market_open_by_time()


def get_dse_header_time_str():
    session = make_session()
    dt = _fetch_dse_header_time(session) or get_bd_time()
    return dt.strftime('%Y-%m-%d %H:%M:%S')

# =========================================
# LTP parser — tickerInitial JSON
# =========================================
def parse_new_site_ltp(html_text):
    """
    new.dsebd.org er HTML table skeleton; real data tickerInitial JSON-e.
    tickerInitial: [{code, price, change, delta}, ...]
    """
    ltp_data = {}
    try:
        m = re.search(r'"tickerInitial"\s*:\s*(\[[^\]]*\])', html_text)
        if not m:
            print("[parse] ❌ tickerInitial not found")
            return ltp_data

        raw = m.group(1)
        try:
            raw = raw.encode('utf-8').decode('unicode_escape')
        except Exception:
            pass

        tickers = json.loads(raw)
        for t in tickers:
            sym = t.get('code')
            price = t.get('price')
            if not sym:
                continue
            try:
                ltp = float(str(price).replace(',', ''))
                if 0 < ltp < 50000:
                    ltp_data[sym.upper().strip()] = ltp
            except (ValueError, TypeError):
                continue

        print(f"📊 [new] tickerInitial: {len(ltp_data)} symbols")
        if ltp_data:
            print(f"📊 [new] sample: {list(ltp_data.items())[:5]}")
    except Exception as e:
        print(f"[parse] error: {e}")
    return ltp_data

# =========================================
# Sector + high/low helpers (MongoDB)
# =========================================
async def get_latest_sectors_for_symbols(symbols):
    if not symbols:
        return {}
    now = get_bd_time()
    if (sector_cache["timestamp"]
            and (now - sector_cache["timestamp"]).total_seconds() < sector_cache["expiry_seconds"]
            and sector_cache["data"]):
        cached = {k: v for k, v in sector_cache["data"].items() if k in symbols}
        if cached:
            return cached
    col = get_mongo_collection("daily_ai_signals")
    if col is None:
        return {}
    try:
        pipeline = [
            {"$match": {"symbol": {"$in": symbols}}},
            {"$sort": {"analysis_date": -1}},
            {"$group": {"_id": "$symbol", "latest_sector": {"$first": "$sector"}}},
            {"$match": {"latest_sector": {"$ne": None, "$ne": ""}}},
        ]
        results = list(col.aggregate(pipeline))
        sector_map = {d["_id"]: d["latest_sector"] for d in results}
        if sector_map:
            sector_cache["data"].update(sector_map)
            sector_cache["timestamp"] = now
        return sector_map
    except Exception as e:
        print(f"[SECTOR] error: {e}")
        return {}


async def get_latest_highs_for_symbols(symbols):
    """MongoDB theke latest high ber kori (breakout highlight er jonno)."""
    if not symbols:
        return {}
    col = get_mongo_collection("daily_ai_signals")
    if col is None:
        return {}
    try:
        pipeline = [
            {"$match": {"symbol": {"$in": symbols}, "high": {"$ne": None}}},
            {"$sort": {"analysis_date": -1}},
            {"$group": {"_id": "$symbol", "latest_high": {"$first": "$high"}}},
        ]
        results = list(col.aggregate(pipeline))
        return {d["_id"]: d["latest_high"] for d in results}
    except Exception as e:
        print(f"[HIGH] error: {e}")
        return {}

# =========================================
# LTP Cache
# =========================================
ltp_cache = {"data": {}, "timestamp": None}

# =========================================
# API
# =========================================
@app.api_route("/head", methods=["GET", "HEAD"])
async def uptime_robot_head():
    return Response(content="OK", status_code=200,
                    headers={"Cache-Control": "no-cache", "X-Health-Status": "healthy"})

@app.get("/api/health")
async def health():
    col = get_mongo_collection()
    return {
        "status": "ok",
        "mongodb": "connected" if col else "not configured",
        "dse_market": "OPEN" if is_dse_market_open() else "CLOSED",
        "dse_time": get_dse_header_time_str(),
        "local_bd_time": get_bd_time().strftime('%Y-%m-%d %H:%M:%S'),
    }

@app.get("/api/market-status")
async def market_status():
    now_bd = get_bd_time()
    is_open = is_dse_market_open()
    close_time = now_bd.replace(hour=14, minute=20, second=0, microsecond=0)
    sec_to_close = (close_time - now_bd).total_seconds()
    alert_10min = is_open and (0 < sec_to_close <= 600)
    next_open = None
    if not is_open:
        wd = now_bd.weekday()
        next_open = "Sunday 10:00 AM" if wd in [4, 5] else "Tomorrow 10:00 AM"
    return {
        "is_open": is_open,
        "alert_10min": alert_10min,
        "alert_message": "⚠️ DSE CLOSING IN 10 MINUTES!" if alert_10min else "",
        "next_open": next_open,
        "dse_time": get_dse_header_time_str(),
        "bd_time": now_bd.strftime('%Y-%m-%d %H:%M:%S'),
        "source": "new.dsebd.org",
    }

@app.get("/api/dse-ltp")
async def get_dse_ltp():
    market_is_open = is_dse_market_open()
    if ltp_cache["timestamp"]:
        age = (get_bd_time() - ltp_cache["timestamp"]).total_seconds()
        max_age = 120 if market_is_open else 300
        if age < max_age and ltp_cache["data"]:
            return ltp_cache["data"]

    session = make_session()
    ltp_data = {}
    try:
        print("[LTP] new.dsebd.org...")
        r = session.get(DSE_LATEST, timeout=15)
        if r.status_code == 200:
            ltp_data = parse_new_site_ltp(r.text)
    except Exception as e:
        print(f"[LTP] new site failed: {e}")

    if ltp_data:
        status = "live" if market_is_open else "closed_with_data"
        result = {
            "status": status,
            "total_symbols": len(ltp_data),
            "ltp_data": ltp_data,
            "source": "new.dsebd.org",
            "dse_time": get_dse_header_time_str(),
        }
        ltp_cache["data"] = result
        ltp_cache["timestamp"] = get_bd_time()
        return result

    if ltp_cache["data"]:
        cached = ltp_cache["data"].copy()
        cached["status"] = "cached"
        cached["source"] = "cache"
        return cached

    return {
        "status": "error",
        "message": "DSE theke LTP data paoa jayni",
        "ltp_data": {},
        "source": "new.dsebd.org",
    }

@app.get("/api/dse-highs")
async def get_dse_highs(symbols: str = Query(None)):
    """MongoDB theke latest high map - frontend merge korbe."""
    if not symbols:
        return {}
    syms = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    return await get_latest_highs_for_symbols(syms)

# =========================================
# Date query helpers
# =========================================
def build_date_query(date_value):
    return {'$or': [
        {'analysis_date': date_value},
        {'analysis_date': {'$regex': f'^{date_value}'}},
        {'saved_at': {'$regex': f'^{date_value}'}},
    ]}

def get_latest_date_from_collection(collection_name):
    col = get_mongo_collection(collection_name)
    if col is None:
        return None
    doc = col.find_one({'analysis_date': {'$exists': True, '$ne': None, '$ne': ''}},
                       sort=[('analysis_date', -1)])
    if doc and doc.get('analysis_date'):
        v = doc['analysis_date']
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
        if isinstance(v, datetime):
            return v.strftime('%Y-%m-%d')
    doc = col.find_one({'saved_at': {'$exists': True}}, sort=[('saved_at', -1)])
    if doc and doc.get('saved_at'):
        v = doc['saved_at']
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
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
    except Exception:
        pass
    try:
        for doc in col.find({'saved_at': {'$exists': True}}, {'saved_at': 1}).limit(2000):
            v = doc.get('saved_at', '')
            if isinstance(v, str) and len(v) >= 10:
                d = v[:10]
                if re.match(r'\d{4}-\d{2}-\d{2}', d):
                    dates_set.add(d)
    except Exception:
        pass
    return sorted(list(dates_set), reverse=True)

@app.get("/api/signals")
async def get_signals(
    date: str = Query(None), signal: str = Query(None), symbol: str = Query(None),
    min_score: float = Query(0), limit: int = Query(1000),
    sort_by: str = Query(None), sort_order: str = Query("asc"),
):
    collection = get_mongo_collection()
    if collection is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest = get_latest_date_from_collection("daily_ai_signals")
        if latest:
            query = build_date_query(latest)
    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol: query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}
    sort_criteria = ([(sort_by, -1 if sort_order == "desc" else 1)] if sort_by
                     else [('diff', 1), ('gape', -1)])
    data = list(collection.find(query, {'_id': 0}).sort(sort_criteria).limit(limit))
    if data:
        symbols = list({d.get('symbol') for d in data if d.get('symbol')})
        sector_map = await get_latest_sectors_for_symbols(symbols)
        for d in data:
            sym = d.get('symbol')
            if sym and sym in sector_map:
                d['sector'] = sector_map[sym]
            elif sym:
                d['sector'] = d.get('sector', 'Other')
    return {"data": data}

@app.get("/api/stats")
async def get_stats(date: str = Query(None)):
    collection = get_mongo_collection()
    if collection is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest = get_latest_date_from_collection("daily_ai_signals")
        if latest:
            query = build_date_query(latest)
    pipeline = [{'$match': query},
                {'$group': {'_id': None, 'total': {'$sum': 1},
                            'avg_score': {'$avg': '$final_combined_score'}}}]
    r = list(collection.aggregate(pipeline))
    return {k: v for k, v in r[0].items() if k != '_id'} if r else {"total": 0, "avg_score": 0}

@app.get("/api/generic-data")
async def get_generic_data(
    collection: str = Query(...), date: str = Query(None), symbol: str = Query(None),
    limit: int = Query(500), sort_by: str = Query(None), sort_order: str = Query("asc"),
):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest = get_latest_date_from_collection(collection)
        if latest:
            query = build_date_query(latest)
    if symbol:
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    sort_criteria = ([(sort_by, -1 if sort_order == "desc" else 1)] if sort_by
                     else [('diff', 1), ('gape', -1)])
    data = list(col.find(query, {'_id': 0}).sort(sort_criteria).limit(limit))
    if data:
        symbols = list({d.get('symbol') for d in data if d.get('symbol')})
        if symbols:
            sector_map = await get_latest_sectors_for_symbols(symbols)
            for d in data:
                sym = d.get('symbol')
                if sym and sym in sector_map:
                    d['sector'] = sector_map[sym]
                elif sym:
                    d['sector'] = d.get('sector', 'Other')
    return {"data": data}

@app.delete("/api/delete-signal")
async def delete_signal(collection: str = Query("daily_ai_signals"),
                        symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    r = col.delete_one({'symbol': symbol, 'analysis_date': date})
    if r.deleted_count == 0:
        r = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    return {"deleted": r.deleted_count}

@app.delete("/api/delete-all-by-date")
async def delete_all_by_date(collection: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    r1 = col.delete_many({'analysis_date': date})
    r2 = col.delete_many({'saved_at': {'$regex': f'^{date}'}})
    return {"deleted": r1.deleted_count + r2.deleted_count, "collection": collection, "date": date}

@app.put("/api/update-trade")
async def update_trade(
    collection: str = Query("daily_ai_signals"),
    symbol: str = Query(...), date: str = Query(...),
    entry_price: float = Query(None), stop_loss: float = Query(None),
    target_price: float = Query(None), total_exposure: float = Query(None),
    risk_percent: float = Query(None),
):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    fields = {'edited': True, 'edited_at': datetime.now().isoformat()}
    if entry_price is not None: fields['entry_price'] = entry_price
    if stop_loss is not None: fields['stop_loss'] = stop_loss
    if target_price is not None: fields['target_price'] = target_price
    if total_exposure is not None: fields['total_exposure'] = total_exposure
    if risk_percent is not None: fields['risk_percent'] = risk_percent
    if entry_price and stop_loss and target_price:
        risk = abs(entry_price - stop_loss)
        reward = abs(target_price - entry_price)
        if risk > 0:
            fields['risk_reward_ratio'] = round(reward / risk, 2)
    r = col.update_one({'symbol': symbol, 'analysis_date': date}, {'$set': fields})
    if r.matched_count == 0:
        r = col.update_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}}, {'$set': fields})
    return {"updated": r.modified_count, "matched": r.matched_count}

@app.get("/api/collection-symbols")
async def get_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    query = {}
    if date:
        query = build_date_query(date)
    else:
        latest = get_latest_date_from_collection(collection)
        if latest:
            query = build_date_query(latest)
    symbols = col.distinct('symbol', query)
    return sorted([s for s in symbols if s])

# =========================================
# Dashboard HTML
# =========================================
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🤖 AI Trading Signals</title>
    <meta name="theme-color" content="#00d4ff">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="AI Signals">
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
        .trade-btn { background: #00cc66; color: #000; font-weight: bold; margin-left: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 0.7em; background: #111122; border-radius: 10px; overflow: hidden; }
        th { background: #1a1a2e; padding: 10px 5px; color: #00d4ff; white-space: nowrap; cursor: pointer; user-select: none; }
        th:hover { background: #1e1e38; }
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
        .signal-SS { color: #ff0000; font-weight: bold; }
        .ltp-alert-row { animation: ltpBlink 0.6s infinite; }
        @keyframes ltpBlink { 0%,100% { background: #ff475730; } 50% { background: #ff475760; } }
        .ltp-above { color: #00ff88 !important; font-weight: bold; }
        .ltp-below { color: #ff4757 !important; font-weight: bold; }
        .ltp-break-high { background: linear-gradient(90deg, #00ff8818, #0a0a0f) !important; border-left: 4px solid #00ff88 !important; animation: highBreakPulse 2s infinite; }
        @keyframes highBreakPulse { 0%,100% { background: #00ff8810; } 50% { background: #00ff8825; } }
        .ltp-break-badge { background: #00ff88; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 0.7em; margin-left: 5px; font-weight: bold; animation: badgePulse 1s infinite; }
        @keyframes badgePulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
        .rrr-high { color: #00ff88; font-weight: bold; }
        .rrr-medium { color: #ffd700; }
        .rrr-low { color: #ff4757; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; overflow-y: auto; }
        .modal.open { display: flex; }
        .modal-content { background: #1a1a2e; padding: 25px; border-radius: 15px; max-width: 550px; width: 90%; border: 2px solid #ffa500; max-height: 90vh; overflow-y: auto; }
        .trade-modal-content { border-color: #00cc66; }
        .modal-content h3 { color: #ffa500; margin-bottom: 15px; }
        .trade-modal-content h3 { color: #00cc66; }
        .modal-content select, .modal-content input { width: 100%; padding: 10px; margin-bottom: 10px; }
        .modal-buttons { display: flex; gap: 10px; margin-top: 15px; }
        .modal-buttons button { flex: 1; }
        .trade-summary { background: #0f3460; padding: 15px; border-radius: 10px; margin: 15px 0; }
        .trade-summary span { display: block; margin: 5px 0; }
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
        <div class="tab" onclick="switchTab('rsi')">📈 RSI</div>
        <div class="tab" onclick="switchTab('buy')">✅ Daily Buy</div>
    </div>
    <div class="controls" id="allControls">
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

    <div id="tradeModal" class="modal">
        <div class="modal-content trade-modal-content">
            <h3>💰 Trade Management</h3>
            <label>📋 Select Symbol:</label>
            <select id="tradeSymbolSelect" onchange="onTradeSymbolChange()"><option value="">-- Loading... --</option></select>
            <label>📊 Entry Price:</label>
            <input type="number" id="tradeEntryPrice" step="0.01" oninput="calculateTradeStats()">
            <label>🛑 Stop Loss:</label>
            <input type="number" id="tradeStopLoss" step="0.01" oninput="calculateTradeStats()">
            <label>🎯 Target Price:</label>
            <input type="number" id="tradeTargetPrice" step="0.01" oninput="calculateTradeStats()">
            <label>💵 Total Exposure (Taka):</label>
            <input type="number" id="tradeTotalExposure" step="0.01" oninput="calculateTradeStats()">
            <label>⚠️ Risk %:</label>
            <input type="number" id="tradeRiskPercent" step="0.01" oninput="calculateTradeStats()">
            <div class="trade-summary" id="tradeSummary" style="display:none;">
                <span>📊 <strong>RRR:</strong> <span id="tradeRRR">-</span></span>
                <span>💸 <strong>Risk:</strong> ৳<span id="tradeRiskAmount">0</span></span>
                <span>🎯 <strong>Profit:</strong> ৳<span id="tradeProfitAmount">0</span></span>
                <span>📈 <strong>Qty:</strong> <span id="tradeQuantity">0</span> shares</span>
            </div>
            <div class="modal-buttons">
                <button class="save-btn" onclick="saveTrade()">💾 Save Trade</button>
                <button onclick="closeTradeModal()">Cancel</button>
            </div>
        </div>
    </div>

    <div id="alertStatusBar" style="background:#0f3460;padding:6px 12px;border-radius:6px;margin-bottom:8px;display:none;color:#ffa500;font-size:0.8em;"></div>
    <div id="sortStatus" style="background:#1a1a2e;padding:6px 12px;border-radius:6px;margin-bottom:8px;color:#00d4ff;font-size:0.8em;"></div>
    <div style="overflow-x:auto;" id="dynamicTable"></div>

    <script>
        let currentTab = 'ai_signals';
        let currentData = [];
        let dseLtpData = {};
        let dseHighData = {};
        let editingRow = null;
        let alertRules = [];
        let currentTradeSymbol = null;
        let currentSort = { field: null, order: null };

        const COLLECTION_MAP = {
            ai_signals: 'daily_ai_signals',
            swrsi: 'swrsi_signals',
            support: 'support_resistance',
            rsi: 'rsi_signals',
            buy: 'daily_buy_signals'
        };

        loadDates(COLLECTION_MAP[currentTab]);
        loadCurrentTab();
        checkMarketStatus();
        loadDseLtp();
        loadAlertRules();
        setInterval(checkMarketStatus, 60000);
        setInterval(loadDseLtp, 60000);
        updateSortStatus();

        function loadAlertRules() {
            const saved = localStorage.getItem('ltpAlertRules_v32');
            if (saved) { try { alertRules = JSON.parse(saved); } catch(e) { alertRules = []; } }
            updateAlertUI();
        }
        function saveAlertRules() {
            localStorage.setItem('ltpAlertRules_v32', JSON.stringify(alertRules));
            updateAlertUI(); renderCurrentTab();
        }
        function updateAlertUI() {
            const bar = document.getElementById('alertStatusBar');
            if (alertRules.length > 0) {
                bar.style.display = 'block';
                bar.innerHTML = '🔔 <strong>' + alertRules.length + ' Alert(s):</strong> ' +
                    alertRules.map(r => r.symbol + ' ' + (r.condition === 'above' ? '↑>' : '↓<') + ' ' + r.threshold).join(' | ');
            } else bar.style.display = 'none';
        }
        function updateSortStatus() {
            const s = document.getElementById('sortStatus');
            if (currentSort.field) {
                s.innerHTML = '📊 <strong>Sorted by:</strong> ' + currentSort.field + ' (' + currentSort.order.toUpperCase() + ') | <span style="cursor:pointer;color:#ffa500;" onclick="resetSort()">↺ Reset</span>';
            } else {
                s.innerHTML = '📊 <strong>Default:</strong> diff ASC, gape DESC';
            }
        }
        function handleSort(field) {
            if (currentSort.field === field) currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            else { currentSort.field = field; currentSort.order = (field === 'diff') ? 'asc' : (field === 'gape' ? 'desc' : 'asc'); }
            updateSortStatus(); loadCurrentTab();
        }
        function resetSort() { currentSort = { field: null, order: null }; updateSortStatus(); loadCurrentTab(); }
        function getSortIndicator(field) {
            if (currentSort.field === field) return '<span class="sort-indicator">' + (currentSort.order === 'asc' ? '▲' : '▼') + '</span>';
            if (!currentSort.field) {
                if (field === 'diff') return '<span class="sort-indicator" style="color:#ffa500;">▲</span>';
                if (field === 'gape') return '<span class="sort-indicator" style="color:#ffa500;">▼</span>';
            }
            return '<span class="sort-indicator" style="opacity:0.3;">⇅</span>';
        }

        async function checkMarketStatus() {
            try {
                const res = await fetch('/api/market-status');
                const s = await res.json();
                document.getElementById('marketStatus').innerHTML = s.is_open
                    ? `🟢 DSE MARKET OPEN | DSE Time: ${s.dse_time}`
                    : `🔴 DSE CLOSED | Opens ${s.next_open || 'next session'} | DSE Time: ${s.dse_time}`;
                document.getElementById('alertBox').style.display = s.alert_10min ? 'block' : 'none';
            } catch(e) { console.error('market status', e); }
        }

        async function loadDseLtp() {
            try {
                const r = await fetch('/api/dse-ltp');
                const j = await r.json();
                if (j.ltp_data && Object.keys(j.ltp_data).length > 0) {
                    dseLtpData = j.ltp_data;
                    console.log(`📊 LTP from ${j.source}: ${j.total_symbols} @ ${j.dse_time}`);
                }
                // high map load
                await loadDseHighs();
                renderCurrentTab();
            } catch(e) { console.error('LTP', e.message); }
        }

        async function loadDseHighs() {
            try {
                // currentData teke symbol list
                const syms = (currentData || []).map(x => x.symbol).filter(Boolean).slice(0, 500);
                if (!syms.length) return;
                const r = await fetch(`/api/dse-highs?symbols=${encodeURIComponent(syms.join(','))}`);
                const j = await r.json();
                if (j && typeof j === 'object') {
                    dseHighData = j;
                }
            } catch(e) { console.error('highs', e.message); }
        }

        async function loadDates(c) {
            const r = await fetch(`/api/dates?collection=${c}`);
            const d = await r.json();
            const s = document.getElementById('dateSelect');
            s.innerHTML = '<option value="">Latest</option>';
            if (Array.isArray(d)) d.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; s.appendChild(o); });
        }

        async function loadCurrentTab() {
            const date = document.getElementById('dateSelect').value;
            const symbol = document.getElementById('symbolSearch').value;
            let sortParam = '';
            if (currentSort.field) sortParam = `&sort_by=${currentSort.field}&sort_order=${currentSort.order}`;

            if (currentTab === 'ai_signals') {
                let url = `/api/signals?date=${date}&limit=1000${sortParam}`;
                if (symbol) url += `&symbol=${symbol}`;
                const j = await (await fetch(url)).json();
                currentData = j.data || [];
            } else if (currentTab === 'swrsi') {
                let url = `/api/generic-data?collection=swrsi_signals&limit=500${sortParam}`;
                if (date) url += `&date=${date}`;
                if (symbol) url += `&symbol=${symbol}`;
                const j = await (await fetch(url)).json();
                currentData = j.data || [];
            } else {
                const map = { support: 'support_resistance', rsi: 'rsi_signals', buy: 'daily_buy_signals' };
                let url = `/api/generic-data?collection=${map[currentTab]}&limit=500${sortParam}`;
                if (date) url += `&date=${date}`;
                if (symbol) url += `&symbol=${symbol}`;
                const j = await (await fetch(url)).json();
                currentData = j.data || [];
            }
            await loadDseHighs();
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
            loadDates(COLLECTION_MAP[t]);
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
        // ✅ highPrice na thakle MongoDB theke niye breakout check
        function resolveHigh(symbol, highPrice) {
            let h = highPrice;
            if (!h || h <= 0) h = dseHighData[symbol] || 0;
            return h;
        }
        function isLtpAboveHigh(symbol, highPrice) {
            const ltp = dseLtpData[symbol] || null;
            const h = resolveHigh(symbol, highPrice);
            if (!ltp || !h || h <= 0) return false;
            return ltp > h;
        }
        function getLtpDisplay(symbol, highPrice) {
            const ltp = dseLtpData[symbol] || null;
            const alertStatus = getLtpAlertStatus(symbol);
            const h = resolveHigh(symbol, highPrice);
            if (!ltp) return '<span style="color:#888;">-</span>';
            let cls = '', arrow = '';
            if (h && ltp > h) { cls = 'ltp-above'; arrow = ' 🚀'; }
            else if (alertStatus === 'above') { cls = 'ltp-above'; arrow = ' ↑'; }
            else if (alertStatus === 'below') { cls = 'ltp-below'; arrow = ' ↓'; }
            return `<span class="${cls}" style="font-weight:bold;">${ltp.toFixed(2)}${arrow}</span>`;
        }
        function getRowClass(symbol, highPrice) {
            const alertStatus = getLtpAlertStatus(symbol);
            if (isLtpAboveHigh(symbol, highPrice)) return 'ltp-break-high';
            if (alertStatus === 'above' || alertStatus === 'below') return 'ltp-alert-row';
            return '';
        }
        function getRRRClass(rrr) {
            if (!rrr || rrr === 0) return '';
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
                document.getElementById('tradeRRR').className = getRRRClass(parseFloat(rrr));
                if (exposure > 0 && riskPct > 0) {
                    const riskAmount = (exposure * riskPct) / 100;
                    const qty = risk > 0 ? Math.floor(riskAmount / risk) : 0;
                    document.getElementById('tradeRiskAmount').textContent = riskAmount.toFixed(2);
                    document.getElementById('tradeProfitAmount').textContent = (qty * reward).toFixed(2);
                    document.getElementById('tradeQuantity').textContent = qty;
                }
            } else summary.style.display = 'none';
        }

        async function onTradeSymbolChange() {
            const symbol = document.getElementById('tradeSymbolSelect').value;
            if (!symbol || symbol.includes('--')) return;
            currentTradeSymbol = symbol;
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
        function openTradeModal() { document.getElementById('tradeModal').classList.add('open'); loadTradeSymbols(); }
        function closeTradeModal() { document.getElementById('tradeModal').classList.remove('open'); }
        async function loadTradeSymbols() {
            const date = document.getElementById('dateSelect').value;
            const collection = COLLECTION_MAP[currentTab];
            const select = document.getElementById('tradeSymbolSelect');
            select.innerHTML = '<option value="">Loading...</option>';
            try {
                let url = `/api/collection-symbols?collection=${collection}`;
                if (date) url += `&date=${date}`;
                const symbols = await (await fetch(url)).json();
                select.innerHTML = '<option value="">-- Select --</option>';
                symbols.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; select.appendChild(o); });
            } catch(e) { select.innerHTML = '<option value="">Error</option>'; }
        }
        async function saveTrade() {
            const symbol = document.getElementById('tradeSymbolSelect').value;
            if (!symbol || symbol.includes('--')) { alert('Please select a symbol!'); return; }
            const entry = parseFloat(document.getElementById('tradeEntryPrice').value) || 0;
            const sl = parseFloat(document.getElementById('tradeStopLoss').value) || 0;
            const tp = parseFloat(document.getElementById('tradeTargetPrice').value) || 0;
            const exposure = parseFloat(document.getElementById('tradeTotalExposure').value) || 0;
            const riskPct = parseFloat(document.getElementById('tradeRiskPercent').value) || 0;
            const record = currentData.find(r => r.symbol === symbol);
            const date = record ? (record.analysis_date || record.date || '') : '';
            if (!date) { alert('Could not find date!'); return; }
            const params = new URLSearchParams({
                collection: COLLECTION_MAP[currentTab], symbol, date
            });
            if (entry) params.append('entry_price', entry);
            if (sl) params.append('stop_loss', sl);
            if (tp) params.append('target_price', tp);
            if (exposure) params.append('total_exposure', exposure);
            if (riskPct) params.append('risk_percent', riskPct);
            const r = await fetch(`/api/update-trade?${params}`, { method: 'PUT' });
            const result = await r.json();
            alert(`Trade saved (${result.updated} updated)`);
            closeTradeModal(); loadCurrentTab();
        }

        function startEdit(symbol, date, i) { editingRow = { symbol, date, rowIndex: i }; renderAITable(); }
        function cancelEdit() { editingRow = null; renderAITable(); }
        async function saveEdit(symbol, date) {
            const safeId = symbol.replace(/[^a-zA-Z0-9]/g, '_');
            const entry = parseFloat(document.getElementById(`edit-entry-${safeId}`).value) || 0;
            const sl = parseFloat(document.getElementById(`edit-sl-${safeId}`).value) || 0;
            const tp = parseFloat(document.getElementById(`edit-tp-${safeId}`).value) || 0;
            const params = new URLSearchParams({
                collection: COLLECTION_MAP[currentTab], symbol, date,
                entry_price: entry, stop_loss: sl, target_price: tp
            });
            await fetch(`/api/update-trade?${params}`, { method: 'PUT' });
            editingRow = null; loadCurrentTab();
        }

        function openAlertModal() { document.getElementById('alertModal').classList.add('open'); loadAlertSymbols(); renderCurrentAlerts(); }
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
                select.innerHTML = '<option value="">-- Select --</option>';
                symbols.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; select.appendChild(o); });
            } catch(e) { select.innerHTML = '<option value="">Error</option>'; }
        }
        function renderCurrentAlerts() {
            const section = document.getElementById('currentAlertsSection');
            const list = document.getElementById('currentAlertsList');
            if (alertRules.length === 0) { section.style.display = 'none'; return; }
            section.style.display = 'block';
            list.innerHTML = alertRules.map((r, i) =>
                `<div style="display:flex;justify-content:space-between;background:#1a1a2e;padding:8px;margin:5px 0;border-radius:5px;"><span>🔔 ${r.symbol} ${r.condition==='above'?'↑>':'↓<'} ${r.threshold}</span><button onclick="removeAlertRule(${i})" style="background:#ff4757;padding:5px;border:none;color:#fff;border-radius:4px;">✕</button></div>`
            ).join('');
        }
        function addAlertRule() {
            const symbol = document.getElementById('alertSymbolSelect').value;
            const condition = document.getElementById('alertCondition').value;
            const threshold = parseFloat(document.getElementById('alertThresholdPrice').value);
            if (!symbol || symbol.includes('--') || !threshold) return;
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
            const r = await fetch(`/api/delete-all-by-date?collection=${COLLECTION_MAP[currentTab]}&date=${date}`, { method: 'DELETE' });
            const result = await r.json();
            alert(`Deleted ${result.deleted} records`);
            loadDates(COLLECTION_MAP[currentTab]); loadCurrentTab();
        }
        async function deleteRecord(symbol, date) {
            if (!confirm(`Delete ${symbol}?`)) return;
            await fetch(`/api/delete-signal?collection=${COLLECTION_MAP[currentTab]}&symbol=${symbol}&date=${date}`, { method: 'DELETE' });
            loadCurrentTab();
        }

        function renderAITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data</p>'; return; }
            let html = `<table><thead><tr>
                <th>#</th>
                <th onclick="handleSort('symbol')">Symbol${getSortIndicator('symbol')}</th>
                <th>Date</th>
                <th>LTP</th>
                <th>Sector</th>
                <th onclick="handleSort('final_signal')">Signal${getSortIndicator('final_signal')}</th>
                <th onclick="handleSort('final_combined_score')">Score${getSortIndicator('final_combined_score')}</th>
                <th onclick="handleSort('diff')">Diff${getSortIndicator('diff')}</th>
                <th onclick="handleSort('gape')">Gape${getSortIndicator('gape')}</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th>
                <th>Exposure</th><th>Risk%</th><th>Act</th>
            </tr></thead><tbody>`;
            currentData.forEach((r, i) => {
                const safeId = (r.symbol || '').replace(/[^a-zA-Z0-9]/g, '_');
                const isEditing = editingRow && editingRow.symbol === r.symbol && editingRow.date === r.analysis_date;
                const isEdited = r.edited === true;
                const hasTrade = r.entry_price || r.stop_loss || r.target_price || r.total_exposure || r.risk_percent;
                const highPrice = r.high || r.current_high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const ltpBreakHigh = isLtpAboveHigh(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const rrr = r.risk_reward_ratio || 0;
                const rrrClass = getRRRClass(rrr);
                const entryCell = isEditing ? `<input class="editable-input" id="edit-entry-${safeId}" value="${(r.entry_price||0).toFixed(2)}">` : (r.entry_price ? `<span style="color:#00ff88;">${r.entry_price.toFixed(2)}</span>` : '-');
                const slCell = isEditing ? `<input class="editable-input" id="edit-sl-${safeId}" value="${(r.stop_loss||0).toFixed(2)}">` : (r.stop_loss ? `<span style="color:#ff4757;">${r.stop_loss.toFixed(2)}</span>` : '-');
                const tpCell = isEditing ? `<input class="editable-input" id="edit-tp-${safeId}" value="${(r.target_price||0).toFixed(2)}">` : (r.target_price ? `<span style="color:#00d4ff;">${r.target_price.toFixed(2)}</span>` : '-');
                const actionCell = isEditing
                    ? `<button class="save-btn" onclick="saveEdit('${r.symbol}','${r.analysis_date}')">💾</button><button class="delete-btn" onclick="cancelEdit()">❌</button>`
                    : `<button class="edit-btn" onclick="startEdit('${r.symbol}','${r.analysis_date}',${i})">✏️</button><button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}')">🗑️</button>`;
                const breakBadge = ltpBreakHigh ? '<span class="ltp-break-badge">🚀HIGH</span>' : '';
                html += `<tr class="${rowClass}">
                    <td>${i+1}</td>
                    <td><strong>${r.symbol}${isEdited ? '<span class="edited-badge">✏️</span>' : ''}${hasTrade ? '<span class="trade-badge">💰</span>' : ''}${alertStatus ? ' 🔔' : ''}${breakBadge}</strong></td>
                    <td>${r.analysis_date||''}</td>
                    <td>${ltpDisplay}</td>
                    <td>${r.sector || 'Other'}</td>
                    <td class="${getSignalClass(r.final_signal)}">${r.final_signal||''}</td>
                    <td><strong>${(r.final_combined_score||0).toFixed(1)}</strong></td>
                    <td style="color:#ffd700;font-weight:bold;">${r.diff !== undefined ? (r.diff > 0 ? '+' : '') + r.diff.toFixed(2) : '-'}</td>
                    <td style="color:#00d4ff;font-weight:bold;">${r.gape !== undefined ? r.gape.toFixed(2) : '-'}</td>
                    <td>${entryCell}</td><td>${slCell}</td><td>${tpCell}</td>
                    <td class="${rrrClass}"><strong>${rrr.toFixed(2)}</strong></td>
                    <td>${r.total_exposure ? '৳'+r.total_exposure.toLocaleString() : '-'}</td>
                    <td>${r.risk_percent ? r.risk_percent.toFixed(1)+'%' : '-'}</td>
                    <td>${actionCell}</td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} signals)`;
        }

        function renderSWRSITable() { renderGenericTable(); }
        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data</p>'; return; }
            const excludeKeys = ['_id','saved_at','analysis_date','date','symbol','entry_price','stop_loss','target_price','risk_reward_ratio','total_exposure','risk_percent','edited','edited_at'];
            const keys = Object.keys(currentData[0]).filter(k => !excludeKeys.includes(k) && !k.startsWith('_'));
            let html = `<table><thead><tr>
                <th>#</th>
                <th onclick="handleSort('symbol')">Symbol${getSortIndicator('symbol')}</th>
                <th>LTP</th>
                <th>Sector</th>
                ${keys.map(k => k === 'diff' || k === 'gape'
                    ? `<th onclick="handleSort('${k}')">${k}${getSortIndicator(k)}</th>`
                    : `<th>${k}</th>`).join('')}
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Exposure</th><th>Risk%</th><th>Act</th>
            </tr></thead><tbody>`;
            currentData.forEach((r, i) => {
                const highPrice = r.high || r.current_high || 0;
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const ltpBreakHigh = isLtpAboveHigh(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const recordDate = r.analysis_date || r.date || '';
                const hasTrade = r.entry_price || r.stop_loss || r.target_price;
                const rrr = r.risk_reward_ratio || 0;
                const rrrClass = getRRRClass(rrr);
                const breakBadge = ltpBreakHigh ? '<span class="ltp-break-badge">🚀HIGH</span>' : '';
                html += `<tr class="${rowClass}">
                    <td>${i+1}</td>
                    <td><strong>${r.symbol || ''}${hasTrade ? '<span class="trade-badge">💰</span>' : ''}${alertStatus ? ' 🔔' : ''}${breakBadge}</strong></td>
                    <td>${ltpDisplay}</td>
                    <td>${r.sector || 'Other'}</td>
                    ${keys.map(k => {
                        if (k === 'diff') return `<td style="color:#ffd700;font-weight:bold;">${r[k] !== undefined ? (r[k] > 0 ? '+' : '') + Number(r[k]).toFixed(2) : '-'}</td>`;
                        if (k === 'gape') return `<td style="color:#00d4ff;font-weight:bold;">${r[k] !== undefined ? Number(r[k]).toFixed(2) : '-'}</td>`;
                        return `<td>${r[k]??''}</td>`;
                    }).join('')}
                    <td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>
                    <td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>
                    <td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>
                    <td class="${rrrClass}"><strong>${rrr.toFixed(2)}</strong></td>
                    <td>${r.total_exposure ? '৳'+r.total_exposure.toLocaleString() : '-'}</td>
                    <td>${r.risk_percent ? r.risk_percent.toFixed(1)+'%' : '-'}</td>
                    <td><button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button><button class="delete-btn" onclick="deleteRecord('${r.symbol||''}','${recordDate}')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} records)`;
        }

        async function openTradeForSymbol(symbol) {
            await loadTradeSymbols();
            document.getElementById('tradeSymbolSelect').value = symbol;
            onTradeSymbolChange();
            openTradeModal();
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML)

# =========================================
# Run
# =========================================
if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
