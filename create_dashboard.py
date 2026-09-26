"""
create_dashboard.py — v25.0.0 (FULL CHROME HEADERS for Render compatibility)
✅ new.dsebd.org ONLY
✅ Full browser headers → DSE datacenter IP block bypass
✅ tickerInitial JSON → 388 symbols LTP
✅ Market status from DSE header time (NO UTC+6)
✅ High + Low from MongoDB → breakout/breakdown highlight
✅ All Tabs, Trade Modal, Alerts, RRR
"""

import os
import re
import json
import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="25.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================
# DSE URL
# =========================================
DSE_BASE = "https://new.dsebd.org"
DSE_LATEST = f"{DSE_BASE}/markets/latest-share-price"


# =========================================
# MongoDB
# =========================================
def get_mongo_collection(collection_name=None):
    if not MONGODB_URI:
        return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        return client[DATABASE_NAME][collection_name or COLLECTION_NAME]
    except Exception as e:
        print(f"[MONGO] error: {e}")
        return None


# =========================================
# Session — FULL CHROME HEADERS (DSE IP block bypass)
# =========================================
def make_session():
    s = requests.Session()
    s.verify = False
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,'
                  'image/avif,image/webp,image/apng,*/*;q=0.8,'
                  'application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'DNT': '1',
        'Referer': 'https://new.dsebd.org/',
        'Origin': 'https://new.dsebd.org',
    })
    return s


# =========================================
# Fetch DSE page
# =========================================
def fetch_dse_page():
    """
    Fetch new.dsebd.org latest-share-price with full browser headers.
    Returns (html_text, status_code, error_msg).
    """
    try:
        s = make_session()

        # Step 1: Visit homepage first (set cookies)
        try:
            s.get(f"{DSE_BASE}/", timeout=15)
        except Exception:
            pass

        # Step 2: Fetch the actual page
        r = s.get(DSE_LATEST, timeout=25)

        if r.status_code != 200:
            print(f"[LTP] ❌ HTTP {r.status_code}")
            return None, r.status_code, f"HTTP {r.status_code}"

        html = r.text
        print(f"[LTP] ✅ fetched: {len(html)} bytes, status={r.status_code}")

        # Debug if tickerInitial missing
        if 'tickerInitial' not in html:
            print(f"[LTP] ⚠️ tickerInitial NOT found. First 300 chars:")
            print(html[:300])
            try:
                with open("/tmp/dse_debug.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("[LTP] 💾 saved to /tmp/dse_debug.html")
            except Exception:
                pass

        return html, 200, None

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"[LTP] ❌ fetch error: {err}")
        return None, 0, err


# =========================================
# Parse tickerInitial JSON → LTP map
# =========================================
def parse_ticker_initial(html_text):
    """
    new.dsebd.org Next.js __next_f block-এ data double-escaped JSON string আকারে থাকে:
      \\"tickerInitial\\":[{\\"code\\":\\"1JANATAMF\\",\\"price\\":\\"3.70\\",...}]
    
    Strategy:
      1. 'tickerInitial' খুঁজি (backslash optional)
      2. তারপরে `[` থেকে `]` পর্যন্ত extract
      3. Escapes unescape করি
      4. json.loads
    """
    ltp_data = {}
    if not html_text:
        print("[LTP] ❌ html_text empty")
        return ltp_data

    # Step 1: tickerInitial খুঁজি (backslash-optional)
    m = re.search(r'tickerInitial', html_text)
    if not m:
        print("[LTP] ❌ tickerInitial not found")
        return ltp_data

    idx = m.start()
    print(f"[LTP] ✅ tickerInitial found at index {idx}")

    # Step 2: '[' খুঁজি tickerInitial-এর পরে 200 chars-এর মধ্যে
    bracket_start = html_text.find('[', idx, min(len(html_text), idx + 200))
    if bracket_start == -1:
        print("[LTP] ❌ no '[' after tickerInitial")
        return ltp_data

    # Step 3: matching ']' bracket counting দিয়ে
    depth = 0
    bracket_end = -1
    in_string = False
    escape_next = False
    
    for i in range(bracket_start, min(len(html_text), bracket_start + 500000)):
        c = html_text[i]
        
        if escape_next:
            escape_next = False
            continue
        if c == '\\':
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                bracket_end = i
                break

    if bracket_end == -1:
        print("[LTP] ❌ no matching ']' found")
        return ltp_data

    raw = html_text[bracket_start:bracket_end + 1]
    print(f"[LTP] extracted raw length: {len(raw)}")
    print(f"[LTP] raw first 200: {raw[:200]}")

    # Step 4: Escapes unescape + json.loads
    tickers = None

    # Method A: direct json.loads (if not escaped)
    try:
        tickers = json.loads(raw)
        print(f"[LTP] ✅ Direct json.loads: {len(tickers)} entries")
    except json.JSONDecodeError as e:
        print(f"[LTP] direct json.loads failed: {e}")

    # Method B: unescape \\\" → \" তারপর json.loads
    if tickers is None:
        try:
            cleaned = raw.replace('\\"', '"').replace('\\\\', '\\')
            tickers = json.loads(cleaned)
            print(f"[LTP] ✅ After unescape: {len(tickers)} entries")
        except json.JSONDecodeError as e:
            print(f"[LTP] unescape method failed: {e}")

    # Method C: unicode_escape decode
    if tickers is None:
        try:
            decoded = raw.encode('utf-8').decode('unicode_escape')
            tickers = json.loads(decoded)
            print(f"[LTP] ✅ After unicode_escape: {len(tickers)} entries")
        except Exception as e:
            print(f"[LTP] unicode_escape method failed: {e}")

    # Method D: regex fallback — সরাসরি code/price pair বের করি
    if tickers is None:
        print("[LTP] trying regex fallback...")
        tickers = []
        # Both \"code\":\"X\" and "code":"X" handle করি
        pattern = r'code\\?"\s*:\s*\\?"([A-Z0-9&._-]+)\\?"\s*,\s*\\?"price\\?"\s*:\s*\\?"([\d.,]+)\\?"'
        for match in re.finditer(pattern, raw):
            tickers.append({"code": match.group(1), "price": match.group(2)})
        if tickers:
            print(f"[LTP] ✅ Regex fallback: {len(tickers)} entries")
        else:
            print("[LTP] ❌ all parse methods failed")
            print(f"[LTP] raw dump first 500: {raw[:500]}")
            return ltp_data

    # Step 5: symbols extract
    for t in tickers:
        sym = t.get('code')
        price = t.get('price')
        if not sym or price in (None, ''):
            continue
        try:
            ltp = float(str(price).replace(',', '').strip())
            if 0 < ltp < 100000:
                ltp_data[sym.upper().strip()] = ltp
        except (ValueError, TypeError):
            continue

    print(f"✅ [LTP] parsed {len(ltp_data)} symbols")
    if ltp_data:
        print(f"✅ [LTP] sample: {list(ltp_data.items())[:5]}")
    return ltp_data
    

# =========================================
# Market status — from DSE header time (NO UTC+6)
# =========================================

