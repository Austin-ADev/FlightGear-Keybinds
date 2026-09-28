"""Assignment editor: catalog selection, guided form, or raw XML."""

from __future__ import annotations

from typing import Optional

from lxml import etree
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.bindings import binding_from_xml, summarize
from ..core.catalog import Action, Catalog
from ..core.search import fold
from . import theme

COMMANDS: list[tuple[str, str]] = [
    ("nasal", "Script Nasal"),
    ("property-toggle", "Toggle a property (true/false)"),
    ("property-assign", "Assign a value to a property"),
    ("property-adjust", "Increment / decrement a property"),
    ("property-cycle", "Browse a list of values"),
    ("property-scale", "Copy the axis into a property"),
    ("dialog-show", "Open a window"),
    ("pause", "Pause"),
    ("screen-capture", "Screenshot"),
    ("toggle-fullscreen", "Full Screen"),
    ("replay", "Replay"),
    ("reset", "Reset"),
    ("null", "No action (disable)"),
]

FIELDS_BY_CMD: dict[str, list[str]] = {
    "nasal": ["script"],
    "property-toggle": ["property"],
    "property-assign": ["property", "value", "property2"],
    "property-adjust": ["property", "step", "min", "max", "wrap"],
    "property-cycle": ["property", "values", "wrap"],
    "property-scale": ["property", "offset", "factor", "power"],
    "dialog-show": ["dialog-name"],
}

FIELD_LABELS = {
    "property": "Property",
    "property2": "Copy from property",
    "value": "Value",
    "step": "Step",
    "min": "Minimum",
    "max": "Maximum",
    "wrap": "Wrap (min ↔ max)",
    "values": "Values (separated by ;)",
    "offset": "Offset",
    "factor": "Factor",
    "power": "Power (integer)",
    "dialog-name": "Window Name",
    "script": "Script",
}

KNOWN_DIALOGS = ["autopilot", "radios", "map", "exit", "replay", "chat-menu", "flight-recorder-load",
                 "flight-recorder-save", "location-in-air", "weather", "time", "view", "sound", "rendering",
                 "fuel-and-payload", "checklist", "gps", "instruments", "failures", "logging"]

_MANAGED = {"command", "property", "value", "step", "min", "max", "wrap", "offset", "factor", "power",
            "squared", "dialog-name", "script"}


def _elem(xml: str) -> etree._Element:
    el = etree.fromstring(xml.strip().encode("utf-8"), etree.XMLParser(strip_cdata=False, remove_blank_text=True))
    if el.tag != "binding":
        raise ValueError("L'élément doit être <binding>.")
    return el


def _xml(el: etree._Element) -> str:
    el2 = etree.fromstring(etree.tostring(el), etree.XMLParser(strip_cdata=False, remove_blank_text=True))
    etree.indent(el2, space="  ")
    return etree.tostring(el2, encoding="unicode")


# ---------------------------------------------------------------------------
# Binding form
# ---------------------------------------------------------------------------

