# Київ Радар — v1.30: read-only перевірка першого партнерського фіда

## Призначення

Перед приватним імпортом перевіряємо локальний фід партнера у **read-only** режимі: формат, дозволені поля, HTTPS-host, ID, нормалізовані посилання, кандидати у повтори. Немає мережевих запитів, SQLite-записів, автоматичних схвалень або публікацій.

**Структурний preflight не є доказом договору, права власності, актуальності або правом публікації.** Синтетичні приклади нижче не дозволяють запуск production.

## Що запросити у партнера

1. Справжній дозвіл на передачу власних оголошень (та дозвіл клієнтів агентства за потреби).
2. Права на конкретні поля: URL, ціну, місто/район, площу/кімнати, термін, attribution, умови відкликання; окремо на фото, описи, телефони та адресу.
3. Приватний тестовий CSV, JSONL або XML/YRL фід зі стабільним source ID і permalink, частотою оновлення, правилами повного/часткового snapshot.
4. Реальні документи, ключі та фіди тільки **поза GitHub**, не в issues, pull requests, workflow artifacts або публічному вебсайті.

Синтетичний приклад CSV:

```csv
external_id,source_url,operation,property_type,city,district,price_uah,rooms,area_m2
EXAMPLE-1,https://agency.example.ua/offer/EXAMPLE-1,rent,apartment,Київ,Дарницький,18000,2,53
```

Синтетична **приватна атестація** (тільки після реального перевіреного дозволу):

```json
{
  "source_key": "pilot_agency",
  "agreement_ref": "private_agreement_ref",
  "operator_rights_reviewed": true,
  "metadata_display_permitted": true,
  "valid_until": "2027-04-01",
  "allowed_source_hosts": ["agency.example.ua"],
  "full_snapshot_allowed": false
}
```

```bash
python scripts/partner_feed_preflight.py \
  --feed /secure/incoming/agency.csv \
  --agreement /secure/grants/agency.json
```

Для YRL (Yandex Realty Language) обов'язково `--format yrl`:

```bash
python scripts/partner_feed_preflight.py \
  --feed /secure/incoming/agency.xml \
  --agreement /secure/grants/agency.json \
  --format yrl
```

На успіх stdout містить **лише агреговані лічильники**, `private_database_writes=0` і `publications=0`. На помилку — лише тип помилки, без значень фіда, URL, телефону, ціни, адреси або приватного шляху.

Повтор `external_id` — помилка. Повтор canonical URL — тільки кандидат у дубль; автоматичного злиття немає. Порожній тестовий пакет — помилка.

## Подальші gates — **не включені до preflight**

- Людина перевіряє реальні права партнера, scope, строк та докази.
- Оператор виконує існуючий **окремий** приватний `scripts/market_inventory.py`; тільки цей крок змінює SQLite.
- Cross-source дублі, source-rights lifecycle, великі падіння full snapshot, цілісність бази та рев'ю зняття перевіряються лише на наступному етапі.
- Незалежний reviewer перевіряє конкретні актуальні оголошення; окремий publication authorization та runtime gate керують видимістю.
- Потрібні green CI, staging E2E та окреме схвалення production.

Поточний metadata-only шлях **не зберігає і не публікує фото, описи, телефони, точні адреси**, незалежно від їх присутності у вхідному фіді. Для продажів, іноземних валют та регіонів поза Києвом потрібні окремі UI/схемні рішення.

Цей PR не підключає OLX/DIM.RIA API, не додає реальні оголошення, не змінює VPS, Telegram-токен, платні сервіси або історичні 150 не підтверджених лотів.
