#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_tests.py — запуск Ngspice-сценариев и проверка PASS/FAIL по допускам.

Две фазы:
  Фаза 1 — базовые сценарии (все sheets/*.yaml без root_page:).
  Фаза 2 — сквозные сценарии корня (root_page.scenarios того
           самого sheets/<ROOT_STEM>.yaml). Запускается ТОЛЬКО
           если все базовые прошли.

  Смысл: сквозной сценарий корня — интеграционный. Он собирает
  всё дерево подсхем и гоняет МК через порты. Если какая-то из
  подсхем сломана, тест корня провалится по той же причине, и
  в логе будет трудно отличить «сломана подсхема» от «сломан
  корень». Поэтому сначала фаза 1, и только на зелёной фазе 1
  имеет смысл фаза 2.

  Когда базовая фаза не прошла, каждый cross-сценарий получает
  статус SKIP-CROSS с явной причиной. В общий итог PASS/M они
  не входят: ни как PASS, ни как FAIL.

  Прогон с фильтром (python3 run_tests.py CC_PWR_UP) однофазный:
  пользователь явно запросил адресный тест и сам отвечает за
  контекст. Это удобно для отладки конкретного cross-сценария.

Идентификация сценариев:
  * Базовый — scenario.name в sheets/*.yaml, КРОМЕ корневого
    (у которого есть root_page:).
  * Сквозной — scenario.name в root_page.scenarios корневого
    <ROOT_STEM>.yaml.
  * .cir — spice/<scenario>.cir; имя файла = имя сценария.
  * Если .cir отсутствует, но checks есть → MISSING (не SKIP):
    значит, kicad_to_spice не прогонялся после последней правки YAML.

Почему важен cwd:
  В .cir относительные .INCLUDE (spice/<stem>.sub, spice/lib/...) —
  от корня проекта. ngspice запускается с cwd=PROJ, иначе ничего
  не найдёт и вернёт пустой stdout, а все проверки превратятся
  в SKIP без объяснения причины.

Диагностика провалов:
  Если ngspice завершился с кодом != 0, stderr выводится (первые
  строки), а все проверки этого .cir помечаются ERROR. Это
  отличается от SKIP: SKIP — «ngspice отработал, но нужного узла
  в выводе нет», ERROR — «ngspice не смог даже запуститься».

Фильтр (позиционные аргументы): имена сценариев и/или id проверок.
    python3 run_tests.py                        # всё, двухфазно
    python3 run_tests.py FAN_KEY_STEADY         # один базовый сценарий
    python3 run_tests.py FAN_KEY_PWM_IG         # одна проверка по id
    python3 run_tests.py CC_PWR_UP              # один cross-сценарий
                                                # (однофазно, для отладки)
"""
import glob
import os
import re
import subprocess
import sys
import yaml

PROJ = os.path.dirname(os.path.abspath(__file__))
SHEETS_DIR = os.path.join(PROJ, "sheets")
SPICE_DIR = os.path.join(PROJ, "spice")

# Имя корневого YAML проекта. Используется только в диагностике
# и справке; деление base/cross делается по наличию root_page:,
# а не по имени.
ROOT_STEM = "climate_control_niva_travel"
ROOT_YAML_NAME = ROOT_STEM + ".yaml"

# Сколько строк stderr ngspice показывать при ERROR.
STDERR_TAIL_LINES = 12

SKIP_CROSS_REASON = "базовые не прошли"


# ─────────────────────────────────────────────────────────────────────
# Сбор проверок: base / cross
# ─────────────────────────────────────────────────────────────────────

def iter_sheet_yamls():
    """Все sheets/*.yaml. Деление base/cross — в collect_checks_split."""
    for path in sorted(glob.glob(os.path.join(SHEETS_DIR, "*.yaml"))):
        yield path


def _collect_from_doc(yml_path, data, target, stem):
    """Разобрать документ (уже развёрнутый от root_page:) и доложить
    проверки в target."""
    for sc in (data.get("scenarios") or []):
        name = sc.get("name")
        if not name:
            print(f"WARN: {yml_path}: сценарий без name — пропущен")
            continue
        sc_checks = sc.get("checks") or []
        if not sc_checks:
            continue

        multiple = len(sc_checks) > 1
        for idx, chk in enumerate(sc_checks):
            cid = chk.get("id")
            if cid is None:
                cid = f"{name}#{idx+1}" if multiple else name
            target.append({
                "id":          cid,
                "cir":         name,
                "node":        chk["node"],
                "min":         float(chk["min"]),
                "max":         float(chk["max"]),
                "description": chk.get("description", ""),
                "stem":        stem,
            })


def collect_checks_split():
    """Собрать проверки, разделив на базовые и сквозные.

    Правило деления:
      * документ с root_page: → корневой YAML;
        его scenarios — это cross (сквозные);
      * документ без root_page: → базовый лист;
        его scenarios — это base.

    Разворот обёртки делается здесь же: для корня данные берутся
    из root_page, для листьев — с верхнего уровня.

    Возвращает (base_checks, cross_checks) — списки словарей.
    """
    base, cross = [], []
    for yml_path in iter_sheet_yamls():
        stem = os.path.splitext(os.path.basename(yml_path))[0]
        try:
            data = yaml.safe_load(open(yml_path, encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            print(f"WARN: {yml_path}: не разобран ({e})")
            continue

        if not isinstance(data, dict):
            continue

        is_root = "root_page" in data
        if is_root:
            data = data.get("root_page") or {}

        target = cross if is_root else base
        _collect_from_doc(yml_path, data, target, stem)

    return base, cross


# ─────────────────────────────────────────────────────────────────────
# Запуск ngspice и парсинг
# ─────────────────────────────────────────────────────────────────────

def run_ngspice(cir_path):
    """Запустить ngspice с cwd=PROJ, чтобы относительные .INCLUDE
    (spice/<stem>.sub, spice/lib/*.lib) разрешались от корня проекта.

    Возвращает (stdout, stderr, returncode).
    """
    r = subprocess.run(
        ["ngspice", "-b", cir_path],
        cwd=PROJ,
        capture_output=True,
        text=True,
    )
    return r.stdout, r.stderr, r.returncode


def parse_vals(out):
    """Извлечь `key = value` из stdout ngspice.

    Формат строк ngspice: 'v(motor_a) = 1.415e+01' или 'ifan = 15.2'.
    Ключ сохраняем как есть — проверки в YAML пишут точно такой же
    регистр ('v(motor_a)', 'vdmax', 'isurge').

    Дополнительно подчищаем типографский мусор: ngspice иногда
    печатает числа с суффиксами (mA, V) — их отбрасываем.
    """
    vals = {}
    for m in re.finditer(
        r'^\s*([a-zA-Z_][\w()]*)\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)',
        out, re.M):
        try:
            vals[m.group(1).lower()] = float(m.group(2))
        except ValueError:
            continue
    return vals


# ─────────────────────────────────────────────────────────────────────
# Общий проход одной фазы
# ─────────────────────────────────────────────────────────────────────

def group_by_cir(checks):
    """Сгруппировать проверки по имени .cir.

    ngspice запускается один раз на файл, поэтому группировка
    нужна до запуска: один .cir → один запуск ngspice → N проверок.
    """
    by_cir = {}
    for chk in checks:
        by_cir.setdefault(chk["cir"], []).append(chk)
    return by_cir


def filter_by_names(by_cir, only):
    """Оставить только те .cir, чьё имя или id проверки попали в only."""
    out = {}
    for cir_name, chks in by_cir.items():
        ids = {c["id"] for c in chks}
        if cir_name in only or (ids & only):
            out[cir_name] = chks
    return out


def emit_ngspice_error(cir_name, rc, stderr):
    """Показать хвост stderr от ngspice при ненулевом rc."""
    print("%-24s ERROR ngspice rc=%d" % (cir_name, rc))
    lines = (stderr or "").splitlines()
    if not lines:
        print("    (stderr пуст — проверьте spice/%s.cir вручную)" % cir_name)
        return
    for line in lines[-STDERR_TAIL_LINES:]:
        print("    " + line)


def run_phase(by_cir):
    """Прогнать все .cir из by_cir. Вернуть (results, ok).

    results — список bool: PASS (True) / всё остальное (False).
              Используется для итоговой сводки.
    ok      — True, если в фазе нет ни одного FAIL/ERROR/MISSING/SKIP.
              По этому флагу main() решает, запускать ли следующую фазу.
    """
    results = []
    for cir_name in sorted(by_cir):
        cir_path = os.path.join(SPICE_DIR, cir_name + ".cir")
        if not os.path.exists(cir_path):
            # Не пропускаем молча: значит, kicad_to_spice не запускался
            # после последней правки YAML (или сценарий упал на генерации).
            for chk in by_cir[cir_name]:
                print("%-24s MISSING (%s не сгенерирован)"
                      % (chk["id"], os.path.relpath(cir_path, PROJ)))
                results.append(False)
            continue

        out, err, rc = run_ngspice(cir_path)

        if rc != 0:
            # Один ERROR на весь .cir: диагностика важнее, чем N SKIP'ов
            # на каждую проверку внутри.
            emit_ngspice_error(cir_name, rc, err)
            results.extend([False] * len(by_cir[cir_name]))
            continue

        vals = parse_vals(out)

        for chk in by_cir[cir_name]:
            node = chk["node"]
            key = node.lower()
            lo, hi = chk["min"], chk["max"]
            if key not in vals:
                # ngspice запустился, но нужного узла в stdout нет:
                # забыли `print <node>` в control:, либо это measure,
                # который не сработал. Всё равно FAIL — иначе можно
                # годами «проходить» тесты, ничего не измеряя.
                print("%-24s SKIP (%s не измерен в %s.cir)"
                      % (chk["id"], node, cir_name))
                results.append(False)
                continue
            v = vals[key]
            ok = lo <= v <= hi
            results.append(ok)
            print("%-24s %s  %s=%+.4g  [%g..%g] %s" % (
                chk["id"],
                "PASS" if ok else "FAIL",
                node, v, lo, hi,
                chk["description"]))

    return results, all(results) if results else True


def emit_skip_cross(by_cir_cross):
    """Плановый пропуск cross-фазы.

    Печатает по одной строке на каждую проверку. Строка содержит
    имя сценария (или id) и пометку SKIP-CROSS с причиной —
    этого достаточно, чтобы run_e2e.py на шаге 4b не считал
    такую проверку «потерянной».
    """
    for cir_name in sorted(by_cir_cross):
        for chk in by_cir_cross[cir_name]:
            print("%-24s SKIP-CROSS (%s)" % (chk["id"], SKIP_CROSS_REASON))


def finalize(results):
    """Итоговая сводка и код возврата.

    В results попадают только те проверки, которые реально
    прогонялись. Планово пропущенные cross-проверки сюда не
    входят — они не PASS и не FAIL, их просто не было.
    """
    if not results:
        print("\nНет выполненных проверок.")
        return 1
    passed = sum(1 for r in results if r)
    print("\nИтого PASS: %d/%d" % (passed, len(results)))
    return 0 if passed == len(results) else 1


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def main():
    only = set(sys.argv[1:])

    base_checks, cross_checks = collect_checks_split()
    if not base_checks and not cross_checks:
        print("Не найдено ни одной проверки в sheets/*.yaml.")
        return 1

    # ─── Адресный прогон по фильтру ───
    # Пользователь явно запросил имена/id — фазы не применяем.
    # Так можно гонять один cross-сценарий без ожидания фазы 1.
    if only:
        all_checks = base_checks + cross_checks
        by_cir = group_by_cir(all_checks)
        by_cir = filter_by_names(by_cir, only)
        if not by_cir:
            print("Ни один сценарий не попал под фильтр %s."
                  % sorted(only))
            return 1
        results, _ = run_phase(by_cir)
        return finalize(results)

    # ─── Полный прогон: две фазы ───
    by_cir_base = group_by_cir(base_checks)
    by_cir_cross = group_by_cir(cross_checks)

    print("== Фаза 1. Базовые сценарии (подсхемы) ==")
    results_base, base_ok = run_phase(by_cir_base)

    print()
    print("== Фаза 2. Сквозные сценарии корня ==")
    if not by_cir_cross:
        print("  (нет сквозных сценариев)")
        results_cross = []
    elif not base_ok:
        print("  Пропущены: %s." % SKIP_CROSS_REASON)
        emit_skip_cross(by_cir_cross)
        results_cross = []
    else:
        results_cross, _ = run_phase(by_cir_cross)

    return finalize(results_base + results_cross)


if __name__ == "__main__":
    sys.exit(main())