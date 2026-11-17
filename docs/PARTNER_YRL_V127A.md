# Київ Радар v1.27a — строго дозволений YRL імпорт

## Навіщо

Агентства нерухомості часто експортують власні об'єкти у **YRL**
(Yandex Realty Language), із тегами `realty-feed`, `offer internal-id`,
`location`, `price`, `area`. Цей формат **не є** нашим простим
canonical XML і **не є** Yandex Market Language (YML) із `shop/offers`.

У цьому релізі додаємо явно вибраний `--format yrl` для вже отриманого
*з дозволу партнера* локального фіда. Ніяких запитів на сторонній сайт,
автоматичного парсингу OLX/DIM.RIA, скопійованих фото чи контактів.

## Приклад синтетичного YRL

```xml
<?xml version="1.0" encoding="UTF-8"?>
<realty-feed xmlns="http://webmaster.yandex.ru/schemas/feed/realty/2010-06">
  <offer internal-id="agency-001">
    <type>оренда</type>
    <property-type>житлова</property-type>
    <category>квартира</category>
    <url>https://agency.example.ua/offers/agency-001</url>
    <location>
      <country>Україна</country>
      <locality-name>Київ</locality-name>
      <district>Дарницький</district>
      <address>не імпортується</address>
    </location>
    <price>
      <value>18000</value><currency>UAH</currency><period>місяць</period>
    </price>
    <area><value>51.5</value><unit>кв.м</unit></area>
    <rooms>2</rooms>
  </offer>
</realty-feed>
```

Це штучний приклад, не реальна пропозиція.

## Локальний імпорт

```bash
python scripts/market_inventory.py \
  --feed /secure/incoming/agency.xml \
  --agreement /secure/grants/agency.json \
  --database /secure/radar/inventory.sqlite \
  --format yrl
```

`--full-snapshot` дозволений тільки при `full_snapshot_allowed=true`
і письмовому праві на повний snapshot. Без флага відсутність лота в
частковій вигрузці не є видаленням. Імпорт проходить через ті ж
`source_rights`, `review_status`, захист від дублювання, контроль
контракту та транзакційний rollback, що й JSON/CSV/XML v1.22–v1.26.

## Підтримуваний піднабір

- Стандартний `realty-feed/offer internal-id`, у UTF-8, з вкладеними
  `price/value/currency/period`, `location/locality-name/district`,
  `area/value/unit`, `rooms`, `url`, `type`, `category`,
  `property-type` (опціонально).
- `type`: продаж / оренда / явно подобова оренда, із затвердженим mapping.
- `category`: квартира, кімната, будинок, таунхаус, ділянка, офіс,
  склад, гараж тощо — тільки whitelisted точні значення.
- Ціна: лише позитивне ціле значення **UAH** без конвертації; для оренди
  обов'язковий `period=місяць`, для подобової — `day/день/доба`.
  Для продажу не можна передавати rent period; `price/unit` відхиляється.
- Площа: тільки явна підтримана одиниця квадратних метрів, без
  перерахунків гектарів, соток або невідомих одиниць.
- HTTPS посилання **тільки на хост із приватної allowlist** договору;
  `external_id` стабільний, подвійні ID в одному пакеті — rollback.
- Поля опису, фото, точна адреса, ім'я, телефон, координати та sales-agent
  **не копіюються**, навіть якщо присутні у фіді.
- DTD, entity declarations, зовнішні entity/XXE, processing instructions,
  UTF-16 і надмірні вкладеність/розмір полів — заборонено.

## Важливі обмеження

Це **строгий піднабір YRL**, а не універсальна підтримка будь-якої
кастомізації агентства. Формати `<price><value>150000</value><currency>USD</currency>`
не можна чесно показувати як UAH без окремого ліцензованого курсу,
дати та правил конвертації. Такі записи блокуються, а не переписуються.
Невідомі значення або лоти без URL/ціни/міста не вгадуються.

Права на фід / сайт агентства, на публікацію полів, фото і контактів
слід узгодити **окремо**. Сам YRL — технічний формат, не ліцензія.

Перед будь-яким live-імпортом: підписаний або інший перевірений дозвіл
партнера, приватна атестація поза GitHub, тест на синтетичному та
дозволеному файлі, ручне ревью, green CI, окреме погодження production.

## Довідкові формати

- https://qip.ua/ru/help/format-fajla-yml-6.html
- https://yandex.ru/support/realty/ru/feed/requirements-sale-housing
- https://ligapro.ua/instrukcia/info-42.html?lang=ua
- https://ostroyke.com.ua/partners

Джерела описують формат і можливість партнерського імпорту, не
передають нам права на сторонні оголошення.
