"""
musique.py -- Décodage de la « musique » des chevaux (v1.29.48, refonte d'après recherche).

SOURCES (consultées le 14/10/2026) : aide officielle PMU (communaute-aide.pmu.fr), Turfoo (guide « musique d'un
cheval »), Equidia (lexique + fiches de courses : musiques réelles), Turfomania, Boturfers, MediaPronos.

RÈGLES DE LECTURE
  * Gauche = performance la plus récente. Jusqu'à ~10 sorties.
  * Chiffre 1-9 = place ; « 0 » = non placé (hors des 9-10 premiers). Certaines sources (Equidia) écrivent les places
    >= 10 en CLAIR sur deux chiffres, SANS lettre de discipline : « 17Da8m8m166mDm » = 17e, Da, 8m, 8m, 16e, 6m, Dm.
  * Lettre minuscule = discipline : a attelé, m monté (trot) ; p plat ; h haies, s steeple, c cross (galop).
  * Majuscule = incident (remplace la place) :
        D  trot  -> disqualifié pour ALLURE IRRÉGULIÈRE (DAI ; « Dpag » = poteau passé au galop) : fautif, parfois rapide ;
        D  obstacle -> DÉROBÉ (refus / dérobade, « Dér ») ;  D  plat -> disqualifié (commissaires) ;
        T  tombé (« Tbé ») : surtout obstacle, accident pas forcément révélateur de la qualité ;
        A  arrêté (« Arr ») : souvent condition / fatigue / blessure -> mauvais signe pour la forme ;
        R  rétrogradé (« Ret ») : a franchi la ligne dans une place puis relégué par les commissaires ;
        j  jockey au sol (tombé).
  * « (24) » = changement d'année : les sorties À DROITE de ce repère datent de 2024 (« 3h Th (24) 1p » : 3e et tombé
    cette année, 1er à plat en 2024). Ce n'est PAS une performance.
  * Un changement de discipline (a->m, p->h) réduit la valeur prédictive des sorties de l'autre discipline.

`incident` garde les valeurs historiques (DISQUALIFIE | ARRETE | TOMBE) pour ne rien casser ; s'y ajoute RETROGRADE ;
`nature` précise le sens selon la discipline (DISQ_ALLURE, DEROBE, DISQ_COMMISSAIRES, TOMBE, ARRETE, RETROGRADE,
JOCKEY_AU_SOL).
"""
from __future__ import annotations
import re
from typing import List, Optional
from pydantic import BaseModel

# incident (long ou court) + lettre de discipline éventuelle | place 1-2 chiffres + lettre éventuelle | année
_TOKEN_RE = re.compile(
    r"\((\d{2})\)"
    r"|(?P<inc>Dpag|Dai|DAI|D[ée]r|Tb[ée]|Arr|Ret|[DATRj])(?P<d1>[apmhscAPMHSC])?"
    r"|(?P<num>\d{1,2})(?P<d2>[apmhscAPMHSC])?"
)

_DISC_MAP = {"a": "TROT_ATTELE", "m": "TROT_MONTE", "p": "PLAT", "h": "HAIES", "s": "STEEPLE", "c": "CROSS"}
_OBSTACLE = ("HAIES", "STEEPLE", "CROSS")
_TROT = ("TROT_ATTELE", "TROT_MONTE")


class MusiquePerf(BaseModel):
    rang: Optional[int] = None          # None si incident ; places >= 10 et « 0 » -> 10
    incident: Optional[str] = None      # DISQUALIFIE | ARRETE | TOMBE | RETROGRADE | None
    nature: Optional[str] = None        # sens précis selon la discipline (voir docstring)
    discipline: str                     # TROT_ATTELE | TROT_MONTE | PLAT | HAIES | STEEPLE | CROSS | INCONNU
    annee: Optional[int] = None         # None si année non déterminée (course la plus récente)
    ordre: int                          # 0 = plus récente
    rang_exact: Optional[int] = None    # place réelle si écrite en clair (ex. 17)


