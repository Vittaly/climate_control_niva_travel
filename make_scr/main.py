# make_scr/main.py
"""Точка входа: поднимает логирование, собирает проект, трассирует, сохраняет.

Идентификация листов — по stem'у YAML-файла. Project хранит
единственный корневой Sheet (project.root_sheet). Дочерние листы
находятся обходом дерева через SheetRefComponent.child_sheet.

Раскладка:

    <project>/
    ├── <project>.kicad_pro                    ← главный файл проекта KiCad
    ├── <project>.kicad_sch                    ← корневая схема
    ├── sheets/
    │   ├── <project>.yaml                     ← корневой YAML
    │   └── <stem>.yaml                        ← остальные листы
    ├── make_scr/
    │   ├── main.py                            ← этот файл
    │   ├── out/                               ← логи (debug.log, router.log)
    │   └── ...
    └── out/                                   ← результаты (в cwd)
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from logging_setup import add_router_log, setup
from project import Project


def _detect_root_stem(root: Path) -> str:
    pro_files = sorted(root.glob("*.kicad_pro"))
    if not pro_files:
        raise FileNotFoundError(
            f"В {root} нет файла *.kicad_pro — не могу определить "
            f"имя проекта."
        )
    if len(pro_files) > 1:
        names = ", ".join(p.name for p in pro_files)
        raise RuntimeError(
            f"В {root} найдено несколько .kicad_pro ({names})."
        )
    return pro_files[0].stem


try:
    ROOT_STEM = _detect_root_stem(_ROOT)
except (FileNotFoundError, RuntimeError) as e:
    print(f"Ошибка конфигурации проекта: {e}", file=sys.stderr)
    sys.exit(1)

ROOT_YAML = _ROOT / "sheets" / f"{ROOT_STEM}.yaml"


def _iter_sheets(root_sheet):
    """DFS по дереву Sheet'ов от корня, дедупликация по id()."""
    seen: set[int] = set()

    def visit(sheet):
        if id(sheet) in seen:
            return
        seen.add(id(sheet))
        yield sheet
        for comp in sheet.components.values():
            if not getattr(comp, "is_sheet_ref", False):
                continue
            child = getattr(comp, "child_sheet", None)
            if child is not None:
                yield from visit(child)

    yield from visit(root_sheet)


def main() -> None:
    root_yaml = ROOT_YAML
    log_dir = _HERE / "out"
    out_dir = Path.cwd()

    if not root_yaml.exists():
        print(f"Не найден {root_yaml}", file=sys.stderr)
        print(
            f"  Ожидается: sheets/<имя проекта>.yaml\n"
            f"  Имя проекта (stem .kicad_pro): {ROOT_STEM}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ---------- логирование ----------
    debug_log = setup(level=10, log_file=log_dir / "debug.log")
    print(f"Лог-файл:       {debug_log}")

    router_log = add_router_log(log_dir / "router.log")
    if router_log:
        print(f"Лог роутера:    {router_log}")

    print(f"Проект:         {ROOT_STEM}")
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
    root = project.root_sheet
    if root is None:
        print("!! project.root_sheet == None после load()", file=sys.stderr)
        sys.exit(1)

    sheets = list(_iter_sheets(root))
    total_components = sum(len(s.components) for s in sheets)

    print(f"Листов:      {len(sheets)}")
    print(f"Компонентов: {total_components}")
    print()

    for sheet in sheets:
        is_root = (sheet is root)
        marker = "root" if is_root else "    "
        # page и out_file — вычисляемые property от yaml_path.
        page = getattr(sheet, "page", "-")
        out_file = getattr(sheet, "out_file", "-")
        print(f"  [{marker}] {sheet.stem:<32} page={page:<24} → {out_file}")


if __name__ == "__main__":
    main()