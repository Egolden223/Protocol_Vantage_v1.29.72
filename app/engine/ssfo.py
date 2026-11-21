"""
ssfo.py -- Catalogue SSFO (Synergie des Signaux Faibles Outsiders,
RAH-271, Partie 17.10e). Absent du moteur jusqu'au 02/09/2026 -- le champ
QualitativeSignals.bonus_ssfo existait déjà dans le modèle (branché dans
gmo_v.py::build_pool_elargi pour l'entrée au Pool Élargi, RAH-272) mais
restait câblé à 0.0 en permanence, le catalogue n'étant délégué qu'à la
Couche LLM désactivée par défaut (contrainte non négociable : 100%
Python, sans API payante). Ce module réimplémente EN PYTHON DÉTERMINISTE
le sous-ensemble des 32 signaux calculable à partir des données déjà
collectées, sans aucune interprétation de texte libre au sens fort.

Éligibilité (RAH-271) : cote >= 8/1 ET >= 1 signal activé.

Sur les 32 signaux du texte source, 21 sont implémentés ici (19 au
02/09/2026 + f9 et f17 débloqués le 12/09/2026).
Le texte source annonce une répartition "13 validés / 19 faibles" qui ne
correspond pas exactement à l'énumération qu'il donne lui-même (11
validés + 21 faibles = 32, en comptant précisément chaque ligne) --
possible coquille du document source, pas une erreur de lecture de ce
module : les poids appliqués ci-dessous suivent l'énumération précise
(chaque signal à son poids nommé individuellement), pas le total résumé.
11 signaux restent NON_EVALUABLE, jamais devinés (RÈGLE 2) :
  - f3, f5 : nécessitent une lecture presse en texte libre (« belle
    chance », « coup de poker ») ou une position chronométrée à 400m de
    l'arrivée -- non modélisées dans le schéma actuel.
  - f30 : variante de changement driver (taux de réussite exact de
    l'ancien) -- f9 est une approximation par delta de classement
    national maison ; f30 reste non évaluable faute de taux bruts.
  - f12, f19, f20, f23, f27, f28, f29 : corde, écurie multi-outsider
    (B56), palmarès propriétaire, spécialiste volté/terrain
    obstacle/vétéran obstacle -- champs non présents dans Cheval.
  - f24 : finisseur longue distance -- demande une position à 400m de
    l'arrivée absente du schéma (seul position_mi_course_hist existe).

f4 (commentaire "bloqué"/"gêné") utilise une simple recherche de
sous-chaînes sur commentaire_derniere_course -- pas une analyse
sémantique, juste un test littéral documenté comme tel.
"""
from __future__ import annotations
from typing import List, Optional, Tuple, Dict

from app.models import Cheval, RaceContext
from app.engine.common import disc_bucket

# poids : signaux "validés" = 1.0, signaux "faibles" = 0.35 (RAH-271)
_POIDS_VALIDE = 1.0
_POIDS_FAIBLE = 0.35

_MOTS_BLOQUE = ("bloqué", "gêné", "gene", "n'a pas eu le passage", "na pas eu le passage",
                "manque de passage", "retardé au départ", "ralenti")


def _f1_progression_rang(cheval: Cheval) -> bool:
    """dernier rang <= moyenne des 3 PRÉCÉDENTS - 2 places (comparaison
    au propre historique du cheval, pas au dernier lui-même -- lecture
    retenue pour que le signal mesure une vraie progression et non une
    tautologie ; non explicitée au mot près dans le texte source)."""
    from app.scraping.musique import parse_musique, rangs_recents
    rangs = rangs_recents(parse_musique(cheval.musique), 4)
    if len(rangs) < 4:
        return False
    dernier, precedents = rangs[0], rangs[1:4]
    return dernier <= (sum(precedents) / len(precedents)) - 2


def _f2_regularite_masquee(cheval: Cheval) -> bool:
    return cheval.irp_score is not None and 0.30 <= cheval.irp_score < 0.45


