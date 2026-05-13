# Priorytet rdzenia tradingowego

Warstwa kontrolna jest domknięta. Teraz cała uwaga idzie na rdzeń tradingowy.

## Nie rozpraszać się na:
- nowe konsole / dashboardy
- nowe warstwy workflow / pipeline
- dodatkowe meta-analizy governance
- rozbudowę operator console

## Skupić się na:
- collector.py — logika wejścia i wyjścia
- pomiar jakości trade'ów (MFE/MAE/range accuracy)
- selekcja i ranking symboli
- kontrola częstotliwości transakcji
- realna ocena edge po kosztach

## Jedyna sytuacja, gdy wracamy do warstw kontrolnych:
- znaleziony bug
- brakujący log/alert blokujący diagnostykę rdzenia
