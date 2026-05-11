# Подпись и установка Whisper Client без «танцев» (Gatekeeper)

## Файл `development.cer` и Apple Development

Если у тебя в Downloads лежит **`development.cer`** — это обычно **публичная часть** сертификата **Apple Development** (WWDR). Подписывать им напрямую нельзя: нужна пара **сертификат + закрытый ключ** в **Связке ключей**.

Проверка, что всё на месте:

```bash
security find-identity -v -p codesigning
```

Должна быть строка вида **`Apple Development: your@email.com (…)`** — это и есть **личность для codesign**. Файл `.cer` на диске при этом может быть не нужен: главное — импорт в Keychain был с приватным ключом (часто ключ подтягивается автоматически, если создавали CSR из Xcode).

Сборка Whisper Client с твоей подписью **Apple Development**:

```bash
export WHISPER_MAC_CODESIGN_IDENTITY='Apple Development: zap.nikita@icloud.com (6L3B9RR8L8)'
bash packaging/build_mac_app.sh
```

Это лучше ad-hoc для **твоего Mac**, но **не заменяет** сертификат **Developer ID Application** для спокойной установки у всех пользователей и нотаризации.

---

Сейчас в репозитории без переменной сборка делает **ad-hoc** подпись (`codesign --sign -`). macOS тогда часто требует **Ctrl+открыть**, сброс TCC после каждой пересборки и т.д.

Чтобы **один раз разрешил и забыл** (как нормальные приложения):

## 1. Apple Developer Program

- Зарегистрируйся в **[Apple Developer Program](https://developer.apple.com/programs/)** (платная подписка).
- В **Certificates, Identifiers & Profiles** создай **Developer ID Application** сертификат  
  (или через Xcode: *Settings → Accounts → Manage Certificates → Developer ID Application*).

Убедись, что в Keychain Access есть сертификат вида  
`Developer ID Application: Your Name (TEAMID)`.

## 2. Подпись приложения

После `bash packaging/build_mac_app.sh` подпиши бандл своим Developer ID:

```bash
codesign --deep --force --options runtime \
  --sign "Developer ID Application: ИМЯ (TEAMID)" \
  "packaging/mac/WhisperClient.app"
```

`--options runtime` нужен для нотаризации (см. ниже).

## 3. Нотаризация Apple (рекомендуется)

Без нотаризации Gatekeeper всё равно может ругаться «не проверено».

1. Собери **DMG** или zip с `.app`:  
   `bash packaging/mac/make_dmg.sh`
2. Отправь на проверку (**notarytool**):

```bash
xcrun notarytool submit dist/release/WhisperClient-*.dmg \
  --apple-id "your@email.com" \
  --team-id TEAMID \
  --password "app-specific-password" \
  --wait
```

3. Прикрепи билет к архиву:

```bash
xcrun stapler staple dist/release/WhisperClient-*.dmg
```

Подробности: [Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution).

## 4. Что получится

- Пользователь качает **DMG**, перетаскивает в **Программы**, первый запуск — без обхода через Системные настройки (после успешной нотаризации).
- **Уведомления / микрофон / ввод** всё равно запрашиваются один раз — это отдельно от подписи.

## 5. Mac App Store

Вынос в App Store — отдельная упаковка (sandbox, entitlements, проверка ревью). Для личного использования достаточно **Developer ID + notarize + DMG**.
