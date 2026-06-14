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
✅ LTP Data Available Even When Market Closed
✅ LTP Parser Matches Exact DSE Table Structure (td index 2, class shares-table)
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
# DSE WEBSITE MARKET STATUS - FIXED VERSION
# ================================
def is_dse_market_open():
    """
    DSE ওয়েবসাইট থেকে মার্কেট স্ট্যাটাস চেক - একাধিক মেথড সহ
    Method 1: DSE হোমপেজ থেকে Market Status টেক্সট স্ক্র্যাপ
    Method 2: LTP AJAX API-তে ডাটা চেক
    Method 3: DSE মোবাইল API চেক  
    Method 4: ট্রেডিং ডাটা আছে কিনা চেক
    Method 5: টাইম-বেসড ফলব্যাক
    """
    
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        })

        # Method 1: DSE হোমপেজ স্ক্র্যাপিং
        try:
            response = session.get('https://www.dsebd.org/', timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # সমস্ত টেক্সট এলিমেন্ট চেক করুন
                all_text_elements = soup.find_all(string=True)
                full_page_text = ' '.join([text.strip() for text in all_text_elements if text.strip()])
                
                # Market Status খুঁজুন - বিভিন্ন ফরম্যাটে
                if re.search(r'Market\s+Status\s*:\s*Open', full_page_text, re.IGNORECASE):
                    print("[DSE] ✅ MARKET OPEN (Homepage Status)")
                    return True
                if re.search(r'Market\s+Status\s*:\s*Closed', full_page_text, re.IGNORECASE):
                    print("[DSE] ❌ MARKET CLOSED (Homepage Status)")
                    return False
                if re.search(r'Market\s+is\s+Open', full_page_text, re.IGNORECASE):
                    print("[DSE] ✅ MARKET OPEN (Homepage)")
                    return True
                if re.search(r'Market\s+is\s+Closed', full_page_text, re.IGNORECASE):
                    print("[DSE] ❌ MARKET CLOSED (Homepage)")
                    return False
                    
                # নির্দিষ্ট এলিমেন্টে খুঁজুন
                for tag in ['div', 'span', 'strong', 'b', 'h1', 'h2', 'h3', 'h4', 'p']:
                    elements = soup.find_all(tag)
                    for element in elements:
                        text = element.get_text().strip()
                        if re.search(r'Market\s+Status\s*:\s*Open', text, re.IGNORECASE):
                            print(f"[DSE] ✅ MARKET OPEN (Tag: {tag})")
                            return True
                        if re.search(r'Market\s+Status\s*:\s*Closed', text, re.IGNORECASE):
                            print(f"[DSE] ❌ MARKET CLOSED (Tag: {tag})")
                            return False
                
                # CSS ক্লাস দিয়ে খুঁজুন
                status_elements = soup.find_all(class_=re.compile(r'market|status|trading', re.IGNORECASE))
                for element in status_elements:
                    text = element.get_text().strip().upper()
                    if 'OPEN' in text and ('MARKET' in text or 'TRADING' in text):
                        print(f"[DSE] ✅ MARKET OPEN (CSS Class)")
                        return True
                    if 'CLOSED' in text and ('MARKET' in text or 'TRADING' in text):
                        print(f"[DSE] ❌ MARKET CLOSED (CSS Class)")
                        return False
                        
        except Exception as e:
            print(f"[DSE] Method 1 failed: {e}")

        # Method 2: LTP AJAX API চেক - সবচেয়ে নির্ভরযোগ্য
        try:
            ajax_response = session.get(
                'https://www.dsebd.org/latest_share_price_scroll_l.php',
                headers={
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': 'https://www.dsebd.org/'
                },
                timeout=15
            )
            
            if ajax_response.status_code == 200:
                soup = BeautifulSoup(ajax_response.text, 'html.parser')
                
                # টেবিল খুঁজুন
                tables = soup.find_all('table')
                
                for table in tables:
                    rows = table.find_all('tr')
                    
                    # ডাটা row গুনুন (যে row-এ td আছে)
                    data_rows = []
                    for row in rows:
                        tds = row.find_all('td')
                        if tds and len(tds) >= 3:  # অন্তত ৩টি কলাম থাকতে হবে
                            # LTP ডাটা ভ্যালিডেশন
                            try:
                                # দ্বিতীয় কলামে সাধারণত সিম্বল থাকে
                                symbol_text = tds[1].get_text(strip=True) if len(tds) > 1 else ''
                                # তৃতীয় কলামে LTP থাকে
                                ltp_text = tds[2].get_text(strip=True).replace(',', '') if len(tds) > 2 else ''
                                
                                if symbol_text and ltp_text:
                                    ltp_value = float(ltp_text)
                                    if ltp_value > 0:  # ভ্যালিড LTP
                                        data_rows.append(row)
                            except:
                                continue
                    
                    if len(data_rows) > 10:  # অন্তত ১০টি স্টকের ডাটা থাকলে মার্কেট ওপেন
                        print(f"[DSE] ✅ MARKET OPEN (LTP Data: {len(data_rows)} stocks)")
                        return True
                    elif len(data_rows) > 0:
                        print(f"[DSE] ⚠️ Limited LTP Data: {len(data_rows)} stocks")
                        # অল্প ডাটা থাকলেও মার্কেট ওপেন ধরা হবে
                        return True
                
                # টেবিলে ডাটা নেই
                print(f"[DSE] ❌ MARKET CLOSED (No LTP Data)")
                return False
                
        except Exception as e:
            print(f"[DSE] Method 2 failed: {e}")

        # Method 3: DSE মোবাইল API চেক
        try:
            mobile_response = session.get(
                'https://www.dsebd.org/mobile.php',
                timeout=10
            )
            
            if mobile_response.status_code == 200:
                # মোবাইল ভার্সনে ট্রেডিং ডাটা চেক
                if '<table' in mobile_response.text and '<td' in mobile_response.text:
                    soup = BeautifulSoup(mobile_response.text, 'html.parser')
                    tables = soup.find_all('table')
                    for table in tables:
                        rows = table.find_all('tr')
                        if len(rows) > 5:  # হেডার + কিছু ডাটা
                            print(f"[DSE] ✅ MARKET OPEN (Mobile API: {len(rows)} rows)")
                            return True
        except Exception as e:
            print(f"[DSE] Method 3 failed: {e}")

        # Method 4: DSE-এর অন্য পেজ চেক
        try:
            market_summary = session.get(
                'https://www.dsebd.org/market_summary.php',
                timeout=10
            )
            
            if market_summary.status_code == 200:
                soup = BeautifulSoup(market_summary.text, 'html.parser')
                
                # ট্রেড ভলিউম বা টার্নওভার চেক
                all_text = soup.get_text()
                
                # আজকের ডেট চেক
                today = get_bd_time().strftime('%Y-%m-%d')
                
                if 'Turnover' in all_text or 'Volume' in all_text:
                    # ট্রেডিং এক্টিভিটি আছে
                    numbers = re.findall(r'[\d,]+\.?\d*', all_text)
                    for num in numbers:
                        try:
                            value = float(num.replace(',', ''))
                            if value > 0:  # পজিটিভ টার্নওভার
                                print(f"[DSE] ✅ MARKET OPEN (Market Summary: Turnover found)")
                                return True
                        except:
                            continue
        except Exception as e:
            print(f"[DSE] Method 4 failed: {e}")

        # Method 5: টাইম-বেসড ফলব্যাক
        print("[DSE] ⚠️ All scraping methods failed, using time-based fallback")
        return _is_dse_market_open_by_time()

    except Exception as e:
        print(f"[DSE] ❌ All market check methods failed: {e}")
        return _is_dse_market_open_by_time()

def _is_dse_market_open_by_time():
    """ফলব্যাক: সময় এবং দিন অনুযায়ী মার্কেট স্ট্যাটাস"""
    now = get_bd_time()
    hour, minute, weekday = now.hour, now.minute, now.weekday()
    
    # সাপ্তাহিক ছুটি (শুক্রবার = 4, শনিবার = 5)
    if weekday in [4, 5]:
        print(f"[DSE] ❌ MARKET CLOSED (Weekend: day {weekday})")
        return False
    
    # ট্রেডিং আওয়ার (রবি-বৃহস্পতি, সকাল ১০:০০ - দুপুর ২:২০)
    if weekday in [6, 0, 1, 2, 3]:
        current_time = hour * 60 + minute
        market_open_time = 10 * 60  # 10:00 AM
        market_close_time = 14 * 60 + 20  # 2:20 PM
        
        if market_open_time <= current_time <= market_close_time:
            print(f"[DSE] ✅ MARKET OPEN (Time: {hour:02d}:{minute:02d})")
            return True
        else:
            print(f"[DSE] ❌ MARKET CLOSED (Time: {hour:02d}:{minute:02d}, outside trading hours)")
            return False
    
    print(f"[DSE] ❌ MARKET CLOSED (Unknown day: {weekday})")
    return False

# ================================
# API Routes
# ================================
@app.api_route("/head", methods=["GET", "HEAD"])
async def uptime_robot_head():
    return Response(content="OK", status_code=200, headers={"Cache-Control": "no-cache", "X-Health-Status": "healthy"})


@app.get('/sw.js')
async def service_worker():
    return FileResponse('static/sw.js', media_type='application/javascript')

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
        if weekday == 4:  # Friday
            next_open = "Sunday 10:00 AM"
        elif weekday == 5:  # Saturday
            next_open = "Sunday 10:00 AM"
        elif weekday in [0, 1, 2, 3]:  # Mon-Thu
            next_open = "Tomorrow 10:00 AM"
        else:  # Sunday
            next_open = "Tomorrow 10:00 AM"
    else:
        next_open = None

    return {
        "is_open": is_open,
        "alert_10min": alert_10min,
        "alert_message": "⚠️ DSE CLOSING IN 10 MINUTES!" if alert_10min else "",
        "next_open": next_open,
        "bangladesh_time": now.strftime('%Y-%m-%d %H:%M:%S'),
        "source": "dse_website"
    }


# LTP Cache
ltp_cache = {"data": {}, "timestamp": None}

def parse_dse_table(html_text):
    """
    DSE টেবিল থেকে LTP বের করার সঠিক পদ্ধতি:
    
    টেবিল স্ট্রাকচার:
    table > tbody > tr
        td[0] = # (সিরিয়াল)
        td[1] = TRADING CODE (<a> ট্যাগে symbol)
        td[2] = LTP*
        td[3] = HIGH
        td[4] = LOW
        ...
    
    কিন্তু আপনি বলেছেন LTP td[3] তে আছে!
    তার মানে:
        td[0] = #
        td[1] = TRADING CODE (symbol)
        td[2] = LTP*
        td[3] = HIGH
        td[4] = LOW
        ...
    
    LTP: td[2] (3rd td, 0-based index 2)
    Symbol: td[1] (2nd td, 0-based index 1)
    """
    
    soup = BeautifulSoup(html_text, 'html.parser')
    ltp_data = {}
    
    # সরাসরি tbody খুঁজে বের করি
    tbodies = soup.find_all('tbody')
    
    for tbody in tbodies:
        rows = tbody.find_all('tr')
        
        for row in rows:
            cells = row.find_all('td')
            
            # Header row skip
            if len(cells) < 3:
                continue
            
            # 🔑 SYMBOL: td[1] থেকে <a> ট্যাগ
            symbol = None
            try:
                a_tag = cells[1].find('a')
                if a_tag:
                    symbol = a_tag.get_text(strip=True)
                else:
                    symbol = cells[1].get_text(strip=True)
            except:
                continue
            
            if not symbol or len(symbol) < 2:
                continue
            
            # 🔑 LTP: td[2] থেকে (3rd td)
            ltp = None
            try:
                ltp_text = cells[2].get_text(strip=True)
                ltp_text = ltp_text.replace(',', '')
                ltp = float(ltp_text)
                
                if ltp <= 0 or ltp > 50000:
                    ltp = None
            except:
                pass
            
            if symbol and ltp:
                ltp_data[symbol.upper().strip()] = ltp
        
        if len(ltp_data) > 10:
            break
    
    print(f"📊 LTP Data Found: {len(ltp_data)} symbols")
    if len(ltp_data) > 0:
        # প্রথম 3টা দেখাই ডিবাগের জন্য
        sample = list(ltp_data.items())[:3]
        print(f"📊 Sample: {sample}")
    
    return ltp_data

@app.get("/api/dse-ltp")
async def get_dse_ltp():
    """DSE থেকে LTP ডাটা ফেচ করুন - মার্কেট বন্ধ থাকলেও ডাটা ফেচ করবে"""

    market_is_open = is_dse_market_open()
    
    # ক্যাশ চেক
    if ltp_cache["timestamp"]:
        age = (get_bd_time() - ltp_cache["timestamp"]).total_seconds()
        if market_is_open:
            if age < 120 and ltp_cache["data"]:
                return ltp_cache["data"]
        else:
            if age < 300 and ltp_cache["data"]:
                return ltp_cache["data"]

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://www.dsebd.org/',
    })

    ltp_data = {}
    data_fetched = False

    # Method 1: সরাসরি dseX_share.php থেকে ডাটা ফেচ
    try:
        print("[LTP] Fetching from dseX_share.php...")
        resp = session.get('https://dsebd.org/dseX_share.php', timeout=15)
        if resp.status_code == 200:
            ltp_data = parse_dse_table(resp.text)
            if ltp_data:
                data_fetched = True
                print(f"[LTP] ✅ dseX_share.php: Found {len(ltp_data)} symbols")
    except Exception as e:
        print(f"[LTP] dseX_share.php failed: {e}")

    # Method 2: latest_share_price_scroll_l.php (AJAX, multiple pages)
    if not data_fetched:
        for page in range(1, 6):
            try:
                resp = session.get(
                    f'https://www.dsebd.org/latest_share_price_scroll_l.php?page={page}',
                    headers={'X-Requested-With': 'XMLHttpRequest'},
                    timeout=10
                )
                if resp.status_code == 200:
                    page_data = parse_dse_table(resp.text)
                    if page_data:
                        ltp_data.update(page_data)
                        data_fetched = True
                    else:
                        break
            except Exception as e:
                print(f"[LTP] AJAX page {page} failed: {e}")
                break
        
        if data_fetched:
            print(f"[LTP] ✅ AJAX API: Found {len(ltp_data)} symbols")

    # Method 3: latest_share_price_scroll_by_ltp.php
    if not data_fetched:
        try:
            resp = session.get('https://www.dsebd.org/latest_share_price_scroll_by_ltp.php', timeout=15)
            if resp.status_code == 200:
                ltp_data = parse_dse_table(resp.text)
                if ltp_data:
                    data_fetched = True
                    print(f"[LTP] ✅ LTP page: Found {len(ltp_data)} symbols")
        except Exception as e:
            print(f"[LTP] LTP page failed: {e}")

    # Method 4: Mobile API
    if not data_fetched:
        try:
            resp = session.get('https://www.dsebd.org/mobile.php', timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for table in soup.find_all('table'):
                    for row in table.find_all('tr'):
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            try:
                                sym = cols[0].get_text(strip=True)
                                ltp_val = float(cols[1].get_text(strip=True).replace(',', ''))
                                if ltp_val > 0:
                                    ltp_data[sym.upper()] = ltp_val
                                    data_fetched = True
                            except:
                                continue
                if data_fetched:
                    print(f"[LTP] ✅ Mobile API: Found {len(ltp_data)} symbols")
        except Exception as e:
            print(f"[LTP] Mobile API failed: {e}")

    # Return data or fallback
    if data_fetched:
        status = "live" if market_is_open else "closed_with_data"
        result = {
            "status": status,
            "total_symbols": len(ltp_data),
            "ltp_data": ltp_data,
            "source": "dse_combined"
        }
        ltp_cache["data"] = result
        ltp_cache["timestamp"] = get_bd_time()
        return result

    # Fallback to cache
    if ltp_cache["data"]:
        print(f"[LTP] ⚠️ Using cached data from {ltp_cache['timestamp']}")
        cached = ltp_cache["data"].copy()
        cached["status"] = "cached"
        cached["source"] = "cache"
        return cached

    print(f"[LTP] ❌ No data available. Market status: {'Open' if market_is_open else 'Closed'}")
    return {
        "status": "error",
        "message": "DSE থেকে LTP ডাটা পাওয়া যায়নি",
        "ltp_data": {},
        "source": "none"
    }

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

    try:
        for d in col.distinct('analysis_date'):
            if d:
                if isinstance(d, datetime): dates_set.add(d.strftime('%Y-%m-%d'))
                elif isinstance(d, str) and re.match(r'\d{4}-\d{2}-\d{2}', d.strip()): dates_set.add(d.strip())
    except: pass

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

    # Default sorting
    sort_criteria = []
    if sort_by:
        sort_dir = -1 if sort_order == "desc" else 1
        sort_criteria.append((sort_by, sort_dir))
    else:
        # Default: diff ASC (low to high), gape DESC (high to low)
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

    # Default sorting
    sort_criteria = []
    if sort_by:
        sort_dir = -1 if sort_order == "desc" else 1
        sort_criteria.append((sort_by, sort_dir))
    else:
        # Default: diff ASC, gape DESC
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

    # Default sorting
    sort_criteria = []
    if sort_by:
        sort_dir = -1 if sort_order == "desc" else 1
        sort_criteria.append((sort_by, sort_dir))
    else:
        # Default: diff ASC, gape DESC
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

    update_fields = {
        'edited': True, 
        'edited_at': datetime.now().isoformat()
    }

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
        <button id="installBtn" onclick="installApp()" 
            style="display:none; background:#00d4ff; color:#000; border:none; padding:10px 20px; border-radius:8px; cursor:pointer; font-weight:bold; margin-top:10px;">
                📲 Install App
        </button>
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
    
    <!-- Alert Modal -->
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
    
    <!-- Trade Management Modal -->
    <div id="tradeModal" class="modal">
        <div class="modal-content trade-modal-content">
            <h3>💰 Trade Management</h3>
            <label>📋 Select Symbol:</label>
            <select id="tradeSymbolSelect" onchange="onTradeSymbolChange()"><option value="">-- Loading... --</option></select>
            <label>📊 Entry Price:</label>
            <input type="number" id="tradeEntryPrice" placeholder="Enter entry price..." step="0.01" oninput="calculateTradeStats()">
            <label>🛑 Stop Loss:</label>
            <input type="number" id="tradeStopLoss" placeholder="Enter stop loss..." step="0.01" oninput="calculateTradeStats()">
            <label>🎯 Target Price:</label>
            <input type="number" id="tradeTargetPrice" placeholder="Enter target price..." step="0.01" oninput="calculateTradeStats()">
            <label>💵 Total Exposure (Taka):</label>
            <input type="number" id="tradeTotalExposure" placeholder="Total capital in Taka..." step="0.01" oninput="calculateTradeStats()">
            <label>⚠️ Risk %:</label>
            <input type="number" id="tradeRiskPercent" placeholder="Risk percentage (e.g., 2)..." step="0.01" oninput="calculateTradeStats()">
            
            <div class="trade-summary" id="tradeSummary" style="display:none;">
                <span>📊 <strong>Risk/Reward Ratio:</strong> <span id="tradeRRR">-</span></span>
                <span>💸 <strong>Risk Amount:</strong> ৳<span id="tradeRiskAmount">0</span></span>
                <span>🎯 <strong>Potential Profit:</strong> ৳<span id="tradeProfitAmount">0</span></span>
                <span>📈 <strong>Quantity:</strong> <span id="tradeQuantity">0</span> shares</span>
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
        let editingRow = null;
        let alertRules = [];
        let currentTradeSymbol = null;
        
        // Sorting state
        let currentSort = { field: null, order: null };
        let defaultSort = { diff: 'asc', gape: 'desc' };

        const COLLECTION_MAP = { 
            ai_signals: 'daily_ai_signals', 
            swrsi: 'swrsi_signals', 
            support: 'support_resistance', 
            macd: 'macd_signals', 
            ema: 'ema_21_signals', 
            buy: 'daily_buy_signals' 
        };

        loadDates(COLLECTION_MAP[currentTab]);
        loadCurrentTab();
        checkMarketStatus();
        loadDseLtp();
        loadAlertRules();
        setInterval(checkMarketStatus, 60000);
        // মার্কেট বন্ধ থাকলেও ৬০ সেকেন্ডে LTP ফেচ করবে
        setInterval(loadDseLtp, 60000);
        updateSortStatus();

        function loadAlertRules() {
            const saved = localStorage.getItem('ltpAlertRules_v30');
            if (saved) { try { alertRules = JSON.parse(saved); } catch(e) { alertRules = []; } }
            updateAlertUI();
        }
        
        function saveAlertRules() { 
            localStorage.setItem('ltpAlertRules_v30', JSON.stringify(alertRules)); 
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

        function updateSortStatus() {
            const statusDiv = document.getElementById('sortStatus');
            if (currentSort.field) {
                statusDiv.innerHTML = '📊 <strong>Sorted by:</strong> ' + currentSort.field + ' (' + currentSort.order.toUpperCase() + ') | <span style="cursor:pointer;color:#ffa500;" onclick="resetSort()">↺ Reset to Default</span>';
                statusDiv.style.display = 'block';
            } else {
                statusDiv.innerHTML = '📊 <strong>Default Sort:</strong> diff ASC (↓low first), gape DESC (↑high first)';
                statusDiv.style.display = 'block';
            }
        }

        function handleSort(field) {
            if (currentSort.field === field) {
                // Toggle order
                currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                // New field - start with asc for diff, desc for gape
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
                return '<span class="sort-indicator">' + (currentSort.order === 'asc' ? '▲' : '▼') + '</span>';
            }
            // Show default indicators
            if (!currentSort.field) {
                if (field === 'diff') return '<span class="sort-indicator" style="color:#ffa500;">▲</span>';
                if (field === 'gape') return '<span class="sort-indicator" style="color:#ffa500;">▼</span>';
            }
            return '<span class="sort-indicator" style="opacity:0.3;">⇅</span>';
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
                // মার্কেট বন্ধ থাকলেও LTP ডাটা লোড হবে
                if (j.ltp_data && Object.keys(j.ltp_data).length > 0) {
                    dseLtpData = j.ltp_data;
                }
                renderCurrentTab();
            } catch(e) {
                console.error('LTP fetch error:', e.message);
            }
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
            let sortParam = '';
            if (currentSort.field) {
                sortParam = `&sort_by=${currentSort.field}&sort_order=${currentSort.order}`;
            }
            // Default sorting is handled by API (diff ASC, gape DESC)
            
            if (currentTab === 'ai_signals') {
                let url = `/api/signals?date=${date}&limit=1000${sortParam}`;
                if (symbol) url += `&symbol=${symbol}`;
                const r = await fetch(url); const j = await r.json();
                currentData = j.data || [];
            } else if (currentTab === 'swrsi') {
                let url = `/api/swrsi?${sortParam}`;
                if (date) url += `&date=${date}`;
                if (symbol) url += `&symbol=${symbol}`;
                const r = await fetch(url); const j = await r.json();
                currentData = j.signals || [];
            } else {
                const map = { support: 'support_resistance', macd: 'macd_signals', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
                let url = `/api/generic-data?collection=${map[currentTab]}&limit=500${sortParam}`;
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
            const map = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
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

        function isLtpAboveHigh(symbol, highPrice) {
            const ltp = dseLtpData[symbol] || null;
            if (!ltp || !highPrice || highPrice <= 0) return false;
            return ltp > highPrice;
        }

        function getLtpDisplay(symbol, highPrice) {
            const ltp = dseLtpData[symbol] || null;
            const alertStatus = getLtpAlertStatus(symbol);
            if (!ltp) return '<span style="color:#888;">-</span>';
            let cls = '', arrow = '';
            
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

        function getRowClass(symbol, highPrice) {
            const alertStatus = getLtpAlertStatus(symbol);
            const ltpBreakHigh = isLtpAboveHigh(symbol, highPrice);
            
            if (ltpBreakHigh) return 'ltp-break-high';
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
            if (!symbol || symbol.includes('--')) return;
            
            currentTradeSymbol = symbol;
            
            const record = currentData.find(r => r.symbol === symbol);
            if (record) {
                document.getElementById('tradeEntryPrice').value = record.entry_price || '';
                document.getElementById('tradeStopLoss').value = record.stop_loss || '';
                document.getElementById('tradeTargetPrice').value = record.target_price || '';
                document.getElementById('tradeTotalExposure').value = record.total_exposure || '';
                document.getElementById('tradeRiskPercent').value = record.risk_percent || '';
            } else {
                document.getElementById('tradeEntryPrice').value = '';
                document.getElementById('tradeStopLoss').value = '';
                document.getElementById('tradeTargetPrice').value = '';
                document.getElementById('tradeTotalExposure').value = '';
                document.getElementById('tradeRiskPercent').value = '';
            }
            calculateTradeStats();
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
            const collection = COLLECTION_MAP[currentTab];
            const select = document.getElementById('tradeSymbolSelect');
            select.innerHTML = '<option value="">Loading...</option>';
            try {
                let url = `/api/collection-symbols?collection=${collection}`;
                if (date) url += `&date=${date}`;
                const symbols = await (await fetch(url)).json();
                select.innerHTML = '<option value="">-- Select Symbol --</option>';
                if (symbols.length > 0) {
                    symbols.forEach(s => { 
                        const o = document.createElement('option'); 
                        o.value = s; 
                        o.textContent = s; 
                        select.appendChild(o); 
                    });
                }
            } catch(e) { 
                select.innerHTML = '<option value="">Error</option>'; 
            }
        }

        async function saveTrade() {
            const symbol = document.getElementById('tradeSymbolSelect').value;
            if (!symbol || symbol.includes('--')) {
                alert('Please select a symbol!');
                return;
            }
            
            const entry = parseFloat(document.getElementById('tradeEntryPrice').value) || 0;
            const sl = parseFloat(document.getElementById('tradeStopLoss').value) || 0;
            const tp = parseFloat(document.getElementById('tradeTargetPrice').value) || 0;
            const exposure = parseFloat(document.getElementById('tradeTotalExposure').value) || 0;
            const riskPct = parseFloat(document.getElementById('tradeRiskPercent').value) || 0;
            
            const record = currentData.find(r => r.symbol === symbol);
            const date = record ? (record.analysis_date || record.date || '') : '';
            
            if (!date) {
                alert('Could not find date for this symbol!');
                return;
            }
            
            const collection = COLLECTION_MAP[currentTab];
            const params = new URLSearchParams({
                collection: collection,
                symbol: symbol,
                date: date
            });
            
            if (entry) params.append('entry_price', entry);
            if (sl) params.append('stop_loss', sl);
            if (tp) params.append('target_price', tp);
            if (exposure) params.append('total_exposure', exposure);
            if (riskPct) params.append('risk_percent', riskPct);
            
            try {
                const r = await fetch(`/api/update-trade?${params}`, { method: 'PUT' });
                const result = await r.json();
                alert(`Trade saved successfully! (${result.updated} record(s) updated)`);
                closeTradeModal();
                loadCurrentTab();
            } catch(e) {
                alert('Failed to save trade: ' + e.message);
            }
        }

        function startEdit(symbol, date, entry, sl, tp, i) { editingRow = { symbol, date, rowIndex: i }; renderAITable(); }
        function cancelEdit() { editingRow = null; renderAITable(); }

        async function saveEdit(symbol, date) {
            const safeId = symbol.replace(/[^a-zA-Z0-9]/g, '_');
            const entry = parseFloat(document.getElementById(`edit-entry-${safeId}`).value) || 0;
            const sl = parseFloat(document.getElementById(`edit-sl-${safeId}`).value) || 0;
            const tp = parseFloat(document.getElementById(`edit-tp-${safeId}`).value) || 0;
            const params = new URLSearchParams({ 
                collection: COLLECTION_MAP[currentTab],
                symbol, 
                date, 
                entry_price: entry, 
                stop_loss: sl, 
                target_price: tp 
            });
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
            const map = { ai_signals: 'daily_ai_signals', swrsi: 'swrsi_signals', support: 'support_resistance', macd: 'macd_signals', ema: 'ema_21_signals', buy: 'daily_buy_signals' };
            await fetch(`/api/delete-signal?collection=${map[tab]}&symbol=${symbol}&date=${date}`, { method: 'DELETE' });
            loadCurrentTab();
        }

        function renderAITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No data</p>'; return; }
            
            let html = `<table><thead><tr>
                <th>#</th>
                <th onclick="handleSort('symbol')">Symbol${getSortIndicator('symbol')}</th>
                <th>Date</th>
                <th onclick="handleSort('current_price')">Price${getSortIndicator('current_price')}</th>
                <th>LTP</th>
                <th>Sector</th>
                <th onclick="handleSort('final_signal')">Signal${getSortIndicator('final_signal')}</th>
                <th onclick="handleSort('final_combined_score')">Score${getSortIndicator('final_combined_score')}</th>
                <th>LLM</th><th>LLM%</th><th>LLM Str</th>
                <th>LLM Bias</th><th>LLM Av</th><th>XGB</th><th>XGB%</th><th>XGB Pr</th><th>AUC</th>
                <th>XGB Av</th><th>PPO</th><th>PPO%</th><th>PPO Av</th><th>PPO Wt</th>
                <th>Agentic</th><th>Ag Bias</th><th>Ag Av</th>
                <th>E Acc</th><th>E Tot</th><th>E Wave</th><th>Sub-Wave</th>
                <th>Cur Wave</th><th>W Conf</th><th>Bull?</th><th>W Pos</th>
                <th onclick="handleSort('diff')">Diff${getSortIndicator('diff')}</th>
                <th onclick="handleSort('gape')">Gape${getSortIndicator('gape')}</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Exposure</th><th>Risk%</th>
                <th>Act</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const safeId = (r.symbol || '').replace(/[^a-zA-Z0-9]/g, '_');
                const isEditing = editingRow && editingRow.symbol === r.symbol && editingRow.date === r.analysis_date;
                const isEdited = r.edited === true;
                const hasTrade = r.entry_price || r.stop_loss || r.target_price || r.total_exposure || r.risk_percent;
                
                const highPrice = r.high || r.current_high || r.breakout_high || r.last_high || 0;
                
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
                    : `<button class="edit-btn" onclick="startEdit('${r.symbol}','${r.analysis_date}','${r.entry_price||0}','${r.stop_loss||0}','${r.target_price||0}',${i})">✏️</button><button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${r.analysis_date}')">🗑️</button>`;
                
                const breakBadge = ltpBreakHigh ? '<span class="ltp-break-badge">🚀HIGH</span>' : '';
                
                html += `<tr class="${rowClass}">
                    <td>${i+1}</td><td><strong>${r.symbol}${isEdited ? '<span class="edited-badge">✏️</span>' : ''}${hasTrade ? '<span class="trade-badge">💰</span>' : ''}${alertStatus ? ' 🔔' : ''}${breakBadge}</strong></td>
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

        function renderSWRSITable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p style="color:#888;text-align:center;padding:40px;">No SWRSI signals found</p>'; return; }
            
            let html = `<table><thead><tr>
                <th>#</th>
                <th onclick="handleSort('symbol')">Symbol${getSortIndicator('symbol')}</th>
                <th>Sector</th><th>LTP</th>
                <th onclick="handleSort('composite_score')">Composite Score${getSortIndicator('composite_score')}</th>
                <th>Weekly Div</th><th>Weekly Label</th><th>Weekly Score</th>
                <th>Prev Low</th><th>Curr Low</th><th>Prev RSI</th><th>Curr RSI</th>
                <th>Price Drop%</th><th>RSI Gain</th>
                <th>Prev Week</th><th>Curr Week</th>
                <th>Daily Div</th><th>Daily Strength</th>
                <th>Daily Last RSI</th><th>Daily Prev RSI</th>
                <th onclick="handleSort('diff')">Diff${getSortIndicator('diff')}</th>
                <th onclick="handleSort('gape')">Gape${getSortIndicator('gape')}</th>
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Exposure</th><th>Risk%</th>
                <th>Act</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const highPrice = r.high || r.daily_last_high || r.weekly_curr_high || 0;
                
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const ltpBreakHigh = isLtpAboveHigh(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const hasTrade = r.entry_price || r.stop_loss || r.target_price || r.total_exposure || r.risk_percent;
                const rrr = r.risk_reward_ratio || 0;
                const rrrClass = getRRRClass(rrr);
                const recordDate = r.analysis_date || r.date || '';
                const breakBadge = ltpBreakHigh ? '<span class="ltp-break-badge">🚀HIGH</span>' : '';
                
                html += `<tr class="${rowClass}">
                    <td>${i+1}</td><td><strong>${r.symbol || ''}${hasTrade ? '<span class="trade-badge">💰</span>' : ''}${alertStatus ? ' 🔔' : ''}${breakBadge}</strong></td><td>${r.sector || ''}</td>
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
                    <td style="color:#ffd700;font-weight:bold;">${r.diff !== undefined ? (r.diff > 0 ? '+' : '') + r.diff.toFixed(2) : '-'}</td>
                    <td style="color:#00d4ff;font-weight:bold;">${r.gape !== undefined ? r.gape.toFixed(2) : '-'}</td>
                    <td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>
                    <td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>
                    <td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>
                    <td class="${rrrClass}"><strong>${rrr.toFixed(2)}</strong></td>
                    <td>${r.total_exposure ? '৳'+r.total_exposure.toLocaleString() : '-'}</td>
                    <td>${r.risk_percent ? r.risk_percent.toFixed(1)+'%' : '-'}</td>
                    <td><button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button><button class="delete-btn" onclick="deleteRecord('${r.symbol}','${recordDate}','swrsi')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
        }

        function renderGenericTable() {
            const div = document.getElementById('dynamicTable');
            if (!currentData.length) { div.innerHTML = '<p>No data</p>'; return; }
            
            const excludeKeys = ['_id', 'saved_at', 'analysis_date', 'latest_date', 'analysis_datetime', 'date', 'symbol', 'entry_price', 'stop_loss', 'target_price', 'risk_reward_ratio', 'total_exposure', 'risk_percent', 'edited', 'edited_at','p1_date','p2_date','level_date','level_price','type','high_x','high_y','no','prev_high','swing_highs_count','swing_highs_details','uptrand_date','SL','buy','dd','dl','No','low'];
            const keys = Object.keys(currentData[0]).filter(k => !excludeKeys.includes(k) && !k.startsWith('_'));
            
            let html = `<table><thead><tr>
                <th>#</th>
                <th onclick="handleSort('symbol')">Symbol${getSortIndicator('symbol')}</th>
                <th>LTP</th>
                ${keys.map(k => {
                    if (k === 'diff' || k === 'gape') {
                        return `<th onclick="handleSort('${k}')">${k}${getSortIndicator(k)}</th>`;
                    }
                    return `<th>${k}</th>`;
                }).join('')}
                <th>Entry</th><th>SL</th><th>TP</th><th>RRR</th><th>Exposure</th><th>Risk%</th>
                <th>Act</th>
            </tr></thead><tbody>`;
            
            currentData.forEach((r, i) => {
                const highPrice = r.high || r.current_high || r.breakout_high || r.last_high || 0;
                
                const ltpDisplay = getLtpDisplay(r.symbol, highPrice);
                const alertStatus = getLtpAlertStatus(r.symbol);
                const ltpBreakHigh = isLtpAboveHigh(r.symbol, highPrice);
                const rowClass = getRowClass(r.symbol, highPrice);
                const recordDate = r.analysis_date || r.date || r.level_date || (r.saved_at||'').substring(0,10) || '';
                const hasTrade = r.entry_price || r.stop_loss || r.target_price || r.total_exposure || r.risk_percent;
                const rrr = r.risk_reward_ratio || 0;
                const rrrClass = getRRRClass(rrr);
                const breakBadge = ltpBreakHigh ? '<span class="ltp-break-badge">🚀HIGH</span>' : '';
                
                html += `<tr class="${rowClass}">
                    <td>${i+1}</td>
                    <td><strong>${r.symbol || ''}${hasTrade ? '<span class="trade-badge">💰</span>' : ''}${alertStatus ? ' 🔔' : ''}${breakBadge}</strong></td>
                    <td>${ltpDisplay}</td>
                    ${keys.map(k => {
                        if (k === 'diff') {
                            return `<td style="color:#ffd700;font-weight:bold;">${r[k] !== undefined ? (r[k] > 0 ? '+' : '') + Number(r[k]).toFixed(2) : '-'}</td>`;
                        }
                        if (k === 'gape') {
                            return `<td style="color:#00d4ff;font-weight:bold;">${r[k] !== undefined ? Number(r[k]).toFixed(2) : '-'}</td>`;
                        }
                        return `<td>${r[k]??''}</td>`;
                    }).join('')}
                    <td>${r.entry_price ? r.entry_price.toFixed(2) : '-'}</td>
                    <td>${r.stop_loss ? r.stop_loss.toFixed(2) : '-'}</td>
                    <td>${r.target_price ? r.target_price.toFixed(2) : '-'}</td>
                    <td class="${rrrClass}"><strong>${rrr.toFixed(2)}</strong></td>
                    <td>${r.total_exposure ? '৳'+r.total_exposure.toLocaleString() : '-'}</td>
                    <td>${r.risk_percent ? r.risk_percent.toFixed(1)+'%' : '-'}</td>
                    <td><button class="trade-edit-btn" onclick="openTradeForSymbol('${r.symbol}')">💰</button><button class="delete-btn" onclick="deleteRecord('${r.symbol||''}','${recordDate}','${currentTab}')">🗑️</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            div.innerHTML = html;
            document.getElementById('recordCount').textContent = `(${currentData.length} records)`;
        }

        async function openTradeForSymbol(symbol) {
            const select = document.getElementById('tradeSymbolSelect');
            await loadTradeSymbols();
            select.value = symbol;
            onTradeSymbolChange();
            openTradeModal();
        }

        // ==================== PWA Install ====================
let deferredPrompt;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    document.getElementById('installBtn').style.display = 'inline-block';
});

function installApp() {
    if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then((choiceResult) => {
            if (choiceResult.outcome === 'accepted') {
                console.log('✅ User installed the app');
            }
            deferredPrompt = null;
            document.getElementById('installBtn').style.display = 'none';
        });
    }
}

// Already installed check
if (window.matchMedia('(display-mode: standalone)').matches) {
    document.getElementById('installBtn').style.display = 'none';
}

       if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js');
        });
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
