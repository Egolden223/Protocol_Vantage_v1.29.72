"""
ghost_d.py -- Catalogue des Signaux Ghost D01-D43 (Partie 4.4 ; D27 est
obsolète/jamais utilisé dans le texte source, donc 41 signaux actifs
possibles, pas 45 -- correction du chiffre "D01-D45" utilisé par erreur
dans PASSATION_02092026.md, section 5 : le catalogue s'arrête à D43).
Alimente tocard_score (plafond global 1.0, appliqué en aval dans
pch_final.py -- pas re-plafonné ici).

42/42 signaux catalogue actifs dans ce fichier (+ D40 en pch_final) --
vague 7 : D18/D20/D24/D30/D35 remplacés par signaux T3/T4 codifiables, en 4 vagues : D01/D06/D17/D22 (1re, 02/09),
D23/D29/D33/D34/D36/D37/D39/D41/D42/D43 (2e, même jour, en priorisant
les signaux référençant des modules déjà calculés dans pch_final.py --
même logique que csf.py), D07/D26 (3e, grâce à Cheval.
historique_hippodrome, cf. models.py), D02/D10/D11/D12/D13 (4e,
04/09 -- D02 en version mono-course dégradée, cf. fonction dédiée ;
D11/D12 généralisent l'exemple ATTENTISTE/fond du texte source à son
symétrique MENEUR/sprint, cf. _profil_coherent_distance). Catalogue COMPLET codifiable (29/09/2026) :
  42/42 IDs actifs (D27 obsolète retiré). Les 5 signaux historiques
  non observables en open data (D18 maternité, D20/D30 passage 400m,
  D24 workout, D35 headgear hors œillères) ont été RETIRÉS et
  REMPLACÉS par des signaux T3/T4 codifiables (même IDs, sémantique
  nouvelle documentée ci-dessous et dans le code) :
  - D18 : drift de cote (soutien marché tardif sur outsider)
  - D20 : changement de driver vers profil plus fort + cote longue
  - D24 : jeune (âge≤5) en forme + cote longue
  - D30 : bon numéro / corde / autostart + cote longue
  - D35 : oublié de la presse (ICP faible) + forme + cote longue
  D40 reste calculé en 2e passe (pch_final / OVERBET).
"""
from __future__ import annotations
from typing import List, Optional, Tuple
from app.models import Cheval, RaceContext, TypeCourse, Depart, StyleMPA
from app.engine.common import disc_bucket
from app.scraping.musique import parse_musique


# ---------------------------------------------------------------------------
# REGISTRE FORMEL du catalogue Ghost D (42/42 codifiés — 29/09/2026)
# D27 = obsolète (hors catalogue). Chaque ID alimente tocard_score via Σ.
# ---------------------------------------------------------------------------
GHOST_D_CATALOG: dict = {
    "D01": "Outsider mûr (forme récente + cote stable longue)",
    "D02": "Forme cachée par incidents excusés (commentaire)",
    "D03": "Driver en forme négligé par le marché",
    "D04": "Entraîneur bien classé, cheval sous-coté",
    "D05": "Forme musique FORTE/RÉGULIÈRE ignorée",
    "D06": "Spécialiste terrain non exploité",
    "D07": "Spécialiste hippodrome négligé",
    "D08": "Retour après long délai / indices repos (proxy)",
    "D09": "Déferré / ferrure rare sous-cotée",
    "D10": "Tandem driver-cheval fort, peu coté",
    "D11": "Distance jamais testée, profil adapté",
    "D12": "Hippodrome neuf, profil GRU favorable",
    "D13": "Changement d'équipement",
    "D14": "Perf. étrangère / hors pattern Europe (proxy)",
    "D15": "H2H normé fort sous-évalué (proxy)",
    "D16": "Œillères / premières œillères sous-cotées",
    "D17": "Profil MPA adapté au rythme, ignoré",
    "D18": "Drift de cote (soutien marché tardif outsider)",
    "D19": "H2H brut fort sous-évalué",
    "D20": "Changement driver vers meilleur profil",
    "D21": "Campagne légère (peu de courses 30j)",
    "D22": "Manque de confiance public (ICP bas + valeur)",
    "D23": "Stagnation statistique trompeuse",
    "D24": "Jeune en forme + cote longue",
    "D25": "Changement de discipline (musique vs course)",
    "D26": "Parcours difficile négligé (+ hippos techniques)",
    "D28": "Gains relatifs bas + forme (proxy oublié marché)",
    "D29": "RK Top2 du champ, cote disproportionnée (TROT)",
    "D30": "Bon draw / autostart + cote longue",
    "D31": "Poids favorable (MODULE_POIDS) non valorisé",
    "D32": "Descente de valeur handicap sous-cotée",
    "D33": "Petit poids bon engagement (PLAT HANDICAP)",
    "D34": "Faible recul + bon RK (TROT HANDICAP)",
    "D35": "Oublié de la presse (ICP faible) + forme",
    "D36": "Recul favorable sous-coté",
    "D37": "Bonne progression DIST_ADAPT non valorisée",
    "D38": "Tandem H2H-04 fort + cote longue",
    "D39": "TANDEM_BONUS fort, peu coté presse",
    "D40": "OVERBET sous-cote (2e passe pch_final)",
    "D41": "Combinaison fantôme (≥3 signaux D)",
    "D42": "D4 autostart risque faute (TROT)",
    "D43": "Outsider driver d'exception",
}
GHOST_D_OBSOLETE = {"D27"}
GHOST_D_ACTIVE_IDS = tuple(sorted(GHOST_D_CATALOG.keys(), key=lambda x: int(x[1:])))
assert len(GHOST_D_CATALOG) == 42


