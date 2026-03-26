# Kolejka zadań — rdzeń tradingowy

CEL GŁÓWNY:
Poprawa zysku netto po kosztach przez ograniczenie overtradingu, lepszą selekcję aktywów oraz poprawę jakości wejść i wyjść.

AKTUALNY PRIORYTET:
Trading core, nie governance.

CO JEST DOMKNIĘTE:
accounting, risk, reporting, policy, governance, notifications, worker, operator console, env→runtime_settings (P1), refaktor _demo_trading (P2).

CZEGO TERAZ NIE RUSZAĆ:
policy/governance/worker/console, chyba że jest bug.

AKTUALNIE PRACUJEMY NAD:
collector.py / entry-exit quality / symbol selection / activity limits.

OSTATNI ZAKOŃCZONY KROK:
Refaktor _demo_trading() na etapy + migracja 15 env→runtime_settings, testy 167/167 zielone.

NASTĘPNY KROK:
Pomiar jakości wyjść i range accuracy (ETAP B / P3).

---

## Kolejka

| # | Zadanie | Status |
|---|---|---|
| A | Checkpoint: commit P1+P2, aktualizacja docs | ✅ |
| B | Exit quality: MFE/MAE, range accuracy, partial exit analysis | ⬜ NASTĘPNY |
| C | Symbol selection: ranking netto po kosztach, black/whitelista | ⬜ |
| D | Activity control: max trades/h, cooldown per setup, gate anty-overtrading | ⬜ |
| E | Przeniesienie reszty env do runtime_settings (infrastrukturalne) | ⬜ |
