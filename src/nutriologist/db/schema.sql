-- Full data model per PLAN.md section 8. Tables are created up front so
-- later iterations don't need their own migrations for the base shape;
-- columns/indexes that a specific iteration still needs to populate are
-- noted inline. Units are always the canonical tokens 'g' / 'ml' / 'piece'.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

-- Итерация 1: чеки
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fd_number TEXT,
    fpd TEXT,
    store_name TEXT,
    purchased_at TEXT,
    total REAL,
    raw_text TEXT NOT NULL,
    -- Raw parser/LLM output kept verbatim so receipts can be re-processed
    -- if the extraction schema changes later, without re-reading the PDF.
    raw_json TEXT,
    -- Path to the source PDF on disk (data/receipts/...); the file itself
    -- lives outside the repo, only the pointer is stored here.
    source_pdf_path TEXT,
    source_format TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- NULL fd_number/fpd rows are never deduplicated against each other: SQLite
-- treats every NULL as distinct for UNIQUE indexes, which matches the
-- decision in PLAN.md — receipts the LLM fallback couldn't fingerprint are
-- saved without a dedup check rather than dropped.
CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_fd_fpd
    ON receipts (fd_number, fpd);

CREATE TABLE IF NOT EXISTS receipt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL REFERENCES receipts (id),
    raw_name TEXT NOT NULL,
    qty REAL NOT NULL,
    unit TEXT,
    unit_price REAL NOT NULL,
    total REAL NOT NULL,
    vat_rate INTEGER,
    vat_amount REAL,
    -- Filled in lazily by product normalization (итерация 2); NULL until then.
    product_id INTEGER REFERENCES products (id)
);

CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt_id
    ON receipt_items (receipt_id);

-- Итерация 2: нормализация продуктов + БЖУ
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    -- Closed category enum enforced at the application level (not in SQL, so
    -- the list can evolve without a migration): молочное, овощи, фрукты,
    -- мясо, рыба, крупы/макароны, бакалея, консервы, заморозка, напитки,
    -- снеки, непищевое, прочее.
    category TEXT,
    is_food INTEGER NOT NULL,
    -- Base unit for inventory and the per-100 nutrition basis: 'g' | 'ml' | 'piece'.
    canonical_unit TEXT,
    -- Weight of one piece, for products sold by count (eggs, ...). NULL until
    -- шт→г conversion is implemented (итерация 3/5); reserved now to avoid a
    -- later migration.
    piece_weight_grams REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Normalization cache: maps a store's verbatim receipt line to a canonical
-- product, so a repeat purchase of the same item costs no LLM call. The key is
-- (store_name, raw_name), NOT raw_name alone: "Яблоки" can mean loose produce
-- in one store and a 500 g pack in another, and net_amount/net_unit below are
-- packaging facts of *this* store's SKU (e.g. "Рис ... 5х80г" -> 400 g), not of
-- the canonical product — which is why they live here and not on `products`.
-- Rows with a NULL store_name are not written by the cache lookup (they would
-- collide across unknown stores); such lines are re-normalized each time.
CREATE TABLE IF NOT EXISTS product_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_name TEXT,
    raw_name TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products (id),
    net_amount REAL,
    net_unit TEXT,
    UNIQUE (store_name, raw_name)
);

-- Nutrition per 100 g (or 100 ml for liquids). One row per product; the
-- resolver writes the best available source and won't overwrite a
-- 'db'/'user' row with an 'llm_estimate'.
CREATE TABLE IF NOT EXISTS nutrition (
    product_id INTEGER NOT NULL REFERENCES products (id),
    kcal REAL,
    protein REAL,
    fat REAL,
    carbs REAL,
    source TEXT NOT NULL CHECK (source IN ('db', 'user', 'llm_estimate')),
    -- Free-form trace of where the numbers came from (e.g. Open Food Facts
    -- product code), for debugging/re-fetching. NULL for hand-entered/llm.
    source_ref TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (product_id)
);

-- Итерация 3: инвентарь как бухгалтерская книга (ledger).
-- Не мутабельный счётчик, а журнал знаковых транзакций: приход из чека (+),
-- расход из приёма пищи (-), ручная корректировка (±, включая "выбросил",
-- "закончилось" = -остаток, и ответы на сверку бота). Текущий остаток —
-- это SUM(change_amount) по продукту (см. вьюху v_inventory_current ниже).
CREATE TABLE IF NOT EXISTS inventory_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products (id),
    -- Signed, in the product's canonical_unit; fractional values are normal.
    change_amount REAL NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('receipt', 'meal', 'manual')),
    -- Polymorphic reference whose meaning depends on source_type (receipt id /
    -- meal id / NULL for manual). Loose coupling on purpose — no FK.
    source_id INTEGER,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_product
    ON inventory_ledger (product_id);

CREATE VIEW IF NOT EXISTS v_inventory_current AS
    SELECT product_id, SUM(change_amount) AS qty_estimate
    FROM inventory_ledger
    GROUP BY product_id;

-- Рецепты / сложные блюда (итерации 5/7). Позволяют логировать «борщ» одной
-- записью вместо перечисления свёклы/картошки/мяса каждый раз. БЖУ рецепта
-- считается на лету = Σ(БЖУ ингредиентов) / yield_grams * 100. Списание из
-- ledger — раскладкой порции на ингредиенты (масштаб grams / yield_grams).
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    -- Finished (cooked) weight of the whole recipe, for уварка/ужарка. NULL ->
    -- fall back to the sum of raw ingredient grams.
    yield_grams REAL,
    source TEXT CHECK (source IN ('user', 'llm')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes (id),
    product_id INTEGER NOT NULL REFERENCES products (id),
    -- Raw amount of the ingredient in the product's canonical_unit.
    grams REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_recipe
    ON recipe_ingredients (recipe_id);

-- Итерация 5: лог питания (однопользовательский — user scoping не вводим)
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    raw_text TEXT NOT NULL
);

-- Each item is EITHER a raw product OR a recipe (composite dish), never both
-- and never neither — enforced by the CHECK. БЖУ is recomputed on the fly from
-- current nutrition/recipe data; only grams are stored (no snapshot).
CREATE TABLE IF NOT EXISTS meal_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL REFERENCES meals (id),
    product_id INTEGER REFERENCES products (id),
    recipe_id INTEGER REFERENCES recipes (id),
    grams REAL NOT NULL,
    grams_source TEXT NOT NULL CHECK (grams_source IN ('user', 'llm_estimate')),
    CHECK (
        (product_id IS NOT NULL) + (recipe_id IS NOT NULL) = 1
    )
);

-- Итерация 6: цели пользователя (одна строка — личный инструмент)
CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_kcal_goal REAL,
    daily_protein_goal REAL,
    daily_fat_goal REAL,
    daily_carbs_goal REAL,
    restrictions TEXT,
    preferences TEXT,
    -- Telegram user bound to this profile (итерация 5).
    telegram_user_id TEXT
);
