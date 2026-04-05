'use client'

import { useState } from 'react'
import MainContent from './MainContent'
import MobileNav from './MobileNav'
import Sidebar from './Sidebar'
import Topbar from './Topbar'

export default function Dashboard() {
  const [activeView, setActiveView] = useState('dashboard')
  const [tradingMode, setTradingMode] = useState<'live' | 'demo'>('demo')

  return (
    <div className="min-h-screen text-slate-100 app-shell">
      <Topbar 
        activeView={activeView}
        setActiveView={setActiveView}
        tradingMode={tradingMode} 
        setTradingMode={setTradingMode}
      />
      <div className="flex">
        <Sidebar 
          activeView={activeView} 
          setActiveView={setActiveView}
          tradingMode={tradingMode}
          setTradingMode={setTradingMode}
        />
        <MainContent 
          activeView={activeView} 
          tradingMode={tradingMode}
        />
      </div>
      <MobileNav activeView={activeView} setActiveView={setActiveView} />
    </div>
  )
}
