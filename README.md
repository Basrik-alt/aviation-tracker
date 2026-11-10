# Отслеживание воздушных судов (OpenSky Network + PostgreSQL)

Курсовой проект: приложение получает географические координаты стран из
**Nominatim (OpenStreetMap)**, загружает воздушные суда, находящиеся сейчас
в воздухе, из **OpenSky Network** и сохраняет данные в **PostgreSQL**.
Работа с базой выполняется через класс `DBManager` и библиотеку `psycopg2`.

## Возможности

- 12 стран наблюдения (Германия, Франция, Испания, Италия, Польша,
  Нидерланды, Бельгия, Австрия, Швейцария, Чехия, Португалия, Швеция).
- Автоматическое определение координат и bounding box страны через Nominatim.
- Загрузка state vectors из OpenSky по bounding box каждой страны.
- Хранение полной информации о самолёте: ICAO24, позывной, страна регистрации,
  координаты, барометрическая и геометрическая высота, скорость, курс,
  вертикальная скорость, squawk, SPI, источник позиции, время последнего контакта.
- Отчёты: количество самолётов по странам, средняя скорость, самолёты быстрее
  средней, поиск по позывному.
- Анонимный доступ к OpenSky и опциональная авторизация по OAuth2.

## Структура проекта

```
.
├── main.py                     # точка входа
├── requirements.txt            # зависимости
├── .env.example                # пример переменных окружения
├── .gitignore
├── aviation/
│   ├── config.py               # конфигурация из переменных окружения
│   ├── countries.py            # список стран наблюдения
│   ├── models.py               # доменные модели (Country, Aeroplane, ...)
│   ├── cli.py                  # команды init-db / load / report
│   ├── api/
│   │   ├── http_client.py      # HTTP-клиент: пауза между запросами, retry
│   │   ├── nominatim_client.py # получение координат стран
│   │   └── opensky_client.py   # получение самолётов
│   ├── db/
│   │   ├── schema.sql          # схема БД
│   │   └── db_manager.py       # класс DBManager (psycopg2)
│   └── services/
│       ├── protocols.py        # протоколы зависимостей (DIP)
│       └── collector.py        # сбор и сохранение данных
└── README.md
```

## Требования

- Python 3.10+
- PostgreSQL 14+
- Доступ в интернет к `nominatim.openstreetmap.org` и
  `opensky-network.org`

## Установка

### 1. Создать базу данных и пользователя

Подключитесь к PostgreSQL под суперпользователем и выполните:

```sql
CREATE USER aviation WITH PASSWORD 'aviation';
CREATE DATABASE aviation OWNER aviation;
```

Если вы используете существующего пользователя (например, `postgres`),
просто укажите его данные в `.env`.

### 2. Установить зависимости

Рекомендуется виртуальное окружение:

```bash
python -m venv .venv
```

