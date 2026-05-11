# Подпись и установка Whisper Client без «танцев» (Gatekeeper)

Сейчас в репозитории сборка делает **ad-hoc** подпись (`codesign --sign -`). macOS тогда часто требует **Ctrl+открыть**, сброс TCC после каждой пересборки и т.д.

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
