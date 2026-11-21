"""
classements.py -- Rang national (1 = meilleur taux de victoire) d'un driver ou d'un entraîneur,
lu dans data/classements/drivers.json et entraineurs.json. Aucun appel réseau.

v1.29.63 : le rapport de vérification de la collecte (55 courses) a montré que B11 (changement de driver), B12 (entraîneur Top
national), le classement driver de catalog_rules / SSFO et `trainer_stats.classement_national` ne pouvaient JAMAIS se déclencher :
les deux fichiers n'étaient ni livrés ni construits (les scripts de construction ne sont pas dans le dépôt). Désormais :
  * si un fichier est absent, il est CONSTRUIT automatiquement, hors ligne, à partir du corpus open-pmu-api déjà mis en cache
    par supra_phase2 (data/pmu_historique_cache/*.json : jockey, entraîneur, ordre d'arrivée de chaque course) ;
  * les noms sont normalisés (accents, points, casse, ordre des mots) à la construction ET à la lecture ;
  * `diagnostic()` expose l'état (nombre d'entrées) : repris dans json_output["diagnostic_donnees"] et dans l'export d'analyse.
Ligne de commande : python -m app.engine.classements  (reconstruit les deux fichiers depuis le cache).
"""
from __future__ import annotations
import json
import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

logger = logging.getLogger("vantage.engine.classements")

_DOSSIER = Path(os.environ.get("VANTAGE_CLASSEMENTS_DIR", "data/classements"))       # Render : /data/classements (disque persistant)
_FICHIERS = {"drivers": _DOSSIER / "drivers.json", "entraineurs": _DOSSIER / "entraineurs.json"}
_CACHE_CORPUS = Path(os.environ.get("VANTAGE_CORPUS_DIR", "data/pmu_historique_cache"))
_MIN_COURSES_CLASSEMENT = 30      # montes minimales pour figurer au classement (taux trop bruité en dessous)
_caches: Dict[str, Dict[str, dict]] = {}
_construction_tentee: Dict[str, bool] = {}


def normaliser_nom(nom: Optional[str]) -> str:
    """'J. Dupont' / 'DUPONT J' / 'Dupont, J.' -> 'DUPONT J' (accents retirés, ponctuation retirée, mots triés)."""
    if not nom:
        return ""
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode("ascii").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(sorted(t for t in s.split() if t))


def construire_classement(courses_raw: Iterable[dict], champ_nom: str) -> Dict[str, dict]:
    """Classement par taux de victoire (puis taux Top5) sur les courses brutes open-pmu-api ; `champ_nom` = nom_jockey | nom_entraineur."""
    montes: Dict[str, int] = defaultdict(int); victoires: Dict[str, int] = defaultdict(int); top5: Dict[str, int] = defaultdict(int)
    noms: Dict[str, str] = {}
    vues = set()
    for c in courses_raw:
        arrivee = [str(x) for x in (c.get("arrivee") or [])]
        details = c.get("arrivee_details") or {}
        cle_course = (c.get("date"), c.get("lieu"), c.get("r/c"), c.get("prix"))
        if not arrivee or not details or cle_course in vues:
            continue
        vues.add(cle_course)
        for numero, d in details.items():
            k = normaliser_nom((d or {}).get(champ_nom))
            if not k:
                continue
            noms.setdefault(k, str(d.get(champ_nom)))
            montes[k] += 1
            if arrivee and str(numero) == arrivee[0]:
                victoires[k] += 1
            if str(numero) in arrivee[:5]:
                top5[k] += 1
    eligibles = [k for k, n in montes.items() if n >= _MIN_COURSES_CLASSEMENT]
    ordre = sorted(eligibles, key=lambda k: (-victoires[k] / montes[k], -top5[k] / montes[k], -montes[k], k))
    return {k: {"rang": i + 1, "taux_victoire": round(victoires[k] / montes[k], 4), "taux_top5": round(top5[k] / montes[k], 4),
                "courses": montes[k], "nom": noms[k]} for i, k in enumerate(ordre)}


def _courses_du_cache() -> list:
    out: list = []
    if not _CACHE_CORPUS.exists():
        return out
    for f in sorted(_CACHE_CORPUS.glob("*.json")):
        try:
            out.extend(json.loads(f.read_text(encoding="utf-8")).get("courses") or [])
        except Exception as e:  # noqa: BLE001
            logger.warning("Cache corpus illisible %s : %s", f, e)
    return out


def reconstruire(cle: Optional[str] = None) -> Dict[str, int]:
    """(Re)construit data/classements/<cle>.json depuis le cache du corpus. Retourne {cle: nb d'entrées}."""
    courses = _courses_du_cache()
    res: Dict[str, int] = {}
    for k, champ in (("drivers", "nom_jockey"), ("entraineurs", "nom_entraineur")):
        if cle and k != cle:
            continue
        cl = construire_classement(courses, champ)
        if not cl:
            res[k] = 0
            continue
        f = _FICHIERS[k]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"genere": datetime.now().isoformat(), "source": "open-pmu-api (cache supra_phase2)",
                                 "n_courses_corpus": len(courses), "min_montes": _MIN_COURSES_CLASSEMENT, "classement": cl},
                                ensure_ascii=False), encoding="utf-8")
        _caches.pop(k, None)
        res[k] = len(cl)
    return res


def _charger(cle: str) -> Dict[str, dict]:
    if cle in _caches:
        return _caches[cle]
    f = _FICHIERS[cle]
    auto = os.environ.get("VANTAGE_CLASSEMENTS_AUTO", "1").strip().lower() not in ("0", "false", "non", "off")   # coupe-circuit pour comparer avec / sans
    if auto and not f.exists() and not _construction_tentee.get(cle):
        _construction_tentee[cle] = True
        try:
            n = reconstruire(cle).get(cle, 0)
            logger.info("Classement %s construit automatiquement depuis le cache du corpus : %d entrées", cle, n)
        except Exception as e:  # noqa: BLE001 -- ne jamais faire échouer le pipeline
            logger.warning("Construction automatique du classement %s impossible : %s", cle, e)
    data: Dict[str, dict] = {}
    if not f.exists():
        logger.warning("%s absent (corpus open-pmu-api pas encore en cache) : B11/B12 et classements driver/entraîneur INACTIFS "
                       "jusqu'à la prochaine construction (python -m app.engine.classements).", f)
    else:
        try:
            data = json.loads(f.read_text(encoding="utf-8")).get("classement", {})
        except Exception as e:  # noqa: BLE001
            logger.warning("Échec lecture %s : %s", f, e)
    _caches[cle] = data
    return data


def _rang(cle: str, nom: Optional[str]) -> Optional[int]:
    if not nom:
        return None
    d = _charger(cle)
    entree = d.get(normaliser_nom(nom)) or d.get(nom.strip().upper())     # 2e clé : fichiers d'anciens scripts
    return entree["rang"] if entree else None


def get_classement_driver(nom_driver: Optional[str]) -> Optional[int]:
    return _rang("drivers", nom_driver)


def get_classement_entraineur(nom_entraineur: Optional[str]) -> Optional[int]:
    return _rang("entraineurs", nom_entraineur)


def diagnostic() -> Dict[str, int]:
    """État des classements (nombre d'entrées) pour json_output['diagnostic_donnees'] et l'export d'analyse."""
    return {"classements_drivers": len(_charger("drivers")), "classements_entraineurs": len(_charger("entraineurs"))}


if __name__ == "__main__":  # python -m app.engine.classements
    logging.basicConfig(level=logging.INFO)
    print(reconstruire())
