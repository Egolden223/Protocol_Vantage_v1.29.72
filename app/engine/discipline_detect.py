"""
discipline_detect.py — Détection robuste de discipline (v1.29.33)

Priorité (spécifique → générique) :
  STEEPLE > HAIES > TROT_MONTE > TROT_ATTELE > PLAT

Signaux : libellé course, URL, hippodrome + distance, musique partants,
texte collecté. Corrige le défaut historique « PLAT » quand le texte
contient Haies/Steeple (cas Auteuil Prix Grandlieu 26/09/2026).

Sources recherche 2026 :
  - Favori Top5 : trot attelé ~72 %, plat ~59 %, haies ~59 %, steeple ~54 %
  - Obstacle : terrain, expérience saut, jockey spécialiste, Auteuil
  - Trot : recul, ferrure, driver, attelé ≠ monté
  - Plat : poids/valeur handicap, corde, distance
"""
from __future__ import annotations
import re
from typing import Any, Optional, Tuple, List

from app.models import Discipline, RaceContext

# Ordre de priorité : le premier match gagne
_PATTERNS: List[Tuple[re.Pattern, Discipline]] = [
    (re.compile(r"steeple[\s\-]?chase|\bsteeple\b|\bstp\b", re.I), Discipline.STEEPLE),
    (re.compile(r"\bhaies?\b|\bhurdl", re.I), Discipline.HAIES),
    (re.compile(r"trot\s*mont[ée]|\bmonté\b|\bmonte\b(?!\s*carlo)", re.I), Discipline.TROT_MONTE),
    (re.compile(r"trot\s*attel[ée]|\battel[ée]\b|\bsulky\b|\bdriver\b", re.I), Discipline.TROT_ATTELE),
    (re.compile(r"\bcross\b|cross-country", re.I), Discipline.STEEPLE),  # assimilé obstacle lourd
    (re.compile(r"\bplat\b|\bflat\b|\bgalop\b(?!.*haie)", re.I), Discipline.PLAT),
]

# Hippodromes quasi exclusivement obstacle (France)
_HIPPO_OBSTACLE = {
    "auteuil", "compiegne", "compiègne", "enghien", "pau",
    "cagnes", "cagnes-sur-mer", "clairefontaine",  # aussi plat mais souvent obstacle
}
_HIPPO_TROT = {
    "vincennes", "cabourg", "caen", "laval", "argentan", "la capelle",
    "la_capelle", "feurs", "meslay", "chartres", "amiens",
}


def _text_blob(race: Optional[RaceContext] = None, extra: str = "") -> str:
    parts = [extra or ""]
    if race is not None:
        for attr in ("nom_course", "url_source", "hippodrome", "commentaire_course"):
            v = getattr(race, attr, None)
            if v:
                parts.append(str(v))
        # URL des sources
        for src in getattr(race, "sources_urls", None) or []:
            parts.append(str(src))
        # musique agrégée (lettres h/s/a/m)
        chevaux = getattr(race, "chevaux", None) or []
        mus = " ".join(str(getattr(c, "musique", "") or "") for c in chevaux[:18])
        parts.append(mus)
    return " | ".join(parts)


def detect_discipline(
    text: str = "",
    *,
    race: Optional[RaceContext] = None,
    hippodrome: str = "",
    distance_m: Optional[float] = None,
    current: Optional[Discipline] = None,
) -> Tuple[Discipline, str]:
    """Retourne (discipline, flag_raison)."""
    blob = _text_blob(race, text)
    hippo = (hippodrome or (getattr(race, "hippodrome", None) or "")).lower().strip()
    dist = distance_m if distance_m is not None else getattr(race, "distance_m", None)

    for pat, disc in _PATTERNS:
        if pat.search(blob):
            return disc, f"DISC_DETECT_TEXT_{disc.value}"

    # v1.29.45 : une discipline OBSTACLE déjà précise (HAIES ou STEEPLE, fournie par les sources) n'est
    # JAMAIS écrasée par une heuristique (avant : tout steeple d'Auteuil >= 3000 m devenait HAIES).
    if current in (Discipline.HAIES, Discipline.STEEPLE):
        return current, "DISC_DETECT_KEEP_OBSTACLE"

    # Heuristique hippodrome + distance
    if any(h in hippo for h in _HIPPO_OBSTACLE):
        if dist and dist >= 3000:
            # Auteuil 3600-6000 = quasi sûr obstacle
            if "auteuil" in hippo:
                return Discipline.HAIES, "DISC_DETECT_AUTEUIL_DIST"
        if "auteuil" in hippo and (not dist or dist >= 2800):
            return Discipline.HAIES, "DISC_DETECT_AUTEUIL"

    if any(h in hippo for h in _HIPPO_TROT) and (not dist or dist >= 2000):
        # défaut trot provincial si pas de signal plat
        if "plat" not in blob.lower() and "haie" not in blob.lower():
            return Discipline.TROT_ATTELE, "DISC_DETECT_HIPPO_TROT"

    # Musique dominante h/s vs a/m vs p
    if race and getattr(race, "chevaux", None):
        mus = " ".join(str(getattr(c, "musique", "") or "") for c in race.chevaux)
        n_h = len(re.findall(r"\d+h", mus, re.I))
        n_s = len(re.findall(r"\d+s", mus, re.I))
        n_a = len(re.findall(r"\d+a", mus, re.I))
        n_m = len(re.findall(r"\d+m", mus, re.I))
        if n_h + n_s >= 4 and (n_h + n_s) > (n_a + n_m):
            return (Discipline.STEEPLE if n_s > n_h else Discipline.HAIES), "DISC_DETECT_MUSIQUE_OBS"
        if n_a + n_m >= 4 and (n_a + n_m) > (n_h + n_s):
            return (Discipline.TROT_MONTE if n_m > n_a else Discipline.TROT_ATTELE), "DISC_DETECT_MUSIQUE_TROT"

    if current is not None and current != Discipline.PLAT:
        return current, "DISC_DETECT_KEEP"

    if current == Discipline.PLAT:
        return Discipline.PLAT, "DISC_DETECT_DEFAULT_PLAT"

    return Discipline.PLAT, "DISC_DETECT_FALLBACK_PLAT"


def ensure_race_discipline(race: RaceContext, extra_text: str = "") -> List[str]:
    """Corrige race.discipline in-place si sous-détectée. Retourne flags."""
    flags: List[str] = []
    cur = getattr(race, "discipline", None)
    disc, reason = detect_discipline(
        extra_text,
        race=race,
        hippodrome=getattr(race, "hippodrome", "") or "",
        distance_m=getattr(race, "distance_m", None),
        current=cur,
    )
    if cur != disc:
        flags.append(f"DISC_CORRECTED_{getattr(cur, 'value', cur)}_TO_{disc.value}")
        race.discipline = disc
    flags.append(reason)
    return flags
