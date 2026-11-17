# Київ Радар v1.23 — приватний XML/YML адаптер партнерських фідів

## Стан і межі

Це **локальний parser/adapter** до вже існуючого `scripts/market_inventory.py`.
Він **НЕ** отримує права на сторонні оголошення, не завантажує фіди з інтернету,
не відкриває публічні картки, не змінює VPS, API, бота або токени.

Спочатку партнер надає дозвіл на відповідні метадані і надає файл дозволеним
каналом. Людина перевіряє договір/тривалість/поля/відкликання й зберігає
атестацію **поза GitHub**. Прапорець `operator_rights_reviewed: true`
**не є юридичним доказом** сам по собі.

## Формати

Підтримуються локальні файли `.xml` і `.yml` у двох строгих формах.

### Канонічний XML (рекомендовано для агенцій)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<realty-feed>
  <offer id="agency-001">
    <source_url>https://partner.example.ua/offer/agency-001</source_url>
    <operation>rent</operation>
    <property_type>apartment</property_type>
    <city>Київ</city>
    <district>Дарницький</district>
    <price_uah>18000</price_uah>
    <rooms>2</rooms>
    <area_m2>52.5</area_m2>
  </offer>
</realty-feed>
```

### Строго обмежений YML з явними характеристиками

```xml
<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog>
  <shop>
    <offers>
      <offer id="agency-001">
        <url>https://partner.example.ua/offer/agency-001</url>
        <price>18000</price>
        <currencyId>UAH</currencyId>
        <param name="operation">rent</param>
        <param name="property_type">apartment</param>
        <param name="city">Київ</param>
        <param name="rooms">2</param>
      </offer>
    </offers>
  </shop>
</yml_catalog>
```

Звичайний YML може не містити типу нерухомості/операції у нашій схемі.
**Не вгадуємо** ці значення за `categoryId` або заголовком. Для реальних
партнерських схем потрібен окремий перевірений mapping adapter з тестами.
`price` у YML приймається тільки з `currencyId=UAH`: без курсів валют
не підміняємо суму у USD/EUR гривнями.

## Приватний запуск

```bash
python scripts/market_inventory.py \
  --feed /secure/incoming/partner.xml \
  --agreement /secure/grants/partner.json \
  --database /secure/radar/inventory.sqlite
```

Позначка `--full-snapshot` допустима **тільки** коли партнерський договір
дозволяє саме повний snapshot; `full_snapshot_allowed: true` також потрібен
у приватній атестації. Без неї неповний фід не знімає старі оголошення.

## Збережені інваріанти

- До 250 MiB на файл і до 1 млн записів на пакет через існуючий importer.
- Потоковий parser (без повного XML DOM). Обмежені вкладеність, атрибути,
  розмір текстового поля; DTD, внутрішні/зовнішні сутності, XML PI відхиляються.
- Тільки UTF-8 XML, без мережевих звернень, без парсингу вкладених структур
  у полях. Будь-яка помилка -> відкат усього пакета SQLite.
- За замовчуванням `pending_review`; зміни вже схваленої картки ->
  `needs_review`. Права на фото, власність чи контакт не встановлюються.
- Копіюються лише whitelisted метадані `external_id`, `source_url`,
  `operation`, `property_type`, `city`, `district`, `price_uah`,
  `rooms`, `area_m2`, `unit_key`. Фото, телефони, імена, описи,
  точні координати і будь-які інші XML-поля відкидаються.
- Канонічна HTTPS URL має збігатись із `allowed_source_hosts` дозволу.
  Дублікати по ID у пакеті — помилка; між джерелами — лише кандидати
  для модератора, без автоматичного злиття.
- **0 нових публікацій, 0 платних API-запитів, 0 живих фідів** у цьому PR.

## Наступні незалежні гейти

1. Письмовий дозвіл конкретного партнера, узгоджені поля та право відкликання.
2. Тест схеми фіда партнера у приватному dry-run (не у public CI).
3. Спільний планувальник ingestion, обробка revoke/expiry та журнал рішень.
4. Окремий public eligibility/export gate з приватними доказами права
   на публікацію, актуальності та контактів.
5. Лише після ручного E2E і явного release approval — production deployment.

Основна задача: GitHub Issue #34.

## Про окремий YRL (Yandex Realty Language)

Стандартний YRL використовує `<realty-feed>` із `internal-id`, вкладені `price/value/currency`, `location` та галузеві типи. Це **інша схема**, ніж наш канонічний XML з таким самим коренем. Поточний strict parser не заявляє сумісності з довільним YRL — для кожного такого партнерського фіда потрібен окремий затверджений mapping з тестами, без вгадування типу чи конвертації валют.
