# Київ Радар v1.26 — приватний конвеєр дозволених партнерських оголошень

## Мета та чесні обмеження

Відкрити **захищений шлях від приватного масового імпорту до API** лише для
партнерських лотів із правом публікації конкретних полів та незалежним
підтвердженням доступності. Поки реальних дозволів/даних немає, система
працює в тестовому режимі: нічого не додає до публічного каталогу.

**Важливо:** `v1.26` — не запуск агрегатора всіх сайтів і не дозвіл копіювати
OLX/DIM.RIA. Ручне `publication_permitted=true` саме по собі не є доказом
договору: відповідальний оператор мусить перевірити оригінал документів.

## Шлях даних

```text
партнерський дозволений JSON/CSV/XML/YML
    -> scripts/market_inventory.py (приватний SQLite)
    -> ручне право на metadata + підтверджений договір
    -> окреме приватне право на ПУБЛІКАЦІЮ потрібних полів
    -> модератор + свіже незалежне підтвердження наявності
    -> python -m server.partner_publication (plan-only)
    -> --execute: приватний metadata-only JSON (не GitHub Pages)
    -> opt-in серверний API через KYIV_RADAR_PRIVATE_PARTNER_EXPORT
    -> незалежна перевірка receipt + reviewer + source_rights в /api/deals
    -> HTTPS response no-store
```

Приватний документ `publication_authorization.json`:
```json
{
  "schema_version": 1,
  "source_key": "agency_one",
  "agreement_ref": "contract_v1",
  "publication_permitted": true,
  "reviewed_by": "operator_1",
  "evidence_ref": "private/contract-case-1",
  "reviewed_at": "2026-11-17T18:00:00+00:00",
  "valid_until": "2027-07-01",
  "permitted_fields": [
    "source_url", "operation", "property_type", "city",
    "district", "price_uah", "rooms", "area_m2"
  ]
}
```

Це **синтетичний приклад**, не підстава увімкнути партнера. Файл повинен
лежати поза GitHub, переглядатися людиною й бути відкликаний разом із
договором. Термін ручного review — максимум 30 днів; строк документа
не може перевищувати термін source agreement.

## Приватний запуск

Спочатку `plan-only` — жодних записів у зовнішні файли:
```bash
python -m server.partner_publication \
  --database /secure/radar/inventory.sqlite \
  --authorization /secure/grants/agency-publication.json \
  --reviews /secure/reviews/independent-availability.json \
  --output /secure/outgoing/partner-preview.json
```

Після перевірки всіх дозволів оператор може додати `--execute`.
Тільки тоді створюється **приватний** файл із правами доступу `0600`.
Повторне виконання не перезаписує існуючий файл мовчки: оператор
використовує новий target або контрольований процес ротації.

Завантаження на сервері вимкнене за замовчуванням. Для **окремого**
погодженого staging/deployment потрібні усі три приватні env:
```bash
KYIV_RADAR_PRIVATE_PARTNER_DB=/secure/radar/inventory.sqlite
KYIV_RADAR_PRIVATE_PARTNER_EXPORT=/secure/outgoing/partner-preview.json
KYIV_RADAR_PRIVATE_PUBLICATION_AUTH=/secure/grants/agency-publication.json
```

API перечитує приватний export і publication receipt при кожному
`GET /api/deals`; якщо право на публікацію відкликано, файл вилучено,
hash/scope змінився або export старший за 48 год — партнери не додаються.
`load_effective_deals()` окремо перераховує reviewer evidence та
поточне `source_rights` у SQLite. `/api/send_contact` користується
тією ж відфільтрованою видачею. Без секретних env старий шлях
працює як раніше.

## Що саме може з'явитися в API

Тільки схвалена коротка картка з дозволеними метаданими:
оренда **квартири в Києві**, ціна у гривнях, загальна локація/район,
кімнатність і площа, якщо такі поля дозволені; HTTPS-лінк на партнера.
Заголовок нейтральний (не з копійованого авторського опису).

**Ніколи не імпортуємо/не публікуємо тут** телефон, ім'я власника,
текст опису, фото, точні координати, contactVerified, ownershipVerified,
0% комісії, гарантії генератора/GPON чи медіаконтент.

Стабільний numeric ID походить з `source + external_id` та перевіряється
на колізії в пакеті. `partnerExternalId` і `partnerSourceKey` потрібні
приватно для API gate, але не виходять у публічну форму `/api/deals`.

Чому поки тільки Київ/оренда: нинішній фронтенд має киянський заголовок
та ціни з позначкою «на місяць». Публікувати продаж або інше місто
до відповідного UI — вводити користувача в оману. *Імпортер v1.22+
вже приймає інші регіони і категорії приватно.*

## План технічної перевірки

- source agreement active/not expired, same agreement_ref
- explicit publication field scope + manual review + expiry
- approval per individual lot
- fresh independent reviewer availability, not feed flags
- no names/phones/media/PII in export or API
- receipt change/revocation or export older than 48h => no partner cards
- runtime source revoke and price/URL mismatch => no partner cards
- no partner data in public GitHub Pages JSON/embedded fallback
- green focused CI and full GitHub Actions before merge
- separate production release, operator E2E and verified legal permission

## Далі

Наступна версія повинна додати повноцінний UI регіонів/типів/купівлі й
оренди, мобільний search experience і пагінацію server-side. Розширення
саме **опублікованого** інвентарю можливе тільки після реальних договорів.

Історичні 150 OLX/DIM.RIA записів досі непідтверджені; їх потрібно
розглянути окремим data-quality/republication audit. Немає fake inventory,
скрапінгу, paid API, VPS або Telegram-token змін у цьому PR.
