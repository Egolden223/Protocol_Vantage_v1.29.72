"""data_contract.py — Contrat de données exhaustif (avant scoring).

Formalise le tableau de collecte/enrichissement du protocole :
  - chaque champ course / cheval / hommes / presse
  - priorité (critique / forte / utile)
  - sources attendues
  - modules consommateurs

Évalué APRÈS enrichissement (2.0–2.7) et AVANT analyse qualitative / scoring.
Une lacune critique bloque la production d'un ticket certifié ; le rapport
structuré reste obligatoire pour diagnostiquer le rejet.
"""
from __future__ import annotations

# Priorité 1 — champs critiques scoring (collecte / 2.7 ciblée)
PRIO1_FIELDS = (
    "valeur_pmu", "recul_m", "ferrure_type", "record_chrono_sec",
    "poids_actuel_kg", "gains_moyenne_carriere_eur", "musique",
    "cote_matin", "cote_avant_course", "driver_stats", "trainer_stats",
)

from typing import Any, Dict, List, Optional, Tuple

from app.models import Cheval, RaceContext


def _vide(val) -> bool:
    if val is None or val == "" or val == [] or val == {}:
        return True
    return False


def _get(obj, name: str):
    return getattr(obj, name, None)


# ---------------------------------------------------------------------------
# Contrat formel : (champ, cible, priorite, sources, modules, discipline_hint)
# priorite: "critique" | "forte" | "utile"
# cible: "course" | "cheval" | "hommes" | "presse"
# ---------------------------------------------------------------------------

CONTRAT_COURSE: List[Dict[str, str]] = [
    {"champ": "hippodrome", "priorite": "critique", "sources": "collecte 4 sources", "modules": "GRU,recul,poids,terrain"},
    {"champ": "discipline", "priorite": "critique", "sources": "collecte,PMU", "modules": "SRI,IFF,MPA,router,forme_disc"},
    {"champ": "distance_m", "priorite": "critique", "sources": "collecte,PMU", "modules": "DIST_ADAPT,poids,MPA"},
    {"champ": "date_course", "priorite": "critique", "sources": "collecte", "modules": "delai,BSH_fenetres,FT_urls"},
    {"champ": "partants_confirmes", "priorite": "critique", "sources": "collecte", "modules": "GMO,quotas,marche"},
    {"champ": "type_course", "priorite": "forte", "sources": "collecte,PMU", "modules": "contexte_handicap"},
    {"champ": "depart", "priorite": "forte", "sources": "collecte,PMU", "modules": "GRU_numero,autostart"},
    {"champ": "penetrometre", "priorite": "forte", "sources": "API_PMU", "modules": "terrain_dyn", "hint": "surface"},
    {"champ": "reunion_course_label", "priorite": "forte", "sources": "collecte,resolve_RC", "modules": "PMU_Equidia_Turfbzh_urls"},
    {"champ": "allocation_eur", "priorite": "utile", "sources": "collecte,PMU", "modules": "niveau_course"},
    {"champ": "terrain_qualificatif", "priorite": "utile", "sources": "collecte", "modules": "terrain"},
    {"champ": "meteo_temp_c", "priorite": "utile", "sources": "PMU", "modules": "contexte"},
    {"champ": "meteo_vent_kmh_max", "priorite": "utile", "sources": "PMU", "modules": "contexte"},
]

