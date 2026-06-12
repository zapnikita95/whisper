# Whisper Client → TestFlight (macOS)

## Bundle ID (задай в Apple Developer)

```
com.zapnikita95.WhisperClient
```

Team ID: **Y52BT2N4L8** (Nikita Zaporozhets)

1. [Identifiers](https://developer.apple.com/account/resources/identifiers/list) → **+** → App IDs → macOS → Explicit → `com.zapnikita95.WhisperClient`
2. Capabilities: **App Sandbox**, **Hardened Runtime** (для MAS), микрофон описан в Info.plist
3. [App Store Connect](https://appstoreconnect.apple.com) → **My Apps** → **+** → New App → macOS → имя **Whisper Client**, bundle `com.zapnikita95.WhisperClient`, SKU `whisper-client-mac`

## Что стабильнее для тебя сейчас

| Способ | TCC (микрофон / хоткеи) | TestFlight |
|--------|-------------------------|------------|
| ad-hoc `local.whisper.client` | дубли, сброс после каждой сборки | нет |
| **Developer ID + `com.zapnikita95.WhisperClient`** | одна запись в настройках | нет (DMG) |
| Mac App Store + TestFlight | sandbox, хоткеи под вопросом | да |

**Рекомендация:** сначала выкати **Developer ID + новый bundle ID + нотаризация** (как сейчас, только с `com.zapnikita95.WhisperClient`). Это даёт ту же стабильность идентичности, что и App Store, без sandbox.

TestFlight — отдельный трек, если нужна раздача через Apple. У Whisper глобальный перехват клавиш (CGEventTap) в sandbox **часто не проходит** ревью; готовься к доработкам или отказу.

## Сборка для TestFlight (Mac App Store)

Нужны сертификат **Apple Distribution** и provisioning profile для Mac App Store (не Developer ID).

```bash
# 1. Обычная сборка .app
bash packaging/build_mac_app.sh

# 2. PKG для App Store Connect
export WHISPER_MAS_SIGN_IDENTITY='Apple Distribution: Nikita Zaporozhets (Y52BT2N4L8)'
export WHISPER_MAS_PROVISION='WhisperClient Mac App Store.provisionprofile'  # путь к профилю
bash packaging/mac/build_mas_pkg.sh
```

Загрузка:

- **Transporter** (из App Store) → файл `dist/release/WhisperClient-mas.pkg`
- или `xcrun altool --upload-app -f dist/release/WhisperClient-mas.pkg -t macos -u YOUR_APPLE_ID -p @keychain:AC_PASSWORD`

В App Store Connect → TestFlight → macOS → добавь билд → internal testing.

## После смены bundle ID (один раз)

Старые разрешения привязаны к `local.whisper.client`. Сброс:

```bash
bash /Applications/WhisperClient.app/Contents/Resources/reset_whisper_client_privacy.command
```

или вручную удали **WhisperClient** и **Python** из «Конфиденциальность» → включи только новый **Whisper Client** (`com.zapnikita95.WhisperClient`).

## Версии

- `CFBundleShortVersionString` — marketing (1.3.0)
- `CFBundleVersion` — build number для TestFlight (увеличивай каждый upload)

Скрипт `build_mac_app.sh` читает `packaging/VERSION` и `packaging/mac/BUILD_NUMBER` (если есть).
