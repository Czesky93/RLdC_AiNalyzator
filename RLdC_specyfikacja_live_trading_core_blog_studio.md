# RLdC — Zintegrowana Specyfikacja Systemu LIVE, Trading Core, Predykcji, Lektora, Bloga i Studio Testowego

*Dokument wykonawczy i architektoniczny ograniczający chaos implementacyjny oraz błędy wynikające z gubienia wątków w VS Code / Copilot*


# 1. Cel dokumentu

Ten dokument ma być jednym, nadrzędnym punktem odniesienia dla całego projektu RLdC w zakresie:
- rdzenia handlowego,
- warstwy predykcji,
- sekcji LIVE,
- studia testowego do transmisji,
- generatora komentarzy i lektora,
- bloga i raportów,
- replayów,
- synchronizacji danych, komunikatów i transakcji,
- zasad pracy projektowej ograniczających chaos w VS Code, Copilot i innych narzędziach AI.

Głównym celem nie jest napisanie „ładnego opisu produktu”, tylko stworzenie dokumentu, który:
1. porządkuje architekturę,
2. eliminuje sprzeczne interpretacje,
3. ogranicza ryzyko duplikacji logiki,
4. wymusza jedno źródło prawdy,
5. ułatwia wdrożenie etapami,
6. minimalizuje przypadki, w których AI lub programista „gubi wątek” i modyfikuje zły fragment systemu.

Dokument ma służyć jako:
- baza dla planowania plików i modułów,
- opis granic odpowiedzialności poszczególnych warstw,
- źródło kontraktów danych,
- instrukcja projektowa dla VS Code / Copilot / agentów AI,
- punkt kontrolny podczas refaktoryzacji.

# 2. Problem, który rozwiązujemy

Dotychczasowy problem nie polega wyłącznie na tym, że bot czasem źle przewiduje, za późno wychodzi, albo nie tłumaczy decyzji. Prawdziwy problem jest głębszy:
- interfejs, analiza, execution i komunikacja potrafią żyć własnym życiem,
- bot może mówić co innego niż robi,
- moduły mogą korzystać z innych danych lub z tych samych danych w innym momencie,
- AI wspomagające kodowanie może pracować na niepełnym obrazie systemu,
- łatwo powstają poprawki lokalne, które nie rozwiązują problemu globalnego,
- VS Code / Copilot / kolejne iteracje poprawek mogą nadpisywać logikę, która jest ważna w innym miejscu.

W praktyce prowadzi to do kilku rodzajów błędów:
1. błąd synchronizacji: interfejs pokazuje co innego niż execution,
2. błąd odpowiedzialności: kilka modułów liczy to samo na różne sposoby,
3. błąd narracji: lektor i tekst bazują na stanie już nieaktualnym,
4. błąd predykcji oderwanej od handlu: linia forecastu nie wpływa na realną decyzję,
5. błąd dokumentacyjny: przy kolejnej poprawce nikt nie wie, który moduł jest źródłowy,
6. błąd wdrożeniowy: agent AI łata objaw, nie przyczynę.

Ten dokument ma temu przeciwdziałać.

# 3. Zasada nadrzędna: jedno źródło prawdy

Najważniejsza zasada całego projektu brzmi:

**W systemie istnieje jedno źródło prawdy dla stanu rynku, predykcji, decyzji, execution i komunikacji.**

To oznacza:
- żadna warstwa prezentacyjna nie tworzy własnej logiki handlowej,
- żadna warstwa komunikacji nie opisuje świata „po swojemu” bez potwierdzenia przez rdzeń,
- żadna sekcja LIVE nie rysuje forecastu, który nie pochodzi z zatwierdzonego silnika predykcji,
- blog nie wymyśla wyników na podstawie przybliżeń,
- Telegram, web, live studio i blog korzystają z tego samego, kanonicznego modelu stanu.

W skrócie:

**Market Data -> Features -> Prediction -> Decision -> Execution -> State -> Explanation -> Broadcast -> Learning**

Każdy etap bazuje na poprzednim. Żaden etap nie może omijać innych skrótami, jeśli skutkuje to niespójnością.

# 4. Główna wizja produktu

RLdC ma być systemem, który:
- handluje,
- przewiduje,
- tłumaczy,
- pokazuje to publicznie w formie LIVE,
- uczy się na swoich decyzjach,
- raportuje sukcesy, błędy i wnioski,
- pozwala testować warstwę transmisyjną przed połączeniem z YouTube i TikTok,
- pozostaje zrozumiały dla początkującego odbiorcy.

To nie ma być tylko bot tradingowy ani tylko wizualny dashboard. To ma być spójny organizm o pięciu twarzach:
1. silnik handlowy,
2. silnik predykcyjny,
3. silnik komunikacyjny,
4. silnik emisji LIVE,
5. silnik nauki i raportowania.

# 5. Zasady projektowe wysokiego poziomu

## 5.1 Integralność ponad efekt
Najpierw poprawna logika, potem efekt wizualny. Ładny overlay nie może przykrywać błędów execution.

## 5.2 Jedna odpowiedzialność na moduł
Każdy moduł ma konkretny zakres odpowiedzialności. Jeśli dwa moduły liczą to samo, to dokument musi wskazać, który liczy kanonicznie, a który tylko konsumuje wynik.

## 5.3 Dane kanoniczne, nie domysły
Każdy komunikat dla użytkownika, lektora, bloga lub live musi być oparty na kanonicznym stanie zapisanym w systemie, a nie na luźnej interpretacji.

## 5.4 Czytelność dla początkującego
Opis, lektor, blog i podstawowe komunikaty mają być zrozumiałe dla osoby początkującej. Techniczne szczegóły mogą istnieć, ale jako warstwa druga.

## 5.5 Predykcja ma wpływać na handel
Forecast 15–20 minut nie może być dekoracją. Musi wpływać na wejścia, wyjścia, trailing, score jakości setupu i opłacalność po kosztach.

## 5.6 Każda decyzja ma przyczynę
System musi umieć odpowiedzieć: dlaczego kupił, dlaczego sprzedał, dlaczego czekał, dlaczego odrzucił wejście.

## 5.7 Każda decyzja wraca do uczenia
Każdy trade, brak trade’u, spóźnione wyjście, fałszywy breakout i oddany zysk stają się materiałem do nauki.

## 5.8 Warstwa publiczna nigdy nie uprzedza rdzenia
Najpierw system podejmuje decyzję i ją zapisuje. Dopiero potem UI, lektor, Telegram i blog mogą to ogłosić.