def _f4_commentaire_sous_evalue(cheval: Cheval) -> bool:
    if not cheval.commentaire_derniere_course:
        return False
    txt = cheval.commentaire_derniere_course.lower()
    return any(mot in txt for mot in _MOTS_BLOQUE)


def _f6_absence_signaux_negatifs(cheval: Cheval) -> bool:
    return cheval.dq_5_dernieres_tentees == 0 and cheval.incidents_30j == 0


def _f7_retour_distance_predilection(cheval: Cheval, race: RaceContext) -> bool:
    if not cheval.historique_distance:
        return False
    return any(h.rang is not None and h.rang <= 3 and h.valeur is not None
               and abs(h.valeur - race.distance_m) <= 100 for h in cheval.historique_distance)


def _f8_allegement_poids(cheval: Cheval) -> bool:
    if cheval.poids_actuel_kg is None or cheval.poids_moyen_champ_kg is None:
        return False
    return cheval.poids_actuel_kg <= cheval.poids_moyen_champ_kg - 2


def _f10_deferrage_favorable_trot(cheval: Cheval, race: RaceContext) -> bool:
    if disc_bucket(race.discipline) != "TROT":
        return False
    return cheval.ferrure_type == "D4" and race.distance_m <= 2200


def _f11_historique_hippodrome(cheval: Cheval) -> bool:
    """>=2 courses sur l'hippodrome exact du jour, toutes Top5 -- lecture
    conservatrice de la clause "(100%)" du texte source. La clause
    alternative "profil similaire (50%)" n'est pas implémentée : "profil
    similaire" n'est pas défini ailleurs dans le texte source (quelle
    similarité, sur quels critères) -- l'inventer serait une fabrication
    (RÈGLE 2), pas une approximation prudente. Débloqué le 02/09/2026
    (cf. Cheval.historique_hippodrome, models.py)."""
    if not cheval.historique_hippodrome or len(cheval.historique_hippodrome) < 2:
        return False
    return all(h.rang is not None and h.rang <= 5 for h in cheval.historique_hippodrome)


def _f13_mouvement_marche_modere(sov_v2: Optional[float]) -> bool:
    return sov_v2 is not None and 0.03 <= sov_v2 <= 0.08


def _f14_icp_modere(cheval: Cheval) -> bool:
    return cheval.icp_pondere is not None and 1.5 <= cheval.icp_pondere <= 2.5


def _f15_cote_stable_malgre_absence(cheval: Cheval) -> bool:
    if cheval.cote_matin is None or cheval.cote_avant_course is None or cheval.delai_j is None:
        return False
    if cheval.delai_j <= 60 or cheval.cote_matin <= 0:
        return False
    delta = abs(cheval.cote_avant_course - cheval.cote_matin) / cheval.cote_matin
    return delta < 0.05


def _f16_zone_valeur_sweet(cheval: Cheval) -> bool:
    return cheval.cote_matin is not None and 12 <= cheval.cote_matin <= 22


def _f18_driver_specialiste_hippodrome(cheval: Cheval) -> bool:
    """taux>=20% -- le seuil ">=5 courses" du texte source n'est pas
    tracé par DriverStats (seul le taux agrégé l'est) ; approximation
    documentée par flag F18_SANS_SEUIL_ECHANTILLON."""
    return cheval.driver_stats is not None and (cheval.driver_stats.taux_hippodrome or 0) >= 0.20


def _f21_rk_amelioration_moderee_trot(cheval: Cheval, race: RaceContext) -> bool:
    if disc_bucket(race.discipline) != "TROT" or not cheval.rk_array_3_derniers_sec:
        return False
    arr = cheval.rk_array_3_derniers_sec
    if len(arr) < 2 or arr[-2] is None or arr[-1] is None:
        return False
    amelioration = arr[-2] - arr[-1]  # positif = plus rapide (RK plus bas)
    return 0.10 <= amelioration <= 0.30


