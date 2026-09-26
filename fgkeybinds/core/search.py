"""Recherche par touche ou par action."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .bindings import MOD_ALT, MOD_CTRL, MOD_META, MOD_SHIFT, MOD_SUPER, canonical, is_null, summarize
from .joystick import AXIS_NAMES_WIN, MAX_AXES, MAX_BUTTONS, JoystickConfig
from .keyboard import KeyboardConfig, combo_label
from .layouts import LAYER_NAME, Layout


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


@dataclass
class SearchItem:
    context: str  # « Clavier », nom du joystick...
    input: str  # « Ctrl+A », « Bouton 3 »...
    action: str
    detail: str  # résumé des commandes
    origin: str  # global | aircraft | joystick
    ref: dict = field(default_factory=dict)  # pour la navigation
    haystack: str = ""

    def build(self) -> "SearchItem":
        self.haystack = fold(" ".join([self.context, self.input, self.action, self.detail]))
        return self


def physical_hint(layout: Optional[Layout], code: int, mask: int) -> str:
    """Touche(s) physique(s) à presser sur la disposition donnée, ex. « Maj+& ou Maj+1 (pavé num.) »."""
    if layout is None:
        return ""
    found = layout.find_inputs(code, mask)
    if not found:
        return ""
    # le bloc principal avant le pavé numérique
    found.sort(key=lambda kl: kl[0].kind == "numpad")
    out: list[str] = []
    for k, lid in found:
        txt = k.display_name if lid == "none" else f"{LAYER_NAME[lid]}+{k.display_name}"
        if txt not in out:
            out.append(txt)
    return " ou ".join(out[:2])


def _catalog_label(catalog, nodes) -> str:
    if catalog is None:
        return ""
    a = catalog.identify(nodes)
    return a.label if a is not None else ""


def keyboard_items(kb: KeyboardConfig, layout: Optional[Layout], context: str = "Clavier",
                   catalog=None) -> list[SearchItem]:
    out = []
    for s in kb.slots():
        if not s.is_bound:
            continue
        combo = combo_label(s.code, s.mask)
        hint = physical_hint(layout, s.code, s.mask)
        inp = combo if not hint or hint.upper() == combo.upper() else f"{combo}  ({layout.name.split(' ')[0]} : {hint})"
        detail = " ; ".join(summarize(b.node, 70) for b in s.live_press + s.live_release)
        canon = " ".join(canonical(b.node) for b in s.live_press + s.live_release)
        cat = _catalog_label(catalog, [b.node for b in s.live_press])
        if cat:
            detail = f"[{cat}]  {detail}"
        it = SearchItem(context, inp, s.description(), detail, s.origin,
                        {"type": "key", "code": s.code, "mask": s.mask})
        it.build()
        it.haystack += " " + fold(canon)
        out.append(it)
    return out


def joystick_items(cfg: JoystickConfig, device_name: Optional[str] = None, catalog=None) -> list[SearchItem]:
    ctx = device_name or cfg.title
    out = []
    for a in sorted(cfg.axes.values(), key=lambda a: a.index):
        if not a.is_bound or a.index >= MAX_AXES:
            continue
        name = f"Axe {a.index} ({AXIS_NAMES_WIN[a.index]})"
        detail = " ; ".join(summarize(b, 70) for b in a.bindings if not is_null(b))
        cat = _catalog_label(catalog, a.bindings)
        if cat:
            detail = f"[{cat}]  {detail}"
        it = SearchItem(ctx, name, a.description(), detail, "joystick",
                        {"type": "axis", "index": a.index, "config": str(cfg.path), "device": device_name}).build()
        it.haystack += " " + fold(" ".join(canonical(b) for b in a.bindings))
        out.append(it)
    for b in sorted(cfg.buttons.values(), key=lambda b: b.index):
        if not b.is_bound or b.index >= MAX_BUTTONS:
            continue
        detail = " ; ".join(summarize(x, 70) for x in b.press + b.release if not is_null(x))
        cat = _catalog_label(catalog, b.press)
        if cat:
            detail = f"[{cat}]  {detail}"
        it = SearchItem(ctx, f"Bouton {b.index}", b.description(), detail, "joystick",
                        {"type": "button", "index": b.index, "config": str(cfg.path), "device": device_name}).build()
        it.haystack += " " + fold(" ".join(canonical(x) for x in b.press + b.release))
        out.append(it)
    return out


def text_filter(items: list[SearchItem], query: str) -> list[SearchItem]:
    toks = [fold(t) for t in query.split() if t.strip()]
    if not toks:
        return list(items)
    return [it for it in items if all(t in it.haystack for t in toks)]


# ---------------------------------------------------------------------------
# Analyse d'une combinaison saisie au clavier (« ctrl+a », « maj+F1 »...)
# ---------------------------------------------------------------------------

_MODS = {
    "ctrl": MOD_CTRL, "control": MOD_CTRL, "ctl": MOD_CTRL, "strg": MOD_CTRL,
    "alt": MOD_ALT, "altgr": MOD_CTRL | MOD_ALT,
    "maj": MOD_SHIFT, "shift": MOD_SHIFT, "⇧": MOD_SHIFT,
    "meta": MOD_META, "super": MOD_SUPER, "win": MOD_SUPER,
}

_NAMED = {
    "esc": 27, "echap": 27, "escape": 27, "tab": 9, "enter": 13, "entree": 13, "return": 13,
    "space": 32, "espace": 32, "backspace": 8, "retour": 8, "suppr": 127, "del": 127, "delete": 127,
    "inser": 364, "insert": 364, "ins": 364, "home": 362, "origine": 362, "debut": 362, "end": 363, "fin": 363,
    "pgup": 360, "pageup": 360, "pgprec": 360, "pgdn": 361, "pagedown": 361, "pgsuiv": 361,
    "left": 356, "gauche": 356, "←": 356, "up": 357, "haut": 357, "↑": 357,
    "right": 358, "droite": 358, "→": 358, "down": 359, "bas": 359, "↓": 359,
    "kpenter": 269, "numenter": 269,
}
for _i in range(1, 13):
    _NAMED[f"f{_i}"] = 256 + _i


def parse_combo(text: str) -> Optional[tuple[int, int]]:
    """Convertit « Ctrl+Maj+A » en (code FlightGear, masque).  None si invalide."""
    t = text.strip()
    if not t:
        return None
    parts: list[str] = []
    buf = ""
    for i, ch in enumerate(t):
        if ch == "+" and buf and i < len(t) - 1:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    mask = 0
    for p in parts[:-1]:
        m = _MODS.get(fold(p.strip()))
        if m is None:
            return None
        mask |= m
    key = parts[-1].strip()
    if not key:
        return None
    fk = fold(key).replace(" ", "").replace(".", "")
    if fk in _NAMED:
        return _NAMED[fk], mask
    if len(key) == 1:
        c = key
        if c.isalpha() and c.isascii():
            if mask & MOD_CTRL:
                return ord(c.lower()) - 96, mask
            if mask & MOD_SHIFT:
                return ord(c.upper()), mask
            return ord(c.lower()), mask
        return ord(c), mask
    return None
