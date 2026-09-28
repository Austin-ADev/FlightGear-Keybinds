"""FlightGear keyboard layout model.

Un *slot* correspond à une touche (code FlightGear) combinée à un masque de
modificateurs.  Chaque slot contient les bindings d'appui et de relâchement
(``mod-up``).  La résolution d'une frappe reproduit
``FGKeyboardInput::_find_key_bindings`` (repli sans Ctrl/Alt, sans Maj pour
les majuscules et la ponctuation...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

from .bindings import (
    MOD_ALT,
    MOD_CTRL,
    MOD_RELEASED,
    MOD_SHIFT,
    MOD_TAGS,
    describe_bindings,
    is_null,
    mask_prefix,
)
from .props import PNode


@dataclass
class BindingRef:
    node: PNode
    path: tuple[str, ...]  # chemin des éléments mod-* sous <key>
    origin: str  # phase de la dernière contribution : "global", "aircraft"...

    @property
    def null(self) -> bool:
        return is_null(self.node)


@dataclass
class Slot:
    code: int
    mask: int  # sans le bit MOD_RELEASED
    press: list[BindingRef] = field(default_factory=list)
    release: list[BindingRef] = field(default_factory=list)
    desc: Optional[str] = None
    desc_origin: Optional[str] = None

    @property
    def live_press(self) -> list[BindingRef]:
        return [b for b in self.press if not b.null]

    @property
    def live_release(self) -> list[BindingRef]:
        return [b for b in self.release if not b.null]

    @property
    def is_bound(self) -> bool:
        return bool(self.live_press or self.live_release)

    @property
    def is_disabled(self) -> bool:
        """Des bindings existent mais ils sont tous neutralisés (commande null)."""
        return bool(self.press or self.release) and not self.is_bound

    @property
    def origin(self) -> str:
        live = self.live_press + self.live_release
        if not live:
            refs = self.press + self.release
            if any(r.origin != "global" for r in refs):
                return "disabled"
            return "none"
        if any(b.origin != "global" for b in live):
            return "aircraft"
        return "global"

    def description(self) -> str:
        if not self.is_bound:
            return ""
        d = describe_bindings([b.node for b in self.press], self.desc)
        if not d:
            d = "Au relâchement : " + describe_bindings([b.node for b in self.release])
        return d


@dataclass
class KeyDef:
    code: int
    name: Optional[str]
    desc: Optional[str]
    repeatable: bool
    node: PNode
    slots: dict[int, Slot] = field(default_factory=dict)


@dataclass
class Resolved:
    """Résultat de la résolution d'une frappe."""

    code: int
    requested_mask: int
    used_mask: int
    slot: Optional[Slot]

    @property
    def fallback(self) -> bool:
        """Vrai si FlightGear a dû ignorer Ctrl/Alt pour trouver une action.

        Le retrait de Maj pour une majuscule ou une ponctuation n'est pas un repli :
        c'est la façon normale de produire ce caractère.
        """
        both = MOD_CTRL | MOD_ALT
        req, used = self.requested_mask, self.used_mask
        if 1 <= self.code <= 26:
            # les codes de contrôle (Ctrl+A = 1...) contiennent déjà le Ctrl
            req &= ~MOD_CTRL
            used &= ~MOD_CTRL
        return (used & both) != (req & both)

    @property
    def is_bound(self) -> bool:
        return self.slot is not None and bool(self.slot.live_press)


def _isupper(c: int) -> bool:
    return 65 <= c <= 90


def _ispunct(c: int) -> bool:
    return 33 <= c <= 47 or 58 <= c <= 64 or 91 <= c <= 96 or 123 <= c <= 126


def _iscntrl(c: int) -> bool:
    return c < 32 or c == 127


