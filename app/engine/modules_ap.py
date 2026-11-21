"""
Modules A-P -- Moteur de score déterministe (PROTOCOL VANTAGE, Partie 3)
==========================================================================
Traduction fidèle des formules lues dans PROTOCOL_VANTAGE_MASTER-2.docx
(Partie 3, lignes ~2075-3513) et confirmées par le tableau condensé du
Bloc 5 des instructions d'exécution v1.22.2-test. Chaque fonction
retourne (valeur, flags) où flags documente les fallbacks appliqués
(RÈGLE 4 : STRICT -> DÉGRADÉ -> MINIMAL -> DERNIER_RECOURS).

Ce module ne couvre QUE les modules dont la formule est intégralement
numérique. Les catalogues qualitatifs (B01-B56, M01-M43, SF, D, GRU,
SUPRA, GAMMA, SSFO) sont délégués à la couche LLM (app/llm/qualitative.py)
qui lit le texte original du protocole -- voir README pour la justification
de cette séparation.
"""
from __future__ import annotations
from typing import List, Optional, Tuple
from statistics import mean

from app.models import Cheval, RaceContext, Discipline, TypeCourse, Depart, StyleMPA
from app.engine.common import clamp, disc_bucket, terrain_category, derive_style_mpa, champ_mean

Flags = List[str]


def _calib_mult(name: str, default: float, low: float = 0.25, high: float = 1.0) -> float:
    import os
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# MODULE A -- SRI v2 (Score de Référence Individuelle)
# ---------------------------------------------------------------------------
def module_a_sri(cheval: Cheval, discipline: Discipline) -> Tuple[float, Flags]:
    flags: Flags = []
    valeur_pmu = cheval.valeur_pmu
    if valeur_pmu is None or valeur_pmu <= 0:
        flags.append("SRI_VALEUR_PMU_MANQUANTE")
        # Fallback (20-21/09/2026) : gains_moyenne (éventuellement dérivée PMU)
        # → gains_totaux/nb → proxy cote (plafonné) → floor.
        g_moy = cheval.gains_moyenne_carriere_eur
        if (g_moy is None or g_moy <= 0) and cheval.gains_totaux_eur and cheval.nb_courses:
            try:
                g_moy = float(cheval.gains_totaux_eur) / max(int(cheval.nb_courses), 1)
            except (TypeError, ValueError, ZeroDivisionError):
                g_moy = None
        if g_moy is not None and g_moy > 0:
            # Plafond abaissé 70→58 pour limiter suroévaluation outsiders riches (Dilva)
            valeur_pmu = clamp(12.0, 58.0, g_moy / 90.0)
            flags.append("SRI_VALEUR_PROXY_GAINS")
        elif cheval.cote_matin is not None and cheval.cote_matin > 0:
            # Priorité 2 (29/09/2026) : proxy cote fortement plafonné (anti double-compte marché)
            valeur_pmu = clamp(12.0, 38.0, 95.0 / max(cheval.cote_matin, 3.0))
            flags.append("SRI_VALEUR_PROXY_COTE")
        else:
            valeur_pmu = 22.0
            flags.append("SRI_VALEUR_FLOOR_MINIMAL")

    if cheval.gains_totaux_eur is None or cheval.nb_courses is None:
        if cheval.gains_moyenne_carriere_eur is not None:
            # Repli Frequence-Turf (table "Moyenne de gains", ajouté le
            # 02/09/2026) : gain/course déjà calculé par la source --
            # évite le repli à 0.0 quand gains_totaux_eur/nb_courses
            # manquent, sans pour autant recalculer un ratio potentiellement
            # moins fidèle (discipline/période différentes de la source).
            gain_par_course = cheval.gains_moyenne_carriere_eur
            flags.append("GAINS_REPLI_MOYENNE_FT")
        else:
            gain_par_course = 0.0
            flags.append("GAINS_MANQUANTS")
    else:
        gain_par_course = cheval.gains_totaux_eur / max(cheval.nb_courses, 1)

    niveau_max = cheval.niveau_max or 0.0
    if cheval.niveau_max_hors_pattern_europeen:
        niveau_max = niveau_max / 2.0
        flags.append("SRI_HORS_PATTERN_EUROPEEN")

    bucket = disc_bucket(discipline)
    age = cheval.age
    if age is None:
        age_mult = 1.00
        flags.append("AGE_MANQUANT")
    elif bucket == "TROT":
        age_mult = 1.05 if 6 <= age <= 9 else 0.95 if 4 <= age <= 5 else 0.88 if age > 10 else 0.80
    elif bucket == "PLAT":
        age_mult = 1.00 if 3 <= age <= 5 else 0.97 if age == 6 else 0.90 if 7 <= age <= 8 else 0.83
    else:  # OBSTACLE
        age_mult = 1.05 if 6 <= age <= 10 else 0.90 if 4 <= age <= 5 else 0.85 if age > 11 else 0.78

    if bucket == "TROT":
        sri_base = valeur_pmu * 1.5 + gain_par_course / 200 + niveau_max * 8
    elif bucket == "PLAT":
        sri_base = valeur_pmu * 1.3 + gain_par_course / 300 + niveau_max * 12
    else:
        sri_base = valeur_pmu * 1.4 + gain_par_course / 150 + niveau_max * 10

    # v1.29.25 — atténuer SRI si proxy (Argentan: SRI_PROXY_GAINS gonflait hors-Top5)
    sri_val = sri_base * age_mult
    if "SRI_VALEUR_PROXY_GAINS" in flags:
        sri_val *= _calib_mult("VANTAGE_SRI_PROXY_GAINS_MULT", 0.65)
        flags.append(f"SRI_PROXY_GAINS_ATTENUE_{_calib_mult('VANTAGE_SRI_PROXY_GAINS_MULT', 0.65):.2f}")
    elif "SRI_VALEUR_PROXY_COTE" in flags:
        # Double-compte marché/p : atténuation forte
        sri_val *= _calib_mult("VANTAGE_SRI_PROXY_COTE_MULT", 0.40)
        flags.append(f"SRI_PROXY_COTE_ATTENUE_{_calib_mult('VANTAGE_SRI_PROXY_COTE_MULT', 0.40):.2f}")
    elif "SRI_VALEUR_FLOOR_MINIMAL" in flags:
        sri_val *= _calib_mult("VANTAGE_SRI_PROXY_FLOOR_MULT", 0.50)
        flags.append(f"SRI_FLOOR_ATTENUE_{_calib_mult('VANTAGE_SRI_PROXY_FLOOR_MULT', 0.50):.2f}")

    return clamp(0, 120, sri_val), flags
# MODULE B -- IFF v2 (Forme & Fitness)
# ---------------------------------------------------------------------------
_IFF_WINDOWS = {
    "TROT": (8, 18, 4),
    "PLAT": (14, 28, 3),
    "OBSTACLE": (21, 42, 2),
}

_IFF_POS_KEYWORDS = [
    (["mieux que ne l'indique le classement", "bonne fin de course", "a fini très fort",
      "aurait pu faire mieux avec de l'espace"], 6, None),
    (["bloqué", "sans avoir ses aises", "gêné", "n'a pas eu le passage",
      "a manqué d'espace dans le dernier virage"], 5, None),
    (["visé de longue date", "ciblé depuis plusieurs mois", "travaille pour cette course",
      "c'est la course qui lui convient", "c'est la course qu'on lui attendait",
      "a été préparé spécifiquement pour", "c'est pour cette course qu'on l'a préparé"], 8, "IFF_ENGAGEMENT_CIBLE"),
    (["a perdu une ferrure", "a perdu un fer en course"], 7, "EE_FERRURE"),
    (["pris dans un accident", "heurté par un autre cheval"], 7, "EE_CHUTE_EXT"),
    (["problème au départ", "n'a pas pris l'autostart"], 5, "EE_DEPART"),
    (["a eu des problèmes mécaniques"], 6, "EE_MECANIQUE"),
]
_IFF_NEG_KEYWORDS = [
    (["a longtemps été au galop", "a fauté"], -6, None),
    (["n'a jamais été en course", "semblait éprouver des difficultés",
      "ne semblait pas à l'aise sur ce terrain"], -4, None),
    (["pas un objectif", "pas la cible", "course de passage", "n'est pas prêt pour ça",
      "je pense qu'il va être juste", "n'est pas au mieux de sa forme",
      "on l'a mis là pour l'occuper"], -8, "IFF_NON_OBJECTIF"),
]


