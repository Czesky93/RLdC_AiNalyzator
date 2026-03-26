# Kolejka zadań — rdzeń tradingowy

CEL GŁÓWNY:
Poprawa zysku netto po kosztach przez ograniczenie overtradingu, lepszą selekcję aktywów oraz poprawę jakości wejść i wyjść.

AKTUALNY PRIORYTET:
Trading core, nie governance.

CO JEST DOMKNIĘTE:
accounting, risk, reporting, policy, governance, notifications, worker, operator console, env→runtime_settings (P1), refaktor _demo_trading (P2), exit quality (ETAP B), telegram rewrite.

CZEGO TERAZ NIE RUSZAĆ:
policy/governance/worker/console, chyba że jest bug.

AKTUALNIE PRACUJEMY NAD:
symbol selection / activity limits.

OSTATNI ZAKOŃCZONY KROK:
ETAP B: ExitQuality model + MFE/MAE tracking + exit_quality_report + Telegram rewrite (operator-friendly). Testy 171/171 zielone. Commit da39fd8.

NASTĘPNY KROK:
Symbol selection: ranking netto po kosztach, black/whitelista (ETAP C).

---

## Kolejka

| # | Zadanie | Status |
|---|---|---|
| A | Checkpoint: commit P1+P2, aktualizacja docs | ✅ |
| B | Exit quality: MFE/MAE, range accuracy, Telegram rewrite | ✅ |
| C | Symbol selection: ranking netto po kosztach, black/whitelista | ⬜ NASTĘPNY |
| D | Activity control: max trades/h, cooldown per setup, gate anty-overtrading | ⬜ |
| E | Przeniesienie reszty env do runtime_settings (infrastrukturalne) | ⬜ |
