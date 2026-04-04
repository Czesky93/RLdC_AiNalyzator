'use client'

import {
    Activity,
    BrainCircuit,
    LayoutDashboard,
    Shield,
    Wallet,
} from 'lucide-react'

interface MobileNavProps {
  activeView: string
  setActiveView: (view: string) => void
  tradingMode: 'live' | 'demo'
  setTradingMode: (mode: 'live' | 'demo') => void
}

const mobileItems = [
  { id: 'dashboard',          label: 'Panel',    icon: LayoutDashboard },
  { id: 'position-analysis',  label: 'Decyzje',  icon: BrainCircuit },
  { id: 'portfolio',          label: 'Portfel',  icon: Wallet },
  { id: 'ai-signals',         label: 'Sygnały',  icon: Activity },
  { id: 'risk',               label: 'Ryzyko',   icon: Shield },
]

export default function MobileNav({ activeView, setActiveView, tradingMode, setTradingMode }: MobileNavProps) {
  return (
    /* Widoczny tylko na mobile (md = 768px) */
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-[#0b121a]/95 border-t border-rldc-dark-border backdrop-blur-md safe-area-pb">
      <div className="flex items-center justify-around px-1 py-1">
        {mobileItems.map((item) => {
          const Icon = item.icon
          const isActive = activeView === item.id
          return (
            <button
              key={item.id}
              onClick={() => setActiveView(item.id)}
              className={`flex flex-col items-center justify-center gap-0.5 flex-1 py-2 rounded-lg transition-all min-w-0 ${
                isActive
                  ? 'text-teal-primary'
                  : 'text-slate-500 active:text-slate-300'
              }`}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 1.8} />
              <span className="text-[10px] font-medium leading-none truncate">{item.label}</span>
            </button>
          )
        })}
      </div>
      {/* Tryb DEMO/LIVE w dolnym pasku */}
      <div className="flex items-center justify-center gap-2 px-4 pb-2 border-t border-rldc-dark-border/50 pt-1.5">
        <span className="text-[9px] text-slate-500 uppercase tracking-wider">Tryb:</span>
        <button
          onClick={() => setTradingMode('demo')}
          className={`px-3 py-0.5 rounded text-[9px] font-bold transition border ${
            tradingMode === 'demo'
              ? 'bg-rldc-green-primary/20 text-rldc-green-primary border-rldc-green-primary/40'
              : 'bg-transparent text-slate-600 border-slate-700/40'
          }`}
        >
          DEMO
        </button>
        <button
          onClick={() => setTradingMode('live')}
          className={`px-3 py-0.5 rounded text-[9px] font-bold transition border ${
            tradingMode === 'live'
              ? 'bg-amber-500/20 text-amber-400 border-amber-500/40'
              : 'bg-transparent text-slate-600 border-slate-700/40'
          }`}
        >
          LIVE
        </button>
      </div>
    </nav>
  )
}
