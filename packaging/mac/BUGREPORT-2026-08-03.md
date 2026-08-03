# Bugreport / hotfix — WhisperClient 1.3.1 (build **53**) — 2026-08-03

## Симптомы
1. Клиент «отваливается» / рестартует; Groq таймаутится из РФ.
2. Layero прокси: «Адрес свободен» (проект удалён), Railway из РФ недоступен.

## Что сделано
| # | Фикс |
|---|------|
| A | Layero зеркало заново: `https://whisper-groq-proxy.layero.app` (smoke POST → 200) |
| B | Прокси **ON** по умолчанию + one-shot миграция prefs b53 |
| C | Fallback proxy ↔ direct Groq |
| D | Нет alloc в audio tap на каждый буфер; нет afconvert/NSTask в sandbox |
| E | UN notify: не спамим при denied; cancel URLSession на timeout |
| F | TestFlight upload build **53** |

## Проверка
1. Меню → версия `1.3.1 (53)`, прокси ON.
2. Настройки → Проверить связь → Layero OK (2xx).
3. Запись 30–120 с → текст вставляется, иконка остаётся.
4. Сразу после «готово» Fn — не роняет; «Повторить расшифровку» работает.