CONTRAT_CHEVAL: List[Dict[str, str]] = [
    # Identité / marché
    {"champ": "numero", "priorite": "critique", "sources": "collecte", "modules": "ticket,audit"},
    {"champ": "nom", "priorite": "critique", "sources": "collecte", "modules": "matching_fiches"},
    {"champ": "cote_matin", "priorite": "critique", "sources": "collecte,PMU", "modules": "tranches_T1T4,marche,STAB"},
    {"champ": "cote_avant_course", "priorite": "critique", "sources": "collecte,PMU", "modules": "SOV_DRIFT,ranking"},
    {"champ": "fiche_url", "priorite": "critique", "sources": "Turfoo,CT,ZT,Geny", "modules": "enrichissement_fiche"},
    {"champ": "age", "priorite": "forte", "sources": "collecte,fiches", "modules": "SRI_age"},
    {"champ": "sexe", "priorite": "utile", "sources": "collecte", "modules": "filtres"},
    {"champ": "proprietaire", "priorite": "utile", "sources": "Geny,fiches", "modules": "qualitatif"},
    {"champ": "cotes_timeline", "priorite": "forte", "sources": "multi_sources", "modules": "SOV_timeline"},
    # Valeur / gains
    {"champ": "valeur_pmu", "priorite": "critique", "sources": "API_PMU,Equidia,fiches", "modules": "SRI,NRC,poids", "hint": "handicap"},
    {"champ": "gains_totaux_eur", "priorite": "critique", "sources": "CanalTurf,PMU,fiches", "modules": "SRI,NRC"},
    {"champ": "gains_moyenne_carriere_eur", "priorite": "forte", "sources": "FT,fiches", "modules": "SRI_proxy,NRC"},
    {"champ": "nb_courses", "priorite": "forte", "sources": "fiches", "modules": "gain_par_course"},
    {"champ": "victoires_carriere", "priorite": "forte", "sources": "fiches", "modules": "regularite,catalogue"},
    {"champ": "places_carriere", "priorite": "utile", "sources": "fiches", "modules": "regularite"},
    {"champ": "valeur_pmu_precedente", "priorite": "forte", "sources": "histo_fiche", "modules": "poids_evolution", "hint": "handicap"},
    {"champ": "niveau_max", "priorite": "utile", "sources": "fiches", "modules": "SRI"},
    # Forme / musique / commentaires
    {"champ": "musique", "priorite": "critique", "sources": "collecte,Equidia,fiches", "modules": "forme_disc,CRE_proxy,IFF"},
    {"champ": "commentaire_derniere_course", "priorite": "forte", "sources": "fiches_Turfoo_Geny", "modules": "IFF,RAH270"},
    {"champ": "delai_j", "priorite": "forte", "sources": "fiches_dates", "modules": "IFF,fraicheur"},
    {"champ": "nb_courses_30j", "priorite": "utile", "sources": "fiches", "modules": "fatigue"},
    {"champ": "feu_equidia", "priorite": "utile", "sources": "Equidia", "modules": "IFF_feu"},
    {"champ": "style_mpa", "priorite": "forte", "sources": "heuristique_histo", "modules": "MPA_CHAMP"},
    # Chronos / incidents
    {"champ": "rk_array_3_derniers_sec", "priorite": "forte", "sources": "fiches,open_pmu", "modules": "CRE", "hint": "trot"},
    {"champ": "rk_derniere_sec", "priorite": "forte", "sources": "fiches", "modules": "CRE", "hint": "trot"},
    {"champ": "chrono_200m", "priorite": "forte", "sources": "rare", "modules": "CRE_complet", "hint": "trot"},
    {"champ": "record_chrono_sec", "priorite": "forte", "sources": "Geny_records", "modules": "CRE_v4", "hint": "trot"},
    {"champ": "dq_12m", "priorite": "forte", "sources": "fiches", "modules": "STAB"},
    {"champ": "incidents_30j", "priorite": "forte", "sources": "fiches", "modules": "STAB,CRE"},
    # Conditions épreuve
    {"champ": "poids_actuel_kg", "priorite": "critique", "sources": "API_PMU,Equidia", "modules": "module_poids", "hint": "plat"},
    {"champ": "poids_precedent_kg", "priorite": "forte", "sources": "histo", "modules": "poids_evolution", "hint": "plat"},
    {"champ": "recul_m", "priorite": "critique", "sources": "collecte,PMU", "modules": "module_recul", "hint": "trot"},
    {"champ": "historique_recul", "priorite": "utile", "sources": "fiches", "modules": "recul_dyn"},
    {"champ": "deferre", "priorite": "forte", "sources": "PMU,fiches", "modules": "RAH163,musique_score", "hint": "trot"},
    {"champ": "ferrure_type", "priorite": "utile", "sources": "fiches", "modules": "ferrure"},
    {"champ": "numero_autostart", "priorite": "forte", "sources": "collecte,PMU", "modules": "GRU_G30", "hint": "autostart"},
    {"champ": "position_ligne", "priorite": "utile", "sources": "collecte", "modules": "GRU"},
    # Historiques contextuels
    {"champ": "historique_terrain", "priorite": "forte", "sources": "fiches", "modules": "terrain_dyn", "hint": "surface"},
    {"champ": "historique_distance", "priorite": "forte", "sources": "fiches", "modules": "DIST_ADAPT"},
    {"champ": "historique_hippodrome", "priorite": "forte", "sources": "fiches", "modules": "local"},
    {"champ": "historique_recent", "priorite": "forte", "sources": "fiches", "modules": "forme,IRP"},
    {"champ": "distance_habituelle_m", "priorite": "utile", "sources": "fiches", "modules": "DIST"},
    {"champ": "confrontations_directes", "priorite": "utile", "sources": "fiches", "modules": "H2H"},
]

