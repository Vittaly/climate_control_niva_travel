# make_scr/main.py
"""Точка входа: поднимает логирование, собирает проект, трассирует, сохраняет.

Запуск:

    cd /любой/каталог
    python /путь/к/make_scr/main.py

Раскладка:

    <project>/
    ├── <project>.kicad_pro                    ← главный файл проекта KiCad
    ├── <project>.kicad_sch                    ← корневая схема (обычно совпадает)
    ├── sheets/
    │   ├── <project>.yaml                     ← корневой YAML (stem = stem .kicad_pro)
    │   └── <stem>.yaml                        ← остальные листы
    ├── make_scr/
    │   ├── main.py                            ← этот файл
    │   ├── project.py
    │   ├── out/                               ← логи (debug.log, router.log)
    │   └── ...
    └── out/                                   ← результаты (в cwd)

Идентификация листов — по stem'у YAML-файла:

    * Stem корня = stem .kicad_pro (имя главного файла проекта KiCad).
      Это же имя носит корневой .kicad_sch и корневой YAML:
      <stem>.kicad_pro ↔ <stem>.kicad_sch ↔ sheets/<stem>.yaml.
      Идеология «stem = имя файла без расширения» выполняется буквально.

    * Ключи в project.sheets:
        ""                    — корень (пишется по root_page.file,
                                 или, если он не задан, по stem'у)
        "<stem>.kicad_sch"    — иерархический или standalone лист

    * Имена X_* (иерархические компоненты в корневом YAML) на ключи
      project.sheets не влияют: связь «компонент ↔ файл» задана
      ровно в одном месте — атрибутом value_sch у соответствующего X_*.

Пути внутри main.py:
    _HERE      — каталог этого файла (make_scr/).
    _ROOT      — его родитель (корень проекта).
    ROOT_STEM  — stem <ROOT>.kicad_pro (см. ниже).
    ROOT_YAML  — sheets/<ROOT_STEM>.yaml.
    log_dir    — make_scr/out (логи).
    out_dir    — cwd (результаты: .kicad_sch, routes.txt).
"""
import sys
from pathlib import Path

# make_scr — каталог этого файла; корень проекта — его родитель.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from logging_setup import add_router_log, setup
from project import Project


def _detect_root_stem(root: Path) -> str:
    """Имя проекта = stem .kicad_pro в корне.

    KiCad однозначно определяет имя проекта по главному файлу
    .kicad_pro. Корневой .kicad_sch и sheets/<stem>.yaml носят
    то же имя, поэтому stem .kicad_pro становится ROOT_STEM
    для всей цепочки (проверки, генерация, run_e2e).
    """
    pro_files = sorted(root.glob("*.kicad_pro"))
    if not pro_files:
        raise FileNotFoundError(
            f"В {root} нет файла *.kicad_pro — не могу определить "
            f"имя проекта. Ожидается <project>.kicad_pro в корне."
        )
    if len(pro_files) > 1:
        names = ", ".join(p.name for p in pro_files)
        raise RuntimeError(
            f"В {root} найдено несколько .kicad_pro ({names}). "
            f"Оставьте один — имя проекта должно быть однозначным."
        )
    return pro_files[0].stem


try:
    ROOT_STEM = _detect_root_stem(_ROOT)
except (FileNotFoundError, RuntimeError) as e:
    # main() ниже покажет понятное сообщение и код возврата;
    # здесь — только чтобы ROOT_YAML можно было посчитать.
    print(f"Ошибка конфигурации проекта: {e}", file=sys.stderr)
    sys.exit(1)

ROOT_YAML = _ROOT / "sheets" / f"{ROOT_STEM}.yaml"


def _output_name(project: Project, key: str, sheet) -> str:
    """Имя выходного .kicad_sch по тому же правилу, что Project.save().

    Корень пишется по root_page.file; если поле не задано — по
    stem'у корневого YAML (согласуется со stem-идеологией:
    <stem>.yaml ↔ <stem>.kicad_sch). Обычные листы — по sheet_path.

    Функция нужна, чтобы сводка не разъезжалась с фактически
    записанными файлами: правило одно, вызывается из двух мест —
    save() и печать.
    """
    if key == "":
        return Path(
            project.root_data.get("file")
            or (project.root_path.stem + ".kicad_sch")
        ).name
    return sheet.sheet_path


def main() -> None:
    """Собирает проект по корневому YAML, трассирует и сохраняет результат."""
    root_yaml = ROOT_YAML                     # sheets/<ROOT_STEM>.yaml
    log_dir = _HERE / "out"                   # логи — рядом со скриптами
    out_dir = Path.cwd()                      # результаты — в cwd

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