# 6. Anti-chaos dla VS Code / Copilot / agentów AI

Ta sekcja jest krytyczna. Jej celem jest ograniczenie sytuacji, w której AI lub programista miesza wątki i dokonuje zmian bez pełnego obrazu.

## 6.1 Jeden dokument źródłowy
Ten dokument jest dokumentem nadrzędnym. Każdy większy patch ma wskazywać:
- które rozdziały zmienia,
- które moduły dotyka,
- czy zmienia kontrakt danych,
- czy wymaga migracji,
- czy wpływa na live / blog / Telegram / execution.

## 6.2 Zakaz „cichych skrótów”
Nie wolno:
- dodać lokalnego pola do endpointu bez aktualizacji kontraktu,
- stworzyć drugiego score’u o tej samej nazwie i innym znaczeniu,
- generować tekstów z pominięciem explanation hub,
- rysować prognoz w UI z użyciem prywatnej logiki frontendowej.

## 6.3 Obowiązkowy nagłówek dla każdego większego patcha
Każdy większy patch tworzony przez AI lub człowieka powinien zaczynać się od bloku:
- Cel zmiany
- Zakres zmiany
- Moduły dotknięte
- Kontrakty danych dotknięte
- Ryzyka
- Testy do uruchomienia
- Potencjalny wpływ na inne warstwy

To ogranicza przypadki „poprawiono, ale nie wiadomo co”.

## 6.4 Zakaz edycji bez wskazania źródła kanonicznego
Jeżeli istnieje pytanie „gdzie to powinno być liczone?”, odpowiedź musi odwołać się do konkretnego modułu kanonicznego zdefiniowanego w tym dokumencie.

## 6.5 Zasada patchy pionowych
Preferowane są poprawki pionowe, które domykają cały przepływ dla jednego problemu:
- dane,
- decyzja,
- execution,
- komunikat,
- test.

Nie preferuje się patchy, które dodają tylko napis w UI bez rozwiązania logiki.

## 6.6 Dziennik architektoniczny
W repo powinien istnieć plik typu `ARCHITECTURE_DECISIONS.md` lub `PROJECT_AUDIT_MASTER.md`, w którym zapisuje się:
- decyzje architektoniczne,
- ich uzasadnienie,
- datę,
- wpływ na moduły,
- status wdrożenia.

## 6.7 Jedna nazwa, jedno znaczenie
Przykład:
- `confidence` nie może raz oznaczać „pewności kierunku”, a innym razem „pewności całej decyzji”.
Trzeba rozbić pojęcia:
- `direction_confidence`
- `continuation_confidence`
- `profitability_confidence`
- `execution_confidence`
- `overall_decision_confidence`

## 6.8 Wyraźne granice pomiędzy „stanem” a „prezentacją”
Modele danych rdzenia nie mogą zawierać ozdobnej logiki prezentacyjnej. Z drugiej strony frontend nie może samodzielnie wytwarzać logiki, której nie ma w rdzeniu.

# 7. Architektura logiczna systemu

Docelowa architektura składa się z dziewięciu głównych hubów:

1. `market_data_hub`
2. `feature_hub`
3. `prediction_hub`
4. `decision_hub`
5. `execution_hub`
6. `state_hub`
7. `explanation_hub`
8. `broadcast_hub`
9. `learning_hub`

Poniżej opis roli każdego z nich.

# 8. Market Data Hub

## 8.1 Rola
To jedyne miejsce odpowiedzialne za pobieranie, normalizację i walidację danych rynkowych.

## 8.2 Zakres danych
- ticki cenowe,
- świece OHLCV,
- order book,
- wolumen,
- spread,
- fee i koszty transakcyjne,
- pozycje i salda z giełdy,
- statusy zleceń,
- funding rate,
- open interest,
- dane korelacyjne,
- dane pomocnicze: sentyment, news events, whale events.

## 8.3 Zasady
- dane są znaczone czasem pobrania i czasem zdarzenia,
- dane muszą przejść walidację świeżości,
- dane mają postać kanoniczną niezależnie od źródła,
- żaden inny moduł nie pobiera surowych danych „na boku”, jeśli nie zostało to jawnie przewidziane.

## 8.4 Odpowiedzialność
Market Data Hub nie interpretuje rynku. On dostarcza czysty stan wejściowy.

## 8.5 Kluczowe ryzyka
- duplikacja źródeł,
- rozjazd czasowy,
- mieszanie danych real-time i danych historycznych,
- brak oznaczania stanu świeżości.

## 8.6 Wymagania jakościowe
- jednoznaczne typy danych,
- walidacja braków,
- fallbacki tylko jawne,
- logowanie opóźnień,
- możliwość replayu z archiwów danych.

# 9. Feature Hub

## 9.1 Rola
Feature Hub zamienia surowe dane rynkowe na cechy analityczne i kontekst używany przez predykcję oraz decyzję.

## 9.2 Przykładowe cechy
- EMA 9 / 21 / 50 / 200,
- slope średnich,
- RSI,
- MACD,
- ATR,
- Bollinger Bands,
- VWAP,
- volume anomaly,
- order book imbalance,
- liquidity zones,
- support / resistance,
- breakout probability features,
- market regime,
- trend regime,
- volatility regime,
- pair profile features,
- correlation with BTC / ETH,
- session context,
- time-of-day context.

## 9.3 Zasada kanoniczności
Jeżeli jakaś cecha jest liczona w Feature Hub, nie wolno przeliczać jej osobno w UI, blogu, Telegramie ani w warstwie lektora.

## 9.4 Wersjonowanie
Feature set musi być wersjonowany. Jeżeli zmienia się definicja cechy, trzeba móc odtworzyć, na których danych i której wersji działał model oraz decyzja.

## 9.5 Wymagania
- deterministyczność,
- logowanie braków,
- odporność na opóźnienia,
- możliwość odtworzenia z replayu.

# 10. Prediction Hub

## 10.1 Rola
Prediction Hub odpowiada za przewidywanie ruchu rynku w horyzoncie 15–20 minut oraz za dodatkowe warstwy jakości sygnału.

## 10.2 Co powinien przewidywać
Nie tylko przyszłą cenę, ale zestaw zmiennych:
- kierunek,
- zasięg ruchu,
- czas do ruchu,
- prawdopodobieństwo kontynuacji,
- prawdopodobieństwo zanegowania,
- prawdopodobieństwo fake breakout,
- expected net move after costs,
- confidence i uncertainty band.

