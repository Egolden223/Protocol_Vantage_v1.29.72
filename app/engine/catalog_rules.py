"""
catalog_rules.py -- Implémentation 100% Python (aucun LLM) d'un
sous-ensemble des catalogues B01-B56 / M01-M43 (Partie 4.1/4.2),
calculable à partir des données que le scraper Geny.com peut extraire
sans requête supplémentaire par cheval (musique, cotes 2 points, valeur,
âge, poids). Chaque fonction cite le RAH/signal source et son seuil exact.

CE QUI N'EST PAS (OU PARTIELLEMENT) COUVERT ICI :
  - B01/B36 (presse) : partiellement via Frequence-Turf / CanalTurf ICP
  - B12/B13 (classements entraîneur/propriétaire) : classement maison
    offline disponible (classement_entraineur.py) mais pas encore câblé
    comme signal B12/B13 dédié dans ce fichier
  - B18/B27/B29/B31/B32/B37/B40/B48/B50 (texte libre)
  - B04/B05/B17/B19 etc. : historiques hippodrome/terrain/distance sont
    désormais collectés via fiches individuelles (enrichment) et traités
    principalement dans historique_signals.py / modules_ap.py
  - B09/B11/M02/M14 (stats driver/entraîneur) : fenêtres + taux Quinté
    / carrière / classement national sont peuplés (CanalTurf + offline)
    et consommés par BSH/BSC (modules_ap) et SSFO f17/f9 ; B11/B12
    câblés 30/09/2026 (soft si BSH/BSC déjà actifs)
Ces signaux restent silencieux (pas de valeur inventée) tant que les
champs correspondants restent vides sur le Cheval (RÈGLE 2).
"""
from __future__ import annotations
from typing import List, Optional
from statistics import mean

from app.models import Cheval, RaceContext, CatalogSignal, Discipline, TypeCourse
from app.engine.common import disc_bucket
from app.scraping.musique import (
    parse_musique, nb_victoires_consecutives, nb_top_consecutifs, taux_incidents,
    rangs_recents, tendance_forme, MusiquePerf,
)

Flags = List[str]


def _discipline_code(discipline: Discipline) -> str:
    return {"TROT_ATTELE": "a", "TROT_MONTE": "m", "PLAT": "p", "HAIES": "h", "STEEPLE": "s"}.get(
        discipline.value, "p")


