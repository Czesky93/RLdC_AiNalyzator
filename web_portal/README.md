# RLDC AiNalyzer - Web Portal

Interfejs webowy dla platformy RLDC Trading Bot z profesjonalnym wyglądem terminala tradingowego.

## Design System

### Kolory

- **Tło główne**: `#0a1219` (rldc-dark-bg)
- **Karty/Panele**: `#111c26` (rldc-dark-card)
- **Obramowania**: `#1e2d3d` (rldc-dark-border)
- **Akcent Teal**: `#14b8a6` (rldc-teal-primary)
- **Akcent Zielony**: `#10b981` (rldc-green-primary)
- **Akcent Czerwony**: `#ef4444` (rldc-red-primary)

### Komponenty

- **Topbar**: Nawigacja główna z przełącznikiem trybu (LIVE/DEMO/BACKTEST) i przyciskiem STOP TRADING
- **Sidebar**: Menu boczne z sekcjami aplikacji
- **Dashboard**: Główny widok z:
  - Przegląd Rynku (market cards)
  - Wykres tradingowy z timeframe selector
  - AI Insights panel
  - Tabela otwartych pozycji

## Uruchomienie

```bash
# Instalacja zależności
npm install

# Tryb deweloperski
npm run dev

# Build produkcyjny
npm run build

# Start produkcyjny
npm start
```

Aplikacja będzie dostępna pod adresem `http://localhost:3000`

## Technologie

- **Next.js 16**: Framework React z App Router
- **TypeScript**: Typowanie statyczne
- **Tailwind CSS**: Stylizacja utility-first
- **Recharts**: Wykresy i wizualizacje
- **Lucide React**: Ikony

## Struktura

```
src/
├── app/
│   ├── layout.tsx       # Layout główny
│   └── page.tsx         # Strona główna
├── components/
│   ├── Dashboard.tsx    # Główny komponent
│   ├── Topbar.tsx       # Górny pasek nawigacji
│   ├── Sidebar.tsx      # Boczne menu
│   ├── MainContent.tsx  # Zawartość główna
│   └── widgets/         # Widżety dashboardu
│       ├── MarketOverview.tsx
│       ├── TradingView.tsx
│       ├── OpenOrders.tsx
│       └── MarketInsights.tsx
└── styles/
    └── globals.css      # Style globalne
```

## Funkcjonalności

- ✅ Responsywny layout z dark theme
- ✅ Tryby tradingu: LIVE, DEMO, BACKTEST
- ✅ Dashboard z przeglądem rynku
- ✅ Wykresy tradingowe (area chart)
- ✅ Panel AI insights
- ✅ Tabela otwartych pozycji
- ✅ Polski interfejs użytkownika
- ⏳ Integracja z backend API (w planach)
- ⏳ Real-time WebSocket updates (w planach)
- ⏳ Więcej widoków (Markets, Trade Desk, Portfolio, etc.)

## Następne kroki

1. Dodanie integracji z backend API
2. Implementacja WebSocket dla danych real-time
3. Dodanie pozostałych widoków (Markets, Portfolio, Strategies, etc.)
4. Uwierzytelnianie użytkowników
5. Persystencja ustawień użytkownika
6. Testy jednostkowe i E2E
