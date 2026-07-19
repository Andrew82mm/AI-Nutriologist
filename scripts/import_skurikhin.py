#!/usr/bin/env python3
"""Импорт справочника Скурихина (.doc) в CSV с БЖУ на 100 г.

Справочник — бинарный MS Word с *текстовыми* таблицами (не скан), поэтому OCR
не нужен: конвертируем `.doc → HTML` через LibreOffice (`soffice`), затем
разбираем строки таблиц регуляркой (только stdlib, без новых зависимостей).

Строка-продукт распознаётся структурно: ячейка-код вида `N.N...` в позиции 0,
имя продукта в позиции 1, маркер порции `100` в позиции 2. Значения нутриентов
берутся по фиксированным смещениям от ячейки «100» — это устойчиво к строкам
разной ширины (12/14/15/16 колонок): лишние ячейки в широких строках всегда
хвостовые и пустые, а недостающие в узких — те же хвостовые колонки, которых
просто нет. Ккал в исходнике нет, считаем по Атуотеру (4·Б + 9·Ж + 4·У).

Запуск:
    python scripts/import_skurikhin.py "<путь к .doc>" [-o <путь к .csv>]
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Куда по умолчанию кладём датасет (package-data пакета products).
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "src/nutriologist/products/data/skurikhin_nutrition.csv"
)

# Смещения колонок относительно ячейки-маркера «100» (см. модуль-докстринг).
# Порядок колонок исходника: Вода Бел Жир НЖК Хол МДС Кр Угл ПВ ОК Зола.
_OFFSETS = {
    "water": 1,
    "protein": 2,
    "fat": 3,
    "sat_fat": 4,
    "cholesterol": 5,
    "sugars": 6,  # МДС — моно- и дисахариды
    "starch": 7,  # Кр — крахмал
    "carbs": 8,  # Угл — усвояемые углеводы (итог)
    "fiber": 9,  # ПВ — пищевые волокна
    "organic_acids": 10,  # ОК
    "ash": 11,  # Зола
}

# Итоговый порядок колонок в CSV: макросы вперёд, остальное следом.
_FIELDS = [
    "code",
    "name",
    "category_path",
    "protein",
    "fat",
    "carbs",
    "kcal",
    "water",
    "sat_fat",
    "cholesterol",
    "sugars",
    "starch",
    "fiber",
    "organic_acids",
    "ash",
]

# Продукт — код с >=1 точкой; заголовок раздела может быть и одноуровневым («1»).
_CODE_RE = re.compile(r"^\d+(\.\d+)+$")
_ANY_CODE_RE = re.compile(r"^\d+(\.\d+)*$")
_ROW_RE = re.compile(r"<tr.*?</tr>", re.S)
_CELL_RE = re.compile(r"<t[dh].*?>(.*?)</t[dh]>", re.S)
_TAG_RE = re.compile(r"<.*?>")


def convert_doc_to_html(doc_path: Path, workdir: Path) -> Path:
    """Конвертирует .doc в .html через LibreOffice, возвращает путь к .html."""
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "html",
            "--outdir",
            str(workdir),
            str(doc_path),
        ],
        check=True,
        capture_output=True,
    )
    html_path = workdir / (doc_path.stem + ".html")
    if not html_path.exists():
        raise RuntimeError(f"LibreOffice не создал {html_path}")
    return html_path


def _cells(row_html: str) -> list[str]:
    out = []
    for raw in _CELL_RE.findall(row_html):
        text = html.unescape(_TAG_RE.sub("", raw)).replace("\xa0", " ").strip()
        out.append(text)
    return out


def _num(cell: str) -> float | None:
    """'3,0' → 3.0; '2,4*' → 2.4 (сноска срезается); '', '-', '—' → None."""
    text = re.sub(r"\*.*$", "", cell.strip().replace(",", ".")).strip()
    if text in ("", "-", "—"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean_title(text: str) -> str:
    """Схлопнуть пробелы/переносы и срезать префикс «Таблица N.»."""
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^Таблица\s+\d+\.\s*", "", text).strip()


def collect_headers(rows: list[str]) -> dict[str, str]:
    """Карта {код-раздела: заголовок} из строк-заголовков разделов.

    Заголовки («1.6 СЫРЫ», «1.6.5 ПЛАВЛЕНЫЕ», «12 Таблица 12. ВСПОМОГАТЕЛЬНЫЕ…»)
    дают контекст, которого нет в листовом имени продукта («Сказка»). Признак
    заголовка: код в позиции 0 и *ровно одна* непустая ячейка-текст после него
    (ширина строки в исходнике плавает 2–5 колонок с пустыми хвостами). Это
    отсекает и продукты (маркер «100» + числа), и методические таблицы (много
    числовых ячеек).
    """
    headers: dict[str, str] = {}
    for row_html in rows:
        cells = _cells(row_html)
        if len(cells) < 2 or not _ANY_CODE_RE.match(cells[0].strip()):
            continue
        if len(cells) > 2 and cells[2].strip() == "100":
            continue  # это продукт, не заголовок
        rest = [c for c in cells[1:] if c.strip()]
        if len(rest) != 1:
            continue  # у заголовка ровно один текстовый столбец — название
        title = _clean_title(rest[0])
        if not title or title.replace(".", "").replace(",", "").replace(" ", "").isdigit():
            continue
        headers.setdefault(cells[0].strip(), title)  # первое вхождение — верное
    return headers


def _category_path(code: str, headers: dict[str, str]) -> str:
    """Путь из заголовков всех префиксов кода, напр. `СЫРЫ > ПЛАВЛЕНЫЕ`."""
    parts = code.split(".")
    titles = [
        headers[prefix]
        for i in range(1, len(parts))
        if (prefix := ".".join(parts[:i])) in headers
    ]
    return " > ".join(titles)


def parse_html(html_path: Path) -> list[dict]:
    data = html_path.read_text(encoding="utf-8", errors="replace")
    rows = _ROW_RE.findall(data)
    headers = collect_headers(rows)
    records: list[dict] = []
    for row_html in rows:
        cells = _cells(row_html)
        if len(cells) < 11 or not _CODE_RE.match(cells[0].strip()):
            continue
        # Якорь: маркер порции «100» должен стоять в позиции 2 (после кода и имени).
        try:
            anchor = cells.index("100")
        except ValueError:
            continue
        if anchor != 2:
            continue
        name = re.sub(r"\s+", " ", cells[1]).strip()
        if not name:
            continue

        def value(offset: int) -> float | None:
            idx = anchor + offset
            return _num(cells[idx]) if idx < len(cells) else None

        rec = {key: value(off) for key, off in _OFFSETS.items()}
        # Углеводы: при пустой итоговой ячейке — фолбэк на сумму МДС+крахмал.
        if rec["carbs"] is None and (
            rec["sugars"] is not None or rec["starch"] is not None
        ):
            rec["carbs"] = (rec["sugars"] or 0) + (rec["starch"] or 0)
        if rec["protein"] is None and rec["fat"] is None and rec["carbs"] is None:
            continue  # строка без единого макроса — не продукт
        rec["code"] = cells[0].strip()
        rec["name"] = name
        rec["category_path"] = _category_path(rec["code"], headers)
        rec["kcal"] = round(
            (rec["protein"] or 0) * 4
            + (rec["fat"] or 0) * 9
            + (rec["carbs"] or 0) * 4,
            1,
        )
        records.append(rec)
    return records


def write_csv(records: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for rec in records:
            writer.writerow({key: rec.get(key) for key in _FIELDS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("doc", type=Path, help="путь к .doc справочника Скурихина")
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="путь к выходному CSV"
    )
    args = parser.parse_args(argv)

    if not args.doc.exists():
        print(f"Файл не найден: {args.doc}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        html_path = convert_doc_to_html(args.doc, Path(tmp))
        records = parse_html(html_path)

    write_csv(records, args.output)
    print(f"Извлечено продуктов: {len(records)}")
    print(f"Записано: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