CONTRAT_HOMMES: List[Dict[str, str]] = [
    {"champ": "driver_jockey", "priorite": "critique", "sources": "collecte", "modules": "BSH,tandem"},
    {"champ": "driver_fiche_url", "priorite": "critique", "sources": "Turfoo,CT,ZT", "modules": "stats_fenetres"},
    {"champ": "driver_stats", "priorite": "critique", "sources": "fiche_personne", "modules": "BSH_v3v4"},
    {"champ": "entraineur", "priorite": "critique", "sources": "collecte", "modules": "BSC,tandem"},
    {"champ": "entraineur_fiche_url", "priorite": "forte", "sources": "fiches_personne", "modules": "BSC"},
    {"champ": "trainer_stats", "priorite": "forte", "sources": "fiche_personne", "modules": "BSC"},
    {"champ": "tandem_driver_cheval", "priorite": "forte", "sources": "fiche_jockey_Turfoo", "modules": "tandem_PCH"},
    {"champ": "driver_precedent", "priorite": "utile", "sources": "PMU,fiches", "modules": "changement_hommes"},
    {"champ": "changement_driver", "priorite": "utile", "sources": "PMU", "modules": "catalogue"},
    {"champ": "changement_entraineur", "priorite": "utile", "sources": "PMU", "modules": "catalogue"},
    {"champ": "driver_est_entraineur", "priorite": "utile", "sources": "detection", "modules": "bonus_malus"},
]

CONTRAT_PRESSE: List[Dict[str, str]] = [
    {"champ": "icp_global", "priorite": "forte", "sources": "Frequence_Turf,stats_quinte", "modules": "GMO_pboost,RAH90,roles_VALUE"},
    {"champ": "icp_pondere", "priorite": "forte", "sources": "Frequence_Turf", "modules": "ICP"},
    {"champ": "citations_top5_par_source", "priorite": "forte", "sources": "Frequence_Turf", "modules": "ICP_detail"},
    {"champ": "favori_unanime", "priorite": "forte", "sources": "FT_consensus", "modules": "malus_sans_forme"},
]


def _norm_disc(disc) -> str:
    if disc is None:
        return ""
    if hasattr(disc, "value"):
        disc = disc.value
    s = str(disc).upper()
    if "ATTEL" in s or "MONT" in s or "TROT" in s:
        return "TROT"
    if "PLAT" in s or "GALOP" in s:
        return "PLAT"
    if "HAIE" in s or "STEEP" in s or "OBST" in s:
        return "OBSTACLE"
    return s


def _applicable(entry: Dict[str, str], disc_fam: str, race: RaceContext) -> bool:
    hint = entry.get("hint") or ""
    if not hint:
        return True
    if hint == "plat" and disc_fam != "PLAT":
        return False
    if hint == "trot" and disc_fam != "TROT":
        return False
    if hint == "surface" and disc_fam == "TROT":
        return False
    if hint == "handicap":
        type_course = str(getattr(race, "type_course", "") or "").upper()
        if "HANDICAP" not in type_course or disc_fam == "TROT":
            return False
    if hint == "autostart":
        dep = str(getattr(race, "depart", "") or "").upper()
        if "AUTO" not in dep:
            return False
    return True


def _fill_rate_cheval(chevaux: List[Cheval], champ: str) -> Tuple[int, int, float]:
    n = len(chevaux) or 1
    filled = sum(1 for c in chevaux if not _vide(_get(c, champ)))
    return filled, n, round(filled / n, 3)


