# FGKeybinds

Gestionnaire graphique des raccourcis clavier et des périphériques de jeu (joystick, HOTAS, yoke, palonnier, manette des gaz…) pour **FlightGear**, sans avoir à éditer de fichiers XML à la main.

> **Version 0.1.1 bêta** — Windows 10/11. Faites une sauvegarde de vos configurations personnelles avant de commencer (l'outil crée aussi ses propres sauvegardes, voir plus bas).

## Fonctionnalités

- **Clavier visuel** AZERTY (France) et QWERTY (États-Unis), plus QWERTY Royaume-Uni et QWERTZ Allemagne. Chaque touche affiche son action pour chaque combinaison de modificateurs (Normal, Maj, Ctrl, Alt, AltGr, Ctrl+Maj, Alt+Maj). La disposition du clavier Windows est détectée automatiquement.
- **Fidèle au comportement de FlightGear** : l'outil reproduit la façon dont FlightGear fusionne les fichiers (global, aéronef, fichiers inclus) et résout les frappes. Exemple : sur AZERTY, `Maj+&` envoie `1` avec Maj, et `AltGr+(` retombe sur l'action de `[`.
- **Périphériques** : détection des périphériques branchés (le même nom que celui lu par FlightGear), affichage en direct des axes et des boutons, et de la configuration réellement utilisée par FlightGear. L'outil n'est lié à aucun modèle : il lit toute la bibliothèque de FlightGear (Saitek/Logitech X52, Pro Flight Yoke et palonniers, Thrustmaster T.16000M, TWCS, Warthog, T-Rudder, CH, Honeycomb…) et crée une configuration pour tout périphérique inconnu.
- **Touches et commandes illuminées en direct** : dans l'onglet Clavier, la touche que vous pressez s'illumine et son action s'affiche. En maintenant Maj, Ctrl, Alt ou AltGr, le clavier dessiné passe sur la couche correspondante. Le repérage se fait par position physique, quelle que soit la disposition. Dans l'onglet Périphériques, le bouton pressé s'illumine et l'axe en mouvement est mis en évidence. Si l'option est activée, l'appareil utilisé s'affiche automatiquement quand plusieurs sont branchés.
- **Recherche** par touche (`ctrl+a`, `maj+F1`, ou capture directe d'une touche) ou par action (`train`, `volets`, `/controls/flight/flaps`…), sur le clavier et les périphériques.
- **Aéronefs** : liste de la bibliothèque d'aéronefs, raccourcis propres à chaque aéronef (ajouts, remplacements, désactivations), **export / import de profils** (`.fgkb`, ou fichier clavier XML de FlightGear) et **copie de raccourcis d'un aéronef vers un autre**.
- **Actions non assignées** : actions courantes de FlightGear (train, volets, trims, pilote automatique, vues, éclairage…) qui n'ont ni touche ni bouton, et liste des combinaisons libres. Assignation en deux clics.
- **Courbes de sensibilité** : zone morte et expo par axe, avec aperçu de la courbe et de la position de l'axe en direct.

## Installation

1. Téléchargez `FGKeybinds.exe` depuis la page [Releases](https://github.com/itaalh/FlightGear-Keybinds/releases).
2. Lancez-le : aucune installation n'est nécessaire.

FGKeybinds retrouve FlightGear à partir des réglages du lanceur et de son journal. Si les dossiers ne sont pas trouvés, indiquez-les dans **Paramètres** : `FG_ROOT` (le dossier qui contient `keyboard.xml`), `FG_HOME` (`%APPDATA%\flightgear.org` par défaut) et vos dossiers d'aéronefs supplémentaires.

**Redémarrez FlightGear** pour que les modifications soient prises en compte.

## Où sont écrites les modifications ?

| Ce que vous modifiez | Fichier modifié |
|---|---|
| Raccourcis globaux | `FG_ROOT/keyboard.xml` |
| Raccourcis d'un aéronef | le fichier clavier de l'aéronef (par exemple `c172p-keyboard.xml`), sinon son `-set.xml` |
| Périphériques et courbes | une copie personnelle dans `FG_HOME/Input/Joysticks/FGKeybinds/`, prioritaire sur les fichiers fournis avec FlightGear (les originaux ne sont jamais modifiés) |

Sécurités :

- Avant la première modification d'un fichier, l'original est copié à côté (`*.fgkb-backup`). Le menu **Sauvegardes** permet de restaurer l'original d'un seul clic.
- Les commentaires et la mise en forme des fichiers XML sont conservés.
- Une mise à jour de FlightGear peut remplacer `keyboard.xml`. FGKeybinds mémorise vos modifications globales et propose de les réappliquer au démarrage.
- Pour modifier une touche héritée du clavier global dans un aéronef, FGKeybinds neutralise l'action globale (commande `null`) au lieu de la fusionner. Ainsi, aucun paramètre hérité (condition, pas, bornes) ne se mélange à la nouvelle action.

## Courbes : zone morte et expo

- **Zone morte** : paramètre natif `<dead-band>` de FlightGear. Le signal est ignoré sous le seuil, puis le reste de la course est redimensionné.
- **Expo** : FlightGear n'a pas d'expo native (`power` n'accepte que des entiers). FGKeybinds l'ajoute au début du binding de l'axe sous forme d'un petit script Nasal, `sortie = (1−e)·x + e·x³`. Un binding `property-scale` est alors converti en script équivalent, et ses paramètres d'origine sont conservés dans un commentaire `# FGKB-SCALE`. En ramenant l'expo à 0, vous retrouvez le binding d'origine.

## Limites connues (bêta)

- Windows uniquement (la détection des périphériques utilise l'API `winmm`, comme FlightGear sous Windows).
- Les périphériques gérés par l'entrée « HID/événements » de FlightGear (`Input/Event`) ne sont pas encore pris en charge : seuls les joysticks classiques (`Input/Joysticks`) le sont.
- Le catalogue d'actions utilise les propriétés génériques de FlightGear. Certains aéronefs ont leurs propres commandes : elles apparaissent dans l'onglet Aéronefs mais pas dans « Non assignées ».
- La combinaison clavier ↔ caractère suit la disposition choisie. Certaines combinaisons Ctrl/Alt peuvent se comporter différemment selon la version d'OpenSceneGraph.

Personnalisation avancée (dans `%APPDATA%\FGKeybinds\`) :

- `actions.json` : actions supplémentaires pour le catalogue (même format que `fgkeybinds/data/actions.json`) ;
- `layouts\*.json` : dispositions de clavier supplémentaires (voir `fgkeybinds/core/layouts.py`).

## Développement

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest            # tests
python FGKeybinds.pyw       # lancer depuis les sources
powershell -ExecutionPolicy Bypass -File build.ps1   # construit dist\FGKeybinds.exe
```

Organisation du code :

- `fgkeybinds/core` : logique métier, sans interface graphique. Contient la lecture des PropertyList avec la sémantique de SimGear, le modèle clavier et sa résolution, les joysticks, les courbes, l'écriture XML, les profils et la recherche.
- `fgkeybinds/ui` : interface PySide6.
- `tests` : tests unitaires (fusion, résolution des touches, écriture, courbes, profils).
