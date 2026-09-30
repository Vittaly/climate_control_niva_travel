#!/usr/bin/env python3
"""
Генерация библиотеки KiCad из JLCPCB/LCSC через вызов CLI JLC2KiCadLib.
"""

import subprocess
import sys
from pathlib import Path


def main():
    # --- Параметры ---
    lcsc_id = "C432213"                 # STM32G071RBT6
    output_dir = Path("./my_kicad_library")
    symbol_lib = "MyMCU"                # имя библиотеки символов
    footprint_lib = "MyFootprints"      # имя библиотеки посадочных мест

    # --- Создание директории ---
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Генерация библиотеки для компонента {lcsc_id}...")
    print(f"Результаты будут сохранены в: {output_dir.resolve()}")

    # --- Формирование команды ---
    # JLC2KiCadLib C432213 -dir ./my_kicad_library -symbol_lib MyMCU -footprint_lib MyFootprints
    cmd = [
        "JLC2KiCadLib",
        lcsc_id,
        "-dir", str(output_dir),
        "-symbol_lib", symbol_lib,
        "-footprint_lib", footprint_lib,
        "-models", "STEP",              # скачать 3D-модель в формате STEP
        "-logging_level", "INFO",
    ]

    print(f"\nВыполняется команда:\n  {' '.join(cmd)}\n")

    # --- Запуск ---
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        print("✅ Генерация успешно завершена!")
        if result.stdout:
            print("\n--- Вывод JLC2KiCadLib ---")
            print(result.stdout)

        # --- Показать созданные файлы ---
        print("\nСозданные файлы:")
        for file in sorted(output_dir.rglob("*")):
            if file.is_file():
                print(f"  - {file.relative_to(output_dir)}")

    except FileNotFoundError:
        print("❌ Команда 'JLC2KiCadLib' не найдена.")
        print("Убедитесь, что пакет установлен: pip install JLC2KiCadLib")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при выполнении JLC2KiCadLib (код {e.returncode}):")
        if e.stderr:
            print(e.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()