class KeyboardConfig:
    def __init__(self, node: Optional[PNode] = None):
        self.keys: dict[int, KeyDef] = {}
        self.node = node
        if node is not None:
            self._parse(node)

    # -- lecture ----------------------------------------------------------
    def _parse(self, kb: PNode) -> None:
        for key in kb.children("key"):
            kd = KeyDef(
                code=key.index,
                name=key.text("name") or None,
                desc=key.text("desc") or None,
                repeatable=key.get_bool("repeatable"),
                node=key,
            )
            self._read(key, 0, (), kd)
            # La description de premier niveau décrit le slot sans modificateur
            s0 = kd.slots.get(0)
            if s0 is not None and kd.desc and not s0.desc:
                s0.desc = kd.desc
                dn = key.node("desc")
                s0.desc_origin = _origin(dn) if dn is not None else None
            self.keys[kd.code] = kd

    def _read(self, node: PNode, mask: int, path: tuple[str, ...], kd: KeyDef) -> None:
        base = mask & ~MOD_RELEASED
        bindings = node.children("binding")
        slot = kd.slots.get(base)
        if slot is None and (bindings or node.child("desc") is not None and path):
            slot = kd.slots[base] = Slot(kd.code, base)
        for b in bindings:
            ref = BindingRef(b, path, _origin(b))
            (slot.release if mask & MOD_RELEASED else slot.press).append(ref)
        if path and not (mask & MOD_RELEASED):
            dn = node.child("desc")
            if dn is not None and slot is not None and not slot.desc:
                slot.desc = (dn.value or "").strip() or None
                slot.desc_origin = _origin(dn)
        for tag, bit in MOD_TAGS:
            c = node.child(tag)
            if c is not None:
                self._read(c, mask | bit, path + (tag,), kd)

    # -- accès -----------------------------------------------------------
    def slot(self, code: int, mask: int) -> Optional[Slot]:
        kd = self.keys.get(code)
        return kd.slots.get(mask) if kd else None

    def slots(self) -> Iterator[Slot]:
        for code in sorted(self.keys):
            kd = self.keys[code]
            for m in sorted(kd.slots):
                yield kd.slots[m]

    def bound_slots(self) -> Iterator[Slot]:
        return (s for s in self.slots() if s.is_bound)

    def _list(self, code: int, mask: int) -> list[BindingRef]:
        s = self.slot(code, mask & ~MOD_RELEASED)
        if s is None:
            return []
        return s.release if mask & MOD_RELEASED else s.press

    def find(self, code: int, mask: int) -> tuple[list[BindingRef], int]:
        """Réplique de FGKeyboardInput::_find_key_bindings."""
        kc = code & 0xFF
        b = self._list(code, mask)
        if b:
            return b, mask
        if mask & (MOD_CTRL | MOD_ALT):
            return self.find(code, mask & ~(MOD_CTRL | MOD_ALT))
        if (mask & MOD_CTRL) and _iscntrl(kc):  # pragma: no cover - branche morte dans FG
            return self.find(code, mask & ~MOD_CTRL)
        if (mask & MOD_SHIFT) and (_isupper(kc) or _ispunct(kc)):
            return self.find(code, mask & ~MOD_SHIFT)
        if (mask & MOD_ALT) and 128 <= code < 256:  # pragma: no cover
            return self.find(code, mask & ~MOD_ALT)
        return b, mask

    def resolve(self, code: int, mask: int) -> Resolved:
        _, used = self.find(code, mask)
        return Resolved(code, mask, used, self.slot(code, used & ~MOD_RELEASED))

    def fix_descriptions(self, base: "KeyboardConfig") -> None:
        """Corrige les descriptions héritées de façon trompeuse par la fusion.

        Beaucoup d'aéronefs placent ``<desc>`` au niveau de la touche alors que leur
        binding est sous ``<mod-alt>`` : la fusion remplace alors la description
        de la touche sans modificateur, dont l'action (globale) n'a pas changé.
        On restaure la description globale et on rattache celle de l'aéronef aux
        combinaisons qu'il définit réellement.
        """
        for code, kd in self.keys.items():
            s0 = kd.slots.get(0)
            key_desc_aircraft = None
            if s0 is not None and s0.desc_origin not in (None, "global"):
                live = s0.live_press + s0.live_release
                if live and all(b.origin == "global" for b in live):
                    key_desc_aircraft = s0.desc
                    b0 = base.slot(code, 0)
                    s0.desc = b0.desc if b0 is not None else None
                    s0.desc_origin = "global"
            elif s0 is None and kd.desc:
                key_desc_aircraft = kd.desc
            if key_desc_aircraft:
                for m, s in kd.slots.items():
                    if m and not s.desc and s.origin == "aircraft":
                        s.desc = key_desc_aircraft
                        s.desc_origin = "aircraft"

    def repeatable(self, code: int) -> bool:
        kd = self.keys.get(code)
        return bool(kd and kd.repeatable)


def _origin(node: PNode) -> str:
    s = node.latest_source()
    return s.phase if s else "global"


# ---------------------------------------------------------------------------
# Libellés des touches
# ---------------------------------------------------------------------------

SPECIAL_KEY_NAMES: dict[int, str] = {
    8: "Retour arrière",
    9: "Tab",
    10: "Entrée (LF)",
    13: "Entrée",
    27: "Échap",
    32: "Espace",
    127: "Suppr",
    269: "Entrée (pavé num.)",
    309: "5 (pavé num. sans Verr.Num)",
    356: "←",
    357: "↑",
    358: "→",
    359: "↓",
    360: "Page préc.",
    361: "Page suiv.",
    362: "Origine",
    363: "Fin",
    364: "Inser",
}
for _i in range(1, 13):
    SPECIAL_KEY_NAMES[256 + _i] = f"F{_i}"


def code_label(code: int) -> str:
    if code in SPECIAL_KEY_NAMES:
        return SPECIAL_KEY_NAMES[code]
    if 1 <= code <= 26:
        return "Ctrl+" + chr(64 + code)
    if 33 <= code < 256:
        return chr(code)
    return f"#{code}"


def combo_label(code: int, mask: int) -> str:
    """Libellé lisible d'une combinaison (code FlightGear + masque)."""
    if 1 <= code <= 26 and code not in SPECIAL_KEY_NAMES:
        # Les codes de contrôle portent déjà le Ctrl
        return mask_prefix(mask | MOD_CTRL) + chr(64 + code)
    if 65 <= code <= 90:
        return mask_prefix(mask | MOD_SHIFT) + chr(code)
    if 97 <= code <= 122:
        return mask_prefix(mask) + chr(code).upper()
    return mask_prefix(mask) + code_label(code)