def _incident(code: str, discipline: str):
    c = code.upper().replace("É", "E")
    if c in ("D", "DAI", "DPAG"):
        if c in ("DAI", "DPAG") or discipline in _TROT:
            return "DISQUALIFIE", "DISQ_ALLURE"
        if discipline in _OBSTACLE:
            return "DISQUALIFIE", "DEROBE"
        return "DISQUALIFIE", "DISQ_COMMISSAIRES"
    if c == "DER":
        return "DISQUALIFIE", "DEROBE"
    if c in ("T", "TBE"):
        return "TOMBE", "TOMBE"
    if code == "j":
        return "TOMBE", "JOCKEY_AU_SOL"
    if c in ("A", "ARR"):
        return "ARRETE", "ARRETE"
    if c in ("R", "RET"):
        return "RETROGRADE", "RETROGRADE"
    return None, None


def parse_musique(musique: Optional[str], annee_course_actuelle: Optional[int] = None) -> List[MusiquePerf]:
    if not musique or musique.strip().lower() in ("inédit", "inedit", "-", ""):
        return []
    perfs: List[MusiquePerf] = []
    current_year = annee_course_actuelle
    idx = 0
    for m in _TOKEN_RE.finditer(musique):
        if m.group(1) is not None:                       # marqueur d'année : sorties suivantes (à droite) = cette année
            current_year = 2000 + int(m.group(1))
            continue
        if m.group("inc"):
            letter = m.group("d1")
            disc = _DISC_MAP.get(letter.lower(), "INCONNU") if letter else "INCONNU"
            incident, nature = _incident(m.group("inc"), disc)
            if incident is None:
                continue
            perfs.append(MusiquePerf(rang=None, incident=incident, nature=nature, discipline=disc,
                                     annee=current_year, ordre=idx))
        else:
            num = m.group("num")
            if len(num) == 2 and int(num) > 30 and not m.group("d2"):
                # '1234' sans lettres : ce ne sont pas des places à 2 chiffres -> deux sorties distinctes
                perfs.append(MusiquePerf(rang=int(num[0]) or 10, incident=None, discipline="INCONNU", annee=current_year, ordre=idx))
                idx += 1
                num = num[1]
            n = int(num)
            letter = m.group("d2")
            disc = _DISC_MAP.get(letter.lower(), "INCONNU") if letter else "INCONNU"
            perfs.append(MusiquePerf(rang=(10 if (n == 0 or n >= 10) else n), incident=None, discipline=disc,
                                     annee=current_year, ordre=idx, rang_exact=(n if n >= 10 else None)))
        idx += 1
    return perfs


def nb_victoires_consecutives(perfs: List[MusiquePerf], meme_discipline: Optional[str] = None) -> int:
    count = 0
    for p in perfs:
        if meme_discipline and p.discipline != meme_discipline:
            break
        if p.incident:
            break
        if p.rang == 1:
            count += 1
        else:
            break
    return count


def nb_top_consecutifs(perfs: List[MusiquePerf], seuil_rang: int, n: int) -> int:
    count = 0
    for p in perfs[:n]:
        if p.incident or p.rang is None or p.rang > seuil_rang:
            break
        count += 1
    return count


def taux_incidents(perfs: List[MusiquePerf], n: int = 10) -> float:
    fenetre = perfs[:n]
    if not fenetre:
        return 0.0
    return sum(1 for p in fenetre if p.incident) / len(fenetre)


def rangs_recents(perfs: List[MusiquePerf], n: int) -> List[int]:
    return [p.rang for p in perfs[:n] if p.rang is not None]


def tendance_forme(perfs: List[MusiquePerf], n: int = 3) -> Optional[str]:
    """AMELIORATION | DEGRADATION | STABLE, basé sur les n derniers rangs (hors incidents)."""
    rangs = rangs_recents(perfs, n)
    if len(rangs) < 2:
        return None
    # rangs[0] = plus récent ... rangs[-1] = plus ancien. Un rang plus PETIT est meilleur.
    deltas = [rangs[i] - rangs[i + 1] for i in range(len(rangs) - 1)]  # <0 : le plus récent est meilleur que le précédent
    if all(d < 0 for d in deltas):
        return "AMELIORATION"
    if all(d > 0 for d in deltas):
        return "DEGRADATION"
    return "STABLE"


