"""
Modèles de données PROTOCOL VANTAGE v1.22.2-test
==================================================
Schéma fidèle au tableau unifié de collecte (Partie 2bis, Blocs A-P) et
aux besoins des Modules A-P (Partie 3) et des formules de synthèse
(Partie 9). Tous les champs "réels" sont Optional : une donnée absente
n'est jamais inventée (RÈGLE 2), elle reste None et les fallbacks
documentés dans le protocole s'appliquent module par module.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field


class Discipline(str, Enum):
    TROT_ATTELE = "TROT_ATTELE"
    TROT_MONTE = "TROT_MONTE"
    PLAT = "PLAT"
    HAIES = "HAIES"
    STEEPLE = "STEEPLE"


class TypeCourse(str, Enum):
    CONDITIONS = "CONDITIONS"
    HANDICAP = "HANDICAP"
    CLAIMER = "CLAIMER"
    AUTRE = "AUTRE"


class Depart(str, Enum):
    AUTOSTART = "AUTOSTART"
    VOLTE = "VOLTE"
    CENTRE = "CENTRE"


class StyleMPA(str, Enum):
    MENEUR_FORT = "MENEUR_FORT"
    MENEUR_MODERE = "MENEUR_MODERE"
    ATTENTISTE = "ATTENTISTE"
    CHASSEUR = "CHASSEUR"
    POLYVALENT = "POLYVALENT"


class Signature(str, Enum):
    LOCK = "LOCK"
    STANDARD = "STANDARD"
    CHAOS = "CHAOS"
    MIXTE_LOCK = "MIXTE_LOCK"


class Tranche(str, Enum):
    T1 = "T1"   # < 9/1 favoris
    T2 = "T2"   # 9-15/1 semi-favoris
    T3 = "T3"   # 15-35/1 outsiders utiles top5 (calibrage 2026-09-18)
    T4A = "T4a"  # 35-100/1 longshots
    T4B = "T4b"  # 100-300/1 extrêmes


class RaceContext(BaseModel):
    """Bloc 1 -- Accusé de réception / métadonnées de la course."""
    url_source: str
    hippodrome: str
    discipline: Discipline
    distance_m: int
    type_course: TypeCourse
    depart: Depart
    partants_confirmes: int
    allocation_eur: Optional[float] = None
    penetrometre: Optional[float] = None
    terrain_qualificatif: Optional[str] = None
    conditions_particulieres: Optional[str] = None
    date_course: Optional[str] = None  # ISO date
    reunion_course_label: Optional[str] = None  # ex "R1C3"

    # renseigné à l'étape 2 du protocole (avant Bloc 8)
    signature: Optional[Signature] = None
    nb_meneurs_champ: Optional[int] = None
    rythme_projete: Optional[str] = None  # LENT|CONTROLE|MODERE|RAPIDE|TRES_RAPIDE
    poids_champ_kg: Optional[List[float]] = None  # v1.29.41 : poids portés de TOUT le champ (dérivé en amont du scoring)
    # v1.29.57 : IIC-v2 (signature = 70 % marché + 30 % contexte) — renseigné par determine_signature, repris dans l'audit
    iic_v2: Optional[float] = None
    iic_market: Optional[float] = None
    market_metrics: Optional[Dict[str, Any]] = None

    # Météo -- absent du modèle avant le 03/08/2026, source : Frequence-Turf
    # (page base-tocard, texte libre). Optionnel, jamais bloquant.
    meteo_temp_c: Optional[float] = None
    meteo_vent_kmh_max: Optional[float] = None
    meteo_risque_pluie: Optional[bool] = None


class TandemStats(BaseModel):
    courses_ensemble: int = 0
    victoires_ensemble: int = 0
    places_top5_ensemble: int = 0
    jours_depuis_derniere_association: Optional[int] = None
    # % de réussite Top5 sur 6 mois -- source Frequence-Turf (table
    # "Meilleurs tandems"), ajouté le 02/09/2026. Distinct des compteurs
    # ci-dessus (courses_ensemble/victoires_ensemble, format Turfoo/
    # CanalTurf) : FT ne donne qu'un taux, jamais les compteurs bruts --
    # ne pas en déduire victoires_ensemble/courses_ensemble (RÈGLE 2).
    taux_top5_6m: Optional[float] = None


class DriverTrainerWindow(BaseModel):
    """Une fenêtre temporelle (ex 7j/14j/30j) pour BSH/BSC."""
    jours: int
    victoires: int = 0
    courses: int = 0


class DriverStats(BaseModel):
    fenetres: List[DriverTrainerWindow] = Field(default_factory=list)
    taux_hippodrome: Optional[float] = None
    taux_distance: Optional[float] = None
    taux_top1_20j: Optional[float] = None  # utilisé par BSH-v4 (RAH allocation <=50k)
    classement_national: Optional[int] = None
    dq_12m: int = 0
    nb_courses_12m: int = 0
    # % de réussite Top5 sur 6 mois, parmi les partants du jour -- source
    # Frequence-Turf (table "Meilleurs drivers"), ajouté le 02/09/2026.
    # Métrique DIFFÉRENTE de classement_national (rang absolu Cravache/
    # Sulky d'Or, toute la profession) : un taux relatif au champ du jour.
    taux_top5_6m: Optional[float] = None
    # Taux de victoire carrière (toutes courses PMU) et spécifique
    # Quinté+ -- source CanalTurf (canalturf_fiche_personne.py, scrapé
    # depuis le 04/08/2026 mais jamais lu jusqu'au 03/09/2026). Le taux
    # Quinté est prioritaire quand disponible (>=5 courses) : plus
    # pertinent pour ce protocole, qui ne prédit QUE des Quintés, qu'un
    # taux toutes-courses-confondues.
    taux_victoire_carriere: Optional[float] = None
    nb_courses_quinte: Optional[int] = None
    taux_victoire_quinte: Optional[float] = None


class TrainerStats(BaseModel):
    fenetres: List[DriverTrainerWindow] = Field(default_factory=list)
    # cf. DriverStats.taux_top5_6m -- même source, même sémantique, pour
    # l'entraîneur (table "Meilleurs entraîneurs").
    taux_top5_6m: Optional[float] = None
    # cf. DriverStats -- mêmes champs, même source CanalTurf, débloqués
    # en même temps le 03/09/2026.
    taux_victoire_carriere: Optional[float] = None
    nb_courses_quinte: Optional[int] = None
    taux_victoire_quinte: Optional[float] = None
    # Classement national entraîneur -- N'EXISTAIT PAS avant le
    # 06/09/2026 (seul le classement driver/jockey Cravache/Sulky d'Or
    # est scrapé). Alimenté par un classement construit hors-ligne à
    # partir du corpus open-pmu-api (scripts/build_classement_
    # entraineurs.py), PAS une source officielle -- débloque D45/B11/
    # affine RAH-181. Cf. app/engine/classement_entraineur.py.
    classement_national: Optional[int] = None


class PerfHistorique(BaseModel):
    """Une performance passée utile pour terrain / distance / recul / H2H."""
    valeur: float           # pénétromètre, distance (m) ou recul (m) selon contexte
    rang: int
    date: Optional[str] = None
    incident: bool = False
    # Discipline de la course (PLAT/TROT_*/HAIES/STEEPLE) -- extrait fiche
    # Turfoo depuis le 12/09/2026. Optionnel : None si source sans discipline.
    discipline: Optional[str] = None


class Cheval(BaseModel):
    """Une ligne complète du tableau unifié de collecte (Blocs A-O)."""
    numero: int
    nom: str

    # Bloc A -- identité
    age: Optional[int] = None
    sexe: Optional[str] = None
    driver_jockey: Optional[str] = None
    # Nom du driver/jockey lors de la dernière course connue de ce
    # cheval (peut différer de driver_jockey ci-dessus si changement) --
    # ajouté le 06/09/2026 pour B11 (comparaison de classement driver
    # ancien vs nouveau). Alimenté par CanalTurf (dernieres_perfs[0].jockey,
    # trié par date) quand disponible.
    driver_precedent: Optional[str] = None
    entraineur: Optional[str] = None
    proprietaire: Optional[str] = None

    # Bloc B -- cotes (2 points, SOV v2)
    cote_matin: Optional[float] = None
    cote_avant_course: Optional[float] = None
    valeur_pmu: Optional[float] = None
    sov_repli_utilise: bool = False
    # Multi-bookmakers / timeline (levier SOV 12/09/2026)
    # cotes_timeline : [{heure: "10h", cote: 8.5, bookmaker: "PMU"}, ...]
    # ordonnée chronologiquement si possible -- 1er = matin, dernier = avant course
    cotes_timeline: Optional[List[Dict[str, Any]]] = None
    # Dernière cote connue par bookmaker (PMU / ZETURF / BETCLIC)
    cotes_bookmakers: Optional[Dict[str, float]] = None

    # Bloc C -- RK & chronos (TROT)
    rk_derniere_sec: Optional[float] = None
    rk_champ_median_sec: Optional[float] = None
    rk_array_3_derniers_sec: Optional[List[float]] = None  # [n-2, n-1, n]
    rk_incident_flag: Optional[List[bool]] = None
    chrono_200m: Optional[float] = None
    champ_median_chrono_200m: Optional[float] = None
    # Record (meilleure perf. chronométrée, PAS le RK de la dernière course) --
    # proxy dégradé du RK, ajouté le 04/08/2026 (source : Zone-Turf.fr,
    # colonne "Rec.", accord explicite pour sursoir au RK complet faute de
    # source vérifiée). Ne pas utiliser comme substitut exact de rk_derniere_sec
    # dans les modules qui en dépendent (RAH-29) sans relire leur définition.
    record_chrono_sec: Optional[float] = None
    # Record sur l'hippodrome du jour précisément (distinct du record
    # absolu ci-dessus) -- source Frequence-Turf, table "Record parcours",
    # ajouté le 02/09/2026. Informatif pour l'instant (pas encore branché
    # dans une formule du catalogue -- candidat naturel pour affiner B19,
    # à faire dans une prochaine session).
    record_parcours_sec: Optional[float] = None

    # Bloc D -- carrière & gains
    gains_totaux_eur: Optional[float] = None
    nb_courses: Optional[int] = None
    niveau_max: Optional[float] = None
    niveau_max_hors_pattern_europeen: bool = False
    # Gain moyen par course déjà calculé par la source (Frequence-Turf,
    # table "Moyenne de gains") -- ajouté le 02/09/2026. Utilisé UNIQUEMENT
    # en repli par module_a_sri quand gains_totaux_eur/nb_courses sont
    # absents (sinon la formule dérive elle-même le ratio, plus précis
    # car spécifique à la discipline collectée).
    gains_moyenne_carriere_eur: Optional[float] = None

    # Bloc E -- musique & style
    musique: Optional[str] = None
    style_mpa: Optional[StyleMPA] = None
    p_avant: Optional[float] = None  # probabilité de prise de tête (continu)
    position_mi_course_hist: Optional[List[int]] = None  # 5 dernières

    # Bloc F -- dernière course, délai, commentaire
    delai_j: Optional[int] = None
    nb_courses_30j: Optional[int] = None
    commentaire_derniere_course: Optional[str] = None
    feu_equidia: Optional[str] = None  # VERT|ORANGE|ROUGE|ABSENT
    icp_pondere: Optional[float] = None

    # RAH-270 (ajouté v1.29.14) -- signal de rythme/allure qualitatif dérivé
    # de commentaire_derniere_course par la Couche IA optionnelle
    # (app/engine/ai_rhythm.py). Borné [-3, +3] par construction (clamp
    # défensif appliqué à la fois côté supervisor.py et pch_final.py).
    # None si l'IA est désactivée, indisponible, ou n'a rien produit --
    # dans ce cas rah270_ai_pch reste à 0.0, comportement 100% déterministe
    # inchangé.
    rah270_ai_signal: Optional[float] = None
    rah270_ai_rationale: Optional[str] = None

    # Bloc G -- allocations & équipement
    allocations_last3: Optional[List[Dict[str, float]]] = None  # [{montant, allocation_course}]
    allocation_course_actuelle: Optional[float] = None
    ferrure_changes: int = 0
    equip_changes: int = 0
    # Code œillères PMU (SANS_OEILLERES, AVEC_OEILLERES, PREMIERE_FOIS_OEILLERES…)
    oeilleres: Optional[str] = None
    # Code de ferrure précis (DA/DP/D4/PA/PP/P4/DA-PP/DP-PA) -- ajouté le
    # 04/08/2026, source Zone-Turf.fr uniquement (Turfoo/CanalTurf ne
    # donnent qu'un booléen ferrure_changes). D4 = "déferré des quatre
    # pieds", le signal recherché par D09bis. ferrure_changes reste un
    # booléen dérivé (1 si ferrure_type est renseigné) pour compatibilité
    # avec le code existant qui le lit déjà.
    ferrure_type: Optional[str] = None
    # Code déferrage PMU (D4/DP/DA/D0…) — distinct de ferrure_type si besoin
    deferre: Optional[str] = None
    all_score: Optional[float] = None

    # Bloc H -- stats driver/jockey, entraîneur, tandem
    driver_stats: Optional[DriverStats] = None
    trainer_stats: Optional[TrainerStats] = None
    tandem_driver_cheval: Optional[TandemStats] = None
    tandem_driver_ecurie: Optional[TandemStats] = None
    driver_est_entraineur: bool = False

    # Bloc I -- poids (PLAT HANDICAP)
    poids_actuel_kg: Optional[float] = None
    poids_precedent_kg: Optional[float] = None
    valeur_pmu_precedente: Optional[float] = None

    # Bloc J -- recul (TROT HANDICAP)
    recul_m: Optional[float] = None
    historique_recul: Optional[List[PerfHistorique]] = None

    # Bloc K -- pronostics presse & ICP
    icp_global: Optional[int] = None  # nb sources total
    citations_top5_par_source: Optional[Dict[str, bool]] = None
    favori_unanime: bool = False

    # Bloc L -- risque DQ, incidents
    dq_12m: int = 0
    nb_courses_12m: Optional[int] = None
    dq_5_dernieres_tentees: int = 0
    incidents_30j: int = 0
    pattern_incidents: Optional[str] = None  # STABLE|VARIABLE|CHANGEANTE|SERIES

    # Bloc M -- historiques distance/terrain
    historique_terrain: Optional[List[PerfHistorique]] = None  # valeur=pénétromètre
    historique_distance: Optional[List[PerfHistorique]] = None  # valeur=distance m
    distance_habituelle_m: Optional[float] = None
    # Courses passées sur L'HIPPODROME EXACT du jour (valeur=distance_m de
    # cette course-là, informatif) -- ajouté le 02/09/2026. La donnée
    # brute (FicheChevalHistorique.hippodrome) était déjà scrapée par
    # turfoo_fiche_cheval.py mais jetée à l'étape enrichment.py (seuls
    # pénétromètre/distance étaient conservés) : débloque SSFO f11 et
    # Ghost D07/D26, qui restaient non-évaluables faute de cette
    # distinction (historique_terrain est indexé pénétromètre, pas
    # hippodrome -- deux courses au même pénétromètre peuvent être sur
    # des hippodromes différents).
    historique_hippodrome: Optional[List[PerfHistorique]] = None
    # Toutes les "dernières performances" affichées par CanalTurf
    # (date+rang, non filtrées par hippodrome) -- ajouté le 04/09/2026
    # pour CSF SF-03 (fenêtre datée multi-courses), qui ne demande QUE
    # date+rang, contrairement à historique_hippodrome/historique_distance
    # qui ont besoin d'un contexte (hippodrome/distance) en plus.
    historique_recent: Optional[List[PerfHistorique]] = None
    # Compteurs carrière bruts (Turfoo, ligne "Courses/Victoires/Places")
    # -- scrapés mais jamais exploités jusqu'au 02/09/2026. "Places" =
    # convention française "placé" (2e/3e), donc (victoires+places)/
    # courses ≈ taux Top3, PAS taux Top5 -- ne pas l'utiliser pour SF-05
    # (Top5), seulement SF-06 (Top3).
    victoires_carriere: Optional[int] = None
    places_carriere: Optional[int] = None
    # PENTE_SCORE brut (B47bis) et IRP_ajusté_final (B47) -- exposés en
    # valeurs numériques propres depuis historique_signals.py à partir du
    # 02/09/2026 (auparavant seulement lisibles en texte libre dans la
    # justification du CatalogSignal correspondant). Utilisés par
    # p5p6.py::_c3_trajectoire et ssfo.py::f2/f31, qui en dépendaient sans
    # y avoir accès -- cf. PASSATION pour le détail de cette lacune.
    pente_score: Optional[float] = None
    irp_score: Optional[float] = None

    # Bloc N -- H2H
    confrontations_directes: Optional[List[Dict[str, Any]]] = None

    # tactique autostart (TROT)
    numero_autostart: Optional[int] = None
    position_ligne: Optional[str] = None  # 1ere_ligne|2eme_ligne|ext_simple|ext_2nd
    attelage_position: Optional[int] = None
    chrono_1km: Optional[float] = None
    ratio_final: Optional[float] = None
    hist_montee_avg: Optional[float] = None
    changement_driver: bool = False
    changement_entraineur: bool = False
    changement_attelage: bool = False

    # poids handicap plat
    poids_moyen_champ_kg: Optional[float] = None
    poids_min_champ_kg: Optional[float] = None
    poids_max_champ_kg: Optional[float] = None

    # notes libres / sources
    sources_manquantes: List[str] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    fiche_url: Optional[str] = None  # lien vers la fiche individuelle (enrichissement optionnel)
    driver_fiche_url: Optional[str] = None
    entraineur_fiche_url: Optional[str] = None
    signaux_precalcules: List[Any] = Field(default_factory=list)  # CatalogSignal calculés à l'enrichissement


class CatalogSignal(BaseModel):
    """Un signal issu des catalogues B01-B56/M01-M43/GRU/SSFO/GAMMA (Couche LLM)."""
    id: str
    valeur_brute: float
    catalog: str  # "B" (bonus) ou "M" (malus)
    famille: Optional[str] = None  # C|L|F|M|P -- si omis, dérivé de la table interne
    is_gamma: bool = False
    justification: Optional[str] = None
    confiance: Optional[str] = None  # STRICT|DEGRADE|MINIMAL


class CSFSignal(BaseModel):
    id: str  # SF-01 .. SF-24
    valeur: float
    famille: Optional[str] = None


class QualitativeSignals(BaseModel):
    """Sortie de la Couche LLM (app/llm/qualitative.py) -- Bloc 5 items 17-32,
    Bloc 7 CSF/tocard, Bloc 7bis SUPRA, Partie 17.4 Longshot Hunter."""
    signaux_catalogue: List[CatalogSignal] = Field(default_factory=list)

    forme_lineaire_pch: float = 0.0
    d46_d22_pch: float = 0.0
    d02_b59_pch: float = 0.0
    m48_b42_pch: float = 0.0
    m04_pch: float = 0.0
    d45_pch: float = 0.0
    rah186_pch: float = 0.0
    m33_pch: float = 0.0
    rah200_pch: float = 0.0
    discipline_specifique_pch: float = 0.0

    csf_signaux: List[CSFSignal] = Field(default_factory=list)

    tocard_somme_d: float = 0.0
    tocard_pdq: float = 0.0
    tocard_sdr: float = 0.0
    tocard_overbet_souscote: bool = False

    supra_verdict: Optional[str] = None
    supra_score_sim: Optional[float] = None       # SUPRA Phase 2, pour GMO-V T3/T4
    supra_omission_candidate: bool = False
    supra_phases: Dict[str, Any] = Field(default_factory=dict)

    ls_final_par_famille: Dict[str, float] = Field(default_factory=dict)  # Longshot Hunter
    bonus_ssfo: float = 0.0  # RAH-271, cap géré par l'appelant
    # Biais de corde empirique (open-pmu-api) -- PAS un signal du texte
    # source, ajout proposé le 06/09/2026 (cf. pmu_corpus_analyse.py).
    # Séparé des bonus catalogue B/M/GAMMA pour ne jamais se faire passer
    # pour un signal du protocole d'origine.
    bonus_corde_empirique: float = 0.0
    # Probabilité de marché après retrait de la marge bookmaker
    # (overround) -- ajouté le 06/09/2026, cf. probabilites_marche.py.
    # PAS un signal catalogue non plus : information exposée pour
    # analyse (calibration, détection de valeur), ne modifie aucun
    # calcul PCH/tocard existant.
    probabilite_marche_vraie: Optional[float] = None
    overround_marche: Optional[float] = None

    flags: List[str] = Field(default_factory=list)
    justifications: Dict[str, str] = Field(default_factory=dict)


class ModuleBreakdown(BaseModel):
    """Décomposition PCH d'un cheval -- un champ par module / poste (33 items Bloc 5)."""
    sri_v2: float = 0.0
    iff_v2: float = 0.0
    nrc: float = 0.0
    bsh_v3v4: float = 0.0
    bsc_v3: float = 0.0
    stab_pch: float = 0.0
    tact_score: float = 0.0
    tact_pch: float = 0.0  # injection PCH bornée (A1), incluse dans la somme et traitée comme secondaire par RAH-242
    module_poids: float = 0.0
    module_recul: float = 0.0
    module_terrain_dyn: float = 0.0
    module_dist_adapt: float = 0.0
    mpa_champ: float = 0.0
    cre_total: float = 0.0
    h2h_norm: float = 0.0            # informatif -- utilisé dans COMPOSITE, pas PCH
    overbet_pch_delta: float = 0.0   # appliqué en 2e passe (anti-circularité)
    # Écart brut (cote_théorique - cote)/cote_théorique -- exposé depuis
    # le 02/09/2026 pour Ghost D40, qui a besoin du seuil FIXE -0.15,
    # distinct du seuil dynamique (0.10/0.15 selon allocation) utilisé en
    # interne par module_o_overbet pour poser OVERBET_SOUSCOTE.
    overbet_ecart: Optional[float] = None
    tandem_final: float = 0.0

    # Items 17-32 (patch v1.20-v1.22, catalogues qualitatifs) -- alimentés par
    # la Couche LLM (qualitative.py), validés/clampés côté Python.
    forme_lineaire_pch: float = 0.0
    d46_d22_pch: float = 0.0
    d02_b59_pch: float = 0.0
    m48_b42_pch: float = 0.0
    m04_pch: float = 0.0
    m30_pch: float = 0.0
    b47_pch: float = 0.0
    b04_pch: float = 0.0
    d45_pch: float = 0.0
    rah186_pch: float = 0.0
    m33_pch: float = 0.0
    b11_pch: float = 0.0
    rah200_pch: float = 0.0
    bonus_b_sum_brut: float = 0.0     # avant décote famille + tranche
    malus_m_sum_brut: float = 0.0
    bonus_b_sum_module: float = 0.0   # après décote famille + BONUS_TRANCHE_MULT
    malus_m_sum_module: float = 0.0
    discipline_specifique_pch: float = 0.0
    gru_pepite_piege_pch: float = 0.0
    gamma_pch: float = 0.0            # cap +8
    gru_dist2_pch: float = 0.0        # interaction sexe x distance fond (TROT >2400m)
    corde_empirique_pch: float = 0.0  # hors texte source, cf. pmu_corpus_analyse.py
    rah163_ferrure_reduction: float = 0.0  # 2e passe anti-double-comptage ferrure x SOV_v2
    rah242_secondary_correction: float = 0.0  # <=0, plafond bonus secondaires <= bonus primaires positifs
    rah242_primary_positive: float = 0.0  # somme primaire positive avant plafond
    rah242_secondary_raw: float = 0.0  # somme secondaire positive avant plafond (GRU/tactique inclus)
    rah242_secondary_allowed: float = 0.0  # montant secondaire autorisé après plafond

    # RAH-270 IA (v1.29.14) -- copie clampée [-3,+3] de cheval.rah270_ai_signal,
    # ajoutée aux postes 17-32 ET soumise au plafond RAH-242 (double borne :
    # cap individuel ±3 + cap collectif par les bonus primaires). 0.0 si
    # l'IA est désactivée/indisponible -- jamais un cheval sans IA n'est
    # pénalisé par rapport au comportement pré-v1.29.14.
    rah270_ai_pch: float = 0.0

    bonus_csf: float = 0.0
    csf_norm: float = 0.0
    tocard_score: float = 0.0
    # Value T2 (semi-favoris 9–15) — hors tocard (réservé T3/T4)
    t2_value_score: float = 0.0
    p5p6_score: float = 0.0  # Étape 11.11bis (Partie 17.10, redéfini) -- ajouté le 08/08/2026
    p5p6_detail: Dict[str, float] = Field(default_factory=dict)  # {c1..c5}
    supra_pch_delta: float = 0.0  # Phases 1/3/4/5, verrou de convergence -- ajouté le 09/08/2026

    pch_final: float = 0.0
    pch_norm: float = 0.0

    signaux_actifs: List[Dict[str, Any]] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)


