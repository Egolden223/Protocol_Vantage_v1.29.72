"""
historique_signals.py -- Calcule un lot de signaux du catalogue B/M qui
nécessitent un historique DÉTAILLÉ par course (hippodrome, distance,
terrain, rang, date) -- débloqué par l'enrichissement fiche cheval
(app/scraping/turfoo_fiche_cheval.py). Avant cet enrichissement, ces
signaux ne pouvaient pas s'activer faute de données.

Formules retranscrites depuis app/protocol_assets/partie4_catalogues.txt
(B04, B05, B17, B19, M03, M04, M10, M21, M23). Certaines modulations
avancées du texte source (RAH-109 âge/valeur sur B04, RAH-236 journalisation
détaillée) nécessitent `valeur_pmu` que Turfoo n'expose pas -- non
appliquées, documenté par flag plutôt que simulé.
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Tuple, Dict
from statistics import mean

from app.models import CatalogSignal
from app.scraping.turfoo_fiche_cheval import FicheChevalHistorique

Flags = List[str]


def _norm_hippo(s: str) -> str:
    return s.strip().upper().replace("-", " ").replace("'", "")


def _delai_jours(date_str: Optional[str], date_ref: str) -> Optional[int]:
    if not date_str:
        return None
    try:
        return (datetime.fromisoformat(date_ref).date() - datetime.fromisoformat(date_str).date()).days
    except ValueError:
        return None


def compute_historique_signals(historique: List[FicheChevalHistorique], race_hippodrome: str,
                                race_distance_m: int, race_penetrometre: Optional[float],
                                date_course_actuelle: Optional[str], tranche: Optional[str] = None
                                ) -> Tuple[List[CatalogSignal], Dict[str, float]]:
    """Retourne (signaux_catalogue, valeurs_brutes). valeurs_brutes contient
    'irp_final' et 'pente_brut' quand calculables (>= 3 / >= 3 courses
    datées requises respectivement) -- ajouté le 02/09/2026 : ces deux
    valeurs n'étaient auparavant lisibles qu'en texte libre dans
    CatalogSignal.justification (ex. "IRP_ajusté_final=0.412 (DÉGRADÉ)"),
    ce qui empêchait p5p6.py (C3) et ssfo.py (f2/f31) de s'en servir sans
    parser une chaîne -- lacune non détectée avant cette session."""
    signaux: List[CatalogSignal] = []
    valeurs_brutes: Dict[str, float] = {}
    if not historique:
        return signaux, valeurs_brutes

    def add(id_, valeur, catalog, famille, justification, confiance="DEGRADE"):
        signaux.append(CatalogSignal(id=id_, valeur_brute=valeur, catalog=catalog, famille=famille,
                                      confiance=confiance, justification=justification))

    hippo_norm = _norm_hippo(race_hippodrome)
    sur_hippodrome = [h for h in historique if _norm_hippo(h.hippodrome) == hippo_norm and h.notre_rang is not None]

    # --- B04 / M23 : affinité hippodrome ---
    nb_courses_hippo = len(sur_hippodrome)
    if nb_courses_hippo < 3:
        pass  # B04_ECHANTILLON_INSUFFISANT -- pas d'activation, RAH-236
    else:
        nb_top5 = sum(1 for h in sur_hippodrome if h.notre_rang <= 5)
        nb_top3 = sum(1 for h in sur_hippodrome if h.notre_rang <= 3)
        taux_top5 = nb_top5 / nb_courses_hippo

        b04_brut = 0.0
        if nb_top5 >= 3 and nb_courses_hippo >= 4:
            b04_brut = 12.0
        elif taux_top5 >= 0.20:
            b04_brut = 6.0
        elif nb_top3 >= 1:
            b04_brut = 3.0

        if b04_brut > 0:
            # RAH-114 : décote temporelle depuis la dernière perf Top5 sur cet hippodrome
            dates_top5 = [h.date for h in sur_hippodrome if h.notre_rang <= 5 and h.date]
            delai = min((_delai_jours(d, date_course_actuelle) for d in dates_top5 if
                        _delai_jours(d, date_course_actuelle) is not None), default=None) \
                if dates_top5 and date_course_actuelle else None
            if delai is None:
                coeff_temps = 0.60
            elif delai <= 90:
                coeff_temps = 1.00
            elif delai <= 180:
                coeff_temps = 0.75
            elif delai <= 365:
                coeff_temps = 0.50
            else:
                coeff_temps = 0.25
            b04_final = max(1.0, round(b04_brut * coeff_temps)) if b04_brut > 0 else 0.0
            add("B04", b04_final, "B", "L",
                f"{nb_courses_hippo} courses à {race_hippodrome}, {nb_top5} Top5 (coeff_temps={coeff_temps})",
                confiance="STRICT" if b04_brut == 12 else "DEGRADE")

        if nb_top5 == 0:
            m23_val = -10.0 if nb_courses_hippo >= 3 else -5.0
            add("M23", m23_val, "M", "L", f"{nb_courses_hippo} courses à {race_hippodrome}, 0 Top5")

    # --- B05 : régularité distance ---
    sur_distance = [h for h in historique if h.distance_m is not None
                    and abs(h.distance_m - race_distance_m) <= 50 and h.notre_rang is not None]
    nb_top5_dist = sum(1 for h in sur_distance if h.notre_rang <= 5)
    nb_top2_dist = sum(1 for h in sur_distance if h.notre_rang <= 2)
    if nb_top5_dist >= 4:
        add("B05", 8.0, "B", "L", f"{nb_top5_dist} Top5 sur distance similaire (±50m)", "STRICT")
    elif nb_top5_dist >= 2:
        add("B05", 4.0, "B", "L", f"{nb_top5_dist} Top5 sur distance similaire")
    elif nb_top2_dist >= 1:
        add("B05", 2.0, "B", "L", f"{nb_top2_dist} Top2 sur distance similaire", "MINIMAL")

    # --- M04 : distance incompatible ---
    rangs_mauvais_dist = [h.notre_rang for h in historique if h.distance_m is not None
                          and abs(h.distance_m - race_distance_m) <= 100
                          and h.notre_rang is not None and h.notre_rang > 7]
    if len(rangs_mauvais_dist) >= 3:
        add("M04", -10.0, "M", "L", f"{len(rangs_mauvais_dist)} rangs > 7 sur distance similaire (±100m)", "STRICT")
    elif len(rangs_mauvais_dist) >= 2:
        add("M04", -5.0, "M", "L", f"{len(rangs_mauvais_dist)} rangs > 7 sur distance similaire")

    # --- B17 / M03 / M10 : affinité terrain (pénétromètre approximatif) ---
    if race_penetrometre is not None:
        sur_terrain = [h for h in historique if h.penetrometre_approx is not None
                       and abs(h.penetrometre_approx - race_penetrometre) <= 0.5 and h.notre_rang is not None]
        nb_top3_terrain = sum(1 for h in sur_terrain if h.notre_rang <= 3)
        if nb_top3_terrain >= 3:
            add("B17", 10.0, "B", "L", f"{nb_top3_terrain} Top3 sur terrain similaire (±0.5)", "STRICT")
        elif nb_top3_terrain >= 2:
            add("B17", 5.0, "B", "L", f"{nb_top3_terrain} Top3 sur terrain similaire")
        elif any(h.notre_rang <= 2 for h in sur_terrain):
            add("B17", 2.0, "B", "L", "1 Top2 sur terrain similaire", "MINIMAL")

        rangs_mauvais_terrain = [h.notre_rang for h in sur_terrain if h.notre_rang > 7]
        if len(rangs_mauvais_terrain) >= 3:
            add("M03", -12.0, "M", "L", f"{len(rangs_mauvais_terrain)} rangs > 7 sur terrain similaire", "STRICT")
        elif len(rangs_mauvais_terrain) >= 2:
            add("M03", -6.0, "M", "L", f"{len(rangs_mauvais_terrain)} rangs > 7 sur terrain similaire")

        if not sur_terrain:
            add("M10", -8.0, "M", "L", "aucune course historique sur terrain similaire", "STRICT")
        elif len(sur_terrain) == 1:
            add("M10", -4.0, "M", "L", "1 seule course historique sur terrain similaire")

        # M21 : jamais performant sur terrain lourd/très lourd (pénétro approx >= 5.0)
        sur_lourd = [h for h in historique if h.penetrometre_approx is not None and h.penetrometre_approx >= 5.0
                    and h.notre_rang is not None]
        if len(sur_lourd) >= 5 and sum(1 for h in sur_lourd if h.notre_rang <= 5) == 0:
            add("M21", -10.0, "M", "L", f"0 Top5 sur {len(sur_lourd)} courses en terrain lourd/très lourd", "STRICT")
        elif len(sur_lourd) >= 3 and sum(1 for h in sur_lourd if h.notre_rang <= 5) == 0:
            add("M21", -5.0, "M", "L", f"0 Top5 sur {len(sur_lourd)} courses en terrain lourd")

    # --- B19 : spécialiste conditions exactes (distance + hippodrome) ---
    sur_conditions = [h for h in historique if h.notre_rang is not None
                      and _norm_hippo(h.hippodrome) == hippo_norm
                      and h.distance_m is not None and abs(h.distance_m - race_distance_m) <= 100]
    nb_top3_conditions = sum(1 for h in sur_conditions if h.notre_rang <= 3)
    if nb_top3_conditions >= 3:
        add("B19", 15.0, "B", "L", f"{nb_top3_conditions} Top3 sur distance+hippodrome exacts", "STRICT")
    elif nb_top3_conditions >= 1 and len(sur_conditions) >= 2:
        add("B19", 8.0, "B", "L", f"{nb_top3_conditions} Top3 sur conditions proches")

    # --- B47 : régularité pondérée (IRP), Partie 4.1 -- ajouté le 09/08/2026 ---
    _RANG_SCORE = {1: 1.000, 2: 0.700, 3: 0.490, 4: 0.343, 5: 0.240, 6: 0.168, 7: 0.118, 8: 0.082}
    _COEFF_CONFIANCE = {8: 1.00, 7: 0.98, 6: 0.95, 5: 0.90, 4: 0.85, 3: 0.80}
    hist_datees = sorted([h for h in historique if h.date], key=lambda h: h.date, reverse=True)[:8]
    if len(hist_datees) >= 3:
        poids_total = sum(0.85 ** i for i in range(len(hist_datees)))
        irp_brut = sum(_RANG_SCORE.get(h.notre_rang, 0.0) * (0.85 ** i)
                       for i, h in enumerate(hist_datees)) / poids_total
        irp_ajuste = irp_brut * _COEFF_CONFIANCE.get(len(hist_datees), 0.80)

        def _dans_12m(h):
            d = _delai_jours(h.date, date_course_actuelle or "")
            return d is not None and d <= 365

        victoires_12m = sum(1 for h in hist_datees if h.notre_rang == 1 and _dans_12m(h))
        nb_12m = sum(1 for h in hist_datees if _dans_12m(h))
        taux_victoires = (victoires_12m / nb_12m) if nb_12m else 0.0
        coeff_taux = (1.00 if taux_victoires >= 0.25 else 0.90 if taux_victoires >= 0.15
                     else 0.80 if taux_victoires >= 0.10 else 0.70 if taux_victoires >= 0.05 else 0.60)
        irp_final = irp_ajuste * coeff_taux
        valeurs_brutes["irp_final"] = round(irp_final, 4)

        seuil_strict, seuil_degrade = (0.55, 0.40) if tranche in ("T3", "T4a", "T4b") else (0.60, 0.45)
        if irp_final >= seuil_strict:
            add("B47", 12.0, "B", "F", f"IRP_ajusté_final={irp_final:.3f} (STRICT)", "STRICT")
        elif irp_final >= seuil_degrade:
            add("B47", 6.0, "B", "F", f"IRP_ajusté_final={irp_final:.3f} (DÉGRADÉ)")
        elif irp_final >= 0.35:
            add("B47", 3.0, "B", "F", f"IRP_ajusté_final={irp_final:.3f} (MINIMAL)", "MINIMAL")
        elif irp_final >= 0.20:
            add("B47", 2.0, "B", "F", f"IRP_ajusté_final={irp_final:.3f} (DERNIER_RECOURS)", "MINIMAL")

        if victoires_12m == 0 and nb_12m > 0 and irp_final >= 0.45:
            add("B47_REGULIER_PERDANT", -3.0, "M", "F", "régulier mais 0 victoire sur 12 mois")

        # --- B47bis : PENTE_SCORE, trajectoire sur 3-4 courses (mêmes 8 triées) ---
        hist_avec_partants = [h for h in hist_datees if h.notre_rang is not None and h.partants]
        if len(hist_avec_partants) >= 3:
            quatre = list(reversed(hist_avec_partants[:4]))  # plus ancien -> plus récent
            rr = [h.notre_rang / h.partants for h in quatre]
            if len(rr) == 4:
                d12, d23, d34 = rr[0] - rr[1], rr[1] - rr[2], rr[2] - rr[3]
                pente = 0.25 * d12 + 0.35 * d23 + 0.40 * d34
            else:
                d23, d34 = rr[0] - rr[1], rr[1] - rr[2]
                pente = 0.45 * d23 + 0.55 * d34
            valeurs_brutes["pente_brut"] = round(pente, 4)

            garde_jeune = len(historique) < 6
            garde_classe = min(rr) < 0.15

            if pente >= 0.15:
                val, flag = 12.0, "PS_FORT"
            elif pente >= 0.07:
                val, flag = 6.0, "PS_MODERE"
            elif pente >= -0.05:
                val, flag = 0.0, "PS_STABLE"
            elif pente >= -0.12:
                val, flag = (-4.0, "PS_DECLIN") if not garde_classe else (0.0, "PENTE_CLASSE")
            else:
                val, flag = (-10.0, "PS_CHUTE") if not garde_classe else (0.0, "PENTE_CLASSE")
            if garde_jeune and val != 0.0:
                val /= 2
            if val != 0.0:
                add("B47bis", val, "B" if val > 0 else "M", "F", f"PENTE_brut={pente:.3f} ({flag})")

    return signaux, valeurs_brutes