def _iff_commentaire(commentaire: Optional[str]) -> Tuple[float, Flags]:
    if not commentaire:
        return 0.0, ["COMMENTAIRE_ABSENT"]
    text = commentaire.lower()
    flags: Flags = []
    best = 0.0
    extended = False
    for keywords, points, flag in _IFF_POS_KEYWORDS:
        if any(k in text for k in keywords):
            if points > best:
                best = points
            if flag:
                flags.append(flag)
                extended = True
    for keywords, points, flag in _IFF_NEG_KEYWORDS:
        if any(k in text for k in keywords):
            if points < best or best == 0.0:
                best = points if best >= 0 else min(best, points)
            if flag:
                flags.append(flag)
                extended = True
    if best == 0.0:
        flags.append("IFF_COMMENTAIRE_VAGUE_NON_CLASSE")
    cap = 8 if extended else 6
    return clamp(-cap, cap, best), flags


def module_b_iff(cheval: Cheval, discipline: Discipline) -> Tuple[float, Flags]:
    flags: Flags = []
    bucket = disc_bucket(discipline)
    opt_min, opt_max, seuil = _IFF_WINDOWS[bucket]

    if cheval.delai_j is None:
        flags.append("DELAI_MANQUANT")
        return 0.0, flags

    delai = cheval.delai_j
    if opt_min <= delai <= opt_max:
        fenetre = 8
    elif delai < opt_min:
        fenetre = -5
    elif delai <= opt_max * 1.5:
        fenetre = 3
    elif delai <= opt_max * 2.5:
        fenetre = 0
    else:
        fenetre = -3

    surmenage = 0.0
    if cheval.nb_courses_30j is not None and cheval.nb_courses_30j > seuil:
        surmenage = -8 * (cheval.nb_courses_30j - seuil)

    commentaire_val, com_flags = _iff_commentaire(cheval.commentaire_derniere_course)
    flags.extend(com_flags)

    feu = (cheval.feu_equidia or "ABSENT").upper()
    if feu == "VERT":
        feu_val = 2 if commentaire_val < 4 else 0  # non cumulable si commentaire>=+4 -> MAX
        feu_val = max(feu_val, 0) if commentaire_val >= 4 else 2
    elif feu == "ORANGE":
        feu_val = -4
        flags.append("FEU_ORANGE")
    elif feu == "ROUGE":
        feu_val = -8
        flags.append("FEU_ROUGE")
    else:
        feu_val = 0

    absence_silencieuse = 0.0
    if (delai > 60 and (cheval.icp_pondere or 0) < 2.0 and bucket in ("TROT", "PLAT")):
        absence_silencieuse = -1

    cap = 18 if ("IFF_ENGAGEMENT_CIBLE" in flags or "IFF_NON_OBJECTIF" in flags or feu_val != 0) else 15
    total = fenetre + surmenage + commentaire_val + absence_silencieuse + feu_val

    # v1.29.36 — forme récente Top6 (musique) : atténue malus si profil non mort
    # (évite d'éliminer un outsider/haies encore capable sur 5 sorties)
    try:
        from app.scraping.musique import score_forme_recente_top6
        fr = score_forme_recente_top6(getattr(cheval, "musique", None) or "", n=5)
        profil = fr.get("profil") or "INCONNUE"
        flags.append(f"IFF_FORME_{profil}")
        if profil in ("FORTE", "UTILE") and total < 0:
            total = total * 0.55  # attenue malus
            flags.append("IFF_MALUS_ATTENUE_FORME")
        elif profil == "MOYENNE" and total < -8:
            total = max(total, -8.0)
            flags.append("IFF_MALUS_PLAFOND_FORME_MOY")
        elif profil == "MORTE" and total > 0:
            total = total * 0.7
            flags.append("IFF_BONUS_REDUIT_FORME_MORTE")
        # Obstacle : plafond malus plus bas si pas MORTE
        if bucket == "OBSTACLE" and profil not in ("MORTE", "INCONNUE") and total < -10:
            total = max(total, -10.0)
            flags.append("IFF_CAP_OBSTACLE_FORME")
    except Exception:
        flags.append("IFF_FORME_TOP6_ERR")

    return clamp(-20, cap, total), flags


# ---------------------------------------------------------------------------
# MODULE C -- NRC (Normalisation Relative Champ)
# ---------------------------------------------------------------------------
def module_c_nrc(cheval: Cheval, champ: List[Cheval]) -> Tuple[float, Flags]:
    """NRC : écart de valeur PMU au champ.

    PROXY (14/09/2026) : si valeur_pmu absente, utiliser gains moyens
    (gains_moyenne_carriere_eur ou gains_totaux/nb_courses) — pas la cote
    (évite double comptage marché). Flag NRC_PROXY_GAINS.
    """
    flags: Flags = []
    valeur = cheval.valeur_pmu
    if valeur is None:
        if cheval.gains_moyenne_carriere_eur is not None:
            valeur = cheval.gains_moyenne_carriere_eur / 1000.0  # échelle relative
            flags.append("NRC_PROXY_GAINS_MOY")
        elif cheval.gains_totaux_eur is not None and cheval.nb_courses:
            valeur = (cheval.gains_totaux_eur / max(cheval.nb_courses, 1)) / 1000.0
            flags.append("NRC_PROXY_GAINS")
        else:
            return 0.0, ["VALEUR_MANQUANTE"]
        # moyenne champ sur même proxy
        vals = []
        for c in champ:
            if c.valeur_pmu is not None:
                vals.append(c.valeur_pmu)
            elif c.gains_moyenne_carriere_eur is not None:
                vals.append(c.gains_moyenne_carriere_eur / 1000.0)
            elif c.gains_totaux_eur is not None and c.nb_courses:
                vals.append((c.gains_totaux_eur / max(c.nb_courses, 1)) / 1000.0)
        moy = champ_mean(vals)
        if moy is None:
            return 0.0, flags + ["VALEUR_MANQUANTE"]
        delta = valeur - moy
        # seuils plus serrés (proxy bruité)
        if delta > 3:
            return 4.0, flags
        if delta > 1:
            return 2.0, flags
        if delta >= -1:
            return 0.0, flags
        if delta >= -3:
            return -2.0, flags
        return -4.0, flags

    moy = champ_mean([c.valeur_pmu for c in champ])
    if moy is None:
        return 0.0, ["VALEUR_MANQUANTE"]
    delta = valeur - moy
    if delta > 5:
        return 8.0, flags
    if delta > 2:
        return 4.0, flags
    if delta >= -2:
        return 0.0, flags
    if delta >= -5:
        return -4.0, flags
    return -8.0, flags


# ---------------------------------------------------------------------------
# MODULE D -- BSH v3/v4 (Bilan Santé Historique Jockey/Driver)
# ---------------------------------------------------------------------------
_BSH_WINDOWS = {
    "TROT": [(7, 3.5), (14, 2.5), (30, 1.0)],
    "PLAT": [(14, 3.0), (28, 2.0), (45, 1.0)],
    "OBSTACLE": [(14, 2.0), (28, 3.0), (45, 1.5)],
}
_BSH_BASELINE = {"TROT": 0.14, "PLAT": 0.12, "OBSTACLE": 0.10}


