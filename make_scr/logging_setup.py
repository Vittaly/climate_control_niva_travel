# make_scr/logging_setup.py
"""Единая настройка логирования.

Дополнительный уровень TRACE (5) — ниже DEBUG (10). Используется
для горячих мест: циклы Dijkstra, обход клеток, проверки блокировок.
По умолчанию выключен: в конфигурации DEBUG не пропускает TRACE.

Использование:
    from logging_setup import setup, add_router_log, get_logger, ctx, TRACE

    setup(level=logging.INFO)          # консоль
    add_router_log("out/router.log")   # отдельный файл для роутера

    log = get_logger(__name__)
    log.trace("...")                   # виден только при setup(level=TRACE)

Формат лог-строки:
    <time> | <level> | <logger> | <ctx> <message>

где <ctx> — префикс из ctx(): [page] [net] [comp] [pin] — в этом
фиксированном порядке. Пропущенное поле В СЕРЕДИНЕ выводится как [-],
чтобы сохранить позицию. Пропущенные ХВОСТОВЫЕ поля опускаются.

Примеры:
    ctx(page="root")                          → "[root]"
    ctx(page="root", net="VCC_3V3")           → "[root] [VCC_3V3]"
    ctx(page="root", comp="C7")               → "[root] [-] [C7]"
    ctx(page="root", comp="C7", pin="C7:1")   → "[root] [-] [C7] [C7:1]"
    ctx(page="root", net="VCC_3V3", pin="C7:1") → "[root] [VCC_3V3] [-] [C7:1]"
    ctx(pin="C7:1")                           → "[-] [-] [-] [C7:1]"
    ctx()                                     → ""
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"

# ---------- кастомный уровень TRACE ----------

TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self: logging.Logger, message, *args, **kwargs) -> None:
    """Метод log.trace(...) — уровень ниже DEBUG."""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


# привязываем метод к классу Logger
logging.Logger.trace = _trace   # type: ignore[attr-defined]


_configured = False
_default_log_path: Path | None = None


def setup(
    level: int = logging.INFO,
    log_file: Path | str | None = None,
    file_level: int = logging.DEBUG,
    max_bytes: int = 100_000_000,
    backup_count: int = 1,
) -> Path | None:
    """Инициализирует корневой логгер.

    Args:
        level:        минимальный уровень для консоли.
        log_file:     путь к общему файлу. None → "out/debug.log".
        file_level:   минимальный уровень для файла (по умолчанию DEBUG).
                      Поставьте TRACE, если нужны все подробности.
        max_bytes:    максимальный размер файла до ротации.
        backup_count: сколько старых файлов хранить.

    Returns:
        Путь к открытому логу или None.
    """
    global _configured, _default_log_path
    if _configured:
        return _default_log_path

    root = logging.getLogger("eda")
    root.setLevel(TRACE)         # корень пропускает всё, включая TRACE
    root.propagate = False

    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # консоль
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # общий файл
    if log_file is None:
        log_file = Path("out") / "debug.log"
    log_file = Path(log_file)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_file,
            mode="w",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        fh.setLevel(file_level)      # ← по умолчанию DEBUG, TRACE отсекается
        fh.setFormatter(fmt)
        root.addHandler(fh)
        _default_log_path = log_file
    except OSError as e:
        root.warning("Не удалось открыть лог-файл %s: %s", log_file, e)
        _default_log_path = None

    _configured = True
    return _default_log_path


def add_router_log(
    path: Path | str,
    level: int = logging.DEBUG,      # ← TRACE по умолчанию выключен
    max_bytes: int = 10_000_000,
    backup_count: int = 3,
) -> Path | None:
    """Отдельный файл для eda.router.

    Args:
        path:         путь к файлу (например, "out/router.log").
        level:        минимальный уровень. DEBUG по умолчанию,
                      TRACE — если нужны подробности циклов.
        max_bytes:    максимальный размер файла до ротации.
        backup_count: сколько старых файлов хранить.

    Returns:
        Путь к открытому файлу или None.
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            mode="w",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
        handler.addFilter(logging.Filter("eda.router"))
        logging.getLogger("eda").addHandler(handler)
        return path
    except OSError as e:
        logging.getLogger("eda").warning(
            "Не удалось открыть лог роутера %s: %s", path, e,
        )
        return None


def get_logger(name: str) -> logging.Logger:
    """Возвращает дочерний логгер в иерархии 'eda.<module>'."""
    short = name.rsplit(".", 1)[-1]
    return logging.getLogger(f"eda.{short}")


def log_path() -> Path | None:
    """Путь к текущему общему лог-файлу (или None)."""
    return _default_log_path


# ---------- контекстный префикс для лог-строк ----------

def ctx(
    page: str | None = None,
    net: str | None = None,
    comp: str | None = None,
    pin: str | None = None,
) -> str:
    """Префикс для лог-строки: [page] [net] [comp] [pin].

    Порядок полей фиксирован. Пропущенное поле В СЕРЕДИНЕ выводится
    как [-], чтобы сохранить позицию. Пропущенные ХВОСТОВЫЕ поля
    опускаются целиком.

    Примеры:
        ctx(page="root")
        → "[root]"

        ctx(page="root", net="VCC_3V3")
        → "[root] [VCC_3V3]"

        ctx(page="root", comp="C7")
        → "[root] [-] [C7]"

        ctx(page="root", comp="C7", pin="C7:1")
        → "[root] [-] [C7] [C7:1]"

        ctx(page="root", net="VCC_3V3", pin="C7:1")
        → "[root] [VCC_3V3] [-] [C7:1]"

        ctx(pin="C7:1")
        → "[-] [-] [-] [C7:1]"

        ctx()
        → ""
    """
    fields = [page, net, comp, pin]

    # индекс последнего заданного поля
    last = -1
    for i, v in enumerate(fields):
        if v is not None:
            last = i

    if last < 0:
        return ""

    parts: list[str] = []
    for i in range(last + 1):
        v = fields[i]
        parts.append(f"[{v}]" if v is not None else "[-]")
    return " ".join(parts)