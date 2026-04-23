# ARCHITECTURE_DECISIONS

Data aktualizacji: 2026-04-14
Status: aktywny

## Zakres
Dokument opisuje realne decyzje architektoniczne, na ktorych opiera sie obecny kod.
Nie zawiera funkcji aspiracyjnych ani planow bez implementacji.

## ADR-001: Monolit modulowy (backend + web + telegram)
- Decyzja: utrzymujemy monolit logicznie podzielony na warstwy.
- Powod: mniejsze ryzyko regresji i prostsza operacja produkcyjna.
- Konsekwencja: refaktor fizyczny tylko gdy daje mierzalny zysk utrzymaniowy.

## ADR-002: Thin routers
- Decyzja: logika biznesowa pozostaje w modulach backendowych, routery tylko waliduja i deleguja.
- Powod: mniejszy coupling i prostsze testy.

## ADR-003: Single source of truth dla KPI konta
- Decyzja: UI korzysta z /api/portfolio/wealth?mode=...
- Powod: spojnosc equity/cash/PnL miedzy backend i frontend.

## ADR-004: Cost-aware trading
- Decyzja: decyzje wejscia/wyjscia musza uwzgledniac koszty (fee/spread/slippage).
- Powod: ochrona przed pozornie dodatnimi sygnalami, ktore po kosztach sa ujemne.

## ADR-005: Explainability by design
- Decyzja: decyzje sa zapisywane z reason_code i reason_pl.
- Powod: diagnostyka i audyt musza tlumaczyc dlaczego bot handluje albo blokuje wejscie.

## ADR-006: Runtime safety gates
- Decyzja: trading ma bramki runtime (max positions, cooldown, gates ryzyka, hold mode, kill-switch).
- Powod: minimalizacja overtradingu i strat skrajnych.

## ADR-007: Test isolation dla efektow zewnetrznych
- Decyzja: podczas pytest outbound Telegram jest domyslnie blokowany (chyba ze ALLOW_TEST_TELEGRAM=true).
- Powod: brak spamu i deterministyczne testy bez skutkow ubocznych na zewnatrz.

## ADR-008: Root npm scripts delegowane do web_portal
- Decyzja: rootowe dev/build/start/lint deleguja do web_portal.
- Powod: jeden punkt uruchomieniowy i brak bledu Missing script: build.

## Rzeczy NIEZAIMPLEMENTOWANE (nie traktowac jako dzialajace)
- Quantum/HFT/blockchain analysis jako produkcyjna warstwa tradingowa
- Pelna mikroserwisowa orkiestracja
- Obietnica "zero strat"
