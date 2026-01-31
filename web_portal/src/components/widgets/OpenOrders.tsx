'use client'

import React from 'react'

const orders = [
  {
    id: '1',
    symbol: 'BTC/USDT',
    type: 'LONG',
    size: '0.125',
    entry: '€20,450',
    current: '€20,587',
    pnl: '+€17.13',
    pnlPercent: '+0.67%',
    status: 'active',
  },
  {
    id: '2',
    symbol: 'ETH/USDT',
    type: 'SHORT',
    size: '2.5',
    entry: '€1,670',
    current: '€1,654',
    pnl: '+€40.00',
    pnlPercent: '+2.4%',
    status: 'active',
  },
  {
    id: '3',
    symbol: 'SOL/USDT',
    type: 'LONG',
    size: '15',
    entry: '€95.20',
    current: '€98.40',
    pnl: '+€48.00',
    pnlPercent: '+3.4%',
    status: 'active',
  },
]

export default function OpenOrders() {
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-200">Otwarte Pozycje</h2>
        <div className="flex space-x-2">
          <button className="px-3 py-1 text-xs rounded bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white transition">
            Wszystkie
          </button>
          <button className="px-3 py-1 text-xs rounded bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white transition">
            Aktywne
          </button>
          <button className="px-3 py-1 text-xs rounded bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white transition">
            Zamknięte
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-rldc-dark-border text-left text-xs text-slate-500">
              <th className="pb-3 font-medium">Para</th>
              <th className="pb-3 font-medium">Typ</th>
              <th className="pb-3 font-medium">Rozmiar</th>
              <th className="pb-3 font-medium">Wejście</th>
              <th className="pb-3 font-medium">Obecna</th>
              <th className="pb-3 font-medium">P&L</th>
              <th className="pb-3 font-medium">Status</th>
              <th className="pb-3 font-medium">Akcje</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr
                key={order.id}
                className="border-b border-rldc-dark-border/50 hover:bg-rldc-dark-hover transition"
              >
                <td className="py-3 text-sm font-medium text-slate-200">{order.symbol}</td>
                <td className="py-3">
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium ${
                      order.type === 'LONG'
                        ? 'bg-rldc-green-primary/20 text-rldc-green-primary'
                        : 'bg-rldc-red-primary/20 text-rldc-red-primary'
                    }`}
                  >
                    {order.type}
                  </span>
                </td>
                <td className="py-3 text-sm text-slate-300">{order.size}</td>
                <td className="py-3 text-sm text-slate-300">{order.entry}</td>
                <td className="py-3 text-sm text-slate-300">{order.current}</td>
                <td className="py-3">
                  <div className="text-sm font-medium text-rldc-green-primary">
                    {order.pnl}
                  </div>
                  <div className="text-xs text-rldc-green-primary/70">
                    {order.pnlPercent}
                  </div>
                </td>
                <td className="py-3">
                  <span className="px-2 py-1 rounded text-xs font-medium bg-rldc-teal-primary/20 text-rldc-teal-primary">
                    {order.status}
                  </span>
                </td>
                <td className="py-3">
                  <button className="px-3 py-1 text-xs rounded bg-rldc-red-primary/20 text-rldc-red-primary hover:bg-rldc-red-primary hover:text-white transition">
                    Zamknij
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Summary */}
      <div className="mt-4 pt-4 border-t border-rldc-dark-border flex items-center justify-between">
        <div className="flex space-x-6">
          <div>
            <div className="text-xs text-slate-500 mb-1">Całkowity P&L</div>
            <div className="text-lg font-bold text-rldc-green-primary">+€105.13</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">ROI</div>
            <div className="text-lg font-bold text-rldc-green-primary">+2.1%</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Otwarte pozycje</div>
            <div className="text-lg font-bold text-slate-200">3</div>
          </div>
        </div>
        
        <button className="px-4 py-2 bg-rldc-red-primary hover:bg-red-600 text-white rounded-lg text-sm font-medium transition">
          Zamknij wszystkie
        </button>
      </div>
    </div>
  )
}
