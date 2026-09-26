"""Page « Périphériques » : joysticks, manettes, palonniers, yokes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import curves as cv
from ..core import joystick as js
from ..core import xmledit
from . import ops, theme
from .capture import JoystickCaptureDialog
from .curve_editor import CurveDialog, CurveWidget
from .device_art import DeviceArt
from .state import AppState


# ---------------------------------------------------------------------------
# Petits composants
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for it in self._items:
            sz = it.sizeHint()
            if x + sz.width() > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._spacing
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._spacing
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y() + m.bottom()


class ButtonTile(QFrame):
    clicked = Signal(int)
    menuRequested = Signal(int, QPoint)

    def __init__(self, index: int, text: str, bound: bool):
        super().__init__()
        self.index = index
        self.bound = bound
        self.setFixedSize(150, 62)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(1)
        self.num = QLabel(f"Bouton {index}")
        self.num.setStyleSheet("font-weight:700; background: transparent;")
        self.txt = QLabel(text or "—")
        self.txt.setWordWrap(True)
        self.txt.setStyleSheet(f"color: {'white' if bound else theme.MUTED}; font-size: 8.5pt; background: transparent;")
        lay.addWidget(self.num)
        lay.addWidget(self.txt, 1)
        self.setToolTip(text or "Libre — cliquez pour assigner une action")
        self.set_pressed(False)

    def set_pressed(self, on: bool) -> None:
        if on:
            bg, border = "#1f5a33", theme.GREEN
        elif self.bound:
            bg, border = "#23466f", "#2f6fc4"
        else:
            bg, border = theme.CARD, theme.BORDER
        self.setStyleSheet(f"ButtonTile {{ background: {bg}; border: 1px solid {border}; border-radius: 7px; }}")

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        elif ev.button() == Qt.RightButton:
            self.menuRequested.emit(self.index, ev.globalPosition().toPoint())


class AxisBar(QWidget):
    """Jauge bipolaire (−1 … +1) partant du centre."""

    def __init__(self):
        super().__init__()
        self.value: Optional[float] = None
        self.setFixedSize(130, 14)

    def set_value(self, v: Optional[float]) -> None:
        self.value = v
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 2.5, -0.5, -2.5)
        p.setPen(QColor(theme.BORDER))
        p.setBrush(QColor(theme.BG))
        p.drawRoundedRect(r, 4, 4)
        cx = r.center().x()
        p.setPen(QColor(theme.MUTED))
        p.drawLine(QPointF(cx, r.top() - 2), QPointF(cx, r.bottom() + 2))
        if self.value is None:
            return
        v = max(-1.0, min(1.0, self.value))
        w = v * (r.width() / 2 - 1)
        bar = QRectF(cx, r.top() + 1.5, w, r.height() - 3).normalized()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.GREEN))
        p.drawRoundedRect(bar, 2, 2)


class AxisRow(QFrame):
    editRequested = Signal(int)
    curveRequested = Signal(int)

    def __init__(self, index: int, axis: Optional[js.AxisDef], curve: Optional[cv.AxisCurve], ignored: bool,
                 live: bool = False):
        super().__init__()
        self.index = index
        self.setProperty("card", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        name = js.AXIS_NAMES_WIN[index] if index < len(js.AXIS_NAMES_WIN) else "?"
        t = QLabel(f"<b>Axe {index}</b><br><span style='color:{theme.MUTED}'>{name}</span>")
        t.setFixedWidth(90)
        lay.addWidget(t)
        self.bar = AxisBar()
        self.bar.setVisible(live)
        lay.addWidget(self.bar)
        desc = axis.description() if axis else ""
        if ignored:
            desc = "Index ≥ 8 : ignoré par FlightGear sous Windows. " + desc
        d = QLabel(desc or "—")
        d.setWordWrap(True)
        if not axis or not axis.is_bound:
            d.setStyleSheet(f"color: {theme.MUTED}")
        lay.addWidget(d, 1)
        self.mini = CurveWidget(compact=True)
        self.mini.setFixedSize(54, 54)
        if curve is not None:
            self.mini.set_curve(curve)
        lay.addWidget(self.mini)
        info = []
        if curve is not None:
            if curve.dead_band:
                info.append(f"Zone morte {curve.dead_band * 100:.0f} %")
            if curve.expo:
                info.append(f"Expo {curve.expo * 100:.0f} %")
            if curve.invert:
                info.append("Inversé")
            if curve.kind == "scale" and curve.power > 1:
                info.append(f"x<sup>{curve.power}</sup>")
        il = QLabel("<br>".join(info) if info else "Linéaire")
        il.setTextFormat(Qt.RichText)
        il.setFixedWidth(110)
        il.setProperty("muted", True)
        lay.addWidget(il)
        b1 = QPushButton("Action…")
        b2 = QPushButton("Courbe…")
        b2.setEnabled(axis is not None and bool(axis.bindings))
        lay.addWidget(b1)
        lay.addWidget(b2)
        b1.clicked.connect(lambda: self.editRequested.emit(self.index))
        b2.clicked.connect(lambda: self.curveRequested.emit(self.index))

    def set_value(self, v: Optional[float]) -> None:
        self.bar.set_value(v)
        self.mini.set_live(v)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class DevicesPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.cfg: Optional[js.JoystickConfig] = None
        self.device: Optional[js.Device] = None
        self.mode = ""
        self.axis_rows: dict[int, AxisRow] = {}
        self.tiles: dict[int, ButtonTile] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # liste
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        hl = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer les configurations…")
        self.filter.setClearButtonEnabled(True)
        hl.addWidget(self.filter, 1)
        self.btn_detect = QPushButton("Détecter")
        self.btn_detect.setToolTip("Rechercher à nouveau les périphériques branchés")
        hl.addWidget(self.btn_detect)
        ll.addLayout(hl)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        ll.addWidget(self.tree, 1)
        split.addWidget(left)

        # détail
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.detail = QWidget()
        self.scroll.setWidget(self.detail)
        self.dl = QVBoxLayout(self.detail)
        self.dl.setContentsMargins(8, 0, 8, 8)
        split.addWidget(self.scroll)
        split.setSizes([330, 1000])

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)

        self.filter.textChanged.connect(self._fill_tree)
        self.btn_detect.clicked.connect(self._detect)
        self.tree.currentItemChanged.connect(self._pick)
        state.devicesChanged.connect(self._reload_keep)
        state.dataChanged.connect(self._reload_keep)
        state.navigateControl.connect(self.show_control)
        self._fill_tree()
        self._select_first()

    # -- liste ---------------------------------------------------------------
    def _fill_tree(self) -> None:
        q = self.filter.text().strip().lower()
        self.tree.blockSignals(True)
        self.tree.clear()
        ws = self.state.ws
        conn = QTreeWidgetItem([f"Branchés ({len(ws.devices)})"])
        conn.setFlags(conn.flags() & ~Qt.ItemIsSelectable)
        self.tree.addTopLevelItem(conn)
        for aj in ws.active_joysticks():
            label = aj.device.name
            it = QTreeWidgetItem([label])
            it.setData(0, Qt.UserRole, ("device", aj.device.id))
            col = {"exact": theme.GREEN, "approx": theme.AMBER, "default": theme.MUTED}.get(aj.mode, theme.RED)
            it.setForeground(0, QColor(col))
            tip = {"exact": f"Configuration : {aj.config.path}" if aj.config else "",
                   "approx": "Une configuration porte un nom proche, mais FlightGear ne l'utilisera pas "
                             "(le nom doit correspondre exactement).",
                   "default": "Aucune configuration dédiée : FlightGear utilise la configuration par défaut.",
                   "none": "Aucune configuration disponible."}.get(aj.mode, "")
            it.setToolTip(0, tip)
            conn.addChild(it)
        if not ws.devices:
            it = QTreeWidgetItem(["Aucun périphérique détecté"])
            it.setFlags(Qt.NoItemFlags)
            conn.addChild(it)
        lib = QTreeWidgetItem([f"Bibliothèque ({len(ws.joy_lib.configs)})"])
        lib.setFlags(lib.flags() & ~Qt.ItemIsSelectable)
        self.tree.addTopLevelItem(lib)
        groups: dict[str, QTreeWidgetItem] = {}
        for cfg in sorted(ws.joy_lib.configs, key=lambda c: (c.origin != "home", c.path.parent.name.lower(),
                                                            c.title.lower())):
            if q and q not in (cfg.title + " " + " ".join(cfg.names) + " " + str(cfg.path)).lower():
                continue
            gname = "Mes configurations (FG_HOME)" if cfg.origin == "home" else cfg.path.parent.name
            g = groups.get(gname)
            if g is None:
                g = QTreeWidgetItem([gname])
                g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
                g.setForeground(0, QColor(theme.AMBER if cfg.origin == "home" else theme.MUTED))
                groups[gname] = g
                lib.addChild(g)
            it = QTreeWidgetItem([cfg.title])
            it.setData(0, Qt.UserRole, ("config", str(cfg.path)))
            it.setToolTip(0, str(cfg.path))
            g.addChild(it)
        conn.setExpanded(True)
        lib.setExpanded(True)
        for g in groups.values():
            g.setExpanded(bool(q) or g.text(0).startswith("Mes"))
        self.tree.blockSignals(False)

    def _select_first(self) -> None:
        conn = self.tree.topLevelItem(0)
        if conn is not None and conn.childCount() and conn.child(0).data(0, Qt.UserRole):
            self.tree.setCurrentItem(conn.child(0))
        else:
            self._show(None, None, "")

    def _detect(self) -> None:
        self.state.ws.reload_joysticks()
        self.state.devicesChanged.emit()
        n = len(self.state.ws.devices)
        self.state.status.emit(f"{n} périphérique(s) détecté(s).")

    def _reload_keep(self) -> None:
        cur = self.tree.currentItem()
        key = cur.data(0, Qt.UserRole) if cur else None
        self._fill_tree()
        if key and self._select_key(key):
            return
        self._select_first()

    def _select_key(self, key) -> bool:
        for it in self.tree.findItems("*", Qt.MatchWildcard | Qt.MatchRecursive):
            if it.data(0, Qt.UserRole) == key:
                self.tree.setCurrentItem(it)
                self._pick(it)
                return True
        return False

    def _pick(self, item: Optional[QTreeWidgetItem], _prev=None) -> None:
        if item is None:
            return
        d = item.data(0, Qt.UserRole)
        if not d:
            return
        ws = self.state.ws
        if d[0] == "device":
            dev = next((x for x in ws.devices if x.id == d[1]), None)
            if dev is None:
                return
            cfg, mode = ws.joy_lib.match(dev.name)
            self._show(cfg, dev, mode)
        else:
            cfg = ws.config_by_path(Path(d[1]))
            self._show(cfg, None, "library")

    def show_control(self, cfg_path: str, typ: str, index: int, device_name: str) -> None:
        ws = self.state.ws
        dev = next((x for x in ws.devices if x.name == device_name), None) if device_name else None
        if dev is not None:
            self._select_key(("device", dev.id))
        else:
            self._select_key(("config", cfg_path))
        w = self.axis_rows.get(index) if typ == "axis" else self.tiles.get(index)
        if w is not None:
            self.scroll.ensureWidgetVisible(w)
            cls = type(w).__name__
            w.setStyleSheet(f"{cls} {{ border: 2px solid {theme.YELLOW}; border-radius: 8px;"
                            f" background: {theme.CARD_HI}; }}")

    # -- détail ----------------------------------------------------------------
    def _clear_detail(self) -> None:
        while self.dl.count():
            it = self.dl.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                self._drop_layout(it.layout())
        self.axis_rows = {}
        self.tiles = {}

    def _drop_layout(self, lay) -> None:
        while lay.count():
            it = lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
            elif it.layout() is not None:
                self._drop_layout(it.layout())

    def _show(self, cfg: Optional[js.JoystickConfig], dev: Optional[js.Device], mode: str) -> None:
        self.timer.stop()
        self._clear_detail()
        self.cfg, self.device, self.mode = cfg, dev, mode
        if cfg is None and dev is None:
            lbl = QLabel("Aucun périphérique de jeu détecté.\n\nBranchez votre joystick, manette des gaz, "
                         "palonnier ou yoke puis cliquez sur « Détecter ».\nVous pouvez aussi parcourir les "
                         "configurations de la bibliothèque dans la liste de gauche.")
            lbl.setProperty("muted", True)
            lbl.setAlignment(Qt.AlignCenter)
            self.dl.addWidget(lbl, 1)
            return
        name = dev.name if dev else cfg.title
        kind = self.state.settings.device_kinds.get(name) or js.guess_kind(name, cfg)

        # en-tête
        head = QFrame()
        head.setProperty("card", True)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 12, 12, 12)
        art = DeviceArt()
        art.set_kind(kind, dev is not None)
        hl.addWidget(art)
        info = QVBoxLayout()
        t = QLabel(name)
        t.setProperty("heading", True)
        t.setWordWrap(True)
        info.addWidget(t)
        lines = []
        if dev is not None:
            lines.append(f"Périphérique n°{dev.id} · {dev.num_buttons} boutons · "
                         f"{'8 axes (avec chapeau chinois)' if dev.has_pov else '6 axes'} · "
                         f"VID {dev.vid:04X} PID {dev.pid:04X}")
        if cfg is not None:
            src = "personnelle (FG_HOME)" if cfg.origin == "home" else "FlightGear (FG_ROOT)"
            lines.append(f"Configuration {src} : {cfg.path}")
        msg = {
            "exact": ("✔ FlightGear utilise cette configuration.", theme.GREEN),
            "approx": ("⚠ Une configuration porte un nom proche, mais FlightGear exige une correspondance exacte "
                       "du nom : elle ne sera pas utilisée. Cliquez sur « Personnaliser » pour l'associer.",
                       theme.AMBER),
            "default": ("⚠ Aucune configuration dédiée : FlightGear utilise la configuration par défaut. "
                        "Cliquez sur « Personnaliser » pour créer la vôtre.", theme.AMBER),
            "library": ("Configuration de la bibliothèque (le périphérique n'est pas branché).", theme.MUTED),
            "none": ("Aucune configuration disponible.", theme.RED),
        }.get(self.mode)
        info_lbl = QLabel("<br>".join(lines))
        info_lbl.setProperty("muted", True)
        info_lbl.setWordWrap(True)
        info_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.addWidget(info_lbl)
        if msg:
            m = QLabel(msg[0])
            m.setWordWrap(True)
            m.setStyleSheet(f"color: {msg[1]}")
            info.addWidget(m)
        bar = QHBoxLayout()
        kc = QComboBox()
        for k, lbl in js.KIND_LABELS.items():
            kc.addItem(lbl, k)
        kc.setCurrentIndex(max(0, kc.findData(kind)))
        kc.currentIndexChanged.connect(lambda _i, n=name, c=kc, a=art: self._set_kind(n, c.currentData(), a))
        bar.addWidget(QLabel("Type :"))
        bar.addWidget(kc)
        if dev is not None and self.mode in ("approx", "default"):
            b = QPushButton("Personnaliser pour ce périphérique")
            b.setProperty("primary", True)
            b.clicked.connect(self._customize)
            bar.addWidget(b)
        if dev is not None:
            b = QPushButton("Identifier une commande…")
            b.clicked.connect(self._identify)
            bar.addWidget(b)
        if cfg is not None:
            b = QPushButton("Ouvrir le dossier")
            b.clicked.connect(lambda: os.startfile(str(cfg.path.parent)))  # noqa: S606
            bar.addWidget(b)
        bar.addStretch(1)
        info.addLayout(bar)
        hl.addLayout(info, 1)
        self.dl.addWidget(head)

        # axes
        ax_title = QLabel("Axes")
        ax_title.setStyleSheet("font-size: 12pt; font-weight: 700; margin-top: 8px;")
        self.dl.addWidget(ax_title)
        indices = set(cfg.axes) if cfg else set()
        if dev is not None:
            indices |= set(range(dev.num_axes))
        if not indices:
            e = QLabel("Aucun axe défini.")
            e.setProperty("muted", True)
            self.dl.addWidget(e)
        for i in sorted(indices):
            a = cfg.axes.get(i) if cfg else None
            curve = cv.curve_from_pnode_axis(a) if a is not None and a.node is not None else None
            row = AxisRow(i, a, curve, i >= js.MAX_AXES, live=dev is not None)
            row.editRequested.connect(self._edit_axis)
            row.curveRequested.connect(self._edit_curve)
            self.axis_rows[i] = row
            self.dl.addWidget(row)

        # boutons
        bt_title = QLabel("Boutons")
        bt_title.setStyleSheet("font-size: 12pt; font-weight: 700; margin-top: 8px;")
        self.dl.addWidget(bt_title)
        holder = QWidget()
        flow = FlowLayout(holder)
        flow.setContentsMargins(0, 0, 0, 0)
        bidx = set(cfg.buttons) if cfg else set()
        if dev is not None:
            bidx |= set(range(dev.num_buttons))
        for i in sorted(bidx):
            b = cfg.buttons.get(i) if cfg else None
            text = b.description() if b else ""
            if i >= js.MAX_BUTTONS:
                text = "(ignoré : index ≥ 32) " + text
            tile = ButtonTile(i, text, bool(b and b.is_bound))
            tile.clicked.connect(self._edit_button)
            tile.menuRequested.connect(self._button_menu)
            self.tiles[i] = tile
            flow.addWidget(tile)
        if not bidx:
            e = QLabel("Aucun bouton défini.")
            e.setProperty("muted", True)
            self.dl.addWidget(e)
        self.dl.addWidget(holder)
        self.dl.addStretch(1)
        if dev is not None:
            self.timer.start(40)

    def _set_kind(self, name: str, kind: str, art: DeviceArt) -> None:
        self.state.settings.device_kinds[name] = kind
        self.state.settings.save()
        art.set_kind(kind, self.device is not None)

    # -- live -------------------------------------------------------------
    def _poll(self) -> None:
        if self.device is None or not self.isVisible():
            return
        st = self.device.poll()
        for i, row in self.axis_rows.items():
            row.set_value(st.axes[i] if st is not None and i < len(st.axes) else None)
        for i, tile in self.tiles.items():
            tile.set_pressed(bool(st is not None and st.pressed(i)))

    # -- édition -------------------------------------------------------------
    def _device_name(self) -> Optional[str]:
        return self.device.name if self.device is not None else None

    def _customize(self) -> None:
        if self.device is None:
            return
        try:
            p = self.state.ws.joystick_for_device(self.device.name)
        except (xmledit.EditError, OSError) as e:
            ops.error(self, e)
            return
        self.state.devicesChanged.emit()
        self.state.after_write(p)

    def _identify(self) -> None:
        dlg = JoystickCaptureDialog(self, [self.device] if self.device else [], "any")
        if dlg.exec() and dlg.result_control:
            _d, typ, i = dlg.result_control
            if typ == "button":
                self._edit_button(i)
            else:
                self._edit_axis(i)

    def _ensure_cfg(self) -> Optional[js.JoystickConfig]:
        if self.cfg is not None:
            return self.cfg
        if self.device is not None:
            try:
                self.state.ws.joystick_for_device(self.device.name)
            except (xmledit.EditError, OSError) as e:
                ops.error(self, e)
                return None
            self.cfg, _ = self.state.ws.joy_lib.match(self.device.name)
        return self.cfg

    def _edit_button(self, i: int) -> None:
        cfg = self._ensure_cfg()
        if cfg is not None:
            ops.edit_joystick_control(self, self.state, cfg, self._device_name(), "button", i)

    def _button_menu(self, i: int, pos: QPoint) -> None:
        m = QMenu(self)
        a_edit = m.addAction("Modifier…")
        a_clear = m.addAction("Effacer")
        b = self.cfg.buttons.get(i) if self.cfg else None
        a_clear.setEnabled(b is not None)
        r = m.exec(pos)
        if r is a_edit:
            self._edit_button(i)
        elif r is a_clear and self.cfg is not None:
            try:
                path = self.state.ws.editable_joystick_path(self.cfg, self._device_name())
                self.state.ws.clear_joystick_control(path, "button", i)
            except (xmledit.EditError, OSError) as e:
                ops.error(self, e)
                return
            self.state.devicesChanged.emit()
            self.state.after_write(path)

    def _edit_axis(self, i: int) -> None:
        cfg = self._ensure_cfg()
        if cfg is None:
            return
        a = cfg.axes.get(i)
        virtual = None
        if a is not None and (a.low is not None or a.high is not None):
            m = QMenu(self)
            act_axis = m.addAction("Action analogique de l'axe…")
            act_low = m.addAction("Action de la demi-course − (bouton virtuel)…")
            act_high = m.addAction("Action de la demi-course + (bouton virtuel)…")
            r = m.exec(self.cursor().pos())
            if r is None:
                return
            virtual = {act_low: "low", act_high: "high"}.get(r)
        ops.edit_joystick_control(self, self.state, cfg, self._device_name(), "axis", i, virtual=virtual)

    def _edit_curve(self, i: int) -> None:
        cfg = self.cfg
        if cfg is None or i not in cfg.axes:
            return
        a = cfg.axes[i]
        curve = cv.curve_from_pnode_axis(a)
        name = self.device.name if self.device else cfg.title
        note = ""
        if cfg.origin != "home" or self.mode in ("approx", "default"):
            note = ("La configuration d'origine n'est pas modifiée : une copie personnelle, prioritaire, "
                    "est créée dans FG_HOME.")
        dlg = CurveDialog(self, f"{name} — Axe {i} : {a.desc or ''}", curve, self.device, i, note)
        if not dlg.exec():
            return
        db, expo, inv = dlg.values()
        try:
            path = self.state.ws.editable_joystick_path(cfg, self._device_name())
            self.state.ws.write_axis_curve(path, i, db, expo, inv)
        except (xmledit.EditError, OSError) as e:
            ops.error(self, e)
            return
        self.state.devicesChanged.emit()
        self.state.after_write(path)

    def hideEvent(self, ev) -> None:  # noqa: N802
        self.timer.stop()
        super().hideEvent(ev)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self.device is not None:
            self.timer.start(40)

