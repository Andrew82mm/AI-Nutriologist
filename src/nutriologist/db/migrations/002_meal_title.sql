-- Пользовательское название приёма пищи (Завтрак/Обед/Ужин/Перекус или своё).
-- NULL → название выводится из времени приёма (api/diary._meal_title). Аддитивно.
ALTER TABLE meals ADD COLUMN title TEXT;