class SynthesisResult(BaseModel):
    composite: float = 0.0
    sov_v2: float = 0.0
    iql_v2: float = 0.0
    harville_mult: float = 1.0
    tact_mult: float = 1.0
    stab_mult: float = 1.0
    all_mult: float = 1.0
    produit_mult_brut: float = 1.0
    produit_mult_corrige: float = 1.0
    ordre_base: float = 0.0
    ordre_final: float = 0.0
    ift: float = 100.0
    ift_label: str = "EXCELLENT"
    tranche: Optional[Tranche] = None
    flags: List[str] = Field(default_factory=list)


class HorseScore(BaseModel):
    cheval: Cheval
    breakdown: ModuleBreakdown
    synthesis: SynthesisResult


class TicketSlot(BaseModel):
    position: str  # P1..P6, R1, R2
    numero: int
    nom: str
    ordre_final: float
    cote: Optional[float] = None
    macro_groupe: Optional[str] = None
    categorie: Optional[str] = None  # Favori/Outsider/Tocard
    justification_rah: List[str] = Field(default_factory=list)
    role: Optional[str] = None  # PIVOT/SEMI/VALUE/SAUVAGE (v1.29.21)


class RaceResult(BaseModel):
    race_id: str
    context: RaceContext
    horses: List[HorseScore] = Field(default_factory=list)
    pool_elargi: List[int] = Field(default_factory=list)
    ticket: List[TicketSlot] = Field(default_factory=list)
    ticket_quotas: List[TicketSlot] = Field(default_factory=list)   # v1.29.42 : ticket B (quotas par tranche)
    quotas_info: Optional[Dict[str, Any]] = None
    ticket_ancre: List[TicketSlot] = Field(default_factory=list)   # v1.29.55 : ticket C (ancré marché : mélange marché + PCH)
    ancre_info: Optional[Dict[str, Any]] = None
    structures_tickets: Optional[Dict[str, Any]] = None   # v1.29.58 : {"A"|"B"|"C": 3 bases + 5 compléments classés, probabilités désordre/bonus/ordre}
    p_top5_in_ticket: Optional[float] = None
    masse_residuelle: Optional[float] = None
    constraints_report: List[Dict[str, Any]] = Field(default_factory=list)
    validation_status: str = "EN_COURS"
    json_output: Optional[Dict[str, Any]] = None


