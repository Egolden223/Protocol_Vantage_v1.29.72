"""
csf.py -- Catalogue des Signaux Faibles SF-01 à SF-24 (Partie 4.3),
poste 30 (bonus_csf, alimente COMPOSITE/Module Q uniquement, PAS
PCH_FINAL). Absent jusqu'au 02/09/2026 : qualitative_engine.py ne
posait que 2 signaux approximatifs (SF-REGULARITE/SF-IRREGULARITE,
dérivés de la seule variance de musique), aucun des 24 signaux réels du
texte source n'était évalué.

Ce module s'exécute dans pch_final.py, APRÈS le calcul des modules A-P
(IFF_v2, BSC_v3, BSH_v3v4, MODULE_RECUL, MODULE_TERRAIN_DYN,
MODULE_DIST_ADAPT) : la plupart des SF référencent directement ces
valeurs déjà calculées plutôt que de les redériver -- c'est la raison
structurelle pour laquelle ce catalogue est resté vide jusqu'ici (il
était délégué à la Couche LLM, qui n'a jamais accès à ces valeurs
intermédiaires du même passage).

22 des 24 signaux sont implémentés (SF-06 débloqué le 02/09/2026 grâce à
Cheval.victoires_carriere/places_carriere ; SF-03 débloqué le 04/09/2026
grâce à Cheval.historique_recent, dates réelles CanalTurf/Turfoo). 2
restent NON_EVALUABLE, jamais
devinés (RÈGLE 2) :
  - SF-05 (taux Top5 carrière) : aucun compteur Top5 spécifique n'est
    modélisé sur Cheval -- places_carriere (Turfoo) correspond à
    "placé" (2e/3e), pas à un Top5 ; l'utiliser pour SF-05 reviendrait à
    fabriquer une valeur Top5 à partir d'une donnée Top3, donc non
    tenté (cf. SF-06, qui EST le bon usage de cette donnée).
  - SF-20 (valeur_pmu stable/en hausse 3 dernières courses) : aucun
    historique de valeur_pmu n'est conservé (seule la valeur actuelle
    l'est).
"""
from __future__ import annotations
from typing import List, Optional
from datetime import datetime
from app.models import Cheval, RaceContext, CSFSignal
from app.engine.common import disc_bucket
from app.scraping.musique import parse_musique, MusiquePerf


