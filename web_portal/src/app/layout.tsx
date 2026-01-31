import '../styles/globals.css'
import { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'RLDC AiNalyzer - Trading Terminal',
  description: 'Advanced AI Trading Platform',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="pl">
      <body>{children}</body>
    </html>
  )
}