## 10.3 Dlaczego to ważne
Jedna linia „price forecast” jest zbyt uboga do sterowania handlem. Silnik decyzji potrzebuje rozumieć nie tylko „gdzie może pójść cena”, ale:
- czy ruch ma sens po kosztach,
- czy jest trwały,
- czy może się szybko odwrócić,
- jak duża jest niepewność.

## 10.4 Typy modeli
Dokument nie narzuca jednego modelu, ale zaleca architekturę wielowarstwową:
- model tabularny do szybkiego scoringu wejścia,
- model sekwencyjny do forecastu czasowego,
- model wykrywania fałszywych wybić,
- meta-model łączący wyniki.

## 10.5 Zasada biznesowa
Prediction Hub nie handluje. Prediction Hub dostarcza ocenę przyszłego ruchu i jakości setupu.

## 10.6 Wymagania operacyjne
- aktualizacja forecastu cyklicznie,
- jawne oznaczenie czasu wygenerowania,
- confidence decay wraz ze starzeniem predykcji,
- przechowywanie poprzednich forecastów do porównania.

## 10.7 Output kanoniczny
Każda predykcja powinna zwracać co najmniej:
- `symbol`
- `forecast_timestamp`
- `horizon_minutes`
- `direction_label`
- `direction_confidence`
- `expected_move_pct`
- `expected_net_move_pct_after_costs`
- `continuation_probability`
- `reversal_probability`
- `false_breakout_probability`
- `forecast_path`
- `uncertainty_band`
- `forecast_quality_score`
- `model_version`

# 11. Decision Hub

## 11.1 Rola
Decision Hub to mózg decyzji handlowej. Łączy:
- cechy rynku,
- predykcję,
- koszty,
- ryzyko,
- stan pozycji,
- zasady strategii.

## 11.2 Co produkuje
- action: buy / wait / hold / reduce / sell / skip,
- entry zone,
- target zone,
- stop zone,
- trailing rules,
- minimal sensible capital,
- opportunity score,
- profitability score,
- risk score,
- reasons,
- scenario set.

## 11.3 Zasada
To jedyne miejsce, które ma prawo powiedzieć: „wchodzimy”, „wychodzimy”, „czekamy”.

## 11.4 Powody decyzji
Każda decyzja musi mieć:
- krótką listę powodów kanonicznych,
- wersję prostą dla laika,
- wersję techniczną dla logów i bloga.

## 11.5 Obsługa scenariuszy
Zalecane są trzy scenariusze:
- bazowy,
- ostrożny,
- awaryjny.

To poprawia zarówno handel, jak i narrację LIVE.

## 11.6 Integracja z forecastem
Decision Hub nie może ignorować Prediction Hub. Forecast ma wpływać na:
- otwieranie pozycji,
- targety,
- trailing,
- wcześniejsze wyjścia,
- blokadę wejścia przy niskim edge.

# 12. Execution Hub

## 12.1 Rola
Execution Hub realizuje zatwierdzone decyzje:
- wystawia zlecenia,
- monitoruje fill,
- aktualizuje stan pozycji,
- obsługuje wyjścia,
- pilnuje TP/SL/trailing,
- reaguje na anulacje lub zmianę scenariusza.

## 12.2 Zasady
- execution nie tworzy własnej strategii,
- execution nie ogłasza samodzielnie komunikatów użytkownikowi,
- execution emituje zdarzenia stanu, które trafiają do State Hub.

## 12.3 Kluczowy wymóg
Komunikacja publiczna ma następować po potwierdzeniu execution, nie przed.

## 12.4 Obsługa wyjątków
Execution musi mieć jawne ścieżki dla:
- partial fill,
- order rejected,
- delayed fill,
- stale price before fill,
- exchange outage,
- risk block after signal.

# 13. State Hub

## 13.1 Rola
State Hub przechowuje i udostępnia kanoniczny stan systemu. To centralny magazyn aktualnej prawdy.

## 13.2 Co przechowuje
Na poziomie pary:
- aktualną cenę,
- trend,
- forecast,
- decision state,
- position state,
- risk state,
- reasons,
- broadcast-ready summary,
- timestamps.

Na poziomie systemu:
- aktywne pozycje,
- aktywne analizy,
- watchlist,
- pinned pairs,
- health stanu,
- last events,
- statistics for live.

## 13.3 Po co istnieje
Aby wszystkie interfejsy i warstwy prezentacyjne korzystały z tego samego obiektu stanu.

## 13.4 Zasada
Żaden frontend nie powinien składać sobie stanu z pięciu różnych endpointów, jeśli istnieje gotowy obiekt kanoniczny.

# 14. Explanation Hub

## 14.1 Rola
Explanation Hub zamienia kanoniczne decyzje i stany na zrozumiałe komunikaty:
- dla UI,
- dla lektora,
- dla Telegrama,
- dla bloga,
- dla raportów.

## 14.2 Kluczowa zasada
Wyjaśnienia mają pochodzić z decyzji systemu, a nie z domysłów warstwy prezentacyjnej.

## 14.3 Warstwy języka
Każdy komunikat powinien mieć kilka wersji:
- wersja prosta,
- wersja standard,
- wersja techniczna,
- wersja krótka overlay,
- wersja TTS.

## 14.4 Styl
Wersja prosta ma być zrozumiała dla początkującego. Zamiast:
„bullish breakout z potwierdzeniem wolumenowym”,
system może powiedzieć:
„cena rośnie i widać większy ruch kupujących, ale bot czeka jeszcze na potwierdzenie”.

## 14.5 Ograniczenia
Explanation Hub nie może mówić o buy, jeśli buy nie został zapisany przez Decision / Execution flow.

# 15. Broadcast Hub

## 15.1 Rola
Broadcast Hub dystrybuuje gotowe, zatwierdzone informacje do:
- strony live,
- studia testowego,
- Telegrama,
- overlay streamowego,
- bloga,
- logów audytowych.

## 15.2 Zasady
- zero prywatnej logiki biznesowej,
- tylko konsumpcja kanonicznego stanu i wyjaśnień,
- priorytetyzacja komunikatów,
- filtrowanie duplikatów,
- harmonogram disclaimerów.

## 15.3 Typy komunikatów
- soft update,
- action alert,
- risk alert,
- forecast update,
- opportunity highlight,
- disclaimer,
- session summary.

# 16. Learning Hub

## 16.1 Rola
Learning Hub zbiera dane zwrotne o skuteczności systemu i karmi nimi modele oraz reguły.