Windows (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Настроить переменные окружения

Скопируйте `.env.example` в `.env` и при необходимости измените значения:

```bash
copy .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Минимально нужно проверить параметры PostgreSQL:

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=aviation
DB_USER=aviation
DB_PASSWORD=aviation
```

> **User-Agent для Nominatim.** По правилам OpenStreetMap в заголовке
> `User-Agent` должно быть указано приложение. Замените значение
> `APP_USER_AGENT` на своё (можно указать ссылку на репозиторий).
> Если Nominatim отвечает `403 Access denied`, проверьте User-Agent.

### 4. Авторизация OpenSky (необязательно)

Без учётных данных OpenSky работает в анонимном режиме с уменьшенными
лимитами (около 400 кредитов в сутки). Для стабильной работы создайте
OAuth2-клиент в личном кабинете OpenSky
(<https://opensky-network.org/my-opensky/account>) и заполните:

```dotenv
OPENSKY_CLIENT_ID=...
OPENSKY_CLIENT_SECRET=...
```

Клиент сам получит токен и будет обновлять его по истечении срока действия.

## Запуск

### Создать таблицы

```bash
python main.py init-db
```

### Загрузить данные

```bash
python main.py load
```

Команда:

1. получает координаты и bounding box 12 стран из Nominatim;
2. сохраняет страны в таблицу `countries` (upsert по ISO-коду);
3. запрашивает самолёты в воздушном пространстве каждой страны в OpenSky;
4. заменяет содержимое таблицы `aeroplanes` актуальным снимком.

Загрузка занимает несколько минут: между запросами выдерживаются паузы,
чтобы не нарушать лимиты публичных API.

### Посмотреть отчёты

```bash
python main.py report --keyword ACA --limit 20
```

Выводятся:

1. все страны и количество самолётов в их воздушном пространстве (`LEFT JOIN`);
2. средняя скорость самолётов;
3. самолёты со скоростью выше средней;
4. самолёты, в позывных которых есть `ACA` (Air Canada);
5. все воздушные суда (первые `--limit` строк).

## Схема базы данных

### `countries`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `SERIAL PK` | идентификатор |
| `name` | `VARCHAR(128) UNIQUE` | название страны |
| `iso_code` | `CHAR(2) UNIQUE` | ISO 3166-1 alpha-2 |
| `latitude`, `longitude` | `DOUBLE PRECISION` | координаты центра |
| `min_latitude`, `max_latitude` | `DOUBLE PRECISION` | границы bbox по широте |
| `min_longitude`, `max_longitude` | `DOUBLE PRECISION` | границы bbox по долготе |
| `created_at` | `TIMESTAMPTZ` | время добавления |

### `aeroplanes`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `BIGSERIAL PK` | идентификатор |
| `icao24` | `VARCHAR(6) UNIQUE` | ICAO24 транспондера |
| `callsign` | `VARCHAR(16)` | позывной |
| `origin_country` | `VARCHAR(128)` | страна регистрации |
| `time_position` | `TIMESTAMPTZ` | время последней позиции |
| `last_contact` | `TIMESTAMPTZ` | время последнего контакта |
| `longitude`, `latitude` | `DOUBLE PRECISION` | координаты |
| `baro_altitude`, `geo_altitude` | `DOUBLE PRECISION` | высоты, м |
| `velocity` | `DOUBLE PRECISION` | скорость, м/с |
| `true_track` | `DOUBLE PRECISION` | курс, градусы |
| `vertical_rate` | `DOUBLE PRECISION` | вертикальная скорость, м/с |
| `on_ground` | `BOOLEAN` | на земле |
| `sensors` | `INTEGER[]` | серийные номера сенсоров |
| `squawk` | `VARCHAR(8)` | код транспондера |
| `spi` | `BOOLEAN` | special purpose indicator |
| `position_source` | `SMALLINT` | источник позиции |
| `category` | `SMALLINT` | категория воздушного судна |
| `country_id` | `INTEGER FK` | страна воздушного пространства |
| `updated_at` | `TIMESTAMPTZ` | время обновления записи |

Индексы создаются по `country_id`, `velocity` и `callsign`.

## Класс `DBManager`

`aviation/db/db_manager.py` использует `psycopg2` и предоставляет методы:

- `get_countries_and_aeroplanes_count()` — страны и количество самолётов
  в их воздушном пространстве (`LEFT JOIN`);
- `get_all_aeroplanes()` — все воздушные суда;
- `get_avg_speed()` — средняя скорость (м/с);
- `get_aeroplanes_with_higher_speed()` — самолёты со скоростью выше средней;
- `get_aeroplanes_with_keyword(keyword)` — поиск по подстроке позывного
  без учёта регистра (`ILIKE`).

Дополнительно класс умеет создавать схему (`create_tables`), сохранять
страны (`save_countries`), сохранять/заменять самолёты
(`save_aeroplanes`, `replace_aeroplanes`) и очищать таблицу
(`clear_aeroplanes`).

Пример использования:

```python
from aviation.config import DatabaseConfig
from aviation.db.db_manager import DBManager

with DBManager(DatabaseConfig.from_env()) as db:
    for row in db.get_countries_and_aeroplanes_count():
        print(row.country, row.aeroplanes_count)
```

## Возможные проблемы

| Проблема | Решение |
|---|---|
| `psycopg2.OperationalError: connection refused` | Проверьте, что PostgreSQL запущен, и параметры в `.env`. |
| `database "aviation" does not exist` | Создайте БД командой `CREATE DATABASE aviation OWNER aviation;`. |
| Nominatim отвечает `403 Access denied` | Укажите корректный `APP_USER_AGENT` (с названием приложения/ссылкой). |
| OpenSky отвечает `429 Too Many Requests` | Подождите или добавьте OAuth2-учётные данные в `.env`. |
| В таблице нет самолётов | Повторите `python main.py load`; проверьте доступ к OpenSky. |

## Примечания

- В базе хранится только актуальный снимок воздушного пространства:
  команда `load` заменяет строки в `aeroplanes`.
- Самолёты на земле и без координат не сохраняются, так как задание
  требует данные о судах, находящихся в воздухе.
- Для стран с заморскими территориями (Франция, Испания, Португалия,
  Нидерланды) Nominatim возвращает bbox всех владений. Чтобы не запрашивать
  самолёты по всему миру, проект использует bbox крупнейшей части страны
  (материковой территории), вычисленный по GeoJSON.
- Если bbox нескольких стран пересекаются, самолёт относится к стране,
  к центру которого он ближе всего. Поэтому каждый самолёт хранится
  в единственном экземпляре (`icao24` уникален).
- Скорость хранится в м/с (как в OpenSky); в отчёте дополнительно
  показывается значение в км/ч.