class BindingForm(QWidget):
    changed = Signal()

    def __init__(self, properties: list[str], parent=None):
        super().__init__(parent)
        self.el: Optional[etree._Element] = None
        self._loading = False
        lay = QFormLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setLabelAlignment(Qt.AlignRight)
        self.form = lay
        self.cmd = QComboBox()
        self.cmd.setEditable(True)
        for c, lbl in COMMANDS:
            self.cmd.addItem(f"{lbl}  —  {c}", c)
        self.cmd.currentIndexChanged.connect(self._cmd_changed)
        self.cmd.lineEdit().editingFinished.connect(self._cmd_edited)
        lay.addRow("Commande", self.cmd)
        comp = QCompleter(sorted(set(properties)))
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.widgets: dict[str, QWidget] = {}
        for key in ["property", "value", "property2", "step", "min", "max", "values", "offset", "factor", "power",
                    "dialog-name"]:
            if key == "dialog-name":
                w = QComboBox()
                w.setEditable(True)
                w.addItems(KNOWN_DIALOGS)
                w.currentTextChanged.connect(self._field_changed)
            else:
                w = QLineEdit()
                if key.startswith("property"):
                    w.setCompleter(QCompleter(comp.model()))
                    w.completer().setFilterMode(Qt.MatchContains)
                    w.completer().setCaseSensitivity(Qt.CaseInsensitive)
                    w.setPlaceholderText("/controls/…")
                w.textEdited.connect(self._field_changed)
            self.widgets[key] = w
            lay.addRow(FIELD_LABELS[key], w)
        self.wrap = QCheckBox()
        self.wrap.toggled.connect(self._field_changed)
        self.widgets["wrap"] = self.wrap
        lay.addRow(FIELD_LABELS["wrap"], self.wrap)
        self.script = QPlainTextEdit()
        self.script.setFont(theme.mono_font(10))
        self.script.setPlaceholderText("controls.gearDown(1)")
        self.script.setMinimumHeight(110)
        self.script.textChanged.connect(self._field_changed)
        self.widgets["script"] = self.script
        lay.addRow(FIELD_LABELS["script"], self.script)
        self.extra = QLabel()
        self.extra.setProperty("muted", True)
        self.extra.setWordWrap(True)
        lay.addRow("", self.extra)
        self.setEnabled(False)

    def set_element(self, el: Optional[etree._Element]) -> None:
        self._loading = True
        self.el = el
        self.setEnabled(el is not None)
        if el is not None:
            cmd = (el.findtext("command") or "").strip()
            idx = self.cmd.findData(cmd)
            if idx >= 0:
                self.cmd.setCurrentIndex(idx)
            else:
                self.cmd.setEditText(cmd)
            props = el.findall("property")
            self.widgets["property"].setText((props[0].text or "").strip() if props else "")
            self.widgets["property2"].setText((props[1].text or "").strip() if len(props) > 1 else "")
            for key in ("value", "step", "min", "max", "offset", "factor", "power"):
                self.widgets[key].setText((el.findtext(key) or "").strip())
            self.widgets["values"].setText("; ".join((v.text or "").strip() for v in el.findall("value")))
            self.widgets["dialog-name"].setCurrentText((el.findtext("dialog-name") or "").strip())
            self.wrap.setChecked((el.findtext("wrap") or "").strip().lower() in ("1", "true"))
            self.script.setPlainText((el.findtext("script") or "").strip("\n"))
            extras = sorted({c.tag for c in el if isinstance(c.tag, str) and c.tag not in _MANAGED})
            self.extra.setText(("Éléments conservés tels quels : " + ", ".join(f"<{t}>" for t in extras))
                               if extras else "")
        self._update_visibility()
        self._loading = False

    def command(self) -> str:
        d = self.cmd.currentData()
        txt = self.cmd.currentText()
        if d and txt.endswith(str(d)):
            return str(d)
        return txt.split("—")[-1].strip()

    def _update_visibility(self) -> None:
        cmd = self.command()
        fields = FIELDS_BY_CMD.get(cmd, [])
        for key, w in self.widgets.items():
            show = key in fields
            if key == "value" and cmd == "property-cycle":
                show = False
            self.form.setRowVisible(w, show)

    def _cmd_changed(self) -> None:
        self._update_visibility()
        self._field_changed()

    def _cmd_edited(self) -> None:
        self._update_visibility()
        self._field_changed()

    def _field_changed(self, *args) -> None:
        if self._loading or self.el is None:
            return
        self._write_back()
        self.changed.emit()

    def _set(self, tag: str, text: str, typ: Optional[str] = None) -> None:
        for e in self.el.findall(tag):
            self.el.remove(e)
        if text.strip():
            e = etree.SubElement(self.el, tag)
            e.text = text.strip()
            if typ:
                e.set("type", typ)

    def _write_back(self) -> None:
        el = self.el
        cmd = self.command()
        fields = FIELDS_BY_CMD.get(cmd, [])
        c = el.find("command")
        if c is None:
            c = etree.Element("command")
            el.insert(0, c)
        c.text = cmd
        # removes managed fields that do not apply to the order
        for tag in _MANAGED - {"command"}:
            for e in el.findall(tag):
                el.remove(e)
        if "property" in fields:
            self._set("property", self.widgets["property"].text())
            if "property2" in fields and self.widgets["property2"].text().strip():
                e = etree.SubElement(el, "property")
                e.text = self.widgets["property2"].text().strip()
        if cmd == "property-cycle":
            for v in self.widgets["values"].text().split(";"):
                if v.strip():
                    etree.SubElement(el, "value").text = v.strip()
        elif "value" in fields and not self.widgets["property2"].text().strip():
            self._set("value", self.widgets["value"].text())
        for key in ("step", "min", "max", "offset", "factor"):
            if key in fields:
                self._set(key, self.widgets[key].text(), "double")
        if "power" in fields:
            self._set("power", self.widgets["power"].text(), "int")
        if "wrap" in fields and self.wrap.isChecked():
            self._set("wrap", "true", "bool")
        if "dialog-name" in fields:
            self._set("dialog-name", self.widgets["dialog-name"].currentText())
        if "script" in fields:
            txt = self.script.toPlainText()
            if txt.strip():
                s = etree.SubElement(el, "script")
                s.text = etree.CDATA(txt) if any(ch in txt for ch in "<>&") else txt