## 16.2 Co zapisuje
- stan rynku w momencie decyzji,
- forecast,
- confidence,
- reasons,
- execution result,
- outcome po 1/3/5/10/15/20 minutach,
- net PnL po kosztach,
- giveback zysku,
- czy signal był poprawny,
- czy wyjście było spóźnione,
- czy setup był dobry, ale execution słaby.

## 16.3 Dlaczego to kluczowe
System nie ma się uczyć „ładnego wykresu”, tylko jakości decyzji.

## 16.4 Zastosowanie
- retrening modeli,
- kalibracja progów,
- pair profiles,
- ranking jakości par,
- wykrywanie godzin o słabszej skuteczności.

# 17. Kanoniczny model obiektu pary

Każda para powinna mieć ujednolicony obiekt stanu. Przykładowe pola:

- symbol
- last_price
- price_change_1m
- price_change_5m
- price_change_15m
- trend_state
- momentum_score
- volatility_state
- liquidity_state
- spread_state
- whale_state
- opportunity_score
- profitability_score
- risk_score
- direction_forecast_15m
- direction_forecast_20m
- forecast_path_15m
- forecast_path_20m
- forecast_band
- overall_decision_confidence
- direction_confidence
- continuation_confidence
- profitability_confidence
- recommended_action
- entry_zone
- target_zone
- stop_zone
- minimal_sensible_capital
- plan_summary_short
- plan_summary_plain
- reasons_short
- reasons_full
- position_state
- current_pnl_net
- last_state_transition
- last_broadcast_id
- data_freshness_seconds
- model_version
- feature_version

Taki obiekt ma być podstawą dla UI, live, lektora i bloga.

# 18. Event-driven architecture

## 18.1 Dlaczego eventy
System wielowarstwowy bez eventów łatwo wpada w chaos zależności. Eventy porządkują przepływ.

## 18.2 Kluczowe zdarzenia
- market_tick_received
- candle_closed
- feature_vector_updated
- forecast_updated
- decision_changed
- entry_signal_armed
- order_submitted
- order_filled
- position_updated
- exit_signal_triggered
- position_closed
- narration_ready
- overlay_ready
- disclaimer_due
- blog_story_ready
- learning_snapshot_recorded

## 18.3 Zasada
Każde ważne przejście stanu powinno być zapisane jako event z timestampem i payloadem.

# 19. Maszyny stanów

## 19.1 Stan pary
- idle
- watching
- setup_forming
- entry_ready
- entering
- in_position
- exit_watch
- exiting
- closed
- blocked

## 19.2 Stan narracji
- silent
- soft_update
- major_update
- action_alert
- risk_alert
- disclaimer_due

## 19.3 Stan live focus
- passive_display
- highlighted_pair
- urgent_attention
- pinned_focus
- replay_mode

## 19.4 Zysk
Maszyny stanów dają:
- lepszą czytelność,
- mniej wyjątków ukrytych w if-ach,
- łatwiejsze testy,
- mniejsze ryzyko mylenia warunków.

# 20. Sekcja LIVE — cele biznesowe i UX

Sekcja LIVE nie jest zwykłym dashboardem. Ma jednocześnie:
- pokazywać aktywne pary,
- tłumaczyć decyzje,
- wyglądać dobrze na streamie,
- być zrozumiała dla początkującego,
- być spójna z execution,
- wspierać zaufanie do systemu.

## 20.1 Główne cele sekcji LIVE
1. natychmiastowa czytelność,
2. widoczność aktywnych okazji,
3. centralne okno dla aktualnie analizowanej pary,
4. jasne oznaczenie: kup / czekaj / trzymaj / sprzedaj,
5. widoczne forecasty 15–20 min,
6. widoczny disclaimer,
7. prosty komentarz tekstowy i głosowy.

# 21. Układ sekcji LIVE na telefonie

## 21.1 Górny pasek aktywnych par
Powinien pokazywać:
- symbol,
- live status,
- cena,
- strzałkę kierunku,
- zmianę procentową,
- entry target plan,
- confidence.

To ma być szybki „ticker decyzji”.

## 21.2 Główne okno analizowanej pary
W centrum:
- nazwa pary,
- cena live,
- status decyzji,
- wykres,
- linia predykcji 15 min i 20 min,
- uncertainty band,
- wskaźniki,
- entry / target / stop,
- plan,
- prosty opis.

## 21.3 Karta decyzji
Pod wykresem:
- trend,
- opłacalność,
- aktualny plan,
- sensowna kwota wejścia,
- powody decyzji,
- ryzyko.

## 21.4 Sekcja pinned pairs
Pary stałe, uproszczone, klikane:
- symbol,
- cena,
- mini trend,
- status,
- uproszczony sygnał.

## 21.5 Sekcja watchlist / queue
Lista okazji, które są blisko wejścia:
- za wcześnie,
- prawie gotowe,
- wymaga potwierdzenia,
- odrzucone przez koszty,
- zablokowane ryzykiem.

# 22. Wskaźniki i warstwa wykresu

Na wykresie głównym zaleca się:
- świece,
- volume,
- EMA 9/21/50/200,
- RSI,
- MACD,
- VWAP,
- Bollinger,
- support / resistance,
- oznaczenie wejść i wyjść,
- targety,
- trailing line,
- forecast path,
- uncertainty band,
- markery whale / anomaly.

Ważne: interfejs nie ma wyświetlać wszystkiego naraz na siłę. Potrzebny jest system warstw i przełączników widoczności.

# 23. Forecast overlay 15–20 minut

## 23.1 Rola
Pokazywać przewidywaną ścieżkę ruchu, nie jako obietnicę, tylko jako scenariusz.

## 23.2 Elementy
- forecast line 15m,
- forecast line 20m,
- uncertainty band,
- invalidation level,
- scenariusz alternatywny.

## 23.3 Zasada biznesowa
Overlay forecastu musi być podpisany jako analiza RLdC, nie gwarancja wyniku.

# 24. Lektor LIVE i system TTS

## 24.1 Rola
Lektor ma mówić prostym językiem, w rytmie zdarzeń, bez spamowania.

## 24.2 Co ma czytać
- kluczowe zmiany stanu,
- wejścia i wyjścia,
- zmiany trendu,
- wykrycie ryzyka,
- wykrycie dużego ruchu,
- okresowe wyjaśnienia,
- disclaimer.

