# Подпись Whisper Client на macOS

## Быстрый путь: Developer ID Application (раздача .app / DMG)

1. В [Certificates](https://developer.apple.com/account/resources/certificates/list) создай **Developer ID Application** (CSR из Связки ключей → загрузка `.certSigningRequest` → скачай `.cer`).

2. **Импорт сертификата** (двойной клик по `.cer` или):

   ```bash
   security import ~/Downloads/developerID_application.cer \
     -k ~/Library/Keychains/login.keychain-db \
     -T /usr/bin/codesign
   ```

3. Проверь личность (должна появиться строка **Developer ID Application: …**):

   ```bash
   security find-identity -v -p codesigning
   ```

4. **Один раз:** скопируй  
   `packaging/mac/whisper_codesign_local.env.example` → `packaging/mac/whisper_codesign_local.env`  
   (файл в `.gitignore`) и заполни пароль связки или `WHISPER_LOGIN_KEYCHAIN_PASSWORD_CMD` — см. комментарии в примере.

5. **Дальше любая сборка сама подписывается Developer ID**, если есть `whisper_codesign_local.env`:

   ```bash
   bash packaging/build_mac_app.sh
   ```

   То же для DMG: `packaging/mac/make_dmg.sh` по умолчанию пересобирает `.app` через тот же скрипт — получится подписанный образ без отдельного шага.

   Явно без env-файла, но с Developer ID (можно ввести пароль в GUI):

   ```bash
   bash packaging/mac/build_signed_app.sh
   ```

   Ручной export (редко нужен):

   ```bash
   export WHISPER_MAC_CODESIGN_IDENTITY='Developer ID Application: Nikita Zaporozhets (Y52BT2N4L8)'
   bash packaging/build_mac_app.sh
   ```

   Если `codesign` зависает или просит пароль и ты собираешь не из интерактивного окна — в **Терминале.app**:

   ```bash
   bash packaging/mac/build_signed_app_unlock_prompt.sh
   ```

   Один раз вводишь пароль связки «Вход», дальше скрипт сам разблокирует связку и запускает подпись.

### Релиз одной командой (+ DMG)

Если `whisper_codesign_local.env` уже создан (шаг 4 выше), можно собрать подписанный `.app` и **DMG** разом:

```bash
bash packaging/mac/release_mac_signed.sh
```

Нужен `brew install create-dmg`. Только `.app`:  
`WHISPER_MAC_SKIP_DMG=1 bash packaging/mac/release_mac_signed.sh`

По желанию один раз, чтобы реже ловить окна «codesign хочет доступ»:  
`bash packaging/mac/codesign_keychain_once.sh`

Подпись Developer ID **нужна при каждой новой сборке**, которую ты отдаёшь людям. При наличии `whisper_codesign_local.env` её выполняет сам `build_mac_app.sh` (в т.ч. когда агент в Cursor запускает сборку).

Если **`whisper_codesign_local.env` нет** и **`WHISPER_MAC_CODESIGN_IDENTITY` не задан**, `build_mac_app.sh` делает **ad-hoc** подпись (`codesign -`) — быстрые локальные тесты, хуже для Gatekeeper и стабильности разрешений.

---

## Что даёт подпись и что **не** меняется в коде

Подпись **не добавляет функций** в Whisper: те же Python-скрипты, хоткеи, меню.

Меняется **идентичность бинарника** для macOS:

| Без Developer ID (ad-hoc) | С Developer ID |
|---------------------------|----------------|
| Подпись «сам себе», при каждой сборке другая | Постоянный **Team ID** (у тебя `Y52BT2N4L8`) |
| Gatekeeper сильнее ругается на незнакомое приложение | Система видит приложение как выпущенное зарегистрированным разработчиком |
| Разрешения микрофона / мониторинга ввода часто «сбиваются» после пересборки | Обычно **стабильнее** привязка в TCC к одному и тому же подписанному идентификатору |
| Нотаризация Apple для DMG по сути недоступна | Можно **нотаризовать** DMG и раздавать без «не открывается» |

Итого: подпись — это **упаковка и доверие**, не новая логика приложения.

---

## codesign постоянно просит пароль / «недействительная метка»

**Полностью без пароля нельзя:** доступ к закрытому ключу Developer ID всегда идёт через связку ключей — так устроено у Apple.

Что можно сделать:

1. **Один раз** разблокировать связку «Вход» и выставить partition list для `codesign` (меньше запросов при сборках):

   ```bash
   chmod +x packaging/mac/codesign_keychain_once.sh
   bash packaging/mac/codesign_keychain_once.sh
   ```

   Пароль — это пароль **связки «Вход»**, обычно совпадает с паролем входа в macOS (или **старым**, если менял пароль пользователя и связка не синхронизировалась).

2. В **Связка ключей** → правая кнопка по **«Вход»** → **Изменить параметры…** — сними или увеличь таймаут **«Блокировать через … мин»**, чтобы связка не закрывалась после простоя.

3. Если вылезает **«Не удаётся использовать текущую связку ключей» / «недействительная метка»** — перезагрузи Mac, при необходимости **Связка ключей → меню «Связка ключей» → «Средство починки связки ключей»** для связки «Вход». Не подбирай пароль наугад — несколько неверных попыток усугубляют сбой.

4. **Сборки без Developer ID и без пароля:** не задавай `WHISPER_MAC_CODESIGN_IDENTITY` — будет **ad-hoc** (`codesign -`), для локальных тестов достаточно, но Gatekeeper строже.

---

## Нотаризация (перед раздачей DMG чужим людям)

Нотаризация — проверка образа у Apple; после **staple** Gatekeeper доверяет файлу сильнее.

Нужны **Apple Developer Program**, подпись **Developer ID** + **`--options runtime`** (у тебя через `whisper_codesign_local.env`), **Team ID** `Y52BT2N4L8`.

**Пароли не коммить.** Файл `packaging/mac/whisper_notary_local.env` в **`.gitignore`** — только локально (как и `whisper_codesign_local.env`). Если пароль приложения когда‑либо попал в чат или git — **удали его на appleid.apple.com** и создай новый.

### Один раз

1. [appleid.apple.com](https://appleid.apple.com) → **Вход и безопасность** → **Пароли приложений** → создай пароль приложения, сохрани в менеджере паролей.

2. Скопируй пример и заполни пароль:

   ```bash
   cp packaging/mac/whisper_notary_local.env.example packaging/mac/whisper_notary_local.env
   ```

   Отредактируй `whisper_notary_local.env`: почта Apple ID, Team ID (уже стоят в примере), строка **`WHISPER_NOTARY_APP_PASSWORD`**.

3. Сохрани профиль **notarytool** в связке ключей (имя профиля по умолчанию в примере — **`whisper-notary`**, его же использует `--keychain-profile`):

   ```bash
   bash packaging/mac/notary_store_credentials.sh
   ```

### Каждый релиз — одной командой

Из корня репозитория (удобно для Cursor / агента):

```bash
bash release-mac.sh
```

Это то же самое, что `bash packaging/mac/release_mac_notarized.sh`.

Соберёт подписанный DMG, отправит на нотаризацию, сделает **staple**. Раздавай **этот** файл из `dist/release/`.

Отдельными шагами: `release_mac_signed.sh`, затем `notarize_and_staple_dmg.sh` (или укажи путь к конкретному `.dmg` вторым аргументом не нужен — скрипт берёт последний `WhisperClient-*.dmg`).

Если **Invalid** — в выводе будет ссылка на лог Apple.

Ручные команды `xcrun notarytool` / `stapler` при желании — как раньше; официально: [Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution).

---

## Apple Development (только своя разработка)

Для отладки через Xcode бывает сертификат **Apple Development** — отдельная личность в `security find-identity`. Его можно передать в `WHISPER_MAC_CODESIGN_IDENTITY`, но для установки «как у всех» снаружи Mac App Store нужен именно **Developer ID Application**, не Development.

Файл **`development.cer`** на диске — это публичная часть; подписывает связка **сертификат + закрытый ключ** в Keychain после импорта.

---

## Mac App Store

Отдельная упаковка (sandbox, entitlements, ревью). Для личного DMG достаточно **Developer ID + нотаризация**.

---

## CI (GitLab / GitHub): пересборка с подписью

Скрипты в репо; **пароли и .p12 — только в секретах CI**, никогда в коммите.

### GitHub Actions (релиз по тегу `v*`)

В **`release.yml`** джоб **build-macos** вызывает **`packaging/mac/ci_mac_signed_build.sh`**.

**Если секреты не заданы** — как раньше: **ad-hoc** подпись и обычный DMG (без Developer ID на раннере).

**Чтобы DMG на GitHub собирался с Developer ID**, в репозитории: **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Зачем |
|--------|--------|
| **`MACOS_CERTIFICATE_BASE64`** | Содержимое файла `.p12` (Developer ID Application + закрытый ключ), закодировать: `base64 -i Cert.p12 \| pbcopy` |
| **`MACOS_CERTIFICATE_PASSWORD`** | Пароль экспорта `.p12` из Связки ключей |
| **`MACOS_KEYCHAIN_PASSWORD`** | Опционально; если не задан — генерируется временный для импорта в CI |
| **`WHISPER_MAC_CODESIGN_IDENTITY`** | Опционально; по умолчанию в скрипте уже строка с Nikita Zaporozhets / `Y52BT2N4L8` |

**Опционально — нотаризация прямо в CI** (не обязательно, можно нотаризовать локально через `release-mac.sh`):

| Secret | Зачем |
|--------|--------|
| **`NOTARY_APPLE_ID`** | Почта Apple ID (`zap.nikita@icloud.com`) |
| **`APPLE_NOTARY_APP_SPECIFIC_PASSWORD`** | Пароль приложения с appleid.apple.com |
| **`NOTARY_TEAM_ID`** | Опционально; по умолчанию `Y52BT2N4L8` |

Локальные файлы **`whisper_codesign_local.env`** и **`whisper_notary_local.env`** по-прежнему в **`.gitignore`** — только на твоём Mac.

### GitLab

Аналогично: переменные CI вместо секретов GitHub; свой runner на **macOS** и те же идеи (импорт `.p12` или пароль связки на runner).

---

### Распространение на Mac (ещё раз коротко)

С **Developer ID** приложение для Gatekeeper выглядит как софт от зарегистрированного разработчика — это уже «нормально» для установки не из App Store.

Чтобы у пользователей было **минимум трения** (без «вредоносное ПО», без правого клика «Открыть» на каждой машине), по возможности добавь **нотаризацию** DMG у Apple (раздел выше в этом файле). Без нотаризации на разных macOS всё равно может ругаться строже.
