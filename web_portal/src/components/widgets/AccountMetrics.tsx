'use client'

import React from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'

interface AccountMetricsProps {
  equity?: number
  freeMargin?: number
  unrealizedPnl?: number
  winrate?: number
  equityChange?: number
}

export default function AccountMetrics({
  equity = 24582,
  freeMargin = 20987,
  unrealizedPnl = 301,
  winrate = 62,
  equityChange = 2.3
}: AccountMetricsProps) {
  const isPnlPositive = unrealizedPnl >= 0
  const isEquityUp = equityChange >= 0

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Equity */}
      <div className="metric-card">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400 font-medium">Equity</span>
          <div className={`flex items-center space-x-1 text-xs ${isEquityUp ? 'text-green-primary' : 'text-red-primary'}`}>
            {isEquityUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            <span className="font-medium">{isEquityUp ? '+' : ''}{equityChange}%</span>
          </div>
        </div>
        <div className="text-2xl font-bold text-slate-100">
          £{equity.toLocaleString()}
        </div>
        <div className="mt-2 text-[10px] text-slate-500">
          BN +£13,582
        </div>
        
        {/* Mini equity curve */}
        <div className="mt-3 h-12 flex items-end space-x-0.5">
          {[42, 38, 45, 52, 48, 55, 58, 54, 62, 68, 65, 72, 75, 71, 78, 82, 79, 85, 88, 91].map((height, i) => (
            <div
              key={i}
              className="flex-1 bg-gradient-to-t from-teal-primary/60 to-teal-primary/20 rounded-t-sm"
              style={{ height: `${height}%` }}
            />
          ))}
        </div>
      </div>

      {/* Free Margin */}
      <div className="metric-card">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400 font-medium">Free Margin</span>
          <span className="text-xs text-green-primary font-medium">P'N'L</span>
        </div>
        <div className="text-2xl font-bold text-slate-100">
          £{freeMargin.toLocaleString()}
        </div>
        <div className="mt-2 text-[10px] text-slate-500">
          +£3,981 +24%
        </div>
      </div>

      {/* Unrealized P'N'L */}
      <div className="metric-card">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400 font-medium">Unrealized P'N'L</span>
        </div>
        <div className={`text-2xl font-bold ${isPnlPositive ? 'text-green-primary' : 'text-red-primary'}`}>
          {isPnlPositive ? '+' : ''}£{unrealizedPnl.toLocaleString()}
        </div>
        <div className="mt-2 text-[10px] text-slate-500">
          +£110,165 +7.4%
        </div>
      </div>

      {/* Winrate */}
      <div className="metric-card">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400 font-medium">Winrate</span>
          <span className="text-xs text-slate-400">45</span>
        </div>
        <div className="flex items-baseline space-x-2">
          <div className="text-2xl font-bold text-teal-primary">{winrate}%</div>
          <span className="text-sm text-green-primary">+2.6%</span>
        </div>
        <div className="mt-3">
          <div className="progress-bar">
            <div 
              className="progress-fill" 
              style={{ width: `${winrate}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[9px] text-slate-500">
            <span>0%</span>
            <span>50%</span>
            <span>100%</span>
          </div>
        </div>
      </div>

      {/* Festio */}
      <div className="metric-card col-span-2">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs text-slate-400 font-medium">Festio</span>
            <div className="text-xl font-bold text-slate-100 mt-1">45</div>
          </div>
          <div className="text-right">
            <span className="text-2xl font-bold text-green-primary">+2.6%</span>
            <div className="text-[10px] text-slate-500 mt-1">30 days</div>
          </div>
        </div>
      </div>
    </div>
  )
}