def module_d_bsh(cheval: Cheval, discipline: Discipline, race: RaceContext) -> Tuple[float, Flags]:
    flags: Flags = []
    bucket = disc_bucket(discipline)
    baseline = _BSH_BASELINE[bucket]
    ds = cheval.driver_stats
    if ds is None:
        return 0.0, ["BSH_DONNEES_ABSENTES"]
    if not ds.fenetres:
        # Repli CanalTurf (débloqué le 03/09/2026, cf. DriverStats) :
        # taux Quinté+ prioritaire sur taux carrière toutes courses --
        # plus pertinent pour ce protocole, qui ne prédit QUE des
        # Quintés. Poids conservateur (poids=1.0, le plus faible des
        # fenêtres du tableau ci-dessus) car ce n'est pas un signal de
        # forme récente, juste une compétence générale du driver.
        if ds.nb_courses_quinte is not None and ds.nb_courses_quinte >= 5 and ds.taux_victoire_quinte is not None:
            # Repli dégradé ×0.30 (29/09/2026) : ×0.50 laissait encore SRI/BSH dominants
            # (Chantilly Rock Blanc BSH+20 systématique). Réduit le faux signal driver.
            score = max(0.0, (ds.taux_victoire_quinte - baseline) * 100) * 1.0 * 0.60 * 0.30
            return clamp(-5, 12, score), ["BSH_REPLI_TAUX_QUINTE_CANALTURF", "BSH_REPLI_DEGRADE_30"]
        if ds.taux_victoire_carriere is not None:
            score = max(0.0, (ds.taux_victoire_carriere - baseline) * 100) * 1.0 * 0.60 * 0.30
            return clamp(-5, 12, score), ["BSH_REPLI_TAUX_CARRIERE_CANALTURF", "BSH_REPLI_DEGRADE_30"]
        return 0.0, ["BSH_DONNEES_ABSENTES"]

    total = 0.0
    fenetres_dispo = {f.jours: f for f in ds.fenetres}
    for jours, poids in _BSH_WINDOWS[bucket]:
        f = fenetres_dispo.get(jours)
        if f is None or f.courses == 0:
            flags.append(f"BSH_FENETRE_{jours}J_MANQUANTE")
            continue
        taux = f.victoires / max(f.courses, 1)
        score_global = max(0.0, (taux - baseline) * 100) * poids * 0.60
        if ds.taux_hippodrome is not None or ds.taux_distance is not None:
            taux_ctx = mean([v for v in [ds.taux_hippodrome, ds.taux_distance] if v is not None])
            score_ctx = max(0.0, (taux_ctx - baseline * 0.85) * 100) * poids * 0.40
        else:
            score_ctx = 0.0
        total += score_global + score_ctx

    bsh_v3 = clamp(-5, 20, total)

    bsh_v4 = 0.0
    if (race.allocation_eur is not None and race.allocation_eur <= 50000
            and ds.classement_national is not None and ds.classement_national <= 10
            and ds.taux_top1_20j is not None and ds.taux_top1_20j > 0.20):
        bsh_v4 = 6.0

    raw_bsh = bsh_v3 + bsh_v4
    # Priorité 4 : coefficients discipline (fenêtres déjà distinctes ; fine-tune amplitude)
    _BSH_DISC_MULT = {"TROT": 1.05, "PLAT": 1.00, "OBSTACLE": 0.92}
    disc_m = _BSH_DISC_MULT.get(bucket, 1.0)
    if disc_m != 1.0:
        flags.append(f"BSH_DISC_MULT_{bucket}_{disc_m:.2f}")
    return clamp(-5, 20, raw_bsh * disc_m), flags


# ---------------------------------------------------------------------------
# MODULE E -- BSC v3 (Bilan Succès Entraîneur)
# ---------------------------------------------------------------------------
_BSC_WINDOWS = {
    "TROT": [(15, 3.0), (30, 1.5)],
    "PLAT": [(15, 3.0), (30, 2.0), (60, 0.5)],
    "OBSTACLE": [(15, 2.0), (30, 3.0), (60, 1.5)],
}
_BSC_BASELINE = {"TROT": 0.12, "PLAT": 0.10, "OBSTACLE": 0.08}


def module_e_bsc(cheval: Cheval, discipline: Discipline) -> Tuple[float, Flags]:
    bucket = disc_bucket(discipline)
    baseline = _BSC_BASELINE[bucket]
    ts = cheval.trainer_stats
    if ts is None:
        return 0.0, ["BSC_DONNEES_ABSENTES"]
    if not ts.fenetres:
        # Repli CanalTurf, même logique que module_d_bsh ci-dessus.
        if ts.nb_courses_quinte is not None and ts.nb_courses_quinte >= 5 and ts.taux_victoire_quinte is not None:
            # Repli dégradé ×0.30 (29/09/2026) — aligné BSH
            score = max(0.0, (ts.taux_victoire_quinte - baseline) * 100) * 1.0 * 0.60 * 0.30
            return clamp(-3, 10, score), ["BSC_REPLI_TAUX_QUINTE_CANALTURF", "BSC_REPLI_DEGRADE_30"]
        if ts.taux_victoire_carriere is not None:
            score = max(0.0, (ts.taux_victoire_carriere - baseline) * 100) * 1.0 * 0.60 * 0.30
            return clamp(-3, 10, score), ["BSC_REPLI_TAUX_CARRIERE_CANALTURF", "BSC_REPLI_DEGRADE_30"]
        return 0.0, []
    total = 0.0
    fenetres_dispo = {f.jours: f for f in ts.fenetres}
    for jours, poids in _BSC_WINDOWS[bucket]:
        f = fenetres_dispo.get(jours)
        if f is None or f.courses == 0:
            continue
        taux = f.victoires / max(f.courses, 1)
        total += max(0.0, (taux - baseline) * 100) * poids * 0.60
    _BSC_DISC_MULT = {"TROT": 1.05, "PLAT": 1.00, "OBSTACLE": 0.92}
    disc_m = _BSC_DISC_MULT.get(bucket, 1.0)
    bsc_flags = []
    if disc_m != 1.0:
        bsc_flags.append(f"BSC_DISC_MULT_{bucket}_{disc_m:.2f}")
    return clamp(-3, 15, total * disc_m), bsc_flags


# ---------------------------------------------------------------------------
# MODULE GRU-DIST-2 -- Interaction sexe x distance longue (TROT)
# ---------------------------------------------------------------------------
_FEMELLES_UNIQUEMENT = ("aux femelles", "pour femelles", "femelles seulement", "femelles uniquement",
                        "pouliches et juments", "course de juments")


