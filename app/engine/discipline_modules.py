"""
discipline_modules.py — Modules spécifiques par discipline (v1.29.33)

Recherche 2026 (MediaPronos, DataTurf, France Galop, Equidia, Turf BZH) :

TROT ATTELÉ
  - Recul 25/50 m, ferrure (déferré = cible), driver + association, corde autostart
  - Favori Top5 ~72 % — marché plus fiable
  - Musique « a » uniquement pour la discipline du jour

TROT MONTÉ
  - Références « m » non transposables depuis attelé
  - Jockey (pas driver), moins d’aléas faute que attelé
  - Effort cheval plus élevé (porter vs tirer)

PLAT
  - Poids / valeur handicap (1 kg ≈ 1 longueur / 2000 m)
  - Corde + distance, terrain, forme récente
  - Favori Top5 ~59 %

HAIES
  - Vitesse + régularité de franchissement, haies amovibles (moins de chutes)
  - Expérience Auteuil / type parcours, terrain lourd discriminant
  - Jockey spécialiste obstacle
  - Favori Top5 ~59 %

STEEPLE
  - Technique de saut + endurance, obstacles fixes (rail-ditch, rivière)
  - Expérience parcours, chutes plus fréquentes (~25 % non-terminés)
  - Favori Top5 ~54 % — marché moins fiable, outsiders plus utiles
"""
from __future__ import annotations
from typing import List, Tuple, Optional

from app.models import Cheval, RaceContext, Discipline, Depart, TypeCourse
from app.engine.common import disc_bucket
from app.scraping.musique import parse_musique

Flags = List[str]


def _rangs_musique(cheval: Cheval, n: int = 8, disc_filter: Optional[str] = None) -> List[int]:
    perfs = parse_musique(cheval.musique)
    out: List[int] = []
    for p in perfs:
        if p.incident is not None:
            continue
        if disc_filter:
            d = (getattr(p, "discipline", None) or "")
            ds = d.value if hasattr(d, "value") else str(d)
            if disc_filter.upper() not in ds.upper():
                continue
        if p.rang is not None and p.rang > 0:
            out.append(int(p.rang))
        if len(out) >= n:
            break
    return out


def _incidents_obstacle(cheval: Cheval) -> Tuple[int, int, bool]:
    """nb_h, nb_s, chute_recente (T/A en 1-2 dernières obs)."""
    perfs = parse_musique(cheval.musique)
    nh = ns = 0
    chute_recente = False
    for i, p in enumerate(perfs[:8]):
        d = (getattr(p, "discipline", None) or "")
        ds = (d.value if hasattr(d, "value") else str(d)).upper()
        if "HAIE" in ds:
            nh += 1
        if "STEEP" in ds:
            ns += 1
        inc = (getattr(p, "incident", None) or "")
        if i < 2 and str(inc).upper() in ("T", "A", "TOMBE", "ARRETE", "ARRÊTÉ"):
            chute_recente = True
    # fallback lettres dans musique brute
    mus = (cheval.musique or "")
    import re
    if nh == 0:
        nh = len(re.findall(r"\d+h", mus, re.I))
    if ns == 0:
        ns = len(re.findall(r"\d+s", mus, re.I))
    if not chute_recente and re.search(r"(?:^|\s)(?:T|A)(?:h|s)?(?:\s|$)", mus[:12], re.I):
        chute_recente = True
    return nh, ns, chute_recente


def _forme_finisseur_musique(rangs: List[int]) -> bool:
    if len(rangs) < 4:
        return False
    recent = rangs[:3]
    older = rangs[3:6] if len(rangs) >= 6 else rangs[3:]
    if not older:
        return False
    return (sum(recent) / len(recent)) + 0.8 < (sum(older) / len(older))


