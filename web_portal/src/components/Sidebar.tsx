'use client'

import {
    Activity,
    BarChart2,
    BarChart3,
    Bell,
    FileText,
    Layers,
    LayoutDashboard,
    Newspaper,
    Settings,
    Shield,
    Target,
    TestTube,
    Wallet
} from 'lucide-react'

interface SidebarProps {
  activeView: string
  setActiveView: (view: string) => void
}

const menuItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'trade-desk', label: 'Trade Desk', icon: Target },
  { id: 'portfolio', label: 'Portfolio', icon: Wallet },
  { id: 'strategies', label: 'Strategie', icon: Layers },
  { id: 'ai-signals', label: 'AI & Sygnały', icon: Activity },
  { id: 'risk', label: 'Risk Sblock', icon: Shield },
  { id: 'backtest', label: 'Backtest / Demo', icon: TestTube },
  { id: 'economics', label: 'Economics', icon: BarChart2 },
  { id: 'alerts', label: 'Alertes', icon: Bell },
  { id: 'news', label: 'News', icon: Newspaper },
  { id: 'macro-reports', label: 'Macro-reports', icon: FileText },
  { id: 'reports', label: 'Reports', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export default function Sidebar({ activeView, setActiveView }: SidebarProps) {
  return (
    <div className="w-20 bg-[#0b121a] border-r border-rldc-dark-border min-h-[calc(100vh-3.5rem)] flex flex-col items-center py-4 shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)]">
      {/* FUTURES Section */}
      <div className="mb-6 w-full px-2">
        <div className="text-[9px] text-slate-500 uppercase tracking-wider text-center mb-2 font-semibold">
          FUTURES
        </div>
        <div className="flex flex-col items-center">
          <div className="text-xs text-slate-300 font-bold mb-1">BTC/USDT</div>
          <div className="px-2 py-0.5 rounded bg-green-primary/10 border border-green-primary/30 text-[9px] text-green-light font-medium">
            ACTIVE
          </div>
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
