#!/usr/bin/env python3
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, os, time, urllib.request, urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any
BACKEND=os.environ.get('RLDC_BACKEND_URL','http://127.0.0.1:8000').rstrip('/')
HOST=os.environ.get('RLDC_OVERLAY_HOST','127.0.0.1')
PORT=int(os.environ.get('RLDC_OVERLAY_PORT','8099'))
TIMEOUT=float(os.environ.get('RLDC_OVERLAY_TIMEOUT','3'))
ENRICH_TIMEOUT=float(os.environ.get('RLDC_OVERLAY_ENRICH_TIMEOUT','0.5'))
ENRICH_ROWS=max(0,int(os.environ.get('RLDC_OVERLAY_ENRICH_ROWS','1')))
ENDPOINTS=[
    '/api/dashboard/market-scan?mode=live',
    '/api/signals/final-decisions?mode=live',
    '/api/account/runtime-activity?mode=live',
    '/api/account/capital-snapshot?mode=live',
    '/api/account/trading-status?mode=live',
    '/api/positions?mode=live',
    '/api/rldc/safe/live-state',
    '/api/system/full-status',
    '/api/control/state',
    '/api/account/runtime-settings',
    '/api/account/runtime-config',
]
HISTORY_TIMEFRAMES=('15m','5m','1m','1h')
NUM={'price':['price','last_price','current_price','mark_price','close','last'],'change_pct':['price_change_pct','change_pct','change_1m_pct','price_change_1m','price_change_5m','change24h_pct'],'pnl_pct':['pnl_pct','current_pnl_pct','total_pnl_pct','net_pnl_pct','roi_pct'],'pnl_eur':['pnl_eur','current_pnl_eur','net_pnl_eur','total_pnl_eur','realized_pnl_eur','unrealized_pnl_eur'],'entry':['entry','entry_price','avg_entry_price','entry_target','buy_at','entry_zone'],'target':['target','target_price','take_profit','tp','tp_price','target_zone','sell_at'],'stop':['stop','stop_price','stop_loss','sl','sl_price','stop_zone'],'confidence':['confidence','overall_decision_confidence','direction_confidence','profitability_confidence'],'risk_score':['risk_score','risk','risk_value'],'edge':['edge','profitability_score','expected_edge','expected_net_move_pct_after_costs'],'min_capital':['minimal_sensible_capital','min_capital','recommended_capital','min_order_eur','min_notional_eur']}
TXT={'symbol':['symbol','pair','market','ticker'],'quote':['quote','quote_asset','currency'],'action':['recommended_action','action','signal','decision','side','final_action','final_action_pl','signal_type'],'trend':['trend','trend_state','direction_label','market_regime'],'plan':['plan','plan_summary_short','plan_summary_plain','summary','next_action','final_user_message'],'reason':['reason','reasons_short','explanation','plain_explanation','why','final_reason','raw_reason'],'whale':['whale','whale_state','anomaly','anomaly_state'],'queue_state':['queue_state','state','position_state','status'],'updated_at':['updated_at','last_update','timestamp','created_at','generated_at']}
def get_json(path, timeout=None):
    req_timeout=TIMEOUT if timeout is None else timeout
    try:
        with urllib.request.urlopen(urllib.request.Request(BACKEND+path,headers={'Accept':'application/json'}),timeout=req_timeout) as r:
            return True,json.loads(r.read().decode('utf-8','replace')),'ok'
    except urllib.error.HTTPError as e: return False,None,f'http_{e.code}'
    except Exception as e: return False,None,f'error:{e}'
def fetch_direct(path, timeout=None):
    ok,data,_=get_json(path, timeout=timeout)
    return data if ok and isinstance(data,dict) else None
def walk(o):
    yield o
    if isinstance(o,dict):
        for v in o.values(): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)
def first(d,keys):
    if not isinstance(d,dict): return None
    low={str(k).lower():v for k,v in d.items()}
    for k in keys:
        if k in d and d[k] not in (None,''): return d[k]
        if k.lower() in low and low[k.lower()] not in (None,''): return low[k.lower()]
    return None
def fl(v):
    if v is None: return None
    if isinstance(v,(int,float)): return float(v)
    if isinstance(v,str):
        s=v.strip().replace('%','').replace('€','').replace('USDC','').replace('USDT','').replace(' ','')
        if ',' in s and '.' not in s: s=s.replace(',','.')
        try: return float(s)
        except: return None
    return None