def compute_catalog_signals(cheval: Cheval, race: RaceContext, champ: List[Cheval]) -> List[CatalogSignal]:
    perfs = parse_musique(cheval.musique)
    signaux: List[CatalogSignal] = []

    def add(id_: str, valeur: float, catalog: str, confiance: str, justification: str):
        signaux.append(CatalogSignal(id=id_, valeur_brute=valeur, catalog=catalog,
                                      confiance=confiance, justification=justification))

    disc_code = _discipline_code(race.discipline)

    # --- B02 Série victoires (même discipline) ---
    n = nb_victoires_consecutives(perfs, meme_discipline=race.discipline.value)
    if n >= 3:
        add("B02", 18, "B", "STRICT", f"{n} victoires consécutives (même discipline)")
    elif n == 2:
        add("B02", 10, "B", "DEGRADE", "2 victoires consécutives")
    elif n == 1 and len(perfs) >= 2 and perfs[1].rang and perfs[1].rang <= 3:
        add("B02", 5, "B", "MINIMAL", "1 victoire + Top3 suivant")

    # --- M01 Forme déclinante / B23 rebond (tendance) ---
    tendance = tendance_forme(perfs, n=4)
    rangs4 = rangs_recents(perfs, 4)
    if tendance == "DEGRADATION" and len(rangs4) >= 3:
        add("M01", -15, "M", "STRICT", "3+ courses en dégradation de rang")
    elif tendance == "DEGRADATION" and len(rangs4) == 2:
        add("M01", -8, "M", "DEGRADE", "2 courses en dégradation")
    elif len(rangs4) >= 2 and rangs4[0] - rangs4[1] >= 4:
        add("M01", -4, "M", "MINIMAL", "dégradation nette (rang +4 vs précédent)")

    if len(rangs4) >= 2 and rangs4[1] >= 6 and rangs4[0] <= 3:
        add("B23", 6, "B", "DEGRADE", "rebond après déception (mauvais rang puis bon rang)")

    # --- B08 Dernière course excellente (Top2) ---
    if perfs and perfs[0].rang is not None:
        if perfs[0].rang <= 2:
            add("B08", 12, "B", "STRICT", "rang <= 2 lors de la dernière course")
        elif perfs[0].rang <= 3:
            add("B08", 3, "B", "MINIMAL", "rang <= 3 lors de la dernière course")
    if len(perfs) >= 2 and perfs[1].rang is not None and perfs[1].rang <= 2:
        add("B08b", 6, "B", "DEGRADE", "rang <= 2 lors de l'avant-dernière course")

    # --- B26 Victoire récente toutes conditions ---
    rangs3 = rangs_recents(perfs, 3)
    if any(r == 1 for r in rangs3):
        add("B26", 8, "B", "DEGRADE", "victoire dans les 3 dernières courses")

    # --- B_TOP5_REGULIER (v1.29.19, port Grok) : régularité Top5 récente ---
    # Soft, plafonné -- distinct de B08/B26 (dernière course seule / victoire
    # seule) : capture la RÉGULARITÉ sur 3 courses, signal directement aligné
    # sur l'objectif P(Top5 ⊂ ticket). Note Grok elle-même : "évite double
    # comptage avec B08/B26" -- vérifié, portées différentes (régularité vs
    # ponctuel), cohérent avec le fait que musique_composite alimente déjà
    # à la fois PCH et p_boost séparément dans ce moteur.
    n_top5 = sum(1 for r in rangs3 if 1 <= r <= 5)
    n_top3 = sum(1 for r in rangs3 if 1 <= r <= 3)
    if n_top5 >= 2:
        add("B_TOP5_REGULIER", 8, "B", "STRICT",
            f"{n_top5} places Top5 sur 3 courses (régularité capture)")
    elif n_top5 == 1 and n_top3 >= 1:
        add("B_TOP5_REGULIER", 4, "B", "DEGRADE",
            "1 Top5 + présence Top3 sur 3 courses")
    elif len(rangs3) >= 3 and n_top5 == 0 and all(r >= 8 for r in rangs3):
        add("M_FORME_MORTE", -5, "M", "MINIMAL",
            "aucune place Top5 et rangs >=8 sur 3 courses")

    # --- B07 Récupération rapide post-DQ ---
    if len(perfs) >= 2 and perfs[1].incident == "DISQUALIFIE":
        if perfs[0].rang is not None and perfs[0].rang <= 3:
            add("B07", 10, "B", "STRICT", "DQ avant-dernière course, Top3 depuis")
    if len(perfs) >= 4 and perfs[3].incident == "DISQUALIFIE" and not any(p.incident for p in perfs[:3]):
        add("B07", 3, "B", "MINIMAL", "DQ il y a 3+ courses, aucune depuis")

    # --- M12 Incidents répétés récents ---
    inc5 = sum(1 for p in perfs[:5] if p.incident)
    if inc5 >= 2:
        add("M12", -15, "M", "STRICT", f"{inc5} incidents sur les 5 dernières courses")
    elif sum(1 for p in perfs[:3] if p.incident) == 1:
        add("M12", -8, "M", "DEGRADE", "1 incident sur les 3 dernières courses")

    # --- M26 Risque DQ comportemental (jamais en OBSTACLE) ---
    if disc_bucket(race.discipline) != "OBSTACLE":
        dq12 = sum(1 for p in perfs if p.incident == "DISQUALIFIE")
        if dq12 >= 2:
            add("M26", -10, "M", "DEGRADE", f"{dq12} DQ dans l'historique musique disponible")
        elif dq12 == 1:
            add("M26", -5, "M", "MINIMAL", "1 DQ dans l'historique musique disponible")

    # --- B06 / M19 : cote (favori public / défiance marché) ---
    cotes_champ = [c.cote_matin for c in champ if c.cote_matin is not None]
    if cheval.cote_matin is not None and cotes_champ:
        if cheval.cote_matin == min(cotes_champ) and cheval.cote_matin <= 4.0:
            add("B06", 8, "B", "STRICT", "cote la plus basse du champ, <= 4/1")
        elif cheval.cote_matin <= 5.0 and cheval.cote_matin == min(cotes_champ):
            add("B06", 4, "B", "DEGRADE", "cote la plus basse du champ, <= 5/1")

    if cheval.cote_matin and cheval.cote_avant_course and cheval.cote_matin > 0:
        delta = (cheval.cote_matin - cheval.cote_avant_course) / cheval.cote_matin
        if delta > 0.25:
            add("B16", 10, "B", "STRICT", f"baisse de cote de {delta*100:.0f}% (repli SOV)")
        elif delta > 0.15:
            add("B16", 6, "B", "DEGRADE", f"baisse de cote de {delta*100:.0f}%")
        elif delta > 0.08:
            add("B16", 3, "B", "MINIMAL", f"baisse de cote de {delta*100:.0f}%")
        elif delta < -0.25:
            add("M19", -10, "M", "STRICT", f"hausse de cote de {-delta*100:.0f}%")
        elif delta < -0.15:
            add("M19", -5, "M", "DEGRADE", f"hausse de cote de {-delta*100:.0f}%")

    # --- B10 Jeunesse prometteuse / M05 jeune inexpérimenté / M24 trop jeune handicap ---
    bucket = disc_bucket(race.discipline)
    nb_perfs = len(perfs)
    if cheval.age is not None:
        seuil_jeune = 4 if bucket == "PLAT" else 5
        nb_wins = sum(1 for p in perfs if p.rang == 1)
        if cheval.age <= seuil_jeune and nb_wins >= 2:
            add("B10", 10, "B", "STRICT", f"âge <= {seuil_jeune} et {nb_wins} victoires")
        elif cheval.age <= seuil_jeune + 1 and rangs3 and min(rangs3) <= 3:
            add("B10", 5, "B", "DEGRADE", "jeune + Top3 récent")

        if cheval.age <= 3 and nb_perfs <= 2 and race.reunion_course_label and "quinte" in (race.reunion_course_label or "").lower():
            add("M05", -10, "M", "STRICT", "âge<=3, <=2 courses, niveau Quinté+")
        elif cheval.age <= 4 and nb_perfs <= 4:
            add("M05", -5, "M", "DEGRADE", "âge<=4, <=4 courses")

        if race.type_course == TypeCourse.HANDICAP and nb_perfs == 0:
            if cheval.age <= 3 and race.partants_confirmes >= 14:
                add("M24", -8, "M", "STRICT", "1er handicap, âge<=3, champ >=14 partants")
            elif cheval.age <= 4:
                add("M24", -4, "M", "DEGRADE", "1er handicap, âge<=4")

    # --- M09 / M22 : niveau vs champ (valeur_pmu) ---
    valeurs_champ = [c.valeur_pmu for c in champ if c.valeur_pmu is not None]
    if cheval.valeur_pmu is not None and len(valeurs_champ) >= 3:
        moy = mean(valeurs_champ)
        if cheval.valeur_pmu < moy - 8:
            add("M09", -10, "M", "STRICT", f"valeur_pmu {cheval.valeur_pmu:.1f} < moyenne champ - 8")
        elif cheval.valeur_pmu < moy - 5:
            add("M09", -5, "M", "DEGRADE", "valeur_pmu < moyenne champ - 5")
        nb_superieurs = sum(1 for v in valeurs_champ if v > cheval.valeur_pmu + 5)
        if nb_superieurs >= 5:
            add("M22", -8, "M", "STRICT", f"{nb_superieurs} partants avec valeur_pmu > +5")
        elif nb_superieurs >= 3:
            add("M22", -4, "M", "DEGRADE", f"{nb_superieurs} partants avec valeur_pmu > +5")

    # --- M13 Risque chute/faute (OBSTACLE/HAIES uniquement) ---
    if bucket == "OBSTACLE":
        chutes5 = sum(1 for p in perfs[:5] if p.incident == "TOMBE")
        if chutes5 >= 1:
            malus = -10
            if race.discipline == Discipline.HAIES:
                malus *= 1.3
            elif race.discipline == Discipline.STEEPLE:
                malus *= 1.7
            add("M13", round(malus, 1), "M", "STRICT", f"{chutes5} chute(s) sur les 5 dernières courses obstacle")


    # --- B11 Driver classement national (A2, 30/09/2026) ---
    # Anti-double-compte BSH : valeur modérée si fenêtres driver déjà riches.
    try:
        rang_d = None
        ds = cheval.driver_stats
        if ds is not None and getattr(ds, "classement_national", None) is not None:
            rang_d = int(ds.classement_national)
        if rang_d is None:
            from app.engine.classements import get_classement_driver as get_classement_national
            rang_d = get_classement_national(cheval.driver_jockey)
        if rang_d is not None:
            has_bsh_windows = bool(ds and getattr(ds, "fenetres", None))
            if rang_d <= 10:
                v = 3.0 if has_bsh_windows else 5.0
                add("B11", v, "B", "DEGRADE" if has_bsh_windows else "STRICT",
                    f"driver classement national #{rang_d}" + (" (soft, BSH déjà actif)" if has_bsh_windows else ""))
            elif rang_d <= 25:
                v = 1.5 if has_bsh_windows else 2.5
                add("B11", v, "B", "MINIMAL", f"driver classement national #{rang_d}")
    except Exception:
        pass

    # --- B12 Entraîneur classement national ---
    try:
        rang_e = None
        ts = cheval.trainer_stats
        if ts is not None and getattr(ts, "classement_national", None) is not None:
            rang_e = int(ts.classement_national)
        if rang_e is None:
            from app.engine.classements import get_classement_entraineur as get_cl_ent
            rang_e = get_cl_ent(cheval.entraineur)
        if rang_e is not None:
            has_bsc = bool(ts and getattr(ts, "fenetres", None))
            if rang_e <= 10:
                v = 2.5 if has_bsc else 4.0
                add("B12", v, "B", "DEGRADE" if has_bsc else "STRICT",
                    f"entraîneur classement national #{rang_e}")
            elif rang_e <= 25:
                v = 1.0 if has_bsc else 2.0
                add("B12", v, "B", "MINIMAL", f"entraîneur classement national #{rang_e}")
    except Exception:
        pass

    # --- D45 Synergie légère (forme récente + local hippo) — plus un poste fantôme ---
    try:
        perfs_d = parse_musique(cheval.musique or "")[:5]
        tops = sum(1 for p in perfs_d if getattr(p, "rang", None) and p.rang <= 5)
        local = 0
        hist = getattr(cheval, "historique_hippodrome", None) or []
        if hist:
            local = sum(1 for h in hist if getattr(h, "rang", None) and h.rang <= 5)
        if tops >= 2 and local >= 1:
            add("D45", 3.0, "B", "DEGRADE", f"synergie forme({tops} top5) + local hippo")
        elif tops >= 2 or local >= 2:
            add("D45", 1.5, "B", "MINIMAL", "synergie partielle forme/local")
    except Exception:
        pass

    # --- Famille G : GRU hippodrome (catalogue Discipline × Hippo × Distance) ---
    try:
        from app.engine.gru_signals import compute_gru_signals
        for gs in compute_gru_signals(cheval, race, champ):
            signaux.append(gs)
    except Exception:
        pass  # ne jamais faire échouer le catalogue B/M pour un défaut GRU

    return signaux
