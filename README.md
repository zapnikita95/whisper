# Распознавание речи (RU / EN)

Стек: **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** — те же веса Whisper, но инференс через CTranslate2: обычно быстрее и заметно экономнее по VRAM, чем `openai-whisper` на PyTorch.

## Рекомендация под ~5 ГБ VRAM

| Модель       | Режим (`--compute-type`) | Качество      | VRAM (ориентир) |
|-------------|---------------------------|---------------|-----------------|
| **large-v3** | `int8` (по умолчанию)     | очень хорошее | ~3–4 ГБ         |
| large-v3    | `int8_float16`            | чуть лучше    | до ~5 ГБ        |
| medium      | `float16`                 | хорошее       | ~2–3 ГБ         |

Если видеокарта занята другими задачами: `--device cpu --compute-type int8` (без VRAM, медленнее).

**Заметка:** связка `tiny` + `int8` + CUDA в CTranslate2 иногда даёт пустой текст; для GPU бери `medium` / `large-v3` или `float16`.

## Пресеты моделей (оригинал и русский fine-tune)

`faster-whisper` грузит репозитории с **раскладкой CTranslate2** на Hugging Face. Чисто PyTorch-веса без конверсии в этот формат **напрямую** не подставлять.

| Что на HF | Заметка |
|-----------|---------|
| [antony66/whisper-large-v3-russian](https://huggingface.co/antony66/whisper-large-v3-russian) | Полный **large-v3** (не turbo), fine-tune под русский; ориентир по WER — в карточке модели. |
| [dvislobokov/whisper-large-v3-turbo-russian](https://huggingface.co/dvislobokov/whisper-large-v3-turbo-russian) | База **large-v3-turbo** (меньше параметров, быстрее) — **другой** размер/скорость vs полный large-v3; сравнивать по своим тестам и метрикам на HF. |
| [pav88/whisper-large-v3-russian-ct2](https://huggingface.co/pav88/whisper-large-v3-russian-ct2) | CT2-версия для faster-whisper (в проекте пресет **`ru-ct2-pav88`**). |
| [bzikst/faster-whisper-large-v3-russian](https://huggingface.co/bzikst/faster-whisper-large-v3-russian) | Альтернативная CT2-сборка (**`ru-ct2-bzikst`**). |

Список ключей — в `whisper_models.py`. **Окно WhisperServer (Windows):** выбери модель в списке и нажми **«Запустить сервер»**. Консоль: `set WHISPER_MODEL=ru-ct2-pav88` перед запуском или `whisper-server.py --model ru-ct2-pav88`. Для hotkey то же через `WHISPER_MODEL` или `--model`.

## Установка

Нужны **Python 3.10+** и драйвер NVIDIA. Полный [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) не обязателен: в `requirements.txt` есть пакет **nvidia-cublas-cu12** (DLL для cuBLAS 12, ~550 МБ). Скрипт `transcribe.py` сам добавляет его `bin` в `PATH` на Windows.

### Виртуальное окружение вне OneDrive

Папка проекта на OneDrive часто **блокирует** файлы в `.venv` при установке pip. Окружение создано здесь:

`%USERPROFILE%\.venvs\faster-whisper`

Переустановка с нуля:

```powershell
$venv = "$env:USERPROFILE\.venvs\faster-whisper"
python -m venv $venv
& "$venv\Scripts\python.exe" -m pip install -U pip
& "$venv\Scripts\pip.exe" install -r "$env:USERPROFILE\OneDrive\Desktop\whisper\requirements.txt"
```

Первый запуск с выбранной моделью скачает веса в кэш Hugging Face (`%USERPROFILE%\.cache\huggingface`).

### Symlinks в кэше HF (предупреждение Windows)

Чтобы не плодить дубликаты на диске, можно включить [режим разработчика Windows](https://learn.microsoft.com/windows/apps/get-started/enable-your-device-for-development) или задать `setx HF_HUB_DISABLE_SYMLINKS_WARNING 1`.

## Запуск

Из папки проекта:

```powershell
.\run-transcribe.ps1 "D:\audio\запись.mp3"
```

Или напрямую:

```powershell
& "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe" .\transcribe.py "файл.mp3"
```

Опции:

```text
--model large-v3
--device cuda
--compute-type int8
--language ru
--vad
```

Пример только английского: `--language en`. Автоопределение языка — не передавай `--language`.

## Горячая клавиша (запись с микрофона)

Скрипт **`whisper-hotkey.py`**: **зажми Ctrl+Win** — идёт запись (короткий звуковой сигнал), **отпусти** — распознавание и вставка текста в активное поле (или буфер обмена).

### Самый простой запуск (батник)

- **С окном** (выбор модели, статус): **`start-whisper-hotkey-gui.bat`** или **`WhisperHotkey.exe`** после установки **`WhisperHotkeySetup-*.exe`**.
- **Консоль** (логи в чёрном окне): **`start-whisper-hotkey.bat`**. Если прав администратора нет, Windows сама спросит подтверждение (нужно для глобального перехвата клавиш).

### Запуск из PowerShell

```powershell
cd $env:USERPROFILE\OneDrive\Desktop\whisper
.\run-hotkey.ps1
```

Или напрямую:

```powershell
& "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe" .\whisper-hotkey.py
```

### Использование

1. Оставь окно консоли открытым.
2. Встань курсором в поле ввода (Блокнот, браузер и т.д.).
3. **Зажми Ctrl+Win** — услышишь **бип**, говори столько, сколько нужно.
4. **Отпусти** обе клавиши — текст появится (или будет в буфере обмена).

Пока идёт распознавание предыдущей фразы, новую запись не начать — подожди пару секунд.

### Произносимая пунктуация

После распознавания слова заменяются на знаки (без учёта регистра):

| Скажи | Вставится |
|--------|-----------|
| запятая | , |
| точка | . |
| тире | — (длинное тире) |
| восклицательный знак | ! |
| вопросительный знак | ? |

Отключить замену: флаг **`--no-spoken-punctuation`**.

Whisper иногда пишет фразу с ошибкой («восклицательный» без «знак») — тогда замена может не сработать; можно повторить чётче.

### Опции

```powershell
.\run-hotkey.ps1 --language ru
.\run-hotkey.ps1 --model medium
.\run-hotkey.ps1 --max-hold 180
.\run-hotkey.ps1 --no-spoken-punctuation
```

### Как это работает

- Запись идёт **пока зажаты Ctrl и Win** (лимит по времени: `--max-hold`, по умолчанию 120 с).
- Транскрипция — **faster-whisper**.
- Текст вставляется через эмуляцию клавиатуры; дублируется в **буфер обмена**.

## Использование GPU с Mac (клиент-сервер)

Если на Mac мало видеопамяти, можно запустить **сервер на Windows** (использует GPU), а на Mac — **клиент** (запись + отправка на сервер).

### На Windows (сервер)

1. Запусти сервер (консоль):
   ```powershell
   .\start-server.bat
   ```
   **Или окно с портом, подсказкой по Ctrl+Win и списком HTTP-клиентов (Mac и др.):**
   ```powershell
   .\start-server-gui.bat
   ```
   В GUI сначала выбери **модель** (оригинал `large-v3` или русский CT2-пресет), затем **«Запустить сервер»**; выбор сохраняется в `whisper_gui_prefs.json` рядом с exe/скриптом.
   Или напрямую:
   ```powershell
   & "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe" .\whisper-server.py --host 0.0.0.0 --port 8000
   ```
   Логика API в модуле `whisper_server.py`; `whisper-server.py` — тонкий shim для старых путей. Эндпоинт `GET /clients` — кто недавно вызывал `POST /transcribe` (IP + заголовок `X-Whisper-Client`, например `mac`).

2. **Tailscale:** IP Windows в сети **меняется**; в `start-client-mac.command` по умолчанию заложен старый пример. Если «сервер не найден»:
   - узнай IPv4 ПК в Tailscale и запусти: `./start-client-mac.command 'http://ТВОЙ_IP:8002'` (порт как в окне `start-server.bat`);
   - или `export WHISPER_SERVER_IP=ТВОЙ_IP` и снова `.command`;
   - или один раз создай `server_url.txt` с одной строкой `http://IP:ПОРТ`;
   - или `server_ip.txt` только с IP, порт по-прежнему ищется 8000–8010 / берётся из `server_port.txt`.
   **Если локальная сеть:** узнай IP через `ipconfig` (IPv4-адрес, например `192.168.1.100`).

**Важно:** убедись, что брандмауэр Windows разрешает входящие подключения на порт 8000, или временно отключи его для теста.

### На Mac (клиент)

1. Установи зависимости:
   ```bash
   pip3 install requests sounddevice numpy soundfile 'pynput>=1.8.1' pyperclip
   pip3 install rumps   # рекомендуется: иконка 🎤/🔴 в строке меню (запись/обработка); `pick_python_for_whisper` выберет Python, где есть rumps, если таких несколько. Отключить: `--no-menu-bar` или `WHISPER_MAC_NO_MENU=1`
   ```

2. Скопируй `whisper-client-mac.py` на Mac.

3. **Приложение (Finder):** после клонирования собери копию скриптов внутрь `.app`:
   ```bash
   ./packaging/build_mac_app.sh
   ```
   Затем открой `packaging/mac/WhisperClient.app`. **CFBundleExecutable** — не bash, а маленький **Mach-O stub** (`whisper_stub.c`), иначе Finder даёт ошибку вроде «нет разрешения открыть (null)». Скрипт `run.sh` подставляет PATH с Homebrew и проверяет pip-модули. Нужны **Xcode Command Line Tools** (`clang`) для сборки. Иконка: `assets/AppIcon.icns`. Перегенерация из PNG: `./packaging/regenerate_icons.sh`. Свой Python: `WHISPER_PYTHON3` (см. `packaging/mac/run.sh`). После правок `whisper-client-mac.py`: `./packaging/build_mac_app.sh`.

   **Почему не было иконки 🎤:** из Finder клиент выбирал **первый** подходящий Python (часто Homebrew), а `pip3 install rumps` ты ставил в **python.org** (`/Library/Frameworks/...`) — в том интерпретаторе `import rumps` был `None`, меню не поднималось. Сейчас для `.app` порядок поиска: **сначала Python.org 3.13/3.12**, потом Homebrew; плюс при отсутствии rumps показывается **диалог** с точной командой `…/python3 -m pip install rumps`. Если поток хоткея падает, клиент **перезапускает** его и шлёт уведомление (процесс не должен «тихо исчезать» из‑за мёртвого listener).

4. **Простой способ (скрипт):** двойной клик на `start-client-mac.command` в Finder  
   **Или из терминала:**
   ```bash
   chmod +x start-client-mac.command  # один раз
   ./start-client-mac.command
   ```

   **`[forkpty: Device not configured]` / «pseudo-tty»:** это не скрипт, а среда без настоящего терминала (часто **Run** в **Cursor**). Запускай из **Terminal.app** (`./start-client-mac.command`) или двойным кликом в **Finder**. Если `.command` открывается в Cursor: **Сведения** → «Открывать в программе» → **Terminal** → «Изменить всё…». Скрипт при отсутствии TTY сам вызывает `open -a Terminal`.

   **Иконка в Dock «думает» полминуты:** раньше поиск сервера шёл по портам по очереди (~33 с). Сейчас **параллельный** опрос в `pick_server_url.py` + выбор первого **Python, где уже стоят pip-зависимости** (`pick_python_for_whisper.sh`). IP Windows в Tailscale: **`export WHISPER_MAC_SERVER_HOST=…`** перед запуском или URL аргументом. Если сервер не найден, `start-client-mac.command` всё равно стартует с `http://$HOST:8000` (можно сменить вручную).

   **Или напрямую:**
   ```bash
   python3 whisper-client-mac.py --server 'http://TAILSCALE_IP:ПОРТ'
   ```

5. При запуске **в терминале** клиент спросит сочетание одной строкой (через `+`); **Enter** без ввода = **⌃+⇧+⌥** (`shift+ctrl+alt`) — **только модификаторы**: в текст **не вставляется символ** (в отличие от варианта с клавишей *grave* / backtick) и **не дёргается** типичный шорткат Cursor «терминал» на **⌃+⇧+`**. **Portal:** по-прежнему без ⌘. Удерживай сочетание — запись, отпусти все клавиши — распознавание. Альтернативы:
   - без вопроса: `--no-hotkey-prompt` (или переменная **`WHISPER_MAC_HOTKEY`**);
   - сразу строкой: `--hotkey 'shift+ctrl+alt'` (умолчание), `--hotkey 'shift+ctrl+grave'` (если нужен старый вариант), `--hotkey 'alt+ctrl'`, `--hotkey 'ctrl+]'`;
   - **WhisperClient.app:** хоткей по умолчанию задаётся в `packaging/mac/run.sh` (`export WHISPER_MAC_HOTKEY=…`), чтобы не тянуть случайный export из Терминала.
   - «нажми и запомни»: `--bind-hotkey`.

   **Вместе с [Portal](https://github.com/zapnikita95/portal) на том же Mac:** см. **[PORTAL_AND_WHISPER_MAC.md](PORTAL_AND_WHISPER_MAC.md)** (права «Мониторинг ввода», порядок запуска, pynput 1.8+).

   **Отладка вставки / сервера:** файл **`~/Library/Logs/WhisperMacClient.log`** (строки с **`[WHISPER_MAC]`**). Вставка идёт в приложение, которое было **активным в момент начала записи** (перед Cmd+V фокус возвращается туда). Если в буфере мусор — в логе будет `clipboard_mismatch` или `paste_target_captured`. Полный текст распознавания в лог: `WHISPER_MAC_DEBUG=1`.

   **Уведомления и «молчит после фразы»:** после `build_mac_app.sh` в бандле есть **`whisper_notify`** — баннеры в Центре уведомлений идут **от бинаря внутри .app** (не от «Python»). Показываются: старт из Finder, «отправка на сервер» (из .app), **готово** с превью текста, пустой ответ, ошибки сети. Отключить всё: `WHISPER_MAC_NO_NOTIFICATIONS=1`. Только убрать «готово»: `WHISPER_MAC_NOTIFY_SUCCESS=0`. Прогресс «отправка…» в терминале по умолчанию выключен; из .app включён; принудительно: `WHISPER_MAC_NOTIFY_PROGRESS=1`.

### Опции клиента

```bash
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --language ru
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --no-spoken-punctuation
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --no-hotkey-prompt
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --hotkey 'ctrl+grave'
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --bind-hotkey
python3 whisper-client-mac.py --enroll-speaker ~/Desktop/calibration.wav   # только эталон, без --server
python3 whisper-client-mac.py --server 'http://…' --speaker-verify
```

### Как это работает

- Mac записывает аудио с микрофона.
- Отправляет WAV на Windows-сервер по HTTP.
- Сервер обрабатывает на GPU (Whisper).
- Возвращает текст.
- Mac вставляет текст через AppleScript.

**Примечание:** если обработка идёт, новая запись не начнётся автоматически (чтобы избежать зависаний).

### Два установщика Windows (релиз по тегу `v*`)

В [GitHub Actions](.github/workflows/release.yml) на тег **`v1.2.3`** собираются:

| Файл в релизе | Назначение |
|---------------|------------|
| **`WhisperSetup-{версия}.exe`** | **Сервер** — GPU HTTP API для Mac и других клиентов (`WhisperServer.exe`). |
| **`WhisperHotkeySetup-{версия}.exe`** | **Локальный клиент** — трей + Ctrl+Win, уведомления, лог `whisper_hotkey.log` (`WhisperHotkey.exe`). |

Локально после PyInstaller: `ISCC.exe packaging\windows\WhisperServer.iss` и `ISCC.exe packaging\windows\WhisperHotkey.iss` (см. ниже).

### Упаковка: exe без консоли (Windows)

#### С нуля: окружение и сборка

Нужны **Python 3.10+** (команда `python` в PATH) и **NVIDIA + драйвер** для GPU. Venv создаётся в **`%USERPROFILE%\.venvs\faster-whisper`** (вне OneDrive).

**Скрипт `packaging\setup-venv-and-build.ps1`** (путь к репо поправь при необходимости):

```powershell
$W = "$env:USERPROFILE\OneDrive\Desktop\whisper"

# Только venv + pip + pyinstaller (без сборки exe)
powershell -ExecutionPolicy Bypass -File "$W\packaging\setup-venv-and-build.ps1" -Build None

# Сборка только сервера (WhisperServer.exe)
powershell -ExecutionPolicy Bypass -File "$W\packaging\setup-venv-and-build.ps1" -Build Server

# Сборка только hotkey (WhisperHotkey.exe, трей)
powershell -ExecutionPolicy Bypass -File "$W\packaging\setup-venv-and-build.ps1" -Build Hotkey

# Оба exe подряд
powershell -ExecutionPolicy Bypass -File "$W\packaging\setup-venv-and-build.ps1" -Build Both

# Скачать все пресеты в кэш Hugging Face + оба exe (долго, нужен интернет)
powershell -ExecutionPolicy Bypass -File "$W\packaging\setup-venv-and-build.ps1" -Build Both -DownloadModels
```

Скачать модели отдельно (venv уже есть):

```powershell
& "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe" "$W\scripts\download_whisper_models.py" --device cuda --compute-type int8
```

#### Логи отладки

| Файл | Когда |
|------|--------|
| **`whisper_server.log`** | HTTP-сервер (`whisper_server.py` / `WhisperServer.exe`), ротация ~2 МБ, строки сразу пишутся на диск. |
| **`%TEMP%\WhisperServer_last_run.log`** | То же самое для сервера — дубль, чтобы не искать каталог с exe (удобно из GUI без консоли). |
| **`whisper_hotkey.log`** | Hotkey (консоль и трей / `WhisperHotkey.exe`). |

Пока в логе висит строка про **импорт faster_whisper** — HTTP ещё не поднят: это загрузка CUDA/CTranslate2 (часто десятки секунд и дольше), не «сломался» API. После **«Uvicorn принимает HTTP»** `GET /` начинает отвечать; **`ready: true`** в JSON — только после первой загрузки весов модели (обычно при первом `POST /transcribe`). Окно **Whisper GPU Server** ждёт ответ API до **~5 минут** (раньше обрывалось через ~60 с и показывало ложный «нет ответа»). Если в **`whisper_server.log`** есть «Импорт faster_whisper завершён», но **нет** строки «**Uvicorn принимает HTTP**» — пересобери **WhisperServer.exe** (исправлен запуск uvicorn из фонового потока: `WindowsSelectorEventLoopPolicy` и отключение записи uvicorn в stderr в windowed-сборке).

Каталог логов: рядом с exe или скриптом; переопределение: **`WHISPER_LOG_DIR=C:\путь`**.

Hotkey: отключить всплывающие уведомления — **меню трея «Уведомления»** или **`WHISPER_HOTKEY_NO_NOTIFICATIONS=1`**. Без стартового тоста: **`WHISPER_HOTKEY_SILENT_START=1`**. Одинаковые и слишком частые тосты режутся (антиспам); **уже показанные** баннеры в Центре уведомлений Windows приложение не «отзывает» — их можно **очистить вручную** (Параметры → Система → Уведомления) или отключить уведомления для приложения.

---

**Если копируешь команды вручную — только целиком этот блок, подряд** (не по одной строке: иначе переменные пустые и всё ломается). Если папка проекта не `OneDrive\Desktop\whisper` — поменяй **первую** строку `$Repo`.

```powershell
$Repo = "$env:USERPROFILE\OneDrive\Desktop\whisper"
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.venvs" | Out-Null
python -m venv "$env:USERPROFILE\.venvs\faster-whisper"
& "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe" -m pip install -U pip
Set-Location $Repo
& "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe" -m pip install -r .\requirements.txt
& "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe" -m pip install pyinstaller
.\packaging\build-server-gui-exe.bat
.\packaging\build-hotkey-gui-exe.bat
```

После успешной сборки:

- Запускай **`dist\WhisperServer\WhisperServer.exe`** (и hotkey: **`dist\WhisperHotkey\WhisperHotkey.exe`**).
- Рядом обязательно лежит папка **`_internal`** — копируй/переноси **всю** папку `dist\WhisperServer` / `dist\WhisperHotkey`, а не один файл.

**Ошибка `Failed to load Python DLL` … `build\…\_internal\python312.dll`:** ты запускаешь **не тот** exe. PyInstaller кладёт **рабочую** сборку только в **`dist\`**. Папка **`build\`** — временная, оттуда запуск **нельзя**. Открой именно `dist\WhisperServer\` или `dist\WhisperHotkey\`.

**Сборка сервера: `PermissionError` / WinError 5 при `Removing dir dist\WhisperServer`:** папка занята — **закрой `WhisperServer.exe`**, закрой **Проводник** в `dist\WhisperServer`, при необходимости пауза антивируса. Батник `packaging\build-server-gui-exe.bat` собирает сначала в **`dist\.whisper_stage`**, затем переносит в `dist\WhisperServer`. Если перенос не вышел, запускай **`dist\.whisper_stage\WhisperServer\WhisperServer.exe`** или выполни **`packaging\promote-whisper-server-dist.bat`** после освобождения папки.

Если **из `dist\`** та же ошибка — поставь [VC++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe) и перенеси всю папку с exe с OneDrive на локальный диск (синк иногда портит DLL).

Повторные сборки: шаги 4–6 (или только 6, если зависимости не менялись).

#### Сборка Whisper Hotkey (локальный Ctrl+Win)

Тот же venv, что и для сервера:

```powershell
.\packaging\build-hotkey-gui-exe.bat
```

Результат: **`dist\WhisperHotkey\WhisperHotkey.exe`** (+ `_internal`): **иконка в трее**, уведомления (старт, запись, результат, ошибки). Запуск **от имени администратора**. Без сборки: **`start-whisper-hotkey-gui.bat`**.

**Проверка голоса (как на Mac):** тот же эталон **`%USERPROFILE%\.whisper\speaker_embedding.npy`**. В трее: **«Записать эталон голоса (~45 с)…»** и пункт **«Проверка голоса»** (после переключения — перезапуск hotkey). Либо **`WHISPER_SPEAKER_VERIFY=1`** и опционально **`WHISPER_SPEAKER_THRESHOLD`**. Сборка **`packaging\build-hotkey-gui-exe.bat`** сама ставит **`packaging\requirements-speaker-windows-pyi.txt`** и **resemblyzer** (без MSVC: заглушка **webrtcvad** в **`speaker_verify.py`**). На Mac/Linux по-прежнему **`requirements-speaker.txt`**. Сообщение в логе про **cuBLAS** (`cublas64_12.dll`) пишет **`whisper_hotkey_core`** — попадает в exe после пересборки; при отсутствии DLL: **`pip install nvidia-cublas-cu12`** в venv.

Консольный вариант: `whisper-hotkey.py` / `start-whisper-hotkey.bat` → тот же **`whisper_hotkey.log`**, флаги **`--speaker-verify`** / **`--speaker-threshold`**.

#### Коротко по шагам (сервер)

1. В том же venv, где стоят `fastapi`, `faster-whisper`, `uvicorn`: `pip install pyinstaller`.
2. В репозитории желательно есть `assets\app_icon.ico` (собирается на Mac: `packaging/regenerate_icons.sh` или кладётся вручную); без иконки сборка всё равно пройдёт, если в батнике нет файла.
3. Запусти `packaging\build-server-gui-exe.bat` — получишь **onedir** `dist\WhisperServer\WhisperServer.exe` (рядом папка `_internal`). Первый запуск exe может быть долгим из‑за CTranslate2 и загрузки модели.
4. Запуск **двойным кликом по WhisperServer.exe** — окно с выбором модели, портом, **статусом API (онлайн / модель / веса)** и списком HTTP‑клиентов; `server_port.txt` создаётся в той же папке, что и exe. Для автозагрузки — ярлык на этот exe.

Чтобы **вообще не открывать батники**, достаточно **WhisperServer.exe** (GUI) для сервера и **WhisperClient.app** на Mac после `build_mac_app.sh`.

### Простая инструкция (Word)

- Открой в Word: **[docs/ИНСТРУКЦИЯ_Whisper_Mac_Windows.html](docs/ИНСТРУКЦИЯ_Whisper_Mac_Windows.html)** → «Файл» → «Сохранить как» → `.docx` при необходимости.

### Версия

- Источник правды: **`packaging/VERSION`** (строка `1.2.0`). В CI при теге `v*` файл перезаписывается из имени тега.
- `GET /` возвращает **`app_version`**; окно **WhisperServer** и меню Mac показывают ту же версию.
- Переопределение: переменная окружения **`WHISPER_VERSION`**.

### Релизы GitHub Actions

При push тега вида **`v1.2.3`** workflow [`.github/workflows/release.yml`](.github/workflows/release.yml):

1. Собирает **Windows**: PyInstaller → **Inno Setup** → `WhisperSetup-{версия}.exe` и **`WhisperHotkeySetup-{версия}.exe`**.
2. Собирает **macOS**: `build_mac_app.sh` → **create-dmg** → `dist/release/WhisperClient-{версия}.dmg`.
3. Прикрепляет **WhisperSetup**, **WhisperHotkeySetup** и DMG к **GitHub Release** для этого тега.

Локально Inno: установи [Inno Setup](https://jrsoftware.org/isinfo.php), затем после PyInstaller:

`"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\WhisperServer.iss /DMyAppVersion=1.2.0`

`"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\WhisperHotkey.iss /DMyAppVersion=1.2.0`

Локально DMG: `brew install create-dmg` → `./packaging/mac/make_dmg.sh`.

### Автообновление

- **Windows (GUI):** через ~10 с после старта запрашивается GitHub `releases/latest`; если тег новее `packaging/VERSION`, предлагается скачать **`WhisperSetup-*.exe`** и запустить. Отключить: **`WHISPER_SKIP_UPDATE_CHECK=1`**. Другой репозиторий: **`WHISPER_RELEASES_REPO=owner/name`**.
- **Mac (меню 🎤):** пункт **«Проверить обновления…»** — скачивает **`WhisperClient-*.dmg`** в `~/Downloads` (или открывает страницу релиза). Фоновое напоминание раз в сессию (~2 мин), если есть более новый тег.

Имена вложений в релизе: **`WhisperSetup`** (`.exe`) и **`WhisperClient`** (`.dmg`) — так автообновление сервера и Mac их находит. Второй установщик **`WhisperHotkeySetup`** — локальный hotkey, ставится отдельно.

### Верификация говорящего (опционально)

**Из .app (без Терминала):** меню 🎤 → **Записать эталон голоса (45 с)…** (нужны `torch` + `resemblyzer`, см. HTML-инструкцию). Если файл **`~/.whisper/speaker_embedding.npy`** уже есть, **`run.sh`** внутри .app выставляет **`WHISPER_SPEAKER_VERIFY=1`** автоматически. Отключить автоматику: **`WHISPER_MAC_NO_SPEAKER_VERIFY=1`** в `packaging/mac/run.sh` перед сборкой.

**Через Терминал:** `pip install -r requirements-speaker.txt`, затем `python3 whisper-client-mac.py --enroll-speaker ./мой.wav` (без `--server`). Порог: **`WHISPER_SPEAKER_THRESHOLD`** или **`--speaker-threshold`**.

**Сервер:** **`WHISPER_SPEAKER_VERIFY=1`** + тот же формат эталона на диске Windows → при несовпадении **HTTP 403**.

## Файлы

| Файл | Назначение |
|------|------------|
| `transcribe.py` | CLI: файл → текст в консоль |
| `whisper_hotkey_core.py` | логика Ctrl+Win (запись → Whisper → вставка) |
| `whisper-hotkey.py` | консольный вход (shim → core), без окна |
| `whisper_hotkey_gui.py` | окно Whisper Hotkey + сборка `WhisperHotkey.exe` |
| `start-whisper-hotkey-gui.bat` | GUI hotkey с запросом прав администратора |
| `whisper_models.py` | пресеты моделей (ключ → HF id для faster-whisper) |
| `whisper_server.py` | код HTTP API (импорт GUI / uvicorn) |
| `whisper-server.py` | shim: запуск CLI как раньше |
| `whisper_server_gui.py` | окно сервера: порт, Ctrl+Win, список HTTP-клиентов |
| `whisper-client-mac.py` | Клиент для Mac: запись → сервер → текст |
| `PORTAL_AND_WHISPER_MAC.md` | Portal + Whisper на одном Mac (хоткеи, права) |
| `start-whisper-hotkey.bat` | простой запуск hotkey + запрос прав администратора |
| `start-server.bat` | запуск HTTP API сервера (консоль) |
| `start-server-gui.bat` | запуск сервера с GUI (как start-server.bat по правам) |
| `packaging/mac/WhisperClient.app` | Mac-приложение (обновлять через `build_mac_app.sh`) |
| `packaging/mac/whisper_stub.c` | Mach-O загрузчик для .app (Finder) |
| `assets/app_icon.png` | исходник иконки; `AppIcon.icns`, `app_icon.ico` — для .app / exe |
| `packaging/regenerate_icons.sh` | PNG → icns + ico |
| `packaging/setup-venv-and-build.ps1` | venv + pip; параметры `-Build Server|Hotkey|Both|None`, `-DownloadModels` |
| `scripts/download_whisper_models.py` | скачать в кэш HF все пресеты из `whisper_models.py` |
| `whisper_file_log.py` | ротационные `whisper_server.log` / `whisper_hotkey.log` |
| `whisper_hotkey_tray.py` | hotkey в трее (точка входа `WhisperHotkey.exe`) |
| `packaging/build-server-gui-exe.bat` | сборка `WhisperServer.exe` через PyInstaller |
| `packaging/build-hotkey-gui-exe.bat` | сборка `WhisperHotkey.exe` через PyInstaller |
| `packaging/windows/WhisperServer.iss` | Inno Setup → `WhisperSetup-{версия}.exe` |
| `packaging/windows/WhisperHotkey.iss` | Inno Setup → `WhisperHotkeySetup-{версия}.exe` |
| `packaging/mac/make_dmg.sh` | DMG для `WhisperClient.app` (create-dmg) |
| `packaging/VERSION` | номер версии для API, GUI, Mac, CI |
| `whisper_version.py` | чтение версии (и `WHISPER_VERSION`) |
| `whisper_update_check.py` | запрос `releases/latest` |
| `speaker_verify.py` | embedding + эталон голоса |
| `requirements-speaker.txt` | torch + resemblyzer для speaker verify |
| `run-transcribe.ps1` | transcribe через venv |
| `run-hotkey.ps1` | hotkey через venv |
| `requirements.txt` | зависимости |
