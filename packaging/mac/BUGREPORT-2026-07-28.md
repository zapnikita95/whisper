# Bugreport — WhisperClient macOS (2026-07-28)

## Симптомы
1. После успешной расшифровки через **свой сервер** приложение периодически «отваливается» (иконка пропадает / нужен рестарт). Retry и сервер при этом работают.
2. Groq через Layero: в UI «Связь OK» при **HTTP 404**; при отправке аудио — XML `MethodNotAllowed` (CDN/S3, не Groq).

## Доказательства из логов
Файл: `~/Library/Containers/com.zapnikita95.WhisperClient/Data/Library/Logs/WhisperMacNative.log`

- `2026-07-28 08:01:25` — `text len=1920 route=server` + «готово», затем сразу короткая запись `bytes=4096`, которая **перезаписала** `last_take`.
- `2026-07-28 08:06:32` — «готово — Thank you.» → `08:07:50 started` (рестарт ~78 с спустя).
- `notification auth granted=0` — уведомления запрещены; клиент звал `osascript` на каждый notify.
- Crash `.ips` за период не найдены → скорее sandbox kill / silent terminate, не ObjC exception dump.

## Корневые причины
| # | Причина | Эффект |
|---|---------|--------|
| A | `NSTask` → `/usr/bin/osascript` в App Sandbox после каждой расшифровки | deny process-exec → процесс убивается |
| B | `processing=NO` сразу после deliver, до Cmd+V (120–450 мс) | Fn стартует AVAudioEngine во время paste → гонка/обрыв |
| C | `preserve last_take` без порога размера | клик Fn (4 KB) затирает нормальную запись |
| D | Тест связи: `200 ≤ code < 500` | **404 считался OK** |
| E | Layero edge на POST → XML `MethodNotAllowed` / таймауты | Groq через прокси ломается; Railway origin при этом жив |

## Исправления (build **1.3.1 / 52**)
- Убран osascript; только `UserNotifications` (без trigger-таймера).
- `finishProcessingAfterDelay:` — `processing` держится до конца paste (~0.45 с).
- `preserveTakeForRetry` игнорирует файлы &lt; 8 KB.
- CGEventTap → `ListenOnly` (не фильтрующий tap).
- `@try/@catch` вокруг pipeline / engine stop / deliver UI.
- Тест прокси: только **2xx**; 404 = ошибка.
- Прокси Layero по умолчанию **OFF** (включать вручную, когда зеркало живое).

## Регрессии для проверки
1. Запись 30–120 с → сервер → текст вставляется, иконка остаётся, без рестарта.
2. Сразу после «готово» ещё раз Fn — не должно ронять; короткий клик не затирает retry.
3. «Повторить расшифровку» после обрыва сети.
4. Настройки → Проверить связь при выключенном прокси / при 404 прокси — не «Связь OK».
