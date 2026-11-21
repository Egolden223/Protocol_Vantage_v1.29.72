"""
qualitative_engine.py -- Remplace app/llm/qualitative.py en mode 100%
Python (sans API Anthropic). Combine :
  1. catalog_rules.py : sous-ensemble fidèle des catalogues B/M (formules
     exactes du protocole, cf. ce fichier pour la liste couverte).
  2. FORME_LINEAIRE : proxy basé sur la musique (Points x Coeff_récence),
     approximation documentée -- le protocole utilise une pondération par
     catégorie de course non disponible sans page individuelle par cheval.
  3. SUPRA_score_sim / Longshot Hunter : heuristiques simplifiées pour ne
     pas neutraliser totalement le P_boost de GMO-V sur les outsiders --
     PAS une implémentation fidèle des 7 phases SUPRA / 8 familles
     Longshot (celles-ci nécessitent une lecture de texte libre).
  4. bloc5_ajustes.py : M30 (nouveau signal catalogue), correction
     d'intention M04 (poste 21) et RAH-200 convergence (poste 29) --
     patch v1.22.2-test.
  5. ssfo.py (ajouté le 02/09/2026, enrichi 12/09/2026) : 21 des 32
     signaux SSFO (RAH-271), calculés en pur Python à partir des données
     déjà collectées -- les 11 restants nécessitent une donnée non
     modélisée ou une lecture de texte libre non triviale, cf. ssfo.py.
     f9 (changement driver positif via classement maison) et f17
     (entraîneur Top20) débloqués le 12/09/2026 grâce à classement_driver
     et TrainerStats.classement_national.

Tout ce qui n'est pas listé ci-dessus (D46-D22, D02-B59, M48-B42, D45
complet, RAH-186, M33, CSF détaillé) reste à 0 avec un flag explicite
-- volontairement, pour ne jamais fabriquer un chiffre non fondé.
Note 12/09/2026 : le classement national driver/entraîneur est
maintenant disponible via les scripts offline (data/classements/) et
TrainerStats/DriverStats ; B11 et D45 peuvent être progressivement
débloqués (f17 SSFO l'est déjà).
"""
from __future__ import annotations
from typing import List, Tuple
from statistics import mean, pvariance

from app.models import Cheval, RaceContext, QualitativeSignals, CSFSignal
from app.engine.catalog_rules import compute_catalog_signals
from app.engine.discipline_modules import compute_discipline_specifique
from app.engine.discipline_detect import ensure_race_discipline
from app.engine.gamma_signals import compute_gamma_signals
from app.engine.tranches import classify_tranche
from app.engine.bloc5_ajustes import compute_m30, intention_active, compute_m04_correction, compute_rah200
from app.engine.longshot import compute_longshot_families
from app.engine.ssfo import compute_ssfo
from app.engine.synthesis import compute_sov_v2
from app.scraping.musique import parse_musique, rangs_recents

NON_IMPLEMENTE = [
    "D46_D22_NON_EVALUE", "D02_B59_NON_EVALUE", "M48_B42_NON_EVALUE", "D45_NON_EVALUE",
    "RAH186_NON_EVALUE", "M33_NON_EVALUE",     "GAMMA_RAH180_RAH186_NON_EVALUES",
    # SSFO : 21/32 au 12/09/2026 (f9 + f17 débloqués). Flags SSFO_* posés
    # par compute_ssfo. B11/D45 restent listés ici tant que leur poste PCH
    # dédié n'est pas câblé (le classement national est disponible).
    # TOCARD_GHOST_D_NON_EVALUE retiré v1.29.34 (vague 5 Ghost D codifiable)
    "SUPRA_7_PHASES_APPROXIME", "LONGSHOT_HUNTER_APPROXIME",
]

_POINTS_PLACE = {1: 10, 2: 7, 3: 5, 4: 3.5, 5: 2.5, 6: 1.5}  # v1.29.36 Top6


