"""Opérations d'édition réutilisées par plusieurs pages."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from ..core import joystick as js
from ..core import xmledit
from ..core.bindings import binding_to_xml, is_null, mask_prefix
from ..core.catalog import Action
from ..core.keyboard import combo_label
from .binding_editor import BindingEditorDialog
from .state import AppState

ACCEPTED = 1


def error(parent: QWidget, e: Exception) -> None:
    QMessageBox.critical(parent, "Impossible d'enregistrer", str(e))


def confirm_global_write(parent: QWidget, state: AppState) -> bool:
    if state.settings.confirmed_root_write:
        return True
    fg_root = state.ws.paths.fg_root
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("Modifier les raccourcis globaux")
    box.setText("Les raccourcis globaux de FlightGear sont définis dans :\n"
                f"{fg_root / 'keyboard.xml'}")
    box.setInformativeText(
        "FGKeybinds va modifier ce fichier. Une copie de l'original est créée automatiquement "
        "(keyboard.xml.fgkb-backup) et peut être restaurée à tout moment (menu Sauvegardes).\n\n"
        "Une mise à jour de FlightGear peut remplacer ce fichier : vos modifications sont donc aussi "
        "mémorisées par FGKeybinds, qui proposera de les réappliquer.")
    cb = QCheckBox("Ne plus afficher ce message")
    box.setCheckBox(cb)
    box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
    box.button(QMessageBox.Ok).setText("Continuer")
    box.button(QMessageBox.Cancel).setText("Cancel")
    box.exec()
    if box.clickedButton() is not box.button(QMessageBox.Ok):
        return False
    if cb.isChecked():
        state.settings.confirmed_root_write = True
        state.settings.save()
    return True


def _mirror_codes(code: int) -> list[int]:
    # La touche Entrée est définie deux fois dans keyboard.xml (13 et 10)
    return [13, 10] if code in (13, 10) else [code]


def write_key(parent: QWidget, state: AppState, code: int, mask: int, press: list[str], release: list[str],
              desc: Optional[str], repeatable: Optional[bool]) -> bool:
    ctx = state.context
    if ctx.is_global and not confirm_global_write(parent, state):
        return False
    path = None
    try:
        for c in _mirror_codes(code):
            path = state.ws.write_slot(ctx, xmledit.SlotChange(
                code=c, mask=mask, press=press, release=release, desc=desc, repeatable=repeatable))
    except (xmledit.EditError, OSError, ValueError) as e:
        error(parent, e)
        return False
    state.after_write(path)
    return True


def edit_key(parent: QWidget, state: AppState, code: int, mask: int, preset: Optional[Action] = None) -> bool:
    ws = state.ws
    kb = state.keyboard
    slot = kb.slot(code, mask)
    press = [binding_to_xml(b.node) for b in slot.press if not b.null] if slot else []
    release = [binding_to_xml(b.node) for b in slot.release if not b.null] if slot else []
    desc = (slot.desc or "") if slot else ""
    combo = combo_label(code, mask)
    target = ws.target_description(state.context, code)
    sub = f"Contexte : {ws.context_label(state.context)}   ·   Fichier modifié : {target}"
    if not slot or not slot.is_bound:
        res = kb.resolve(code, mask)
        if res.slot is not None and res.slot.is_bound and res.fallback:
            sub += (f"\nActuellement, FlightGear se replie sur {combo_label(code, res.used_mask)} : "
                    f"« {res.slot.description()} ».")
    dlg = BindingEditorDialog(
        parent, f"Assigner {combo}", sub, ws.catalog, "button", press, release, desc,
        kb.repeatable(code), allow_clear=bool(slot and slot.is_bound),
        clear_label="Désactiver pour cet aéronef" if not state.context.is_global else "Effacer l'assignation",
        preset=preset,
    )
    r = int(dlg.exec())
    if r == BindingEditorDialog.CLEARED:
        return clear_key(parent, state, code, mask, ask=False)
    if r != ACCEPTED:
        return False
    d = dlg.result_data()
    return write_key(parent, state, code, mask, d["press"], d["release"], d["desc"], d["repeatable"])


def clear_key(parent: QWidget, state: AppState, code: int, mask: int, ask: bool = True) -> bool:
    combo = combo_label(code, mask)
    if ask:
        msg = (f"Effacer l'action de {combo} ?" if state.context.is_global else
               f"Désactiver {combo} pour cet aéronef ?\nL'action globale éventuelle sera neutralisée "
               "uniquement pour cet aéronef.")
        if QMessageBox.question(parent, "Confirmer", msg) != QMessageBox.Yes:
            return False
    return write_key(parent, state, code, mask, [], [], None, None)


def restore_key(parent: QWidget, state: AppState, code: int, mask: int) -> bool:
    try:
        path = None
        for c in _mirror_codes(code):
            try:
                path = state.ws.restore_slot_to_global(state.context, c, mask)
            except xmledit.EditError:
                if c == code:
                    raise
    except (xmledit.EditError, OSError) as e:
        error(parent, e)
        return False
    state.after_write(path)
    return True


# ---------------------------------------------------------------------------
# Joysticks
# ---------------------------------------------------------------------------

def edit_joystick_control(parent: QWidget, state: AppState, cfg: js.JoystickConfig, device_name: Optional[str],
                          typ: str, index: int, preset: Optional[Action] = None,
                          virtual: Optional[str] = None) -> bool:
    """Édite un bouton ou un axe.  ``virtual`` = "low"/"high" pour les demi-axes."""
    ws = state.ws
    title_dev = device_name or cfg.title
    if typ == "axis" and virtual is None:
        a = cfg.axes.get(index)
        press = [binding_to_xml(b) for b in a.bindings if not is_null(b)] if a else []
        desc = a.desc if a else ""
        dlg = BindingEditorDialog(
            parent, f"{title_dev} — Axe {index} ({js.AXIS_NAMES_WIN[index] if index < 8 else '?'})",
            _joy_subtitle(ws, cfg, device_name), ws.catalog, "axis", press, [], desc, False,
            allow_release=False, allow_repeat=False, allow_clear=bool(a), preset=preset)
    else:
        if virtual is not None:
            a = cfg.axes.get(index)
            b = getattr(a, virtual) if a else None
            label = f"Axe {index} {'−' if virtual == 'low' else '+'} (demi-course)"
        else:
            b = cfg.buttons.get(index)
            label = f"Bouton {index}"
        press = [binding_to_xml(x) for x in b.press if not is_null(x)] if b else []
        release = [binding_to_xml(x) for x in b.release if not is_null(x)] if b else []
        dlg = BindingEditorDialog(
            parent, f"{title_dev} — {label}", _joy_subtitle(ws, cfg, device_name), ws.catalog, "button",
            press, release, b.desc if b else "", b.repeatable if b else False, allow_clear=bool(b),
            preset=preset)
    r = int(dlg.exec())
    if r not in (ACCEPTED, BindingEditorDialog.CLEARED):
        return False
    try:
        path = ws.editable_joystick_path(cfg, device_name)
        if r == BindingEditorDialog.CLEARED:
            if virtual is not None:
                ws.write_joystick_button(path, index, None, [], [], False, (index, virtual))
            else:
                ws.clear_joystick_control(path, typ, index)
        else:
            d = dlg.result_data()
            if typ == "axis" and virtual is None:
                ws.write_joystick_axis(path, index, d["desc"], d["press"])
            else:
                ws.write_joystick_button(path, index, d["desc"], d["press"], d["release"], d["repeatable"],
                                         (index, virtual) if virtual else None)
    except (xmledit.EditError, OSError, ValueError) as e:
        error(parent, e)
        return False
    state.devicesChanged.emit()
    state.after_write(path)
    return True


def _joy_subtitle(ws, cfg: js.JoystickConfig, device_name: Optional[str]) -> str:
    if cfg.origin == "home" and device_name is None:
        return f"Fichier modifié : {cfg.path}"
    return (f"Configuration d'origine : {cfg.path}\nLes modifications sont écrites dans une copie personnelle "
            f"placée dans {ws.user_joystick_dir()} (prioritaire, l'original reste intact).")


def describe_mask(mask: int) -> str:
    return mask_prefix(mask).rstrip("+") or "Aucun"


def joystick_path_label(path: Path) -> str:
    return str(path)
