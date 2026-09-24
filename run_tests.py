#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_tests.py — запуск Ngspice-сценариев и проверка PASS/FAIL по допускам.

Все проверки берутся из <stem>.yaml: scenarios[].checks[]
(node, min, max, id, description). Один .cir даёт несколько проверок —
ngspice запускается один раз на файл.

Идентификация сценариев:
  * Сценарий — scenario.name в одном из sheets/*.yaml (кроме main.yaml).
  * .cir — spice/<scenario>.cir; имя файла = имя сценария.
  * Никакого собственного резолвера YAML: пробегаем все sheets/*.yaml.
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
    python3 run_tests.py                        # все
    python3 run_tests.py FAN_KEY_STEADY         # один сценарий
    python3 run_tests.py FAN_KEY_PWM_IG         # одна проверка по id
    python3 run_tests.py FAN_KEY_STEADY FAN_KEY_PWM_VD
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

# Сколько строк stderr ngspice показывать при ERROR — чтобы было видно
# причину («unknown subckt X», «file not found», «timestep too small»),
# но не залить экран.
STDERR_TAIL_LINES = 12


# ─────────────────────────────────────────────────────────────────────
# Сбор проверок из всех sheet YAML
# ─────────────────────────────────────────────────────────────────────

def iter_sheet_yamls():
    """Все sheets/*.yaml, кроме main.yaml."""
    for path in sorted(glob.glob(os.path.join(SHEETS_DIR, "*.yaml"))):
        if os.path.basename(path) == "main.yaml":
            continue
        yield path


def collect_checks():
    """Собрать все проверки из всех листов.

    Возвращает список словарей:
      { id, cir, node, min, max, description, stem }

    id по умолчанию:
      * один check в сценарии → имя сценария;
      * несколько → '<scenario>#<n>' (1-based), если id не задан явно.
    """
    out = []
    for yml_path in iter_sheet_yamls():
        stem = os.path.splitext(os.path.basename(yml_path))[0]
        try:
            data = yaml.safe_load(open(yml_path, encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            print(f"WARN: {yml_path}: не разобран ({e})")
            continue

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
                out.append({
                    "id":          cid,
                    "cir":         name,
                    "node":        chk["node"],
                    "min":         float(chk["min"]),
                    "max":         float(chk["max"]),
                    "description": chk.get("description", ""),
                    "stem":        stem,
                })
    return out


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
            vals[m.group(1)] = float(m.group(2))
        except ValueError:
            continue
    return vals


# ─────────────────────────────────────────────────────────────────────
# Основной проход
# ─────────────────────────────────────────────────────────────────────

def emit_ngspice_error(cir_name, rc, stderr):
    """Показать первые строки stderr от ngspice при ненулевом rc."""
    print("%-24s ERROR ngspice rc=%d" % (cir_name, rc))
    lines = (stderr or "").splitlines()
    if not lines:
        print("    (stderr пуст — проверьте spice/%s.cir вручную)" % cir_name)
        return
    # ngspice любит печатать «Warning: ...» пачками; берём хвост,
    # там обычно собственно причина падения
    for line in lines[-STDERR_TAIL_LINES:]:
        print("    " + line)


def main():
    only = set(sys.argv[1:])  # фильтр по имени сценария или id проверки

    checks = collect_checks()
    if not checks:
        print("Не найдено ни одной проверки в sheets/*.yaml.")
        return 1

    # Группируем проверки по .cir: ngspice запускается один раз на файл
    by_cir = {}
    for chk in checks:
        by_cir.setdefault(chk["cir"], []).append(chk)

    results = []
    for cir_name in sorted(by_cir):
        ids = {c["id"] for c in by_cir[cir_name]}
        if only and cir_name not in only and not (ids & only):
            continue

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
            lo, hi = chk["min"], chk["max"]
            if node not in vals:
                # ngspice запустился, но нужного узла в stdout нет:
                # забыли `print <node>` в control:, либо это measure,
                # который не сработал. Всё равно FAIL — иначе можно
                # годами «проходить» тесты, ничего не измеряя.
                print("%-24s SKIP (%s не измерен в %s.cir)"
                      % (chk["id"], node, cir_name))
                results.append(False)
                continue
            v = vals[node]
            ok = lo <= v <= hi
            results.append(ok)
            print("%-24s %s  %s=%+.4g  [%g..%g] %s" % (
                chk["id"],
                "PASS" if ok else "FAIL",
                node, v, lo, hi,
                chk["description"]))

    if not results:
        print("Ни одна проверка не попала под фильтр %s." % sorted(only))
        return 1

    passed = sum(1 for r in results if r)
    print("\nИтого PASS: %d/%d" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())