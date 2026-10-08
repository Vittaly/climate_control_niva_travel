# make_scr/main.py
"""Точка входа: поднимает логирование, собирает проект, трассирует, сохраняет.

Идентификация проекта — по имени каталога, в котором лежит make_scr/.

    <project>/
    ├── <project>.kicad_pro                    ← главный файл проекта KiCad
    ├── <project>.kicad_sch
    ├── sheets/
    │   ├── <project>.yaml                     ← корневой YAML
    │   └── <stem>.yaml                        ← остальные листы
    ├── make_scr/
    │   ├── main.py                            ← этот файл
    │   ├── out/                               ← логи
    │   └── ...
    └── out/                                   ← результаты (в cwd)

ROOT_STEM = имя каталога-проекта (родитель make_scr/). Рядом с
make_scr/ обычно лежит <ROOT_STEM>.kicad_pro — наличие проверяется,
отсутствие не критично (файлы библиотек создадутся по ${KIPRJMOD}).
Посторонние .kicad_pro в каталоге игнорируются.

Политика ошибок загрузки:
    Project.load() собирает все проблемы YAML в self.load_errors и
    в конце бросает ProjectLoadError с полным списком. main() ловит
    его, печатает текст в stderr и завершается с кодом 1 — без
    traceback. Тот же текст уже записан в debug.log.

    Ошибки на последующих стадиях (place_and_route, save) не ловятся
    здесь: их падение — баг, а не ошибка конфигурации, и traceback
    уместен.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent   # <project>/make_scr
_ROOT = _HERE.parent                       # <project>

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from logging_setup import add_router_log, setup
from project import Project, ProjectLoadError
from constants import ComponentKind


class ProjectConfigError(Exception):
    """Не удалось определить корень проекта по имени каталога."""
    pass


def _detect_root_stem(root: Path) -> str:
    """Корневой stem = имя каталога-проекта.

    Каталог-проект — тот, что содержит make_scr/. Имя этого каталога
    должно совпадать:
        * с именем корневого YAML — <root>/sheets/<name>.yaml;
        * с именем главного .kicad_pro — <root>/<name>.kicad_pro.

    Если YAML нет — ошибка (нечего грузить).
    Если .kicad_pro нет — это не ошибка: файлы проекта могут ещё не
    существовать, библиотеки создадутся в out_dir по ${KIPRJMOD}.

    Raises:
        ProjectConfigError: каталог sheets/ отсутствует, или в нём
            нет <name>.yaml.
    """
    name = root.name
    if not name:
        raise ProjectConfigError(
            f"не удалось получить имя каталога-проекта из {root}"
        )

    sheets_dir = root / "sheets"
    if not sheets_dir.is_dir():
        raise ProjectConfigError(
            f"нет каталога {sheets_dir} — не могу найти корневой YAML "
            f"<name>.yaml для проекта {name!r}"
        )

    root_yaml = sheets_dir / f"{name}.yaml"
    if not root_yaml.exists():
        raise ProjectConfigError(
            f"нет {root_yaml} — имя корневого YAML должно совпадать "
            f"с именем каталога-проекта {name!r}"
        )

    pro = root / f"{name}.kicad_pro"
    if not pro.exists():
        print(
            f"Замечание: рядом нет {pro.name} — "
            f"библиотеки создадутся по ${KIPRJMOD} из out_dir.",
            file=sys.stderr,
        )

    return name


try:
    ROOT_STEM = _detect_root_stem(_ROOT)
except ProjectConfigError as e:
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
            if getattr(comp, "kind", None) != ComponentKind.SHEET_REF:
                continue
            child = getattr(comp, "child_sheet", None)
            if child is not None:
                yield from visit(child)

    yield from visit(root_sheet)


def main() -> int:
    root_yaml = ROOT_YAML
    log_dir = _HERE / "out"
    out_dir = Path.cwd()

    if not root_yaml.exists():
        print(f"Не найден {root_yaml}", file=sys.stderr)
        print(
            f"  Ожидается: sheets/<имя каталога-проекта>.yaml\n"
            f"  Имя каталога-проекта: {ROOT_STEM}",
            file=sys.stderr,
        )
        return 1

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
    try:
        project = Project(root_yaml).load()
    except ProjectLoadError as e:
        print(file=sys.stderr)
        print(e, file=sys.stderr)
        print(file=sys.stderr)
        print(
            "Загрузка прервана. Детали — в debug.log.",
            file=sys.stderr,
        )
        return 1

    # ---------- размещение, роутинг, сохранение ----------
    project.place_and_route()
    project.save(out_dir)

    # ---------- сводка ----------
    root = project.root_sheet
    if root is None:
        print("!! project.root_sheet == None после load()", file=sys.stderr)
        return 1

    sheets = list(_iter_sheets(root))
    total_components = sum(len(s.components) for s in sheets)

    print(f"Листов:      {len(sheets)}")
    print(f"Компонентов: {total_components}")
    print()

    for sheet in sheets:
        is_root = (sheet is root)
        marker = "root" if is_root else "    "
        page = getattr(sheet, "page", "-")
        out_file = getattr(sheet, "out_file", "-")
        print(f"  [{marker}] {sheet.stem:<32} page={page:<24} → {out_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())