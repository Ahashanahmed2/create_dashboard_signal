"""
scripts/create_dashboard.py
FastAPI + MongoDB Dashboard for AI Trading Signals
✅ তারিখ ভিত্তিক ফিল্টার + ৩৬টি কলাম
"""

import os
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime

MONGODB_URI = os.environ.get("MONGODBEMAIL_URI", "")
DATABASE_NAME = "swing_trading_db"
COLLECTION_NAME = "daily_ai_signals"

app = FastAPI(title="AI Trading Signals Dashboard", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_mongo_collection():
    if not MONGODB_URI:
        return None
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        return db[COLLECTION_NAME]
    except:
        return None

# ================================
# API
# ================================
@app.get("/api/health")
async def health():
    return {"status": "ok", "mongodb": "connected" if MONGODB_URI else "not configured"}

@app.get("/api/dates")
async def get_dates():
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)
    dates = collection.distinct('analysis_date')
    return sorted(dates, reverse=True)

@app.get("/api/signals")
async def get_signals(date: str = Query(None), signal: str = Query(None), min_score: float = Query(0), limit: int = Query(500), offset: int = Query(0)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(collection.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']

    if signal: query['final_signal'] = {'$regex': signal, '$options': 'i'}
    if min_score > 0: query['final_combined_score'] = {'$gte': min_score}

    total = collection.count_documents(query)
    cursor = collection.find(query, {'_id': 0}).sort('final_combined_score', -1).skip(offset).limit(limit)
    return {"total": total, "count": len(list(cursor.clone())), "offset": offset, "limit": limit, "data": list(cursor)}

@app.get("/api/stats")
async def get_stats(date: str = Query(None)):
    collection = get_mongo_collection()
    if collection is None: return JSONResponse({"error": "MongoDB not configured"}, status_code=500)

    query = {}
    if date: query['analysis_date'] = date
    else:
        latest = list(collection.find().sort('analysis_date', -1).limit(1))
        if latest: query['analysis_date'] = latest[0]['analysis_date']

    pipeline = [{'$match': query}, {'$group': {'_id': None, 'total': {'$sum': 1}, 'avg_score': {'$avg': '$final_combined_score'}, 'max_score': {'$max': '$final_combined_score'}, 'buy_count': {'$sum': {'$cond': [{'$regexFind': {'input': '$final_signal', 'regex': 'BUY'}}, 1, 0]}}, 'sell_count': {'$sum': {'$cond': [{'$regexFind': {'input': '$final_signal', 'regex': 'SELL'}}, 1, 0]}}}}]
    result = list(collection.aggregate(pipeline))
    if result: return {k: v for k, v in result[0].items() if k != '_id'}
    return {"total": 0, "avg_score": 0, "max_score": 0, "buy_count": 0, "sell_count": 0}

# ================================
# HTML
# ================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Trading Signals</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 30px; background: linear-gradient(45deg, #1a1a2e, #0f3460); border-radius: 15px; margin-bottom: 20px; }
        .header h1 { font-size: 2.5em; background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-card { background: #111122; border: 1px solid #222; border-radius: 10px; padding: 20px; text-align: center; }
        .stat-card h3 { color: #888; font-size: 0.9em; margin-bottom: 10px; }
        .stat-card .value { font-size: 2em; font-weight: bold; }
        .controls { display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }
        select, input, button { padding: 10px 15px; background: #1a1a2e; color: #fff; border: 1px solid #333; border-radius: 8px; }
        button { cursor: pointer; background: #0f3460; }
        .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .chart-card { background: #111122; border: 1px solid #222; border-radius: 10px; padding: 20px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.8em; margin-top: 20px; background: #111122; border-radius: 10px; overflow: hidden; }
        th { background: #1a1a2e; padding: 12px 8px; color: #00d4ff; white-space: nowrap; }
        td { padding: 8px; border-bottom: 1px solid #222; white-space: nowrap; }
        .signal-SB { color: #00ff88; font-weight: bold; }
        .signal-B { color: #00cc66; font-weight: bold; }
        .signal-H { color: #ffd700; }
        .signal-S { color: #ff4757; }
        .signal-SS { color: #ff0000; font-weight: bold; }
    </style>
</head>
<body>
    <div class="header"><h1>🤖 AI Trading Signals Dashboard</h1><p>LLM + XGBoost + PPO + Agentic Loop + Elliott Wave | MongoDB Powered</p></div>

    <div class="stats">
        <div class="stat-card"><h3>📊 Total</h3><div class="value" id="statTotal">-</div></div>
        <div class="stat-card" style="border-left:3px solid #00ff88;"><h3>🟢 Buy</h3><div class="value" id="statBuy" style="color:#00ff88;">-</div></div>
        <div class="stat-card" style="border-left:3px solid #ff4757;"><h3>🔴 Sell</h3><div class="value" id="statSell" style="color:#ff4757;">-</div></div>
        <div class="stat-card"><h3>📈 Avg Score</h3><div class="value" id="statAvg">-</div></div>
    </div>

    <div class="controls">
        <label>📅 Date:</label>
        <select id="dateSelect" onchange="loadData(this.value)"><option value="">Latest</option></select>
        <label>📈 Signal:</label>
        <select id="signalFilter" onchange="renderTable()"><option value="">All</option><option value="BUY">Buy</option><option value="SELL">Sell</option><option value="HOLD">Hold</option></select>
        <label>⭐ Min Score:</label><input type="number" id="minScore" value="0" onchange="renderTable()" style="width:80px;">
        <button onclick="loadData()">🔄 Refresh</button>
    </div>

    <div class="charts">
        <div class="chart-card"><h3>📈 Signal Distribution</h3><canvas id="signalChart"></canvas></div>
        <div class="chart-card"><h3>🌊 Elliott Wave</h3><canvas id="elliottChart"></canvas></div>
    </div>

    <h2>📋 Trading Signals <span id="tableCount"></span></h2>
    <div style="overflow-x:auto;">
        <table id="signalTable">
    <thead>
        <tr>
            <th>#</th>
            <th>Symbol</th>
            <th>Date</th>
            <th>Price</th>
            <th>Sector</th>
            <th>Final Signal</th>
            <th>Score</th>
            <th>LLM</th>
            <th>LLM%</th>
            <th>LLM Str</th>
            <th>LLM Bias</th>
            <th>LLM Avail</th>
            <th>XGB</th>
            <th>XGB%</th>
            <th>XGB Prob</th>
            <th>AUC</th>
            <th>XGB Avail</th>
            <th>PPO</th>
            <th>PPO%</th>
            <th>PPO Avail</th>
            <th>PPO Wt</th>
            <th>Agentic</th>
            <th>Agentic Bias</th>
            <th>Agentic Avail</th>
            <th>Elliott Acc</th>
            <th>Elliott Total</th>
            <th>Elliott Wave</th>
            <th>Sub-Waves</th>
            <th>Current Wave</th>
            <th>Wave Conf</th>
            <th>Bullish?</th>
            <th>Wave Pos</th>
            <th>Models</th>
            <th>Entry</th>
            <th>SL</th>
            <th>TP</th>
            <th>R:R</th>
        </tr>
    </thead>
    <tbody id="tableBody"></tbody>
</table>
    </div>

    <script>
        let currentData = [];
        let signalChart, elliottChart;

        async function loadDates() {
            try {
                const res = await fetch('/api/dates');
                const dates = await res.json();
                const select = document.getElementById('dateSelect');
                select.innerHTML = '<option value="">Latest</option>';
                dates.forEach(d => { const opt = document.createElement('option'); opt.value = d; opt.textContent = d; select.appendChild(opt); });
            } catch(e) { console.error(e); }
        }

        async function loadData(date = '') {
            document.getElementById('tableBody').innerHTML = '<tr><td colspan="17" style="text-align:center;padding:40px;">📂 Loading...</td></tr>';
            try {
                const url = date ? `/api/signals?date=${date}&limit=1000` : '/api/signals?limit=1000';
                const res = await fetch(url);
                const json = await res.json();
                currentData = json.data || [];
                updateStats();
                renderTable();
                updateCharts();
            } catch(e) {
                document.getElementById('tableBody').innerHTML = '<tr><td colspan="17" style="color:red;">❌ Failed to load</td></tr>';
            }
        }

        async function updateStats() {
            try {
                const res = await fetch('/api/stats');
                const stats = await res.json();
                document.getElementById('statTotal').textContent = stats.total || 0;
                document.getElementById('statBuy').textContent = stats.buy_count || 0;
                document.getElementById('statSell').textContent = stats.sell_count || 0;
                document.getElementById('statAvg').textContent = (stats.avg_score || 0).toFixed(1);
            } catch(e) {}
        }

        function renderTable() {
    const signalFilter = document.getElementById('signalFilter').value;
    const minScore = parseFloat(document.getElementById('minScore').value) || 0;
    
    let filtered = currentData;
    if (signalFilter) filtered = filtered.filter(r => (r.final_signal || '').includes(signalFilter));
    if (minScore > 0) filtered = filtered.filter(r => (r.final_combined_score || 0) >= minScore);
    
    const tbody = document.getElementById('tableBody');
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="38" style="text-align:center;padding:40px;color:#888;">No signals match filters</td></tr>';
        return;
    }
    
    tbody.innerHTML = filtered.map((r, i) => `
        <tr>
            <td>${i + 1}</td>
            <td><strong>${r.symbol}</strong></td>
            <td>${r.analysis_date || r.date || ''}</td>
            <td>${(r.current_price || 0).toFixed(2)}</td>
            <td>${r.sector || 'N/A'}</td>
            <td class="${getSignalClass(r.final_signal)}">${r.final_signal || 'N/A'}</td>
            <td><strong>${(r.final_combined_score || 0).toFixed(1)}</strong></td>
            <td>${r.llm_signal || 'N/A'}</td>
            <td>${(r.llm_confidence || 0).toFixed(0)}%</td>
            <td>${r.llm_strength || 'N/A'}</td>
            <td>${r.llm_bias || 'N/A'}</td>
            <td>${r.llm_available ? '✅' : '❌'}</td>
            <td>${r.xgb_signal || 'N/A'}</td>
            <td>${(r.xgb_confidence || 0).toFixed(0)}%</td>
            <td>${(r.xgb_prob_up || 0).toFixed(3)}</td>
            <td>${(r.xgb_auc || 0).toFixed(3)}</td>
            <td>${r.xgb_available ? '✅' : '❌'}</td>
            <td>${r.ppo_signal || 'N/A'}</td>
            <td>${(r.ppo_confidence || 0).toFixed(0)}%</td>
            <td>${r.ppo_available ? '✅' : '❌'}</td>
            <td>${r.ppo_weight || 0}</td>
            <td>${(r.agentic_score || 0).toFixed(1)}</td>
            <td>${r.agentic_bias || 'N/A'}</td>
            <td>${r.agentic_available ? '✅' : '❌'}</td>
            <td>${(r.elliott_accuracy || 0).toFixed(1)}%</td>
            <td>${r.elliott_total_predictions || 0}</td>
            <td style="font-size:0.7em;">${r.elliott_wave_count || 'N/A'}</td>
            <td style="font-size:0.7em;max-width:150px;overflow:hidden;text-overflow:ellipsis;">${r.elliott_sub_waves || 'N/A'}</td>
            <td>${r.elliott_current_wave || 'N/A'}</td>
            <td>${(r.elliott_wave_confidence || 0).toFixed(0)}%</td>
            <td>${r.elliott_is_bullish ? '✅' : '❌'}</td>
            <td>${r.elliott_wave_position || 'N/A'}</td>
            <td>${r.model_availability || 'N/A'}</td>
            <td>${(r.entry_price || 0).toFixed(2)}</td>
            <td>${(r.stop_loss || 0).toFixed(2)}</td>
            <td>${(r.target_price || 0).toFixed(2)}</td>
            <td>${r.risk_reward_ratio || 0}</td>
        </tr>
    `).join('');
}

        function updateCharts() {
            // Signal Distribution
            const signalCounts = {};
            currentData.forEach(r => { const s = r.final_signal || 'Unknown'; signalCounts[s] = (signalCounts[s] || 0) + 1; });
            const ctx1 = document.getElementById('signalChart').getContext('2d');
            if (signalChart) signalChart.destroy();
            signalChart = new Chart(ctx1, { type: 'doughnut', data: { labels: Object.keys(signalCounts), datasets: [{ data: Object.values(signalCounts), backgroundColor: ['#00ff88', '#00cc66', '#ffa500', '#ffd700', '#ff4757', '#ff0000'] }] }, options: { plugins: { legend: { position: 'bottom', labels: { color: '#aaa' } } } } });
            
            // Elliott Wave
            const waveCounts = {};
            currentData.forEach(r => { const w = r.elliott_current_wave; if (w && !['Unknown','None','Error'].includes(w)) waveCounts[w] = (waveCounts[w] || 0) + 1; });
            const ctx2 = document.getElementById('elliottChart').getContext('2d');
            if (elliottChart) elliottChart.destroy();
            elliottChart = new Chart(ctx2, { type: 'bar', data: { labels: Object.keys(waveCounts), datasets: [{ data: Object.values(waveCounts), backgroundColor: ['#ff6b6b','#ffa500','#ffd700','#00ff88','#00d4ff','#7b2ff7'] }] }, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#aaa' } }, y: { ticks: { color: '#aaa' } } } } });
        }

        loadDates();
        loadData();
    </script>
</body>
</html>
"""
def get_signal_class(signal):
    if not signal:
        return ''
    if 'STRONG BUY' in signal:
        return 'signal-SB'
    elif 'BUY' in signal:
        return 'signal-B'
    elif 'HOLD' in signal:
        return 'signal-H'
    elif 'STRONG SELL' in signal:
        return 'signal-SS'
    elif 'SELL' in signal:
        return 'signal-S'
    return ''

if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", 8000))
    print(f"🚀 Dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