def parse_dse_header_time(html_text):
    """
    Header time escaped JSON-এও থাকতে পারে।
    e.g. On Sep 26, 2026 at 4:58 AM
    """
    if not html_text:
        return None

    # Normal + escaped patterns
    patterns = [
        # Normal
        (r'On\s+(\w+\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)', "%b %d, %Y %I:%M %p"),
        (r'On\s+\w+,\s+(\w+\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)', "%B %d, %Y %I:%M %p"),
        (r'On\s+(\w+\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2})', "%b %d, %Y %H:%M"),
        # Escaped (\\" style)
        (r'On\s+(\w+\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2})\s*([AP]M)?', "%b %d, %Y %I:%M %p"),
    ]

    # First: try unescape whole HTML
    try:
        # If HTML has lots of \" try unescaping a copy
        if html_text.count('\\"') > 100:
            test_html = html_text.replace('\\"', '"').replace('\\\\', '\\')
        else:
            test_html = html_text
    except Exception:
        test_html = html_text

    for pat, fmt in patterns:
        for src in [html_text, test_html]:
            m = re.search(pat, src)
            if m:
                try:
                    if len(m.groups()) == 3 and m.group(3):
                        # 12-hour with AM/PM separately
                        time_str = f"{m.group(2)} {m.group(3)}"
                        return datetime.strptime(f"{m.group(1)} {time_str}", fmt)
                    else:
                        return datetime.strptime(f"{m.group(1)} {m.group(2)}", fmt)
                except ValueError:
                    continue

    # Fallback: search a broader window
    # Sometimes date is separated from time
    m = re.search(r'(\w+\s+\d{1,2},\s+\d{4})', test_html)
    if m:
        date_str = m.group(1)
        # Look for time nearby (±200 chars)
        for i in [m.start(), m.end()]:
            window = test_html[max(0, i-50):i+200]
            tm = re.search(r'(\d{1,2}:\d{2}\s*[AP]M)', window)
            if tm:
                try:
                    return datetime.strptime(f"{date_str} {tm.group(1)}", "%b %d, %Y %I:%M %p")
                except ValueError:
                    try:
                        return datetime.strptime(f"{date_str} {tm.group(1)}", "%B %d, %Y %I:%M %p")
                    except ValueError:
                        continue

    return None

def detect_market_status_from_text(html_text):
    if not html_text:
        return None, None
    next_open = None
    m = re.search(r'Opens\s+([A-Za-z]+\s+\d{1,2}\s+\w+,\s+\d{1,2}:\d{2})', html_text)
    if m:
        next_open = m.group(1).strip()
    if re.search(r'Market\s+closed', html_text, re.IGNORECASE):
        return False, next_open
    if re.search(r'Market\s+open', html_text, re.IGNORECASE):
        return True, next_open
    return None, next_open


def is_market_open_fallback_time(dse_time):
dataif dse_time is None:
        return None
    wd = dse_time.weekday()
    if wd in (4, 5):
        return False
    mins = dse_time.hour * 60 + dse_time.minute
    return 10 * 60 <= mins <= 14 * 60 + 20


# =========================================
# LTP Cache
# =========================================
ltp_cache = {
    "html": None,
    "ltp_data": {},
    "fetched_at": None,
    "dse_time_str": None,
    "is_open": None,
    "next_open": None,
}


def _refresh_ltp_cache(force=False):
    now = datetime.now()

    if not force and ltp_cache["fetched_at"]:
        age = (now - ltp_cache["fetched_at"]).total_seconds()
        max_age = 60 if ltp_cache["is_open"] else 300
        if age < max_age and ltp_cache["ltp_data"]:
            return True

    print("=" * 60)
    print("[refresh] Starting DSE fetch...")

    html, code, err = fetch_dse_page()
    if html is None:
        print(f"[refresh] ❌ fetch failed: {err}")
        return False

    print(f"[refresh] ✅ html fetched: {len(html)} bytes")

    ltp_data = parse_ticker_initial(html)
    print(f"[refresh] parsed LTP: {len(ltp_data)} symbols")

    dse_time = parse_dse_header_time(html)
    is_open_text, next_open = detect_market_status_from_text(html)

    if is_open_text is not None:
        is_open = is_open_text
    else:
        is_open = is_market_open_fallback_time(dse_time)

    # ✅ CRITICAL: only update cache if parse succeeded
    if not ltp_data:
        print("[refresh] ⚠️ parse returned 0 — NOT overwriting cache with empty")
        # যদি আগে ভালো data থাকে, রাখি
        if ltp_cache["ltp_data"]:
            print(f"[refresh] keeping previous cache: {len(ltp_cache['ltp_data'])} symbols")
            return False
        # না থাকলে empty রাখি
        ltp_cache["html"] = html
        ltp_cache["fetched_at"] = now
        print("[refresh] ❌ no data at all")
        return False

    ltp_cache["html"] = html
    ltp_cache["ltp_data"] = ltp_data
    ltp_cache["fetched_at"] = now
    ltp_cache["dse_time_str"] = dse_time.strftime('%Y-%m-%d %H:%M:%S') if dse_time else None
    ltp_cache["is_open"] = bool(is_open)
    ltp_cache["next_open"] = next_open

    print(f"🔄 [cache] LTP={len(ltp_data)} | time={ltp_cache['dse_time_str']} | open={is_open}")
    print("=" * 60)
    return True


# =========================================
# Sector + High/Low caches
# =========================================
sector_cache = {"data": {}, "timestamp": None, "expiry_seconds": 300}
hl_cache = {"data": {}, "timestamp": None, "expiry_seconds": 180}


async def get_latest_sectors_for_symbols(symbols):
    if not symbols:
        return {}
    now = datetime.now()
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
        print(f"[SECTOR] {e}")
        return {}


async def get_latest_high_low_for_symbols(symbols):
    if not symbols:
        return {}
    now = datetime.now()
    if (hl_cache["timestamp"]
            and (now - hl_cache["timestamp"]).total_seconds() < hl_cache["expiry_seconds"]
            and hl_cache["data"]):
        cached = {k: v for k, v in hl_cache["data"].items() if k in symbols}
        if cached:
            return cached

    col = get_mongo_collection("daily_ai_signals")
    if col is None:
        return {}
    try:
        pipeline = [
            {"$match": {
                "symbol": {"$in": symbols},
                "$or": [
                    {"high": {"$ne": None, "$ne": 0}},
                    {"low": {"$ne": None, "$ne": 0}},
                ]
            }},
            {"$sort": {"analysis_date": -1}},
            {"$group": {
                "_id": "$symbol",
                "latest_high": {"$first": "$high"},
                "latest_low": {"$first": "$low"},
            }},
        ]
        results = list(col.aggregate(pipeline))
        out = {d["_id"]: {"high": d.get("latest_high") or 0,
                          "low": d.get("latest_low") or 0} for d in results}
        if out:
            hl_cache["data"].update(out)
            hl_cache["timestamp"] = now
        print(f"📊 [HL] {len(out)} symbols")
        return out
    except Exception as e:
        print(f"[HL] {e}")
        return {}


