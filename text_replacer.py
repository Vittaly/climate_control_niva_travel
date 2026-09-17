#!/usr/bin/env python3
"""
Патч yaml_to_skidl.py:
  1. Передаём top_name='climate_control_niva_travel' в generate_schematic.
  2. Убираем постпереименование — SKiDL сразу создаёт файлы с нужным именем.
"""
import shutil
import sys
import yaml


TARGET = 'yaml_to_skidl.py'


def load_project_sch_name():
    try:
        with open('main.yaml', 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return 'climate_control_niva_travel'
    name = data.get('root_page', {}).get('file', 'root.kicad_sch')
    # Отрезаем .kicad_sch — top_name в SKiDL без расширения
    if name.endswith('.kicad_sch'):
        name = name[:-len('.kicad_sch')]
    return name


def main():
    top_name = load_project_sch_name()
    print(f'[INFO] top_name для SKiDL: {top_name}')

    try:
        with open(TARGET, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        print(f'[ОШИБКА] {TARGET} не найден')
        sys.exit(1)

    changed = False

    # --- 1. Добавляем top_name в generate_schematic ---
    old_call = (
        "    lines.append('    generate_schematic(')\n"
        "    lines.append('        filepath=str(SCHEMATIC_DIR),')\n"
    )
    new_call = (
        "    lines.append('    generate_schematic(')\n"
        "    lines.append('        filepath=str(SCHEMATIC_DIR),')\n"
        f"    lines.append(\"        top_name={top_name!r},\")\n"
    )
    if 'top_name=' in text:
        print('[SKIP] top_name уже добавлен')
    elif old_call in text:
        text = text.replace(old_call, new_call, 1)
        print(f'[OK] top_name={top_name!r} добавлен в generate_schematic')
        changed = True
    else:
        print('[ОШИБКА] Не нашёл вызов generate_schematic в yaml_to_skidl.py')
        sys.exit(1)

    # --- 2. Убираем постпереименование ---
    # Ищем блок от "    # Переименовать" до "    lines.append(f'-> Все .kicad_sch"
    marker_start = "    lines.append('    # Переименовать"
    marker_end = "    lines.append(\"    print(f'-> Все .kicad_sch в: {SCHEMATIC_DIR}', flush=True)\")"

    idx_start = text.find(marker_start)
    idx_end = text.find(marker_end)

    if idx_start < 0:
        print('[SKIP] Блок переименования не найден (уже убран)')
    elif idx_end < 0:
        print('[ОШИБКА] Не нашёл конец блока переименования')
        sys.exit(1)
    else:
        # Оставляем только финальный print «Все .kicad_sch в: ...»
        text = text[:idx_start] + marker_end + '\n' + text[idx_end + len(marker_end):]
        print('[OK] Блок постпереименования убран')
        changed = True

    if not changed:
        print('[SKIP] Ничего не изменилось')
        return

    # --- Резервная копия ---
    shutil.copy2(TARGET, TARGET + '.bak_topname')
    print(f'[OK] Резервная копия: {TARGET}.bak_topname')

    with open(TARGET, 'w', encoding='utf-8') as f:
        f.write(text)

    # --- Проверка синтаксиса ---
    import ast
    try:
        ast.parse(text)
        print('[OK] Синтаксис валиден')
    except SyntaxError as e:
        print(f'[ОШИБКА] Синтаксис сломан: {e}')
        print(f'        Строка {e.lineno}: {e.text}')
        sys.exit(1)

    print('')
    print('[OK] Патч применён')
    print(f'     SKiDL создаст файлы:')
    print(f'       {top_name}.kicad_sch (обёртка)')
    print(f'       {top_name}_ROOT.kicad_sch')
    print(f'       {top_name}_ROOT_SHEET_*.kicad_sch')
    print(f'     Все файлы — в корне проекта (рядом со скриптом).')
    print('')
    print('Дальше:')
    print('  rm -f *.kicad_sch')
    print('  python3 yaml_to_skidl.py')
    print('  python3 -u circuit_generated.py 2>&1 | tee build.log')
    print('  ls -la *.kicad_sch')


if __name__ == '__main__':
    main()