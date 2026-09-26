"""Dispositions physiques de clavier et correspondance avec les codes FlightGear.

FlightGear reçoit des *caractères* (et non des positions de touches) : sur un
clavier AZERTY, la touche marquée « A » produit ``a`` (97), et la touche « & »
produit ``&`` (38), ou ``1`` (49) avec Maj.  Chaque touche physique est donc
décrite par les caractères qu'elle produit sur chaque niveau (normal, Maj,
AltGr), puis traduite en (code, masque) pour chaque couche de modificateurs.

Des dispositions supplémentaires peuvent être ajoutées sous forme de fichiers
JSON dans le dossier utilisateur (voir ``load_user_layouts``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .bindings import MOD_ALT, MOD_CTRL, MOD_SHIFT

# ---------------------------------------------------------------------------
# Couches de modificateurs proposées dans l'interface
# ---------------------------------------------------------------------------

LAYERS: list[tuple[str, str, int]] = [
    ("none", "Normal", 0),
    ("shift", "Maj", MOD_SHIFT),
    ("ctrl", "Ctrl", MOD_CTRL),
    ("alt", "Alt", MOD_ALT),
    ("altgr", "AltGr", MOD_CTRL | MOD_ALT),
    ("ctrl+shift", "Ctrl+Maj", MOD_CTRL | MOD_SHIFT),
    ("alt+shift", "Alt+Maj", MOD_ALT | MOD_SHIFT),
]
LAYER_MASK = {lid: m for lid, _, m in LAYERS}
LAYER_NAME = {lid: n for lid, n, _ in LAYERS}


@dataclass(frozen=True)
class KeyInput:
    code: int
    mask: int
    text: str  # caractère ou nom produit (pour affichage)


@dataclass
class PhysKey:
    id: str
    x: float
    y: float
    w: float = 1.0
    h: float = 1.0
    kind: str = "char"  # char | special | numpad | modifier | dead
    label: str = ""
    base: Optional[str] = None
    shift: Optional[str] = None
    altgr: Optional[str] = None
    code: Optional[int] = None  # touches spéciales
    alt_codes: tuple[int, ...] = ()  # codes secondaires (Entrée = 13 et 10...)
    shape: Optional[str] = None  # "iso_enter"
    note: str = ""

    @property
    def display_name(self) -> str:
        name = self.label or (self.base or "")
        if self.kind == "numpad":
            name += " (pavé num.)"
        return name

    @property
    def bindable(self) -> bool:
        return self.kind not in ("modifier",)

    def input_for(self, layer: str) -> Optional[KeyInput]:
        """Code FlightGear et masque produits par cette touche sur une couche."""
        mask = LAYER_MASK[layer]
        if self.kind == "modifier":
            return None
        if self.kind in ("special", "numpad") and self.code is not None:
            return KeyInput(self.code, mask, self.label)
        # touches produisant des caractères
        if layer == "none":
            c = self.base
            return KeyInput(ord(c), 0, c) if c else None
        if layer == "shift":
            c = self.shift
            return KeyInput(ord(c), MOD_SHIFT, c) if c else None
        if layer in ("ctrl", "ctrl+shift"):
            c = self.base
            if not c:
                return None
            if "a" <= c.lower() <= "z" and len(c) == 1 and c.isascii():
                return KeyInput(ord(c.lower()) - 96, mask, "Ctrl+" + c.upper())
            if layer == "ctrl+shift" and self.shift:
                return KeyInput(ord(self.shift), mask, self.shift)
            return KeyInput(ord(c), mask, c)
        if layer == "alt":
            c = self.base
            return KeyInput(ord(c), MOD_ALT, c) if c else None
        if layer == "alt+shift":
            c = self.shift
            return KeyInput(ord(c), mask, c) if c else None
        if layer == "altgr":
            c = self.altgr
            return KeyInput(ord(c), MOD_CTRL | MOD_ALT, c) if c else None
        return None

    def all_codes(self) -> set[int]:
        codes: set[int] = set()
        if self.code is not None:
            codes.add(self.code)
        codes.update(self.alt_codes)
        for lid, _, _ in LAYERS:
            ki = self.input_for(lid)
            if ki:
                codes.add(ki.code)
        return codes


@dataclass
class Layout:
    id: str
    name: str
    variant: str  # "iso" | "ansi"
    has_altgr: bool
    keys: list[PhysKey] = field(default_factory=list)

    @property
    def width(self) -> float:
        return max(k.x + k.w for k in self.keys)

    @property
    def height(self) -> float:
        return max(k.y + k.h for k in self.keys)

    def key(self, kid: str) -> Optional[PhysKey]:
        for k in self.keys:
            if k.id == kid:
                return k
        return None

    def find_inputs(self, code: int, mask: int) -> list[tuple[PhysKey, str]]:
        """Touches physiques et couches produisant exactement (code, masque)."""
        out = []
        for k in self.keys:
            for lid, _, _ in LAYERS:
                if lid == "altgr" and not self.has_altgr:
                    continue
                ki = k.input_for(lid)
                if ki and ki.code == code and ki.mask == mask:
                    out.append((k, lid))
            if mask == 0 and code in k.alt_codes:
                out.append((k, "none"))
        return out

    def find_code(self, code: int) -> list[tuple[PhysKey, str]]:
        out = []
        for k in self.keys:
            for lid, _, _ in LAYERS:
                if lid == "altgr" and not self.has_altgr:
                    continue
                ki = k.input_for(lid)
                if ki and ki.code == code:
                    out.append((k, lid))
            if code in k.alt_codes:
                out.append((k, "none"))
        return out


# ---------------------------------------------------------------------------
# Tables de caractères
# ---------------------------------------------------------------------------

# Chaque entrée : (normal, maj, altgr)  -- None si rien n'est produit.
_AZERTY_FR = {
    "E": [("²", None, None), ("&", "1", None), ("é", "2", "~"), ('"', "3", "#"), ("'", "4", "{"),
          ("(", "5", "["), ("-", "6", "|"), ("è", "7", "`"), ("_", "8", "\\"), ("ç", "9", "^"),
          ("à", "0", "@"), (")", "°", "]"), ("=", "+", "}")],
    "D": [("a", "A", None), ("z", "Z", None), ("e", "E", "€"), ("r", "R", None), ("t", "T", None),
          ("y", "Y", None), ("u", "U", None), ("i", "I", None), ("o", "O", None), ("p", "P", None),
          ("^", "¨", None), ("$", "£", "¤")],
    "C": [("q", "Q", None), ("s", "S", None), ("d", "D", None), ("f", "F", None), ("g", "G", None),
          ("h", "H", None), ("j", "J", None), ("k", "K", None), ("l", "L", None), ("m", "M", None),
          ("ù", "%", None), ("*", "µ", None)],
    "B": [("<", ">", None), ("w", "W", None), ("x", "X", None), ("c", "C", None), ("v", "V", None),
          ("b", "B", None), ("n", "N", None), (",", "?", None), (";", ".", None), (":", "/", None),
          ("!", "§", None)],
}
_AZERTY_DEAD = {("D", 10)}  # ^ est une touche morte

_QWERTY_US = {
    "E": [("`", "~", None), ("1", "!", None), ("2", "@", None), ("3", "#", None), ("4", "$", None),
          ("5", "%", None), ("6", "^", None), ("7", "&", None), ("8", "*", None), ("9", "(", None),
          ("0", ")", None), ("-", "_", None), ("=", "+", None)],
    "D": [("q", "Q", None), ("w", "W", None), ("e", "E", None), ("r", "R", None), ("t", "T", None),
          ("y", "Y", None), ("u", "U", None), ("i", "I", None), ("o", "O", None), ("p", "P", None),
          ("[", "{", None), ("]", "}", None), ("\\", "|", None)],
    "C": [("a", "A", None), ("s", "S", None), ("d", "D", None), ("f", "F", None), ("g", "G", None),
          ("h", "H", None), ("j", "J", None), ("k", "K", None), ("l", "L", None), (";", ":", None),
          ("'", '"', None)],
    "B": [("z", "Z", None), ("x", "X", None), ("c", "C", None), ("v", "V", None), ("b", "B", None),
          ("n", "N", None), ("m", "M", None), (",", "<", None), (".", ">", None), ("/", "?", None)],
}

_QWERTY_UK = {
    "E": [("`", "¬", "¦"), ("1", "!", None), ("2", '"', None), ("3", "£", None), ("4", "$", "€"),
          ("5", "%", None), ("6", "^", None), ("7", "&", None), ("8", "*", None), ("9", "(", None),
          ("0", ")", None), ("-", "_", None), ("=", "+", None)],
    "D": [("q", "Q", None), ("w", "W", None), ("e", "E", "é"), ("r", "R", None), ("t", "T", None),
          ("y", "Y", None), ("u", "U", "ú"), ("i", "I", "í"), ("o", "O", "ó"), ("p", "P", None),
          ("[", "{", None), ("]", "}", None)],
    "C": [("a", "A", "á"), ("s", "S", None), ("d", "D", None), ("f", "F", None), ("g", "G", None),
          ("h", "H", None), ("j", "J", None), ("k", "K", None), ("l", "L", None), (";", ":", None),
          ("'", "@", None), ("#", "~", None)],
    "B": [("\\", "|", None), ("z", "Z", None), ("x", "X", None), ("c", "C", None), ("v", "V", None),
          ("b", "B", None), ("n", "N", None), ("m", "M", None), (",", "<", None), (".", ">", None),
          ("/", "?", None)],
}

_QWERTZ_DE = {
    "E": [("^", "°", None), ("1", "!", None), ("2", '"', "²"), ("3", "§", "³"), ("4", "$", None),
          ("5", "%", None), ("6", "&", None), ("7", "/", "{"), ("8", "(", "["), ("9", ")", "]"),
          ("0", "=", "}"), ("ß", "?", "\\"), ("´", "`", None)],
    "D": [("q", "Q", "@"), ("w", "W", None), ("e", "E", "€"), ("r", "R", None), ("t", "T", None),
          ("z", "Z", None), ("u", "U", None), ("i", "I", None), ("o", "O", None), ("p", "P", None),
          ("ü", "Ü", None), ("+", "*", "~")],
    "C": [("a", "A", None), ("s", "S", None), ("d", "D", None), ("f", "F", None), ("g", "G", None),
          ("h", "H", None), ("j", "J", None), ("k", "K", None), ("l", "L", None), ("ö", "Ö", None),
          ("ä", "Ä", None), ("#", "'", None)],
    "B": [("<", ">", "|"), ("y", "Y", None), ("x", "X", None), ("c", "C", None), ("v", "V", None),
          ("b", "B", None), ("n", "N", None), ("m", "M", "µ"), (",", ";", None), (".", ":", None),
          ("-", "_", None)],
}
_QWERTZ_DEAD = {("E", 0), ("E", 12)}


# ---------------------------------------------------------------------------
# Géométrie
# ---------------------------------------------------------------------------

Y_F = 0.0
Y_E = 1.25
Y_D = Y_E + 1
Y_C = Y_D + 1
Y_B = Y_C + 1
Y_A = Y_B + 1
X_NAV = 15.5
X_PAD = 19.0


def _special(kid, x, y, label, code, w=1.0, h=1.0, alt_codes=(), note="", kind="special"):
    return PhysKey(kid, x, y, w, h, kind=kind, label=label, code=code, alt_codes=tuple(alt_codes), note=note)


def _modifier(kid, x, y, label, w=1.0):
    return PhysKey(kid, x, y, w, 1.0, kind="modifier", label=label)


def _chars(row: str, entries, x0: float, y: float, dead: set) -> list[PhysKey]:
    out = []
    for i, (b, s, g) in enumerate(entries):
        kind = "dead" if (row, i) in dead else "char"
        label = (b or "").upper() if b and b.isalpha() and len(b) == 1 else (b or "")
        out.append(PhysKey(f"{row}{i:02d}", x0 + i, y, 1.0, 1.0, kind=kind, label=label,
                           base=b, shift=s, altgr=g,
                           note="Touche morte : le caractère n'est envoyé qu'après une seconde frappe."
                           if kind == "dead" else ""))
    return out


def _common_keys(has_altgr: bool) -> list[PhysKey]:
    k: list[PhysKey] = []
    k.append(_special("ESC", 0, Y_F, "Échap", 27))
    fx = [2, 3, 4, 5, 6.5, 7.5, 8.5, 9.5, 11, 12, 13, 14]
    for i, x in enumerate(fx, start=1):
        k.append(_special(f"F{i}", x, Y_F, f"F{i}", 256 + i))
    k.append(_modifier("PRTSC", X_NAV, Y_F, "Impr"))
    k.append(_modifier("SCRLK", X_NAV + 1, Y_F, "Arrêt défil"))
    k.append(_modifier("PAUSE", X_NAV + 2, Y_F, "Pause"))
    # bloc de navigation
    k.append(_special("INS", X_NAV, Y_E, "Inser", 364))
    k.append(_special("HOME", X_NAV + 1, Y_E, "Origine", 362))
    k.append(_special("PGUP", X_NAV + 2, Y_E, "Pg préc", 360))
    k.append(_special("DEL", X_NAV, Y_D, "Suppr", 127))
    k.append(_special("END", X_NAV + 1, Y_D, "Fin", 363))
    k.append(_special("PGDN", X_NAV + 2, Y_D, "Pg suiv", 361))
    k.append(_special("UP", X_NAV + 1, Y_B, "↑", 357))
    k.append(_special("LEFT", X_NAV, Y_A, "←", 356))
    k.append(_special("DOWN", X_NAV + 1, Y_A, "↓", 359))
    k.append(_special("RIGHT", X_NAV + 2, Y_A, "→", 358))
    # pavé numérique (Verr. Num. actif : les chiffres envoient 0-9)
    k.append(_modifier("NUMLK", X_PAD, Y_E, "Verr Num"))
    k.append(_special("KPDIV", X_PAD + 1, Y_E, "/", 47, kind="numpad"))
    k.append(_special("KPMUL", X_PAD + 2, Y_E, "*", 42, kind="numpad"))
    k.append(_special("KPSUB", X_PAD + 3, Y_E, "-", 45, kind="numpad"))
    k.append(_special("KP7", X_PAD, Y_D, "7", 55, kind="numpad"))
    k.append(_special("KP8", X_PAD + 1, Y_D, "8", 56, kind="numpad"))
    k.append(_special("KP9", X_PAD + 2, Y_D, "9", 57, kind="numpad"))
    k.append(_special("KPADD", X_PAD + 3, Y_D, "+", 43, h=2.0, kind="numpad"))
    k.append(_special("KP4", X_PAD, Y_C, "4", 52, kind="numpad"))
    k.append(_special("KP5", X_PAD + 1, Y_C, "5", 53, alt_codes=(309,), kind="numpad",
                      note="Sans Verr. Num., cette touche envoie le code 309."))
    k.append(_special("KP6", X_PAD + 2, Y_C, "6", 54, kind="numpad"))
    k.append(_special("KP1", X_PAD, Y_B, "1", 49, kind="numpad"))
    k.append(_special("KP2", X_PAD + 1, Y_B, "2", 50, kind="numpad"))
    k.append(_special("KP3", X_PAD + 2, Y_B, "3", 51, kind="numpad"))
    k.append(_special("KPENT", X_PAD + 3, Y_B, "Entrée", 269, h=2.0, kind="numpad"))
    k.append(_special("KP0", X_PAD, Y_A, "0", 48, w=2.0, kind="numpad"))
    k.append(_special("KPDOT", X_PAD + 2, Y_A, ".", 46, kind="numpad"))
    # rangée du bas
    right_alt = "AltGr" if has_altgr else "Alt"
    x = 0.0
    for kid, label, w in [("LCTRL", "Ctrl", 1.25), ("LWIN", "Win", 1.25), ("LALT", "Alt", 1.25)]:
        k.append(_modifier(kid, x, Y_A, label, w))
        x += w
    k.append(_special("SPACE", x, Y_A, "Espace", 32, w=6.25))
    x += 6.25
    for kid, label, w in [("RALT", right_alt, 1.25), ("RWIN", "Win", 1.25), ("MENU", "Menu", 1.25),
                          ("RCTRL", "Ctrl", 1.25)]:
        k.append(_modifier(kid, x, Y_A, label, w))
        x += w
    return k


def _build(lid: str, name: str, variant: str, table: dict, dead: set, has_altgr: bool) -> Layout:
    keys = _common_keys(has_altgr)
    keys += _chars("E", table["E"], 0, Y_E, dead)
    keys.append(_special("BKSP", 13, Y_E, "⟵ Retour", 8, w=2.0))
    keys.append(_special("TAB", 0, Y_D, "Tab ⇥", 9, w=1.5))
    keys += _chars("D", table["D"], 1.5, Y_D, dead)
    keys.append(_modifier("CAPS", 0, Y_C, "Verr Maj", 1.75))
    keys += _chars("C", table["C"], 1.75, Y_C, dead)
    if variant == "iso":
        keys.append(PhysKey("ENTER", 13.5, Y_D, 1.5, 2.0, kind="special", label="Entrée ↵",
                            code=13, alt_codes=(10,), shape="iso_enter"))
        keys.append(_modifier("LSHIFT", 0, Y_B, "⇧ Maj", 1.25))
        keys += _chars("B", table["B"], 1.25, Y_B, dead)
        keys.append(_modifier("RSHIFT", 1.25 + len(table["B"]), Y_B, "⇧ Maj",
                              15 - 1.25 - len(table["B"])))
    else:
        keys.append(_special("ENTER", 1.75 + len(table["C"]), Y_C, "Entrée ↵", 13,
                             w=15 - 1.75 - len(table["C"]), alt_codes=(10,)))
        keys.append(_modifier("LSHIFT", 0, Y_B, "⇧ Maj", 2.25))
        keys += _chars("B", table["B"], 2.25, Y_B, dead)
        keys.append(_modifier("RSHIFT", 2.25 + len(table["B"]), Y_B, "⇧ Maj",
                              15 - 2.25 - len(table["B"])))
    # Dernière touche de la rangée D en ANSI : 1,5 unité
    if variant == "ansi":
        for k in keys:
            if k.id == f"D{len(table['D']) - 1:02d}":
                k.w = 1.5
    return Layout(lid, name, variant, has_altgr, keys)


def builtin_layouts() -> list[Layout]:
    return [
        _build("azerty_fr", "AZERTY (France)", "iso", _AZERTY_FR, _AZERTY_DEAD, True),
        _build("qwerty_us", "QWERTY (États-Unis)", "ansi", _QWERTY_US, set(), False),
        _build("qwerty_uk", "QWERTY (Royaume-Uni)", "iso", _QWERTY_UK, set(), True),
        _build("qwertz_de", "QWERTZ (Allemagne)", "iso", _QWERTZ_DE, _QWERTZ_DEAD, True),
    ]


def load_user_layouts(folder: Path) -> list[Layout]:
    """Charge des dispositions JSON : même format que les tables ci-dessus.

    Exemple ::

        {"id": "azerty_be", "name": "AZERTY (Belgique)", "variant": "iso",
         "has_altgr": true,
         "rows": {"E": [["²", "³", null], ...], "D": [...], "C": [...], "B": [...]},
         "dead": [["D", 10]]}
    """
    out: list[Layout] = []
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            rows = {r: [tuple(e) for e in data["rows"][r]] for r in "EDCB"}
            dead = {(r, int(i)) for r, i in data.get("dead", [])}
            out.append(_build(data["id"], data["name"], data.get("variant", "iso"), rows, dead,
                              bool(data.get("has_altgr", True))))
        except Exception:  # fichier invalide : ignoré
            continue
    return out


def detect_system_layout() -> str:
    """Devine la disposition à partir de la langue du clavier Windows."""
    try:
        import ctypes

        hkl = ctypes.windll.user32.GetKeyboardLayout(0)
        lang = hkl & 0xFFFF
    except Exception:
        return "azerty_fr"
    primary = lang & 0x3FF
    if primary == 0x0C:  # français
        return "qwerty_us" if lang == 0x0C0C else "azerty_fr"  # fr-CA utilise un QWERTY
    if primary == 0x07:
        return "qwertz_de"
    if lang == 0x0809:
        return "qwerty_uk"
    return "qwerty_us"
