# make_scr/library_manager.py
"""Ленивая генерация и регистрация пользовательской библиотеки KiCad.

Одна библиотека на проект — общий контейнер для всех сгенерированных
символов и футпринтов. Отдельных библиотек «на тип» не заводим: KiCad
работает с одной projectLib на проект, и все символы живут внутри неё.

Layout (от корня проекта, а не от sheets/):

    <project_root>/libs/projectLib.kicad_sym
    <project_root>/libs/projectLib.pretty/
    <project_root>/libs/projectLib.pretty/packages3d/

Три точки — генерация (JLC2KiCadLib), проверка (поиск по lcsc_id),
регистрация в sym-lib-table/fp-lib-table — используют одни и те же
поля self.sym_file и self.fp_dir.

JLC2KiCadLib вызывается как Python-библиотека через
JLC2KiCadLib.JLC2KiCadLib.add_component(component_id, args).
Аргумент args — argparse.Namespace с полями CLI. Собираем его так,
чтобы инструмент писал ровно в наш layout:

    output_dir       = libs_root
    symbol_lib       = LIB_NAME
    symbol_lib_dir   = "" (символ в корень libs_root, а не в symbol/)
    footprint_lib    = LIB_NAME (инструмент сам добавит .pretty)
    models           = "STEP"
    model_dir        = "packages3d"

Контракт ensure_type (ДВА обязательства):

    1. tdef["symbol"] после успешного возврата ОБЯЗАН быть установлен.
       Если symbol установить не удалось — RuntimeError с диагностикой.

    2. Возвращается Path к .kicad_sym ВСЕГДА, когда symbol установлен,
       вне зависимости от того, был файл только что создан или уже
       существовал. Sheet._load_components по непустому возврату
       вызывает self.source.register_library(lib_path) — без этого
       KiCadSource не знает о projectLib и не находит в нём символы
       (KeyError: 'Символ не найден: projectLib:…').

    Footprint НЕ входит в контракт: символ без footprint в схеме
    допустим. Отсутствие footprint — только warning в лог.

Формат .kicad_sym (JLC2KiCadLib):
    Символы пишутся с отступом в 2 пробела:
        (kicad_symbol_lib …
          (symbol "NAME" …
            (property "LCSC" "C…" …)
    Поэтому блоки символов ищутся по '^\\s*\\(symbol\\s+"NAME"', а не
    по '^\\(symbol' — иначе ни один символ не находится.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional, Set

from constants import LibTableKind
from logging_setup import get_logger

log = get_logger(__name__)


try:
    from JLC2KiCadLib.JLC2KiCadLib import add_component as _jlc_add_component
except ImportError as _e:
    _jlc_add_component = None
    _jlc_import_error = _e
else:
    _jlc_import_error = None


class LibraryManager:
    """Генерирует projectLib.kicad_sym по lcsc_id и отдаёт пути в KiCadSource.

    Жизненный цикл:
        LibraryManager — вспомогательный объект Project. Создаётся
        один раз в load(), накапливает символы/футпринты в одной
        библиотеке проекта по мере появления новых типов.

    Раскладка файлов (всё — от корня проекта):
        <project_root>/libs/projectLib.kicad_sym       — символы;
        <project_root>/libs/projectLib.pretty/         — посадочные;
        <project_root>/libs/projectLib.pretty/packages3d/  — 3D-модели.

    project_root — каталог с .kicad_pro. Генерируемые библиотеки
    лежат в <project_root>/libs/ — это часть исходников, а не
    артефакт генерации.
    """

    LIB_NAME = "projectLib"

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.libs_root = self.project_root / "libs"

        self.lib_name = self.LIB_NAME
        self.sym_file = self.libs_root / f"{self.lib_name}.kicad_sym"
        self.fp_dir = self.libs_root / f"{self.lib_name}.pretty"

        self._resolved: Set[str] = set()

        log.info(
            "LibraryManager: project_root=%s libs_root=%s "
            "sym_file=%s fp_dir=%s",
            self.project_root, self.libs_root,
            self.sym_file, self.fp_dir,
        )

        if _jlc_add_component is None:
            log.warning(
                "LibraryManager: JLC2KiCadLib недоступен — импорт "
                "JLC2KiCadLib.JLC2KiCadLib.add_component упал: %s",
                _jlc_import_error,
            )

    # ---------- публичное ----------

    def ensure_type(self, type_name: str, tdef: dict) -> Optional[Path]:
        """Гарантирует наличие symbol и footprint для типа.

        Возвращает Path к .kicad_sym, если symbol установлен (был
        установлен ранее, найден в существующем файле, или только что
        сгенерирован). Этот путь нужен Sheet._load_components для
        вызова self.source.register_library(lib_path) — без него
        KiCadSource не знает о библиотеке projectLib.

        Контракт:
            * tdef["symbol"] после возврата установлен;
            * если symbol установить не удалось — RuntimeError.

        Returns:
            Path к .kicad_sym, если файл существует. None — только
            если symbol установлен в tdef, но файла по этому пути
            нет (аномалия: пользователь задал symbol явно, а файла
            нет — тогда регистрировать нечего).
        """
        if type_name in self._resolved:
            if not tdef.get("symbol"):
                raise RuntimeError(
                    f"LibraryManager: ensure_type для {type_name} "
                    f"вызван повторно, но symbol не установлен. "
                    f"Первый вызов завершился с ошибкой — см. лог выше."
                )
            # symbol уже установлен — вернуть путь для регистрации.
            return self.sym_file if self.sym_file.exists() else None
        self._resolved.add(type_name)

        lcsc_id = tdef.get("lcsc_id")
        if not lcsc_id:
            if not tdef.get("symbol"):
                raise RuntimeError(
                    f"LibraryManager: {type_name} — нет lcsc_id и нет "
                    f"symbol. Не могу сгенерировать или найти символ."
                )
            # Пользователь задал symbol явно, lcsc_id нет.
            # Регистрировать нечего, но символ уже прописан.
            return self.sym_file if self.sym_file.exists() else None

        has_symbol = bool(tdef.get("symbol"))
        has_footprint = bool(tdef.get("footprint"))
        if has_symbol and has_footprint:
            log.debug(
                "LibraryManager: %s (lcsc_id=%s): оба поля уже заданы, "
                "пропуск",
                type_name, lcsc_id,
            )
            # ВАЖНО: возвращаем путь, чтобы Sheet зарегистрировал
            # библиотеку в KiCadSource. Иначе символ прописан,
            # а get_pins по нему упадёт с KeyError.
            return self.sym_file if self.sym_file.exists() else None

        log.info(
            "LibraryManager: ensure_type %s (lcsc_id=%s) — "
            "symbol=%s footprint=%s",
            type_name, lcsc_id, has_symbol, has_footprint,
        )

        # ─── проверка symbol в уже существующих файлах ───
        if not has_symbol:
            if not self.sym_file.exists():
                log.info(
                    "LibraryManager: %s (lcsc_id=%s): %s не существует — "
                    "потребуется генерация",
                    type_name, lcsc_id, self.sym_file,
                )
            else:
                name = self._find_symbol_name(self.sym_file, lcsc_id)
                if name:
                    tdef["symbol"] = f"{self.lib_name}:{name}"
                    has_symbol = True
                    log.info(
                        "LibraryManager: %s (lcsc_id=%s): символ найден — "
                        "%s:%s",
                        type_name, lcsc_id, self.lib_name, name,
                    )
                else:
                    log.warning(
                        "LibraryManager: %s (lcsc_id=%s): %s существует, "
                        "но lcsc_id не найден — потребуется генерация",
                        type_name, lcsc_id, self.sym_file,
                    )

        # ─── проверка footprint в уже существующих файлах ───
        if not has_footprint:
            if not self.fp_dir.exists():
                log.info(
                    "LibraryManager: %s (lcsc_id=%s): %s не существует — "
                    "потребуется генерация",
                    type_name, lcsc_id, self.fp_dir,
                )
            else:
                name = self._find_footprint_name(self.fp_dir, lcsc_id)
                if name:
                    tdef["footprint"] = f"{self.lib_name}:{name}"
                    has_footprint = True
                    log.info(
                        "LibraryManager: %s (lcsc_id=%s): footprint найден — "
                        "%s:%s",
                        type_name, lcsc_id, self.lib_name, name,
                    )
                else:
                    log.warning(
                        "LibraryManager: %s (lcsc_id=%s): %s существует, "
                        "но lcsc_id не найден — потребуется генерация",
                        type_name, lcsc_id, self.fp_dir,
                    )

        if has_symbol and has_footprint:
            return self.sym_file if self.sym_file.exists() else None

        # ─── генерация через JLC2KiCadLib (Python API) ───
        self._call_jlc_add_component(type_name, lcsc_id)

        log.info(
            "LibraryManager: %s (lcsc_id=%s): JLC2KiCadLib завершён, "
            "sym_file=%s (exists: %s), fp_dir=%s (exists: %s)",
            type_name, lcsc_id,
            self.sym_file, self.sym_file.exists(),
            self.fp_dir, self.fp_dir.exists(),
        )

        # ─── повторный поиск symbol ───
        if not has_symbol:
            name = self._find_symbol_name(self.sym_file, lcsc_id)
            if name:
                tdef["symbol"] = f"{self.lib_name}:{name}"
                has_symbol = True
                log.info(
                    "LibraryManager: %s (lcsc_id=%s): символ найден "
                    "после генерации — %s:%s",
                    type_name, lcsc_id, self.lib_name, name,
                )
            else:
                log.error(
                    "LibraryManager: %s (lcsc_id=%s): символ НЕ найден "
                    "даже после генерации.\n"
                    "  Искали в: %s (exists: %s)\n"
                    "  project_root: %s",
                    type_name, lcsc_id,
                    self.sym_file, self.sym_file.exists(),
                    self.project_root,
                )

        # ─── повторный поиск footprint ───
        if not has_footprint:
            name = self._find_footprint_name(self.fp_dir, lcsc_id)
            if name:
                tdef["footprint"] = f"{self.lib_name}:{name}"
                has_footprint = True
                log.info(
                    "LibraryManager: %s (lcsc_id=%s): footprint найден "
                    "после генерации — %s:%s",
                    type_name, lcsc_id, self.lib_name, name,
                )
            else:
                log.warning(
                    "LibraryManager: %s (lcsc_id=%s): footprint не найден "
                    "после генерации. Задайте footprint: явно в "
                    "component_types[%s] или разберитесь с JLC2KiCadLib.",
                    type_name, lcsc_id, type_name,
                )

        # ─── контракт: symbol установлен или исключение ───
        if not tdef.get("symbol"):
            raise RuntimeError(
                f"LibraryManager: symbol для {type_name} "
                f"(lcsc_id={lcsc_id}) не установлен.\n"
                f"  libs_root:    {self.libs_root}\n"
                f"  sym_file:     {self.sym_file} "
                f"(exists: {self.sym_file.exists()})\n"
                f"  fp_dir:       {self.fp_dir} "
                f"(exists: {self.fp_dir.exists()})\n"
                f"  project_root: {self.project_root}\n"
                f"  Причины — в логе выше (строки LibraryManager: …)."
            )

        return self.sym_file if self.sym_file.exists() else None

    def _call_jlc_add_component(self, type_name: str, lcsc_id: str) -> None:
        """Вызвать JLC2KiCadLib.JLC2KiCadLib.add_component(id, args)."""
        if _jlc_add_component is None:
            raise RuntimeError(
                "JLC2KiCadLib недоступен: импорт "
                "JLC2KiCadLib.JLC2KiCadLib.add_component упал "
                f"({_jlc_import_error}). Установите пакет в то же "
                "окружение, из которого запускается проект."
            )

        self.libs_root.mkdir(parents=True, exist_ok=True)

        args = argparse.Namespace(
            output_dir=str(self.libs_root),
            symbol_lib=self.lib_name,
            symbol_lib_dir="",
            symbol_creation=True,
            footprint_lib=self.lib_name,
            footprint_creation=True,
            models="STEP",
            model_dir="packages3d",
            model_base_variable="",
            skip_existing=False,
        )

        log.info(
            "LibraryManager: %s (lcsc_id=%s): вызов add_component, "
            "output_dir=%s symbol_lib=%s footprint_lib=%s",
            type_name, lcsc_id,
            args.output_dir, args.symbol_lib, args.footprint_lib,
        )

        try:
            _jlc_add_component(str(lcsc_id), args)
        except Exception as e:
            raise RuntimeError(
                f"JLC2KiCadLib.add_component: ошибка генерации "
                f"{lcsc_id}: {type(e).__name__}: {e}\n"
                f"  output_dir={args.output_dir}\n"
                f"  symbol_lib={args.symbol_lib} "
                f"symbol_lib_dir={args.symbol_lib_dir!r}\n"
                f"  footprint_lib={args.footprint_lib} "
                f"model_dir={args.model_dir}\n"
                f"  Проверьте доступность LCSC и корректность lcsc_id."
            ) from e

    def library_entries(self) -> List[tuple]:
        """[(kind, nickname, abs_path), ...] для sym-lib-table / fp-lib-table."""
        return [
            (LibTableKind.SYMBOL, self.lib_name, self.sym_file),
            (LibTableKind.FOOTPRINT, self.lib_name, self.fp_dir),
        ]

    # ---------- поиск в сгенерированных файлах ----------

    def _find_symbol_name(self, sym_file: Path, lcsc_id: str) -> Optional[str]:
        """Имя символа, содержащего lcsc_id, в .kicad_sym.

        Регулярка учитывает ведущий отступ: JLC2KiCadLib пишет
        символы с отступом в 2 пробела внутри (kicad_symbol_lib …).
        """
        if not sym_file.exists():
            return None
        try:
            text = sym_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        needle = str(lcsc_id)

        starts = [
            (m.start(), m.group(1))
            for m in re.finditer(
                r'^\s*\(symbol\s+"([^"]+)"', text, re.MULTILINE,
            )
        ]
        for i, (pos, name) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
            if needle in text[pos:end]:
                return name
        return None

    def _find_footprint_name(
        self, fp_dir: Path, lcsc_id: str,
    ) -> Optional[str]:
        """Имя .kicad_mod с lcsc_id в описании (или None)."""
        if not fp_dir.exists():
            return None
        needle = str(lcsc_id)
        for f in fp_dir.glob("*.kicad_mod"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle in text:
                return f.stem
        return None