## 24.3 Czego nie robić
- nie czytać wszystkiego,
- nie mówić zbyt technicznie,
- nie gadać non stop,
- nie uprzedzać execution.

## 24.4 Pipeline
State -> Explanation -> Narration Queue -> TTS -> Audio Output.

## 24.5 Kolejka i priorytety
Priorytety:
1. action alert,
2. risk alert,
3. major market shift,
4. soft update,
5. disclaimer.

## 24.6 Minimalny odstęp
Musi istnieć minimalny odstęp czasowy pomiędzy komunikatami oraz filtr duplikatów.

## 24.7 Styl języka
Język ma być prosty, naturalny, zrozumiały:
- „bot czeka”
- „cena rośnie”
- „ryzyko wzrosło”
- „ten ruch może się cofnąć”
- „na razie wejście jest za drogie”

# 25. Disclaimery i bezpieczeństwo komunikacyjne

## 25.1 Dlaczego są obowiązkowe
System publicznie pokazujący handel i analizy musi stale przypominać:
- że to nie gwarantuje zysku,
- że można stracić kapitał,
- że kopiowanie odbywa się na własne ryzyko,
- że RLdC nie ponosi odpowiedzialności za decyzje użytkownika.

## 25.2 Warstwy disclaimerów
1. stały pasek ostrzegawczy,
2. pełny komunikat okresowy,
3. ekran wejścia / start live,
4. stopka sekcji analizy,
5. blog i raporty.

## 25.3 Przykład skrócony
„Analizy RLdC nie gwarantują zysku. Inwestujesz i kopiujesz na własne ryzyko.”

## 25.4 Przykład pełny
„Materiały, wskazówki, analizy, wizualizacje, komentarze oraz transmisje RLdC mają charakter informacyjny i edukacyjny. Nie stanowią porady inwestycyjnej ani obietnicy osiągnięcia zysku. Rynek jest zmienny i możesz stracić część lub całość kapitału. Każde kopiowanie działań odbywa się na własne ryzyko użytkownika. RLdC nie ponosi odpowiedzialności za skutki decyzji inwestycyjnych podejmowanych na podstawie prezentowanych treści.”

# 26. RLdC Live Studio — środowisko testowe transmisji

## 26.1 Cel
Oddzielna sekcja do sprawdzania LIVE przed spięciem z serwisami zewnętrznymi.

## 26.2 Co musi zawierać
- preview TikTok 9:16,
- preview YouTube 16:9,
- replay historyczny,
- tryb symulacji,
- podgląd komunikatów lektora,
- test disclaimera,
- test overlayów,
- nagrywanie próbki,
- test responsywności.

## 26.3 Dlaczego to ważne
Pozwala wykryć problemy:
- chaos ekranu,
- złe proporcje,
- zbyt częste komunikaty,
- nieczytelność forecastu,
- nakładające się warstwy tekstu,
- brak synchronizacji audio-video.

## 26.4 Osobne widoki
- `/live`
- `/live/studio`
- `/live/studio/audio`
- `/live/studio/replay`
- `/live/disclaimer`

# 27. Blog RLdC

## 27.1 Rola bloga
Blog ma być dziennikiem działania i nauki systemu:
- osiągnięcia,
- błędy,
- wnioski,
- analizy,
- wyjaśnienia,
- raporty dzienne i tygodniowe.

## 27.2 Zasada
Blog nie może zmyślać. Musi korzystać z tego samego rdzenia co execution i live.

## 27.3 Typy wpisów
- raport dzienny,
- raport tygodniowy,
- najlepsza transakcja dnia,
- najgorsza decyzja dnia,
- czego bot się nauczył,
- wyjaśnienia dla początkujących,
- case study ruchu rynku,
- wpis o błędzie i poprawce.

## 27.4 Struktura wpisu
- tytuł,
- lead,
- podsumowanie prostym językiem,
- część techniczna,
- dane liczbowe,
- screen lub wykres,
- wnioski,
- disclaimer.

## 27.5 Wartość
Blog buduje:
- zaufanie,
- SEO,
- materiał do sociali,
- materiał do nauki i audytu,
- transparentność.

# 28. Replay i odtwarzanie decyzji

## 28.1 Cel
Możliwość odtworzenia:
- co widział bot,
- co przewidział,
- co zdecydował,
- co zrobił execution,
- co powiedział live,
- co wydarzyło się naprawdę.

## 28.2 Zastosowanie
- debugowanie,
- trenowanie modeli,
- tworzenie wpisów blogowych,
- analiza błędów,
- generowanie nagrań demo.

## 28.3 Co przechowywać
- snapshot rynku,
- cechy,
- forecast,
- decyzję,
- execution events,
- komunikaty,
- wynik.

# 29. Pinned pairs i watchlist

## 29.1 Pinned pairs
To para przypięta ręcznie przez użytkownika. Powinna być pokazywana stale w sekcji uproszczonej.

## 29.2 Watchlist
To lista par obserwowanych dynamicznie przez system z powodami:
- blisko wejścia,
- za wcześnie,
- niski wolumen,
- słaba opłacalność,
- wysoki risk score.

## 29.3 Zasada
Pinned pairs nie zastępują watchlisty. To dwa różne byty.

# 30. Whale / crowd / anomaly radar

## 30.1 Cel
Wykrywanie:
- dużych zleceń,
- anomalii wolumenowych,
- absorpcji,
- spoofingu,
- nienaturalnego order flow,
- sygnałów, że „grube ryby” mogą sterować ruchem.

## 30.2 Prezentacja
- prosty status na ekranie,
- marker na wykresie,
- opcjonalny komunikat lektora,
- wpływ na risk score oraz explanation.

# 31. System „sensownej kwoty wejścia”

## 31.1 Dlaczego potrzebny
Dla początkującego użytkownika sama informacja „kup” jest niewystarczająca. Trzeba wiedzieć, czy wejście ma sens po kosztach.

## 31.2 Co liczyć
- fee,
- spread,
- poślizg,
- expected net gain,
- minimalny sensowny kapitał,
- rekomendowany zakres wejścia.

## 31.3 Efekt
Lepsza edukacja i mniejsza liczba nierozsądnych wejść kopiujących.

# 32. Frontend — struktura komponentów

Przykładowe komponenty:
- LivePairsTicker
- PrimaryPairPanel
- PredictionChart
- AIDecisionCard
- TrendSummaryCard
- RiskPanel
- WhaleRadar
- OpportunityQueue
- PinnedPairsGrid
- DisclaimerBanner
- NarrationSubtitleBar
- BlogHighlightsPanel
- ReplayControls
- StudioPreviewSwitcher

