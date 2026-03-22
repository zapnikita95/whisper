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

Дважды щёлкни **`start-whisper-hotkey.bat`**. Если прав администратора нет, Windows сама спросит подтверждение (нужно для глобального перехвата клавиш).

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
   ```

2. Скопируй `whisper-client-mac.py` на Mac.

3. **Приложение (Finder):** после клонирования собери копию скриптов внутрь `.app`:
   ```bash
   ./packaging/build_mac_app.sh
   ```
   Затем открой `packaging/mac/WhisperClient.app` (нужен системный **Python 3** с теми же pip-пакетами). Из Finder клиент стартует с `--no-hotkey-prompt` (⌥+⌃ по умолчанию); свой `--hotkey` задавай из Терминала.

4. **Простой способ (скрипт):** двойной клик на `start-client-mac.command` в Finder  
   **Или из терминала:**
   ```bash
   chmod +x start-client-mac.command  # один раз
   ./start-client-mac.command
   ```
   
   **Или напрямую:**
   ```bash
   python3 whisper-client-mac.py --server 'http://TAILSCALE_IP:ПОРТ'
   ```

5. При запуске **в терминале** клиент спросит сочетание одной строкой (как шорткат, через `+`); **Enter** без ввода = **⌥+⌃** (Option+Control). Удерживай выбранное сочетание — запись, отпусти все клавиши — распознавание. Альтернативы:
   - без вопроса с ⌥+⌃: `--no-hotkey-prompt`;
   - сразу строкой: `--hotkey 'ctrl+grave'` или `--hotkey 'ctrl+]'`;
   - «нажми и запомни»: `--bind-hotkey`.

### Опции клиента

```bash
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --language ru
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --no-spoken-punctuation
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --no-hotkey-prompt
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --hotkey 'ctrl+grave'
python3 whisper-client-mac.py --server 'http://100.x.x.x:8002' --bind-hotkey
```

### Как это работает

- Mac записывает аудио с микрофона.
- Отправляет WAV на Windows-сервер по HTTP.
- Сервер обрабатывает на GPU (Whisper).
- Возвращает текст.
- Mac вставляет текст через AppleScript.

**Примечание:** если обработка идёт, новая запись не начнётся автоматически (чтобы избежать зависаний).

### Упаковка: exe без консоли (Windows)

1. В том же venv, где стоят `fastapi`, `faster-whisper`, `uvicorn`: `pip install pyinstaller`.
2. Запусти `packaging\build-server-gui-exe.bat` — получишь `dist\WhisperServer\WhisperServer.exe` (первый запуск может быть долгим из‑за CTranslate2).
3. Положи рядом с exe файлы из репозитория при необходимости (`server_port.txt` создаётся сам). Для «красивого» ярлыка: закрепи exe на панели задач / создай ярлык в автозагрузке.

Чтобы **вообще не открывать батники**, достаточно **WhisperServer.exe** (GUI) для сервера и **WhisperClient.app** на Mac после `build_mac_app.sh`.

## Файлы

| Файл | Назначение |
|------|------------|
| `transcribe.py` | CLI: файл → текст в консоль |
| `whisper-hotkey.py` | Ctrl+Win удерживаешь — запись, отпускаешь — текст (Windows) |
| `whisper_server.py` | код HTTP API (импорт GUI / uvicorn) |
| `whisper-server.py` | shim: запуск CLI как раньше |
| `whisper_server_gui.py` | окно сервера: порт, Ctrl+Win, список HTTP-клиентов |
| `whisper-client-mac.py` | Клиент для Mac: запись → сервер → текст |
| `start-whisper-hotkey.bat` | простой запуск hotkey + запрос прав администратора |
| `start-server.bat` | запуск HTTP API сервера (консоль) |
| `start-server-gui.bat` | запуск сервера с GUI (как start-server.bat по правам) |
| `packaging/mac/WhisperClient.app` | Mac-приложение (обновлять через `build_mac_app.sh`) |
| `packaging/build-server-gui-exe.bat` | сборка `WhisperServer.exe` через PyInstaller |
| `run-transcribe.ps1` | transcribe через venv |
| `run-hotkey.ps1` | hotkey через venv |
| `requirements.txt` | зависимости |