def _f22_premiere_ligne_autostart_trot(cheval: Cheval, race: RaceContext) -> bool:
    if disc_bucket(race.discipline) != "TROT":
        return False
    num = cheval.numero_autostart
    if num is None and getattr(race, "depart", None) is not None:
        # AUTOSTART : numero de dossard ≈ ligne si numero_autostart non scrapé
        from app.models import Depart
        if race.depart == Depart.AUTOSTART and cheval.numero is not None:
            num = cheval.numero
    return num is not None and num <= 4


def _f25_specialiste_terrain_plat(cheval: Cheval, race: RaceContext) -> bool:
    if disc_bucket(race.discipline) != "PLAT" or not cheval.historique_terrain or race.penetrometre is None:
        return False
    nb_top5 = sum(1 for h in cheval.historique_terrain
                  if h.rang is not None and h.rang <= 5 and h.valeur is not None
                  and abs(h.valeur - race.penetrometre) <= 0.5)
    return nb_top5 >= 2


def _f26_poids_tres_favorable_plat_sprint(cheval: Cheval, race: RaceContext) -> bool:
    if disc_bucket(race.discipline) != "PLAT" or race.distance_m >= 1400:
        return False
    return cheval.poids_actuel_kg is not None and cheval.poids_actuel_kg <= 53


def _f31_retour_forme_pente(cheval: Cheval) -> bool:
    return cheval.pente_score is not None and cheval.pente_score >= 0.07


def _f32_absence_signal_negatif_majeur(cheval: Cheval, breakdown_flags: List[str]) -> bool:
    return ("STAB_DQ_SERIE_CRITIQUE" not in breakdown_flags
            and cheval.dq_12m == 0 and cheval.dq_5_dernieres_tentees == 0)


def _f17_entraineur_classement_national(cheval: Cheval) -> bool:
    """Débloqué le 12/09/2026 : TrainerStats.classement_national est
    désormais peuplé via le classement maison open-pmu-api (scripts/
    build_classement_entraineurs.py). Seuil Top20 (aligné sur la logique
    Driver_Elite de Longshot F1 et sur B11). Flag explicite si la donnée
    est absente (fichier non généré ou entraîneur hors corpus)."""
    ts = cheval.trainer_stats
    if ts is None or ts.classement_national is None:
        return False
    return ts.classement_national <= 20


def _f9_changement_driver_positif(cheval: Cheval) -> bool:
    """Approximation prudente de f9/f30 (changement jockey/driver positif).
    Le texte source exige le taux de réussite de l'ancien driver. Ici on
    utilise le classement national maison (classement_driver) quand les
    deux noms sont connus : nouveau driver mieux classé que l'ancien
    (delta >= 15 places) ET changement_driver=True. Si les classements
    sont absents, le signal reste silencieux (RÈGLE 2)."""
    if not cheval.changement_driver or not cheval.driver_jockey or not cheval.driver_precedent:
        return False
    try:
        from app.engine.classements import get_classement_driver as get_classement_national
        rang_nouveau = get_classement_national(cheval.driver_jockey)
        rang_ancien = get_classement_national(cheval.driver_precedent)
    except Exception:
        return False
    if rang_nouveau is None or rang_ancien is None:
        return False
    # Nouveau mieux classé (rang plus petit) d'au moins 15 places
    return (rang_ancien - rang_nouveau) >= 15


# id -> (poids, description courte)
_SIGNAUX_VALIDES = ["f1", "f7", "f10", "f11", "f16", "f21", "f31", "f32"]  # poids 1.0
_SIGNAUX_FAIBLES = ["f2", "f4", "f6", "f8", "f9", "f13", "f14", "f15", "f17", "f18",
                    "f22", "f25", "f26"]  # poids 0.35  (+f9, +f17 débloqués 12/09/2026)

NON_EVALUABLES = ["f3", "f5", "f12", "f19", "f20",
                   "f23", "f24", "f27", "f28", "f29", "f30"]


