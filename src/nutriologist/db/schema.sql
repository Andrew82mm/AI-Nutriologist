-- Full data model per PLAN.md section 8. Tables are created up front so
-- later iterations don't need their own migrations for the base shape;
-- columns/indexes that a specific iteration still needs to populate are
-- noted inline.

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
    product_id INTEGER REFERENCES products (id)
);

CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt_id
    ON receipt_items (receipt_id);

-- Итерация 2: нормализация продуктов + БЖУ
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    category TEXT,
    is_food INTEGER NOT NULL,
    shelf_life_days INTEGER
);

CREATE TABLE IF NOT EXISTS product_aliases (
    raw_name TEXT PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products (id)
);

CREATE TABLE IF NOT EXISTS nutrition (
    product_id INTEGER NOT NULL REFERENCES products (id),
    kcal REAL,
    protein REAL,
    fat REAL,
    carbs REAL,
    source TEXT NOT NULL CHECK (source IN ('db', 'user', 'llm_estimate')),
    PRIMARY KEY (product_id)
);

-- Итерация 3: инвентарь
CREATE TABLE IF NOT EXISTS inventory (
    product_id INTEGER PRIMARY KEY REFERENCES products (id),
    qty_estimate REAL NOT NULL,
    confidence REAL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Итерация 5: лог питания
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    raw_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL REFERENCES meals (id),
    product_id INTEGER REFERENCES products (id),
    grams REAL NOT NULL,
    grams_source TEXT NOT NULL CHECK (grams_source IN ('user', 'llm_estimate'))
);

-- Итерация 6: цели пользователя
CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_kcal_goal REAL,
    daily_protein_goal REAL,
    daily_fat_goal REAL,
    daily_carbs_goal REAL,
    restrictions TEXT,
    preferences TEXT
);
