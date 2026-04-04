'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { getAdminToken, getApiBase, withAdminToken } from '../../lib/api'

// ─────────────────────────────────────────────
// Typy
// ─────────────────────────────────────────────
interface LogEntry {
  id: number
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG' | string
  module: string
  message: string
  exception?: string | null
  timestamp?: string | null
  type?: string
}

interface SystemStatus {
  uptime: string
  trading_mode: string
  regime?: { regime: string; buy_blocked: boolean; buy_confidence_adj: number; reason: string } | null
  collector: { running: boolean; status: string; watchlist_size: number; last_tick_ts?: string }
  database: { connected: boolean; log_count?: number }
  ai: { openai_enabled: boolean; provider: string }
  binance: { connected?: boolean; status: string }
  telegram: { configured: boolean; status: string }
  last_log?: { level: string; module: string; message: string; timestamp?: string } | null
  timestamp: string
}

interface PublicUrlInfo {
  public_url: string | null
  lan_url: string
  source: string
  mode: string
  status: string
  warning?: string
}

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  provider?: string
  timestamp: string
}

interface ActionResult {
  success: boolean
  action: string
  message: string
  data?: unknown
  timestamp: string
}

interface TraceSymbol {
  symbol: string
  reason_code: string
  reason_pl: string
  trace_age_seconds: number
  has_position: boolean
  has_pending: boolean
  pending_status: string | null
  signal_type: string
  signal_confidence: number
  signal_age_seconds: number
  details?: {
    signal_summary?: Record<string, unknown>
    risk_check?: Record<string, unknown>
    cost_check?: Record<string, unknown>
    execution_check?: Record<string, unknown>
  }
}

interface TraceData {
  symbols: TraceSymbol[]
  mode: string
  window_minutes: number
  summary: Record<string, unknown>
}

interface OperatorDecisionItem {
  id: number
  symbol: string
  action_type: string
  reason_code: string
  plan_status?: string | null
  action?: string | null
  break_even_price?: number | null
  expected_net_profit?: number | null
  confidence_score?: number | null
  risk_score?: number | null
  requires_revision?: boolean
  invalidation_reason?: string | null
  timestamp?: string | null
}

interface OperatorDecisionSection {
  count: number
  blocked_count: number
  revision_required_count: number
  negative_expected_net_count: number
  items: OperatorDecisionItem[]
}

interface OperatorConsoleBundle {
  generated_at: string
  sections: {
    decision_intelligence?: OperatorDecisionSection
  } & Record<string, unknown>
}

type TabId = 'status' | 'actions' | 'logs' | 'decisions' | 'chat' | 'terminal'

interface TermLine {
  text: string
  type: 'output' | 'info' | 'error'
  ts: number
}

// ─────────────────────────────────────────────
// Stałe
// ─────────────────────────────────────────────
const LOG_LEVEL_COLORS: Record<string, string> = {
  INFO: 'text-sky-400',
  WARNING: 'text-amber-400',
  ERROR: 'text-red-400',
  DEBUG: 'text-slate-500',
  SUCCESS: 'text-emerald-400',
}

const LOG_LEVEL_BG: Record<string, string> = {
  INFO: 'bg-sky-950/20',
  WARNING: 'bg-amber-950/20',
  ERROR: 'bg-red-950/30',
  DEBUG: '',
}

// Filtry modułów logów
const LOG_MODULE_TAGS: { id: string; label: string; match: string[] }[] = [
  { id: '', label: 'WSZYSTKO', match: [] },
  { id: 'TRADE', label: 'TRADE', match: ['collector', 'entry', 'exit', 'order', 'position', 'trade', 'pending'] },
  { id: 'AI', label: 'AI', match: ['ai', 'gemini', 'groq', 'openai', 'heuristic', 'analysis', 'signal'] },
  { id: 'BINANCE', label: 'BINANCE', match: ['binance', 'api'] },
  { id: 'TELEGRAM', label: 'TELEGRAM', match: ['telegram', 'bot'] },
  { id: 'RISK', label: 'RISK', match: ['risk', 'gate', 'drawdown', 'kill'] },
  { id: 'SYS', label: 'SYS', match: ['system', 'startup', 'database', 'runtime', 'operator'] },
  { id: 'ERR', label: 'ERR', match: [] },
]

const QUICK_ACTIONS = [
  { id: 'analyze-now', label: 'Analizuj teraz', icon: '⚡', color: 'border-sky-700/50 hover:border-sky-500' },
  { id: 'scan-opportunities', label: 'Szukaj okazji', icon: '🔍', color: 'border-emerald-700/50 hover:border-emerald-500' },
  { id: 'recompute-signals', label: 'Przelicz sygnały', icon: '📊', color: 'border-violet-700/50 hover:border-violet-500' },
  { id: 'check-positions', label: 'Sprawdź pozycje', icon: '💼', color: 'border-teal-700/50 hover:border-teal-500' },
  { id: 'check-sl-tp', label: 'Sprawdź SL/TP', icon: '🛡', color: 'border-orange-700/50 hover:border-orange-500' },
  { id: 'check-errors', label: 'Sprawdź błędy', icon: '🚨', color: 'border-red-700/50 hover:border-red-500' },
  { id: 'restart-collector', label: 'Restart collectora', icon: '🔄', color: 'border-amber-700/50 hover:border-amber-500' },
  { id: 'generate-report', label: 'Generuj raport', icon: '📋', color: 'border-slate-600/50 hover:border-slate-400' },
  { id: 'check-binance', label: 'Test Binance', icon: '🏦', color: 'border-yellow-700/50 hover:border-yellow-500' },
  { id: 'check-telegram', label: 'Test Telegram', icon: '✈️', color: 'border-blue-700/50 hover:border-blue-500' },
  { id: 'check-ai', label: 'Test AI', icon: '🤖', color: 'border-pink-700/50 hover:border-pink-500' },
  { id: 'force-sync', label: 'Wymuś sync', icon: '🔃', color: 'border-indigo-700/50 hover:border-indigo-500' },
  { id: 'save-snapshot', label: 'Zapisz snapshot', icon: '📸', color: 'border-cyan-700/50 hover:border-cyan-500' },
]

const AI_SUGGESTIONS = [
  'dlaczego bot nie otwiera pozycji?',
  'dlaczego sprzedał? przeanalizuj exit',
  'sprawdź ostatnie błędy systemu',
  'przeanalizuj ostatnie sygnały',
  'co blokuje wejście na rynek?',
  'sprawdź SL/TP — które pozycje zagrożone?',
  'status wszystkich modułów systemu',
  'oceń jakość sygnałów — czy edge jest wystarczający?',
]