# ---------------------------------------------------------------------------
# List of bindings
# ---------------------------------------------------------------------------

class BindingListEditor(QWidget):
    changed = Signal()

    def __init__(self, properties: list[str], parent=None):
        super().__init__(parent)
        self.elements: list[etree._Element] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        bar = QHBoxLayout()
        self.btn_add = QPushButton("＋ Add")
        self.btn_del = QPushButton("Delete")
        self.btn_up = QPushButton("↑")
        self.btn_down = QPushButton("↓")
        self.btn_xml = QPushButton("XML")
        self.btn_xml.setCheckable(True)
        self.btn_xml.setToolTip("Directly edit the binding XML")
        for b in (self.btn_add, self.btn_del, self.btn_up, self.btn_down):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.btn_xml)
        root.addLayout(bar)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        # vue guidée
        guided = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(180)
        self.form = BindingForm(properties)
        guided.addWidget(self.list)
        fw = QWidget()
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(10, 0, 0, 0)
        fl.addWidget(self.form)
        fl.addStretch(1)
        guided.addWidget(fw)
        guided.setSizes([220, 480])
        self.stack.addWidget(guided)
        # vue XML
        self.xml = QPlainTextEdit()
        self.xml.setFont(theme.mono_font(10))
        self.stack.addWidget(self.xml)
        self.empty_hint = QLabel()
        self.empty_hint.setProperty("muted", True)
        root.addWidget(self.empty_hint)

        self.btn_add.clicked.connect(self._add)
        self.btn_del.clicked.connect(self._delete)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_xml.toggled.connect(self._toggle_xml)
        self.list.currentRowChanged.connect(self._select)
        self.form.changed.connect(self._form_changed)
        self.xml.textChanged.connect(self.changed)

    def set_empty_hint(self, text: str) -> None:
        self.empty_hint.setText(text)

    def set_bindings(self, xmls: list[str]) -> None:
        if self.btn_xml.isChecked():
            self.btn_xml.blockSignals(True)
            self.btn_xml.setChecked(False)
            self.btn_xml.blockSignals(False)
            self.stack.setCurrentIndex(0)
        self.elements = [_elem(x) for x in xmls]
        self._refresh_list(0 if self.elements else -1)

    def bindings(self) -> list[str]:
        if self.btn_xml.isChecked():
            self._parse_xml_view()
        return [_xml(e) for e in self.elements]

    def validate(self) -> Optional[str]:
        if self.btn_xml.isChecked():
            try:
                self._parse_xml_view()
            except ValueError as e:
                return str(e)
        for e in self.elements:
            cmd = (e.findtext("command") or "").strip()
            if not cmd:
                return "A binding has no command."
            if cmd.startswith("property-") and not (e.findtext("property") or "").strip():
                return f"The order « {cmd} » requires a property."
            if cmd == "nasal" and not (e.findtext("script") or "").strip():
                return "The Nasal script is empty."
        return None

    def _parse_xml_view(self) -> None:
        txt = self.xml.toPlainText().strip()
        if not txt:
            self.elements = []
            return
        try:
            root = etree.fromstring(("<r>" + txt + "</r>").encode("utf-8"),
                                    etree.XMLParser(strip_cdata=False, remove_blank_text=True))
        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML : {e}") from e
        els = [c for c in root if isinstance(c.tag, str)]
        if any(c.tag != "binding" for c in els):
            raise ValueError("Only <binding> elements are accepted.")
        self.elements = els

    def _toggle_xml(self, on: bool) -> None:
        if on:
            self.xml.blockSignals(True)
            self.xml.setPlainText("\n".join(_xml(e) for e in self.elements))
            self.xml.blockSignals(False)
            self.stack.setCurrentIndex(1)
        else:
            try:
                self._parse_xml_view()
            except ValueError as e:
                QMessageBox.warning(self, "Invalid XML", str(e))
                self.btn_xml.blockSignals(True)
                self.btn_xml.setChecked(True)
                self.btn_xml.blockSignals(False)
                return
            self.stack.setCurrentIndex(0)
            self._refresh_list(0 if self.elements else -1)
        for b in (self.btn_add, self.btn_del, self.btn_up, self.btn_down):
            b.setEnabled(not on)

    def _refresh_list(self, select: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.elements:
            try:
                txt = summarize(binding_from_xml(_xml(e)), 70)
            except Exception:
                txt = "(invalid binding)"
            self.list.addItem(QListWidgetItem(txt))
        self.list.blockSignals(False)
        if 0 <= select < len(self.elements):
            self.list.setCurrentRow(select)
            self.form.set_element(self.elements[select])
        else:
            self.form.set_element(None)
        self.btn_del.setEnabled(bool(self.elements))

    def _select(self, row: int) -> None:
        self.form.set_element(self.elements[row] if 0 <= row < len(self.elements) else None)

    def _form_changed(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.elements):
            try:
                self.list.item(row).setText(summarize(binding_from_xml(_xml(self.elements[row])), 70))
            except Exception:
                pass
        self.changed.emit()

    def _add(self) -> None:
        el = _elem("<binding><command>property-toggle</command><property></property></binding>")
        self.elements.append(el)
        self._refresh_list(len(self.elements) - 1)
        self.changed.emit()

    def _delete(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.elements):
            del self.elements[row]
            self._refresh_list(min(row, len(self.elements) - 1))
            self.changed.emit()

    def _move(self, d: int) -> None:
        row = self.list.currentRow()
        j = row + d
        if 0 <= row < len(self.elements) and 0 <= j < len(self.elements):
            self.elements[row], self.elements[j] = self.elements[j], self.elements[row]
            self._refresh_list(j)
            self.changed.emit()


# ---------------------------------------------------------------------------
# Dialogue
# ---------------------------------------------------------------------------

class BindingEditorDialog(QDialog):
    CLEARED = 2

    def __init__(
        self,
        parent: QWidget,
        title: str,
        subtitle: str,
        catalog: Catalog,
        kind: str = "button",  # button | axis
        press: Optional[list[str]] = None,
        release: Optional[list[str]] = None,
        desc: str = "",
        repeatable: bool = False,
        properties: Optional[list[str]] = None,
        allow_release: bool = True,
        allow_repeat: bool = True,
        allow_clear: bool = True,
        clear_label: str = "Effacer l'assignation",
        preset: Optional[Action] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1080, 640)
        self.catalog = catalog
        self.kind = kind
        self._preset_desc = ""
        props = set(properties or [])
        for a in catalog.actions:
            for x in a.press + a.release:
                try:
                    b = binding_from_xml(x)
                    for p in b.children("property"):
                        if p.value:
                            props.add(p.value.strip())
                except Exception:
                    pass

        root = QVBoxLayout(self)
        h = QLabel(title)
        h.setProperty("heading", True)
        root.addWidget(h)
        sub = QLabel(subtitle)
        sub.setProperty("muted", True)
        sub.setWordWrap(True)
        sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(sub)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # catalogue
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 8, 8, 0)
        lab = QLabel("Choisir une action")
        lab.setStyleSheet("font-weight:600")
        ll.addWidget(lab)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer : train, volets, vue…")
        self.filter.setClearButtonEnabled(True)
        ll.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        ll.addWidget(self.tree, 1)
        split.addWidget(left)

        # détails
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 0, 0)
        form = QFormLayout()
        self.desc = QLineEdit(desc)
        self.desc.setPlaceholderText("Description displayed in the FlightGear help")
        form.addRow("Description", self.desc)
        self.repeat = QCheckBox("Repeat while the key / button is held")
        self.repeat.setChecked(repeatable)
        self.repeat.setVisible(allow_repeat)
        form.addRow("", self.repeat)
        rl.addLayout(form)
        self.tabs = QTabWidget()
        self.press_ed = BindingListEditor(sorted(props))
        self.release_ed = BindingListEditor(sorted(props))
        self.press_ed.set_empty_hint("")
        self.tabs.addTab(self.press_ed, "Axis movement" if kind == "axis" else "In support")
        if allow_release:
            self.tabs.addTab(self.release_ed, "Upon release")
        rl.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([330, 750])

        bb = QDialogButtonBox()
        self.btn_clear = QPushButton(clear_label)
        self.btn_clear.setProperty("danger", True)
        self.btn_clear.setVisible(allow_clear)
        bb.addButton(self.btn_clear, QDialogButtonBox.ResetRole)
        self.btn_ok = bb.addButton("Enregistrer", QDialogButtonBox.AcceptRole)
        self.btn_ok.setProperty("primary", True)
        bb.addButton("Cancel", QDialogButtonBox.RejectRole)
        root.addWidget(bb)

        self.press_ed.set_bindings(press or [])
        self.release_ed.set_bindings(release or [])
        self._fill_tree()
        self.filter.textChanged.connect(self._fill_tree)
        self.tree.currentItemChanged.connect(self._on_pick)
        self.btn_clear.clicked.connect(self._clear)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        if preset is not None:
            self.apply_action(preset)
            self._select_action(preset.id)
        else:
            self._select_current()

    # -- catalogue ------------------------------------------------------
    def _fill_tree(self) -> None:
        q = fold(self.filter.text().strip())
        cur = self.tree.currentItem()
        cur_id = cur.data(0, Qt.UserRole) if cur else None
        self.tree.blockSignals(True)
        self.tree.clear()
        custom = QTreeWidgetItem(["✎  Action personnalisée"])
        custom.setData(0, Qt.UserRole, "__custom__")
        self.tree.addTopLevelItem(custom)
        cats: dict[str, QTreeWidgetItem] = {}
        for a in self.catalog.actions:
            if (self.kind == "axis") != (a.kind == "axis"):
                continue
            if q and q not in fold(a.label + " " + a.category + " " + a.id):
                continue
            cat = cats.get(a.category)
            if cat is None:
                cat = QTreeWidgetItem([a.category])
                cat.setFlags(cat.flags() & ~Qt.ItemIsSelectable)
                cat.setForeground(0, QColor(theme.MUTED))
                cats[a.category] = cat
                self.tree.addTopLevelItem(cat)
            it = QTreeWidgetItem([a.label])
            it.setData(0, Qt.UserRole, a.id)
            it.setToolTip(0, a.id)
            cat.addChild(it)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if cur_id:
            self._select_action(cur_id, quiet=True)

    def _select_action(self, aid: str, quiet: bool = False) -> None:
        its = self.tree.findItems("*", Qt.MatchWildcard | Qt.MatchRecursive)
        for it in its:
            if it.data(0, Qt.UserRole) == aid:
                if quiet:
                    self.tree.blockSignals(True)
                self.tree.setCurrentItem(it)
                self.tree.scrollToItem(it)
                if quiet:
                    self.tree.blockSignals(False)
                return

    def _select_current(self) -> None:
        try:
            nodes = [binding_from_xml(x) for x in self.press_ed.bindings()]
        except Exception:
            nodes = []
        a = self.catalog.identify(nodes)
        if a is not None:
            self._select_action(a.id, quiet=True)
        elif nodes:
            self._select_action("__custom__", quiet=True)

    def _on_pick(self, item: Optional[QTreeWidgetItem], _prev=None) -> None:
        if item is None:
            return
        aid = item.data(0, Qt.UserRole)
        if not aid or aid == "__custom__":
            return
        a = self.catalog.by_id.get(aid)
        if a is not None:
            self.apply_action(a)

    def apply_action(self, a: Action) -> None:
        self.press_ed.set_bindings(a.press)
        self.release_ed.set_bindings(a.release)
        if not self.desc.text().strip() or self.desc.text() == self._preset_desc:
            self.desc.setText(a.label)
            self._preset_desc = a.label
        self.repeat.setChecked(a.repeatable)

    # -- résultat -------------------------------------------------------
    def _clear(self) -> None:
        self.done(self.CLEARED)

    def _accept(self) -> None:
        for ed in (self.press_ed, self.release_ed):
            err = ed.validate()
            if err:
                QMessageBox.warning(self, "Assignation incomplète", err)
                return
        if not self.press_ed.bindings() and not self.release_ed.bindings():
            QMessageBox.information(self, "Aucune action",
                                    "Choisissez une action dans la liste, ou utilisez « Effacer l'assignation ».")
            return
        self.accept()

    def result_data(self) -> dict:
        return {
            "press": self.press_ed.bindings(),
            "release": self.release_ed.bindings(),
            "desc": self.desc.text().strip(),
            "repeatable": self.repeat.isChecked(),
        }