def module_gru_dist2(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """Cheval.sexe scrapé depuis le début (turfoo_fiche_cheval.py) mais
    jamais lu nulle part dans le moteur jusqu'au 03/09/2026. Formule
    entièrement déterministe et autonome du texte source -- aucune
    donnée manquante. Non-cumul/interaction avec un signal "M17 jument
    contre mâles" mentionné dans le texte source à cet endroit précis
    n'est PAS repris : le catalogue définit M17 ailleurs comme "doute
    sur la forme physique (commentaire)", un signal totalement
    différent -- coquille apparente du document source (collision de
    nom), donc GRU-DIST-2 est implémenté seul, sans ce recoupement."""
    if disc_bucket(race.discipline) != "TROT" or race.distance_m <= 2400 or not cheval.sexe:
        return 0.0, []
    cp = (race.conditions_particulieres or "").lower()
    if any(m in cp for m in _FEMELLES_UNIQUEMENT):
        return 0.0, ["GRU_DIST2_COURSE_FEMELLES"]

    sexe = cheval.sexe.upper()[0]
    if race.distance_m > 2800:
        if sexe == "M":
            return 5.0, ["GRU_MALE_FOND_CRITIQUE"]
        if sexe == "F":
            return -5.0, ["GRU_JUMENT_FOND_CRITIQUE"]
        return 0.0, []  # hongre, référence neutre
    if sexe == "M":
        return 3.0, ["GRU_MALE_FOND"]
    if sexe == "F":
        return -3.0, ["GRU_JUMENT_FOND"]
    return 0.0, []


# ---------------------------------------------------------------------------
# MODULE F -- STAB (Stabilité / Risque DQ)
# ---------------------------------------------------------------------------
def module_f_stab(cheval: Cheval, discipline: Discipline, champ_cotes: List[Optional[float]]) -> Tuple[float, Flags]:
    flags: Flags = []

    # S1 -- DQ cheval 12 mois
    taux1 = cheval.dq_12m / max(cheval.nb_courses_12m or 1, 1) if cheval.nb_courses_12m else 0.0
    s1 = -20 if taux1 > 0.20 else -15 if taux1 > 0.15 else -10 if taux1 > 0.10 else -5 if taux1 > 0.05 else 0.0

    # S2 -- DQ driver 12 mois
    ds = cheval.driver_stats
    s2 = 0.0
    if ds and ds.nb_courses_12m:
        taux2 = ds.dq_12m / max(ds.nb_courses_12m, 1)
        s2 = -15 if taux2 > 0.15 else -12 if taux2 > 0.10 else -8 if taux2 > 0.05 else 0.0

    # S3 -- incidents 30j + pattern
    nb_inc = cheval.incidents_30j
    s3a = {0: 0.0, 1: -8.0, 2: -12.0}.get(nb_inc, -20.0 if nb_inc >= 3 else 0.0)
    pattern_map = {"STABLE": 0.0, "VARIABLE": -3.0, "CHANGEANTE": -8.0, "SERIES": -15.0}
    s3b = pattern_map.get((cheval.pattern_incidents or "STABLE").upper(), 0.0)
    s3 = s3a + s3b

    if cheval.pattern_incidents and cheval.pattern_incidents.upper() == "SERIES" and cheval.dq_5_dernieres_tentees >= 3:
        flags.append("STAB_DQ_SERIE_CRITIQUE")

    # S4 -- ferrure & équipement
    fc = cheval.ferrure_changes
    s4a = -12 if fc >= 2 else -5 if fc == 1 else 0.0
    ec = cheval.equip_changes
    s4b = -10 if ec >= 3 else -5 if ec >= 1 else 0.0
    s4 = s4a + s4b

    # S5 -- STAB-06 risque d'allure sur favori (TROT) -- équivalent RAH-233
    # (comparé le 11/09/2026 à hardened_complete/modules/normative.py :
    # même condition non-cumul taux1<=0.15, même seuil cote<=6/rang<=2,
    # même dq_12m>=1 -- déjà fonctionnellement identique côté chat, seul
    # le flag de traçabilité RAH233 manquait pour l'audit post-course)
    s5 = 0.0
    bucket = disc_bucket(discipline)
    if bucket == "TROT" and taux1 <= 0.15:
        cotes_valides = sorted([c for c in champ_cotes if c is not None])
        est_favori_ou_2e = (cheval.cote_matin is not None and cheval.cote_matin in cotes_valides[:2])
        cote_courte = cheval.cote_matin is not None and cheval.cote_matin <= 6.0
        if (est_favori_ou_2e or cote_courte) and cheval.dq_12m >= 1:
            s5 = -5
            flags.append("STAB_FAVORI_RISQUE_ALLURE")
            flags.append("RAH233_STAB06_NON_CUMUL_STAB01")

    stab_score = clamp(-100, 0, s1 + s2 + s3 + s4 + s5)
    return max(-20, stab_score), flags


# ---------------------------------------------------------------------------
# MODULE G -- TACT (toutes disciplines)
#   - TROT   : autostart / lignes / chrono (historique)
#   - PLAT   : corde (n°) × distance × style × poids relatif
#   - OBS*   : haies / steeple / cross — poids, expérience, style (corde faible)
# Réf. turf : corde critique <1600m plat ; négligeable obstacle ; poids handicap central.
# ---------------------------------------------------------------------------
_TACT_LIGNES_RESTREINTES = {"CAEN", "CABOURG", "GRAIGNES"}
_RECUL_COEFF_GEO = {
    "VINCENNES": 0.8, "ENGHIEN": 0.8, "MARSEILLE-BORELY": 0.8,
    "BORDEAUX": 0.8, "LYON-PARILLY": 0.8, "CAEN": 1.3, "CABOURG": 1.3, "GRAIGNES": 1.3,
}


def _tact_trot(cheval: Cheval, race: RaceContext, flags: Flags) -> float:
    style = cheval.style_mpa
    num = cheval.numero_autostart

    t1 = 0.0
    if num is not None:
        is_meneur = style in (StyleMPA.MENEUR_FORT, StyleMPA.MENEUR_MODERE)
        is_attentiste = style == StyleMPA.ATTENTISTE
        if 1 <= num <= 3:
            t1 = 12 if is_meneur else 8 if is_attentiste else 8
        elif 4 <= num <= 8:
            t1 = 8 if is_meneur else 5 if is_attentiste else 5
        elif 9 <= num <= 12:
            t1 = -6 if is_meneur else -4 if is_attentiste else -4
        elif 13 <= num <= 16:
            t1 = -12 if is_meneur else -8 if is_attentiste else -8
        else:
            t1 = -8 if is_meneur else -3 if is_attentiste else -3
    if race.partants_confirmes and race.partants_confirmes > 12:
        t1 -= 2

    t2 = 0.0
    pos_map = {"1ere_ligne": 10, "2eme_ligne": 0, "ext_simple": -5, "ext_2nd": -8}
    if cheval.position_ligne:
        t2 += pos_map.get(cheval.position_ligne, 0.0)
    if cheval.attelage_position == 1:
        t2 += 5

    t3 = 0.0
    if cheval.chrono_1km is not None:
        t3 += 8 if cheval.chrono_1km < 62 else 4 if cheval.chrono_1km < 65 else 0
    is_meneur = style in (StyleMPA.MENEUR_FORT, StyleMPA.MENEUR_MODERE)
    is_attentiste = style == StyleMPA.ATTENTISTE
    if cheval.ratio_final is not None:
        if cheval.ratio_final > 1.05 and is_meneur:
            t3 += 3
        if cheval.ratio_final < 0.95 and is_attentiste:
            t3 += 8
    if cheval.hist_montee_avg is not None:
        if cheval.hist_montee_avg <= 3 and is_meneur:
            t3 += 10
        if cheval.hist_montee_avg >= 8 and is_attentiste:
            t3 += 8

    t4 = 0.0
    if cheval.changement_driver:
        t4 -= 10
    if cheval.changement_entraineur:
        t4 -= 5
    if cheval.changement_attelage:
        t4 -= 8
    if cheval.ferrure_changes >= 1:
        t4 -= 3

    t5 = 0.0
    hippo = (race.hippodrome or "").upper()
    if hippo == "VINCENNES" and num == 9 and cheval.position_ligne == "1ere_ligne":
        t5 = -6

    t6 = 0.0
    if hippo in _TACT_LIGNES_RESTREINTES and num is not None and num > 7:
        t6 = -4

    total = t1 + t2 + t3 + t4 + t5 + t6
    if race.depart == Depart.VOLTE:
        total *= 0.8
    flags.append("TACT_TROT")
    return total


def _tact_plat(cheval: Cheval, race: RaceContext, flags: Flags) -> float:
    """Plat : corde (n° de stalle) × distance + style + poids relatif + changements."""
    flags.append("TACT_PLAT")
    style = cheval.style_mpa
    # En plat FR le n° de partant ≈ corde/stalle
    corde = cheval.numero if cheval.numero and cheval.numero > 0 else None
    dist = race.distance_m or 0
    n_part = race.partants_confirmes or 0

    # --- Impact corde selon distance (critique sprint, faible fond) ---
    if dist <= 0:
        dist_w = 0.50
        flags.append("TACT_PLAT_DIST_ABSENTE")
    elif dist <= 1300:
        dist_w = 1.00
        flags.append("TACT_PLAT_SPRINT_CORDE_CRITIQUE")
    elif dist <= 1800:
        dist_w = 0.75
        flags.append("TACT_PLAT_MILE_CORDE")
    elif dist <= 2200:
        dist_w = 0.40
    else:
        dist_w = 0.20
        flags.append("TACT_PLAT_FOND_CORDE_FAIBLE")

    t_corde = 0.0
    if corde is not None:
        is_meneur = style in (StyleMPA.MENEUR_FORT, StyleMPA.MENEUR_MODERE)
        is_finisseur = style in (StyleMPA.ATTENTISTE, StyleMPA.CHASSEUR)
        # Corde basse favorable en sprint ; corde 1 risque enfermement si gros champ
        if corde <= 3:
            t_corde = 10.0 if is_meneur else 7.0
            if n_part >= 14 and corde == 1:
                t_corde -= 3.0  # risque blocage
                flags.append("TACT_PLAT_CORDE1_GROS_CHAMP")
        elif corde <= 6:
            t_corde = 8.0 if is_meneur else 6.0
        elif corde <= 9:
            t_corde = 2.0
        elif corde <= 12:
            t_corde = -4.0 if is_meneur else -2.0
        else:
            t_corde = -10.0 if dist <= 1600 else -5.0
            flags.append("TACT_PLAT_CORDE_HAUTE")
        t_corde *= dist_w

    # Terrain lourd : biais corde intérieure parfois inversé → atténuer t_corde
    try:
        from app.engine.common import terrain_category
        cat, _ = terrain_category(getattr(race, "penetrometre", None))
        if cat in ("LOURD", "TRES_LOURD") and t_corde > 0:
            t_corde *= 0.55
            flags.append("TACT_PLAT_TERRAIN_LOURD_CORDE_ATTENUE")
        elif cat in ("LOURD", "TRES_LOURD") and t_corde < 0 and corde and corde >= 10:
            t_corde *= 0.70  # extérieur moins pénalisé sur lourd
            flags.append("TACT_PLAT_TERRAIN_LOURD_EXT_MOINS_PENAL")
    except Exception:
        pass

    # --- Poids relatif (handicap) ---
    t_poids = 0.0
    p = cheval.poids_actuel_kg
    pmin = cheval.poids_min_champ_kg
    pmax = cheval.poids_max_champ_kg
    pmoy = cheval.poids_moyen_champ_kg
    if p is not None and pmoy is not None and pmoy > 0:
        delta = float(pmoy) - float(p)  # positif = plus léger que la moyenne
        t_poids = clamp(-8.0, 8.0, delta * 1.2)
        if pmin is not None and abs(float(p) - float(pmin)) < 0.3:
            t_poids += 2.0
            flags.append("TACT_PLAT_POIDS_MIN_CHAMP")
        flags.append("TACT_PLAT_POIDS_RELATIF")
    elif p is not None and pmax is not None and pmin is not None and pmax > pmin:
        # position dans la fourchette
        rel = (float(pmax) - float(p)) / max(float(pmax) - float(pmin), 0.1)
        t_poids = clamp(-6.0, 6.0, (rel - 0.5) * 10.0)

    # --- Style × rythme (léger, MPA porte le gros) ---
    t_style = 0.0
    rythme = race.rythme_projete or ""
    if style == StyleMPA.MENEUR_FORT and rythme in ("LENT", "CONTROLE"):
        t_style = 4.0
    elif style == StyleMPA.ATTENTISTE and rythme in ("RAPIDE", "TRES_RAPIDE"):
        t_style = 4.0
    elif style == StyleMPA.MENEUR_FORT and rythme in ("RAPIDE", "TRES_RAPIDE"):
        t_style = -3.0

    # --- Changements ---
    t_chg = 0.0
    if cheval.changement_driver:
        t_chg -= 6.0
        flags.append("TACT_PLAT_CHG_JOCKEY")
    if cheval.changement_entraineur:
        t_chg -= 3.0

    # Gros peloton
    t_field = -2.0 if n_part >= 16 else (-1.0 if n_part >= 14 else 0.0)

    total = t_corde + t_poids + t_style + t_chg + t_field
    return total


def _tact_obstacle(cheval: Cheval, race: RaceContext, flags: Flags) -> float:
    """Haies / steeple / cross : corde quasi neutre ; poids, expérience, style, jockey."""
    disc = getattr(race.discipline, "value", str(race.discipline or "")).upper()
    if "STEEP" in disc:
        flags.append("TACT_STEEPLE")
        exp_bonus_scale = 1.15
    elif "HAIE" in disc:
        flags.append("TACT_HAIES")
        exp_bonus_scale = 1.05
    else:
        flags.append("TACT_OBSTACLE")
        exp_bonus_scale = 1.00

    # Corde : impact faible (longue distance, trajectoire dictée par obstacles)
    t_corde = 0.0
    corde = cheval.numero if cheval.numero and cheval.numero > 0 else None
    dist = race.distance_m or 0
    if corde is not None and dist > 0 and dist < 3200:
        if corde <= 4:
            t_corde = 2.0
        elif corde >= 12:
            t_corde = -2.0
    # sinon négligeable

    # Poids relatif (très important en obstacle handicap)
    t_poids = 0.0
    p = cheval.poids_actuel_kg
    pmoy = cheval.poids_moyen_champ_kg
    if p is not None and pmoy is not None and pmoy > 0:
        delta = float(pmoy) - float(p)
        t_poids = clamp(-10.0, 10.0, delta * 1.5)
        flags.append("TACT_OBS_POIDS_RELATIF")

    # Expérience (nb courses) — sauteurs confirmés
    t_exp = 0.0
    nb = cheval.nb_courses
    if nb is not None:
        if nb >= 20:
            t_exp = 6.0 * exp_bonus_scale
            flags.append("TACT_OBS_EXP_FORTE")
        elif nb >= 10:
            t_exp = 3.5 * exp_bonus_scale
        elif nb <= 3:
            t_exp = -5.0
            flags.append("TACT_OBS_PEU_EXPERIMENTE")

    # Style : meneurs moins favorisés sur longs steeple ; attentistes OK
    t_style = 0.0
    style = cheval.style_mpa
    if "STEEP" in disc and dist >= 4000:
        if style == StyleMPA.MENEUR_FORT:
            t_style = -3.0
        elif style == StyleMPA.ATTENTISTE:
            t_style = 3.0
    elif "HAIE" in disc:
        if style in (StyleMPA.MENEUR_MODERE, StyleMPA.POLYVALENT):
            t_style = 2.0

    # Changements jockey (critique obstacle)
    t_chg = 0.0
    if cheval.changement_driver:
        t_chg -= 8.0
        flags.append("TACT_OBS_CHG_JOCKEY")
    if cheval.changement_entraineur:
        t_chg -= 4.0

    # Ferrure / équipement
    t_eq = 0.0
    if cheval.ferrure_changes >= 1:
        t_eq -= 2.0

    total = t_corde + t_poids + t_exp + t_style + t_chg + t_eq
    return total


def module_g_tact(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    """TACT multi-disciplines → tact_score ∈ [-50, 50]."""
    flags: Flags = []
    bucket = disc_bucket(race.discipline)

    if bucket == "TROT":
        total = _tact_trot(cheval, race, flags)
    elif bucket == "PLAT":
        total = _tact_plat(cheval, race, flags)
    elif bucket == "OBSTACLE":
        total = _tact_obstacle(cheval, race, flags)
    else:
        flags.append("TACT_DISCIPLINE_INCONNUE")
        return 0.0, flags

    return clamp(-50, 50, total), flags


def tact_mult(tact_score: float) -> float:
    """Multiplicateur ordre_final. Amplitude réduite (A1) car tact entre aussi en PCH."""
    return clamp(0.85, 1.15, 1.0 + tact_score / 150.0)


# ---------------------------------------------------------------------------
# MODULE H -- POIDS (PLAT HANDICAP)
# ---------------------------------------------------------------------------

def module_h_poids(cheval: Cheval, race: RaceContext, champ: List[Cheval]) -> Tuple[float, Flags]:
    flags: Flags = []
    if race.discipline != Discipline.PLAT or race.type_course != TypeCourse.HANDICAP:
        return 0.0, flags
    if cheval.poids_actuel_kg is None:
        return 0.0, ["POIDS_MANQUANT"]

    poids = cheval.poids_actuel_kg
    poids_moy = champ_mean([c.poids_actuel_kg for c in champ]) or poids
    poids_min = min([c.poids_actuel_kg for c in champ if c.poids_actuel_kg is not None], default=poids)
    poids_max = max([c.poids_actuel_kg for c in champ if c.poids_actuel_kg is not None], default=poids)

    c1 = 10 if 52 <= poids <= 56 else 5 if 56 < poids <= 58 else -8 if poids > 59 else 3 if poids < 51 else 0.0

    ecart = poids - poids_moy
    c2 = 12 if ecart < -4 else 6 if ecart < -2 else -10 if ecart > 4 else -5 if ecart > 2 else 0.0

    c3 = 0.0
    if cheval.valeur_pmu is not None and cheval.valeur_pmu_precedente is not None and \
       cheval.poids_precedent_kg is not None:
        dvaleur = cheval.valeur_pmu - cheval.valeur_pmu_precedente
        dpoids = poids - cheval.poids_precedent_kg
        if dvaleur > 0 and dpoids <= 1:
            c3 = 15
        elif dvaleur > 0 and dpoids > 3:
            c3 = -3
        elif dvaleur < 0 and dpoids < -1:
            c3 = 8
        elif dvaleur < 0 and dpoids > 0:
            c3 = -5

    c4 = 0.0
    if (poids_max - poids_min) > 8 and poids <= poids_min + 2:
        c4 = 8

    brut = c1 + c2 + c3 + c4

    # v1.29.16 (port Grok, walk-forward) — atténuer les pénalités poids
    # extrêmes (module déjà PLAT+HANDICAP uniquement, cf. garde ci-dessus).
    if brut < 0:
        brut *= 0.75
        flags.append("POIDS_ATTENUATION_MALUS_PLAT")

    # Modulation hippodrome (RAH-103, RAH-104)
    hippo = race.hippodrome.upper()
    piste = (race.terrain_qualificatif or "").upper()
    top_weight = poids >= poids_moy + 2
    if hippo in ("LONGCHAMP", "PARISLONGCHAMP", "CHANTILLY") and top_weight and \
       cheval.valeur_pmu is not None and champ_mean([c.valeur_pmu for c in champ]) is not None and \
       cheval.valeur_pmu >= champ_mean([c.valeur_pmu for c in champ]) + 3:
        if hippo != "CHANTILLY" or "PSF" in piste:
            brut += 2
            flags.append("RAH103_ATTENUATION_OPEN_STRETCH")

    if hippo == "CHANTILLY" and race.distance_m >= 2000 and race.type_course == TypeCourse.HANDICAP and top_weight:
        brut *= 1.5
        flags.append("RAH104_CHANTILLY_MAJORATION")

    if race.distance_m < 1600:
        cap_final = 25
    elif race.distance_m < 2000:
        cap_final = 20
    elif race.distance_m < 2400:
        cap_final = 15
    else:
        cap_final = 10
    if cap_final < 25:
        flags.append("POIDS_DEGRESSIVITE_FOND")

    # Atténuation (20/09/2026) : malus POIDS trop agressifs sur cotes 15-40
    # quand historique poids/valeur absent (cas LESSLEPASSER / ROYALWOOD).
    cote = cheval.cote_matin
    if (brut < -6 and cote is not None and 15.0 <= cote <= 40.0
            and cheval.poids_precedent_kg is None):
        brut = brut * 0.55
        flags.append("POIDS_MALUS_ATTENUE_MIDCOTE_SANS_HISTO")

    return clamp(-20, cap_final, brut), flags


# ---------------------------------------------------------------------------
# MODULE I -- MODULE_RECUL (TROT HANDICAP uniquement)
# ---------------------------------------------------------------------------
def module_i_recul(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    flags: Flags = []
    if disc_bucket(race.discipline) != "TROT":
        return 0.0, flags
    # Appliquer dès que recul connu (GNT parfois mal typé hors HANDICAP)
    if race.type_course != TypeCourse.HANDICAP and (cheval.recul_m or 0) == 0:
        return 0.0, flags
    if cheval.recul_m is None:
        return 0.0, ["RECUL_MANQUANT"]

    recul = cheval.recul_m
    # v1.29.32 — calibrage terrain : 0m avantage, +25m compensable, +50m très pénalisant
    # (Fréquence-Turf / analyses trot : ~0.8s/km par 25m à rattraper)
    if recul <= 0:
        c1 = 16.0
    elif recul <= 25:
        c1 = 2.0   # léger, pas un bonus fort (souvent les meilleurs gains)
    elif recul <= 50:
        c1 = -12.0  # lourd — était -5, trop doux
    else:
        c1 = -18.0

    c2 = 0.0
    if cheval.rk_champ_median_sec is not None and cheval.rk_derniere_sec is not None and recul > 0:
        superiority = cheval.rk_champ_median_sec - cheval.rk_derniere_sec
        if superiority > 0:
            metres_compenses = superiority * 25
            c2 = clamp(0, 12, metres_compenses / recul * 12)
        else:
            c2 = clamp(-8, 0, superiority * 5)

    c3 = 0.0
    if cheval.historique_recul:
        similaires = [p.rang for p in cheval.historique_recul if abs(p.valeur - recul) <= 12]
        if similaires:
            avg = mean(similaires)
            c3 += 8 if avg <= 3 else 4 if avg <= 5 else -8 if avg >= 7 else 0.0
        derniers3 = [p.valeur for p in cheval.historique_recul[-3:]]
        if len(derniers3) == 3:
            m3 = mean(derniers3)
            c3 += 8 if recul < m3 else -5 if recul > m3 else 0.0

    coeff_geo = _RECUL_COEFF_GEO.get(race.hippodrome.upper(), 1.0)
    return clamp(-20, 20, c1 + c2 + c3) * coeff_geo, flags


# ---------------------------------------------------------------------------
# MODULE J -- MODULE_TERRAIN_DYN (toutes disciplines)
# ---------------------------------------------------------------------------
def module_j_terrain(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    flags: Flags = []
    if race.penetrometre is None:
        return 0.0, ["PENETROMETRE_ABSENT"]

    categorie, _ = terrain_category(race.penetrometre)

    c1 = 0.0
    if cheval.historique_terrain:
        proches = [p.rang for p in cheval.historique_terrain if abs(p.valeur - race.penetrometre) < 1.0]
        if proches:
            avg = mean(proches)
            c1 = 15 if avg <= 2 else 8 if avg <= 4 else 2 if avg <= 6 else -12 if avg >= 8 else 0.0
            if len(proches) >= 5:
                var = sum((x - avg) ** 2 for x in proches) / len(proches)
                if var < 2.5:
                    c1 += 5

    c2 = 0.0
    style = cheval.style_mpa
    lourd = categorie in ("LOURD", "TRES_LOURD")
    leger = categorie in ("LEGER", "TRES_LEGER")
    is_meneur = style in (StyleMPA.MENEUR_FORT, StyleMPA.MENEUR_MODERE)
    is_attentiste = style == StyleMPA.ATTENTISTE
    if lourd and race.distance_m >= 2000 and is_attentiste:
        c2 += 8
    if lourd and race.distance_m < 1600 and is_meneur:
        c2 -= 6
    if lourd and race.distance_m >= 1600 and is_meneur:
        c2 -= 3
    if leger and race.distance_m < 1600 and is_meneur:
        c2 += 8
    if leger and is_attentiste and race.distance_m < 1400:
        c2 -= 4

    c3 = 0.0
    corde = cheval.numero_autostart  # proxy corde si non distinct
    if corde is not None and corde <= 4:
        if lourd:
            c3 -= 5
        if leger:
            c3 += 3

    total = clamp(-15, 15, c1 + c2 + c3)

    malus_decouverte = 0.0
    if cheval.historique_terrain is not None and len(cheval.historique_terrain) == 0:
        malus_decouverte = -3
        flags.append("DECOUVERTE_HIPPODROME_ATYPIQUE")

    return total + malus_decouverte, flags


# ---------------------------------------------------------------------------
# MODULE K -- MODULE_DIST_ADAPT (toutes disciplines)
# ---------------------------------------------------------------------------
def module_k_dist_adapt(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    flags: Flags = []
    if not cheval.historique_distance:
        return 0.0, ["HISTORIQUE_DISTANCE_ABSENT"]

    dist = race.distance_m
    exactes = [p.rang for p in cheval.historique_distance if abs(p.valeur - dist) <= 50]
    c1 = 0.0
    if len(exactes) >= 3:
        avg = mean(exactes)
        c1 = 15 if avg <= 2 else 8 if avg <= 4 else -10 if avg >= 7 else 0.0
    elif len(exactes) == 1:
        c1 = 5 if exactes[0] <= 3 else -4 if exactes[0] >= 7 else 0.0

    c2 = 0.0
    if cheval.distance_habituelle_m is not None:
        delta = abs(dist - cheval.distance_habituelle_m)
        c2 = -12 if delta > 400 else -6 if delta > 200 else 3 if delta <= 100 else 0.0

    c3 = 0.0
    if not exactes:
        larges = [p.rang for p in cheval.historique_distance if abs(p.valeur - dist) <= 200]
        if larges:
            avg = mean(larges)
            c3 = 5 if avg <= 3 else -5 if avg >= 7 else 0.0

    # COMP-4/COMP-5 nécessitent un historique par parcours exact (hippodrome+distance) ;
    # non modélisés séparément dans ce MVP -> laissés à 0 avec flag informatif.
    c4 = 0.0
    c5 = 0.0
    flags.append("DIST_COMP4_COMP5_NON_EVALUES")

    return clamp(-15, 15, c1 + c2 + c3 + c4 + c5), flags


# ---------------------------------------------------------------------------
# MODULE L -- MPA_CHAMP (projection rythme)
# ---------------------------------------------------------------------------
_MPA_MATRIX = {
    # (style, rythme) -> valeur
    ("MENEUR_FORT", "LENT"): 15, ("MENEUR_FORT", "CONTROLE"): 10, ("MENEUR_FORT", "MODERE"): 0,
    ("MENEUR_FORT", "RAPIDE"): -12, ("MENEUR_FORT", "TRES_RAPIDE"): -18,
    ("MENEUR_MODERE", "LENT"): 12, ("MENEUR_MODERE", "CONTROLE"): 8, ("MENEUR_MODERE", "MODERE"): 3,
    ("MENEUR_MODERE", "RAPIDE"): -7, ("MENEUR_MODERE", "TRES_RAPIDE"): -11,
    ("ATTENTISTE", "TRES_RAPIDE"): 18, ("ATTENTISTE", "RAPIDE"): 10, ("ATTENTISTE", "MODERE"): 5,
    ("ATTENTISTE", "CONTROLE"): -3, ("ATTENTISTE", "LENT"): -10,
    ("CHASSEUR", "TRES_RAPIDE"): 15, ("CHASSEUR", "RAPIDE"): 8, ("CHASSEUR", "MODERE"): 3,
    ("CHASSEUR", "LENT"): 2, ("CHASSEUR", "CONTROLE"): 4,
    ("POLYVALENT", "LENT"): 3, ("POLYVALENT", "CONTROLE"): 3, ("POLYVALENT", "MODERE"): 4,
    ("POLYVALENT", "RAPIDE"): 4, ("POLYVALENT", "TRES_RAPIDE"): 5,
}


def rythme_projete(nb_meneurs: int) -> str:
    if nb_meneurs == 0:
        return "LENT"
    if nb_meneurs == 1:
        return "CONTROLE"
    if nb_meneurs == 2:
        return "MODERE"
    if nb_meneurs <= 4:
        return "RAPIDE"
    return "TRES_RAPIDE"


def module_l_mpa_champ(cheval: Cheval, race: RaceContext) -> Tuple[float, Flags]:
    flags: Flags = []
    style = cheval.style_mpa
    rythme = race.rythme_projete
    style_conf = float(getattr(cheval, "style_mpa_confidence", 0.0) or 0.0)
    # Si style absent, tenter dérivation légère (sans inventer un rythme)
    if style is None:
        try:
            from app.engine.common import derive_style_mpa
            st, conf, _, st_flags = derive_style_mpa(cheval)
            if st is not None:
                style = st
                style_conf = max(style_conf, float(conf or 0.0))
                flags.extend(list(st_flags or [])[:3])
                flags.append("MPA_STYLE_DERIVE")
        except Exception:
            pass
    if style is None or rythme is None:
        return 0.0, ["MPA_STYLE_OU_RYTHME_MANQUANT"]

    compat = _MPA_MATRIX.get((style.value, rythme), 0.0)
    # Priorité 3 : style peu confiant → écraser l'amplitude (surtout malus)
    if style_conf <= 0:
        if compat < 0:
            compat *= _calib_mult("VANTAGE_MPA_UNKNOWN_CONF_MULT", 0.50)
            flags.append("MPA_STYLE_CONFIANCE_INCONNUE_MALUS_ATTENUE")
        elif compat > 0:
            flags.append("MPA_STYLE_CONFIANCE_INCONNUE_POSITIF_CONSERVE")
    elif style_conf < 0.45:
        compat *= 0.55
        flags.append("MPA_STYLE_CONFIANCE_FAIBLE")
    elif style_conf > 0 and style_conf < 0.65:
        compat *= 0.80
        flags.append("MPA_STYLE_CONFIANCE_MOYENNE")

    if race.distance_m >= 2400:
        impact = 0.65
    elif race.distance_m >= 1800:
        impact = 0.80
    elif race.distance_m >= 1400:
        impact = 0.90
    else:
        impact = 1.00

    # v1.29.16 (port Grok, discipline) — plat/obstacles : MPA moins
    # discriminant (walk-forward). Structurel : s'applique une seule fois,
    # sur `impact` (donc sur `brut` ci-dessous), avant toute réduction
    # par-cheval.
    disc = getattr(race.discipline, "value", str(race.discipline or ""))
    if "PLAT" in disc.upper():
        impact *= 0.70
        flags.append("MPA_ATTENUATION_PLAT")
    elif any(x in disc.upper() for x in ("HAIES", "STEEPLE", "OBSTACLE", "CROSS")):
        impact *= 0.55
        flags.append("MPA_ATTENUATION_OBSTACLE")

    brut = clamp(-20, 20, compat * impact)

    # v1.29.34 — sans pénétromètre / terrain fiable, le mismatch rythme est
    # trop spéculatif (Chantilly/Argentan : MPA_CHAMP a pénalisé des arrivés
    # Top5). Atténue fortement la partie négative uniquement.
    if getattr(race, "penetrometre", None) is None:
        if brut < 0:
            brut *= _calib_mult("VANTAGE_MPA_NO_PENETRO_MULT", 0.20)
            flags.append("MPA_ATTENUATION_SANS_PENETRO")
        else:
            flags.append("MPA_SANS_PENETRO_POSITIF_CONSERVE")

    # v1.29.16 (retravaillé, port Grok) — Grok empilait 3 atténuations
    # multiplicatives indépendantes (historique cheval x0.50, PUIS tranche
    # marché x0.45/0.60/0.85) : pour un jeune meneur favori en rythme
    # rapide, le malus finissait à ~16% de sa valeur d'origine -- le
    # module devenait quasi silencieux exactement pour les favoris
    # tactiquement à risque, la population qu'il est censé surveiller le
    # plus. Correction : on ne retient que la réduction la PLUS FORTE
    # parmi les critères applicables (jamais leur produit). Chaque
    # critère reste un vrai signal, mais un seul s'applique à la fois.
    reduction_candidates: list = []  # (facteur, flag) -- + petit facteur = réduction + forte

    if cheval.age is not None and cheval.age <= 4 and style == StyleMPA.MENEUR_FORT and rythme == "TRES_RAPIDE":
        reduction_candidates.append((0.50, "MPA_REDUCTION_JEUNE"))
    elif (style in (StyleMPA.MENEUR_FORT, StyleMPA.MENEUR_MODERE) and cheval.position_mi_course_hist and
          mean(cheval.position_mi_course_hist[-5:]) <= 2 and cheval.nb_courses and cheval.nb_courses > 5 and
          rythme in ("RAPIDE", "TRES_RAPIDE")):
        reduction_candidates.append((0.50, "MPA_REDUCTION_VRAI_CHEVAL_DE_TRAIN"))

    # v1.29.16 (port Grok) — dossier marché : ne pas écraser un favori ou
    # semi-favori sur un seul mismatch rythme.
    cote = cheval.cote_avant_course if cheval.cote_avant_course is not None else cheval.cote_matin
    if brut < 0 and cote is not None and cote > 0:
        if cote < 9.0:
            reduction_candidates.append((0.45, "MPA_ATTENUATION_T1_MARCHE"))
        elif cote < 15.0:
            reduction_candidates.append((0.60, "MPA_ATTENUATION_T2_MARCHE"))
        else:
            reduction_candidates.append((0.75, "MPA_ATTENUATION_OUTSIDER_LEGERE"))

    if reduction_candidates:
        facteur, flag_applique = min(reduction_candidates, key=lambda x: x[0])
        ajuste = clamp(-20, 20, brut * facteur)
        flags.append(flag_applique)
        if len(reduction_candidates) > 1:
            autres = [f for fa, f in reduction_candidates if f != flag_applique]
            flags.append(f"MPA_REDUCTION_NON_CUMULEE_ignores={','.join(autres)}")
    else:
        ajuste = brut

    # v1.29.16 (port Grok) — plafond des malus MPA (symétrique soft sur le négatif)
    if ajuste < -10:
        ajuste = -10.0
        flags.append("MPA_PLAFOND_MALUS_10")

    # Flags explicites de match/mismatch (levier 3 -- lisibles dans audits)
    if ajuste >= 10:
        flags.append("MPA_MATCH_FORT")
    elif ajuste <= -10:
        flags.append("MPA_MISMATCH_FORT")
    # Modulation GRU hippodrome-spécifique : déléguée à la couche LLM (fiches
    # 22 hippodromes trop volumineuses pour être hardcodées ici) -- ajoutée
    # séparément dans pch_final.py comme partie du bloc "discipline_specifique".
    return clamp(-20, 20, ajuste), flags


# ---------------------------------------------------------------------------
# MODULE M -- CRE v2 (Chrono Relatif) + PROXY CRE v3
# ---------------------------------------------------------------------------
_TERRAIN_COEFF = {"TRES_LEGER": 1.08, "LEGER": 1.04, "STANDARD": 1.00, "LOURD": 0.95, "TRES_LOURD": 0.88}


def module_m_cre(cheval: Cheval, race: RaceContext, champ: List[Cheval] = None) -> Tuple[float, Flags]:
    flags: Flags = []
    categorie, _ = terrain_category(race.penetrometre)
    coeff = _TERRAIN_COEFF.get(categorie, 1.00)

    if cheval.chrono_200m is not None and cheval.champ_median_chrono_200m is not None:
        chrono_norm = cheval.chrono_200m * coeff
        champ_norm = cheval.champ_median_chrono_200m * coeff
        superiority = champ_norm - chrono_norm
        if superiority > 0.8:
            return 18.0, flags
        if superiority > 0.5:
            return 12.0, flags
        if superiority > 0.2:
            return 6.0, flags
        if superiority >= -0.2:
            return 0.0, flags
        if superiority >= -0.5:
            return -6.0, flags
        return -12.0, flags

    # PROXY CRE v3 (TROT, >= 3 RK)
    if disc_bucket(race.discipline) == "TROT" and cheval.rk_array_3_derniers_sec and \
            len(cheval.rk_array_3_derniers_sec) == 3:
        incidents = cheval.rk_incident_flag or [False, False, False]
        if any(incidents):
            flags.append("CRE_PROXY_INCIDENTS_EXCLUS")
            return 0.0, flags
        rk = cheval.rk_array_3_derniers_sec
        delta12 = rk[1] - rk[0]
        delta23 = rk[2] - rk[1]
        delta_moy = 0.40 * delta12 + 0.60 * delta23
        coherente = (delta12 > 0 and delta23 > 0) or (delta12 < 0 and delta23 < 0)

        if delta_moy >= 0.60 and coherente:
            val = 14.0
        elif delta_moy >= 0.40:
            val = 10.0
        elif delta_moy >= 0.20:
            val = 6.0
        elif -0.15 <= delta_moy < 0.20:
            val = 0.0
        elif -0.40 <= delta_moy < -0.15:
            val = -4.0
        elif delta_moy < -0.40 and coherente:
            val = -10.0
        else:
            val = -6.0

        if not coherente and delta_moy > 0:
            val *= 0.70

        flags.append("CRE_PROXY_v3")
        return clamp(-12, 18, val), flags

    # PROXY CRE v4 (TROT, Record -- ajouté le 07/08/2026, source Zone-Turf).
    # Le Record trot est conventionnellement une réduction kilométrique
    # (temps/km), directement comparable entre chevaux quelle que soit la
    # distance à laquelle il a été établi -- pas besoin de renormaliser.
    # Plafond volontairement réduit (+-8 au lieu de +-12/18 pour les
    # paliers ci-dessus) : un record peut dater de plusieurs saisons et
    # dit plus sur le potentiel brut que sur la forme actuelle -- signal
    # plus faible que RK (récent) ou chrono_200m (course en cours).
    if (disc_bucket(race.discipline) == "TROT" and cheval.record_chrono_sec is not None and champ):
        records_champ = [c.record_chrono_sec for c in champ if c.record_chrono_sec is not None]
        if len(records_champ) >= 3:
            records_champ.sort()
            mediane = records_champ[len(records_champ) // 2]
            superiority = mediane - cheval.record_chrono_sec  # positif = record plus rapide que la médiane
            if superiority > 1.5:
                val = 8.0
            elif superiority > 0.8:
                val = 5.0
            elif superiority > 0.3:
                val = 2.0
            elif superiority >= -0.3:
                val = 0.0
            elif superiority >= -0.8:
                val = -2.0
            else:
                val = -5.0
            flags.append("CRE_PROXY_v4_RECORD")
            return val, flags

    # PROXY v5 : régularité musique (PMU toujours dispo) — bonus/malus léger
    try:
        from app.engine.musique_features import calculer_forme, calculer_regularite
        forme = calculer_forme(cheval.musique)
        reg = calculer_regularite(cheval.musique)
        if forme >= 0.75 and reg >= 0.65:
            flags.append("CRE_PROXY_v5_MUSIQUE")
            return 4.0, flags
        if forme <= 0.30 and reg <= 0.40:
            flags.append("CRE_PROXY_v5_MUSIQUE_FAIBLE")
            return -3.0, flags
    except Exception:
        pass

    flags.append("CRE_DESACTIVE")
    return 0.0, flags


# ---------------------------------------------------------------------------
# MODULE N -- H2H_GRAPH (informatif -- alimente COMPOSITE, pas PCH)
# ---------------------------------------------------------------------------
def module_n_h2h(cheval: Cheval, champ: List[Cheval]) -> Tuple[float, Flags]:
    """Retourne h2h_norm ∈ [-1, 1]. Version simplifiée : utilise les
    confrontations directes déclarées (Bloc N) ; H2H-02/03 (bipartite,
    style tactique) et H2H-04 (tandem) sont approximés via le style MPA
    et les statistiques tandem déjà collectées ailleurs."""
    flags: Flags = []
    if not cheval.confrontations_directes:
        # repli sur H2H-04 (taux tandem) si disponible
        td = cheval.tandem_driver_cheval
        if td and td.courses_ensemble >= 3:
            taux = (td.victoires_ensemble + td.places_top5_ensemble) / max(td.courses_ensemble, 1)
            coeff_nb = min(1.0, td.courses_ensemble / 10)
            if taux >= 0.70 and td.courses_ensemble >= 10:
                val = 10 * coeff_nb
            elif taux >= 0.60 and td.courses_ensemble >= 5:
                val = 6 * coeff_nb
            elif taux >= 0.50:
                val = 3 * coeff_nb
            else:
                val = 0.0
            return clamp(-1.0, 1.0, val / 15), flags
        return 0.0, ["H2H_ABSENT"]

    scores = []
    for conf in cheval.confrontations_directes:
        weight = conf.get("weight", 1.0)
        rang = conf.get("rang", None)
        if rang == 1:
            scores.append(10 * weight)
        elif rang and rang <= 3:
            scores.append(2 * weight)
        else:
            scores.append(-2 * weight)
    if not scores:
        return 0.0, flags
    h2h_avg = mean(scores)
    return clamp(-1.0, 1.0, h2h_avg / 15), flags


# ---------------------------------------------------------------------------
# MODULE O -- OVERBET_DETECTOR (appliqué en 2e passe, cf pch_final.py)
# ---------------------------------------------------------------------------
def module_o_overbet(cheval: Cheval, ordre_score_initial: float, nb_partants: int,
                      allocation_eur: Optional[float]) -> Tuple[float, float, Flags, Optional[float]]:
    """Retourne (delta_pch, delta_tocard, flags, ecart). À appeler APRÈS le calcul
    de ORDRE_SCORE_initial (anti-circularité, séquence Étape A-D). ecart
    (ajouté le 02/09/2026, pour Ghost D40) est None si non calculable."""
    flags: Flags = []
    cote = cheval.cote_avant_course or cheval.cote_matin
    if cote is None or ordre_score_initial <= 0:
        return 0.0, 0.0, flags, None

    cote_theorique = 1 / max(ordre_score_initial * 0.80, 1e-6)
    ecart = (cote_theorique - cote) / cote_theorique
    seuil = 0.10 if (allocation_eur is not None and allocation_eur <= 50000) else 0.15

    delta_pch = 0.0
    delta_tocard = 0.0

    if ecart >= seuil and ordre_score_initial < 0.50:
        delta_pch -= 12
        delta_tocard -= 0.08
        flags.append("OVERBET_SURCOTE")
    elif ecart <= -seuil:
        delta_pch += 6
        delta_tocard += 0.08
        flags.append("OVERBET_SOUSCOTE")
    else:
        flags.append("OVERBET_NEUTRE")

    icp = cheval.icp_pondere or 0.0
    if icp >= 3.0 and ordre_score_initial <= 0.50 and cote / max(ordre_score_initial, 1e-6) < 1.5:
        delta_pch -= 8
        delta_tocard = max(0.0, delta_tocard - 0.05)
        flags.append("OVERBET_MEDIA")

    if (cheval.cote_avant_course and cheval.cote_matin and
            cheval.cote_avant_course >= 2 * cheval.cote_matin):
        delta_pch = min(delta_pch, -12)
        flags.append("OVERBET_DRIFT_EXTREME")

    delta_tocard = clamp(-1.0, 1.0, delta_tocard)
    return delta_pch, delta_tocard, flags, ecart


# ---------------------------------------------------------------------------
# MODULE P -- TANDEM_BONUS
# ---------------------------------------------------------------------------
def _tandem_contrib(stats) -> Tuple[float, Flags]:
    if stats is None or stats.courses_ensemble < 3:
        return 0.0, ["TANDEM_INSUFFISANT"]
    taux = (stats.victoires_ensemble + stats.places_top5_ensemble) / max(stats.courses_ensemble, 1)
    coeff_nb = min(1.0, stats.courses_ensemble / 10)
    if taux >= 0.65 and stats.courses_ensemble >= 10:
        raw = 15.0
    elif taux >= 0.50 and stats.courses_ensemble >= 5:
        raw = 10.0
    elif taux >= 0.35 and stats.courses_ensemble >= 3:
        raw = 6.0
    else:
        raw = 0.0
    contrib = raw * coeff_nb

    # RAH-253 (porté depuis hardened_complete, 11/09/2026) : échantillon <8
    # courses ensemble -> plafond +5, quel que soit le taux. coeff_nb seul
    # ne suffisait pas à l'empêcher (ex. 7 courses à taux>=0,50 donnait
    # 10 x 0,7 = 7,0, au-dessus du plafond). Correction indépendante du
    # coeff_temps ci-dessous, appliquée sur la contribution brute*coeff_nb.
    if stats.courses_ensemble < 8 and contrib > 5.0:
        contrib = 5.0
        flags: Flags = ["RAH253_TANDEM_CAP_ECHANTILLON"]
    else:
        flags = []

    delai = stats.jours_depuis_derniere_association
    if delai is None:
        coeff_temps = 0.70
        flags.append("TANDEM_DELAI_INCONNU")
    elif delai <= 60:
        coeff_temps = 1.00
    elif delai <= 120:
        coeff_temps = 0.80
    elif delai <= 180:
        coeff_temps = 0.60
    elif delai <= 365:
        coeff_temps = 0.40
        flags.append("TANDEM_ANCIEN")
    else:
        coeff_temps = 0.20
        flags.append("TANDEM_TRES_ANCIEN")

    final = contrib * coeff_temps
    cap = 10 if stats.courses_ensemble < 5 else 15
    return min(final, cap), flags


def module_p_tandem(cheval: Cheval) -> Tuple[float, Flags]:
    flags: Flags = []
    val_a, flags_a = _tandem_contrib(cheval.tandem_driver_cheval)
    if cheval.driver_est_entraineur:
        return val_a, flags_a
    val_b, flags_b = _tandem_contrib(cheval.tandem_driver_ecurie)
    if val_b > val_a:
        return val_b, flags_b
    return val_a, flags_a
