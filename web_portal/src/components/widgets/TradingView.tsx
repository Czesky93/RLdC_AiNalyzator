'use client'

import React from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts'

// Mock data for the chart
const chartData = [
  { time: '00:00', price: 20100, volume: 450 },
  { time: '04:00', price: 20300, volume: 380 },
  { time: '08:00', price: 20150, volume: 520 },
  { time: '12:00', price: 20450, volume: 640 },
  { time: '16:00', price: 20380, volume: 580 },
  { time: '20:00', price: 20587, volume: 610 },
]

export default function TradingView() {
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">BTC/USDT</h2>
          <div className="flex items-center space-x-4 mt-1">
            <span className="text-2xl font-bold text-rldc-green-primary">€20,587</span>
            <span className="text-sm text-rldc-green-primary">+3.6% (24h)</span>
          </div>
        </div>
        
        <div className="flex space-x-2">
          {['1m', '5m', '15m', '1h', '4h', '1D'].map((tf) => (
            <button
              key={tf}
              className="px-3 py-1 text-xs rounded bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white transition"
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#14b8a6" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#14b8a6" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2d3d" />
            <XAxis 
              dataKey="time" 
              stroke="#64748b"
              style={{ fontSize: '12px' }}
            />
            <YAxis 
              stroke="#64748b"
              style={{ fontSize: '12px' }}
              domain={['dataMin - 100', 'dataMax + 100']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#111c26',
                border: '1px solid #1e2d3d',
                borderRadius: '8px',
                color: '#f1f5f9'
              }}
            />
            <Area 
              type="monotone" 
              dataKey="price" 
              stroke="#14b8a6" 
              strokeWidth={2}
              fill="url(#colorPrice)" 
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Trading Stats */}
      <div className="grid grid-cols-4 gap-4 mt-4 pt-4 border-t border-rldc-dark-border">
        <div>
          <div className="text-xs text-slate-500 mb-1">24h Max</div>
          <div className="text-sm font-semibold text-slate-200">€20,789</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">24h Min</div>
          <div className="text-sm font-semibold text-slate-200">€19,845</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">Wolumen 24h</div>
          <div className="text-sm font-semibold text-slate-200">€2.3M</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">Zmienność</div>
          <div className="text-sm font-semibold text-rldc-green-primary">Średnia</div>
        </div>
      </div>
    </div>
  )
}