Każdy komponent ma konsumować stan, a nie liczyć własną logikę biznesową.

# 33. Backend — sugerowany podział modułów

Przykładowe moduły backendowe:
- `market_data_hub.py`
- `feature_hub.py`
- `prediction_engine.py`
- `decision_engine.py`
- `execution_engine.py`
- `state_store.py`
- `explanation_engine.py`
- `broadcast_engine.py`
- `learning_engine.py`
- `whale_detection_service.py`
- `pair_profile_service.py`
- `forecast_overlay_service.py`
- `narration_queue.py`
- `tts_service.py`
- `blog_story_builder.py`
- `replay_service.py`
- `disclaimer_service.py`

# 34. API i WebSocket

## 34.1 REST do odczytu stanu
- `/api/live/overview`
- `/api/live/primary-symbol`
- `/api/live/pinned`
- `/api/live/watchlist`
- `/api/live/blog/highlights`
- `/api/live/replay/{session_id}`
- `/api/studio/settings`

## 34.2 Strumienie WebSocket
- `pairs_tick`
- `state_updates`
- `forecast_updates`
- `decision_updates`
- `execution_updates`
- `narration_updates`
- `whale_alerts`
- `disclaimer_updates`

## 34.3 Zasada
WebSocket ma dostarczać zmiany stanu, ale kontrakt danych ma być spójny z REST.

# 35. Model danych dla bloga

Blog korzysta z eventów typu:
- trade_closed_profit
- trade_closed_loss
- forecast_hit
- forecast_miss
- giveback_detected
- whale_event_detected
- daily_summary_ready
- weekly_summary_ready
- model_improved
- bug_pattern_detected

Na ich bazie generowane są drafty wpisów.

# 36. Persistencja i baza danych

## 36.1 Tabele / byty logiczne
- market_snapshots
- feature_snapshots
- forecasts
- decisions
- execution_events
- positions
- cost_ledgers
- pair_profiles
- narration_events
- broadcast_events
- disclaimers_log
- learning_outcomes
- replay_sessions
- blog_posts
- blog_drafts
- blog_assets

## 36.2 Zasady
- wszystko oznaczone czasem,
- wersjonowanie modeli,
- wersjonowanie cech,
- brak nadpisywania bez śladu,
- możliwość audytu.

# 37. Testy i jakość

## 37.1 Poziomy testów
- testy jednostkowe,
- testy kontraktów danych,
- testy replay,
- testy event flow,
- testy renderu live studio,
- testy jakości narracji,
- testy spójności execution vs broadcast.

## 37.2 Szczególnie ważne testy
1. Jeśli decyzja zmienia się na BUY, czy execution i broadcast reagują właściwie.
2. Czy lektor nie ogłasza niepotwierdzonego fill.
3. Czy disclaimer pojawia się zgodnie z harmonogramem.
4. Czy pinned pairs i watchlist nie mieszają się logicznie.
5. Czy forecast line używa tej samej predykcji co decision hub.
6. Czy blog pobiera net PnL po kosztach, a nie brutto.

# 38. Obserwowalność i monitoring

Trzeba mierzyć:
- stale data rate,
- forecast drift,
- action-to-broadcast latency,
- execution confirmation latency,
- stale message rate,
- narration spam rate,
- sync mismatch count,
- profit giveback rate,
- false entry rate,
- expected vs realized net gain.

# 39. Fazy wdrożenia

## Etap 1 — rdzeń i porządek
- uporządkowanie hubów,
- kontrakty danych,
- state hub,
- eventy,
- explanation hub.

## Etap 2 — live i studio
- live layout,
- pinned pairs,
- forecast overlay,
- disclaimer banner,
- studio preview.

## Etap 3 — lektor
- narration queue,
- TTS,
- harmonogram komunikatów,
- anti-spam.

## Etap 4 — blog i replay
- story builder,
- replay snapshots,
- raporty dzienne,
- wpisy o błędach.

## Etap 5 — learning loop
- pełny feedback,
- kalibracja modeli,
- pair profiles,
- adaptive thresholds.

# 40. Akceptacja biznesowa

System można uznać za spójny dopiero wtedy, gdy spełnia łącznie:
- live pokazuje to, co system naprawdę robi,
- forecast wpływa na handel,
- execution nie rozmija się z narracją,
- komunikaty są zrozumiałe dla początkującego,
- disclaimery są stale obecne,
- blog pokazuje wyniki i błędy bez zmyślania,
- replay pozwala odtworzyć krytyczne decyzje,
- AI wspomagające kodowanie ma jasną mapę odpowiedzialności.

# 41. Najczęstsze antywzorce, których trzeba unikać

1. Frontend liczy własne score’y.
2. Lektor mówi na podstawie lokalnego stanu UI.
3. Blog korzysta z ręcznie składanych danych.
4. Forecast jest dekoracją bez wpływu na decision hub.
5. Dwie warstwy liczą koszty inaczej.
6. Telegram używa innych nazw stanów niż web.
7. Pinned pairs stają się substytutem watchlisty.
8. Brak wersjonowania forecastów i feature setów.
9. Patch AI dotyka wiele modułów bez określenia zakresu.
10. Brak replayu dla trudnych przypadków.

# 42. Zalecenia dla promptów do VS Code / Copilot

Każdy większy prompt wdrożeniowy powinien zawierać:
- streszczenie celu,
- odwołanie do rozdziałów dokumentu,
- listę plików kanonicznych,
- zakaz tworzenia równoległej logiki,
- wymóg aktualizacji testów,
- wymóg aktualizacji kontraktów danych,
- wymóg raportu ryzyk po zmianie.

Przykładowa formuła:
„Pracuj wyłącznie w granicach modułów X, Y, Z. Nie twórz równoległego źródła prawdy. Jeśli brakuje danych, rozszerz kontrakt kanoniczny zamiast dodawać lokalny fallback w UI.”

# 43. Minimalny zestaw dokumentów towarzyszących

Poza tym dokumentem projekt powinien mieć:
- `PROJECT_AUDIT_MASTER.md`
- `ARCHITECTURE_DECISIONS.md`
- `DATA_CONTRACTS.md`
- `EVENT_CATALOG.md`
- `STATE_MACHINE_MAP.md`
- `TEST_MATRIX.md`
- `LIVE_COPY_GUIDE.md`
- `BLOG_STYLE_GUIDE.md`

# 44. Wniosek końcowy

