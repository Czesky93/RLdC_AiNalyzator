'use client'

import {
  Activity,
  BarChart2,
  BarChart3,
  Bell,
  BrainCircuit,
  FileText,
  Layers,
  LayoutDashboard,
  MessageSquare,
  Newspaper,
  ScrollText,
  SearchX,
  Settings,
  Shield,
  Target,
  TestTube,
  TrendingDown,
  Wallet
} from 'lucide-react'

interface SidebarProps {
  activeView: string
  setActiveView: (view: string) => void
  tradingMode: 'live' | 'demo'
  setTradingMode: (mode: 'live' | 'demo') => void
}

const menuItems = [
  { id: 'dashboard', label: 'Panel główny', icon: LayoutDashboard },
  { id: 'position-analysis', label: 'Decyzje', icon: BrainCircuit },
  { id: 'execution-trace', label: 'Diagnostyka', icon: SearchX },
  { id: 'operator-console', label: 'Panel operatora', icon: Shield },
  { id: 'telegram-intel', label: 'Telegram AI', icon: MessageSquare },
  { id: 'trade-desk', label: 'Zlecenia', icon: Target },
  { id: 'exit-diagnostics', label: 'Diagnostyka wyjść', icon: TrendingDown },
  { id: 'portfolio', label: 'Portfel', icon: Wallet },
  { id: 'strategies', label: 'Strategie', icon: Layers },
  { id: 'ai-signals', label: 'AI Sygnały', icon: Activity },
  { id: 'risk', label: 'Ryzyko', icon: Shield },
  { id: 'backtest', label: 'Historia', icon: TestTube },
  { id: 'economics', label: 'Ekonomia', icon: BarChart2 },
  { id: 'alerts', label: 'Alerty', icon: Bell },
  { id: 'news', label: 'Wiadomości', icon: Newspaper },
  { id: 'macro-reports', label: 'Raporty', icon: FileText },
  { id: 'reports', label: 'Statystyki', icon: BarChart3 },
  { id: 'logs', label: 'Logi', icon: ScrollText },
  { id: 'settings', label: 'Ustawienia', icon: Settings },
]

export default function Sidebar({ activeView, setActiveView, tradingMode, setTradingMode }: SidebarProps) {
  return (
    <div className="w-20 bg-[#0b121a] border-r border-rldc-dark-border sticky top-14 h-[calc(100vh-3.5rem)] overflow-y-auto flex flex-col items-center py-4 shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)]">
      {/* Przełącznik trybu DEMO / LIVE */}
      <div className="mb-4 w-full px-2">
        <div className="text-[9px] text-slate-500 uppercase tracking-wider text-center mb-2 font-semibold">
          TRYB
        </div>
        <div className="flex flex-col gap-1">
          <button
            onClick={() => setTradingMode('demo')}
            title="Tryb symulacyjny (DEMO)"
            className={`w-full py-1 rounded text-[9px] font-bold transition border ${
              tradingMode === 'demo'
                ? 'bg-rldc-green-primary/20 text-rldc-green-primary border-rldc-green-primary/40'
                : 'bg-transparent text-slate-600 border-slate-700/40 hover:text-slate-400'
            }`}
          >
            DEMO
          </button>
          <button
            onClick={() => setTradingMode('live')}
            title="Handel realny — dane z Binance"
            className={`w-full py-1 rounded text-[9px] font-bold transition border ${
              tradingMode === 'live'
                ? 'bg-amber-500/20 text-amber-400 border-amber-500/40'
                : 'bg-transparent text-slate-600 border-slate-700/40 hover:text-slate-400'
            }`}
          >
            LIVE
          </button>
        </div>
      </div>

      {/* Separator */}
      <div className="w-12 h-px bg-rldc-dark-border mb-4"></div>

      {/* Menu Icons */}
      <nav className="flex-1 flex flex-col items-center space-y-2 w-full px-2">
        {menuItems.map((item) => {
          const Icon = item.icon
          const isActive = activeView === item.id
          
          return (
            <button
              key={item.id}
              onClick={() => setActiveView(item.id)}
              title={item.label}
              className={`w-14 h-14 flex items-center justify-center rounded-lg transition-all duration-200 group relative ${
                isActive
                  ? 'bg-teal-primary/10 text-teal-primary border-2 border-teal-primary/50 shadow-glow-teal'
                  : 'text-slate-400 hover:bg-rldc-dark-hover hover:text-slate-200'
              }`}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />
              
              {/* Tooltip on hover */}
              <div className="absolute left-full ml-3 px-3 py-1.5 bg-rldc-dark-card border border-rldc-dark-border rounded-lg text-xs text-slate-200 whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none z-50 shadow-elevation">
                {item.label}
                <div className="absolute right-full top-1/2 -translate-y-1/2 w-0 h-0 border-8 border-transparent border-r-rldc-dark-border"></div>
              </div>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