def compute_csf_signaux(cheval: Cheval, race: RaceContext, champ_size: int,
                         signaux_catalogue_ids: List[str], iff_v2: float, bsc_v3: float,
                         bsh_v3v4: float, module_recul: float, module_terrain_dyn: float,
                         module_dist_adapt: float) -> List[CSFSignal]:
    perfs = parse_musique(cheval.musique)
    out: List[CSFSignal] = []

    def add(sid: str, valeur: float, famille: str):
        out.append(CSFSignal(id=sid, valeur=valeur, famille=famille))

    # --- F_PERF ---
    sf01_actif = False
    if perfs and perfs[0].rang is not None and perfs[0].rang <= 3 and cheval.delai_j is not None:
        if cheval.delai_j <= 8:
            add("SF-01", 4, "F_PERF")
            sf01_actif = True
        elif cheval.delai_j <= 15:
            add("SF-02", 3, "F_PERF")
    # SF-03 (débloqué le 04/09/2026 : Cheval.historique_recent, dates
    # réelles depuis CanalTurf/Turfoo, cf. models.py) -- non cumulable
    # avec SF-01/SF-02 par construction du texte source (familles
    # F_PERF distinctes mais l'exemple CSF donné dans le texte source
    # les liste ensemble sans exclusion explicite ; ils s'additionnent
    # ici comme les autres SF, aucune règle de non-cumul n'étant énoncée
    # pour ce trio contrairement à SF-01/SF-02 entre eux).
    if cheval.historique_recent and race.date_course:
        try:
            d_course = datetime.fromisoformat(race.date_course).date()
            nb_top3_30j = sum(
                1 for p in cheval.historique_recent
                if p.rang is not None and p.rang <= 3 and p.date
                and 0 <= (d_course - datetime.fromisoformat(p.date).date()).days <= 30)
            if nb_top3_30j >= 2:
                add("SF-03", 4, "F_PERF")
        except ValueError:
            pass
    if cheval.pente_score is not None:
        if cheval.pente_score >= 0.15:
            add("SF-04b", 5, "F_PERF")
        elif cheval.pente_score >= 0.07:
            add("SF-04b", 3, "F_PERF")
    # SF-05 : NON_EVALUABLE (cf. docstring)

    # --- F_PHYS ---
    if module_terrain_dyn >= 8:
        add("SF-07", 3, "F_PHYS")
    dix_dernieres = [p for p in perfs[:10]]
    if dix_dernieres and not any(p.incident is not None for p in dix_dernieres):
        add("SF-08", 3, "F_PHYS")
    if cheval.age is not None:
        bucket = disc_bucket(race.discipline)
        fenetre_ok = (6 <= cheval.age <= 9 if bucket == "TROT" else
                      3 <= cheval.age <= 5 if bucket == "PLAT" else
                      6 <= cheval.age <= 10)
        if fenetre_ok:
            add("SF-09", 2, "F_PHYS")
    if iff_v2 >= 8:
        add("SF-10", 4, "F_PHYS")

    # --- SF-06 (F_PERF, ajouté le 02/09/2026 : places_carriere/
    # victoires_carriere scrapés mais jamais exploités jusqu'ici) ---
    # "places" en convention Turfoo = placé (2e/3e) -- (victoires+places)
    # /courses est donc un vrai taux Top3 carrière, pas une approximation.
    if cheval.victoires_carriere is not None and cheval.places_carriere is not None \
            and cheval.nb_courses:
        taux_top3 = (cheval.victoires_carriere + cheval.places_carriere) / cheval.nb_courses
        if taux_top3 > 0.35:
            add("SF-06", 3, "F_PERF")

    # --- F_COND ---
    if cheval.equip_changes and cheval.equip_changes > 0 and len(perfs) >= 2 and \
            perfs[0].rang is not None and perfs[1].rang is not None and perfs[0].rang < perfs[1].rang:
        # Approximation : on ne sait pas si le changement a eu lieu précisément
        # entre ces 2 courses (pas de date par changement d'équipement) --
        # signal posé si la tendance est cohérente avec l'hypothèse, flag dédié.
        add("SF-11", 3, "F_COND")
    if bsc_v3 >= 8:
        add("SF-12", 4, "F_COND")
    if not cheval.changement_driver:
        add("SF-13", 2, "F_COND")
    if cheval.distance_habituelle_m is not None and abs(cheval.distance_habituelle_m - race.distance_m) <= 100:
        add("SF-14", 3, "F_COND")
    if bsh_v3v4 >= 12 and bsc_v3 >= 8:
        add("SF-15", 5, "F_COND")
    if race.type_course.value == "HANDICAP" and disc_bucket(race.discipline) == "TROT" and module_recul >= 8:
        add("SF-16", 4, "F_COND")

    # --- F_MARKET ---
    delta_brut = None
    if cheval.cote_matin is not None and cheval.cote_avant_course is not None and cheval.cote_matin > 0:
        delta_brut = (cheval.cote_matin - cheval.cote_avant_course) / cheval.cote_matin
        if abs(delta_brut) < 0.05:
            add("SF-17", 2, "F_MARKET")
        sov_v2_brut = max(-0.10, min(0.15, 0.4 * delta_brut))
        if sov_v2_brut >= 0.07:
            add("SF-18", 4, "F_MARKET")
        if delta_brut > 0.25:
            add("SF-19", 4, "F_MARKET")
    # SF-20 : NON_EVALUABLE (cf. docstring)

    # --- F_CONTEXT ---
    specialiste_confirme = bool(cheval.historique_distance) and sum(
        1 for h in cheval.historique_distance if h.rang is not None and h.rang <= 3
        and h.valeur is not None and abs(h.valeur - race.distance_m) <= 100) >= 2
    if module_dist_adapt >= 10 and specialiste_confirme:
        add("SF-21", 4, "F_CONTEXT")
    if "B04" in signaux_catalogue_ids:
        add("SF-22", 3, "F_CONTEXT")
    if champ_size < 10:
        add("SF-23", 2, "F_CONTEXT")
    if module_recul >= 10:
        add("SF-24", 4, "F_CONTEXT")

    return out