# =========================================
# Health / HEAD
# =========================================
@app.api_route("/head", methods=["GET", "HEAD"])
async def uptime_head():
    return Response(content="OK", status_code=200,
                    headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
async def api_health():
    _refresh_ltp_cache()
    col = get_mongo_collection()
    return {
        "status": "ok",
        "mongodb": "connected" if col else "not configured",
        "dse_time": ltp_cache["dse_time_str"],
        "is_open": ltp_cache["is_open"],
        "ltp_symbols": len(ltp_cache["ltp_data"]),
        "source": "new.dsebd.org",
    }


@app.get("/api/debug-html")
async def api_debug_html():
    """Debug endpoint — DSE থেকে কী HTML আসছে দেখুন (first 5000 chars)."""
    _refresh_ltp_cache(force=True)
    html = ltp_cache.get("html") or ""
    return {
        "length": len(html),
        "has_tickerInitial": "tickerInitial" in html,
        "has_market_closed": "Market closed" in html,
        "has_TRADING_CODE": "TRADING CODE" in html,
        "first_1000_chars": html[:1000],
    }


# =========================================
# Market status
# =========================================
@app.get("/api/market-status")
async def api_market_status():
    _refresh_ltp_cache()
    dse_time_str = ltp_cache["dse_time_str"]
    is_open = ltp_cache["is_open"]
    next_open = ltp_cache["next_open"]

    alert_10min = False
    if is_open and dse_time_str:
        try:
            dt = datetime.strptime(dse_time_str, "%Y-%m-%d %H:%M:%S")
            close_dt = dt.replace(hour=14, minute=20, second=0, microsecond=0)
            sec_to_close = (close_dt - dt).total_seconds()
            alert_10min = 0 < sec_to_close <= 600
        except Exception:
            pass

    if not next_open and dse_time_str and not is_open:
        try:
            dt = datetime.strptime(dse_time_str, "%Y-%m-%d %H:%M:%S")
            wd = dt.weekday()
            if wd in (4, 5):
                next_open = "Sunday 10:00 AM"
            elif dt.hour >= 15:
                next_open = "Tomorrow 10:00 AM"
            else:
                next_open = "Today 10:00 AM"
        except Exception:
            pass

    return {
        "is_open": bool(is_open),
        "alert_10min": alert_10min,
        "alert_message": "⚠️ DSE CLOSING IN 10 MINUTES!" if alert_10min else "",
        "next_open": next_open,
        "dse_time": dse_time_str or "unknown",
        "source": "new.dsebd.org",
    }


@app.get("/api/dse-ltp")
async def api_dse_ltp():
    _refresh_ltp_cache()
    ltp = ltp_cache["ltp_data"]
    if not ltp:
        return {
            "status": "error",
            "message": "No LTP data",
            "ltp_data": {},
            "source": "new.dsebd.org",
            "dse_time": ltp_cache["dse_time_str"],
        }
    return {
        "status": "live" if ltp_cache["is_open"] else "closed_with_data",
        "total_symbols": len(ltp),
        "ltp_data": ltp,
        "source": "new.dsebd.org",
        "dse_time": ltp_cache["dse_time_str"],
    }


@app.get("/api/dse-highs")
async def api_dse_highs(symbols: str = Query(None)):
    if not symbols:
        return {}
    syms = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    return await get_latest_high_low_for_symbols(syms)


# =========================================
# Dates / Signals / Generic
# =========================================
def build_date_query(date_value):
    return {'$or': [
        {'analysis_date': date_value},
        {'analysis_date': {'$regex': f'^{date_value}'}},
        {'saved_at': {'$regex': f'^{date_value}'}},
    ]}


def get_latest_date(col_name):
    col = get_mongo_collection(col_name)
    if col is None:
        return None
    doc = col.find_one({'analysis_date': {'$exists': True, '$nin': [None, '']}},
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
async def api_dates(collection: str = Query("daily_ai_signals")):
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
async def api_signals(
    date: str = Query(None), signal: str = Query(None), symbol: str = Query(None),
    min_score: float = Query(0), limit: int = Query(1000),
    sort_by: str = Query(None), sort_order: str = Query("asc"),
):
    col = get_mongo_collection()
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    if date:
        query = build_date_query(date)
    else:
        latest = get_latest_date("daily_ai_signals")
        query = build_date_query(latest) if latest else {}

    if signal:
        query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if symbol:
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}
    if min_score > 0:
        query['final_combined_score'] = {'$gte': min_score}

    sort_criteria = ([(sort_by, -1 if sort_order == "desc" else 1)] if sort_by
                     else [('diff', 1), ('gape', -1)])

    data = list(col.find(query, {'_id': 0}).sort(sort_criteria).limit(limit))

    if data:
        syms = list({d.get('symbol') for d in data if d.get('symbol')})
        sector_map = await get_latest_sectors_for_symbols(syms)
        for d in data:
            sym = d.get('symbol')
            if sym and sym in sector_map:
                d['sector'] = sector_map[sym]
            elif sym:
                d['sector'] = d.get('sector', 'Other')

    return {"data": data}

@app.get("/api/debug-parse")
async def api_debug_parse():
    """Direct debug: fetch + parse + return detail."""
    import traceback
    result = {
        "fetch_ok": False,
        "html_length": 0,
        "tickerInitial_found": False,
        "regex_match": False,
        "json_parsed": False,
        "symbols_extracted": 0,
        "first_5_symbols": {},
        "header_time": None,
        "error": None,
    }
    try:
        html, code, err = fetch_dse_page()
        if html is None:
            result["error"] = f"fetch failed: {err}"
            return result

        result["fetch_ok"] = True
        result["html_length"] = len(html)
        result["tickerInitial_found"] = "tickerInitial" in html

        # Try regex
        m = re.search(r'"tickerInitial"\s*:\s*(\[[^\]]*\])', html)
        result["regex_match"] = m is not None

        if m:
            raw = m.group(1)
            result["raw_first_200"] = raw[:200]
            try:
                raw_decoded = raw.encode('utf-8').decode('unicode_escape')
                result["decoded_first_200"] = raw_decoded[:200]
            except Exception as e:
                result["decode_error"] = str(e)
                raw_decoded = raw

            try:
                tickers = json.loads(raw_decoded)
                result["json_parsed"] = True
                result["tickers_count"] = len(tickers)

                # Extract symbols
                ltp = {}
                for t in tickers:
                    sym = t.get('code')
                    price = t.get('price')
                    if not sym or price in (None, ''):
                        continue
                    try:
                        p = float(str(price).replace(',', '').strip())
                        if 0 < p < 100000:
                            ltp[sym.upper().strip()] = p
                    except (ValueError, TypeError):
                        continue
                result["symbols_extracted"] = len(ltp)
                result["first_5_symbols"] = dict(list(ltp.items())[:5])
            except Exception as e:
                result["json_error"] = str(e)
                result["json_error_trace"] = traceback.format_exc()[-500:]

        # Header time
        dse_time = parse_dse_header_time(html)
        result["header_time"] = dse_time.strftime('%Y-%m-%d %H:%M:%S') if dse_time else None

        # Look for actual header patterns (debug)
        patterns_found = []
        for pat in [
            r'On\s+\w+\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*[AP]M',
            r'On\s+\w+,\s+\w+\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*[AP]M',
            r'On\s+[^<]{5,60}at\s+\d{1,2}:\d{2}',
        ]:
            mm = re.search(pat, html)
            if mm:
                patterns_found.append(mm.group(0))

        result["header_patterns_found"] = patterns_found

        # Look for what's actually around 'Market closed'
        idx = html.find('Market closed')
        if idx > -1:
            result["market_closed_context"] = html[max(0, idx-100):idx+150]

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["trace"] = traceback.format_exc()[-1000:]

    return result
@app.get("/api/generic-data")
async def api_generic(
    collection: str = Query(...), date: str = Query(None), symbol: str = Query(None),
    limit: int = Query(500), sort_by: str = Query(None), sort_order: str = Query("asc"),
):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    if date:
        query = build_date_query(date)
    else:
        latest = get_latest_date(collection)
        query = build_date_query(latest) if latest else {}

    if symbol:
        query['symbol'] = {'$regex': f'^{symbol}', '$options': 'i'}

    sort_criteria = ([(sort_by, -1 if sort_order == "desc" else 1)] if sort_by
                     else [('diff', 1), ('gape', -1)])

    data = list(col.find(query, {'_id': 0}).sort(sort_criteria).limit(limit))

    if data:
        syms = list({d.get('symbol') for d in data if d.get('symbol')})
        if syms:
            sector_map = await get_latest_sectors_for_symbols(syms)
            for d in data:
                sym = d.get('symbol')
                if sym and sym in sector_map:
                    d['sector'] = sector_map[sym]
                elif sym:
                    d['sector'] = d.get('sector', 'Other')

    return {"data": data}


@app.delete("/api/delete-signal")
async def api_delete_signal(collection: str = Query("daily_ai_signals"),
                            symbol: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    r = col.delete_one({'symbol': symbol, 'analysis_date': date})
    if r.deleted_count == 0:
        r = col.delete_one({'symbol': symbol, 'saved_at': {'$regex': f'^{date}'}})
    return {"deleted": r.deleted_count}


@app.delete("/api/delete-all-by-date")
async def api_delete_all(collection: str = Query(...), date: str = Query(...)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    r1 = col.delete_many({'analysis_date': date})
    r2 = col.delete_many({'saved_at': {'$regex': f'^{date}'}})
    return {"deleted": r1.deleted_count + r2.deleted_count}


@app.put("/api/update-trade")
async def api_update_trade(
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
async def api_collection_symbols(collection: str = Query(...), date: str = Query(None)):
    col = get_mongo_collection(collection)
    if col is None:
        return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    if date:
        query = build_date_query(date)
    else:
        latest = get_latest_date(collection)
        query = build_date_query(latest) if latest else {}
    symbols = col.distinct('symbol', query)
    return sorted([s for s in symbols if s])


# =========================================
# Dashboard HTML
# =========================================
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🤖 AI Trading Signals</title>
<style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:system-ui,sans-serif; background:#0a0a0f; color:#e0e0e0; padding:15px; }
    .header { text-align:center; padding:22px; background:linear-gradient(45deg,#1a1a2e,#0f3460); border-radius:15px; margin-bottom:15px; }
    .header h1 { font-size:1.9em; background:linear-gradient(90deg,#00d4ff,#7b2ff7,#ff6b6b); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
    .status-line { margin-top:8px; font-size:0.95em; color:#aaf; }
    .alert-box { background:#ff4757; color:#fff; padding:12px; border-radius:10px; margin:12px 0; text-align:center; font-size:1.2em; font-weight:bold; display:none; animation:pulse 1s infinite; }
    @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.7; } }
    .tabs { display:flex; margin-bottom:15px; background:#111; border-radius:10px; overflow:hidden; flex-wrap:wrap; }
    .tab { flex:1; padding:12px; text-align:center; cursor:pointer; border-right:1px solid #222; color:#aaa; min-width:100px; font-size:0.9em; }
    .tab:last-child { border-right:none; }
    .tab.active { background:#1a1a2e; color:#00d4ff; font-weight:bold; }
    .controls { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; align-items:center; }
    select,input,button { padding:8px 12px; background:#1a1a2e; color:#fff; border:1px solid #333; border-radius:8px; font-size:0.85em; }
    button { cursor:pointer; background:#0f3460; }
    button:hover { background:#164a7a; }
    .btn-danger { background:#ff4757; color:#fff; font-weight:bold; }
    .btn-warn { background:#ffa500; color:#000; font-weight:bold; }
    .btn-success { background:#00cc66; color:#000; font-weight:bold; }
    table { width:100%; border-collapse:collapse; font-size:0.72em; background:#111122; border-radius:10px; overflow:hidden; }
    th { background:#1a1a2e; padding:9px 5px; color:#00d4ff; white-space:nowrap; cursor:pointer; user-select:none; font-size:0.9em; }
    th:hover { background:#1e1e38; }
    td { padding:5px; border-bottom:1px solid #222; white-space:nowrap; }
    .sort-ind { font-size:0.8em; margin-left:3px; }
    .btn-xs { border:none; padding:3px 6px; border-radius:4px; cursor:pointer; font-size:0.72em; }
    .edit-btn { background:#ffa500; color:#000; }
    .delete-btn { background:#ff4757; color:#fff; }
    .save-btn { background:#00ff88; color:#000; }
    .trade-btn-row { background:#7b2ff7; color:#fff; font-weight:bold; min-width:40px; }
    .badge { padding:2px 6px; border-radius:10px; font-size:0.72em; margin-left:4px; }
    .badge-edit { background:#ffa500; color:#000; }
    .badge-trade { background:#cc00cc; color:#fff; }
    .badge-break { background:#00ff88; color:#000; font-weight:bold; animation:bp 1s infinite; }
    .badge-break-low { background:#ff4757; color:#fff; font-weight:bold; animation:bp 1s infinite; }
    @keyframes bp { 0%,100% { opacity:1; } 50% { opacity:0.6; } }
    .editable-input { background:#1a1a2e; color:#fff; border:1px solid #ffa500; padding:3px; width:62px; border-radius:4px; font-size:0.9em; }
    .sig-SB { color:#00ff88; font-weight:bold; }
    .sig-B  { color:#00cc66; font-weight:bold; }
    .sig-H  { color:#ffd700; }
    .sig-S  { color:#ff4757; }
    .sig-SS { color:#ff0000; font-weight:bold; }
    .ltp-alert-row { animation:ltpBlink 0.6s infinite; }
    @keyframes ltpBlink { 0%,100% { background:#ff475730; } 50% { background:#ff475760; } }
    .ltp-above { color:#00ff88 !important; font-weight:bold; }
    .ltp-below { color:#ff4757 !important; font-weight:bold; }
    .row-break-high { background:linear-gradient(90deg,#00ff8818,#0a0a0f) !important; border-left:4px solid #00ff88 !important; }
    .row-break-low  { background:linear-gradient(90deg,#ff475718,#0a0a0f) !important; border-left:4px solid #ff4757 !important; }
    .rrr-high { color:#00ff88; font-weight:bold; }
    .rrr-mid  { color:#ffd700; }
    .rrr-low  { color:#ff4757; }
    .modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:1000; justify-content:center; align-items:center; overflow-y:auto; }
    .modal.open { display:flex; }
    .modal-box { background:#1a1a2e; padding:22px; border-radius:15px; max-width:520px; width:92%; border:2px solid #ffa500; max-height:92vh; overflow-y:auto; }
    .modal-box.trade { border-color:#00cc66; }
    .modal-box h3 { color:#ffa500; margin-bottom:12px; }
    .modal-box.trade h3 { color:#00cc66; }
    .modal-box label { display:block; margin-top:8px; font-size:0.9em; color:#aaf; }
    .modal-box select, .modal-box input { width:100%; margin-bottom:6px; }
    .modal-btns { display:flex; gap:8px; margin-top:15px; }
    .modal-btns button { flex:1; }
    .trade-summary { background:#0f3460; padding:12px; border-radius:8px; margin-top:12px; font-size:0.9em; }
    .trade-summary span { display:block; margin:4px 0; }
    .info-bar { background:#0f3460; padding:6px 12px; border-radius:6px; margin-bottom:6px; font-size:0.8em; }
    #sortStatus { color:#00d4ff; }
    #alertStatus { color:#ffa500; display:none; }
    #recordCount { color:#888; }
    .refresh-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#00ff88; margin-right:6px; animation:pulse 2s infinite; }
    @media (max-width:768px) { .header h1 { font-size:1.4em; } }
</style>
</head>
<body>
<div class="header">
    <h1>🤖 AI Trading Signals</h1>
    <div class="status-line" id="marketStatus">Loading DSE status...</div>
</div>
<div id="alertBox" class="alert-box">⚠️ DSE CLOSING IN 10 MINUTES!</div>

<div class="tabs">
    <div class="tab active" data-tab="ai_signals" onclick="switchTab('ai_signals', event)">🤖 AI Signals</div>
    <div class="tab" data-tab="swrsi" onclick="switchTab('swrsi', event)">🔍 SWRSI</div>
    <div class="tab" data-tab="support" onclick="switchTab('support', event)">📊 S/R</div>
    <div class="tab" data-tab="rsi" onclick="switchTab('rsi', event)">📈 RSI</div>
    <div class="tab" data-tab="buy" onclick="switchTab('buy', event)">✅ Daily Buy</div>
</div>

<div class="controls">
    <label>📅</label>
    <select id="dateSelect" onchange="loadCurrentTab()"><option value="">Latest</option></select>
    <label>🔍</label>
    <input type="text" id="symbolSearch" placeholder="Symbol" onkeyup="debounceLoad()" style="width:110px;">
    <button onclick="forceRefresh()">🔄 Refresh</button>
    <button class="btn-warn" onclick="openAlertModal()">🔔 Alerts</button>
    <button class="btn-danger" onclick="deleteAllByDate()">🗑️ Delete All</button>
    <button class="btn-success" onclick="openTradeModal()">💰 Trade</button>
    <button style="background:#555;" onclick="resetSort()">↺ Sort</button>
    <span id="recordCount"></span>
</div>

<div id="alertStatus" class="info-bar"></div>
<div id="sortStatus" class="info-bar"></div>

<div style="overflow-x:auto;" id="dynamicTable">
    <p style="color:#888;text-align:center;padding:40px;">Loading...</p>
</div>

<!-- Alert Modal -->
<div id="alertModal" class="modal">
  <div class="modal-box">
    <h3>🔔 Configure LTP Alerts</h3>
    <label>Symbol</label>
    <select id="alertSymbolSelect"><option value="">-- Loading --</option></select>
    <label>Condition</label>
    <select id="alertCondition">
        <option value="above">LTP উপরে গেলে Alert</option>
        <option value="below">LTP নিচে গেলে Alert</option>
    </select>
    <label>Threshold Price</label>
    <input type="number" id="alertThresholdPrice" step="0.01" placeholder="e.g. 100.50">
    <div class="modal-btns">
        <button class="save-btn" onclick="addAlertRule()">➕ Add</button>
        <button onclick="closeAlertModal()">Cancel</button>
    </div>
    <div id="currentAlertsSection" style="margin-top:14px;background:#0f3460;padding:10px;border-radius:8px;display:none;">
        <h4 style="color:#ffa500;">Active:</h4>
        <div id="currentAlertsList"></div>
    </div>
  </div>
</div>

<!-- Trade Modal -->
<div id="tradeModal" class="modal">
  <div class="modal-box trade">
    <h3>💰 Trade Management</h3>
    <label>Symbol</label>
    <select id="tradeSymbolSelect" onchange="onTradeSymbolChange()"><option value="">-- Loading --</option></select>
    <label>Entry Price</label>
    <input type="number" id="tradeEntryPrice" step="0.01" oninput="calcTrade()">
    <label>Stop Loss</label>
    <input type="number" id="tradeStopLoss" step="0.01" oninput="calcTrade()">
    <label>Target Price</label>
    <input type="number" id="tradeTargetPrice" step="0.01" oninput="calcTrade()">
    <label>Total Exposure (৳)</label>
    <input type="number" id="tradeTotalExposure" step="0.01" oninput="calcTrade()">
    <label>Risk %</label>
    <input type="number" id="tradeRiskPercent" step="0.01" oninput="calcTrade()">
    <div class="trade-summary" id="tradeSummary" style="display:none;">
        <span>📊 RRR: <span id="tradeRRR">-</span></span>
        <span>💸 Risk: ৳<span id="tradeRiskAmount">0</span></span>
        <span>🎯 Profit: ৳<span id="tradeProfitAmount">0</span></span>
        <span>📈 Qty: <span id="tradeQuantity">0</span></span>
    </div>
    <div class="modal-btns">
        <button class="save-btn" onclick="saveTrade()">💾 Save</button>
        <button onclick="closeTradeModal()">Cancel</button>
    </div>
  </div>
</div>

<script>
const COLLECTION_MAP = {
    ai_signals: 'daily_ai_signals',
    swrsi:      'swrsi_signals',
    support:    'support_resistance',
    rsi:        'rsi_signals',
    buy:        'daily_buy_signals'
};

let currentTab = 'ai_signals';
let currentData = [];
let dseLtpData = {};
let dseHLData = {};
let editingRow = null;
let alertRules = [];
let currentSort = { field: null, order: null };
let debounceTimer = null;
let lastMarketStatus = null;

document.addEventListener('DOMContentLoaded', () => {
    loadAlertRules();
    loadDates(COLLECTION_MAP[currentTab]);
    loadCurrentTab();
    refreshLtpAndStatus();
    checkMarketStatus();
    setInterval(refreshLtpAndStatus, 60000);
    setInterval(checkMarketStatus, 60000);
    updateSortStatus();
});

function debounceLoad() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(loadCurrentTab, 300);
}

// ============ MARKET STATUS ============
async function checkMarketStatus() {
    try {
        const r = await fetch('/api/market-status');
        const s = await r.json();
        lastMarketStatus = s;
        const el = document.getElementById('marketStatus');
        if (s.is_open) {
            el.innerHTML = `<span class="refresh-dot"></span>🟢 DSE OPEN · <b>${s.dse_time}</b>`;
        } else {
            const next = s.next_open ? ` · Opens ${s.next_open}` : '';
            el.innerHTML = `🔴 DSE CLOSED${next} · Last: <b>${s.dse_time}</b>`;
        }
        document.getElementById('alertBox').style.display = s.alert_10min ? 'block' : 'none';
    } catch (e) {
        console.error('market-status', e);
        document.getElementById('marketStatus').textContent = '⚠️ DSE status fetch failed';
    }
}

// ============ LTP + HL ============
async function refreshLtpAndStatus() {
    await loadDseLtp();
    await loadDseHL();
    renderCurrentTab();
}

async function loadDseLtp() {
    try {
        const r = await fetch('/api/dse-ltp');
        const j = await r.json();
        if (j.ltp_data && Object.keys(j.ltp_data).length > 0) {
            dseLtpData = j.ltp_data;
            console.log(`✅ LTP: ${j.total_symbols} symbols @ ${j.dse_time}`);
        } else {
            console.warn('⚠️ LTP empty:', j);
        }
    } catch (e) {
        console.error('LTP fetch failed', e);
    }
}

async function loadDseHL() {
    try {
        const syms = currentData.map(x => x.symbol).filter(Boolean).slice(0, 500);
        if (!syms.length) return;
        const r = await fetch(`/api/dse-highs?symbols=${encodeURIComponent(syms.join(','))}`);
        const j = await r.json();
        if (j && typeof j === 'object') dseHLData = j;
    } catch (e) {
        console.error('HL fetch failed', e);
    }
}

async function loadDates(col) {
    try {
        const r = await fetch(`/api/dates?collection=${col}`);
        const d = await r.json();
        const s = document.getElementById('dateSelect');
        s.innerHTML = '<option value="">Latest</option>';
        if (Array.isArray(d)) {
            d.forEach(v => {
                const o = document.createElement('option');
                o.value = v; o.textContent = v;
                s.appendChild(o);
            });
        }
    } catch (e) { console.error('dates', e); }
}

async function loadCurrentTab() {
    const date = document.getElementById('dateSelect').value;
    const symbol = document.getElementById('symbolSearch').value.trim();
    const sortParam = currentSort.field
        ? `&sort_by=${currentSort.field}&sort_order=${currentSort.order}` : '';

    let url = '';
    if (currentTab === 'ai_signals') {
        url = `/api/signals?limit=1000${sortParam}`;
        if (date) url += `&date=${date}`;
        if (symbol) url += `&symbol=${encodeURIComponent(symbol)}`;
    } else {
        const col = COLLECTION_MAP[currentTab];
        url = `/api/generic-data?collection=${col}&limit=500${sortParam}`;
        if (date) url += `&date=${date}`;
        if (symbol) url += `&symbol=${encodeURIComponent(symbol)}`;
    }

    try {
        const r = await fetch(url);
        const j = await r.json();
        if (j.error) {
            console.error('API error:', j.error);
            currentData = [];
        } else {
            currentData = j.data || [];
        }
    } catch (e) {
        console.error('load tab failed', e);
        currentData = [];
    }

    await loadDseHL();
    renderCurrentTab();
}

function forceRefresh() {
    loadCurrentTab();
    refreshLtpAndStatus();
    checkMarketStatus();
}

function renderCurrentTab() {
    if (currentTab === 'ai_signals') renderAITable();
    else renderGenericTable();
}

function switchTab(t, ev) {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    ev.target.classList.add('active');
    currentTab = t;
    document.getElementById('symbolSearch').value = '';
    loadDates(COLLECTION_MAP[t]);
    loadCurrentTab();
}

// ============ SORT ============
function updateSortStatus() {
    const s = document.getElementById('sortStatus');
    if (currentSort.field) {
        s.innerHTML = `📊 Sorted by <b>${currentSort.field}</b> (${currentSort.order.toUpperCase()}) · <span style="cursor:pointer;color:#ffa500;" onclick="resetSort()">reset</span>`;
    } else {
        s.innerHTML = '📊 Default: diff ASC, gape DESC';
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
function resetSort() { currentSort = { field: null, order: null }; updateSortStatus(); loadCurrentTab(); }
function sortIndicator(field) {
    if (currentSort.field === field) return `<span class="sort-ind">${currentSort.order === 'asc' ? '▲' : '▼'}</span>`;
    if (!currentSort.field && field === 'diff') return '<span class="sort-ind" style="color:#ffa500;">▲</span>';
    if (!currentSort.field && field === 'gape') return '<span class="sort-ind" style="color:#ffa500;">▼</span>';
    return '<span class="sort-ind" style="opacity:0.3;">⇅</span>';
}

// ============ HELPERS ============
function sigClass(s) {
    if (!s) return '';
    if (s.includes('STRONG BUY')) return 'sig-SB';
    if (s.includes('BUY')) return 'sig-B';
    if (s.includes('HOLD')) return 'sig-H';
    if (s.includes('STRONG SELL')) return 'sig-SS';
    if (s.includes('SELL')) return 'sig-S';
    return '';
}
function alertStatus(sym) {
    if (!alertRules.length) return null;
    const ltp = dseLtpData[sym];
    if (ltp == null) return null;
    for (const rule of alertRules) {
        if (rule.symbol === sym) {
            if (rule.condition === 'above' && ltp > rule.threshold) return 'above';
            if (rule.condition === 'below' && ltp < rule.threshold) return 'below';
        }
    }
    return null;
}
function resolveHigh(sym, docHigh) {
    if (docHigh && docHigh > 0) return docHigh;
    const hl = dseHLData[sym];
    return (hl && hl.high) ? hl.high : 0;
}
function resolveLow(sym, docLow) {
    if (docLow && docLow > 0) return docLow;
    const hl = dseHLData[sym];
    return (hl && hl.low) ? hl.low : 0;
}
function isAboveHigh(sym, docHigh) {
    const ltp = dseLtpData[sym]; const h = resolveHigh(sym, docHigh);
    return ltp != null && h > 0 && ltp > h;
}
function isBelowLow(sym, docLow) {
    const ltp = dseLtpData[sym]; const l = resolveLow(sym, docLow);
    return ltp != null && l > 0 && ltp < l;
}
function ltpDisplay(sym, docHigh, docLow) {
    const ltp = dseLtpData[sym];
    if (ltp == null) return '<span style="color:#666;">-</span>';
    const a = alertStatus(sym);
    const h = resolveHigh(sym, docHigh);
    const l = resolveLow(sym, docLow);
    let cls = '', arrow = '';
    if (h > 0 && ltp > h)            { cls = 'ltp-above'; arrow = ' 🚀'; }
    else if (l > 0 && ltp < l)       { cls = 'ltp-below'; arrow = ' 🔻'; }
    else if (a === 'above')          { cls = 'ltp-above'; arrow = ' ↑'; }
    else if (a === 'below')          { cls = 'ltp-below'; arrow = ' ↓'; }
    return `<span class="${cls}" style="font-weight:bold;">${ltp.toFixed(2)}${arrow}</span>`;
}
function rowClass(sym, docHigh, docLow) {
    if (isAboveHigh(sym, docHigh)) return 'row-break-high';
    if (isBelowLow(sym, docLow))   return 'row-break-low';
    const a = alertStatus(sym);
    if (a === 'above' || a === 'below') return 'ltp-alert-row';
    return '';
}
function rrrClass(r) {
    if (!r) return '';
    if (r >= 2) return 'rrr-high';
    if (r >= 1) return 'rrr-mid';
    return 'rrr-low';
}

// ============ AI TABLE ============
function renderAITable() {
    const div = document.getElementById('dynamicTable');
    if (!currentData.length) {
        div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data</p>';
        document.getElementById('recordCount').textContent = '';
        return;
    }
    let html = `<table><thead><tr>
        <th>#</th>
        <th onclick="handleSort('symbol')">Symbol${sortIndicator('symbol')}</th>
        <th>Date</th>
        <th>LTP</th>
        <th>Sector</th>
        <th onclick="handleSort('final_signal')">Signal${sortIndicator('final_signal')}</th>
        <th onclick="handleSort('final_combined_score')">Score${sortIndicator('final_combined_score')}</th>
        <th onclick="handleSort('diff')">Diff${sortIndicator('diff')}</th>
        <th onclick="handleSort('gape')">Gape${sortIndicator('gape')}</th>
        <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th>
        <th>Exposure</th><th>Risk%</th><th>Act</th>
    </tr></thead><tbody>`;

    currentData.forEach((r, i) => {
        const safeId = (r.symbol || '').replace(/[^A-Z0-9]/gi, '_');
        const isEditing = editingRow && editingRow.symbol === r.symbol && editingRow.date === r.analysis_date;
        const isEdited = r.edited === true;
        const hasTrade = r.entry_price || r.stop_loss || r.target_price || r.total_exposure || r.risk_percent;
        const docHigh = r.high || r.current_high || 0;
        const docLow  = r.low  || r.current_low  || 0;
        const aStat = alertStatus(r.symbol);
        const brkHigh = isAboveHigh(r.symbol, docHigh);
        const brkLow  = isBelowLow(r.symbol, docLow);
        const rrr = r.risk_reward_ratio || 0;

        const entryCell = isEditing
            ? `<input class="editable-input" id="ee-${safeId}" value="${(r.entry_price||0).toFixed(2)}">`
            : (r.entry_price ? `<span style="color:#00ff88;">${r.entry_price.toFixed(2)}</span>` : '-');
        const slCell = isEditing
            ? `<input class="editable-input" id="es-${safeId}" value="${(r.stop_loss||0).toFixed(2)}">`
            : (r.stop_loss ? `<span style="color:#ff4757;">${r.stop_loss.toFixed(2)}</span>` : '-');
        const tpCell = isEditing
            ? `<input class="editable-input" id="et-${safeId}" value="${(r.target_price||0).toFixed(2)}">`
            : (r.target_price ? `<span style="color:#00d4ff;">${r.target_price.toFixed(2)}</span>` : '-');
        const actionCell = isEditing
            ? `<button class="btn-xs save-btn" onclick="saveEdit('${r.symbol}','${r.analysis_date}')">💾</button>
               <button class="btn-xs delete-btn" onclick="cancelEdit()">❌</button>`
            : `<button class="btn-xs edit-btn" onclick="startEdit('${r.symbol}','${r.analysis_date}')">✏️</button>
               <button class="btn-xs trade-btn-row" onclick="openTradeForSymbol('${r.symbol}')">💰</button>
               <button class="btn-xs delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}')">🗑️</button>`;

        const brkHighBadge = brkHigh ? '<span class="badge badge-break">🚀HIGH</span>' : '';
        const brkLowBadge  = brkLow  ? '<span class="badge badge-break-low">🔻LOW</span>' : '';

        html += `<tr class="${rowClass(r.symbol, docHigh, docLow)}">
            <td>${i+1}</td>
            <td><b>${r.symbol}</b>
                ${isEdited ? '<span class="badge badge-edit">✏️</span>' : ''}
                ${hasTrade ? '<span class="badge badge-trade">💰</span>' : ''}
                ${aStat ? ' 🔔' : ''}${brkHighBadge}${brkLowBadge}
            </td>
            <td>${r.analysis_date || ''}</td>
            <td>${ltpDisplay(r.symbol, docHigh, docLow)}</td>
            <td>${r.sector || 'Other'}</td>
            <td class="${sigClass(r.final_signal)}">${r.final_signal || ''}</td>
            <td><b>${(r.final_combined_score || 0).toFixed(1)}</b></td>
            <td style="color:#ffd700;font-weight:bold;">${r.diff != null ? (r.diff > 0 ? '+' : '') + Number(r.diff).toFixed(2) : '-'}</td>
            <td style="color:#00d4ff;font-weight:bold;">${r.gape != null ? Number(r.gape).toFixed(2) : '-'}</td>
            <td>${entryCell}</td><td>${slCell}</td><td>${tpCell}</td>
            <td class="${rrrClass(rrr)}"><b>${rrr.toFixed(2)}</b></td>
            <td>${r.total_exposure ? '৳' + r.total_exposure.toLocaleString() : '-'}</td>
            <td>${r.risk_percent ? r.risk_percent.toFixed(1) + '%' : '-'}</td>
            <td>${actionCell}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    div.innerHTML = html;
    document.getElementById('recordCount').textContent = `(${currentData.length})`;
}

// ============ GENERIC TABLE ============
function renderGenericTable() {
    const div = document.getElementById('dynamicTable');
    if (!currentData.length) {
        div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data</p>';
        document.getElementById('recordCount').textContent = '';
        return;
    }
    const exclude = ['_id','saved_at','analysis_date','date','symbol',
                     'entry_price','stop_loss','target_price','risk_reward_ratio',
                     'total_exposure','risk_percent','edited','edited_at','high','low','current_high','current_low'];
    const keys = Object.keys(currentData[0]).filter(k => !exclude.includes(k) && !k.startsWith('_'));

    let html = `<table><thead><tr>
        <th>#</th>
        <th onclick="handleSort('symbol')">Symbol${sortIndicator('symbol')}</th>
        <th>LTP</th>
        <th>Sector</th>
        ${keys.map(k => (k === 'diff' || k === 'gape')
            ? `<th onclick="handleSort('${k}')">${k}${sortIndicator(k)}</th>`
            : `<th>${k}</th>`).join('')}
        <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th>
        <th>Exposure</th><th>Risk%</th><th>Act</th>
    </tr></thead><tbody>`;

    currentData.forEach((r, i) => {
        const docHigh = r.high || r.current_high || 0;
        const docLow  = r.low  || r.current_low  || 0;
        const aStat = alertStatus(r.symbol);
        const brkHigh = isAboveHigh(r.symbol, docHigh);
        const brkLow  = isBelowLow(r.symbol, docLow);
        const hasTrade = r.entry_price || r.stop_loss || r.target_price;
        const rrr = r.risk_reward_ratio || 0;
        const recordDate = r.analysis_date || r.date || '';

        const brkHighBadge = brkHigh ? '<span class="badge badge-break">🚀HIGH</span>' : '';
        const brkLowBadge  = brkLow  ? '<span class="badge badge-break-low">🔻LOW</span>' : '';

        html += `<tr class="${rowClass(r.symbol, docHigh, docLow)}">
            <td>${i+1}</td>
            <td><b>${r.symbol || ''}</b>
                ${hasTrade ? '<span class="badge badge-trade">💰</span>' : ''}
                ${aStat ? ' 🔔' : ''}${brkHighBadge}${brkLowBadge}
            </td>
            <td>${ltpDisplay(r.symbol, docHigh, docLow)}</td>
            <td>${r.sector || 'Other'}</td>
            ${keys.map(k => {
                if (k === 'diff') return `<td style="color:#ffd700;font-weight:bold;">${r[k] != null ? (r[k] > 0 ? '+' : '') + Number(r[k]).toFixed(2) : '-'}</td>`;
                if (k === 'gape') return `<td style="color:#00d4ff;font-weight:bold;">${r[k] != null ? Number(r[k]).toFixed(2) : '-'}</td>`;
                return `<td>${r[k] ?? ''}</td>`;
            }).join('')}
            <td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>
            <td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>
            <td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>
            <td class="${rrrClass(rrr)}"><b>${rrr.toFixed(2)}</b></td>
            <td>${r.total_exposure ? '৳' + r.total_exposure.toLocaleString() : '-'}</td>
            <td>${r.risk_percent ? r.risk_percent.toFixed(1) + '%' : '-'}</td>
            <td>
                <button class="btn-xs trade-btn-row" onclick="openTradeForSymbol('${r.symbol}')">💰</button>
                <button class="btn-xs delete-btn" onclick="deleteRecord('${r.symbol || ''}','${recordDate}')">🗑️</button>
            </td>
        </tr>`;
    });

    html += '</tbody></table>';
    div.innerHTML = html;
    document.getElementById('recordCount').textContent = `(${currentData.length})`;
}

// ============ EDIT ============
function startEdit(symbol, date) { editingRow = { symbol, date }; renderCurrentTab(); }
function cancelEdit() { editingRow = null; renderCurrentTab(); }
async function saveEdit(symbol, date) {
    const safeId = symbol.replace(/[^A-Z0-9]/gi, '_');
    const entry = parseFloat(document.getElementById(`ee-${safeId}`).value) || 0;
    const sl = parseFloat(document.getElementById(`es-${safeId}`).value) || 0;
    const tp = parseFloat(document.getElementById(`et-${safeId}`).value) || 0;
    const p = new URLSearchParams({
        collection: COLLECTION_MAP[currentTab], symbol, date,
        entry_price: entry, stop_loss: sl, target_price: tp
    });
    await fetch(`/api/update-trade?${p}`, { method: 'PUT' });
    editingRow = null;
    loadCurrentTab();
}

// ============ TRADE MODAL ============
function openTradeModal() {
    document.getElementById('tradeModal').classList.add('open');
    loadTradeSymbols();
}
function closeTradeModal() { document.getElementById('tradeModal').classList.remove('open'); }

async function loadTradeSymbols() {
    const date = document.getElementById('dateSelect').value;
    const col = COLLECTION_MAP[currentTab];
    const sel = document.getElementById('tradeSymbolSelect');
    sel.innerHTML = '<option value="">Loading...</option>';
    try {
        let url = `/api/collection-symbols?collection=${col}`;
        if (date) url += `&date=${date}`;
        const symbols = await (await fetch(url)).json();
        sel.innerHTML = '<option value="">-- Select --</option>';
        symbols.forEach(s => {
            const o = document.createElement('option');
            o.value = s; o.textContent = s;
            sel.appendChild(o);
        });
    } catch (e) { sel.innerHTML = '<option value="">Error</option>'; }
}

function onTradeSymbolChange() {
    const sym = document.getElementById('tradeSymbolSelect').value;
    if (!sym) return;
    const rec = currentData.find(r => r.symbol === sym);
    if (rec) {
        document.getElementById('tradeEntryPrice').value = rec.entry_price || '';
        document.getElementById('tradeStopLoss').value = rec.stop_loss || '';
        document.getElementById('tradeTargetPrice').value = rec.target_price || '';
        document.getElementById('tradeTotalExposure').value = rec.total_exposure || '';
        document.getElementById('tradeRiskPercent').value = rec.risk_percent || '';
    }
    calcTrade();
}

function calcTrade() {
    const entry = parseFloat(document.getElementById('tradeEntryPrice').value) || 0;
    const sl = parseFloat(document.getElementById('tradeStopLoss').value) || 0;
    const tp = parseFloat(document.getElementById('tradeTargetPrice').value) || 0;
    const exp = parseFloat(document.getElementById('tradeTotalExposure').value) || 0;
    const rp = parseFloat(document.getElementById('tradeRiskPercent').value) || 0;
    const box = document.getElementById('tradeSummary');
    if (entry > 0 && sl > 0 && tp > 0) {
        box.style.display = 'block';
        const risk = Math.abs(entry - sl);
        const reward = Math.abs(tp - entry);
        const rrr = risk > 0 ? (reward / risk).toFixed(2) : '0';
        document.getElementById('tradeRRR').textContent = rrr;
        document.getElementById('tradeRRR').className = rrrClass(parseFloat(rrr));
        if (exp > 0 && rp > 0) {
            const riskAmt = exp * rp / 100;
            const qty = risk > 0 ? Math.floor(riskAmt / risk) : 0;
            document.getElementById('tradeRiskAmount').textContent = riskAmt.toFixed(2);
            document.getElementById('tradeProfitAmount').textContent = (qty * reward).toFixed(2);
            document.getElementById('tradeQuantity').textContent = qty;
        }
    } else {
        box.style.display = 'none';
    }
}

async function saveTrade() {
    const symbol = document.getElementById('tradeSymbolSelect').value;
    if (!symbol) { alert('Select a symbol'); return; }
    const rec = currentData.find(r => r.symbol === symbol);
    const date = rec ? (rec.analysis_date || rec.date || '') : '';
    if (!date) { alert('Date not found'); return; }

    const p = new URLSearchParams({
        collection: COLLECTION_MAP[currentTab], symbol, date
    });
    const fields = [
        ['entry_price', 'tradeEntryPrice'],
        ['stop_loss', 'tradeStopLoss'],
        ['target_price', 'tradeTargetPrice'],
        ['total_exposure', 'tradeTotalExposure'],
        ['risk_percent', 'tradeRiskPercent']
    ];
    fields.forEach(([param, id]) => {
        const v = parseFloat(document.getElementById(id).value);
        if (!isNaN(v)) p.append(param, v);
    });

    const r = await fetch(`/api/update-trade?${p}`, { method: 'PUT' });
    const res = await r.json();
    alert(`Saved: ${res.updated} updated, ${res.matched} matched`);
    closeTradeModal();
    loadCurrentTab();
}

async function openTradeForSymbol(sym) {
    await loadTradeSymbols();
    document.getElementById('tradeSymbolSelect').value = sym;
    onTradeSymbolChange();
    openTradeModal();
}

// ============ ALERT MODAL ============
function loadAlertRules() {
    try {
        alertRules = JSON.parse(localStorage.getItem('ltpAlertRules_v25') || '[]');
    } catch (e) { alertRules = []; }
    updateAlertBar();
}
function saveAlertRules() {
    localStorage.setItem('ltpAlertRules_v25', JSON.stringify(alertRules));
    updateAlertBar();
    renderCurrentTab();
}
function updateAlertBar() {
    const bar = document.getElementById('alertStatus');
    if (alertRules.length) {
        bar.style.display = 'block';
        bar.innerHTML = '🔔 <b>' + alertRules.length + ' alert(s):</b> ' +
            alertRules.map(r => `${r.symbol} ${r.condition === 'above' ? '↑>' : '↓<'} ${r.threshold}`).join(' · ');
    } else {
        bar.style.display = 'none';
    }
}
function openAlertModal() {
    document.getElementById('alertModal').classList.add('open');
    loadAlertSymbols();
    renderCurrentAlerts();
}
function closeAlertModal() { document.getElementById('alertModal').classList.remove('open'); }
async function loadAlertSymbols() {
    const date = document.getElementById('dateSelect').value;
    const col = COLLECTION_MAP[currentTab];
    const sel = document.getElementById('alertSymbolSelect');
    sel.innerHTML = '<option value="">Loading...</option>';
    try {
        let url = `/api/collection-symbols?collection=${col}`;
        if (date) url += `&date=${date}`;
        const symbols = await (await fetch(url)).json();
        sel.innerHTML = '<option value="">-- Select --</option>';
        symbols.forEach(s => {
            const o = document.createElement('option');
            o.value = s; o.textContent = s;
            sel.appendChild(o);
        });
    } catch (e) { sel.innerHTML = '<option value="">Error</option>'; }
}
function renderCurrentAlerts() {
    const sec = document.getElementById('currentAlertsSection');
    const list = document.getElementById('currentAlertsList');
    if (!alertRules.length) { sec.style.display = 'none'; return; }
    sec.style.display = 'block';
    list.innerHTML = alertRules.map((r, i) =>
        `<div style="display:flex;justify-content:space-between;background:#1a1a2e;padding:6px;margin:4px 0;border-radius:5px;">
            <span>🔔 ${r.symbol} ${r.condition === 'above' ? '↑>' : '↓<'} ${r.threshold}</span>
            <button onclick="removeAlertRule(${i})" style="background:#ff4757;padding:3px 8px;border:none;color:#fff;border-radius:4px;">✕</button>
        </div>`
    ).join('');
}
function addAlertRule() {
    const sym = document.getElementById('alertSymbolSelect').value;
    const cond = document.getElementById('alertCondition').value;
    const thr = parseFloat(document.getElementById('alertThresholdPrice').value);
    if (!sym || !thr) { alert('Select symbol & enter price'); return; }
    alertRules = alertRules.filter(r => r.symbol !== sym);
    alertRules.push({ symbol: sym, condition: cond, threshold: thr });
    saveAlertRules();
    document.getElementById('alertSymbolSelect').value = '';
    document.getElementById('alertThresholdPrice').value = '';
}
function removeAlertRule(i) {
    alertRules.splice(i, 1);
    saveAlertRules();
}

// ============ DELETE ============
async function deleteRecord(symbol, date) {
    if (!confirm(`Delete ${symbol} (${date})?`)) return;
    await fetch(`/api/delete-signal?collection=${COLLECTION_MAP[currentTab]}&symbol=${symbol}&date=${date}`, { method: 'DELETE' });
    loadCurrentTab();
}
async function deleteAllByDate() {
    const date = document.getElementById('dateSelect').value;
    if (!date) { alert('Select a date first'); return; }
    if (!confirm(`DELETE ALL records for ${date}?`)) return;
    const r = await fetch(`/api/delete-all-by-date?collection=${COLLECTION_MAP[currentTab]}&date=${date}`, { method: 'DELETE' });
    const res = await r.json();
    alert(`Deleted ${res.deleted} records`);
    loadDates(COLLECTION_MAP[currentTab]);
    loadCurrentTab();
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
    print(f"🚀 Dashboard starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