Największa przewaga RLdC nie ma polegać na tym, że „coś przewiduje”, ale na tym, że:
- przewiduje w sposób mierzalny,
- wykorzystuje predykcję w handlu,
- pokazuje to publicznie w czytelnej formie,
- tłumaczy decyzje prostym językiem,
- uczy się na skutkach swoich działań,
- raportuje sukcesy i błędy,
- zachowuje spójność wszystkich warstw.

Ten dokument opisuje drogę do systemu, który nie jest zlepkiem ekranów, tylko spójnym, audytowalnym organizmem.

# 45. Lista kontrolna przed każdym większym wdrożeniem

- Czy zmiana dotyka jednego źródła prawdy czy tworzy nowe?
- Czy zmiana wymaga aktualizacji kontraktów?
- Czy explanation i live pozostaną spójne z execution?
- Czy blog i replay będą nadal działały na tych samych danych?
- Czy dodano testy dla nowego przejścia stanu?
- Czy istnieje ryzyko duplikacji logiki?
- Czy disclaimery nadal pojawiają się poprawnie?
- Czy początkujący użytkownik nadal zrozumie komunikat?
- Czy VS Code / Copilot dostaną wystarczająco jasny zakres prac?
- Czy zmiana poprawia integralność, a nie tylko wygląd?

# 46. Podsumowanie wykonawcze

Rekomendowany kierunek dla RLdC można streścić jednym zdaniem:

**Budujemy jeden, zintegrowany rdzeń handlowo-predykcyjno-komunikacyjny, z którego karmione są LIVE, lektor, blog, replay, Telegram i dashboard — bez dublowania logiki i bez rozjazdów danych.**

Wdrożenie takiego podejścia:
- ograniczy chaos,
- zmniejszy liczbę błędów wynikających z mylenia wątków,
- poprawi jakość handlu,
- poprawi jakość komunikacji,
- zwiększy czytelność projektu dla ludzi i AI,
- stworzy solidną podstawę do dalszego rozwoju RLdC.


# 47. Załącznik A — zalecana struktura repozytorium

Poniżej przykładowa struktura logiczna repozytorium, która ogranicza mieszanie odpowiedzialności i ułatwia nawigację agentom AI:

- `backend/`
  - `core/`
    - `market_data_hub.py`
    - `feature_hub.py`
    - `prediction_engine.py`
    - `decision_engine.py`
    - `execution_engine.py`
    - `state_store.py`
    - `learning_engine.py`
  - `services/`
    - `whale_detection_service.py`
    - `pair_profile_service.py`
    - `cost_profitability_service.py`
    - `forecast_overlay_service.py`
    - `replay_service.py`
    - `disclaimer_service.py`
  - `communication/`
    - `explanation_engine.py`
    - `broadcast_engine.py`
    - `narration_queue.py`
    - `tts_service.py`
    - `telegram_publisher.py`
    - `blog_story_builder.py`
  - `routers/`
    - `live.py`
    - `studio.py`
    - `blog.py`
    - `account.py`
    - `portfolio.py`
    - `control.py`
  - `schemas/`
    - `market.py`
    - `features.py`
    - `forecast.py`
    - `decision.py`
    - `execution.py`
    - `state.py`
    - `blog.py`
  - `events/`
    - `catalog.py`
    - `publisher.py`
    - `subscribers.py`
  - `storage/`
    - `models.py`
    - `repositories.py`
    - `migrations/`
  - `tests/`
    - `unit/`
    - `contracts/`
    - `replay/`
    - `integration/`
    - `live/`
    - `blog/`
- `frontend/`
  - `src/components/live/`
  - `src/components/studio/`
  - `src/components/blog/`
  - `src/components/shared/`
  - `src/state/`
  - `src/api/`
  - `src/pages/`
- `docs/`
  - `RLdC_SPECYFIKACJA_GLOWNA.md`
  - `DATA_CONTRACTS.md`
  - `EVENT_CATALOG.md`
  - `STATE_MACHINE_MAP.md`
  - `TEST_MATRIX.md`
  - `LIVE_COPY_GUIDE.md`
  - `BLOG_STYLE_GUIDE.md`

Ta struktura nie jest obowiązkowa co do nazwy folderów, ale jest obowiązkowa co do logiki: warstwa rdzenia, komunikacja, routingi, schematy i testy nie mogą być wymieszane w losowych plikach.

# 48. Załącznik B — standard nazewnictwa i typów

## 48.1 Nazwy pól
Nazwy mają być jednoznaczne i pełne. Unikać skrótów bez definicji. Przykład:
- dobre: `expected_net_move_pct_after_costs`
- złe: `move2`

## 48.2 Nazwy akcji
Lista akcji ma być skończona i opisana:
- `BUY`
- `WAIT`
- `HOLD`
- `REDUCE`
- `SELL`
- `SKIP`
- `BLOCKED`

Nie wolno wprowadzać synonimów typu `WATCH_AND_WAIT`, `SOFT_HOLD`, `LIGHT_SELL`, jeśli nie zostały opisane w kontrakcie.

## 48.3 Nazwy stanów
Stany mają być wspólne dla web, Telegrama, live i replay. Jeżeli UI potrzebuje innej etykiety, to korzysta z mapowania prezentacyjnego, a nie zmienia stanu kanonicznego.

## 48.4 Typy czasowe
Każdy timestamp ma mieć:
- strefę czasową,
- nazwę znaczenia,
- źródło czasu.

Przykład:
- `event_time_utc`
- `exchange_time_utc`
- `ingested_at_utc`
- `broadcasted_at_utc`

# 49. Załącznik C — przykładowe kontrakty danych

## 49.1 Forecast contract
Przykładowy kształt payloadu forecastu:

```json
{
  "symbol": "SOLUSDC",
  "forecast_timestamp_utc": "2026-04-23T06:10:00Z",
  "horizon_minutes": 15,
  "direction_label": "UP",
  "direction_confidence": 0.78,
  "continuation_probability": 0.71,
  "reversal_probability": 0.19,
  "false_breakout_probability": 0.22,
  "expected_move_pct": 1.24,
  "expected_net_move_pct_after_costs": 0.83,
  "forecast_quality_score": 81,
  "uncertainty_band": {
    "lower_pct": -0.35,
    "upper_pct": 1.55
  },
  "forecast_path": [
    {"minute": 1, "price": 86.02},
    {"minute": 5, "price": 86.21},
    {"minute": 10, "price": 86.48},
    {"minute": 15, "price": 86.79}
  ],
  "model_version": "pred_v3_2",
  "feature_version": "feat_v5_1"
}
```

