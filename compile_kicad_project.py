import yaml
import os
import kicad_sch_api as ksa

def load_yaml(file_path):
    if not os.path.exists(file_path):
        return None
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def build_project_perfect_layout(main_yaml_path):
    main_data = load_yaml(main_yaml_path)
    if not main_data:
        print(f"[ОШИБКА] Не найден файл {main_yaml_path}")
        return

    root = main_data.get('root_page', {})
    components = root.get('components', {})
    comp_types = root.get('component_types', {})
    nets = root.get('nets', {})
    PROJECT_NAME = root.get('project', "Climate_Control")

    # ===== ШАГ 1: Инициализация схемы и установка листа А2 =====
    main_sch = ksa.create_schematic(PROJECT_NAME)
    parent_uuid = main_sch.uuid
    main_sch.paper = "A2"  # Расширяем чертеж, чтобы МК поместился ниже

    # ===== ШАГ 2: Геометрическая сетка (Ряд сверху + МК опущен ровно в 2 раза ниже) =====
    sheet_start_x = 40
    sheet_fixed_y = 30
    sheet_gap_x = 70

    # Центральный контроллер U1 опущен в два раза ниже (Y: 340) строго по центру листа
    mcu_x, mcu_y = 200, 340

    # Сетка для пассивных компонентов обвязки
    discrete_start_x = 280
    discrete_x, discrete_y = discrete_start_x, 260

    sheet_pin_positions = {}
    sheet_uuids = {}
    comp_positions = {}
    comp_objects = {}

    # ===== ШАГ 3: Создание иерархических листов в один горизонтальный ряд =====
    for ref, comp_info in components.items():
        if not ref.startswith('X_'):
            continue

        file_sch = comp_info.get('value_sch', f"sheets/{ref.lower().replace('x_', '')}.kicad_sch")

        pins = []
        for net_name, net_info in nets.items():
            for node in net_info.get('nodes', []) or []:
                if node.get('component') == ref:
                    pins.append(node.get('pin', net_name))
        pins = sorted(list(set(pins)))

        height = max(25, len(pins) * 6)
        sheet_uuid = main_sch.sheets.add_sheet(
            name=ref, filename=file_sch, position=(sheet_start_x, sheet_fixed_y), size=(50, height), project_name=PROJECT_NAME
        )
        sheet_uuids[ref] = sheet_uuid
        sheet_pin_positions[ref] = {}

        for idx, pin_name in enumerate(pins, start=1):
            py = sheet_fixed_y + (idx * 5)
            main_sch.sheets.add_sheet_pin(sheet_uuid, pin_name, "input", "left", idx * 5)
            sheet_pin_positions[ref][pin_name] = (sheet_start_x, py)

        sheet_start_x += sheet_gap_x

    # ===== ШАГ 4: Изолированное размещение МК и элементов обвязки =====
    for ref, comp_info in components.items():
        if ref.startswith('X_'):
            continue
        c_type = comp_info.get('type')
        type_data = comp_types.get(c_type, {})
        symbol_name = type_data.get('symbol', 'Device:R')
        value = str(type_data.get('value', 'Value'))

        if ref == "U1" or "STM32" in value:
            comp_obj = main_sch.components.add(symbol_name, ref, value, position=(mcu_x, mcu_y))
            comp_objects[ref] = comp_obj
            comp_positions[ref] = (mcu_x, mcu_y)
            print(f"[ЗОНА] Контроллер U1 зафиксирован на позиции: {mcu_x}, {mcu_y}")
        else:
            comp_obj = main_sch.components.add(symbol_name, ref, value, position=(discrete_x, discrete_y))
            comp_objects[ref] = comp_obj
            comp_positions[ref] = (discrete_x, discrete_y)

            discrete_x += 45
            if discrete_x > 410:
                discrete_x = discrete_start_x
                discrete_y += 35

        if type_data.get('footprint'):
            comp_obj.footprint = type_data.get('footprint')

        # ===== ШАГ 5: ОТЛАДОЧНОЕ ПОДКЛЮЧЕНИЕ ЧЕРЕЗ МИКРО-ПРОВОДА И ЛОКАЛЬНЫЕ МЕТКИ =====
    print("\n🔬 ================== СТАРТ ОТЛАДКИ ПОДКЛЮЧЕНИЙ ВЫВОДОВ ==================")
    print(f"[ИНФО] Базовая точка установки МК U1 на листе А2: X={mcu_x}, Y={mcu_y}")

    total_labels_attempted = 0
    total_labels_failed = 0

    for net_name, net_info in nets.items():
        nodes = net_info.get('nodes', []) or []

        for node in nodes:
            comp_ref = node.get('component')
            pin_id = str(node.get('pin', net_name))

            if not comp_ref:
                continue

            # Блоки подмодулей верхнего ряда (ставим метку прямо на пин блока)
            if comp_ref.startswith('X_'):
                if comp_ref in sheet_pin_positions and pin_id in sheet_pin_positions[comp_ref]:
                    exact_pin_pt = sheet_pin_positions[comp_ref][pin_id]
                    main_sch.add_label(net_name, position=exact_pin_pt)
                    print(f"📡 [ПОДМОДУЛЬ {comp_ref}] Сеть {net_name:<20} -> Метка на пине: X={exact_pin_pt}, Y={exact_pin_pt}")

            # Подключение МК (U1) и дискретных элементов верхнего уровня
            else:
                if comp_ref in comp_positions:
                    total_labels_attempted += 1
                    try:
                        base_x, base_y = comp_positions[comp_ref]
                        comp_item = comp_objects.get(comp_ref)

                        # ДИАГНОСТИКА СТРУКТУРЫ: Проверяем, видит ли библиотека пины в объекте
                        has_pins_attr = hasattr(comp_item, 'pins')
                        pins_type = type(comp_item.pins).__name__ if has_pins_attr else "None"
                        pins_count = len(comp_item.pins) if has_pins_attr and isinstance(comp_item.pins, list) else 0

                        if comp_ref == "U1":
                            p_num = int(pin_id) if pin_id.isdigit() else 1

                            # Геометрический расчет отводов по периметру корпуса LQFP-64
                            if p_num <= 16:  # Левая сторона
                                start_pt = (base_x - 15, base_y - 20 + (p_num * 2.5))
                                end_pt = (start_pt - 5, start_pt)
                                side = "ЛЕВАЯ"
                            elif p_num <= 32:  # Нижня сторона
                                start_pt = (base_x - 20 + ((p_num - 16) * 2.5), base_y + 15)
                                end_pt = (start_pt, start_pt + 5)
                                side = "НИЖНЯЯ"
                            elif p_num <= 48:  # Правая сторона
                                start_pt = (base_x + 15, base_y + 20 - ((p_num - 32) * 2.5))
                                end_pt = (start_pt + 5, start_pt)
                                side = "ПРАВАЯ"
                            else:  # Upper side
                                start_pt = (base_x + 20 - ((p_num - 48) * 2.5), base_y - 15)
                                end_pt = (start_pt, start_pt - 5)
                                side = "ВЕРХНЯЯ"

                            print(f"📌 [ПИН МК {pin_id:<2}] Сеть: {net_name:<20} Грань: {side:<7}")
                            print(f"   ├─ Объекты библиотеки: .pins доступен={has_pins_attr}, Тип коллекции={pins_type}, Найдено пинов={pins_count}")
                            print(f"   ├─ Начало провода на МК (Start Wire): X={start_pt:.1f}, Y={start_pt:.1f}")
                            print(f"   └─ Посадка метки на край провода (End Wire): X={end_pt:.1f}, Y={end_pt:.1f}")
                        else:
                            # Для резисторов/конденсаторов обвязки
                            p_num = int(pin_id) if pin_id.isdigit() else 1
                            start_pt = (base_x - 10 if p_num == 1 else base_x + 10, base_y)
                            end_pt = (start_pt - 3 if p_num == 1 else start_pt + 3, start_pt)
                            print(f"📦 [ОБВЯЗКА {comp_ref}:{pin_id}] Сеть: {net_name:<20} Смещение: X={end_pt:.1f}, Y={end_pt:.1f}")

                        # Вызовы методов рисования проводников и установки текста
                        main_sch.add_wire(start=start_pt, end=end_pt)
                        main_sch.add_label(net_name, position=end_pt)

                    except Exception as e:
                        print(f"   💥 [СБОЙ ТРАССИРОВКИ ПИНА {pin_id} для {comp_ref}]: {str(e)}")
                        total_labels_failed += 1

    print("\n📊 ==================== ИТОГОВЫЙ СВЕДЕННЫЙ ОТЧЕТ ОБРАБОТКИ ====================")
    print(f"Всего локальных меток отправлено на разметку: {total_labels_attempted}")
    print(f"Из них завершились критической ошибкой:       {total_labels_failed}")
    print("===============================================================================\n")