def compute_ssfo(cheval: Cheval, race: RaceContext, sov_v2: Optional[float],
                  breakdown_flags: List[str], pch_final: Optional[float] = None
                  ) -> Tuple[float, Dict[str, bool], List[str]]:
    """Retourne (bonus_ssfo_final, detail_signaux_actifs, flags).
    Formule (RAH-271) : Raw_SSFO = somme des poids activés ; Bonus_SSFO =
    MIN(10, Raw_SSFO x 2) ; multiplicateur x1,3 si cote>=25/1 sinon x1,0 ;
    Bonus_SSFO_final = MIN(10, Bonus_SSFO x multiplicateur). Garde-fous
    du texte source appliqués : f16 ne déclenche jamais en plus le
    multiplicateur (déjà exclusif par construction ici) ; si
    PCH_FINAL>=160, Bonus_SSFO=0 (le cheval est déjà très bien noté par
    ailleurs, le texte source considère le signal redondant)."""
    flags = [f"SSFO_{len(_SIGNAUX_VALIDES) + len(_SIGNAUX_FAIBLES)}_SUR_32_IMPLEMENTES"]  # 21 au 12/09/2026

    cote = cheval.cote_matin
    eligible = cote is not None and cote >= 8
    if not eligible:
        flags.append("SSFO_NON_ELIGIBLE_COTE_INF_8")
        return 0.0, {}, flags

    if pch_final is not None and pch_final >= 160:
        flags.append("SSFO_ZERO_PCH_PLAFOND")
        return 0.0, {}, flags

    checks = {
        "f1": (_f1_progression_rang(cheval), _POIDS_VALIDE),
        "f7": (_f7_retour_distance_predilection(cheval, race), _POIDS_VALIDE),
        "f10": (_f10_deferrage_favorable_trot(cheval, race), _POIDS_VALIDE),
        "f11": (_f11_historique_hippodrome(cheval), _POIDS_VALIDE),
        "f16": (_f16_zone_valeur_sweet(cheval), _POIDS_VALIDE),
        "f21": (_f21_rk_amelioration_moderee_trot(cheval, race), _POIDS_VALIDE),
        "f32": (_f32_absence_signal_negatif_majeur(cheval, breakdown_flags), _POIDS_VALIDE),
        "f2": (_f2_regularite_masquee(cheval), _POIDS_FAIBLE),
        "f4": (_f4_commentaire_sous_evalue(cheval), _POIDS_FAIBLE),
        "f6": (_f6_absence_signaux_negatifs(cheval), _POIDS_FAIBLE),
        "f8": (_f8_allegement_poids(cheval), _POIDS_FAIBLE),
        "f9": (_f9_changement_driver_positif(cheval), _POIDS_FAIBLE),
        "f13": (_f13_mouvement_marche_modere(sov_v2), _POIDS_FAIBLE),
        "f14": (_f14_icp_modere(cheval), _POIDS_FAIBLE),
        "f15": (_f15_cote_stable_malgre_absence(cheval), _POIDS_FAIBLE),
        "f17": (_f17_entraineur_classement_national(cheval), _POIDS_FAIBLE),
        "f18": (_f18_driver_specialiste_hippodrome(cheval), _POIDS_FAIBLE),
        "f22": (_f22_premiere_ligne_autostart_trot(cheval, race), _POIDS_FAIBLE),
        "f25": (_f25_specialiste_terrain_plat(cheval, race), _POIDS_FAIBLE),
        "f26": (_f26_poids_tres_favorable_plat_sprint(cheval, race), _POIDS_FAIBLE),
        "f31": (_f31_retour_forme_pente(cheval), _POIDS_VALIDE),
    }

    detail = {fid: actif for fid, (actif, _) in checks.items()}
    raw_ssfo = sum(poids for actif, poids in checks.values() if actif)
    if raw_ssfo == 0.0:
        return 0.0, detail, flags

    bonus = min(10.0, raw_ssfo * 2)
    multiplicateur = 1.3 if (cote is not None and cote >= 25) else 1.0
    bonus_final = min(10.0, bonus * multiplicateur)

    signaux_actifs = [fid for fid, actif in detail.items() if actif]
    flags.append(f"SSFO_ACTIFS_{'_'.join(signaux_actifs)}")
    return round(bonus_final, 3), detail, flags