# --- D02 (EE_CUMULÉ), taxonomie exacte du texte source. NON-excuses
# vérifiées EN PREMIER et prioritaires : si l'une d'elles apparaît, le
# commentaire est traité comme un aveu de faute, jamais comme une excuse,
# même si un mot de la catégorie A/B/C apparaît par ailleurs dans la
# même phrase.
_D02_NON_EXCUSES = ("a longtemps été au galop", "a fauté", "semblait éprouver des difficultés")
_D02_CAT_A = ("gêné", "bloqué", "manque de champ libre", "coincé dans le peloton",
              "chute causée par un contact", "victime d'une chute", "bousculé",
              "accident au départ", "gêné au départ", "s'est empêtré au départ")
_D02_CAT_B = ("terrain ne lui convenait pas", "n'a pas apprécié le terrain", "terrain inadapté",
              "terrain trop lourd pour lui", "déferré en course", "a perdu un fer",
              "bris de matériel", "incident mécanique", "problème de sulky")
_D02_CAT_C = ("indisposition", "soigné par le vétérinaire", "légère blessure",
              "blessure sans gravité", "blessure superficielle")


def _d02_ee_score_mono_course(cheval: Cheval) -> float:
    """Version DÉGRADÉE de D02/EE_CUMULÉ : le texte source agrège les 3
    dernières courses (poids_récence 1.0/0.65/0.35), mais
    Cheval.commentaire_derniere_course ne couvre QUE la toute dernière
    course -- aucun historique de commentaire officiel sur les courses
    n-1/n-2 n'est scrapé nulle part dans ce projet. Recalculer un vrai
    EE_CUMULÉ sur 3 courses est donc structurellement impossible pour
    l'instant ; ce qui suit est la version mono-course explicitement
    évoquée par le texte source lui-même ("[Remplace D02 mono-course]"),
    avec poids_récence=1.0 pour l'unique course disponible. Recherche de
    sous-chaînes littérale (pas d'interprétation sémantique) -- même
    prudence que ssfo.py::f4, mais taxonomie à 3 niveaux ici, donc risque
    de mauvaise catégorisation plus élevé si les listes de mots-clés sont
    trop larges : elles sont volontairement resserrées sur les
    formulations les plus explicites du texte source, pas étendues par
    déduction."""
    if not cheval.commentaire_derniere_course:
        return 0.0
    txt = cheval.commentaire_derniere_course.lower()
    if any(ne in txt for ne in _D02_NON_EXCUSES):
        return 0.0
    if any(a in txt for a in _D02_CAT_A):
        return 1.0
    if any(b in txt for b in _D02_CAT_B):
        return 0.70
    if any(c in txt for c in _D02_CAT_C):
        return 0.50
    return 0.0




_FOND_SEUIL_M = 2400   # même seuil que GRU-DIST-2 et le reste du moteur (modules_ap.py)
_SPRINT_SEUIL_M = 1600  # même seuil que module_h_poids/module_l_mpa_champ


def _profil_coherent_distance(style: Optional[StyleMPA], distance_m: int) -> Optional[str]:
    """Généralisation de l'unique exemple donné par D11/D12 ("ATTENTISTE
    sur fond") à son symétrique naturel ("meneur sur sprint") -- logique
    de turf standard déjà implicite ailleurs dans ce moteur (un
    attentiste profite d'une longue ligne droite pour revenir, un meneur
    risque de se faire déborder sur une distance longue), et réutilise
    les seuils de distance déjà en place dans modules_ap.py (2400m,
    1600m) plutôt que d'en inventer de nouveaux. CHASSEUR/POLYVALENT ne
    sont volontairement PAS étendus : le texte source ne donne qu'un
    exemple par polarité (attentiste/fond), pas de base pour leur
    attribuer une affinité de distance particulière -- les y ajouter
    serait fabriquer une règle, pas généraliser celle qui existe.
    Retourne un libellé court pour le flag si cohérent, sinon None."""
    if style == StyleMPA.ATTENTISTE and distance_m >= _FOND_SEUIL_M:
        return "ATTENTISTE_FOND"
    if style in (StyleMPA.MENEUR_FORT, StyleMPA.MENEUR_MODERE) and distance_m < _SPRINT_SEUIL_M:
        return "MENEUR_SPRINT"
    return None


