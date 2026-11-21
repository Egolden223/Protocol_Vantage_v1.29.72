"""Normalisation robuste des noms d'hippodromes (25 majeurs FR + Zone-Turf).

Zone-Turf.fr utilise des URL du type :
  /programmes/r1-longchamp-192222.html
  /programmes/r4-chantilly-198860.html
  /programmes/z7-le-croise-laroche-198852.html
  /programmes/r3-salon-de-provence-198857.html

Le slug hippodrome est la partie centrale (sans rN-/zN- ni -id numérique).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple


def _ascii_lower(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


# ---------------------------------------------------------------------------
# 25 hippodromes majeurs (PMU / France Galop / Le Trot — volume & prestige)
# Forme canonique : minuscules, espaces
# ---------------------------------------------------------------------------
TOP25_MAJEURS: List[str] = [
    "vincennes",              # 1  Trot national
    "longchamp",              # 2  Plat / Arc
    "auteuil",                # 3  Obstacle
    "saint cloud",            # 4  Plat
    "chantilly",              # 5  Plat
    "deauville",              # 6  Plat
    "clairefontaine",         # 7  Plat / mixte
    "enghien soisy",          # 8  Trot / obstacle
    "cagnes sur mer",         # 9  Mixte Côte d'Azur
    "maisons laffitte",       # 10 Plat
    "cabourg",                # 11 Trot
    "caen",                   # 12 Trot
    "marseille borely",       # 13 Plat
    "marseille vivaux",       # 14 Trot
    "lyon parilly",           # 15 Plat (Lyon)
    "lyon la soie",           # 16 Trot (Lyon)
    "toulouse",               # 17 Mixte
    "bordeaux le bouscat",    # 18 Mixte
    "pau",                    # 19 Mixte
    "vichy",                  # 20 Mixte
    "compiegne",              # 21 Plat / obstacle
    "fontainebleau",          # 22 Plat
    "nantes",                 # 23 Mixte
    "pornichet",              # 24 Trot / plat
    "le croise laroche",      # 25 Nord — volume PMU
]

# Autres pistes fréquentes PMU (fuzzy + alias, hors top 25 strict)
CANONICAL_EXTRA: List[str] = [
    "laval", "dieppe", "graignes", "argentan", "amiens", "angers",
    "salon de provence", "la teste", "mont de marsan", "strasbourg",
    "nancy", "hyeres", "evreux", "meslay du maine", "le lion d angers",
    "les sables d olonne", "saint malo", "saint galmier", "chateaubriant",
    "beaumont de lomagne", "lisieux", "craon", "vittel", "nice",
    # Ajoutés 17/09/2026 — présents dans liste Quinté UI, absents du catalogue
    "feurs", "mauquenchy", "chartres", "cordemais", "cavaillon",
    "nimes", "reims", "vire", "la capelle", "cherbourg", "agen",
    "le touquet", "le mans",
]

CANONICAL_HIPPODROMES: List[str] = list(dict.fromkeys(TOP25_MAJEURS + CANONICAL_EXTRA))

# ---------------------------------------------------------------------------
# Slugs Zone-Turf observés / attendus (partie centrale de l'URL)
# ---------------------------------------------------------------------------
ZONE_TURF_SLUGS: Dict[str, str] = {
    # slug ZT -> canonique
    "longchamp": "longchamp",
    "paris-longchamp": "longchamp",
    "auteuil": "auteuil",
    "vincennes": "vincennes",
    "paris-vincennes": "vincennes",
    "saint-cloud": "saint cloud",
    "st-cloud": "saint cloud",
    "chantilly": "chantilly",
    "deauville": "deauville",
    "clairefontaine": "clairefontaine",
    "enghien-soisy": "enghien soisy",
    "enghien": "enghien soisy",
    "cagnes-sur-mer": "cagnes sur mer",
    "cagnes": "cagnes sur mer",
    "maisons-laffitte": "maisons laffitte",
    "cabourg": "cabourg",
    "caen": "caen",
    "marseille-borely": "marseille borely",
    "borely": "marseille borely",
    "marseille-vivaux": "marseille vivaux",
    "vivaux": "marseille vivaux",
    "lyon-parilly": "lyon parilly",
    "parilly": "lyon parilly",
    "lyon-la-soie": "lyon la soie",
    "la-soie": "lyon la soie",
    "toulouse": "toulouse",
    "bordeaux-le-bouscat": "bordeaux le bouscat",
    "le-bouscat": "bordeaux le bouscat",
    "pau": "pau",
    "vichy": "vichy",
    "compiegne": "compiegne",
    "fontainebleau": "fontainebleau",
    "nantes": "nantes",
    "pornichet": "pornichet",
    "pornichet-la-baule": "pornichet",
    "le-croise-laroche": "le croise laroche",
    "croise-laroche": "le croise laroche",
    "salon-de-provence": "salon de provence",
    "beaumont-de-lomagne": "beaumont de lomagne",
    "lisieux": "lisieux",
    "laval": "laval",
    "dieppe": "dieppe",
    "graignes": "graignes",
    "argentan": "argentan",
    "amiens": "amiens",
    "angers": "angers",
    "la-teste": "la teste",
    "la-teste-de-buch": "la teste",
    "mont-de-marsan": "mont de marsan",
    "strasbourg": "strasbourg",
    "nancy": "nancy",
    "meslay-du-maine": "meslay du maine",
    "le-lion-d-angers": "le lion d angers",
    "les-sables-d-olonne": "les sables d olonne",
    "feurs": "feurs",
    "mauquenchy": "mauquenchy",
    "chartres": "chartres",
    "cordemais": "cordemais",
    "cavaillon": "cavaillon",
    "nimes": "nimes",
    "reims": "reims",
    "vire": "vire",
    "la-capelle": "la capelle",
    "cherbourg": "cherbourg",
    "agen": "agen",
    "craon": "craon",
    "hyeres": "hyeres",
    "chateaubriant": "chateaubriant",
    "vittel": "vittel",
    "evreux": "evreux",
    "nice": "nice",
    "saint-malo": "saint malo",
    "saint-galmier": "saint galmier",
    "le-mans": "le mans",
    "le-touquet": "le touquet",
}


# Alias saisie utilisateur -> canonique
_ALIASES: Dict[str, str] = {
    "paris longchamp": "longchamp",
    "parislongchamp": "longchamp",
    "longchamps": "longchamp",
    "long champ": "longchamp",
    "hippodrome de longchamp": "longchamp",
    "paris vincennes": "vincennes",
    "parisvincennes": "vincennes",
    "vincenes": "vincennes",
    "vinssennes": "vincennes",
    "vincenne": "vincennes",
    "hippodrome de vincennes": "vincennes",
    "paris auteuil": "auteuil",
    "parisauteuil": "auteuil",
    "st cloud": "saint cloud",
    "stcloud": "saint cloud",
    "saintcloud": "saint cloud",
    "st-cloud": "saint cloud",
    "cagnes": "cagnes sur mer",
    "cagnessurmer": "cagnes sur mer",
    "cagnes surmer": "cagnes sur mer",
    "cote d azur": "cagnes sur mer",
    "enghien": "enghien soisy",
    "enghiensoisy": "enghien soisy",
    "enghien-soisy": "enghien soisy",
    "deaauville": "deauville",
    "dauville": "deauville",
    "claire fontaine": "clairefontaine",
    "lyon paradis": "lyon parilly",  # confusion fréquente
    "lyon-paradis": "lyon parilly",
    "lyonparadis": "lyon parilly",
    "parilly": "lyon parilly",
    "lyon soie": "lyon la soie",
    "lyonlasoie": "lyon la soie",
    "borely": "marseille borely",
    "marseille-borely": "marseille borely",
    "vivaux": "marseille vivaux",
    "maisons laffite": "maisons laffitte",
    "maisons-laffitte": "maisons laffitte",
    "maison laffitte": "maisons laffitte",
    "le bouscat": "bordeaux le bouscat",
    "bordeaux": "bordeaux le bouscat",
    "croise laroche": "le croise laroche",
    "croise-laroche": "le croise laroche",
    "marcq": "le croise laroche",
    "pornichet la baule": "pornichet",
    "la baule": "pornichet",
    "lion d angers": "le lion d angers",
    "les sables": "les sables d olonne",
    "sables d olonne": "les sables d olonne",
    "meslay": "meslay du maine",
    "mont-de-marsan": "mont de marsan",
    "montdemarsan": "mont de marsan",
    "salon": "salon de provence",
    "compiegne": "compiegne",
    "compiègne": "compiegne",
    "feur": "feurs",
    "maukenchy": "mauquenchy",
    "chartre": "chartres",
    "corde mais": "cordemais",
    "nime": "nimes",
    "nimès": "nimes",
    "la capelle": "la capelle",
}



def extract_zone_turf_hippo_slug(url_or_slug: str) -> str:
    """Extrait le nom d'hippodrome d'une URL/slug Zone-Turf.

    r1-longchamp-192222 → longchamp
    z7-le-croise-laroche-198852 → le-croise-laroche
    r3-salon-de-provence-198857 → salon-de-provence
    phh-lisieux-198853 → lisieux (préfixe phh)
    """
    s = (url_or_slug or "").strip()
    if "/" in s:
        s = s.rstrip("/").split("/")[-1]
    s = s.replace(".html", "")
    # retirer préfixe r12- / z7- / phh-
    s = re.sub(r"^(?:[rz]\d+|phh)-", "", s, flags=re.I)
    # retirer suffixe -123456
    s = re.sub(r"-\d{4,}$", "", s)
    return s.strip("-").lower()


def normalize_hippodrome(name: str) -> str:
    s = _ascii_lower(name)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"paris\s*long\s*champ?s?", "paris longchamp", s)
    s = re.sub(r"parislongchamp?s?", "paris longchamp", s)
    s = re.sub(r"paris\s*vincenn?es?", "paris vincennes", s)
    s = re.sub(r"parisvincenn?es?", "paris vincennes", s)
    s = re.sub(r"cagnes?\s*sur\s*mer", "cagnes sur mer", s)
    s = re.sub(r"cagnessurmer", "cagnes sur mer", s)
    s = re.sub(r"enghien\s*soisy", "enghien soisy", s)
    s = re.sub(r"\bst\s*cloud\b", "saint cloud", s)
    s = re.sub(r"saintcloud", "saint cloud", s)
    s = re.sub(r"le\s*croise\s*laroche", "le croise laroche", s)
    s = re.sub(r"lyon\s*parilly", "lyon parilly", s)
    if s in _ALIASES:
        return _ALIASES[s]
    compact = s.replace(" ", "")
    for k, v in _ALIASES.items():
        if k.replace(" ", "") == compact:
            return v
    # slug zone-turf collé
    slug = s.replace(" ", "-")
    if slug in ZONE_TURF_SLUGS:
        return ZONE_TURF_SLUGS[slug]
    return s


def hippodrome_tokens(name: str) -> Set[str]:
    s = normalize_hippodrome(name)
    toks = set(s.split())
    if "longchamp" in s:
        toks.update({"longchamp", "paris"})
    if "vincennes" in s:
        toks.update({"vincennes", "paris"})
    if "auteuil" in s:
        toks.update({"auteuil", "paris"})
    if "parilly" in s:
        toks.update({"lyon", "parilly"})
    if "croise" in s or "laroche" in s:
        toks.update({"croise", "laroche"})
    return {t for t in toks if len(t) >= 2}


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


_GENERIC_TOKENS = {"saint", "sainte", "st", "ste", "la", "le", "les", "de", "du", "des",
                   "sur", "en", "l", "d", "mer", "et", "aux", "au", "hippodrome"}


def resolve_hippodrome(name: str, min_score: float = 0.72) -> Tuple[str, float]:
    norm = normalize_hippodrome(name)
    if not norm:
        return "", 0.0
    if norm in CANONICAL_HIPPODROMES:
        return norm, 1.0
    # via slug ZT
    slug = norm.replace(" ", "-")
    if slug in ZONE_TURF_SLUGS:
        return ZONE_TURF_SLUGS[slug], 1.0
    best, best_sc = norm, 0.0
    compact = norm.replace(" ", "")
    for can in CANONICAL_HIPPODROMES:
        sc = max(_similarity(norm, can), _similarity(compact, can.replace(" ", "")))
        inter = len((set(norm.split()) - _GENERIC_TOKENS) & (set(can.split()) - _GENERIC_TOKENS))  # v1.29.40 : mots génériques exclus
        if inter:
            sc = max(sc, 0.75 + 0.05 * inter)
        if sc > best_sc:
            best, best_sc = can, sc
    if best_sc >= min_score:
        return best, best_sc
    return norm, best_sc


def hippodromes_match(user_input: str, candidate: str, min_score: float = 0.72) -> bool:
    # Si candidate est un slug ZT brut, extraire le nom
    cand = candidate
    if re.search(r"(?:^|[rz]\d+-).*\-\d{4,}", candidate.replace(".html", "")) or candidate.count("-") >= 2:
        extracted = extract_zone_turf_hippo_slug(candidate)
        if extracted:
            cand = extracted
    u, su = resolve_hippodrome(user_input, min_score=min_score)
    c, sc = resolve_hippodrome(cand, min_score=min_score)
    if u and c and u == c and min(su, sc) >= min_score:
        return True
    tu, tc = set(u.split()), set(c.split())
    # v1.29.40 : les mots génériques (saint, la, le, sur, mer...) ne prouvent
    # JAMAIS l'identité (Saint-Cloud != Saint-Brieuc, La Teste != La Capelle).
    _GEN = {"saint", "sainte", "st", "ste", "la", "le", "les", "de", "du", "des",
            "sur", "en", "l", "d", "mer", "et", "aux", "au", "hippodrome"}
    tu_s, tc_s = tu - _GEN, tc - _GEN
    if not tu_s or not tc_s:
        return _similarity(u.replace(" ", ""), c.replace(" ", "")) >= 0.85
    inter = tu_s & tc_s
    if not inter:
        return _similarity(u.replace(" ", ""), c.replace(" ", "")) >= 0.85
    key = {
        "longchamp", "vincennes", "auteuil", "deauville", "chantilly", "cabourg",
        "cagnes", "enghien", "cloud", "borely", "parilly", "soie", "croise", "laroche",
        "bouscat", "pornichet", "compiegne", "fontainebleau", "vichy", "toulouse",
        "nantes", "caen", "pau", "clairefontaine",
    }
    if inter & key:
        return True
    return len(inter) >= max(1, (len(tu_s) + 1) // 2)


def best_match_among(user_input: str, candidates: List[str]) -> Optional[Tuple[str, float]]:
    if not user_input or not candidates:
        return None
    best: Optional[Tuple[str, float]] = None
    for cand in candidates:
        label = extract_zone_turf_hippo_slug(cand) if "-" in cand else cand
        if hippodromes_match(user_input, label) or hippodromes_match(user_input, cand):
            _, sc = resolve_hippodrome(label)
            sc2 = _similarity(
                normalize_hippodrome(user_input).replace(" ", ""),
                normalize_hippodrome(label).replace(" ", ""),
            )
            sc = max(sc, sc2)
            if best is None or sc > best[1]:
                best = (cand, sc)
        else:
            sc = _similarity(
                normalize_hippodrome(user_input).replace(" ", ""),
                normalize_hippodrome(label).replace(" ", ""),
            )
            if sc >= 0.80 and (best is None or sc > best[1]):
                best = (cand, sc)
    return best


# --- Hippodromes Quinté+ (ex-hippodromes_quinte.py, fusionné en v1.29.42) ---
# Classés par volume décroissant de Quinté+ (Vincennes ~30 %, puis Auteuil, Enghien, Deauville...).
_HIPPODROMES_ORDONNES: List[Tuple[str, int]] = [
    ("Vincennes", 120),
    ("Auteuil", 35),
    ("Enghien-Soisy", 28),
    ("Deauville", 25),
    ("Cagnes-sur-Mer", 24),
    ("Saint-Cloud", 22),
    ("Longchamp", 22),
    ("Chantilly", 20),
    ("Cabourg", 14),
    ("Caen", 12),
    ("Pau", 12),
    ("Clairefontaine", 10),
    ("Vichy", 10),
    ("Compiègne", 10),
    ("Lyon-Parilly", 9),
    ("Toulouse", 9),
    ("Bordeaux-Le Bouscat", 8),
    ("Marseille-Borély", 7),
    ("Marseille-Vivaux", 7),
    ("Lyon-La Soie", 7),
    ("Fontainebleau", 6),
    ("Nantes", 6),
    ("Pornichet", 6),
    ("Le Croisé-Laroche", 6),
    ("Amiens", 5),
    ("Angers", 5),
    ("Argentan", 5),
    ("La Capelle", 5),
    ("Laval", 5),
    ("Craon", 4),
    ("Feurs", 4),
    ("Dieppe", 4),
    ("Beaumont-de-Lomagne", 4),
    ("Meslay-du-Maine", 4),
    ("Graignes", 4),
    ("Strasbourg", 3),
    ("Nancy", 3),
    ("La Teste-de-Buch", 3),
    ("Les Sables-d'Olonne", 3),
    ("Le Lion-d'Angers", 3),
    ("Hyères", 3),
    ("Salon-de-Provence", 3),
    ("Mauquenchy", 3),
    ("Lisieux", 2),
    ("Chartres", 2),
    ("Châteaubriant", 2),
    ("Saint-Malo", 2),
    ("Saint-Galmier", 2),
    ("Aix-les-Bains", 2),
    ("Vittel", 2),
    ("Mont-de-Marsan", 2),
    ("Cordemais", 2),
    ("Le Mans", 2),
    ("Maisons-Laffitte", 2),
    ("Agen", 1),
    ("Cherbourg", 1),
    ("Cavaillon", 1),
    ("Évreux", 1),
    ("Le Touquet", 1),
    ("Nice", 1),
    ("Nîmes", 1),
    ("Reims", 1),
    ("Vire", 1)
]

HIPPODROMES_QUINTE: List[str] = [h for h, _ in _HIPPODROMES_ORDONNES]


def list_hippodromes_quinte() -> List[str]:
    """Liste UI : ordre décroissant de volume Quinté+."""
    return list(HIPPODROMES_QUINTE)


def list_hippodromes_quinte_with_weight() -> List[dict]:
    return [{"name": h, "poids_relatif": w} for h, w in _HIPPODROMES_ORDONNES]
