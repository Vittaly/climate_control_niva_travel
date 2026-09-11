from kicad_sch_api import Schematic, HierarchicalSheet, SheetPin, HierarchicalLabel, Component, Wire

# -------------------------------------------------------------
# ШАГ 1: Создаем дочернюю схему (sub_page.kicad_sch)
# -------------------------------------------------------------
sub_sch = Schematic()

# Добавляем иерархические метки, которые станут пинами на родительской схеме
label_in = HierarchicalLabel(text="INPUT", x=50, y=50, shape="input")
label_out = HierarchicalLabel(text="OUTPUT", x=150, y=50, shape="output")
sub_sch.add_label(label_in)
sub_sch.add_label(label_out)

# Для примера добавим резистор внутри дочерней страницы
resistor = Component(lib_id="Device:R", reference="R1", value="1k", x=100, y=50)
sub_sch.add_component(resistor)

# Соединяем метки с компонентом (координаты условные)
sub_sch.add_wire(Wire(start=(50, 50), end=(90, 50)))
sub_sch.add_wire(Wire(start=(110, 50), end=(150, 50)))

# Сохраняем дочерний лист
sub_sch.save("sub_page.kicad_sch")


# -------------------------------------------------------------
# ШАГ 2: Создаем родительскую схему (root.kicad_sch)
# -------------------------------------------------------------
root_sch = Schematic()

# Создаем объект иерархического листа (блока)
# Задаем координаты левого верхнего угла, ширину и высоту блока на схеме
sheet_box = HierarchicalSheet(
    name="Power_Module",      # Имя блока на схеме
    file_name="sub_page.kicad_sch", # Ссылка на сгенерированный ранее файл
    x=100, y=100,
    width=60, height=40
)

# Добавляем пины на сам блок (они должны строго совпадать по имени с HierarchicalLabel)
pin_in = SheetPin(name="INPUT", x=100, y=110, side="left")   # Пин слева блока
pin_out = SheetPin(name="OUTPUT", x=160, y=110, side="right") # Пин справа блока

sheet_box.add_pin(pin_in)
sheet_box.add_pin(pin_out)

# Добавляем блок на родительскую схему
root_sch.add_sheet(sheet_box)

# Теперь на родительской схеме можно подключать провода к пинам sheet_box
# Например, подведем провод к INPUT:
root_sch.add_wire(Wire(start=(80, 110), end=(100, 110)))

# Сохраняем корневую схему
root_sch.save("root.kicad_sch")
