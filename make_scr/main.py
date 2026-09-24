# make_scr/main.py
"""Точка входа: поднимает логирование, собирает проект, трассирует, сохраняет.

Запуск:

    cd /любой/каталог
    python /путь/к/make_scr/main.py

Раскладка:

    project/
    ├── sheets/
    │   ├── main.yaml          ← вход
    │   └── <stem>.yaml        ← листы (иерархия и standalone)
    ├── make_scr/
    │   ├── main.py            ← этот файл
    │   ├── project.py
    │   ├── out/               ← логи (debug.log, router.log)
    │   └── ...
    └── out/                   ← результаты (.kicad_sch, routes.txt)
                                 (в cwd, откуда вызван скрипт)

Идентификация листов — по stem'у YAML-файла. Ключи в project.sheets:

    ""                    — корень (пишется по main.yaml:file)
    "<stem>.kicad_sch"    — иерархический или standalone лист

Имена X_* (иерархические компоненты в main.yaml) на ключи
project.sheets не влияют: связь «компонент ↔ файл» задана ровно
в одном месте — атрибутом value_sch у соответствующего X_*.
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


def _output_name(project: Project, key: str, sheet) -> str:
    """Имя выходного .kicad_sch по тому же правилу, что Project.save().

    Вынесено в отдельную функцию, чтобы сводка не разъезжалась
    с фактически записанными файлами: правило одно, вызывается из
    двух мест — save() и печать.
    """
    if key == "":
        return Path(
            project.root_data.get("file", "root.kicad_sch")
        ).name
    return sheet.sheet_path


def main() -> None:
    """Собирает проект по main.yaml, трассирует и сохраняет результат."""
    root_yaml = _ROOT / "sheets" / "main.yaml"    # вход — рядом с make_scr
    log_dir = _HERE / "out"                       # логи — рядом со скриптами
    out_dir = Path.cwd()                          # результаты — в cwd

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
        Project(root_yaml)
        .load()
        .place_and_route()
    )
    project.save(out_dir)

    # ---------- сводка ----------
    total = sum(len(s.components) for s in project.sheets.values())
    print(f"Компонентов: {total}")
    print(f"Листов:      {len(project.sheets)}")

    for key, sheet in project.sheets.items():
        label = "root" if key == "" else key
        out_name = _output_name(project, key, sheet)
        page = sheet.page or "—"
        print(f"  {label:<32} page={page:<24} → {out_name}")


if __name__ == "__main__":
    main()