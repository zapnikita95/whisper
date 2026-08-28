# Bugreport / hotfix — WhisperClient 1.4.1 (build **63**) — 2026-08-28

## Симптомы
После ~1–7 минут простоя после «готово» menubar «отваливается»: клик по 🎤 не стартует запись, нужен ручной рестарт.
На Windows стабильно; на Mac (MAS / TestFlight, sandbox) — нет.

## Доказательства (лог контейнера)
`~/Library/Containers/com.zapnikita95.WhisperClient/Data/Library/Logs/WhisperMacNative.log`

- 237 стартов vs 3 user quit — процесс умирает/замораживается без `applicationShouldTerminate`.
- `PreventAppNap` assertion **всегда** `rc=-536870206` (NotPrivileged) в App Sandbox.
- LaunchAgent KeepAlive в MAS был **отключён** («sandbox: skip LaunchAgent»).
- Watchdog `tap dead` / `statusItem recreate` = **0** за всё время → либо App Nap freeze, либо SIGKILL без логов.
- Типичный gap после последнего «готово»: 93–600 с.

## Фикс (build **63**)
| # | Изменение |
|---|-----------|
| A | Silent `AVAudioPlayer` loop (vol=0) — обход App Nap в sandbox; пауза на время записи |
| B | MAS `SMAppService` agent `Contents/Library/LaunchAgents/…keepalive.plist` с KeepAlive (SuccessfulExit=NO) |
| C | Heartbeat 15 с: renew NSActivity, re-enable `CGEventTap` (только если Input Monitoring OK), rewire клики, pulse-лог каждые ~2 мин |
| D | Убран бесполезный PreventAppNap (sandbox NotPrivileged) и display-sleep IOPM |
| E | Single-instance guard + SIGTERM/INT/ABRT → лог |

## Локальный smoke (build 62 dev-подпись)
- `silent keep-alive audio loop ON`
- через ~2 мин: `heartbeat pulse tap=0 audio=1` (tap=0 из‑за другой code signature / Input Monitoring; в MAS TF будет trusted)
- процесс жив после idle

## TestFlight
Upload build **63** (1.4.1). После установки:

1. Меню → версия `1.4.1 (63)`.
2. System Settings → General → Login Items → разреши **Whisper Client** / keepalive, если спросит.
3. Запись → «готово» → **не трогай 10+ минут** → клик 🎤 снова должен писать.
4. В логе каждые ~2 мин: `heartbeat pulse tap=1 audio=1`.

## Ограничения
- KeepAlive agent требует approval в Login Items (один раз).
- Silent audio не трогает микрофон (только output loop vol=0).