def evaluate_data_contract(race: RaceContext, chevaux: List[Cheval]) -> Dict[str, Any]:
    """Évalue le contrat de données post-enrichissement, pré-scoring.

    Retourne un rapport structuré : par famille, taux, lacunes critiques,
    tableau ligne à ligne (champ, priorité, sources, taux, statut).
    """
    disc_fam = _norm_disc(getattr(race, "discipline", None))
    lignes: List[Dict[str, Any]] = []
    lacunes_critiques: List[str] = []
    lacunes_fortes: List[str] = []

    # --- Course ---
    for e in CONTRAT_COURSE:
        if not _applicable(e, disc_fam, race):
            continue
        val = _get(race, e["champ"])
        ok = not _vide(val)
        # partants_confirmes: aussi len(chevaux)
        if e["champ"] == "partants_confirmes" and not ok:
            ok = len(chevaux) >= 8
        statut = "OK" if ok else ("LACUNE_CRITIQUE" if e["priorite"] == "critique" else (
            "LACUNE_FORTE" if e["priorite"] == "forte" else "LACUNE_UTILE"))
        if not ok and e["priorite"] == "critique":
            lacunes_critiques.append(f"course.{e['champ']}")
        elif not ok and e["priorite"] == "forte":
            lacunes_fortes.append(f"course.{e['champ']}")
        lignes.append({
            "cible": "course",
            "champ": e["champ"],
            "priorite": e["priorite"],
            "sources": e["sources"],
            "modules": e["modules"],
            "remplissage": 1.0 if ok else 0.0,
            "remplis": 1 if ok else 0,
            "total": 1,
            "statut": statut,
        })

    # --- Cheval / hommes / presse (taux sur le champ) ---
    for cible, contrat in (
        ("cheval", CONTRAT_CHEVAL),
        ("hommes", CONTRAT_HOMMES),
        ("presse", CONTRAT_PRESSE),
    ):
        for e in contrat:
            if not _applicable(e, disc_fam, race):
                continue
            filled, total, rate = _fill_rate_cheval(chevaux, e["champ"])
            # Seuils: critique < 0.70 → LACUNE_CRITIQUE ; forte < 0.50 → LACUNE_FORTE
            if e["priorite"] == "critique":
                if rate < 0.70:
                    statut = "LACUNE_CRITIQUE"
                    lacunes_critiques.append(f"{cible}.{e['champ']}={filled}/{total}")
                elif rate < 1.0:
                    statut = "PARTIEL"
                else:
                    statut = "OK"
            elif e["priorite"] == "forte":
                if rate < 0.50:
                    statut = "LACUNE_FORTE"
                    lacunes_fortes.append(f"{cible}.{e['champ']}={filled}/{total}")
                elif rate < 1.0:
                    statut = "PARTIEL"
                else:
                    statut = "OK"
            else:
                statut = "OK" if rate >= 0.30 else "LACUNE_UTILE"
            lignes.append({
                "cible": cible,
                "champ": e["champ"],
                "priorite": e["priorite"],
                "sources": e["sources"],
                "modules": e["modules"],
                "remplissage": rate,
                "remplis": filled,
                "total": total,
                "statut": statut,
            })

    n_crit = sum(1 for L in lignes if L["priorite"] == "critique")
    n_crit_ok = sum(1 for L in lignes if L["priorite"] == "critique" and L["statut"] in ("OK", "PARTIEL"))
    score_critique = round(n_crit_ok / max(n_crit, 1), 3)
    score_global = round(
        sum(L["remplissage"] for L in lignes) / max(len(lignes), 1),
        3,
    )

    verdict = "CONFORME"
    if lacunes_critiques:
        verdict = "LACUNES_CRITIQUES"
    elif lacunes_fortes:
        verdict = "LACUNES_FORTES"

    return {
        "verdict": verdict,
        "discipline_famille": disc_fam,
        "nb_lignes": len(lignes),
        "score_completude_global": score_global,
        "score_completude_critique": score_critique,
        "nb_lacunes_critiques": len(lacunes_critiques),
        "nb_lacunes_fortes": len(lacunes_fortes),
        "lacunes_critiques": lacunes_critiques[:40],
        "lacunes_fortes": lacunes_fortes[:40],
        "tableau": lignes,
        "resume_par_cible": {
            cible: {
                "nb": sum(1 for L in lignes if L["cible"] == cible),
                "score": round(
                    sum(L["remplissage"] for L in lignes if L["cible"] == cible)
                    / max(sum(1 for L in lignes if L["cible"] == cible), 1),
                    3,
                ),
            }
            for cible in ("course", "cheval", "hommes", "presse")
        },
        "note": (
            "Contrat de données formel — évalué après enrichissement (2.7), "
            "avant scoring. Les lacunes critiques bloquent désormais la "
            "production d'un ticket certifié et sont signalées explicitement."
        ),
    }