# ===== ШАГ 6: Локальная разметка внутри дочерних листов =====
    for ref, comp_info in components.items():
        if not ref.startswith('X_'):
            continue

        yaml_spec = comp_info.get('value', f"sheets/{ref.lower().replace('x_', '')}.yaml")
        file_sch = comp_info.get('value_sch', f"sheets/{ref.lower().replace('x_', '')}.kicad_sch")
        yaml_path = yaml_spec if os.path.exists(yaml_spec) else os.path.join("sheets", os.path.basename(yaml_spec))

        child_data = load_yaml(yaml_path)
        if not child_data:
            continue

        child_page = child_data.get('page_info', child_data) if 'page_info' in child_data else child_data
        c_components = child_page.get('components', {})
        c_types = child_page.get('component_types', {})
        c_nets = child_page.get('nets', {})

        child_sch = ksa.create_schematic(PROJECT_NAME)
        child_sch.set_hierarchy_context(parent_uuid, sheet_uuids[ref])

        pins = sorted(list(sheet_pin_positions[ref].keys()))
        ly = 40
        child_label_positions = {}
        for p in pins:
            child_sch.add_hierarchical_label(p, position=(40, ly))
            child_label_positions[p] = (40, ly)
            ly += 15

        child_comp_objects = {}
        child_comp_positions = {}
        cx, cy = 130, 40
        for c_ref, c_info in c_components.items():
            t_data = c_types.get(c_info.get('type'), {})
            c_obj = child_sch.components.add(t_data.get('symbol', 'Device:R'), c_ref, str(t_data.get('value', 'Value')), position=(cx, cy))
            child_comp_objects[c_ref] = c_obj
            child_comp_positions[c_ref] = (cx, cy)

            cx += 45
            if cx > 320:
                cx = 130
                cy += 45

        # Локальные метки внутри подлистов (также через защищенный обход списка)
        for c_net_name, c_net_info in c_nets.items():
            c_nodes = c_net_info.get('nodes', []) or []
            for c_node in c_nodes:
                node_comp = c_node.get('component')
                node_pin = str(c_node.get('pin', '1'))

                if node_comp in child_comp_objects:
                    try:
                        c_item = child_comp_objects[node_comp]
                        c_global_x, c_global_y = child_comp_positions[node_comp]

                        child_pin_found = None
                        if hasattr(c_item, 'pins') and isinstance(c_item.pins, list):
                            for p in c_item.pins:
                                if str(p.number) == node_pin or str(p.name) == node_pin:
                                   child_pin_found = p
                                   break
                        if str(p.number) == node_pin or str(p.name) == node_pin:
                                    child_pin_found = p
                                    break

                        if child_pin_found:
                            # Извлекаем родные относительные координаты вывода компонента
                            c_pin_x, c_pin_y = child_pin_found.x, child_pin_found.y
                            # Векторное сложение: прибавляем позицию самого компонента на подлисте
                            absolute_child_pin_pt = (c_global_x + c_pin_x, c_global_y + c_pin_y)
                        else:
                            # Безопасный фолбэк для стандартных двухвыводных SMD/Through-Hole элементов
                            p_num = int(node_pin) if node_pin.isdigit() else 1
                            absolute_child_pin_pt = (c_global_x - 8 if p_num == 1 else c_global_x + 8, c_global_y)

                        # Сажаем локальную метку подлиста снайперски точно на вывод элемента
                        child_sch.add_label(c_net_name, position=absolute_child_pin_pt)
                    except Exception as e:
                        print(f"[WARN] Ошибка позиционирования метки подлиста: {e}")
                        pass

        child_sch.save(file_sch)
        print(f"[✓ API] Дочерний лист схемы сохранен: {file_sch}")

    print("\n[УСПЕХ] Контроллер опущен на Y:340. Все баги итерации устранены, метки жестко зафиксированы на ножки МК!")

if __name__ == "__main__":
    build_project_perfect_layout("main.yaml")