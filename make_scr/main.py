# make_scr/main.py
"""Точка входа: поднимает логирование, собирает проект, трассирует, сохраняет.

Запуск:

    cd /любой/каталог
    python /путь/к/make_scr/main.py

Раскладка:

    project/
    ├── main.yaml
    ├── sheets/*.yaml
    └── make_scr/
        ├── main.py          ← этот файл
        ├── project.py
        ├── out/             ← логи (debug.log, router.log)
        └── ...

Вход (main.yaml) ищется рядом с make_scr — путь от __file__.
Логи (debug.log, router.log) — в make_scr/out/.
Результаты роутинга (.kicad_sch, routes.txt) — в текущей рабочей
директории, откуда был вызван скрипт.
"""
import sys
from pathlib import Path

# make_scr — каталог этого файла; project — его родитель
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from logging_setup import add_router_log, setup
from project import Project
from constants import DEFAULT_GRID_MM


def main() -> None:
    """Собирает проект по main.yaml, трассирует и сохраняет результат."""
    root_yaml = _ROOT / "main.yaml"       # вход — рядом с make_scr
    log_dir = _HERE / "out"               # логи — рядом со скриптами
    out_dir = Path.cwd()                  # результаты — в cwd

    if not root_yaml.exists():
        print(f"Не найден {root_yaml}", file=sys.stderr)
        sys.exit(1)

    # ---------- логирование ----------
    debug_log = setup(level=10, log_file=log_dir / "debug.log")
    print(f"Лог-файл:       {debug_log}")

    router_log = add_router_log(log_dir / "router.log")
    if router_log:
        print(f"Лог роутера:    {router_log}")

    print(f"Корневой YAML:  {root_yaml}")
    print(f"Каталог вывода: {out_dir}")

    # ---------- проект ----------
    project = (
        Project(root_yaml, grid_mm=DEFAULT_GRID_MM)
        .load()
        .place_and_route()
    )
    project.save(out_dir)

    # ---------- сводка ----------
    total = sum(len(s.components) for s in project.sheets.values())
    print(f"Компонентов: {total}")
    print(f"Листов: {len(project.sheets)}")
    for ref, sheet in project.sheets.items():
        print(f"  {ref or 'root'}: {sheet.name} → {sheet.out_file}")


if __name__ == "__main__":
    main()