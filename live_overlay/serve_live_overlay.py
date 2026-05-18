#!/usr/bin/env python3
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, os, sqlite3, threading, time, urllib.request, urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any
BACKEND=os.environ.get('RLDC_BACKEND_URL','http://127.0.0.1:8000').rstrip('/')
HOST=os.environ.get('RLDC_OVERLAY_HOST','127.0.0.1')
PORT=int(os.environ.get('RLDC_OVERLAY_PORT','8099'))
TIMEOUT=float(os.environ.get('RLDC_OVERLAY_TIMEOUT','8'))
ENRICH_TIMEOUT=float(os.environ.get('RLDC_OVERLAY_ENRICH_TIMEOUT','2.0'))
# Ścieżka do SQLite — bezpośredni odczyt klines bez HTTP (omija threadpool starvation)
_DB_PATH=os.environ.get('RLDC_DB_PATH',os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'trading_bot.db'))
DECISION_TIMEOUT=float(os.environ.get('RLDC_OVERLAY_DECISION_TIMEOUT','2.5'))
ENRICH_ROWS=max(0,int(os.environ.get('RLDC_OVERLAY_ENRICH_ROWS','8')))
ENDPOINTS=[
    '/api/rldc/safe/live-state',
    '/api/account/trading-status?mode=live',
]
if os.environ.get('RLDC_OVERLAY_INCLUDE_POSITIONS_ANALYSIS', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
    ENDPOINTS.append('/api/positions/analysis?mode=live')
if os.environ.get('RLDC_OVERLAY_INCLUDE_RUNTIME_STATUS', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
    ENDPOINTS.extend([
        '/api/account/trading-status?mode=live',
        '/api/control/state',
        '/health',
    ])
if os.environ.get('RLDC_OVERLAY_USE_EXTENDED_ENDPOINTS', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
    ENDPOINTS.extend([
        '/api/signals/final-decisions?mode=live',
        '/api/account/runtime-activity?mode=live',
        '/api/account/capital-snapshot?mode=live',
        '/api/account/trading-status?mode=live',
        '/api/positions?mode=live',
        '/api/system/full-status',
        '/api/account/runtime-settings',
        '/api/account/runtime-config',
    ])
if os.environ.get('RLDC_OVERLAY_INCLUDE_MARKET_SCAN', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
    ENDPOINTS.append('/api/dashboard/market-scan?mode=live')
HISTORY_TIMEFRAMES=('15m','5m','1m','1h')
NUM={'price':['price','last_price','current_price','mark_price','close','last'],'change_pct':['price_change_pct','change_pct','change_1m_pct','price_change_1m','price_change_5m','change24h_pct'],'pnl_pct':['pnl_pct','pnl_percent','current_pnl_pct','total_pnl_pct','net_pnl_pct','roi_pct'],'pnl_eur':['pnl_eur','current_pnl_eur','net_pnl_eur','total_pnl_eur','realized_pnl_eur','unrealized_pnl_eur'],'entry':['entry','entry_price','avg_entry_price','entry_target','buy_at','entry_zone'],'target':['target','target_price','take_profit','tp','tp_price','planned_tp','target_zone','sell_at'],'stop':['stop','stop_price','stop_loss','sl','sl_price','planned_sl','stop_zone'],'quantity':['qty','quantity','position_qty','size'],'confidence':['confidence','overall_decision_confidence','direction_confidence','profitability_confidence','final_confidence'],'risk_score':['risk_score','risk','risk_value'],'edge':['edge','profitability_score','expected_edge','expected_net_move_pct_after_costs'],'min_capital':['minimal_sensible_capital','min_capital','recommended_capital','min_order_eur','min_notional_eur']}
TXT={'symbol':['symbol','pair','market','ticker'],'analysis_symbol':['analysis_symbol','chart_symbol','canonical_symbol'],'quote':['quote','quote_asset','currency'],'action':['recommended_action_label','recommended_action','action','signal','decision','side','final_action','final_action_pl','signal_type'],'trend':['trend','trend_state','direction_label','market_regime'],'plan':['plan','plan_summary_short','plan_summary_plain','plain_summary','summary','next_action','final_user_message'],'reason':['plain_summary','plain_reasons','reason','reasons','reasons_short','explanation','plain_explanation','why','final_reason','raw_reason'],'whale':['whale','whale_state','anomaly','anomaly_state'],'queue_state':['queue_state','state','position_state','status','classification'],'updated_at':['updated_at','last_update','timestamp','created_at','generated_at']}
_OVERLAY_CACHE_LOCK = threading.Lock()
_OVERLAY_CACHE: dict[str, tuple[float, tuple[bool, Any, str]]] = {}
_CACHE_TTL_SECONDS = float(os.environ.get('RLDC_OVERLAY_CACHE_TTL', '2.0') or 2.0)
_HEAVY_CACHE_TTL_SECONDS = float(os.environ.get('RLDC_OVERLAY_HEAVY_CACHE_TTL', '8.0') or 8.0)
_SYMBOL_RESOLVE_CACHE_LOCK = threading.Lock()
_SYMBOL_RESOLVE_CACHE: dict[str, tuple[float, str]] = {}
_SYMBOL_RESOLVE_TTL_SECONDS = float(os.environ.get('RLDC_OVERLAY_SYMBOL_RESOLVE_TTL', '45.0') or 45.0)
_MIN_POSITION_VALUE_EUR = float(os.environ.get('RLDC_OVERLAY_MIN_POSITION_VALUE_EUR', '2.0') or 2.0)

# Last-known-good state cache — zwraca stale data zamiast timeout gdy backend wolny
_STATE_CACHE_LOCK = threading.Lock()
_STATE_CACHE_RESULT: dict | None = None
_STATE_CACHE_TS: float = 0.0
_STATE_RESULT_TTL = float(os.environ.get('RLDC_OVERLAY_RESULT_TTL', '3.0') or 3.0)
_STATE_STALE_TTL = float(os.environ.get('RLDC_OVERLAY_STALE_TTL', '120.0') or 120.0)


def _cache_ttl_for_path(path: str) -> float:
    if 'market-scan' in path or 'final-decisions' in path:
        return _HEAVY_CACHE_TTL_SECONDS
    return _CACHE_TTL_SECONDS


def get_json(path, timeout=None, use_cache=True):
    req_timeout=TIMEOUT if timeout is None else timeout
    now=time.time()
    if use_cache:
        with _OVERLAY_CACHE_LOCK:
            cached=_OVERLAY_CACHE.get(path)
            if cached and (now-cached[0]) <= _cache_ttl_for_path(path):
                return cached[1]
    try:
        with urllib.request.urlopen(urllib.request.Request(BACKEND+path,headers={'Accept':'application/json'}),timeout=req_timeout) as r:
            result=(True,json.loads(r.read().decode('utf-8','replace')),'ok')
    except urllib.error.HTTPError as e:
        result=(False,None,f'http_{e.code}')
    except Exception as e:
        result=(False,None,f'error:{e}')
    if use_cache:
        with _OVERLAY_CACHE_LOCK:
            _OVERLAY_CACHE[path]=(now,result)
    return result
def fetch_direct(path, timeout=None):
    ok,data,_=get_json(path, timeout=timeout, use_cache=True)
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
def text(v):
    if v is None: return None
    if isinstance(v,list):
        parts=[text(x) for x in v]
        parts=[x for x in parts if x]
        return '; '.join(parts) if parts else None
    if isinstance(v,dict):
        for key in ('plain','short','message','reason','text','label'):
            if key in v:
                t=text(v.get(key))
                if t: return t
        return json.dumps(v,ensure_ascii=False,separators=(',',':'))
    s=str(v).strip()
    return s if s else None
def fl(v):
    if v is None: return None
    if isinstance(v,(int,float)): return float(v)
    if isinstance(v,dict):
        vals=[fl(v.get(k)) for k in ('price','value','min','max','lower','upper')]
        vals=[x for x in vals if x is not None]
        return (sum(vals)/len(vals)) if vals else None
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
def base_symbol(symbol):
    s=nsym(symbol) or ''
    for q in ('USDC','USDT','BUSD','FDUSD','TUSD','EUR','BTC','ETH'):
        if s.endswith(q) and len(s)>len(q):
            return s[:-len(q)]
    return s
def quote_symbol(symbol):
    s=nsym(symbol) or ''
    for q in ('USDC','USDT','BUSD','FDUSD','TUSD','EUR','BTC','ETH'):
        if s.endswith(q) and len(s)>len(q):
            return q
    return ''
def prefer_symbol(current, candidate):
    cur=nsym(current)
    cand=nsym(candidate)
    if not cur: return cand
    if not cand: return cur
    order={'USDC':5,'USDT':4,'EUR':3,'BTC':2,'ETH':2}
    return cand if order.get(quote_symbol(cand),0)>order.get(quote_symbol(cur),0) else cur
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
            if v is not None:
                tv=text(v)
                if tv is not None: out[name]=tv
    for name,keys in NUM.items():
        v=fl(first(row,keys))
        if v is not None: out[name]=v
    out['history']=hist(row); out['forecast_path']=fc(row)
    if 'price' not in out and out['history']: out['price']=out['history'][-1]
    if out.get('analysis_symbol'):
        out['chart_symbol']=nsym(out.get('analysis_symbol')) or out.get('analysis_symbol')
    if 'quote' not in out:
        for q in ['USDC','USDT','EUR','BTC','ETH']:
            if s.endswith(q): out['quote']=q; break
    if 'action' not in out: out['action']='hold' if 'position' in str(out.get('queue_state','')).lower() else 'wait'
    if 'plain_summary' not in out:
        out['plain_summary']=plain_row_summary(out)
    return out
def plain_action_label(action):
    a=str(action or '').strip().lower()
    if a in {'buy','kup','kupno','entry','enter'}: return 'kup'
    if a in {'sell','sprzedaj','sprzedaż','exit','close'}: return 'sprzedaj'
    if a in {'hold','trzymaj'}: return 'trzymaj'
    if a in {'skip','blocked','block','zablokowane','no_trade','brak danych'}: return 'nie wchodź'
    return 'czekaj'
def plain_row_summary(row):
    symbol=str(row.get('symbol') or 'tej pary')
    action_label=plain_action_label(row.get('action'))
    pnl=row.get('pnl_pct')
    trend=str(row.get('trend') or '').strip().upper()
    bits=[f"Bot dla {symbol} mówi prosto: {action_label}."]
    if pnl is not None:
        bits.append(f"Wynik tej pozycji to około {pnl:+.2f}%.")
    if trend and trend not in {'BRAK DANYCH','NONE','NULL'}:
        if 'WZROST' in trend:
            bits.append('Cena ma przewagę w górę.')
        elif 'SPAD' in trend:
            bits.append('Cena ma przewagę w dół.')
        else:
            bits.append('Cena idzie bokiem.')
    elif row.get('history'):
        bits.append('Wykres cen jest dostępny, ale trend nie jest jeszcze pewny.')
    else:
        bits.append('Brakuje świec do pełnej oceny wykresu.')
    reason=text(row.get('reason'))
    if reason and reason not in bits[-1]:
        bits.append(reason[:180])
    return ' '.join(bits)
def decision_block(payload):
    if isinstance(payload,dict):
        data=payload.get('data')
        if isinstance(data,dict): return data
        return payload
    return {}
def merge_pair(old,new):
    merged=dict(old)
    merged['symbol']=prefer_symbol(merged.get('symbol'),new.get('symbol'))
    for key,value in new.items():
        if value in (None,'',[],{}): continue
        if key=='symbol': continue
        if key=='action':
            if merged.get('action') in (None,'','wait','hold') and new.get('reason'):
                merged[key]=value
            continue
        if key in {'history','forecast_path'}:
            if len(value)>len(merged.get(key,[]) or []): merged[key]=value
            continue
        if key in {'price','entry','target','stop'}:
            if merged.get(key) in (None,'') or quote_symbol(new.get('symbol'))==quote_symbol(merged.get('symbol')):
                merged[key]=value
            continue
        if merged.get(key) in (None,'',[],{}):
            merged[key]=value
    merged['quote']=quote_symbol(merged.get('symbol')) or merged.get('quote')
    merged['chart_symbol']=prefer_symbol(merged.get('chart_symbol') or merged.get('analysis_symbol') or merged.get('symbol'),new.get('chart_symbol') or new.get('analysis_symbol'))
    reason=text(merged.get('reason'))
    merged['plain_summary']=reason if reason and 'Bot mówi' in reason else plain_row_summary(merged)
    return merged
def useful_pair(row):
    if row.get('price') is not None or row.get('entry') is not None or row.get('pnl_pct') is not None:
        return True
    if row.get('target') is not None or row.get('stop') is not None or row.get('history'):
        return True
    state=str(row.get('queue_state') or '').upper()
    return state in {'IN_POSITION','FULL_TRADING_POSITION','ENTRY_READY','WATCHING','SETUP_FORMING'}
def collect(payloads):
    # Kanoniczny fallback: final-decisions daje decyzje/score nawet gdy safe-live-state ma tylko pozycje.
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        decisions=payload.get('decisions')
        if not isinstance(decisions, list):
            continue
        for item in decisions:
            if not isinstance(item, dict):
                continue
            symbol=nsym(item.get('symbol'))
            if not symbol:
                continue
            analysis=item.get('symbol_analysis') if isinstance(item.get('symbol_analysis'), dict) else {}
            position=item.get('position_state') if isinstance(item.get('position_state'), dict) else {}
            synthetic={
                'symbol': symbol,
                'action': text(item.get('final_action_pl') or item.get('final_action') or analysis.get('signal_type')),
                'confidence': fl(analysis.get('confidence')),
                'score': fl(analysis.get('score')),
                'trend': text(analysis.get('trend')),
                'price': fl(position.get('current_price')) or fl(analysis.get('price')),
                'entry': fl(position.get('entry_price')),
                'target': fl(position.get('planned_tp')),
                'stop': fl(position.get('planned_sl')),
                'pnl_pct': fl(position.get('pnl_pct')),
                'queue_state': text(item.get('final_action')),
                'reason': text(item.get('final_reason') or analysis.get('raw_reason')),
            }
            payloads.append(synthetic)

    rows=[]
    for p in payloads:
        for it in walk(p):
            if isinstance(it,dict) and nsym(first(it,TXT['symbol'])):
                if any(k in it for kk in NUM.values() for k in kk) or any(k in it for kk in TXT.values() for k in kk if k!='symbol'):
                    q=pair(it)
                    if q and useful_pair(q): rows.append(q)
    by={}
    for p in rows:
        key=base_symbol(p.get('symbol'))
        old=by.get(key)
        by[key]=merge_pair(old,p) if old else p
    rows=list(by.values())
    rows.sort(key=lambda p:(0 if str(p.get('action','')).lower() in {'buy','sell','kup','sprzedaj','entry','exit'} else 1,-abs(float(p.get('pnl_pct') or p.get('change_pct') or 0))))
    return rows
def _klines_from_db(symbol: str, tf: str, limit: int = 120) -> list[float]:
    """Odczyt klines bezpośrednio z SQLite — omija HTTP i threadpool starvation backendu."""
    if not os.path.exists(_DB_PATH):
        return []
    try:
        con=sqlite3.connect(_DB_PATH, timeout=3, check_same_thread=False)
        con.execute('PRAGMA query_only=ON')
        cur=con.execute(
            'SELECT close FROM klines WHERE symbol=? AND timeframe=? ORDER BY open_time DESC LIMIT ?',
            (symbol, tf, limit),
        )
        rows=[r[0] for r in cur.fetchall()]
        con.close()
        vals=[]
        for v in reversed(rows):
            try: vals.append(float(v))
            except (TypeError, ValueError): pass
        return vals
    except Exception:
        return []


def _symbol_has_klines(symbol: str) -> bool:
    if not symbol or not os.path.exists(_DB_PATH):
        return False
    try:
        con=sqlite3.connect(_DB_PATH, timeout=2, check_same_thread=False)
        con.execute('PRAGMA query_only=ON')
        cur=con.execute(
            'SELECT 1 FROM klines WHERE symbol=? LIMIT 1',
            (symbol,),
        )
        row=cur.fetchone()
        con.close()
        return bool(row)
    except Exception:
        return False


def _resolve_chart_symbol(symbol: str) -> str:
    normalized=nsym(symbol)
    if not normalized:
        return symbol
    now=time.time()
    with _SYMBOL_RESOLVE_CACHE_LOCK:
        cached=_SYMBOL_RESOLVE_CACHE.get(normalized)
        if cached and (now-cached[0]) <= _SYMBOL_RESOLVE_TTL_SECONDS:
            return cached[1]

    base=base_symbol(normalized)
    candidates=[normalized]
    for quote in ('USDC','USDT','FDUSD','EUR'):
        candidate=f'{base}{quote}'
        if candidate not in candidates:
            candidates.append(candidate)

    resolved=normalized
    for candidate in candidates:
        if _symbol_has_klines(candidate):
            resolved=candidate
            break

    with _SYMBOL_RESOLVE_CACHE_LOCK:
        _SYMBOL_RESOLVE_CACHE[normalized]=(now,resolved)
    return resolved

def enrich_row(row):
    source_symbol=row.get('symbol')
    symbol=row.get('chart_symbol') or row.get('analysis_symbol') or row.get('symbol')
    if not symbol:
        return row
    resolved_symbol=_resolve_chart_symbol(symbol)
    if resolved_symbol:
        symbol=resolved_symbol
        row['chart_symbol']=symbol
    decision=decision_block(fetch_direct(f'/api/signals/{symbol}/decision-view?mode=live', timeout=DECISION_TIMEOUT))
    if decision:
        action_value=first(decision,['recommended_action_label','public_action','primary_cta','final_signal'])
        if action_value is not None:
            row['action']=text(action_value)
        confidence=fl(first(decision,['final_confidence','overall_decision_confidence','direction_confidence']))
        if confidence is not None:
            row['confidence']=confidence
        reason=text(first(decision,['plain_reason','plain_explanation','final_signal_reason']))
        if reason:
            row['reason']=reason
            row['plain_summary']=reason
        indicators=decision.get('indicators') if isinstance(decision.get('indicators'),dict) else {}
        trend=text(first(indicators,['trend']))
        if trend:
            row['trend']=trend
        # Wyciągnij wskaźniki techniczne dla frontendu
        for ind_key in ('rsi','atr','ema_cross','boll_position','macd_signal'):
            val=indicators.get(ind_key)
            if val is not None and ind_key not in row:
                row[ind_key]=val
        position=decision.get('position') if isinstance(decision.get('position'),dict) else {}
        if row.get('entry') is None:
            entry=fl(first(position,['entry_price']))
            if entry is not None:
                row['entry']=entry
        cta=decision.get('cta') if isinstance(decision.get('cta'),dict) else {}
        target=fl(first(cta,['take_profit'])) or fl(first(decision,['target']))
        stop=fl(first(cta,['stop_loss']))
        if target is not None:
            row['target']=target
        if stop is not None:
            row['stop']=stop
        if decision.get('has_position') is True:
            row['queue_state']='IN_POSITION'
    if not row.get('history'):
        for tf in HISTORY_TIMEFRAMES:
            # Próbuj najpierw z DB (szybko, bez HTTP), potem HTTP fallback
            history=_klines_from_db(symbol, tf, 120)
            if len(history)>=2:
                row['history']=history
                row['chart_tf']=tf
                break
        if not row.get('history'):
            # HTTP fallback gdy DB nie ma danych (np. symbol spoza collectora)
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

    # Gdy wykres jest pobrany z innej waluty quote (np. BTCUSDC dla BTCEUR),
    # przeskaluj serie do waluty symbolu wyświetlanego, aby uniknąć fałszywego obrazu.
    src_quote=quote_symbol(source_symbol)
    chart_quote=quote_symbol(symbol)
    row_price=fl(row.get('price'))
    history=row.get('history') if isinstance(row.get('history'),list) else []
    if src_quote and chart_quote and src_quote != chart_quote and row_price is not None and history:
        last_history=fl(history[-1])
        if last_history and last_history > 0:
            scale=row_price/last_history
            if 0.2 <= scale <= 5.0:
                row['history']=[round(float(v)*scale, 8) for v in history]
                if isinstance(row.get('forecast_path'), list) and row.get('forecast_path'):
                    row['forecast_path']=[round(float(v)*scale, 8) for v in row['forecast_path']]

    if not row.get('plain_summary'):
        row['plain_summary']=plain_row_summary(row)
    return row
def summary(payloads):
    keys={'total_value_eur':['total_value_eur','portfolio_value_eur','wallet_value_eur','equity_eur','equity','total_equity','balance','total_value'],'total_cost_eur':['total_cost_eur','invested_eur','invested','total_cost'],'total_pnl_eur':['total_pnl_eur','total_pnl','pnl_eur','net_pnl_eur','unrealized_pnl_eur'],'total_pnl_pct':['total_pnl_pct','equity_change_pct','pnl_pct','net_pnl_pct','roi_pct'],'positions_count':['positions_count','open_positions','valid_positions_count','open_positions_count','count'],'mode':['mode','trading_mode','environment'],'allow_new_entries':['allow_new_entries'],'reduce_only_mode':['reduce_only_mode'],'no_trade_mode':['no_trade_mode'],'market_health_mode':['market_health_mode'],'min_buy_eur':['min_buy_eur','min_buy_reference_eur','required_cash_eur'],'cash_available_eur':['cash_available_eur','free_cash','cash_available'],'best_ready_symbol':['best_ready_symbol'],'best_ready_score':['best_ready_score'],'status_pl':['status_pl']}
    res={}

    # Najpierw preferuj dane z kanonicznych endpointow statusowych
    trading_status_data=None
    runtime_activity_data=None
    full_status_data=None
    for o in payloads:
        if not isinstance(o,dict):
            continue
        d=o.get('data') if isinstance(o.get('data'),dict) else None
        if isinstance(d,dict):
            if 'available_to_trade' in d or 'blockers_count' in d:
                trading_status_data=d
            if 'collector' in d and 'market_data' in d:
                runtime_activity_data=d
            if 'live_execution_ok' in d and 'trading_mode' in d:
                full_status_data=d

    if isinstance(full_status_data,dict):
        mode=first(full_status_data,['trading_mode'])
        if mode is not None:
            res['mode']=str(mode)
        live_ok=full_status_data.get('live_execution_ok')
        if live_ok is True:
            res['bot_status']='PRACUJE'
        elif live_ok is False:
            res['bot_status']='BLOKADA'

    # Fallback z lekkiego endpointu /api/rldc/safe/live-state
    for o in payloads:
        if not isinstance(o,dict):
            continue
        if 'trading_mode' in o or 'allow_live' in o or 'execution_enabled' in o:
            mode=o.get('trading_mode')
            if mode is not None and 'mode' not in res:
                res['mode']=str(mode)
            allow_live=o.get('allow_live')
            execution_enabled=o.get('execution_enabled')
            if allow_live is False or execution_enabled is False:
                res['bot_status']='BLOKADA'
                res['allow_new_entries']=False
            elif allow_live is True and execution_enabled is True and 'bot_status' not in res:
                res['bot_status']='PRACUJE'
                if 'allow_new_entries' not in res:
                    res['allow_new_entries']=True

    if isinstance(trading_status_data,dict):
        mh=trading_status_data.get('market_health')
        if isinstance(mh,dict):
            mh_mode=first(mh,['mode'])
            if mh_mode is not None:
                res['market_health_mode']=str(mh_mode)
            allow=mh.get('allow_new_entries')
            if allow is not None:
                res['allow_new_entries']=str(allow).strip().lower() in {'1','true','yes','on'}
        for fkey in ('allow_new_entries','reduce_only_mode','no_trade_mode'):
            if fkey in trading_status_data:
                res[fkey]=str(trading_status_data.get(fkey)).strip().lower() in {'1','true','yes','on'}

    if isinstance(runtime_activity_data,dict):
        collector=runtime_activity_data.get('collector') or {}
        mh=collector.get('market_health')
        if isinstance(mh,dict):
            if 'market_health_mode' not in res:
                mh_mode=first(mh,['mode'])
                if mh_mode is not None:
                    res['market_health_mode']=str(mh_mode)
            if 'allow_new_entries' not in res and mh.get('allow_new_entries') is not None:
                res['allow_new_entries']=str(mh.get('allow_new_entries')).strip().lower() in {'1','true','yes','on'}

    # Fallback: heurystyczne mapowanie z dowolnych blokow JSON
    for o in walk(payloads):
        if isinstance(o,dict):
            blocks=[o]+[o[k] for k in ['summary','portfolio_summary','account_summary','overview','analytics','data'] if isinstance(o.get(k),dict)]
            for b in blocks:
                for out,ks in keys.items():
                    if out not in res:
                        v=first(b,ks)
                        if v is not None:
                            if out in {'mode','market_health_mode'}:
                                res[out]=str(v)
                            elif out in {'allow_new_entries','reduce_only_mode','no_trade_mode'}:
                                res[out]=str(v).strip().lower() in {'1','true','yes','on'}
                            else:
                                res[out]=fl(v)

    if 'bot_status' not in res:
        if res.get('no_trade_mode'):
            res['bot_status']='BLOKADA'
        elif res.get('reduce_only_mode'):
            res['bot_status']='TYLKO WYJSCIA'
        elif res.get('allow_new_entries') is True:
            res['bot_status']='PRACUJE'

    return res
def narr(payloads,rows):
    if rows:
        simple=text(rows[0].get('plain_summary') or rows[0].get('reason') or rows[0].get('plan'))
        if simple:
            return simple[:420]
    for o in walk(payloads):
        if isinstance(o,dict):
            t=first(o,['narration','tts_text','broadcast_text','plain_explanation','explanation','message'])
            tt=text(t)
            if tt and len(tt)>12: return tt[:420]
    return f"Bot patrzy na {rows[0]['symbol']} i czeka na pełniejsze dane." if rows else 'Brak prostego komentarza z bota. Overlay czeka na synchronizację.'


def _extract_position_rows(payloads: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for node in walk(payloads):
        if not isinstance(node, dict):
            continue
        positions = node.get('positions')
        if isinstance(positions, list):
            for item in positions:
                if isinstance(item, dict):
                    rows.append(item)
    return rows


def _is_countable_position(pos: dict) -> bool:
    symbol = nsym(first(pos, ['symbol', 'pair', 'market']))
    if not symbol:
        return False
    qty = fl(first(pos, ['qty', 'quantity', 'position_qty'])) or 0.0
    if qty <= 0:
        return False
    state = str(first(pos, ['state', 'position_state', 'source']) or '').lower()
    if 'dust' in state:
        return False
    price = fl(first(pos, ['current_price', 'price', 'mark_price', 'last_price']))
    notional = (qty * price) if (price is not None and price > 0) else None
    if notional is not None and notional < _MIN_POSITION_VALUE_EUR:
        return False
    return True


def _count_positions_from_payloads(payloads: list[dict]) -> int | None:
    positions = _extract_position_rows(payloads)
    if not positions:
        return None
    symbols = {
        nsym(first(pos, ['symbol', 'pair', 'market']))
        for pos in positions
        if _is_countable_position(pos)
    }
    symbols.discard(None)
    return len(symbols)


def _estimate_total_value_eur(payloads: list[dict]) -> float | None:
    total = 0.0
    seen_any = False
    for pos in _extract_position_rows(payloads):
        if not _is_countable_position(pos):
            continue
        qty = fl(first(pos, ['qty', 'quantity', 'position_qty'])) or 0.0
        price = fl(first(pos, ['current_price', 'price', 'mark_price', 'last_price'])) or 0.0
        if qty > 0 and price > 0:
            total += qty * price
            seen_any = True
    return total if seen_any else None


def _compute_live_state() -> dict:
    statuses={}; payloads=[]
    max_workers=min(4,max(1,len(ENDPOINTS)))
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
    # Równoległy enrich — zamiast sekwencyjnego [enrich_row(r) for r in rows[:N]]
    to_enrich=rows[:ENRICH_ROWS]; rest=rows[ENRICH_ROWS:]
    if to_enrich:
        max_e=min(4,len(to_enrich))
        with ThreadPoolExecutor(max_workers=max_e) as epool:
            efutures=[epool.submit(enrich_row,dict(r)) for r in to_enrich]
            enriched=[]
            for original,ef in zip(to_enrich,efutures):
                try: enriched.append(ef.result())
                except Exception: enriched.append(original)
        rows=enriched+rest
    summ=summary(payloads)
    payload_positions_count=_count_positions_from_payloads(payloads)
    if payload_positions_count is not None:
        summ['positions_count']=payload_positions_count
    if ('total_value_eur' not in summ) or ((fl(summ.get('total_value_eur')) or 0.0) <= 0.0):
        estimated_total=_estimate_total_value_eur(payloads)
        if estimated_total is not None:
            summ['total_value_eur']=round(estimated_total, 6)

    if 'positions_count' not in summ and rows:
        open_rows=0
        for row in rows:
            state=str(row.get('queue_state') or '').lower()
            qty=fl(row.get('quantity')) or 0.0
            entry=fl(row.get('entry')) or 0.0
            if 'dust' in state:
                continue
            if qty <= 0:
                continue
            if ('position' in state) or state in {'binance_spot','in_position'} or entry > 0:
                open_rows += 1
        summ['positions_count']=open_rows
    ok_any=bool(payloads); partial=ok_any and (not rows or any(v!='ok' for v in statuses.values()))
    warn=''
    if not ok_any: warn=f'Brak odpowiedzi JSON z backendu RLdC {BACKEND}. Sprawdź, czy FastAPI działa na :8000 albo ustaw RLDC_BACKEND_URL.'
    elif not rows: warn='Backend odpowiada, ale adapter nie znalazł aktywnych par/pozycji z polem symbol. Dane overlayu są niekompletne.'
    elif partial: warn='Część endpointów backendu nie odpowiedziała lub nie istnieje. Overlay pokazuje tylko dostępne dane.'
    market_health_mode=str(summ.get('market_health_mode','UNKNOWN') or 'UNKNOWN').upper()
    allow_new_entries=bool(summ.get('allow_new_entries',True))
    reduce_only_mode=bool(summ.get('reduce_only_mode',False))
    no_trade_mode=bool(summ.get('no_trade_mode',False))
    if market_health_mode == 'NO_TRADE':
        no_trade_mode=True; allow_new_entries=False
    elif market_health_mode == 'REDUCE_ONLY':
        reduce_only_mode=True; allow_new_entries=False
    trading_guard={
        'market_health_mode':market_health_mode,
        'allow_new_entries':allow_new_entries,
        'reduce_only_mode':reduce_only_mode,
        'no_trade_mode':no_trade_mode,
    }
    return {'ok':ok_any and bool(rows),'partial':partial or not bool(rows),'warning':warn,'source':'RLdC backend adapter','backend_url':BACKEND,'fetched_at':time.time(),'summary':summ,'trading_guard':trading_guard,'active_pairs':rows,'queue':rows,'narration':narr(payloads,rows),'endpoint_status':statuses}

def live_state() -> dict:
    """Zwraca stan live z cache last-known-good; oblicza świeży stan tylko gdy cache wygasł."""
    global _STATE_CACHE_RESULT, _STATE_CACHE_TS
    now=time.time()
    with _STATE_CACHE_LOCK:
        if _STATE_CACHE_RESULT is not None and (now-_STATE_CACHE_TS) < _STATE_RESULT_TTL:
            return dict(_STATE_CACHE_RESULT)
    try:
        result=_compute_live_state()
        with _STATE_CACHE_LOCK:
            _STATE_CACHE_RESULT=result
            _STATE_CACHE_TS=time.time()
        return result
    except Exception as exc:
        with _STATE_CACHE_LOCK:
            age=now-_STATE_CACHE_TS if _STATE_CACHE_RESULT else _STATE_STALE_TTL+1
            if _STATE_CACHE_RESULT is not None and age < _STATE_STALE_TTL:
                stale=dict(_STATE_CACHE_RESULT)
                stale['partial']=True; stale['stale']=True
                stale['warning']=f'Dane z ostatniego poprawnego stanu (wiek {age:.0f}s). Backend chwilowo nie odpowiada: {exc}'
                return stale
        return {'ok':False,'partial':True,'stale':True,'warning':f'Backend nie odpowiada i brak poprzedniego stanu: {exc}','source':'RLdC backend adapter','backend_url':BACKEND,'fetched_at':now,'summary':{},'trading_guard':{},'active_pairs':[],'queue':[],'narration':'Overlay nie ma połączenia z backendem.','endpoint_status':{}}
class H(SimpleHTTPRequestHandler):
    def log_message(self,*a):
        if os.environ.get('RLDC_OVERLAY_VERBOSE')=='1': super().log_message(*a)
    def do_GET(self):
        try:
            p=urlparse(self.path)
            if p.path=='/overlay/api/live-state': return self.send_json(live_state())
            if p.path.startswith('/api/'):
                ok,data,st=get_json(p.path+('?'+p.query if p.query else ''), use_cache=False)
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