def _forme_lineaire(perfs, cap: float = 20.0) -> float:
    """Forme linéaire v1.29.36 : 5 dernières, places 1–6 valorisées, récence forte."""
    if not perfs:
        return 0.0
    total = 0.0
    # Focus 5 dernières sorties ; poids récence décroissant
    weights = (1.00, 0.85, 0.70, 0.55, 0.40, 0.30, 0.22, 0.15)
    for i, p in enumerate(perfs[:5]):
        if p.incident:
            points = -3.0  # malus modéré (pas -5 éliminatoire)
        else:
            points = float(_POINTS_PLACE.get(p.rang, -1.5 if (p.rang or 99) <= 9 else -2.5))
        total += points * weights[i]
    return max(-cap, min(cap, total))


def _supra_score_sim(cheval: Cheval, signaux, perfs) -> float:
    score = 0.30
    ids_actifs = {s.id for s in signaux}
    score += 0.10 if "B02" in ids_actifs else 0.0
    score += 0.10 if "B26" in ids_actifs else 0.0
    score += 0.08 if "B08" in ids_actifs else 0.0
    score += 0.06 if "B07" in ids_actifs else 0.0
    score -= 0.15 if "M01" in ids_actifs else 0.0
    score -= 0.12 if "M09" in ids_actifs else 0.0
    score -= 0.15 if "M12" in ids_actifs else 0.0
    rangs = rangs_recents(perfs, 5)
    if len(rangs) >= 3:
        var = pvariance(rangs)
        if var < 3:
            score += 0.05  # régularité
    return max(0.0, min(1.0, score))


def _supra_score_sim_v2(cheval: Cheval, signaux, perfs, race: RaceContext) -> Tuple[float, List[str]]:
    """Tente le vrai SCORE_SIM (supra_phase2.py, open-pmu-api) ; si
    désactivé (ACTIVER_SUPRA_PHASE2_REEL=False, par défaut) ou en échec,
    retombe intégralement sur l'heuristique _supra_score_sim ci-dessus --
    jamais de mélange des deux, jamais un résultat non fiable affiché
    comme fiable. Ajouté le 05/09/2026."""
    from app.engine.supra_phase2 import build_profil_gagnant_type, score_cheval_vs_profil
    resultat = build_profil_gagnant_type(race)
    flags = list(resultat.get("flags", []))
    if resultat.get("bonus_historique") is not None:
        return resultat["bonus_historique"], flags  # base insuffisante mais tentative réelle faite -- neutre 0.50
    profil = resultat.get("profil_gagnant_type")
    if profil is not None:
        return score_cheval_vs_profil(cheval, profil), flags
    # Désactivé ou échec réseau -- repli heuristique, flag ajouté pour transparence.
    flags.append("SUPRA_PHASE2_REPLI_HEURISTIQUE")
    return _supra_score_sim(cheval, signaux, perfs), flags


def _csf_signaux(perfs) -> List[CSFSignal]:
    """OBSOLÈTE depuis le 02/09/2026 -- remplacé par app/engine/csf.py
    (SF-01 à SF-24 réels, calculés dans pch_final.py après les modules
    A-P). Conservée uniquement comme valeur de départ ; systématiquement
    écrasée en aval, cf. pch_final.py::compute_module_breakdown."""
    signaux = []
    rangs = rangs_recents(perfs, 5)
    if len(rangs) >= 3:
        var = pvariance(rangs)
        if var < 2.5:
            signaux.append(CSFSignal(id="SF-REGULARITE", valeur=4, famille="F"))
        elif var > 12:
            signaux.append(CSFSignal(id="SF-IRREGULARITE", valeur=-3, famille="F"))
    return signaux