// ─────────────────────────────────────────────
// Główny komponent
// ─────────────────────────────────────────────
export default function ControlCenter() {
  const [activeTab, setActiveTab] = useState<TabId>('status')
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [publicUrl, setPublicUrl] = useState<PublicUrlInfo | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [logFilter, setLogFilter] = useState('')
  const [logLevelFilter, setLogLevelFilter] = useState('')
  const [logModuleTag, setLogModuleTag] = useState('')
  const [logPaused, setLogPaused] = useState(false)
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [actionResults, setActionResults] = useState<Record<string, ActionResult | null>>({})
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})
  const [statusLoading, setStatusLoading] = useState(true)
  const [adminTokenSet, setAdminTokenSet] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [tokenSaved, setTokenSaved] = useState(false)
  const [traceData, setTraceData] = useState<TraceData | null>(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const [expandedSymbols, setExpandedSymbols] = useState<Set<string>>(new Set())
  const [traceActionFilter, setTraceActionFilter] = useState('')
  const [operatorConsole, setOperatorConsole] = useState<OperatorConsoleBundle | null>(null)

  // ── Terminal state
  const [termLines, setTermLines] = useState<TermLine[]>([])
  const [termInput, setTermInput] = useState('')
  const [termConnected, setTermConnected] = useState(false)
  const [termHistory, setTermHistory] = useState<string[]>([])
  const [termHistoryIdx, setTermHistoryIdx] = useState(-1)

  const logsEndRef = useRef<HTMLDivElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const termEndRef = useRef<HTMLDivElement>(null)
  const termInputRef = useRef<HTMLInputElement>(null)
  const sseRef = useRef<EventSource | null>(null)
  const wsTermRef = useRef<WebSocket | null>(null)

  // ── ANSI stripping helper
  const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*[A-Za-z]/g, '').replace(/\x1b[A-Za-z]/g, '')

  const apiBase = getApiBase()

  // ─── Token management
  useEffect(() => {
    setAdminTokenSet(!!getAdminToken())
  }, [])

  // ─── Terminal WebSocket
  useEffect(() => {
    if (activeTab !== 'terminal') {
      if (wsTermRef.current) {
        wsTermRef.current.close()
        wsTermRef.current = null
        setTermConnected(false)
      }
      return
    }
    const token = getAdminToken() || ''
    const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost'
    const wsUrl = `ws://${host}:8000/ws/terminal?token=${encodeURIComponent(token)}&cols=220&rows=50`
    const ws = new WebSocket(wsUrl)
    wsTermRef.current = ws

    ws.onopen = () => {
      setTermConnected(true)
      setTermLines((prev) => [
        ...prev,
        { text: '● Połączono z terminalem.', type: 'info', ts: Date.now() },
      ])
    }
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string)
        if (msg.type === 'output') {
          const cleaned = stripAnsi(msg.data as string)
          setTermLines((prev) => [...prev.slice(-3000), { text: cleaned, type: 'output', ts: Date.now() }])
        } else if (msg.type === 'ready') {
          setTermLines((prev) => [...prev, { text: msg.message as string, type: 'info', ts: Date.now() }])
        } else if (msg.type === 'exit') {
          setTermLines((prev) => [
            ...prev,
            { text: `Shell zakończył pracę (kod ${msg.code}).`, type: 'info', ts: Date.now() },
          ])
          setTermConnected(false)
        } else if (msg.type === 'error') {
          setTermLines((prev) => [
            ...prev,
            { text: `BŁĄD: ${msg.message}`, type: 'error', ts: Date.now() },
          ])
        }
      } catch {
        // raw text fallback
        setTermLines((prev) => [...prev.slice(-3000), { text: stripAnsi(e.data as string), type: 'output', ts: Date.now() }])
      }
    }
    ws.onclose = () => {
      setTermConnected(false)
      setTermLines((prev) => [
        ...prev,
        { text: '● Połączenie zamknięte.', type: 'info', ts: Date.now() },
      ])
      wsTermRef.current = null
    }
    ws.onerror = () => {
      setTermLines((prev) => [
        ...prev,
        { text: '✗ Błąd WebSocket — sprawdź czy backend jest uruchomiony i token jest poprawny.', type: 'error', ts: Date.now() },
      ])
    }
    return () => {
      ws.close()
      wsTermRef.current = null
      setTermConnected(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  // ─── Terminal auto-scroll
  useEffect(() => {
    termEndRef.current?.scrollIntoView({ behavior: 'auto' })
  }, [termLines])

  const termSendInput = useCallback((raw: string) => {
    const ws = wsTermRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'input', data: raw }))
  }, [])

  const termSubmit = useCallback(() => {
    const cmd = termInput
    if (!cmd) return
    termSendInput(cmd + '\n')
    setTermHistory((prev) => [cmd, ...prev.slice(0, 99)])
    setTermHistoryIdx(-1)
    setTermInput('')
  }, [termInput, termSendInput])

  const termKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      termSubmit()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setTermHistoryIdx((idx) => {
        const next = Math.min(idx + 1, termHistory.length - 1)
        if (termHistory[next] !== undefined) setTermInput(termHistory[next])
        return next
      })
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setTermHistoryIdx((idx) => {
        const next = Math.max(idx - 1, -1)
        if (next === -1) setTermInput('')
        else if (termHistory[next] !== undefined) setTermInput(termHistory[next])
        return next
      })
    } else if (e.key === 'c' && e.ctrlKey) {
      // Ctrl+C
      termSendInput('\x03')
    } else if (e.key === 'l' && e.ctrlKey) {
      // Ctrl+L — clear local
      e.preventDefault()
      setTermLines([])
    }
  }, [termSubmit, termHistory, termSendInput])

  const saveToken = useCallback(() => {
    const t = tokenInput.trim()
    if (!t) return
    if (typeof window !== 'undefined') localStorage.setItem('rldc_admin_token', t)
    setAdminTokenSet(true)
    setTokenInput('')
    setTokenSaved(true)
    setTimeout(() => setTokenSaved(false), 2500)
  }, [tokenInput])

  const clearToken = useCallback(() => {
    if (typeof window !== 'undefined') localStorage.removeItem('rldc_admin_token')
    setAdminTokenSet(false)
  }, [])

  // ─── Load system status
  const loadStatus = useCallback(async () => {
    try {
      setStatusLoading(true)
      const [statusRes, urlRes, consoleRes] = await Promise.all([
        fetch(`${apiBase}/api/system/status`, { headers: withAdminToken() }),
        fetch(`${apiBase}/api/system/public-url`),
        fetch(`${apiBase}/api/account/analytics/console`, { headers: withAdminToken() }),
      ])
      if (statusRes.ok) setSystemStatus(await statusRes.json())
      if (urlRes.ok) {
        const data = await urlRes.json()
        setPublicUrl(data.data)
      }
      if (consoleRes.ok) {
        const data = await consoleRes.json()
        setOperatorConsole(data.data)
      }
    } catch {
      // ignore
    } finally {
      setStatusLoading(false)
    }
  }, [apiBase])

  useEffect(() => {
    loadStatus()
    const interval = setInterval(loadStatus, 15000)
    return () => clearInterval(interval)
  }, [loadStatus])

  // ─── Load decision trace
  const loadTrace = useCallback(async () => {
    setTraceLoading(true)
    try {
      const res = await fetch(`${apiBase}/api/signals/execution-trace?limit=50`, {
        headers: withAdminToken(),
      })
      if (res.ok) {
        const data = await res.json()
        setTraceData(data)
      }
    } catch {
      // ignore
    } finally {
      setTraceLoading(false)
    }
  }, [apiBase])

  useEffect(() => {
    if (activeTab !== 'decisions') return
    loadTrace()
    const interval = setInterval(loadTrace, 30000)
    return () => clearInterval(interval)
  }, [activeTab, loadTrace])

  const toggleExpand = useCallback((symbol: string) => {
    setExpandedSymbols((prev) => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }, [])

  // ─── SSE log stream
  useEffect(() => {
    if (activeTab !== 'logs') {
      sseRef.current?.close()
      sseRef.current = null
      return
    }
    const params = new URLSearchParams()
    if (logLevelFilter) params.set('level', logLevelFilter)
    const url = `${apiBase}/api/system/logs/stream?${params.toString()}`
    const es = new EventSource(url)
    sseRef.current = es

    es.onmessage = (e) => {
      if (logPaused) return
      try {
        const data: LogEntry = JSON.parse(e.data)
        if (data.type === 'connected') return
        setLogs((prev) => [...prev.slice(-999), data])
      } catch {
        // ignore parse errors
      }
    }
    es.onerror = () => {
      es.close()
    }
    return () => {
      es.close()
      sseRef.current = null
    }
  }, [activeTab, logLevelFilter, apiBase, logPaused])

  // Filtrowanie logów po stronie klienta
  const filteredLogs = logs.filter((log) => {
    if (logFilter && !log.message?.toLowerCase().includes(logFilter.toLowerCase())
      && !log.module?.toLowerCase().includes(logFilter.toLowerCase())) return false
    if (logModuleTag) {
      const tag = LOG_MODULE_TAGS.find((t) => t.id === logModuleTag)
      if (tag) {
        const modLow = (log.module || '').toLowerCase()
        const msgLow = (log.message || '').toLowerCase()
        if (logModuleTag === 'ERR') {
          if (!['ERROR', 'WARNING'].includes(log.level)) return false
        } else if (tag.match.length > 0) {
          if (!tag.match.some((m) => modLow.includes(m) || msgLow.includes(m))) return false
        }
      }
    }
    return true
  })

  // ─── Auto-scroll logs
  useEffect(() => {
    if (!logPaused) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, logPaused])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  // ─── Quick action
  const runAction = useCallback(async (actionId: string) => {
    setActionLoading((prev) => ({ ...prev, [actionId]: true }))
    try {
      const res = await fetch(`${apiBase}/api/actions/${actionId}`, {
        method: 'POST',
        headers: withAdminToken({ 'Content-Type': 'application/json' }),
      })
      const data: ActionResult = await res.json()
      setActionResults((prev) => ({ ...prev, [actionId]: data }))
    } catch (err) {
      setActionResults((prev) => ({
        ...prev,
        [actionId]: {
          success: false,
          action: actionId,
          message: `Błąd: ${String(err).slice(0, 150)}`,
          timestamp: new Date().toISOString(),
        },
      }))
    } finally {
      setActionLoading((prev) => ({ ...prev, [actionId]: false }))
    }
  }, [apiBase])

  // ─── AI Chat
  const sendChat = useCallback(async (message: string) => {
    if (!message.trim()) return
    const userMsg: ChatMsg = { role: 'user', content: message, timestamp: new Date().toISOString() }
    setChatMessages((prev) => [...prev, userMsg])
    setChatInput('')
    setChatLoading(true)
    try {
      const res = await fetch(`${apiBase}/api/actions/ai/chat`, {
        method: 'POST',
        headers: withAdminToken({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ message }),
      })
      const data = await res.json()
      const assistantMsg: ChatMsg = {
        role: 'assistant',
        content: data.response || data.detail || 'Brak odpowiedzi.',
        provider: data.provider,
        timestamp: data.timestamp || new Date().toISOString(),
      }
      setChatMessages((prev) => [...prev, assistantMsg])
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Błąd: ${String(err).slice(0, 200)}`, timestamp: new Date().toISOString() },
      ])
    } finally {
      setChatLoading(false)
    }
  }, [apiBase])

  // ─────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full bg-[#0b0f18] text-slate-300 font-mono text-sm min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-[#0d1320] shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-emerald-400 font-bold tracking-wider text-xs">⬡ CONTROL CENTER</span>
          {systemStatus && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${
              systemStatus.trading_mode === 'live'
                ? 'border-amber-500/40 text-amber-400 bg-amber-950/30'
                : 'border-emerald-600/40 text-emerald-400 bg-emerald-950/30'
            }`}>
              {systemStatus.trading_mode.toUpperCase()}
            </span>
          )}
          {systemStatus && (
            <span className="text-[10px] text-slate-500">uptime: {systemStatus.uptime}</span>
          )}
          {systemStatus?.regime?.regime && (
            <span className={`text-[10px] px-2 py-0.5 rounded border font-bold ${
              systemStatus.regime.buy_blocked
                ? 'border-red-700/40 text-red-400 bg-red-950/20'
                : 'border-emerald-700/40 text-emerald-400 bg-emerald-950/20'
            }`}>
              {systemStatus.regime.regime}
            </span>
          )}
        </div>
        <button
          onClick={loadStatus}
          className="text-[10px] text-slate-500 hover:text-slate-300 border border-slate-700 px-2 py-0.5 rounded"
        >
          ↻ odśwież
        </button>
        <span className={`text-[10px] px-2 py-0.5 rounded border font-semibold ${
          adminTokenSet
            ? 'border-emerald-700/40 text-emerald-400 bg-emerald-950/20'
            : 'border-red-700/40 text-red-400 bg-red-950/20'
        }`}>
          {adminTokenSet ? '🔑 auth' : '🔒 brak tokenu'}
        </span>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800 bg-[#0d1320] shrink-0 overflow-x-auto">
        {(
          [
            { id: 'status', label: 'Status', icon: '◉' },
            { id: 'actions', label: 'Akcje', icon: '▶' },
            { id: 'logs', label: 'Live logi', icon: '☰' },
            { id: 'decisions', label: 'Decyzje', icon: '⊞' },
            { id: 'chat', label: 'AI Chat', icon: '◆' },
            { id: 'terminal', label: 'Terminal', icon: '▸_' },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-[11px] font-semibold tracking-wide border-b-2 transition-colors whitespace-nowrap ${
              activeTab === tab.id
                ? 'border-sky-500 text-sky-300 bg-sky-950/20'
                : 'border-transparent text-slate-500 hover:text-slate-300 hover:bg-slate-800/30'
            }`}
          >
            <span className="mr-1.5">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto min-h-0">
        {/* ── TAB: STATUS ── */}
        {activeTab === 'status' && (
          <div className="p-4 space-y-4">
            {statusLoading && !systemStatus && (
              <div className="text-slate-500 text-xs">Ładowanie statusu...</div>
            )}

            {/* Admin Token */}
            <div className={`border rounded-lg p-3 ${
              adminTokenSet
                ? 'border-emerald-700/30 bg-emerald-950/10'
                : 'border-red-700/40 bg-red-950/10'
            }`}>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2 font-semibold">
                Admin Token (X-Admin-Token)
              </div>
              {adminTokenSet ? (
                <div className="flex items-center gap-3">
                  <span className="text-emerald-400 text-xs font-semibold">✓ Token ustawiony — akcje są autoryzowane</span>
                  <button
                    onClick={clearToken}
                    className="text-[10px] px-2 py-0.5 rounded border border-red-700/40 text-red-400 hover:bg-red-950/30"
                  >
                    ✕ Usuń
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="text-amber-400/80 text-[11px]">
                    ⚠ Brak tokenu — akcje operatorskie zwrócą 401 Unauthorized
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="password"
                      placeholder="Wpisz ADMIN_TOKEN z pliku .env"
                      value={tokenInput}
                      onChange={(e) => setTokenInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') saveToken() }}
                      className="flex-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-sky-600"
                    />
                    <button
                      onClick={saveToken}
                      disabled={!tokenInput.trim()}
                      className="px-3 py-1 bg-sky-700 hover:bg-sky-600 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded text-[11px] font-semibold transition"
                    >
                      {tokenSaved ? '✓ Zapisano' : 'Zapisz'}
                    </button>
                  </div>
                  <div className="text-[10px] text-slate-600">
                    Token zapisywany w localStorage przeglądarki, nie wysyłany przez sieć bez akcji.
                  </div>
                </div>
              )}
            </div>

            {/* Public URL */}
            {publicUrl && (
              <div className="border border-slate-700/50 rounded-lg p-3 bg-slate-900/40">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2 font-semibold">Publiczny adres panelu</div>
                <div className="flex items-center gap-2 flex-wrap">
                  {publicUrl.public_url ? (
                    <a
                      href={publicUrl.public_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sky-400 hover:text-sky-300 underline text-sm font-semibold"
                    >
                      {publicUrl.public_url}
                    </a>
                  ) : (
                    <span className="text-amber-400 text-xs">Brak publicznego adresu</span>
                  )}
                  <span className={`text-[9px] px-1.5 py-0.5 rounded border font-bold ${
                    publicUrl.status === 'configured' ? 'border-emerald-600/40 text-emerald-400' :
                    publicUrl.status === 'tunnel_active' ? 'border-sky-600/40 text-sky-400' :
                    publicUrl.status === 'detected' ? 'border-amber-600/40 text-amber-400' :
                    'border-slate-600/40 text-slate-500'
                  }`}>
                    {publicUrl.status.toUpperCase().replace('_', ' ')}
                  </span>
                  <span className="text-slate-600 text-[10px]">⌂ LAN: {publicUrl.lan_url}</span>
                </div>
                {publicUrl.warning && (
                  <div className="mt-1.5 text-amber-500/80 text-[10px]">⚠ {publicUrl.warning}</div>
                )}
                <div className="mt-1 text-slate-600 text-[10px]">Źródło: {publicUrl.source}</div>
              </div>
            )}

            {/* Status grid */}
            {systemStatus && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <StatusCard
                  title="Kolektor"
                  status={systemStatus.collector.running ? 'OK' : 'STOP'}
                  ok={systemStatus.collector.running}
                  detail={`watchlist: ${systemStatus.collector.watchlist_size} symboli`}
                  sub={systemStatus.collector.last_tick_ts
                    ? `ostatni tick: ${systemStatus.collector.last_tick_ts.slice(11, 19)} UTC`
                    : undefined}
                />
                <StatusCard
                  title="Baza danych"
                  status={systemStatus.database.connected ? 'OK' : 'ERROR'}
                  ok={systemStatus.database.connected}
                  detail={systemStatus.database.log_count !== undefined ? `logów: ${systemStatus.database.log_count}` : ''}
                />
                <StatusCard
                  title="AI"
                  status={systemStatus.ai.openai_enabled ? 'OpenAI' : 'Heurystyka'}
                  ok={true}
                  detail={`provider: ${systemStatus.ai.provider}`}
                />
                <StatusCard
                  title="Binance API"
                  status={systemStatus.binance.status.toUpperCase()}
                  ok={systemStatus.binance.connected !== false && systemStatus.binance.status !== 'error'}
                  detail={systemStatus.binance.status}
                />
                <StatusCard
                  title="Telegram"
                  status={systemStatus.telegram.configured ? 'OK' : 'BRAK KONFIGURACJI'}
                  ok={systemStatus.telegram.configured}
                  detail={systemStatus.telegram.status}
                />
                <StatusCard
                  title="Tryb handlu"
                  status={systemStatus.trading_mode.toUpperCase()}
                  ok={true}
                  detail={`uptime: ${systemStatus.uptime}`}
                  highlight={systemStatus.trading_mode === 'live' ? 'amber' : 'green'}
                />
              </div>
            )}

            {/* Last log */}
            {systemStatus?.last_log && (
              <div className={`border rounded p-2.5 text-xs ${
                LOG_LEVEL_BG[systemStatus.last_log.level] || 'bg-slate-900/30'
              } border-slate-700/40`}>
                <span className="text-slate-500 text-[10px] mr-2">
                  {systemStatus.last_log.timestamp?.slice(11, 19)} UTC
                </span>
                <span className={`${LOG_LEVEL_COLORS[systemStatus.last_log.level] || 'text-slate-400'} font-bold mr-2 text-[10px]`}>
                  {systemStatus.last_log.level}
                </span>
                <span className="text-slate-500 mr-2 text-[10px]">[{systemStatus.last_log.module}]</span>
                <span className="text-slate-300">{systemStatus.last_log.message}</span>
              </div>
            )}

            {operatorConsole?.sections?.decision_intelligence && (
              <div className="border border-slate-700/40 rounded-lg bg-slate-900/30 p-3">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                    Intelligence decyzji
                  </div>
                  <div className="text-[10px] text-slate-600">
                    {operatorConsole.generated_at?.slice(11, 19)} UTC
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                  <MiniMetric
                    label="Decyzje"
                    value={String(operatorConsole.sections.decision_intelligence.count)}
                    color="text-slate-200"
                  />
                  <MiniMetric
                    label="Zablokowane"
                    value={String(operatorConsole.sections.decision_intelligence.blocked_count)}
                    color="text-amber-400"
                  />
                  <MiniMetric
                    label="Rewizje"
                    value={String(operatorConsole.sections.decision_intelligence.revision_required_count)}
                    color="text-orange-400"
                  />
                  <MiniMetric
                    label="Netto < 0"
                    value={String(operatorConsole.sections.decision_intelligence.negative_expected_net_count)}
                    color="text-red-400"
                  />
                </div>
                <div className="space-y-2">
                  {operatorConsole.sections.decision_intelligence.items.slice(0, 6).map((item) => (
                    <div key={item.id} className="rounded border border-slate-800 bg-slate-950/40 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-slate-200">{item.symbol}</span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                            item.action === 'BUY' ? 'text-emerald-400 border-emerald-700/40' :
                            item.action === 'SELL' ? 'text-red-400 border-red-700/40' :
                            'text-slate-400 border-slate-700/40'
                          }`}>
                            {item.action || item.action_type}
                          </span>
                          {item.requires_revision && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded border text-amber-400 border-amber-700/40">
                              rewizja
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-slate-600">{item.timestamp?.slice(11, 19)} UTC</div>
                      </div>
                      <div className="mt-1 text-[11px] text-slate-400 flex flex-wrap gap-x-3 gap-y-1">
                        <span>Status: <span className="text-slate-300">{item.plan_status || '—'}</span></span>
                        <span>BE: <span className="text-slate-300">{item.break_even_price != null ? item.break_even_price.toFixed(item.break_even_price < 1 ? 6 : 4) : '—'}</span></span>
                        <span>Netto: <span className={item.expected_net_profit != null && item.expected_net_profit < 0 ? 'text-red-400' : 'text-emerald-400'}>
                          {item.expected_net_profit != null ? `${item.expected_net_profit >= 0 ? '+' : ''}${item.expected_net_profit.toFixed(2)} EUR` : '—'}
                        </span></span>
                        <span>Pewność: <span className="text-slate-300">{item.confidence_score != null ? `${Math.round(item.confidence_score * 100)}%` : '—'}</span></span>
                        <span>Ryzyko: <span className="text-slate-300">{item.risk_score != null ? `${Math.round(item.risk_score * 100)}%` : '—'}</span></span>
                      </div>
                      {item.invalidation_reason && (
                        <div className="mt-1 text-[10px] text-amber-400">Powód rewizji: {item.invalidation_reason}</div>
                      )}
                      <div className="mt-1 text-[10px] text-slate-600">reason_code: {item.reason_code}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── TAB: ACTIONS ── */}
        {activeTab === 'actions' && (
          <div className="p-4 space-y-4">
            <div className="flex items-center justify-between">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                Szybkie akcje operatorskie ({QUICK_ACTIONS.length})
              </div>
              {Object.values(actionResults).some(Boolean) && (
                <button
                  onClick={() => setActionResults({})}
                  className="text-[10px] text-slate-600 hover:text-slate-400 border border-slate-800 px-2 py-0.5 rounded"
                >
                  ✕ wyczyść wyniki
                </button>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {QUICK_ACTIONS.map((action) => {
                const result = actionResults[action.id]
                const loading = actionLoading[action.id]
                return (
                  <ActionButton
                    key={action.id}
                    action={action}
                    loading={loading}
                    result={result}
                    onRun={runAction}
                  />
                )
              })}
            </div>

            {/* Wyniki akcji */}
            {Object.entries(actionResults).some(([, r]) => r !== null) && (
              <div className="mt-4 space-y-2">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Historia akcji</div>
                {Object.entries(actionResults)
                  .filter(([, r]) => r !== null)
                  .sort(([, a], [, b]) => (b?.timestamp || '').localeCompare(a?.timestamp || ''))
                  .slice(0, 8)
                  .map(([id, result]) => result && (
                    <div
                      key={id}
                      className={`border rounded p-2.5 text-xs ${
                        result.success
                          ? 'border-emerald-700/40 bg-emerald-950/20'
                          : 'border-red-700/40 bg-red-950/20'
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`font-bold text-[10px] ${result.success ? 'text-emerald-400' : 'text-red-400'}`}>
                          {result.success ? '✓' : '✗'} {result.action}
                        </span>
                        <span className="text-slate-600 text-[10px]">
                          {result.timestamp?.slice(11, 19)} UTC
                        </span>
                      </div>
                      <div className="text-slate-300">{result.message}</div>
                      {result.data !== null && result.data !== undefined && (
                        <div className="mt-1.5 text-slate-500 text-[10px] font-mono whitespace-pre-wrap bg-slate-900/60 rounded p-1.5 max-h-40 overflow-y-auto">
                          {JSON.stringify(result.data as Record<string, unknown>, null, 2).slice(0, 600)}
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}

        {/* ── TAB: LOGS ── */}
        {activeTab === 'logs' && (
          <div className="flex flex-col h-full min-h-0">
            {/* Log toolbar */}
            <div className="px-3 py-2 border-b border-slate-800 bg-[#0d1320] shrink-0 space-y-2">
              {/* Wiersz 1: szukaj + poziom + przyciski */}
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  type="text"
                  placeholder="Szukaj w logach..."
                  value={logFilter}
                  onChange={(e) => setLogFilter(e.target.value)}
                  className="bg-slate-800 border border-slate-700 rounded px-2 py-0.5 text-[11px] text-slate-300 placeholder-slate-600 w-40 focus:outline-none focus:border-sky-600"
                />
                <select
                  title="Filtr poziomu logu"
                  value={logLevelFilter}
                  onChange={(e) => setLogLevelFilter(e.target.value)}
                  className="bg-slate-800 border border-slate-700 rounded px-2 py-0.5 text-[11px] text-slate-300 focus:outline-none focus:border-sky-600"
                >
                  <option value="">Wszystkie poziomy</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                  <option value="DEBUG">DEBUG</option>
                </select>
                <button
                  onClick={() => setLogPaused((p) => !p)}
                  className={`text-[10px] px-2 py-0.5 rounded border font-semibold transition ${
                    logPaused
                      ? 'border-amber-600/50 text-amber-400 bg-amber-950/30'
                      : 'border-slate-600/50 text-slate-400 hover:border-slate-500'
                  }`}
                >
                  {logPaused ? '▶ Wznów' : '⏸ Pauza'}
                </button>
                <button
                  onClick={() => setLogs([])}
                  className="text-[10px] px-2 py-0.5 rounded border border-slate-700/50 text-slate-500 hover:text-slate-300 hover:border-slate-500"
                >
                  ⌫ Wyczyść
                </button>
                <button
                  onClick={() => {
                    const content = filteredLogs.map((l) =>
                      `${l.timestamp || ''} [${l.level}] [${l.module}] ${l.message}${l.exception ? '\n  ' + l.exception : ''}`
                    ).join('\n')
                    const blob = new Blob([content], { type: 'text/plain' })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = `rldc-logs-${new Date().toISOString().slice(0, 19)}.txt`
                    a.click()
                    URL.revokeObjectURL(url)
                  }}
                  className="text-[10px] px-2 py-0.5 rounded border border-slate-700/50 text-slate-500 hover:text-slate-300 hover:border-slate-500"
                >
                  ↓ Eksportuj
                </button>
                <span className="text-[10px] text-slate-600 ml-auto">
                  {filteredLogs.length}/{logs.length} wpisów
                  {logPaused && <span className="text-amber-500 ml-1">• PAUZA</span>}
                </span>
              </div>
              {/* Wiersz 2: filtry modułów */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[9px] text-slate-600 mr-1 shrink-0">MODUŁ:</span>
                {LOG_MODULE_TAGS.map((tag) => (
                  <button
                    key={tag.id}
                    onClick={() => setLogModuleTag(tag.id)}
                    className={`text-[9px] px-1.5 py-0.5 rounded border font-bold transition ${
                      logModuleTag === tag.id
                        ? 'border-sky-500/60 text-sky-300 bg-sky-950/40'
                        : 'border-slate-700/40 text-slate-500 hover:border-slate-600 hover:text-slate-400'
                    }`}
                  >
                    {tag.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Log entries */}
            <div className="flex-1 overflow-y-auto min-h-0 font-mono text-[11px] leading-relaxed">
              {filteredLogs.length === 0 && (
                <div className="text-slate-600 text-xs p-4">
                  {logs.length === 0
                    ? 'Czekam na logi... (stream SSE połączony)'
                    : `Brak logów pasujących do filtrów (łącznie: ${logs.length})`}
                </div>
              )}
              {filteredLogs.map((log, idx) => (
                <LogRow key={`${log.id}-${idx}`} log={log} />
              ))}
              <div ref={logsEndRef} />
            </div>
          </div>
        )}

        {/* ── TAB: DECISIONS ── */}
        {activeTab === 'decisions' && (
          <div className="flex flex-col h-full min-h-0">
            {/* Toolbar */}
            <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800 bg-[#0d1320] shrink-0 flex-wrap">
              <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">
                Decision Trace
              </span>
              <div className="flex items-center gap-1.5 ml-2 flex-wrap">
                {(['', 'BUY', 'SELL', 'HOLD'] as const).map((f) => (
                  <button key={f}
                    onClick={() => setTraceActionFilter(f)}
                    className={`text-[9px] px-2 py-0.5 rounded border font-bold transition ${
                      traceActionFilter === f
                        ? (f === 'BUY' ? 'border-emerald-500/60 text-emerald-300 bg-emerald-950/40'
                          : f === 'SELL' ? 'border-orange-500/60 text-orange-300 bg-orange-950/40'
                          : f === 'HOLD' ? 'border-slate-500/60 text-slate-300 bg-slate-800/40'
                          : 'border-sky-500/60 text-sky-300 bg-sky-950/40')
                        : 'border-slate-700/40 text-slate-500 hover:text-slate-400'
                    }`}>
                    {f || 'WSZYSTKO'}
                  </button>
                ))}
              </div>
              <button onClick={loadTrace}
                className="text-[10px] border border-slate-700 text-slate-500 hover:text-slate-300 px-2 py-0.5 rounded ml-auto">
                {traceLoading ? '⟳' : '↻'} odśwież
              </button>
            </div>

            {/* Trace content */}
            <div className="flex-1 overflow-y-auto min-h-0 p-3">
              {traceLoading && !traceData && (
                <div className="text-slate-500 text-xs animate-pulse p-2">Ładowanie decision trace...</div>
              )}
              {traceData && (
                <>
                  {/* Summary bar */}
                  <TraceSummaryBar data={traceData} />
                  {/* Symbol cards */}
                  <div className="space-y-1.5 mt-3">
                    {(traceData.symbols || [])
                      .filter((s) => !traceActionFilter || s.signal_type === traceActionFilter)
                      .map((sym) => (
                        <TraceCard
                          key={sym.symbol}
                          sym={sym}
                          expanded={expandedSymbols.has(sym.symbol)}
                          onToggle={() => toggleExpand(sym.symbol)}
                        />
                      ))}
                    {(traceData.symbols || []).filter(
                      (s) => !traceActionFilter || s.signal_type === traceActionFilter
                    ).length === 0 && (
                      <div className="text-slate-600 text-xs p-3">Brak decyzji dla wybranego filtra.</div>
                    )}
                  </div>
                </>
              )}
              {!traceData && !traceLoading && (
                <div className="text-slate-600 text-xs p-3">
                  Kliknij &quot;odśwież&quot; aby załadować trace decyzji.
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── TAB: AI CHAT ── */}
        {activeTab === 'chat' && (
          <div className="flex flex-col h-full min-h-0">
            {/* Chat header */}
            <div className="px-4 py-2 border-b border-slate-800 bg-[#0d1320] shrink-0 flex items-center justify-between">
              <div className="text-[10px] text-slate-500">
                AI Operator Chat — {systemStatus?.ai.provider === 'openai' ? '🤖 OpenAI aktywny' : systemStatus?.ai.provider ? `⚙️ ${systemStatus.ai.provider}` : '⚙️ heurystyka'}
              </div>
              {chatMessages.length > 0 && (
                <button onClick={() => setChatMessages([])}
                  className="text-[10px] text-slate-600 hover:text-slate-400 border border-slate-800 px-2 py-0.5 rounded">
                  ✕ wyczyść
                </button>
              )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-3">
              {chatMessages.length === 0 && (
                <div className="space-y-2">
                  <div className="text-slate-600 text-[11px] mb-2 font-semibold">Przykładowe zapytania:</div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                    {AI_SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        onClick={() => sendChat(s)}
                        className="text-left text-[11px] text-sky-400/80 hover:text-sky-300 border border-sky-900/40 hover:border-sky-700/50 rounded px-3 py-1.5 bg-sky-950/20 transition"
                      >
                        ◆ {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {chatMessages.map((msg, idx) => (
                <ChatBubble key={idx} msg={msg} />
              ))}
              {chatLoading && (
                <div className="text-slate-500 text-xs animate-pulse">⋯ Analizuję...</div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-slate-800 bg-[#0d1320] p-3 shrink-0">
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Wpisz polecenie: sprawdź, przeanalizuj, napraw..."
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(chatInput) } }}
                  disabled={chatLoading}
                  className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-[12px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-sky-600 disabled:opacity-50"
                />
                <button
                  onClick={() => sendChat(chatInput)}
                  disabled={chatLoading || !chatInput.trim()}
                  className="px-3 py-1.5 bg-sky-700 hover:bg-sky-600 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded text-[11px] font-semibold transition"
                >
                  ↵ Wyślij
                </button>
              </div>
              <div className="text-[10px] text-slate-600 mt-1">Enter = wyślij • kontekst: pozycje, sygnały, błędy, blokady</div>
            </div>
          </div>
        )}
        {/* ── TAB: TERMINAL ── */}
        {activeTab === 'terminal' && (
          <div
            className="flex flex-col h-full min-h-0"
            onClick={() => termInputRef.current?.focus()}
          >
            {/* Terminal header */}
            <div className="flex items-center gap-3 px-3 py-1.5 border-b border-slate-800 bg-[#080c14] shrink-0">
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                termConnected ? 'text-emerald-400 border-emerald-800/40 bg-emerald-950/20' : 'text-slate-500 border-slate-700/40'
              }`}>
                {termConnected ? '● POŁĄCZONY' : '○ OFFLINE'}
              </span>
              <span className="text-[10px] text-slate-600 font-mono">bash — RLdC Terminal</span>
              <div className="ml-auto flex gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); setTermLines([]) }}
                  className="text-[10px] text-slate-600 hover:text-slate-400 border border-slate-800 px-2 py-0.5 rounded"
                >
                  ✕ wyczyść
                </button>
                {!termConnected && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setActiveTab('status'); setTimeout(() => setActiveTab('terminal'), 100) }}
                    className="text-[10px] text-sky-500 hover:text-sky-300 border border-sky-900/40 px-2 py-0.5 rounded"
                  >
                    ↻ reconnect
                  </button>
                )}
              </div>
            </div>

            {/* Output area */}
            <div
              className="flex-1 overflow-y-auto min-h-0 bg-[#0a0d13] p-0"
              style={{ fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace" }}
            >
              <div className="px-3 pt-2 pb-1">
                {termLines.length === 0 && !termConnected && (
                  <span className="text-slate-600 text-xs">
                    Oczekiwanie na połączenie z backendem... (wymaga ADMIN_TOKEN)
                  </span>
                )}
                {termLines.map((line, idx) => (
                  <div
                    key={idx}
                    style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: '1.45' }}
                    className={`text-[12px] leading-relaxed ${
                      line.type === 'error'
                        ? 'text-red-400'
                        : line.type === 'info'
                        ? 'text-sky-500/80'
                        : 'text-green-300'
                    }`}
                  >
                    {line.text}
                  </div>
                ))}
                <div ref={termEndRef} />
              </div>
            </div>

            {/* Input area */}
            <div className="shrink-0 border-t border-slate-800/60 bg-[#080c14] px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-emerald-500 text-[13px] font-bold select-none shrink-0" style={{ fontFamily: "monospace" }}>$</span>
                <input
                  ref={termInputRef}
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  value={termInput}
                  onChange={(e) => setTermInput(e.target.value)}
                  onKeyDown={termKeyDown}
                  disabled={!termConnected}
                  placeholder={termConnected ? 'wpisz komendę...' : 'brak połączenia'}
                  className="flex-1 bg-transparent border-none outline-none text-[13px] text-green-200 placeholder-slate-700 caret-green-400 disabled:opacity-40"
                  style={{ fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace" }}
                />
                <button
                  onClick={termSubmit}
                  disabled={!termConnected || !termInput.trim()}
                  className="text-[10px] text-slate-600 hover:text-slate-300 border border-slate-800 px-2 py-0.5 rounded disabled:opacity-40"
                >
                  ↵
                </button>
              </div>
              <div className="text-[9px] text-slate-700 mt-1">
                Enter = wyślij · ↑↓ = historia · Ctrl+C = przerwij · Ctrl+L = wyczyść
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────
// Sub-komponenty
// ─────────────────────────────────────────────

function StatusCard({
  title,
  status,
  ok,
  detail,
  sub,
  highlight,
}: {
  title: string
  status: string
  ok: boolean
  detail?: string
  sub?: string
  highlight?: 'amber' | 'green'
}) {
  const statusColor =
    highlight === 'amber'
      ? 'text-amber-400'
      : highlight === 'green'
      ? 'text-emerald-400'
      : ok
      ? 'text-emerald-400'
      : 'text-red-400'

  const borderColor =
    highlight === 'amber'
      ? 'border-amber-800/40'
      : highlight === 'green'
      ? 'border-emerald-800/40'
      : ok
      ? 'border-emerald-900/40'
      : 'border-red-900/60'

  return (
    <div className={`border rounded-lg p-3 bg-slate-900/40 ${borderColor}`}>
      <div className="text-[9px] text-slate-500 uppercase tracking-wider font-semibold mb-1">{title}</div>
      <div className={`text-sm font-bold ${statusColor}`}>{status}</div>
      {detail && <div className="text-[10px] text-slate-500 mt-0.5">{detail}</div>}
      {sub && <div className="text-[10px] text-slate-600 mt-0.5">{sub}</div>}
    </div>
  )
}

function ActionButton({
  action,
  loading,
  result,
  onRun,
}: {
  action: (typeof QUICK_ACTIONS)[0]
  loading?: boolean
  result?: ActionResult | null
  onRun: (id: string) => void
}) {
  const hasResult = !!result
  const resultOk = result?.success

  return (
    <button
      onClick={() => onRun(action.id)}
      disabled={loading}
      className={`
        relative flex flex-col items-center justify-center gap-1.5 p-3 rounded-lg border 
        bg-slate-900/50 transition-all text-center
        ${loading ? 'opacity-60 cursor-wait' : 'cursor-pointer'}
        ${action.color}
        ${hasResult && resultOk ? 'border-emerald-700/60 bg-emerald-950/20' : ''}
        ${hasResult && !resultOk ? 'border-red-700/60 bg-red-950/20' : ''}
      `}
    >
      <span className="text-xl leading-none">{loading ? '⏳' : action.icon}</span>
      <span className="text-[10px] text-slate-300 font-semibold leading-tight">{action.label}</span>
      {hasResult && (
        <span className={`text-[9px] font-bold ${resultOk ? 'text-emerald-500' : 'text-red-500'}`}>
          {resultOk ? '✓ OK' : '✗ BŁĄD'}
        </span>
      )}
    </button>
  )
}

function LogRow({ log }: { log: LogEntry }) {
  const levelColor = LOG_LEVEL_COLORS[log.level] || 'text-slate-400'
  const bg = LOG_LEVEL_BG[log.level] || ''
  return (
    <div className={`flex gap-2 px-3 py-0.5 hover:bg-slate-800/30 border-b border-slate-800/30 ${bg}`}>
      <span className="text-slate-600 shrink-0 w-[70px]">
        {log.timestamp ? log.timestamp.slice(11, 19) : '??:??:??'}
      </span>
      <span className={`shrink-0 w-[56px] font-bold text-[10px] ${levelColor}`}>
        {log.level?.slice(0, 5)}
      </span>
      <span className="text-slate-500 shrink-0 w-[120px] truncate text-[10px]">
        [{log.module}]
      </span>
      <span className="text-slate-300 flex-1 break-all">
        {log.message}
        {log.exception && (
          <span className="block text-red-400/70 text-[10px] mt-0.5 pl-2 border-l border-red-900">
            {log.exception.slice(0, 200)}
          </span>
        )}
      </span>
    </div>
  )
}

function ChatBubble({ msg }: { msg: ChatMsg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-sky-800/40 border border-sky-700/40 text-sky-100'
            : 'bg-slate-800/60 border border-slate-700/40 text-slate-200'
        }`}
      >
        {!isUser && (
          <div className="text-[9px] text-slate-500 mb-1 font-semibold">
            ◆ AI {msg.provider ? `[${msg.provider}]` : ''} — {msg.timestamp?.slice(11, 19)} UTC
          </div>
        )}
        {msg.content}
      </div>
    </div>
  )
}

function MiniMetric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/40 px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-wider text-slate-600">{label}</div>
      <div className={`text-sm font-bold mt-1 ${color || 'text-slate-200'}`}>{value}</div>
    </div>
  )
}

// ─────────────────────────────────────────────
// Sub-komponenty: Decision Trace
// ─────────────────────────────────────────────

function TraceSummaryBar({ data }: { data: TraceData }) {
  const syms = data.symbols || []
  const buyCount = syms.filter((s) => s.signal_type === 'BUY').length
  const sellCount = syms.filter((s) => s.signal_type === 'SELL').length
  const holdCount = syms.filter((s) => s.signal_type === 'HOLD').length
  const withPos = syms.filter((s) => s.has_position).length
  const pending = syms.filter((s) => s.has_pending).length
  return (
    <div className="flex flex-wrap gap-2 p-2 bg-slate-900/50 rounded-lg border border-slate-800/50">
      <TraceBadge label="Łącznie" value={syms.length} color="slate" />
      <TraceBadge label="BUY" value={buyCount} color="emerald" />
      <TraceBadge label="SELL" value={sellCount} color="orange" />
      <TraceBadge label="HOLD" value={holdCount} color="gray" />
      <TraceBadge label="Pozycja" value={withPos} color="blue" />
      <TraceBadge label="Pending" value={pending} color="amber" />
      <span className="text-[9px] text-slate-600 ml-auto self-center">
        okno {data.window_minutes}min · {data.mode?.toUpperCase()}
      </span>
    </div>
  )
}

function TraceBadge({ label, value, color }: { label: string; value: number; color: string }) {
  const colorMap: Record<string, string> = {
    slate: 'border-slate-700/40 text-slate-400',
    emerald: 'border-emerald-700/40 text-emerald-400',
    orange: 'border-orange-700/40 text-orange-400',
    gray: 'border-slate-600/40 text-slate-500',
    blue: 'border-blue-700/40 text-blue-400',
    amber: 'border-amber-700/40 text-amber-400',
  }
  return (
    <span className={`text-[9px] px-2 py-0.5 rounded border font-bold ${colorMap[color] || colorMap.slate}`}>
      {label}: {value}
    </span>
  )
}

function TraceCard({ sym, expanded, onToggle }: {
  sym: TraceSymbol; expanded: boolean; onToggle: () => void
}) {
  const signalBorder = sym.signal_type === 'BUY'
    ? 'border-emerald-900/30'
    : sym.signal_type === 'SELL'
    ? 'border-orange-900/30'
    : 'border-slate-800/30'

  const signalBg = sym.signal_type === 'BUY'
    ? 'bg-emerald-950/10'
    : sym.signal_type === 'SELL'
    ? 'bg-orange-950/10'
    : 'bg-slate-900/20'

  const signalBadge = sym.signal_type === 'BUY'
    ? 'text-emerald-400 border-emerald-800/40'
    : sym.signal_type === 'SELL'
    ? 'text-orange-400 border-orange-800/40'
    : 'text-slate-400 border-slate-700/40'

  const isBlocked = sym.reason_code && sym.reason_code !== 'ok' && sym.reason_code !== 'executed'
  const reasonColor = isBlocked ? 'text-red-400/80' : 'text-emerald-400/80'

  const det = sym.details || {}
  const risk = det.risk_check as Record<string, unknown> | undefined
  const cost = det.cost_check as Record<string, unknown> | undefined
  const exec = det.execution_check as Record<string, unknown> | undefined
  const sigsum = det.signal_summary as Record<string, unknown> | undefined

  return (
    <div className={`border rounded-lg overflow-hidden ${signalBg} ${signalBorder}`}>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-800/20 transition text-left"
      >
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${signalBadge}`}>
          {sym.signal_type}
        </span>
        <span className="text-slate-200 font-semibold text-[12px] w-[96px] shrink-0">{sym.symbol}</span>
        <div className="flex items-center gap-1 shrink-0">
          <div className="w-20 bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full rounded-full ${
                sym.signal_confidence >= 0.75 ? 'bg-emerald-500'
                  : sym.signal_confidence >= 0.6 ? 'bg-amber-500'
                  : 'bg-slate-500'
              }`}
              style={{ width: `${Math.min(100, sym.signal_confidence * 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-slate-400">{(sym.signal_confidence * 100).toFixed(0)}%</span>
        </div>
        <span className={`flex-1 text-[11px] truncate ${reasonColor}`}>
          {sym.reason_pl || sym.reason_code || '—'}
        </span>
        <div className="flex items-center gap-1.5 shrink-0">
          {sym.has_position && (
            <span className="text-[9px] text-blue-400 border border-blue-800/40 px-1 rounded">poz</span>
          )}
          {sym.has_pending && (
            <span className="text-[9px] text-amber-400 border border-amber-800/40 px-1 rounded">oczek</span>
          )}
          <span className="text-[9px] text-slate-600">{sym.trace_age_seconds}s</span>
          <span className="text-slate-600 text-[10px]">{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-800/40 px-3 py-2.5 space-y-2.5 text-[11px]">
          <div className="flex items-start gap-2">
            <span className="text-slate-600 w-28 shrink-0 text-[10px]">reason_code</span>
            <span className="text-amber-300/90 font-mono text-[10px]">{sym.reason_code}</span>
          </div>
          {sigsum && (
            <TraceSection title="Sygnał" ok={true}>
              {Object.entries(sigsum).slice(0, 8).map(([k, v]) => (
                <TraceRow key={k} k={k} v={v} />
              ))}
            </TraceSection>
          )}
          {risk && (
            <TraceSection title="Risk Gate" ok={risk.eligible !== false}>
              {Object.entries(risk).slice(0, 8).map(([k, v]) => (
                <TraceRow key={k} k={k} v={v} />
              ))}
            </TraceSection>
          )}
          {cost && (
            <TraceSection title="Cost Gate" ok={cost.eligible !== false}>
              {Object.entries(cost).slice(0, 8).map(([k, v]) => (
                <TraceRow key={k} k={k} v={v} />
              ))}
            </TraceSection>
          )}
          {exec && (
            <TraceSection title="Execution" ok={exec.eligible !== false}>
              {Object.entries(exec).slice(0, 8).map(([k, v]) => (
                <TraceRow key={k} k={k} v={v} />
              ))}
            </TraceSection>
          )}
        </div>
      )}
    </div>
  )
}

function TraceSection({ title, ok, children }: {
  title: string; ok: boolean; children: React.ReactNode
}) {
  const cls = ok
    ? 'border-emerald-900/30 text-emerald-400/60'
    : 'border-red-900/30 text-red-400/60'
  return (
    <div className={`border rounded p-2 ${cls}`}>
      <div className={`text-[9px] font-bold uppercase tracking-wider mb-1.5 ${ok ? 'text-emerald-400/60' : 'text-red-400/60'}`}>
        {ok ? '✓' : '✗'} {title}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function TraceRow({ k, v }: { k: string; v: unknown }) {
  const strV = typeof v === 'boolean'
    ? (v ? '✓ tak' : '✗ nie')
    : typeof v === 'number'
    ? (Number.isInteger(v) ? String(v) : v.toFixed(4))
    : String(v ?? '—').slice(0, 80)
  const valColor = v === true ? 'text-emerald-400'
    : v === false ? 'text-red-400'
    : typeof v === 'number' && v < 0 ? 'text-red-400'
    : 'text-slate-300'
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-slate-600 w-32 shrink-0 text-[10px]">{k}</span>
      <span className={`${valColor} font-mono text-[10px]`}>{strV}</span>
    </div>
  )
}