def compute_ghost_d(cheval: Cheval, race: RaceContext, champ: List[Cheval], icp_global: Optional[int],
                     iff_v2: float, module_terrain_dyn: float, mpa_champ: float,
                     module_poids: float, module_recul: float, module_dist_adapt: float,
                     tandem_final: float, breakdown_flags: List[str], nb_sf_positifs: int,
                     signaux_catalogue_ids: Optional[List[str]] = None,
                     h2h_norm: float = 0.0,
                     ) -> Tuple[float, List[str], List[Tuple[str, float]]]:
    """Retourne (somme_d, flags, contributions). somme_d → tocard_somme_d ; le
    plafond global à 1.0 du tocard_score est appliqué en aval par
    pch_final.py (formule Bloc 7 déjà en place), pas ici.

    v1.29.34 — vague 5 : D03/D04/D05/D09bis/D15proxy/D21 + cote_avant
    fallback (les signaux restants restent bloqués faute de données).
    """
    cote = cheval.cote_avant_course if cheval.cote_avant_course is not None else cheval.cote_matin
    if cote is None:
        return 0.0, ["GHOST_D_COTE_ABSENTE"], []
    try:
        cote = float(cote)
    except (TypeError, ValueError):
        return 0.0, ["GHOST_D_COTE_ABSENTE"], []

    bucket = disc_bucket(race.discipline)
    perfs = parse_musique(cheval.musique)
    autres: List[Tuple[str, float]] = []  # tous les signaux D sauf D22/D41 (gérés à part, non-cumul)

    # --- D01 Outsider mûr ---
    perfs6 = perfs[:6]
    nb_top5_6 = sum(1 for p in perfs6 if p.rang is not None and p.rang <= 5)
    cote_stable = (cheval.cote_avant_course is not None and cote > 0
                   and abs(cheval.cote_avant_course - cote) / cote < 0.10)
    if cote >= 15 and cote_stable and nb_top5_6 >= 2:
        autres.append(("D01_STRICT", 0.12))
    elif cote >= 12 and nb_top5_6 >= 1:
        autres.append(("D01_DEGRADE", 0.07))

    # --- D02 Forme cachée par incidents excusés (version mono-course, cf. fonction) ---
    # Non-cumul avec B23 (rebond après déception) si déjà actif -- même
    # événement potentiellement compté deux fois sous deux angles
    # différents ; on suppose une redondance et on suspend D02 plutôt que
    # de risquer un double comptage (simplification documentée : les 2
    # signaux sont sur des échelles différentes, PCH vs tocard, donc
    # "prendre le plus fort des deux" du texte source n'est pas
    # directement comparable -- on privilégie B23, plus fiable car sans
    # catégorisation de texte libre).
    if not (signaux_catalogue_ids and "B23" in signaux_catalogue_ids):
        ee_score = _d02_ee_score_mono_course(cheval)
        if ee_score >= 1.00 and cote >= 10:
            autres.append(("D02_STRICT", 0.12))
        elif ee_score >= 0.65 and cote >= 8:
            autres.append(("D02_DEGRADE", 0.08))
        elif ee_score >= 0.35 and cote >= 6:
            autres.append(("D02_MINIMAL", 0.04))
        elif ee_score >= 0.35:
            autres.append(("D02_DERNIER_RECOURS", 0.02))

    # --- D06 Spécialiste terrain non exploité par le marché ---
    if module_terrain_dyn >= 10 and cote >= 15 and (icp_global or 0) <= 1:
        autres.append(("D06", 0.12))

    # --- D07 Spécialiste hippodrome actuel négligé ---
    # Seuil MINIMAL du texte source ("abaissé à 1 Top3 pour Graignes
    # spécifiquement") non repris : aucun moyen de distinguer les
    # hippodromes à faible volume dans les données actuelles, et
    # généraliser à un seul hippodrome nommément cité serait arbitraire.
    if cheval.historique_hippodrome:
        nb_top5_hippo = sum(1 for h in cheval.historique_hippodrome if h.rang is not None and h.rang <= 5)
        nb_top3_hippo = sum(1 for h in cheval.historique_hippodrome if h.rang is not None and h.rang <= 3)
        if nb_top5_hippo >= 3 and cote >= 12 and (icp_global or 0) <= 2:
            autres.append(("D07_STRICT", 0.12))
        elif nb_top5_hippo >= 2 and cote >= 10:
            autres.append(("D07_DEGRADE", 0.07))
        elif nb_top3_hippo >= 1 and cote >= 15:
            autres.append(("D07_MINIMAL", 0.04))

    # --- D26 Parcours réputé difficile négligé (2 cas explicites du texte source) ---
    hippo_upper = (race.hippodrome or "").strip().upper()
    parcours_difficile = (
        (hippo_upper == "VINCENNES" and bucket == "TROT")
        or (hippo_upper == "AUTEUIL" and race.discipline.value == "STEEPLE")
    )
    if parcours_difficile and cheval.historique_hippodrome and cote >= 15 and (icp_global or 0) <= 1:
        if any(h.rang is not None and h.rang <= 5 for h in cheval.historique_hippodrome):
            autres.append(("D26", 0.10))

    # --- D17 Profil MPA parfaitement adapté au rythme mais ignoré ---
    if mpa_champ >= 15 and cote >= 15 and (icp_global or 0) <= 1:
        autres.append(("D17", 0.12))

    # --- D10 Tandem driver-cheval historiquement fort mais peu coté ---
    if cheval.tandem_driver_cheval and cheval.tandem_driver_cheval.courses_ensemble >= 5 and cote >= 12:
        taux_top5_tandem = cheval.tandem_driver_cheval.places_top5_ensemble / cheval.tandem_driver_cheval.courses_ensemble
        if taux_top5_tandem >= 0.70:
            autres.append(("D10", 0.12))

    # --- D11 Distance jamais testée mais profil adapté ---
    distance_deja_testee = bool(cheval.historique_distance) and any(
        h.valeur is not None and abs(h.valeur - race.distance_m) <= 100 for h in cheval.historique_distance)
    if not distance_deja_testee and cote >= 15:
        profil = _profil_coherent_distance(cheval.style_mpa, race.distance_m)
        if profil:
            autres.append((f"D11_{profil}", 0.08))

    # --- D12 Hippodrome neuf pour le cheval mais profil GRU favorable ---
    if not cheval.historique_hippodrome and cote >= 15:
        profil = _profil_coherent_distance(cheval.style_mpa, race.distance_m)
        if profil:
            autres.append((f"D12_{profil}", 0.10))

    # --- D13 Changement d'équipement (palier MINIMAL seulement) ---
    # STRICT/DÉGRADÉ demandent "premières œillères" + historique de
    # l'entraîneur avec ce type d'équipement -- ni l'un ni l'autre n'est
    # distingué dans les données actuelles (equip_changes est un simple
    # compteur, pas un type d'équipement ni un historique entraîneur).
    if cheval.equip_changes and cheval.equip_changes > 0:
        autres.append(("D13_MINIMAL", 0.08))

    # --- D23 Stagnation statistique trompeuse ---
    if len(perfs) >= 3 and cote >= 15 and all(p.rang is not None and 2 <= p.rang <= 5 for p in perfs[:3]):
        autres.append(("D23", 0.10))

    # --- D29 RK Top2 du champ mais cote disproportionnée (TROT) ---
    if bucket == "TROT" and cote >= 12 and cheval.rk_array_3_derniers_sec:
        rk_self = cheval.rk_array_3_derniers_sec[-1]
        if rk_self is not None:
            rks_champ = sorted(
                c.rk_array_3_derniers_sec[-1] for c in champ
                if c.rk_array_3_derniers_sec and c.rk_array_3_derniers_sec[-1] is not None)
            if len(rks_champ) >= 3 and rk_self in rks_champ[:2]:
                autres.append(("D29", 0.12))

    # --- D33 Petit poids avec bon engagement (PLAT HANDICAP) ---
    if bucket == "PLAT" and race.type_course == TypeCourse.HANDICAP and \
            module_poids >= 15 and cote >= 15 and (icp_global or 0) <= 1:
        autres.append(("D33", 0.12))

    # --- D34 Faible recul avec bon RK (TROT HANDICAP) ---
    if bucket == "TROT" and race.type_course == TypeCourse.HANDICAP and \
            module_recul >= 12 and cote >= 15 and (icp_global or 0) <= 1:
        autres.append(("D34", 0.12))

    # --- D36 Recul favorable sous-coté ---
    if module_recul >= 10 and cote >= 12:
        autres.append(("D36_STRICT", 0.20))
    elif module_recul >= 6 and cote >= 10:
        autres.append(("D36_DEGRADE", 0.10))

    # --- D37 Bonne progression MODULE_DIST_ADAPT non valorisée ---
    if module_dist_adapt >= 12 and cote >= 15 and (icp_global or 0) <= 1:
        autres.append(("D37", 0.10))

    # --- D39 TANDEM_BONUS fort mais cheval peu coté presse ---
    if tandem_final >= 10 and (icp_global or 0) <= 1 and cote >= 12:
        autres.append(("D39", 0.10))

    # --- D42 D4 autostart -- risque de faute au départ (TROT) ---
    if "STAB_DQ_SERIE_CRITIQUE" not in breakdown_flags and bucket == "TROT" and \
            cheval.ferrure_type == "D4" and race.depart == Depart.AUTOSTART:
        antecedent = (cheval.dq_12m or 0) > 0
        if race.distance_m <= 2200:
            autres.append(("D42_STRICT", 0.10) if antecedent else ("D42_MINIMAL", 0.05))
        elif race.distance_m <= 2700:
            autres.append(("D42_DEGRADE_FOND", 0.07) if antecedent else ("D42_MINIMAL_FOND", 0.04))

    # --- D43 Outsider driver d'exception ---
    # Non-cumul si driver == entraîneur (déjà valorisé via BSC/TANDEM_BONUS).
    if not cheval.driver_est_entraineur and cheval.driver_stats is not None and \
            cheval.driver_stats.classement_national is not None and cote >= 12:
        rang_driver = cheval.driver_stats.classement_national
        if bucket not in ("TROT", "PLAT"):
            # Classement non confirmé officiel pour l'obstacle -- palier
            # DERNIER_RECOURS forcé, cf. docstring.
            autres.append(("D43_OBS_APPROX", 0.05))
        elif cote >= 20 and rang_driver <= 3:
            autres.append(("D43_LONGSHOT", 0.22))
        elif rang_driver <= 3:
            autres.append(("D43_STRICT", 0.18))
        elif rang_driver <= 10:
            autres.append(("D43_DEGRADE", 0.12))
        elif rang_driver <= 20:
            autres.append(("D43_MINIMAL", 0.08))

    # =====================================================================
    # v1.29.34 vague 5 — signaux débloqués sur données déjà collectées
    # =====================================================================

    # --- D03 Driver en forme négligé par le marché ---
    # Proxy : taux Quinté / carrière driver > baseline + fenêtre récente si dispo.
    ds = cheval.driver_stats
    if ds is not None and cote >= 12.0 and (icp_global or 0) <= 2:
        baseline_d = {"TROT": 0.14, "PLAT": 0.12, "OBSTACLE": 0.10}.get(bucket, 0.12)
        taux_d = None
        if ds.fenetres:
            # fenêtre la plus courte disponible
            fen_sorted = sorted(ds.fenetres, key=lambda f: f.jours)
            for f in fen_sorted:
                if f.courses and f.courses >= 3:
                    taux_d = f.victoires / max(f.courses, 1)
                    break
        if taux_d is None and ds.taux_victoire_quinte is not None and (ds.nb_courses_quinte or 0) >= 5:
            taux_d = ds.taux_victoire_quinte
        elif taux_d is None and ds.taux_victoire_carriere is not None:
            taux_d = ds.taux_victoire_carriere
        if taux_d is not None and taux_d >= baseline_d + 0.05:
            if cote >= 20 and taux_d >= baseline_d + 0.10:
                autres.append(("D03_STRICT", 0.12))
            else:
                autres.append(("D03_DEGRADE", 0.07))

    # --- D04 Entraîneur bien classé, cheval sous-coté ---
    ts = cheval.trainer_stats
    if ts is not None and ts.classement_national is not None and cote >= 12.0:
        rang_e = ts.classement_national
        if rang_e <= 10 and cote >= 18 and (icp_global or 0) <= 2:
            autres.append(("D04_STRICT", 0.12))
        elif rang_e <= 20 and (icp_global or 0) <= 3:
            autres.append(("D04_DEGRADE", 0.08))
        elif rang_e <= 30 and cote >= 15:
            autres.append(("D04_MINIMAL", 0.05))

    # --- D05 Forme récente forte (musique) ignorée par le marché ---
    try:
        from app.engine.musique_features import profil_forme_recente, nb_top5_recent
        forme = profil_forme_recente(cheval.musique)
        n_top = nb_top5_recent(cheval.musique, 3)
    except Exception:
        forme, n_top = "INCONNUE", 0
    if forme == "FORTE" and cote >= 18.0 and (icp_global or 0) <= 1:
        autres.append(("D05_STRICT", 0.12))
    elif forme == "FORTE" and cote >= 14.0 and (icp_global or 0) <= 2:
        autres.append(("D05_DEGRADE", 0.08))
    elif forme == "REGULIERE" and n_top >= 2 and cote >= 20.0 and (icp_global or 0) <= 1:
        autres.append(("D05_REGULIERE", 0.06))

    # --- D09bis Déferré / ferrure rare sous-cotée (tocard, pas bonus PCH) ---
    ferr = (cheval.ferrure_type or cheval.deferre or "")
    ferr_u = str(ferr).upper().replace(" ", "")
    if ferr_u and cote >= 12.0:
        # D4 / déferré 4 pieds = signal le plus fort ; DP/DA/PP partiels plus faibles
        if ferr_u in ("D4", "D4P", "DEFERRE4", "DÉFERRÉ4") or ferr_u.startswith("D4"):
            if cote >= 20:
                autres.append(("D09BIS_D4_STRICT", 0.12))
            else:
                autres.append(("D09BIS_D4", 0.08))
        elif ferr_u in ("DP", "DA", "D0", "PP", "PA", "P4") or ferr_u.startswith("D"):
            if cote >= 15:
                autres.append(("D09BIS_PARTIEL", 0.06))

    # --- D15 proxy H2H fort sous-évalué (échelle h2h_norm ∈ [-1,1]) ---
    # Seuils source bruts (+8/+5) non dispo → mapping conservateur sur norme.
    try:
        h2h_v = float(h2h_norm or 0.0)
    except (TypeError, ValueError):
        h2h_v = 0.0
    if h2h_v >= 0.55 and cote >= 15.0 and (icp_global or 0) <= 2:
        autres.append(("D15_PROXY_STRICT", 0.12))
    elif h2h_v >= 0.35 and cote >= 12.0 and (icp_global or 0) <= 3:
        autres.append(("D15_PROXY_DEGRADE", 0.08))

    # --- D21 Campagne légère (peu de courses récentes) + cote longue ---
    nb30 = cheval.nb_courses_30j
    if nb30 is not None and nb30 <= 2 and cote >= 15.0:
        forme_ok = forme in ("FORTE", "REGULIERE") or n_top >= 1 or iff_v2 >= 0
        if forme_ok and cote >= 25.0:
            autres.append(("D21_STRICT", 0.10))
        elif forme_ok:
            autres.append(("D21_DEGRADE", 0.06))
        elif cote >= 30.0:
            autres.append(("D21_MINIMAL", 0.04))

    # --- D28 proxy : gains relatifs bas + forme + cote longue ---
    # "Petit gains / oublié du marché" codifiable sans headgear.
    gains_list = [c.gains_totaux_eur for c in champ if c.gains_totaux_eur is not None and c.gains_totaux_eur > 0]
    if cheval.gains_totaux_eur is not None and gains_list and cote >= 18.0:
        med = sorted(gains_list)[len(gains_list) // 2]
        if med > 0 and cheval.gains_totaux_eur <= 0.45 * med and forme in ("FORTE", "REGULIERE"):
            autres.append(("D28_PROXY_GAINS", 0.08))
        elif med > 0 and cheval.gains_totaux_eur <= 0.30 * med and cote >= 25.0:
            autres.append(("D28_PROXY_GAINS_MIN", 0.05))

    # --- D26 élargi : hippodromes techniques additionnels (liste fermée) ---
    # Complément aux 2 cas source (Vincennes GP / Auteuil steeple déjà plus haut).
    hippo = (getattr(race, "hippodrome", None) or "").upper()
    _DIFFICILES_EXTRA = (
        "ENGHIEN", "CAGNES", "CABOURG", "LA CAPELLE", "CAPELLE",
        "MESLAY", "CHATEAUBRIANT", "CHÂTEAUBRIANT",
    )
    if any(h in hippo for h in _DIFFICILES_EXTRA) and cote >= 12.0:
        # ne pas doubler si D26 déjà posé
        if not any(f.startswith("D26") for f, _ in autres):
            if module_terrain_dyn >= 4 or module_dist_adapt >= 6 or forme in ("FORTE", "REGULIERE"):
                autres.append(("D26_EXTRA", 0.08))
            elif cote >= 20:
                autres.append(("D26_EXTRA_MIN", 0.05))


    # =====================================================================
    # v1.29.34 vague 6 — restants codifiables (données PMU / musique / H2H)
    # =====================================================================

    # --- D16 Premières œillères / œillères actives sous-cotées ---
    # API PMU : oeilleres (SANS_OEILLERES, AVEC_OEILLERES, PREMIERE_FOIS… selon flux)
    oe = (getattr(cheval, "oeilleres", None) or "").upper().replace(" ", "_")
    if oe and oe not in ("SANS_OEILLERES", "SANS", "NONE", "NULL", ""):
        premiere = any(x in oe for x in ("PREMIERE", "PREMIÈRE", "1ERE", "1ÈRE", "FIRST", "PREMIER"))
        if premiere and cote >= 12.0:
            autres.append(("D16_PREMIERE_STRICT", 0.14) if cote >= 18 else ("D16_PREMIERE", 0.10))
        elif cote >= 15.0 and (icp_global or 0) <= 2:
            autres.append(("D16_OEILLERES", 0.08))
        elif cote >= 12.0 and cheval.equip_changes:
            autres.append(("D16_OEILLERES_MIN", 0.05))

    # --- D19 H2H brut (seuils source ≈ +5 / +8) sous-évalué ---
    h2h_brut = None
    confs = getattr(cheval, "confrontations_directes", None) or []
    if confs:
        scores = []
        for conf in confs:
            w = float(conf.get("weight", 1.0) or 1.0)
            rang = conf.get("rang")
            if rang == 1:
                scores.append(10.0 * w)
            elif rang is not None and rang <= 3:
                scores.append(2.0 * w)
            else:
                scores.append(-2.0 * w)
        if scores:
            h2h_brut = sum(scores) / len(scores)
    if h2h_brut is not None and cote >= 12.0:
        if h2h_brut >= 8.0 and cote >= 15.0 and (icp_global or 0) <= 2:
            autres.append(("D19_STRICT", 0.14))
        elif h2h_brut >= 5.0 and (icp_global or 0) <= 3:
            autres.append(("D19_DEGRADE", 0.10))
        elif h2h_brut >= 3.0 and cote >= 18.0:
            autres.append(("D19_MINIMAL", 0.06))

    # --- D38 H2H-04 tandem fort + cote longue (complément D10/D39, non redondant si H2H) ---
    td = getattr(cheval, "tandem_driver_cheval", None)
    if td is not None and cote >= 12.0 and not cheval.driver_est_entraineur:
        n_ens = int(getattr(td, "courses_ensemble", 0) or 0)
        if n_ens >= 3:
            v = int(getattr(td, "victoires_ensemble", 0) or 0)
            p5 = int(getattr(td, "places_top5_ensemble", 0) or 0)
            taux = (v + p5) / max(n_ens, 1)
            if taux >= 0.60 and n_ens >= 5 and cote >= 15.0 and (icp_global or 0) <= 2:
                # éviter double-count excessif avec D10 déjà posé
                if not any(f.startswith("D10") for f, _ in autres):
                    autres.append(("D38_TANDEM_H2H", 0.10))
                else:
                    autres.append(("D38_TANDEM_COMPLEMENT", 0.05))
            elif taux >= 0.50 and cote >= 20.0:
                autres.append(("D38_TANDEM_MIN", 0.05))

    # --- D25 Changement de discipline (musique vs course actuelle) ---
    def _disc_from_musique_token(tok: str) -> str:
        t = tok.lower().strip()
        if not t:
            return ""
        # suffixes courants musique FR : p=plat, h=haies, s/c=steeple, a/at=trot attelé, m=monté
        if t.endswith("h") or "haie" in t:
            return "HAIES"
        if t.endswith("s") or t.endswith("c") or "steeple" in t:
            return "STEEPLE"
        if t.endswith("p") or "plat" in t:
            return "PLAT"
        if t.endswith("m") and not t.endswith("cm"):
            return "TROT_MONTE"
        return "TROT"

    disc_course = (getattr(race.discipline, "value", None) or str(race.discipline or "")).upper()
    if disc_course:
        if "HAIES" in disc_course:
            disc_bucket_c = "HAIES"
        elif "STEEPLE" in disc_course or "CROSS" in disc_course:
            disc_bucket_c = "STEEPLE"
        elif "PLAT" in disc_course:
            disc_bucket_c = "PLAT"
        elif "MONTE" in disc_course:
            disc_bucket_c = "TROT_MONTE"
        else:
            disc_bucket_c = "TROT"
        mus = (cheval.musique or "").strip()
        if mus and cote >= 12.0:
            tokens = [x for x in mus.replace(",", " ").split() if x]
            recent = tokens[:4]
            prev_discs = [_disc_from_musique_token(x) for x in recent]
            prev_discs = [d for d in prev_discs if d]
            if prev_discs and all(d != disc_bucket_c for d in prev_discs[:2]):
                if cote >= 20.0:
                    autres.append(("D25_SWITCH_STRICT", 0.12))
                else:
                    autres.append(("D25_SWITCH", 0.08))
            elif prev_discs and prev_discs[0] != disc_bucket_c and cote >= 15.0:
                autres.append(("D25_SWITCH_MIN", 0.05))

    # --- D31 Poids favorable (MODULE_POIDS) non valorisé par le marché ---
    if module_poids >= 8.0 and cote >= 12.0 and (icp_global or 0) <= 2:
        autres.append(("D31_POIDS_STRICT", 0.12) if module_poids >= 12 else ("D31_POIDS", 0.08))
    elif module_poids >= 5.0 and cote >= 18.0:
        autres.append(("D31_POIDS_MIN", 0.05))

    # --- D32 Descente de valeur handicap sous-cotée ---
    vp = cheval.valeur_pmu
    vp_prev = getattr(cheval, "valeur_pmu_precedente", None)
    if vp is not None and vp_prev is not None and cote >= 12.0:
        try:
            delta_v = float(vp_prev) - float(vp)
        except (TypeError, ValueError):
            delta_v = 0.0
        if delta_v >= 8.0 and cote >= 15.0:
            autres.append(("D32_VALEUR_STRICT", 0.12))
        elif delta_v >= 4.0 and cote >= 12.0:
            autres.append(("D32_VALEUR", 0.08))
        elif delta_v >= 2.0 and cote >= 20.0:
            autres.append(("D32_VALEUR_MIN", 0.05))

    # --- D08 proxy : long délai + indices de repos/blessure dans commentaire ---
    delai = getattr(cheval, "delai_j", None)
    comm = (getattr(cheval, "commentaire_derniere_course", None) or "").lower()
    _BLESS_KW = (
        "bless", "repos", "arrêt", "arret", "convalescence", "soins", "clinique",
        "opération", "operation", "tendin", "fracture", "boiter", "période",
        "absent", "longue absence", "reprise",
    )
    has_bless_kw = any(k in comm for k in _BLESS_KW) if comm else False
    if delai is not None and delai >= 60 and cote >= 12.0:
        if has_bless_kw and delai >= 90 and cote >= 15.0:
            autres.append(("D08_RETOUR_STRICT", 0.12))
        elif has_bless_kw or delai >= 120:
            autres.append(("D08_RETOUR", 0.08))
        elif delai >= 90 and cote >= 20.0 and forme in ("FORTE", "REGULIERE"):
            autres.append(("D08_RETOUR_MIN", 0.05))

    # --- D14 proxy : perf étrangère / pattern hors Europe ---
    _ETR = (
        " usa", " gb", " ire", " irl", " uk", " ger", " ita", " spa", " bel",
        " dubai", " ascot", " newmarket", " meylan", " milan", " winsor",
        "(gb)", "(ire)", "(usa)", "(ger)", "(ita)",
    )
    hist_parts = []
    for attr in ("historique_hippodrome", "historique_distance", "historique_terrain"):
        for perf in (getattr(cheval, attr, None) or [])[:4]:
            hist_parts.append(str(getattr(perf, "lieu", "") or ""))
            hist_parts.append(str(getattr(perf, "discipline", "") or ""))
    hist_txt = " ".join(hist_parts).lower()
    mus_l = (cheval.musique or "").lower()
    flag_etr = bool(getattr(cheval, "niveau_max_hors_pattern_europeen", False))
    if not flag_etr:
        flag_etr = any(x in (" " + mus_l + " " + hist_txt) for x in _ETR)
    if flag_etr and cote >= 12.0:
        if cote >= 20.0 and (icp_global or 0) <= 2:
            autres.append(("D14_ETRANGER_STRICT", 0.10))
        else:
            autres.append(("D14_ETRANGER", 0.06))


    # =====================================================================
    # v1.29.34 vague 7 — REMPLACEMENT définitif D18/D20/D24/D30/D35
    # (anciennes définitions non observables supprimées du catalogue)
    # Objectif : renforcer la discrimination T3/T4 / outsiders viables
    # =====================================================================

    # --- D18 (remplace maternité) : drift de cote — soutien marché tardif ---
    # cote_matin longue qui se resserre avant le départ = argent intelligent
    # sur un outsider encore jouable (reste >= 12).
    cm = cheval.cote_matin
    ca = cheval.cote_avant_course
    try:
        cm_f = float(cm) if cm is not None else None
        ca_f = float(ca) if ca is not None else None
    except (TypeError, ValueError):
        cm_f, ca_f = None, None
    if cm_f is not None and ca_f is not None and cm_f >= 15.0 and ca_f >= 12.0:
        ratio = ca_f / cm_f if cm_f > 0 else 1.0
        if ratio <= 0.70 and ca_f >= 12.0:
            autres.append(("D18_DRIFT_STRICT", 0.14))
        elif ratio <= 0.85 and cm_f >= 18.0:
            autres.append(("D18_DRIFT", 0.10))
        elif ratio <= 0.92 and cm_f >= 25.0:
            autres.append(("D18_DRIFT_MIN", 0.06))

    # --- D20 (remplace passage 400m) : changement driver vers meilleur profil ---
    chg_drv = bool(getattr(cheval, "changement_driver", False))
    drv_prev = (getattr(cheval, "driver_precedent", None) or "").strip()
    drv_now = (getattr(cheval, "driver_jockey", None) or "").strip()
    if cote >= 12.0 and (chg_drv or (drv_prev and drv_now and drv_prev.lower() != drv_now.lower())):
        ds = cheval.driver_stats
        rang_d = getattr(ds, "classement_national", None) if ds else None
        taux_q = getattr(ds, "taux_victoire_quinte", None) if ds else None
        baseline = {"TROT": 0.14, "PLAT": 0.12, "OBSTACLE": 0.10}.get(bucket, 0.12)
        boost = False
        if rang_d is not None and rang_d <= 15:
            boost = True
        if taux_q is not None and taux_q >= baseline + 0.04:
            boost = True
        if boost and cote >= 15.0:
            autres.append(("D20_DRIVER_UP_STRICT", 0.12))
        elif boost or cote >= 20.0:
            autres.append(("D20_DRIVER_UP", 0.08))
        elif cote >= 18.0:
            autres.append(("D20_DRIVER_UP_MIN", 0.05))

    # --- D24 (remplace workout) : jeune en forme + cote longue ---
    age = getattr(cheval, "age", None)
    if age is not None and age <= 5 and cote >= 14.0:
        if forme == "FORTE" and cote >= 18.0:
            autres.append(("D24_JEUNE_FORTE", 0.12))
        elif forme in ("FORTE", "REGULIERE") and cote >= 15.0:
            autres.append(("D24_JEUNE_FORME", 0.08))
        elif n_top >= 1 and cote >= 20.0:
            autres.append(("D24_JEUNE_MIN", 0.05))

    # --- D30 (remplace trajet 400m) : bon draw / autostart + cote longue ---
    n_part = len(champ) if champ else 0
    num = getattr(cheval, "numero", None)
    nas = getattr(cheval, "numero_autostart", None)
    good_draw = False
    if nas is not None and nas <= 3 and bucket == "TROT":
        good_draw = True
    if num is not None and n_part >= 12 and num <= 4:
        good_draw = True
    if good_draw and cote >= 12.0:
        if cote >= 20.0 and forme in ("FORTE", "REGULIERE"):
            autres.append(("D30_DRAW_STRICT", 0.12))
        elif cote >= 15.0:
            autres.append(("D30_DRAW", 0.08))
        else:
            autres.append(("D30_DRAW_MIN", 0.05))

    # --- D35 (remplace headgear non-œillères) : oublié presse + forme ---
    icp = icp_global if icp_global is not None else 0
    icp_p = getattr(cheval, "icp_pondere", None)
    try:
        icp_p_f = float(icp_p) if icp_p is not None else None
    except (TypeError, ValueError):
        icp_p_f = None
    presse_faible = icp <= 1 or (icp_p_f is not None and icp_p_f < 2.0)
    if presse_faible and cote >= 15.0 and forme in ("FORTE", "REGULIERE"):
        if cote >= 25.0 and forme == "FORTE":
            autres.append(("D35_OUBLIE_PRESSE_STRICT", 0.14))
        elif cote >= 18.0:
            autres.append(("D35_OUBLIE_PRESSE", 0.10))
        else:
            autres.append(("D35_OUBLIE_PRESSE_MIN", 0.06))
    elif presse_faible and cote >= 30.0 and n_top >= 1:
        autres.append(("D35_OUBLIE_PRESSE_MIN", 0.05))

    # --- D22 Manque de confiance public = opportunité ---



    valeurs_champ = sorted((c.valeur_pmu for c in champ if c.valeur_pmu is not None), reverse=True)
    rang_valeur = (valeurs_champ.index(cheval.valeur_pmu) + 1
                   if cheval.valeur_pmu is not None and cheval.valeur_pmu in valeurs_champ else None)
    d22: Optional[Tuple[str, float]] = None
    if icp_global is not None:
        garde_forme_ok = (int(nb_sf_positifs >= 1) + int(iff_v2 >= 0)
                           + int((cheval.irp_score or 0) >= 0.35)) >= 2
        if icp_global <= 1 and rang_valeur is not None and rang_valeur <= 3 and garde_forme_ok:
            d22 = ("D22_STRICT", 0.30)
        elif icp_global <= 1 and rang_valeur is not None and rang_valeur <= 3:
            d22 = ("D22_FORME_INSUFFISANTE", 0.10)
        elif icp_global <= 2 and rang_valeur is not None and rang_valeur <= 5:
            d22 = ("D22_DEGRADE", 0.18)
        elif icp_global <= 1:
            d22 = ("D22_MINIMAL", 0.10)
        elif icp_global <= 2:
            d22 = ("D22_DERNIER_RECOURS", 0.05)

    # --- D41 Combinaison fantôme (>=3 signaux D actifs, D22 inclus, D41 exclu) ---
    # Non-cumul D22/D41 (texte source) : si D41 se déclenche, D22 est absorbé
    # dedans -- on prend MAX(D22, D41=0.08), jamais l'addition.
    nb_actifs = len(autres) + (1 if d22 else 0)
    flags = [f for f, _ in autres]
    somme = sum(v for _, v in autres)
    contributions: List[Tuple[str, float]] = list(autres)  # (flag_complet, valeur)
    if nb_actifs >= 3:
        flags.append("D41")
        contrib_d22_d41 = max(d22[1] if d22 else 0.0, 0.08)
        somme += contrib_d22_d41
        contributions.append(("D41", 0.08))
        if d22:
            flags.append(d22[0])
            # D22 absorbé dans le max : on journalise le flag mais la valeur
            # nette est déjà dans contrib_d22_d41 (éviter double compte Σ)
            if d22[1] > 0.08:
                contributions.append((d22[0], d22[1] - 0.08))
    elif d22:
        somme += d22[1]
        flags.append(d22[0])
        contributions.append(d22)

    if not flags:
        flags.append("GHOST_D_AUCUN_SIGNAL")
    # 3e élément : contributions pour signaux_actifs / audit (id, flag, valeur)
    return round(somme, 3), flags, contributions
