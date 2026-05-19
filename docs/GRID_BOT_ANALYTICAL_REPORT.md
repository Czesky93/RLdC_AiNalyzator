# Raport analityczny grid bota

**Zakres danych:** eksport historii handlu Spot Binance z okresu 2026-05-18 do 2026-05-19.  
**Uwaga metodologiczna:** materiał zawiera wyłącznie fill-e transakcyjne. Brakuje equity curve, ustawień strategii, świec cenowych i identyfikatorów bota, więc pełny backtest oraz wiarygodny CAGR pozostają nieokreślone.

## Executive Summary

Analiza wskazuje, że strategia/grid bot w badanej próbce wygenerował niewielki zysk brutto na zamkniętych nogach, ale niemal cały wynik został skonsumowany przez koszty transakcyjne. W praktyce oznacza to, że problemem nie jest sam brak ruchu rynku, lecz zbyt mały przechwytywany ruch względem fee i prawdopodobnego slippage.

Najważniejsze wnioski:
- dostępny zakres danych to około 32,47 godziny historii,
- po agregacji filli i przybliżonym dopasowaniu FIFO wynik brutto był dodatni, ale netto prawie zerowy,
- strategia zarabiała głównie w reżimach większej zmienności i dłuższego utrzymania pozycji,
- w konsolidacji i przy małych ruchach strategia traciła,
- uniwersum par wygląda na zbyt szerokie, a siatka zbyt ciasna kosztowo.

## Zakres i ograniczenia danych

Raport opiera się wyłącznie na eksporcie transakcji. Nie da się z niego odtworzyć pełnej logiki bota, warunków wejścia/wyjścia ani prawdziwego profilu ryzyka portfela. Z tego powodu następujące wielkości są nieokreślone:
- CAGR,
- rzeczywisty max drawdown portfela,
- slippage,
- equity curve,
- pełny backtest,
- dokładny timeframe i konfiguracja gridu.

## Wyniki historyczne

| Metryka | Wynik |
|---|---:|
| Okres analizy | 32,47 h |
| Liczba filli | 109 |
| Zdarzenia po agregacji | 72 |
| Zamknięte nogi FIFO | 55 |
| PnL brutto | +5,30 USDC |
| Szacowane opłaty | ~5,08 USDC |
| PnL netto | **+0,22 USDC** |
| Profit factor | 1,02 |
| Win rate | 23,6% |
| Mediana czasu trwania pozycji | 63,9 min |

Wniosek kosztowy jest prosty: opłaty pochłonęły niemal cały zysk brutto. To oznacza, że minimalny krok siatki oraz minimalny target realizacji były prawdopodobnie zbyt małe jak na realne koszty handlu.

## Reżim rynku i zachowanie strategii

W próbce strategia traciła w konsolidacji i przy małych ruchach, a zarabiała głównie wtedy, gdy rynek dawał większe wychylenie. To sugeruje, że bot wymaga filtra reżimu rynku oraz adaptacji kroku siatki do zmienności. Klasyczny statyczny grid bez adaptacji ma słabą oczekiwaną wartość, a poprawa przychodzi dopiero po ograniczeniu handlu do reżimów sprzyjających mean-reversion.

## Najważniejsze anomalie

- wiele trade'ów miało ruch brutto poniżej 0,20%, czyli na granicy break-even po kosztach,
- część transakcji była dodatnia brutto, ale ujemna netto,
- wynik był silnie skoncentrowany na kilku parach,
- spekulacyjne pary rozcieńczały wynik core basket,
- część filli wygląda tak, jakby historia mogła łączyć aktywność kilku botów lub transakcji manualnych.

## Rekomendacje

1. Poszerzyć grid step i minimalny TP, aby wyjścia były wyraźnie powyżej round-trip fee plus slippage.
2. Zawęzić uniwersum par do koszyka core i wyłączyć aktywa spekulacyjne.
3. Wyłączyć lub mocno ograniczyć martingale.
4. Włączyć filtr reżimu rynku i uruchamiać grid tylko w mean-reversion / range.
5. Dodać reset siatki przy wybiciu poza band.
6. Utrzymywać bufor BNB na opłaty, jeśli fee mają być rozliczane z rabatem.

## Minimalny plan dalszych danych

Do pełnej, wiarygodnej oceny potrzebne są:
- export ustawień strategii dla każdej pary,
- equity curve z unrealized PnL,
- świece 1m, 5m, 15m i 1h,
- snapshoty mid-price / order book w chwili wysyłki zlecenia,
- identyfikatory bota i strategii dla każdego order-event.

## Konkluzja

Na podstawie tej próbki grid bot nie wygląda na fundamentalnie zepsuty, ale wygląda na za gęsty, za szeroki w uniwersum i zbyt słabo dopasowany do kosztów oraz reżimu rynku. Bez korekty tych trzech elementów strategia ma małą szansę utrzymać dodatni wynik netto.