class StageStatus(str, Enum):
    EN_COURS = "EN_COURS"
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class StageTrace(BaseModel):
    """Une étape du pipeline (ex. 'Collecte', 'Analyse qualitative'...).
    But : localiser précisément OÙ un bug se produit, sans attendre le
    résultat de la course (contrairement au rapport d'audit walk-forward,
    qui compare le ticket aux résultats officiels après coup)."""
    nom: str
    status: StageStatus = StageStatus.OK
    optionnelle: bool = False   # une étape optionnelle en échec ne bloque pas le pipeline
    debut: Optional[str] = None
    fin: Optional[str] = None
    duree_sec: Optional[float] = None
    message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ExecutionReport(BaseModel):
    """Rapport d'EXÉCUTION -- trace technique du déroulé du pipeline
    (quelle étape a tourné, combien de temps, avec quels avertissements ou
    erreurs). Répond à "la stratégie a-t-elle été exécutée correctement de
    bout en bout ?" et "où ça a cassé ?".

    DISTINCT du rapport d'AUDIT (app/engine/post_race_audit.py), qui lui
    compare le ticket généré en walk-forward aux résultats officiels réels
    une fois la course courue, et analyse les causes d'échec de la
    stratégie elle-même (pas du code) pour ajuster le protocole plus tard.
    """
    race_id: str
    version_moteur: str = "v1.28.2"
    mode: str = "100% Python -- sans API Anthropic"
    demarre_le: str
    termine_le: Optional[str] = None
    statut_global: str = "EN_COURS"  # EN_COURS | TERMINE | TERMINE_AVEC_AVERTISSEMENTS | ECHEC
    etapes: List[StageTrace] = Field(default_factory=list)
    etape_courante: Optional[str] = None  # nom de l'étape en cours (UI live)
    sources_liens: Dict[str, Any] = Field(default_factory=dict)  # URLs exactes collecte + enrichissement
    regle_20_respectee: Optional[bool] = None
    regle_20_note: Optional[str] = None
    erreur_fatale: Optional[str] = None
    traceback_complet: Optional[str] = None