## 49.2 Decision contract
Przykładowy payload decyzji:

```json
{
  "symbol": "SOLUSDC",
  "decision_timestamp_utc": "2026-04-23T06:10:01Z",
  "recommended_action": "WAIT",
  "entry_zone": {"min": 85.90, "max": 86.05},
  "target_zone": {"min": 86.70, "max": 86.95},
  "stop_zone": {"min": 85.20, "max": 85.35},
  "minimal_sensible_capital": 45.0,
  "opportunity_score": 79,
  "profitability_score": 74,
  "risk_score": 41,
  "direction_confidence": 0.78,
  "overall_decision_confidence": 0.69,
  "reasons_short": [
    "trend rośnie",
    "wolumen powyżej średniej",
    "wejście jeszcze niepotwierdzone"
  ],
  "reasons_full": [
    "Cena utrzymuje się powyżej EMA21 i EMA50",
    "Wolumen świecy 5m jest wyższy od średniej sesyjnej",
    "Order book pokazuje przewagę kupujących, ale bez pełnego wybicia"
  ],
  "plain_language_summary": "Cena rośnie, ale bot czeka na lepszy moment wejścia.",
  "decision_version": "dec_v2_4"
}
```

## 49.3 Narration contract
Przykładowy payload komunikatu lektora:

```json
{
  "message_id": "nar_20260423_061005_sol_wait",
  "priority": "SOFT_UPDATE",
  "symbol": "SOLUSDC",
  "text_overlay": "Bot czeka na potwierdzenie wejścia na SOL.",
  "text_tts": "SOL rośnie, ale bot czeka jeszcze na potwierdzenie wejścia.",
  "valid_from_utc": "2026-04-23T06:10:05Z",
  "expires_at_utc": "2026-04-23T06:10:45Z",
  "source_decision_id": "dec_abc123",
  "dedupe_key": "SOLUSDC_WAIT_CONFIRMATION"
}
```

# 50. Załącznik D — standard wpisów blogowych

Każdy automatyczny lub półautomatyczny wpis powinien mieć następujący szkielet:

1. Tytuł
2. Lead
3. Podsumowanie prostym językiem
4. Co zrobił bot
5. Dlaczego tak zrobił
6. Co wydarzyło się naprawdę
7. Czy forecast był trafny
8. Wynik netto po kosztach
9. Czego bot się nauczył
10. Co to znaczy dla początkującego
11. Disclaimer

Dzięki temu blog nie staje się chaotyczą tablicą ogłoszeń, tylko powtarzalnym, czytelnym produktem.

# 51. Załącznik E — checklista dla patcha przygotowywanego przez AI

Przed zaakceptowaniem patcha wygenerowanego przez VS Code / Copilot / innego agenta należy sprawdzić:

- Czy patch dotyka tylko zadeklarowanych plików?
- Czy nie wprowadza nowego źródła prawdy?
- Czy używa istniejących kontraktów danych?
- Czy aktualizuje testy?
- Czy aktualizuje dokumentację kontraktów, jeśli zmienia payload?
- Czy nie dubluje logiki w frontendzie?
- Czy nie generuje prywatnych wyjątków nazw stanów?
- Czy lektor, blog i live nadal bazują na tych samych danych?
- Czy dodano logowanie dla nowych przejść stanu?
- Czy patch ma jasny opis ryzyk?

# 52. Załącznik F — checklista przed wypuszczeniem nowej wersji LIVE

Przed wypuszczeniem nowej wersji sekcji LIVE należy sprawdzić:

- Czy dane na ekranie są świeże?
- Czy forecast overlay pokazuje aktualny model i aktualną wersję?
- Czy komunikaty lektora nie dublują się?
- Czy disclaimer jest stale widoczny?
- Czy ostrzeżenie pełne odtwarza się zgodnie z harmonogramem?
- Czy entry / target / stop pochodzą z Decision Hub?
- Czy wypełniono test podglądu TikTok 9:16?
- Czy wypełniono test podglądu YouTube 16:9?
- Czy pinned pairs działają poprawnie po kliknięciu?
- Czy replay daje się odtworzyć dla ostatniej sesji?

# 53. Załącznik G — macierz odpowiedzialności

Dla ograniczenia chaosu warto utrzymywać prostą macierz odpowiedzialności:

- Market Data Hub: pobiera i normalizuje dane.
- Feature Hub: liczy cechy.
- Prediction Hub: przewiduje ruch i niepewność.
- Decision Hub: podejmuje decyzje handlowe.
- Execution Hub: wykonuje decyzje.
- State Hub: przechowuje kanoniczny stan.
- Explanation Hub: tłumaczy stan i decyzję.
- Broadcast Hub: rozsyła gotowe komunikaty.
- Learning Hub: zapisuje outcome i uczy system.

Jeżeli w kodzie pojawia się funkcja, której nie da się przypisać do jednego z tych bytów, trzeba rozważyć, czy nie mamy już chaosu architektonicznego.

# 54. Załącznik H — minimalny workflow pracy wdrożeniowej

Każda większa zmiana powinna przechodzić przez ten sam, prosty workflow:

1. Zdefiniuj problem.
2. Wskaż rozdziały tego dokumentu, których dotyczy.
3. Wskaż moduł kanoniczny odpowiedzialny za problem.
4. Przygotuj patch o ograniczonym zakresie.
5. Uruchom testy jednostkowe i kontraktowe.
6. Uruchom replay lub integrację, jeśli zmiana dotyczy execution / live.
7. Sprawdź zgodność komunikatów z explanation hub.
8. Sprawdź zgodność blog / replay / live.
9. Zapisz zmianę w dzienniku architektonicznym.
10. Dopiero wtedy scalaj.

# 55. Załącznik I — rekomendacja końcowa dla dalszych prac

Najlepszy następny krok po przyjęciu tego dokumentu to rozbicie wdrożenia na trzy artefakty robocze:

1. Techniczna mapa modułów i plików do refaktoryzacji.
2. Katalog kontraktów danych z przykładami payloadów.
3. Matryca testów obejmująca execution, live, narration, disclaimery, blog i replay.

Dopiero na tej podstawie warto generować duże prompty do VS Code / Copilot. Bez tych trzech artefaktów rośnie ryzyko, że agent AI będzie nadal mylił wątki, naprawiał niewłaściwe pliki albo rozwiązywał objaw zamiast przyczyny.