def compute_qualitative_signals_python(race: RaceContext, chevaux: List[Cheval]) -> List[QualitativeSignals]:
    try:
        ensure_race_discipline(race)
    except Exception:
        pass
    results = []

    # --- 17.5(d) CHAMP_A_RISQUE_DQ_ELEVE : >=3 chevaux du champ avec "D"
    # dans les 2 dernières courses -- ajouté le 09/08/2026, absent jusque-là.
    # Transmis à GMO-V pour vérifier qu'au moins une réserve a un profil
    # STAB propre (garde-fou informatif, pas un blocage dur).
    nb_champ_d_recent = 0
    for c in chevaux:
        p = parse_musique(c.musique)
        if any(perf.incident == "DISQUALIFIE" for perf in p[:2]):
            nb_champ_d_recent += 1
    race._champ_a_risque_dq_eleve = nb_champ_d_recent >= 3

    for cheval in chevaux:
        perfs = parse_musique(cheval.musique)
        signaux = compute_catalog_signals(cheval, race, chevaux)
        signaux = signaux + list(cheval.signaux_precalcules)  # B04/B05/B17/B19/M03/M04/M10/M21/M23 (enrichissement)
        signaux = signaux + compute_gamma_signals(cheval, race, chevaux)  # RAH-179/182/183/184
        m30_signal = compute_m30(cheval, perfs)
        if m30_signal is not None:
            signaux = signaux + [m30_signal]
        forme_lin = _forme_lineaire(perfs)
        score_sim, supra_phase2_flags = _supra_score_sim_v2(cheval, signaux, perfs, race)
        longshot_result = compute_longshot_families(cheval, race, chevaux, signaux)
        ls_familles = longshot_result.get("familles_scores", {})
        csf = _csf_signaux(perfs)
        discipline_val, discipline_flags = compute_discipline_specifique(cheval, race)

        # --- Postes 21 (M04 ajusté) et 29 (RAH-200), patch v1.22.2-test ---
        tranche = classify_tranche(cheval.cote_matin, getattr(cheval, "cote_avant_course", None) or cheval.cote_matin)
        intention = intention_active(score_sim)
        m04_correction, m04_flags = compute_m04_correction(signaux, tranche, intention)
        rah200_val, rah200_flags = compute_rah200(signaux, intention)

        # --- SSFO (RAH-271), ajouté le 02/09/2026 -- sov_v2 recalculé ici
        # (valeur canonique définie dans synthesis.py, dupliquée car cette
        # étape s'exécute avant le passage synthesis de race_pipeline.py ;
        # le plafond PCH_FINAL>=160 est appliqué a posteriori dans
        # race_pipeline.py, pch_final n'étant pas encore connu ici).
        # breakdown_flags=[] ici : STAB_DQ_SERIE_CRITIQUE (utilisé par f32)
        # n'est posé que dans compute_module_breakdown, en aval -- f32
        # s'appuie donc uniquement sur dq_12m/dq_5_dernieres_tentees à ce
        # stade, pas sur ce flag précis. Limitation documentée, pas une
        # invention de valeur.
        sov_v2, _ = compute_sov_v2(cheval, tranche)
        bonus_ssfo, ssfo_detail, ssfo_flags = compute_ssfo(cheval, race, sov_v2, [])

        omission_candidate = (
            cheval.cote_matin is not None and cheval.cote_matin > 12
            and score_sim >= 0.45
            and sum(1 for s in signaux if s.catalog == "M") == 0
        )

        results.append(QualitativeSignals(
            signaux_catalogue=signaux,
            forme_lineaire_pch=forme_lin,
            m04_pch=m04_correction,
            rah200_pch=rah200_val,
            csf_signaux=csf,
            discipline_specifique_pch=discipline_val,
            supra_verdict="POSITIF" if score_sim >= 0.55 else "NEUTRE" if score_sim >= 0.35 else "RESERVE",
            supra_score_sim=score_sim,
            supra_omission_candidate=omission_candidate,
            supra_phases={
                "note": "approximation heuristique -- pas les 7 phases SUPRA complètes",
                "longshot_eligible": longshot_result.get("eligible", False),
                "longshot_ls_final": longshot_result.get("ls_final", 0.0),
                "longshot_famille_dominante": longshot_result.get("famille_dominante"),
                "longshot_palier": longshot_result.get("palier"),
            },
            ls_final_par_famille=ls_familles,
            bonus_ssfo=bonus_ssfo,
            flags=(list(NON_IMPLEMENTE) + discipline_flags + m04_flags + rah200_flags
                   + longshot_result.get("flags", []) + ssfo_flags + supra_phase2_flags),
            justifications=({"ssfo_detail": str(ssfo_detail)} if ssfo_detail else {}),
        ))
    return results