def nsym(v):
    if not v: return None
    s=str(v).strip().upper().replace('/','').replace('-','')
    return s if len(s)>=4 and s not in {'NONE','NULL','UNKNOWN'} else None
def hist(row):
    for k in ['history','price_history','candles','ohlcv','forecast_source_prices']:
        v=row.get(k)
        if isinstance(v,list):
            out=[]
            for x in v[-80:]:
                n=fl(first(x,['close','price','last_price','value']) if isinstance(x,dict) else (x[-1] if isinstance(x,(list,tuple)) and x else x))
                if n is not None: out.append(n)
            if len(out)>=2: return out
    return []
def fc(row):
    for k in ['forecast_path','forecast_path_15m','forecast_path_20m','prediction_path','forecast']:
        v=row.get(k)
        if isinstance(v,list):
            out=[fl(x.get('price') if isinstance(x,dict) else x) for x in v]
            out=[x for x in out if x is not None]
            if len(out)>=2: return out[:30]
    return []
def pair(row):
    s=nsym(first(row,TXT['symbol']))
    if not s: return None
    out={'symbol':s}
    for name,keys in TXT.items():
        if name!='symbol':
            v=first(row,keys)
            if v is not None: out[name]=str(v)
    for name,keys in NUM.items():
        v=fl(first(row,keys))
        if v is not None: out[name]=v
    out['history']=hist(row); out['forecast_path']=fc(row)
    if 'price' not in out and out['history']: out['price']=out['history'][-1]
    if 'quote' not in out:
        for q in ['USDC','USDT','EUR','BTC','ETH']:
            if s.endswith(q): out['quote']=q; break
    if 'action' not in out: out['action']='hold' if 'position' in str(out.get('queue_state','')).lower() else 'wait'
    return out
def collect(payloads):
    rows=[]
    for p in payloads:
        for it in walk(p):
            if isinstance(it,dict) and nsym(first(it,TXT['symbol'])):
                if any(k in it for kk in NUM.values() for k in kk) or any(k in it for kk in TXT.values() for k in kk if k!='symbol'):
                    q=pair(it)
                    if q: rows.append(q)
    by={}
    for p in rows:
        score=len([v for v in p.values() if v not in (None,'',[],{})])+len(p.get('history',[]))
        old=by.get(p['symbol'])
        if not old or score>old[0]: by[p['symbol']]=(score,p)
    rows=[v[1] for v in by.values()]
    rows.sort(key=lambda p:(0 if str(p.get('action','')).lower() in {'buy','sell','kup','sprzedaj','entry','exit'} else 1,-abs(float(p.get('pnl_pct') or p.get('change_pct') or 0))))
    return rows
def enrich_row(row):
    symbol=row.get('symbol')
    if not symbol:
        return row
    if not row.get('history'):
        for tf in HISTORY_TIMEFRAMES:
            payload=fetch_direct(
                f'/api/market/kline?symbol={symbol}&tf={tf}&limit=120',
                timeout=ENRICH_TIMEOUT,
            )
            candles=(payload or {}).get('data') if isinstance(payload,dict) else None
            if isinstance(candles,list):
                history=[fl((c or {}).get('close')) for c in candles]
                history=[value for value in history if value is not None]
                if len(history)>=2:
                    row['history']=history
                    row['chart_tf']=tf
                    break
    forecast=fetch_direct(f'/api/market/forecast/{symbol}', timeout=ENRICH_TIMEOUT)
    if isinstance(forecast,dict):
        path=[]
        for key in ('forecast_1h','forecast_4h','forecast_24h'):
            block=forecast.get(key)
            if isinstance(block,dict):
                projected=fl(block.get('projected_price'))
                if projected is not None:
                    path.append(projected)
        if path:
            row['forecast_path']=path
        current=fl(forecast.get('current_price'))
        if current is not None and row.get('price') is None:
            row['price']=current
    return row
