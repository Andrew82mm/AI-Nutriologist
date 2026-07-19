-- Итерация 3 (инвентарь): готовка блюд.
--
-- 1) Связь рецепта с продуктом-блюдом, которым он лежит на складе. Готовка не
--    только сохраняет рецепт, но и ставит готовое блюдо на учёт отдельным
--    продуктом (category='блюда') — эта колонка их связывает. Аддитивно.
ALTER TABLE recipes ADD COLUMN product_id INTEGER REFERENCES products (id);

-- 2) Новый source_type 'cooked' для транзакций готовки: списание ингредиентов
--    (−) и постановка готового блюда (+), оба с source_id = recipe_id. SQLite не
--    умеет менять CHECK на месте, поэтому пересобираем таблицу. Вьюху сначала
--    роняем (она зависит от таблицы), потом пересоздаём.
DROP VIEW IF EXISTS v_inventory_current;

CREATE TABLE inventory_ledger_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products (id),
    change_amount REAL NOT NULL,
    source_type TEXT NOT NULL
        CHECK (source_type IN ('receipt', 'meal', 'manual', 'cooked')),
    source_id INTEGER,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO inventory_ledger_new
    (id, product_id, change_amount, source_type, source_id, note, created_at)
SELECT id, product_id, change_amount, source_type, source_id, note, created_at
FROM inventory_ledger;

DROP TABLE inventory_ledger;
ALTER TABLE inventory_ledger_new RENAME TO inventory_ledger;

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_product
    ON inventory_ledger (product_id);

CREATE VIEW IF NOT EXISTS v_inventory_current AS
    SELECT product_id, SUM(change_amount) AS qty_estimate
    FROM inventory_ledger
    GROUP BY product_id;