# ===== completude.py (fusionné en v1.29.42) =====
# completude.py -- Bloc 4 (RAPPORT DE COMPLÉTUDE DE COLLECTE DE DONNÉES),
# absent du moteur Python jusqu'au 05/08/2026.
# 
# Le protocole source (Partie 6, Étape 10bis) définit TAUX_LEGACY comme un
# mécanisme de DÉGRADATION avec conséquences réelles : >=0,40 -> poids des
# modules dépendants de Bloc C réduit de 50% ; >=0,60 -> Phase B neutralisée
# (ticket structurel Borda seul, P5P6 sauté).
# 
# Décision explicite du 04/08/2026 : Phase B reste TOUJOURS activée, quel
# que soit TAUX_LEGACY -- ce module calcule et REPORTE le taux (utile pour
# comprendre pourquoi un ticket donné s'appuie plus ou moins sur des
# modules en repli), mais N'APPLIQUE AUCUNE dégradation de poids ni
# neutralisation. C'est un écart assumé au protocole source, pas un oubli
# -- documenté ici et dans le rapport d'exécution à chaque course.
# 
# Attendu, pas un bug : tant que Bloc C (RK/chronos, cf. CARTOGRAPHIE_
# DONNEES.md) n'est collecté nulle part, TAUX_LEGACY sera proche de 1.0
# sur quasi toutes les courses (P_SCORE et CRE tournent alors TOUJOURS en
# repli, PENTE_SCORE n'étant lui pas implémenté du tout). Le chiffre est
# honnête, pas défaillant.
from statistics import mean
from typing import List, Dict, Any

from app.models import Cheval, HorseScore
from app.engine.synthesis import compute_iql_v2

_SEUIL_DEGRADE = 0.40
_SEUIL_NEUTRALISE = 0.60


def _indicateurs_degrades(cheval: Cheval) -> List[str]:
    """Les 4 composantes de TAUX_LEGACY (Partie 6, Étape 10bis) : P_SCORE,
    CRE, IQL_v2, PENTE_SCORE. Toutes dépendent de Bloc C, jamais collecté
    à ce jour (cf. CARTOGRAPHIE_DONNEES.md) -- 3 des 4 sont donc en
    pratique TOUJOURS déclenchées aujourd'hui."""
    actifs = []
    if cheval.chrono_200m is None and not cheval.position_mi_course_hist:
        actifs.append("PSCORE_LEGACY")  # repli musique (common.py::_style_from_musique)
    if cheval.chrono_200m is None and not (cheval.rk_array_3_derniers_sec and len(cheval.rk_array_3_derniers_sec) == 3):
        actifs.append("CRE_LEGACY")  # ni méthode complète ni proxy RK (modules_ap.py::module_m_cre)
    _, iql_source = compute_iql_v2(cheval)
    if iql_source in ("GAINS2", "NEUTRE"):
        actifs.append("IQL_LEGACY")
    actifs.append("PENTE_SCORE_NON_IMPLEMENTE")  # aucun module ne le calcule à ce jour, quelle que soit la donnée dispo
    return actifs


def compute_rapport_completude(chevaux: List[Cheval], horses: List[HorseScore] = None) -> Dict[str, Any]:
    par_cheval = []
    for cheval in chevaux:
        indicateurs = _indicateurs_degrades(cheval)
        par_cheval.append({
            "numero": cheval.numero, "nom": cheval.nom,
            "indicateurs_degrades": indicateurs, "nb_indicateurs": len(indicateurs),
            "legacy": len(indicateurs) >= 2,
        })

    nb = len(chevaux) or 1
    taux_legacy = round(sum(1 for c in par_cheval if c["legacy"]) / nb, 3)

    if taux_legacy >= _SEUIL_NEUTRALISE:
        seuil_franchi = "NEUTRALISATION (>=0,60) -- normalement Phase B neutralisée, ticket Borda seul"
    elif taux_legacy >= _SEUIL_DEGRADE:
        seuil_franchi = "DÉGRADATION (>=0,40) -- normalement poids Bloc-C réduit de 50%"
    else:
        seuil_franchi = "aucun (<0,40)"

    ift_course_base = None
    if horses:
        valeurs_ift = [h.synthesis.ift for h in horses if h.synthesis and h.synthesis.ift is not None]
        if valeurs_ift:
            ift_course_base = round(mean(valeurs_ift), 2)

    return {
        "taux_legacy": taux_legacy,
        "seuil_protocole_franchi": seuil_franchi,
        "phase_b_neutralisee": False,
        "note": "Phase B reste activée quel que soit le taux -- décision explicite du 04/08/2026, "
                "écart assumé au protocole source (voir docstring de ce module).",
        "ift_course_base": ift_course_base,
        "par_cheval": par_cheval,
    }