def summary(payloads):
    keys={'total_value_eur':['total_value_eur','portfolio_value_eur','wallet_value_eur','equity_eur','total_value'],'total_cost_eur':['total_cost_eur','cost_eur','invested_eur','total_cost'],'total_pnl_eur':['total_pnl_eur','pnl_eur','net_pnl_eur','unrealized_pnl_eur'],'total_pnl_pct':['total_pnl_pct','pnl_pct','net_pnl_pct','roi_pct'],'positions_count':['positions_count','valid_positions_count','open_positions_count','count'],'mode':['mode','trading_mode','environment'],'bot_status':['bot_status','status','state']}
    res={}
    for o in walk(payloads):
        if isinstance(o,dict):
            blocks=[o]+[o[k] for k in ['summary','portfolio_summary','account_summary','overview','analytics','data'] if isinstance(o.get(k),dict)]
            for b in blocks:
                for out,ks in keys.items():
                    if out not in res:
                        v=first(b,ks)
                        if v is not None: res[out]=str(v) if out in {'mode','bot_status'} else fl(v)
    return res
def narr(payloads,rows):
    for o in walk(payloads):
        if isinstance(o,dict):
            t=first(o,['narration','tts_text','broadcast_text','plain_explanation','explanation','message'])
            if isinstance(t,str) and len(t)>12: return t[:420]
    return f"Bot analizuje {rows[0]['symbol']}. Decyzja: {rows[0].get('action','wait')}. Dane są w fazie testów i mogą być niepełne." if rows else 'Brak kanonicznego komentarza z bota. Overlay czeka na synchronizację.'
def live_state():
    statuses={}; payloads=[]
    max_workers=min(8,max(1,len(ENDPOINTS)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures={pool.submit(get_json,ep):ep for ep in ENDPOINTS}
        for fut in as_completed(futures):
            ep=futures[fut]
            try:
                ok,data,st=fut.result()
            except Exception as exc:
                ok,data,st=False,None,f'error:{exc}'
            statuses[ep]=st
            if ok: payloads.append(data)
    rows=collect(payloads)
    rows=[enrich_row(dict(row)) for row in rows[:ENRICH_ROWS]] + rows[ENRICH_ROWS:]
    summ=summary(payloads)
    if 'positions_count' not in summ and rows: summ['positions_count']=len(rows)
    ok_any=bool(payloads); partial=ok_any and (not rows or any(v!='ok' for v in statuses.values()))
    warn=''
    if not ok_any: warn=f'Brak odpowiedzi JSON z backendu RLdC {BACKEND}. Sprawdź, czy FastAPI działa na :8000 albo ustaw RLDC_BACKEND_URL.'
    elif not rows: warn='Backend odpowiada, ale adapter nie znalazł aktywnych par/pozycji z polem symbol. Dane overlayu są niekompletne.'
    elif partial: warn='Część endpointów backendu nie odpowiedziała lub nie istnieje. Overlay pokazuje tylko dostępne dane.'
    return {'ok':ok_any and bool(rows),'partial':partial or not bool(rows),'warning':warn,'source':'RLdC backend adapter','backend_url':BACKEND,'fetched_at':time.time(),'summary':summ,'active_pairs':rows,'queue':rows,'narration':narr(payloads,rows),'endpoint_status':statuses}
class H(SimpleHTTPRequestHandler):
    def log_message(self,*a):
        if os.environ.get('RLDC_OVERLAY_VERBOSE')=='1': super().log_message(*a)
    def do_GET(self):
        try:
            p=urlparse(self.path)
            if p.path=='/overlay/api/live-state': return self.send_json(live_state())
            if p.path.startswith('/api/'):
                ok,data,st=get_json(p.path+('?'+p.query if p.query else ''))
                return self.send_json({'ok':ok,'status':st,'data':data},200 if ok else 502)
            return super().do_GET()
        except Exception as exc:
            return self.send_json({'ok':False,'error':f'overlay_handler_error:{exc}'},500)
    def send_json(self,data,code=200):
        body=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def end_headers(self):
        self.send_header('Cache-Control','no-store'); self.send_header('Access-Control-Allow-Origin','*'); super().end_headers()
if __name__=='__main__':
    class ReusableThreadingHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    print(f'RLdC LIVE overlay: http://{HOST}:{PORT}/index.html'); print(f'Backend RLdC: {BACKEND}'); print('OBS Browser Source: URL powyżej, Width 1920, Height 1080')
    ReusableThreadingHTTPServer((HOST,PORT),H).serve_forever()
