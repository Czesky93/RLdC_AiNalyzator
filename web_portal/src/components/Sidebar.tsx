'use client'

import {
    Activity,
    BarChart2,
    Bell,
    BookOpen,
    BrainCircuit,
    LayoutDashboard,
    MonitorDot,
    Settings,
    Shield,
    Target,
    TrendingDown,
    Wallet
} from 'lucide-react'

interface SidebarProps {
  activeView: string
  setActiveView: (view: string) => void
}

// ─── MENU GŁÓWNE ───────────────────────────────────────────────
// 13 pozycji wg podziału: trade / portfolio / AI / diag / admin
// Legacy: dashboard-classic, blog, macro-reports, reports, backtest — dostępne
//         tylko przez Topbar lub bezpośrednie URL, nie pokazujemy w sidebarze.
const menuItems = [
  // ── Trading ──
  { id: 'dashboard',         label: 'Panel główny',        icon: LayoutDashboard, group: 'trade' },
  { id: 'trade-desk',        label: 'Zlecenia',            icon: Target,          group: 'trade' },
  { id: 'portfolio',         label: 'Portfel',             icon: Wallet,          group: 'trade' },
  { id: 'position-analysis', label: 'Pozycje / Decyzje',  icon: BrainCircuit,    group: 'trade' },
  // ── Analiza ──
  { id: 'ai-signals',        label: 'AI i Sygnały',       icon: Activity,        group: 'ai' },
  { id: 'exit-diagnostics',  label: 'Dyag. wyjść',         icon: TrendingDown,    group: 'ai' },
  { id: 'risk',              label: 'Ryzyko',              icon: Shield,          group: 'ai' },
  // ── Rynek ──
  { id: 'economics',         label: 'Ekonomia',            icon: BarChart2,       group: 'market' },
  { id: 'alerts',            label: 'Alerty',              icon: Bell,            group: 'market' },
  // ── Diagnostyka ──
  { id: 'operator-console',  label: 'Centrum diagnostyki', icon: MonitorDot,      group: 'diag' },
  { id: 'strategies',        label: 'Strategie',           icon: BookOpen,        group: 'diag' },
  // ── Admin ──
  { id: 'settings',          label: 'Ustawienia',          icon: Settings,        group: 'admin' },
]

const groupSeparators: Record<string, boolean> = {
  ai: true,     // separator przed grupą "ai"
  diag: true,   // separator przed grupą "diag"
  admin: true,  // separator przed grupą "admin"
}

export default function Sidebar({ activeView, setActiveView }: SidebarProps) {
  return (
    <div className="w-20 bg-[#0b121a] border-r border-rldc-dark-border sticky top-14 h-[calc(100vh-3.5rem)] overflow-y-auto flex flex-col items-center py-4 shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)]">
      {/* Status LIVE */}
      <div className="mb-4 w-full px-2">
        <div className="w-full py-1 rounded text-[9px] font-bold text-center border bg-amber-500/20 text-amber-400 border-amber-500/40">
          LIVE
        </div>
      </div>

      {/* Separator */}
      <div className="w-12 h-px bg-rldc-dark-border mb-4"></div>

      {/* Menu Icons */}
      <nav className="flex-1 flex flex-col items-center space-y-1 w-full px-2">
        {menuItems.map((item, idx) => {
          const Icon = item.icon
          const isActive = activeView === item.id
          const prevGroup = idx > 0 ? menuItems[idx - 1].group : item.group
          const showSep = item.group !== prevGroup && groupSeparators[item.group]

          return (
            <div key={item.id} className="w-full flex flex-col items-center">
              {showSep && <div className="w-10 h-px bg-rldc-dark-border my-1.5 opacity-50" />}
              <button
                onClick={() => setActiveView(item.id)}
                title={item.label}
                className={`w-14 h-14 flex items-center justify-center rounded-lg transition-all duration-200 group relative ${
                  isActive
                    ? 'bg-teal-primary/10 text-teal-primary border-2 border-teal-primary/50 shadow-glow-teal'
                    : 'text-slate-400 hover:bg-rldc-dark-hover hover:text-slate-200'
                }`}
              >
                <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />

                {/* Tooltip */}
                <div className="absolute left-full ml-3 px-3 py-1.5 bg-rldc-dark-card border border-rldc-dark-border rounded-lg text-xs text-slate-200 whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none z-50 shadow-elevation">
                  {item.label}
                  <div className="absolute right-full top-1/2 -translate-y-1/2 w-0 h-0 border-8 border-transparent border-r-rldc-dark-border"></div>
                </div>
              </button>
            </div>
          )
        })}
      </nav>
    </div>
  )
}