# Points dégressifs places 1–6 (sélection outsider / ranking intra-tranche)
# Place 1..6 valorisées ; 7+ et incidents pénalisés doucement.
_POINTS_TOP6 = {1: 10.0, 2: 7.0, 3: 5.0, 4: 3.5, 5: 2.5, 6: 1.5}
# Poids de récence sur les 5 dernières sorties (plus récent = plus lourd)
_RECENCE_5 = (1.00, 0.85, 0.70, 0.55, 0.40)


def score_forme_recente_top6(
    musique: Optional[str],
    n: int = 5,
    annee_course_actuelle: Optional[int] = None,
    discipline_filter: Optional[str] = None,
) -> dict:
    """Forme récente intelligente sur n sorties (défaut 5).

    - Valorise les places 1 à 6 (pas seulement podium / Top5)
    - Pondère la récence (sortie 1 > sortie 5)
    - Incidents (T/D/A) : malus modéré, pas éliminatoire seul
    - Option filtre discipline (ex. HAIES pour ne compter que les h)

    Retourne dict:
      score_0_1 : normalisé 0–1
      score_brut : somme pondérée
      n_perfs : nombre de perfs utilisées
      n_top6 : nb places ≤6
      n_incidents
      profil : FORTE | UTILE | MOYENNE | FAIBLE | MORTE | INCONNUE
      detail : liste courte pour flags
    """
    perfs = parse_musique(musique, annee_course_actuelle=annee_course_actuelle)
    if discipline_filter:
        disc = discipline_filter.upper()
        filtered = [p for p in perfs if (p.discipline or "").upper() == disc]
        if len(filtered) >= 2:
            perfs = filtered
    perfs = perfs[: max(1, n)]
    if not perfs:
        return {
            "score_0_1": 0.0, "score_brut": 0.0, "n_perfs": 0,
            "n_top6": 0, "n_incidents": 0, "profil": "INCONNUE", "detail": [],
        }

    weights = _RECENCE_5[: len(perfs)]
    # normaliser si n != 5
    if len(weights) < len(perfs):
        weights = tuple(1.0 - 0.15 * i for i in range(len(perfs)))
    wsum = sum(weights) or 1.0

    brut = 0.0
    n_top6 = 0
    n_inc = 0
    detail = []
    for i, p in enumerate(perfs):
        w = weights[i] if i < len(weights) else 0.35
        if p.incident:
            pts = -3.0
            n_inc += 1
            detail.append(f"s{i+1}:INC:{p.incident}")
        elif p.rang is None:
            pts = -2.0
            detail.append(f"s{i+1}:?")
        else:
            pts = _POINTS_TOP6.get(p.rang, -1.5 if p.rang <= 9 else -2.5)
            if p.rang <= 6:
                n_top6 += 1
            detail.append(f"s{i+1}:P{p.rang}")
        brut += pts * w

    # Max théorique : toutes 1ères = 10 * wsum
    max_theo = 10.0 * wsum
    min_theo = -3.0 * wsum
    norm = (brut - min_theo) / (max_theo - min_theo) if max_theo > min_theo else 0.0
    norm = max(0.0, min(1.0, norm))

    if norm >= 0.72 and n_top6 >= 3:
        profil = "FORTE"
    elif norm >= 0.55 and n_top6 >= 2:
        profil = "UTILE"
    elif norm >= 0.40:
        profil = "MOYENNE"
    elif norm >= 0.25 or n_top6 >= 1:
        profil = "FAIBLE"
    else:
        profil = "MORTE"

    return {
        "score_0_1": round(norm, 4),
        "score_brut": round(brut, 3),
        "n_perfs": len(perfs),
        "n_top6": n_top6,
        "n_incidents": n_inc,
        "profil": profil,
        "detail": detail,
    }


def tendance_forme_top6(musique: Optional[str], n: int = 5) -> Optional[str]:
    """Alias profil pour flags pipeline."""
    return score_forme_recente_top6(musique, n=n).get("profil")
