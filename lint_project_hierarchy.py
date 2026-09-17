import os
import yaml

def run_netlist_linter(base_dir="."):
    main_yaml_path = os.path.join(base_dir, "main.yaml")
    sheets_dir = os.path.join(base_dir, "sheets")

    print("======================================================================")
    print("🔍 ЗАПУСК АУДИТА ИЕРАРХИИ ПРОЕКТА (Netlist & Hierarchy Linter)")
    print("======================================================================")

    if not os.path.exists(main_yaml_path):
        print(f"❌ [КРИТИЧЕСКАЯ ОШИБКА]: Главный файл {main_yaml_path} не найден!")
        return

    # 1. Читаем главный файл проекта
    with open(main_yaml_path, "r", encoding="utf-8") as f:
        main_data = yaml.load(f, Loader=yaml.SafeLoader)
    root_page = main_data.get("root_page", {})
    root_components = set(root_page.get("components", {}).keys())

    total_warnings = 0
    total_critical_errors = 0
    sheet_ports_db = {} # Карта для проверки сквозной консистентности портов

    # 2. Сканируем дочерние листы в папке sheets/
    if os.path.exists(sheets_dir):
        for file_name in os.listdir(sheets_dir):
            if not file_name.endswith(".yaml"):
                continue

            file_path = os.path.join(sheets_dir, file_name)
            with open(file_path, "r", encoding="utf-8") as f:
                sheet_data = yaml.load(f, Loader=yaml.SafeLoader)

            if not sheet_data or "components" not in sheet_data or "nets" not in sheet_data:
                continue

            page_name = sheet_data.get("page_name", file_name)
            local_components = set(sheet_data["components"].keys())
            declared_ports = {p.get("net_label") for p in sheet_data.get("ports", []) if p.get("net_label")}
            sheet_ports_db[page_name] = declared_ports

            print(f"\n📁 Проверка дочернего модуля: {page_name} ({file_name})")
            print(f"   ├── Компонентов на листе: {len(local_components)}")
            print(f"   └── Объявлено портов связи: {len(declared_ports)}")

            # Проверка 1: Поиск инородных компонентов, вызывающих зависание графического движка
            for net_name, net_info in sheet_data["nets"].items():
                for node in net_info.get("nodes", []):
                    comp_ref = node.get("component")

                    # Компонент в цепи подстраницы обязан быть либо локальной деталью, либо локальным портом
                    if comp_ref not in local_components and comp_ref != f"PORT_{net_name}" and comp_ref != net_name:
                        print(f"   ├── ❌ [ОШИБКА ЗАЦИКЛИВАНИЯ]: Цепь '{net_name}' пытается подключиться к '{comp_ref}'.")
                        print(f"   │    💥 Этого элемента НЕТ на текущей странице! Графический движок зависнет.")
                        total_critical_errors += 1

            # Проверка 2: Консистентность флагов портов
            for net_name, net_info in sheet_data["nets"].items():
                if net_info.get("is_hierarchical_port") is True and net_name not in declared_ports:
                    print(f"   ├── ⚠️ [ПРЕДУПРЕЖДЕНИЕ]: Цепь '{net_name}' помечена как порт, но отсутствует в блоке 'ports:' заголовка.")
                    total_warnings += 1

    # 3. Аудит перекрестных связей в main.yaml (Верхний уровень)
    print("\n🌐 Проверка иерархических связей верхнего уровня (main.yaml)...")
    for net_name, net_info in root_page.get("nets", {}).items():
        for node in net_info.get("nodes", []):
            comp = node.get("component")
            pin = node.get("pin")

            # Если цепь корня подключается к кубику суб-листа (начинается с X_)
            if str(comp).startswith("X_"):
                target_sheet_name = str(comp)[2:] # Отрезаем X_ получаем имя страницы (PWR, UI, CAN...)

                # Проверяем, существует ли такой порт внутри суб-листа
                if target_sheet_name in sheet_ports_db:
                    if pin not in sheet_ports_db[target_sheet_name]:
                        print(f"   ├── ❌ [ОШИБКА ИЕРАРХИИ]: В main.yaml цепь '{net_name}' подключается к кубику {comp} через пин '{pin}'.")
                        print(f"   │    💥 Но внутри файла sheets/ {target_sheet_name}.yaml такого входного порта НЕ существует!")
                        total_critical_errors += 1

    print("\n======================================================================")
    print("📊 ИТОГИ ПРОВЕРКИ ПРОЕКТА:")
    print("======================================================================")
    if total_critical_errors == 0 and total_warnings == 0:
        print("✅ [УСПЕХ]: Проект v3.0 идеален! Ошибок зацикливания и нарушений инкапсуляции не обнаружено.")
        print("            Можно безопасно запускать генератор generate_kicad_project.py.")
    else:
        print(f"❌ Найдено критических ошибок зацикливания: {total_critical_errors}")
        print(f"⚠️ Найдено предупреждений иерархии: {total_warnings}")
        if total_critical_errors > 0:
            print("\n💡 Действие: Запустите скрипт чистки 'python3 ./clean_sheets_bottom_up.py', чтобы автоматически убрать ошибки.")
    print("======================================================================")

if __name__ == "__main__":
    run_netlist_linter()