# ---------------------------------------------------------------------------
# PLAT
# ---------------------------------------------------------------------------
def _plat_01(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """PLAT-01 Sprint : poids léger sur distance courte."""
    dist = race.distance_m or 0
    poids = cheval.poids_actuel_kg
    if not poids or dist <= 0 or dist > 1600:
        return 0.0, []
    if poids <= 54:
        return 8.0, ["PLAT01_POIDS_LEGER_SPRINT"]
    if poids <= 56:
        return 4.0, ["PLAT01_POIDS_MODERE_SPRINT"]
    if poids >= 60:
        return -4.0, ["PLAT01_POIDS_LOURD_SPRINT"]
    return 0.0, []


def _plat_02(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """PLAT-02 Fond : tenue distance longue."""
    dist = race.distance_m or 0
    if dist < 2200:
        return 0.0, []
    rangs = _rangs_musique(cheval, 6)
    if len(rangs) >= 3 and sum(1 for r in rangs[:3] if r <= 5) >= 2:
        return 6.0, ["PLAT02_TENUE_FOND"]
    if cheval.gains_totaux_eur and cheval.gains_totaux_eur > 80000 and dist >= 2400:
        return 3.0, ["PLAT02_PROXY_GAINS_FOND"]
    return 0.0, []


def _plat_03(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """PLAT-03 Grand champ : n° élevé + forme récente (proxy)."""
    n_part = len(getattr(race, "chevaux", None) or []) or 12
    num = cheval.numero or 0
    if n_part < 12 or num <= 8:
        return 0.0, []
    rangs = _rangs_musique(cheval, 5)
    if rangs and sum(1 for r in rangs[:3] if r <= 5) >= 2:
        return 4.0, ["PLAT03_GRAND_CHAMP_FORME"]
    return 0.0, []


def _plat_04(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """PLAT-04 Finisseur."""
    rangs = _rangs_musique(cheval, 8)
    if _forme_finisseur_musique(rangs):
        return 5.0, ["PLAT04_FINISSEUR"]
    return 0.0, []


def _plat_05(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """PLAT-05 Handicap valeur/poids : sous-poids relatif vs médiane champ (v1.29.33)."""
    if race.type_course != TypeCourse.HANDICAP:
        return 0.0, []
    poids = cheval.poids_actuel_kg
    if poids is None:
        return 0.0, ["PLAT05_POIDS_MANQUANT"]
    champs = [w for w in (getattr(race, "poids_champ_kg", None) or []) if w]  # v1.29.41 : race.chevaux n'existe pas (AttributeError sur tout Plat handicap)
    if len(champs) < 4:
        return 0.0, []
    med = sorted(champs)[len(champs) // 2]
    delta = med - poids  # >0 = plus léger que médiane
    if delta >= 3:
        return 6.0, ["PLAT05_SOUS_POIDS"]
    if delta >= 1.5:
        return 3.0, ["PLAT05_LEGEREMENT_SOUS_POIDS"]
    if delta <= -3:
        return -5.0, ["PLAT05_SURPOIDS"]
    return 0.0, []


# ---------------------------------------------------------------------------
# TROT
# ---------------------------------------------------------------------------
def _trot_01(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """TROT-01 Régularité haute (RK ou musique)."""
    if cheval.rk_array_3_derniers_sec and len(cheval.rk_array_3_derniers_sec) >= 3:
        arr = [x for x in cheval.rk_array_3_derniers_sec if x is not None]
        if len(arr) >= 3:
            ecart = max(arr) - min(arr)
            if ecart <= 0.5:
                return 8.0, ["TROT01_RK_STABLE"]
            if ecart <= 1.0:
                return 5.0, ["TROT01_RK_PARTIEL"]
    rangs = _rangs_musique(cheval, 5)
    if len(rangs) >= 3:
        ecart = max(rangs) - min(rangs)
        moy = sum(rangs) / len(rangs)
        if ecart <= 3 and moy <= 4.0:
            return 5.0, ["TROT01_PROXY_MUSIQUE"]
    return 0.0, []


def _trot_02(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """TROT-02 Tenue / finisseur."""
    rangs = _rangs_musique(cheval, 8)
    if _forme_finisseur_musique(rangs):
        return 5.0, ["TROT02_FINISSEUR"]
    return 0.0, []


def _trot_03(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """TROT-03 Spécialiste volte."""
    if getattr(race, "depart", None) != Depart.VOLTE:
        return 0.0, []
    mus = (cheval.musique or "").lower()
    if "volte" in mus or mus.count("a") >= 3:
        return 4.0, ["TROT03_VOLTE"]
    return 0.0, []


def _trot_04(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """TROT-04 Autostart corde intérieure."""
    if getattr(race, "depart", None) != Depart.AUTOSTART:
        return 0.0, []
    num = cheval.numero_autostart or cheval.numero or 99
    if num <= 3:
        return 6.0, ["TROT04_CORDE_INTERIEURE"]
    if num <= 6:
        return 3.0, ["TROT04_1ERE_LIGNE"]
    if num >= 10:
        return -3.0, ["TROT04_2E_LIGNE"]
    return 0.0, []


def _trot_05(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """TROT-05 Ferrure : déferré = signal cible (recherche 2026)."""
    ferr = (getattr(cheval, "ferrure", None) or getattr(cheval, "ferrure_code", None) or "")
    ferr_s = str(ferr).lower()
    if not ferr_s or ferr_s in ("none", "null", "?"):
        return 0.0, ["TROT05_FERRURE_INCONNUE"]
    if "défer" in ferr_s or "defer" in ferr_s or ferr_s in ("d", "da", "dp", "4d", "0"):
        return 5.0, ["TROT05_DEFERRE"]
    if "ferré" in ferr_s or "ferre" in ferr_s or ferr_s in ("f", "4f"):
        return 0.0, ["TROT05_FERRE"]
    return 0.0, []


def _trot_06_monte(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """TROT-06 Monté : références musique « m » (non transposable attelé)."""
    if race.discipline != Discipline.TROT_MONTE:
        return 0.0, []
    import re
    mus = cheval.musique or ""
    nm = len(re.findall(r"\d+m", mus, re.I))
    na = len(re.findall(r"\d+a", mus, re.I))
    if nm >= 3:
        return 7.0, ["TROT06_REF_MONTE"]
    if nm >= 1:
        return 3.0, ["TROT06_REF_MONTE_PARTIEL"]
    if na >= 3 and nm == 0:
        return -4.0, ["TROT06_QUE_ATTELE_SUR_MONTE"]
    return 0.0, ["TROT06_SANS_REF_MONTE"]


# ---------------------------------------------------------------------------
# OBSTACLE (haies + steeple)
# ---------------------------------------------------------------------------
def _obs_01(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """OBS-01 Expérience obstacle (nb sorties h/s)."""
    nh, ns, _ = _incidents_obstacle(cheval)
    total = nh + ns
    if total >= 6:
        return 8.0, ["OBS01_EXP_FORTE"]
    if total >= 3:
        return 5.0, ["OBS01_EXP_MOYENNE"]
    if total >= 1:
        return 2.0, ["OBS01_EXP_FAIBLE"]
    return -3.0, ["OBS01_SANS_EXP_OBS"]


def _obs_02(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """OBS-02 Spécialiste type (haies vs steeple)."""
    nh, ns, _ = _incidents_obstacle(cheval)
    if race.discipline == Discipline.HAIES:
        if nh >= 3 and nh >= ns:
            return 6.0, ["OBS02_SPE_HAIES"]
        if ns > nh and ns >= 3:
            return -2.0, ["OBS02_PLUTOT_STEEPLE_SUR_HAIES"]
    if race.discipline == Discipline.STEEPLE:
        if ns >= 3 and ns >= nh:
            return 7.0, ["OBS02_SPE_STEEPLE"]
        if nh > ns and nh >= 3:
            return -2.0, ["OBS02_PLUTOT_HAIES_SUR_STEEPLE"]
    return 0.0, []


def _obs_03(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """OBS-03 Franchissement fiable (peu d’incidents)."""
    nh, ns, chute = _incidents_obstacle(cheval)
    if chute:
        return -6.0, ["OBS03_CHUTE_RECENTE"]
    total = nh + ns
    if total >= 4:
        return 4.0, ["OBS03_FIABLE"]
    return 0.0, []


def _obs_04(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """OBS-04 Risque chute récente (alias renforcé)."""
    _, _, chute = _incidents_obstacle(cheval)
    if chute:
        return -8.0, ["OBS04_RISQUE_CHUTE"]
    return 0.0, []


def _obs_05(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """OBS-05 Distance adaptée (historique)."""
    dist = race.distance_m or 0
    if dist < 3000:
        return 0.0, []
    rangs = _rangs_musique(cheval, 6)
    if len(rangs) >= 3 and sum(1 for r in rangs[:4] if r <= 5) >= 2:
        return 5.0, ["OBS05_DIST_OK"]
    return 0.0, []


def _obs_06(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """OBS-06 Spécialiste Auteuil / hippodrome obstacle (v1.29.33)."""
    hippo = (race.hippodrome or "").lower()
    if "auteuil" not in hippo:
        return 0.0, []
    # proxy : musique avec plusieurs sorties + forme
    nh, ns, chute = _incidents_obstacle(cheval)
    if chute:
        return -2.0, ["OBS06_AUTEUIL_CHUTE"]
    if nh + ns >= 4:
        return 6.0, ["OBS06_AUTEUIL_EXP"]
    if nh + ns >= 2:
        return 3.0, ["OBS06_AUTEUIL_PARTIEL"]
    return 0.0, []


def _obs_07_terrain(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """OBS-07 Terrain lourd / pénétromètre (discriminant obstacle)."""
    pen = getattr(race, "penetrometre", None)
    if pen is None:
        return 0.0, []
    try:
        pen_f = float(pen)
    except (TypeError, ValueError):
        return 0.0, []
    # terrain collant/lourd >= 4.0 : favoriser forme solide, pénaliser musique morte
    if pen_f >= 4.0:
        rangs = _rangs_musique(cheval, 5)
        if rangs and sum(1 for r in rangs[:3] if r <= 4) >= 2:
            return 5.0, ["OBS07_TERRAIN_LOURD_FORME"]
        if not rangs or (rangs and min(rangs[:3]) >= 8):
            return -3.0, ["OBS07_TERRAIN_LOURD_FAIBLE"]
    return 0.0, []


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def score_discipline_modules(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """Somme bornée des modules de la famille de discipline."""
    disc = race.discipline
    flags: Flags = []
    total = 0.0

    bucket = disc_bucket(disc)

    if bucket == "PLAT" or disc == Discipline.PLAT:
        for fn in (_plat_01, _plat_02, _plat_03, _plat_04, _plat_05):
            v, f = fn(cheval, race)
            total += v
            flags.extend(f)
    elif bucket == "TROT" or disc in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE):
        for fn in (_trot_01, _trot_02, _trot_03, _trot_04, _trot_05, _trot_06_monte):
            v, f = fn(cheval, race)
            total += v
            flags.extend(f)
    elif bucket == "OBSTACLE" or disc in (Discipline.HAIES, Discipline.STEEPLE):
        for fn in (_obs_01, _obs_02, _obs_03, _obs_04, _obs_05, _obs_06, _obs_07_terrain):
            v, f = fn(cheval, race)
            total += v
            flags.extend(f)
    else:
        flags.append("DISC_MODULES_UNKNOWN")

    # Plafond anti-saturation
    total = max(-25.0, min(25.0, total))
    return total, flags


# Alias historique (qualitative_engine)
def compute_discipline_specifique(cheval: Cheval, race: RaceContext):
    """API historique → score_discipline_modules."""
    return score_discipline_modules(cheval, race)
