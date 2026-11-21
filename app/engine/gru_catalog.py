"""
GRU Catalog — Discipline × Hippodrome × Distance
================================================
Catalogue reconstruit hippodrome par hippodrome (Quinté+ 2023-2026).
11 hippodromes majeurs formalisés pour production / walk-forward.

Chaque entrée fournit :
  - stats_corpus (favori G/P)
  - distance_bins
  - gru_keys
  - numero_bias (conditionnel)
  - flags_dominants
  - ticket_policy (densifier | elargir | mixte)

Ne jamais inventer de données absentes : si hippodrome inconnu → GRU_INCONNU.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

GRU_CATALOG: Dict[str, Dict[str, Any]] = {

    # 1. VINCENNES
    "vincennes": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "medium", "cote_sweet_spot": [12, 26], "cote_max_utile": 115, "extreme_longshot_ok": True, "extreme_range": [35, 115], "notes": "hippo_open=moyen (ordre_moy~57591€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "serre", "ordre_moyen_proxy": 57591, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Grande piste; AS coeur 1ere ligne; median desordre bas (~105€)"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "aliases": ["vincennes", "paris-vincennes", "paris vincennes"],
        "corde": "gauche",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3541, "favori_taux_place": 0.5991, "nb_favoris_corpus": 2372, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "sprint": {"min": 0, "max": 2100, "regime": "vitesse"},
            "standard": {"min": 2101, "max": 2700, "regime": "equilibre"},
            "long": {"min": 2701, "max": 9999, "regime": "tenue"},
        },
        "gru_keys": [
            {"key": "VIN_ATT_SPRINT_GP_AS", "distance_bin": "sprint", "depart": "autostart", "priority": "very_high"},
            {"key": "VIN_ATT_STANDARD", "distance_bin": "standard", "priority": "high"},
            {"key": "VIN_ATT_LONG_GP", "distance_bin": "long", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 3},
                "interieur": {"numeros": [1], "effet": "malus", "poids": 2},
                "exterieur_1ere": {"numeros": [7, 8], "effet": "neutre", "poids": 0},
                "2e_ligne": {"numeros": list(range(9, 19)), "effet": "malus", "poids": 3},
            },
            "plafond_total_numero": 5,
        },
        "flags_dominants": ["specialiste_vincennes", "tenue_gp", "specialiste_distance", "deferre_d4"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "bas_trot"},
    },

    # 2. AUTEUIL
    "auteuil": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=tres_ouvert (ordre_moy~143803€); disc=tres_ouvert (haies,steeple); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "tres_ouvert", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 143803, "boost_extreme": 1.4, "by_discipline": {"haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": None, "notes": "Obstacle; qualite saut + tenue; terrain lourd change la donne"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "aliases": ["auteuil"],
        "corde": "gauche",
        "disciplines": ["haies", "steeple"],
        "stats_corpus": {"favori_taux_gagne": 0.3112, "favori_taux_place": 0.5597, "nb_favoris_corpus": 511, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "court": {"min": 0, "max": 3600, "regime": "vitesse_saut"},
            "moyen": {"min": 3601, "max": 4200, "regime": "equilibre"},
            "long": {"min": 4201, "max": 9999, "regime": "tenue_saut"},
        },
        "gru_keys": [
            {"key": "AUT_HAI_MOYEN", "discipline": "haies", "distance_bin": "moyen", "priority": "very_high"},
            {"key": "AUT_STP_LONG", "discipline": "steeple", "distance_bin": "long", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 0},
        "flags_dominants": ["specialiste_auteuil", "qualite_saut", "specialiste_distance"],
        "ticket_policy": {"conseil": "mixte", "profil_rapport": "eleve_obstacle", "median_rapport_desordre_haies": 295},
    },

    # 3. ENGHIEN
    "enghien": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "low", "cote_sweet_spot": [10, 22], "cote_max_utile": 110, "extreme_longshot_ok": True, "extreme_range": [35, 110], "notes": "hippo_open=serre (ordre_moy~34643€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "serre", "ordre_moyen_proxy": 34643, "boost_extreme": 0.3, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": False, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "AS critique; coeur 1ere ligne"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "serre", "favori_fiable": True},
        "aliases": ["enghien", "enghien-soisy", "enghien soisy", "soisy"],
        "corde": "gauche",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3407, "favori_taux_place": 0.5826, "nb_favoris_corpus": 587, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "vitesse": {"min": 0, "max": 2300, "regime": "vitesse"},
            "tenue": {"min": 2301, "max": 9999, "regime": "tenue"},
        },
        "gru_keys": [
            {"key": "ENG_ATT_VITESSE_AS", "distance_bin": "vitesse", "depart": "autostart", "priority": "very_high"},
            {"key": "ENG_ATT_TENUE", "distance_bin": "tenue", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 4},
                "interieur": {"numeros": [1], "effet": "malus", "poids": 3},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 4},
            },
            "plafond_total_numero": 6,
        },
        "flags_dominants": ["specialiste_enghien", "specialiste_distance", "deferre_d4"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "bas_trot"},
    },

    # 4. DEAUVILLE
    "deauville": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=tres_ouvert (ordre_moy~116953€); disc=ouvert (plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "tres_ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 116953, "boost_extreme": 1.4, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": None, "notes": "PSF vs gazon: ne pas mélanger les formes; favori moins fiable"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "aliases": ["deauville", "deauville-la-touques"],
        "corde": "droite",
        "disciplines": ["plat"],
        "stats_corpus": {"favori_taux_gagne": 0.2801, "favori_taux_place": 0.5553, "nb_favoris_corpus": 814, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "sprint": {"min": 0, "max": 1300, "regime": "vitesse"},
            "mile": {"min": 1301, "max": 1800, "regime": "vitesse_finish"},
            "inter": {"min": 1801, "max": 2400, "regime": "placement"},
            "stayer": {"min": 2401, "max": 9999, "regime": "fond"},
        },
        "gru_keys": [
            {"key": "DEA_PLAT_MILE_GAZ", "surface": "gazon", "distance_bin": "mile", "priority": "very_high"},
            {"key": "DEA_PLAT_PSF_MILE", "surface": "psf", "distance_bin": "mile", "priority": "very_high"},
            {"key": "DEA_PLAT_SPRINT", "distance_bin": "sprint", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 0},
        "flags_dominants": ["specialiste_deauville", "specialiste_surface", "specialiste_distance", "forme_psf"],
        "ticket_policy": {"conseil": "elargir", "profil_rapport": "eleve_plat"},
    },

    # 5. CAGNES-SUR-MER
    "cagnes": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~78651€); disc=ouvert (attele,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 78651, "boost_extreme": 1.0, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "PSF stable; AS trot; spécialistes surface valorisés"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": True},
        "aliases": ["cagnes", "cagnes-sur-mer", "cagnes sur mer", "cagnes-sur-mer"],
        "corde": "droite",
        "disciplines": ["attele", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3421, "favori_taux_place": 0.6093, "nb_favoris_corpus": 1070, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 0, "max": 9999, "regime": "tenue"},
            "plat_mile": {"min": 0, "max": 1800, "regime": "vitesse"},
            "plat_inter": {"min": 1801, "max": 9999, "regime": "placement"},
        },
        "gru_keys": [
            {"key": "CAG_ATT_TENUE", "discipline": "attele", "priority": "very_high"},
            {"key": "CAG_PLAT_PSF_MILE", "discipline": "plat", "surface": "psf", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 4,
        },
        "flags_dominants": ["specialiste_cagnes", "specialiste_surface", "specialiste_distance"],
        "ticket_policy": {"attele": "densifier", "plat": "elargir", "conseil": "densifier_leger"},
    },

    # 6. CHANTILLY
    "chantilly": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=tres_ouvert (ordre_moy~119431€); disc=ouvert (plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "tres_ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 119431, "boost_extreme": 1.4, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": None, "notes": "Montée finale 10m; terrain lourd amplifie; PSF hiver ≠ gazon"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "aliases": ["chantilly"],
        "corde": "droite",
        "disciplines": ["plat"],
        "stats_corpus": {"favori_taux_gagne": 0.2821, "favori_taux_place": 0.5668, "nb_favoris_corpus": 801, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "sprint": {"min": 0, "max": 1300, "regime": "vitesse"},
            "mile": {"min": 1400, "max": 1700, "regime": "vitesse_finish"},
            "intermediaire": {"min": 1800, "max": 2200, "regime": "placement_montee"},
            "stayer": {"min": 2400, "max": 9999, "regime": "fond_montee"},
        },
        "gru_keys": [
            {"key": "CHA_PLAT_MILE_GAZ", "surface": "gazon", "distance_bin": "mile", "priority": "very_high"},
            {"key": "CHA_PLAT_MILE_PSF", "surface": "psf", "distance_bin": "mile", "priority": "very_high"},
            {"key": "CHA_PLAT_JC", "piste": "jockey_club", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 1},
        "flags_dominants": ["specialiste_chantilly", "specialiste_surface", "specialiste_distance", "aptitude_montee", "forme_psf"],
        "ticket_policy": {"conseil": "elargir", "profil_rapport": "eleve_plat"},
    },

    # 7. VICHY
    "vichy": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~56345€); disc=ouvert (attele,plat,haies); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "ouvert", "ordre_moyen_proxy": 56345, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": None, "notes": "Trot densifier; avantage local modéré"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": True},
        "aliases": ["vichy", "vichy-bellerive", "bellerive"],
        "corde": "droite",
        "disciplines": ["attele", "plat", "haies"],
        "stats_corpus": {"favori_taux_gagne": 0.335, "favori_taux_place": 0.6227, "nb_favoris_corpus": 591, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_vitesse": {"min": 0, "max": 2400},
            "attele_tenue": {"min": 2700, "max": 3200},
            "attele_endurance": {"min": 3400, "max": 9999},
            "plat_sprint": {"min": 0, "max": 1400},
            "plat_inter": {"min": 2000, "max": 2400},
            "plat_stayer": {"min": 2600, "max": 9999},
        },
        "gru_keys": [
            {"key": "VIC_ATT_TENUE", "discipline": "attele", "distance_bin": "attele_tenue", "priority": "very_high"},
            {"key": "VIC_ATT_ENDURANCE", "discipline": "attele", "distance_bin": "attele_endurance", "priority": "high"},
            {"key": "VIC_PLAT_INTER", "discipline": "plat", "distance_bin": "plat_inter", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 3},
                "interieur": {"numeros": [1], "effet": "malus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 3},
            },
            "plafond_total_numero": 4,
        },
        "flags_dominants": ["specialiste_vichy", "specialiste_distance", "finisseur", "tenue_longue", "corde_droite"],
        "ticket_policy": {"attele": "densifier", "plat": "elargir_modere", "conseil": "densifier_leger"},
    },

    # 8. PARISLONGCHAMP
    "paris_longchamp": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=tres_ouvert (ordre_moy~996774€); disc=ouvert (plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "tres_ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 996774, "boost_extreme": 1.4, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": None, "notes": "Grandes distances; terrain critique; near-rail place+"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "aliases": ["longchamp", "parislongchamp", "paris-longchamp", "paris longchamp"],
        "corde": "droite",
        "disciplines": ["plat"],
        "stats_corpus": {"favori_taux_gagne": 0.32, "favori_taux_place": 0.64, "nb_favoris_corpus": 450, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "sprint": {"min": 0, "max": 1200},
            "mile_court": {"min": 1300, "max": 1500},
            "mile": {"min": 1600, "max": 1900},
            "inter": {"min": 2000, "max": 2400},
            "stayer": {"min": 2500, "max": 9999},
        },
        "gru_keys": [
            {"key": "LON_PLAT_NOUVELLE", "piste": "nouvelle", "distance_bin": "mile_court", "priority": "very_high"},
            {"key": "LON_PLAT_MILE", "distance_bin": "mile", "priority": "very_high"},
            {"key": "LON_PLAT_INTER", "distance_bin": "inter", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "distance_bin in [sprint, mile_court, mile]",
            "zones": {
                "pres_rail": {"numeros": [1, 2, 3, 4, 5], "effet": "bonus_place", "poids": 2},
                "exterieur": {"numeros": list(range(12, 19)), "effet": "malus_leger", "poids": 1},
            },
            "plafond_total_numero": 2,
        },
        "flags_dominants": ["specialiste_longchamp", "specialiste_nouvelle", "specialiste_distance", "pres_rail_ok"],
        "ticket_policy": {"conseil": "mixte", "profil_rapport": "eleve_plat"},
    },

    # 9. SAINT-CLOUD
    "saint_cloud": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=tres_ouvert (ordre_moy~107228€); disc=ouvert (plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "tres_ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 107228, "boost_extreme": 1.4, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": None, "notes": "Near-rail avantage place"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": True},
        "aliases": ["saint-cloud", "saint cloud", "val d'or", "val dor"],
        "corde": "gauche",
        "disciplines": ["plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3354, "favori_taux_place": 0.5938, "nb_favoris_corpus": 480, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "sprint": {"min": 0, "max": 1400},
            "mile": {"min": 1500, "max": 1900},
            "inter": {"min": 2000, "max": 2400},
            "stayer": {"min": 2500, "max": 9999},
        },
        "gru_keys": [
            {"key": "STC_PLAT_INTER", "distance_bin": "inter", "priority": "very_high"},
            {"key": "STC_PLAT_MILE", "distance_bin": "mile", "priority": "high"},
            {"key": "STC_PLAT_STAYER", "distance_bin": "stayer", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "distance_bin in [sprint, mile]",
            "zones": {
                "pres_rail": {"numeros": [1, 2, 3, 4], "effet": "bonus_leger", "poids": 1},
                "exterieur": {"numeros": list(range(13, 17)), "effet": "malus_leger", "poids": 1},
            },
            "plafond_total_numero": 2,
        },
        "flags_dominants": ["specialiste_saint_cloud", "gaucher", "specialiste_distance", "finisseur"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "moyen_plat"},
    },

    # 10. COMPIÈGNE
    "compiegne": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~93018€); disc=tres_ouvert (plat,haies,steeple,cross,attele); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 93018, "boost_extreme": 1.0, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}, "cross": {"openness": "tres_ouvert", "median_desordre_indic": 400}, "attele": {"openness": "serre", "median_desordre_indic": 95}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": None, "notes": "Obstacle + plat; élargir si terrain collant"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "aliases": ["compiegne", "compiègne", "putois"],
        "corde": "gauche",
        "disciplines": ["plat", "haies", "steeple", "cross", "attele"],
        "stats_corpus": {"favori_taux_gagne": 0.3002, "favori_taux_place": 0.6199, "nb_favoris_corpus": 463, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "plat_mile": {"min": 1400, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2400},
            "plat_stayer": {"min": 2600, "max": 9999},
            "haies_moyen": {"min": 3200, "max": 3600},
            "haies_long": {"min": 3800, "max": 9999},
        },
        "gru_keys": [
            {"key": "COM_PLAT_INTER", "discipline": "plat", "distance_bin": "plat_inter", "priority": "very_high"},
            {"key": "COM_PLAT_STAYER", "discipline": "plat", "distance_bin": "plat_stayer", "priority": "high"},
            {"key": "COM_HAI_MOYEN", "discipline": "haies", "distance_bin": "haies_moyen", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "plat and distance_bin in [plat_mile, plat_inter]",
            "zones": {
                "exterieur_leger": {"numeros": [8, 9, 10, 11, 12], "effet": "bonus_leger", "poids": 1},
                "pres_rail": {"numeros": [1, 2], "effet": "malus_leger", "poids": 1},
            },
            "plafond_total_numero": 2,
        },
        "flags_dominants": ["specialiste_compiegne", "gaucher", "specialiste_distance", "qualite_saut"],
        "ticket_policy": {"plat": "elargir", "obstacle": "elargir", "conseil": "mixte"},
    },

    # 11. LYON-PARILLY
    "lyon_parilly": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~77816€); disc=tres_ouvert (attele,plat,haies,steeple,cross); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 77816, "boost_extreme": 1.0, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}, "cross": {"openness": "tres_ouvert", "median_desordre_indic": 400}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "AS + spécialistes Parilly"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "serre", "favori_fiable": True},
        "aliases": ["lyon-parilly", "parilly", "lyon parilly", "bron", "lyonparilly"],
        "corde": "gauche",
        "disciplines": ["attele", "plat", "haies", "steeple", "cross"],
        "stats_corpus": {"favori_taux_gagne": 0.3362, "favori_taux_place": 0.6182, "nb_favoris_corpus": 461, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_vitesse": {"min": 0, "max": 2200},
            "attele_tenue": {"min": 2600, "max": 2900},
            "plat_mile": {"min": 1350, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2400},
            "plat_stayer": {"min": 2600, "max": 9999},
        },
        "gru_keys": [
            {"key": "LYP_ATT_TENUE", "discipline": "attele", "distance_bin": "attele_tenue", "priority": "very_high"},
            {"key": "LYP_ATT_VITESSE", "discipline": "attele", "distance_bin": "attele_vitesse", "priority": "high"},
            {"key": "LYP_PLAT_INTER", "discipline": "plat", "distance_bin": "plat_inter", "priority": "very_high"},
            {"key": "LYP_PLAT_MILE", "discipline": "plat", "distance_bin": "plat_mile", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True,
            "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 3},
                "interieur": {"numeros": [1], "effet": "malus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 3},
            },
            "plafond_total_numero": 4,
        },
        "flags_dominants": ["specialiste_parilly", "gaucher", "specialiste_distance", "finisseur"],
        "ticket_policy": {"attele": "densifier", "plat": "densifier", "conseil": "densifier_leger"},
    },

    # 12. TOULOUSE (La Cépière)
    "toulouse": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~43313€); disc=tres_ouvert (attele,monte,plat,haies,steeple); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 43313, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Pres-rail fort au plat (12.9% G); corde droite"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "aliases": ["toulouse", "la cepiére", "la-cepiere", "cépière", "cepiere"],
        "corde": "droite",
        "disciplines": ["attele", "monte", "plat", "haies", "steeple"],
        "stats_corpus": {"favori_taux_gagne": 0.3755, "favori_taux_place": 0.6388, "nb_favoris_corpus": 490, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_vitesse": {"min": 0, "max": 2400}, "attele_tenue": {"min": 2500, "max": 3000},
            "plat_sprint": {"min": 0, "max": 1400}, "plat_mile": {"min": 1500, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2400}, "plat_stayer": {"min": 2500, "max": 9999},
            "haies_moyen": {"min": 3200, "max": 3600}, "haies_long": {"min": 3800, "max": 9999},
        },
        "gru_keys": [
            {"key": "TOU_ATT_TENUE", "discipline": "attele", "distance_bin": "attele_tenue", "priority": "very_high"},
            {"key": "TOU_PLAT_INTER", "discipline": "plat", "distance_bin": "plat_inter", "priority": "very_high"},
            {"key": "TOU_HAI_MOYEN", "discipline": "haies", "distance_bin": "haies_moyen", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 3},
                "interieur": {"numeros": [1], "effet": "malus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 3},
            },
            "plafond_total_numero": 4,
        },
        "flags_dominants": ["specialiste_toulouse", "specialiste_distance", "corde_droite", "placement_precoce", "pres_rail_ok", "qualite_saut"],
        "ticket_policy": {"conseil": "densifier", "attele": "densifier", "plat": "densifier", "obstacle": "mixte", "profil_rapport": "bas_a_moyen"},
    },

    # 13. PAU (Pont-Long)
    "pau": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~70978€); disc=tres_ouvert (plat,haies,steeple,cross); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 70978, "boost_extreme": 1.0, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}, "cross": {"openness": "tres_ouvert", "median_desordre_indic": 400}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": False, "gaucher_droitier": "droitier", "notes": "Obstacle hiver + PSF; spécialistes terrain/saut"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "aliases": ["pau", "pont-long", "pont long", "hippodrome du pont-long"],
        "corde": "droite",
        "disciplines": ["plat", "haies", "steeple", "cross"],
        "stats_corpus": {"favori_taux_gagne": 0.2834, "favori_taux_place": 0.6089, "nb_favoris_corpus": 427, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "plat_sprint": {"min": 0, "max": 1400}, "plat_mile": {"min": 1500, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2400}, "plat_stayer": {"min": 2500, "max": 9999},
            "haies_moyen": {"min": 3500, "max": 3900}, "haies_long": {"min": 4000, "max": 9999},
            "steeple_long": {"min": 4300, "max": 5500}, "cross_long": {"min": 5600, "max": 9999},
        },
        "gru_keys": [
            {"key": "PAU_HAI_MOYEN", "discipline": "haies", "distance_bin": "haies_moyen", "priority": "very_high"},
            {"key": "PAU_STP_LONG", "discipline": "steeple", "distance_bin": "steeple_long", "priority": "very_high"},
            {"key": "PAU_PLAT_PSF_INTER", "discipline": "plat", "surface": "psf", "distance_bin": "plat_inter", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "plat and distance_bin in [plat_sprint, plat_mile, plat_inter]",
            "zones": {
                "pres_rail": {"numeros": [1, 2, 3, 4, 5], "effet": "bonus_place", "poids": 1},
                "exterieur": {"numeros": list(range(12, 17)), "effet": "malus_leger", "poids": 1},
            },
            "plafond_total_numero": 2,
        },
        "flags_dominants": ["specialiste_pau", "specialiste_psf", "qualite_saut", "tenue_longue", "meeting_hiver", "corde_droite"],
        "ticket_policy": {"conseil": "elargir", "plat": "mixte", "obstacle": "elargir", "profil_rapport": "moyen_a_eleve"},
    },

    # 14. PORNICHET-LA BAULE
    "pornichet": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~50000€); disc=ouvert (attele,monte,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "ouvert", "ordre_moyen_proxy": 50000, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": False, "gaucher_droitier": "gaucher", "notes": "PSF; près-rail place+"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "aliases": ["pornichet", "pornichet-la-baule", "pornichet la baule", "la baule"],
        "corde": "gauche",
        "disciplines": ["attele", "monte", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3183, "favori_taux_place": 0.5772, "nb_favoris_corpus": 421, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_vitesse": {"min": 0, "max": 2300}, "attele_tenue": {"min": 2400, "max": 2900},
            "plat_sprint": {"min": 0, "max": 1400}, "plat_mile": {"min": 1500, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2500}, "plat_stayer": {"min": 2600, "max": 9999},
        },
        "gru_keys": [
            {"key": "POR_ATT_TENUE", "discipline": "attele", "distance_bin": "attele_tenue", "priority": "very_high"},
            {"key": "POR_PLAT_PSF_INTER", "discipline": "plat", "surface": "psf", "distance_bin": "plat_inter", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "plat",
            "zones": {
                "pres_rail": {"numeros": [1, 2, 3, 4, 5], "effet": "bonus_place", "poids": 1},
                "exterieur": {"numeros": list(range(11, 17)), "effet": "malus_leger", "poids": 1},
            },
            "plafond_total_numero": 2,
        },
        "flags_dominants": ["specialiste_pornichet", "specialiste_psf", "specialiste_pouzzolane", "placement_precoce", "corde_gauche", "finisseur"],
        "ticket_policy": {"conseil": "mixte", "attele": "densifier_leger", "plat": "elargir_leger", "profil_rapport": "moyen"},
    },

    # 15. CABOURG
    "cabourg": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~79016€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "serre", "ordre_moyen_proxy": 79016, "boost_extreme": 1.0, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Difficile revenir arrière; nocturnes été; AS coeur"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "piste_meta": {"surface_trot": 'sable', "corde": 'droite', "tour_m_trot": 1275, "ligne_trot": 265, "notes": 'nocturnes; difficile revenir arrière'},
        "aliases": ["cabourg"],
        "corde": "droite",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3176, "favori_taux_place": 0.5782, "nb_favoris_corpus": 403, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_vitesse": {"min": 0, "max": 2200}, "attele_tenue": {"min": 2500, "max": 2900},
            "attele_as": {"min": 1600, "max": 2100},
        },
        "gru_keys": [
            {"key": "CAB_ATT_TENUE", "discipline": "attele", "distance_bin": "attele_tenue", "priority": "very_high"},
            {"key": "CAB_ATT_AS", "discipline": "attele", "depart": "autostart", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 3},
                "interieur": {"numeros": [1], "effet": "malus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 3},
            },
            "plafond_total_numero": 4,
        },
        "flags_dominants": ["specialiste_cabourg", "placement_precoce", "corde_droite", "nocturne", "finisseur"],
        "ticket_policy": {"conseil": "mixte", "attele": "densifier_leger", "profil_rapport": "moyen"},
    },

    # 16. MARSEILLE-BORÉLY
    "marseille_borely": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~90375€); disc=ouvert (attele,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 90375, "boost_extreme": 1.0, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": False, "gaucher_droitier": "gaucher", "notes": "Gazon + trot pouzzolane; près-rail"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "serre", "favori_fiable": True},
        "aliases": ["marseille-borely", "borély", "borely", "marseille borely", "marseille-borély"],
        "corde": "gauche",
        "disciplines": ["attele", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3317, "favori_taux_place": 0.6457, "nb_favoris_corpus": 398, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 2300, "max": 3100}, "plat_sprint": {"min": 0, "max": 1200},
            "plat_mile": {"min": 1500, "max": 1800}, "plat_inter": {"min": 2000, "max": 2600},
        },
        "gru_keys": [
            {"key": "BOR_ATT_TENUE", "discipline": "attele", "priority": "high"},
            {"key": "BOR_PLAT_GAZ", "discipline": "plat", "surface": "gazon", "priority": "very_high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "plat",
            "zones": {
                "pres_rail": {"numeros": [1, 2, 3, 4, 5], "effet": "bonus_place", "poids": 2},
                "exterieur": {"numeros": list(range(12, 17)), "effet": "malus_leger", "poids": 1},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_borely", "corde_gauche", "specialiste_distance", "pres_rail_ok"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "bas_a_moyen"},
    },

    # 17. MARSEILLE-VIVAUX
    "marseille_vivaux": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~70000€); disc=ouvert (attele,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 70000, "boost_extreme": 1.0, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": True, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": True, "autostart_critical": False, "gaucher_droitier": "gaucher", "notes": "Tourniquet; cheval de tête souvent; PSF/pouzzolane"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "aliases": ["marseille-vivaux", "vivaux", "pont-de-vivaux", "pont de vivaux", "marseille vivaux"],
        "corde": "gauche",
        "disciplines": ["attele", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3135, "favori_taux_place": 0.5777, "nb_favoris_corpus": 386, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 2100, "max": 3200}, "plat_sprint": {"min": 0, "max": 1300},
            "plat_mile": {"min": 1400, "max": 1600}, "plat_inter": {"min": 1800, "max": 2600},
        },
        "gru_keys": [
            {"key": "VIV_ATT_TENUE", "discipline": "attele", "priority": "high"},
            {"key": "VIV_PLAT_PSF", "discipline": "plat", "surface": "psf", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "plat",
            "zones": {
                "exterieur_leger": {"numeros": list(range(8, 14)), "effet": "bonus_leger", "poids": 1},
                "pres_rail": {"numeros": [1, 2], "effet": "malus_leger", "poids": 1},
            },
            "plafond_total_numero": 2,
        },
        "flags_dominants": ["specialiste_vivaux", "corde_gauche", "specialiste_psf", "tourniquet"],
        "ticket_policy": {"conseil": "mixte", "profil_rapport": "moyen"},
    },

    # 18. LYON-LA SOIE
    "lyon_la_soie": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~70088€); disc=ouvert (attele,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 70088, "boost_extreme": 1.0, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": False, "gaucher_droitier": "gaucher", "notes": "PSF; favori fiable"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "aliases": ["lyon-la-soie", "la soie", "carre de soie", "carré-de-soie", "lyon la soie"],
        "corde": "gauche",
        "disciplines": ["attele", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3508, "favori_taux_place": 0.6409, "nb_favoris_corpus": 362, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 2100, "max": 2900}, "plat_mile": {"min": 1400, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2500},
        },
        "gru_keys": [
            {"key": "LLS_ATT_TENUE", "discipline": "attele", "priority": "very_high"},
            {"key": "LLS_PLAT_PSF", "discipline": "plat", "surface": "psf", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 0},
        "flags_dominants": ["specialiste_la_soie", "corde_gauche", "specialiste_psf"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "bas_a_moyen"},
    },

    # 19. CAEN
    "caen": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~53721€); disc=ouvert (attele,monte,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "ouvert", "ordre_moyen_proxy": 53721, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Pôle national trot; AS soft"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": True},
        "aliases": ["caen"],
        "corde": "gauche",
        "disciplines": ["attele", "monte", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3363, "favori_taux_place": 0.5706, "nb_favoris_corpus": 333, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_vitesse": {"min": 0, "max": 2300}, "attele_tenue": {"min": 2500, "max": 2900},
            "plat_mile": {"min": 1400, "max": 1800}, "plat_inter": {"min": 2000, "max": 2500},
        },
        "gru_keys": [
            {"key": "CAE_ATT_TENUE", "discipline": "attele", "priority": "high"},
            {"key": "CAE_PLAT", "discipline": "plat", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_caen", "corde_gauche", "specialiste_distance"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "moyen"},
    },

    # 20. FONTAINEBLEAU
    "fontainebleau": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~64169€); disc=ouvert (plat,haies); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "ouvert", "ordre_moyen_proxy": 64169, "boost_extreme": 0.6, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": "droitier", "notes": "Plat + haies; corde droite"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "aliases": ["fontainebleau"],
        "corde": "droite",
        "disciplines": ["plat", "haies"],
        "stats_corpus": {"favori_taux_gagne": 0.3201, "favori_taux_place": 0.622, "nb_favoris_corpus": 328, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "plat_sprint": {"min": 0, "max": 1400}, "plat_mile": {"min": 1500, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2400}, "haies_moyen": {"min": 3200, "max": 4000},
        },
        "gru_keys": [
            {"key": "FON_PLAT_INTER", "discipline": "plat", "priority": "high"},
            {"key": "FON_HAI", "discipline": "haies", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 0},
        "flags_dominants": ["specialiste_fontainebleau", "corde_droite", "qualite_saut"],
        "ticket_policy": {"conseil": "mixte", "profil_rapport": "moyen"},
    },

    # 21. LAVAL
    "laval": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=serre (ordre_moy~13026€); disc=ouvert (attele,monte,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "ouvert", "ordre_moyen_proxy": 13026, "boost_extreme": 0.3, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Favori très fiable (37%); densifier"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "aliases": ["laval"],
        "corde": "gauche",
        "disciplines": ["attele", "monte", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3717, "favori_taux_place": 0.6414, "nb_favoris_corpus": 304, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 2100, "max": 2900}, "plat_mile": {"min": 1400, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2500},
        },
        "gru_keys": [
            {"key": "LAV_ATT_TENUE", "discipline": "attele", "priority": "very_high"},
            {"key": "LAV_PLAT", "discipline": "plat", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 3},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 4,
        },
        "flags_dominants": ["specialiste_laval", "corde_gauche", "specialiste_distance"],
        "ticket_policy": {"conseil": "densifier", "profil_rapport": "bas_a_moyen"},
    },

    # 22. CLAIREFONTAINE
    "clairefontaine": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~98932€); disc=tres_ouvert (plat,haies,steeple); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 98932, "boost_extreme": 1.0, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": "droitier", "notes": "Montée ligne opposée + descente; difficile revenir arrière; obstacle premium"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "piste_meta": {"surface_plat": 'gazon', "surface_obstacle": 'gazon', "corde": 'droite', "tour_m_plat": 2000, "notes": 'montée ligne opposée, descente finale; difficile revenir arrière'},
        "aliases": ["clairefontaine", "deauville-clairefontaine", "tourgeville"],
        "corde": "droite",
        "disciplines": ["plat", "haies", "steeple"],
        "stats_corpus": {"favori_taux_gagne": 0.2721, "favori_taux_place": 0.5748, "nb_favoris_corpus": 294, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "plat_sprint": {"min": 0, "max": 1400}, "plat_mile": {"min": 1500, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2500}, "haies_moyen": {"min": 3200, "max": 4000},
        },
        "gru_keys": [
            {"key": "CLA_PLAT", "discipline": "plat", "priority": "high"},
            {"key": "CLA_HAI", "discipline": "haies", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 0},
        "flags_dominants": ["specialiste_clairefontaine", "corde_droite", "qualite_saut"],
        "ticket_policy": {"conseil": "elargir", "obstacle": "elargir", "profil_rapport": "moyen"},
    },

    # 23. BORDEAUX-LE BOUSCAT
    "bordeaux": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=serre (ordre_moy~26928€); disc=ouvert (plat,attele,haies); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "ouvert", "ordre_moyen_proxy": 26928, "boost_extreme": 0.3, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}, "attele": {"openness": "serre", "median_desordre_indic": 95}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Montée + longue ligne; tenue + pointe vitesse"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "piste_meta": {"surface_trot": 'sable_rouge', "surface_plat": 'gazon', "corde": 'droite', "tour_m_trot": 1600, "tour_m_plat": 2000, "notes": 'montée + longue ligne; tenue + pointe vitesse'},
        "aliases": ["bordeaux", "le bouscat", "bordeaux-le bouscat", "bouscat", "bordeaux le bouscat"],
        "corde": "droite",
        "disciplines": ["plat", "attele", "haies"],
        "stats_corpus": {"favori_taux_gagne": 0.3199, "favori_taux_place": 0.6094, "nb_favoris_corpus": 297, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "plat_mile": {"min": 1400, "max": 1800}, "plat_inter": {"min": 2000, "max": 2500},
            "attele_tenue": {"min": 2100, "max": 2900},
        },
        "gru_keys": [
            {"key": "BDX_PLAT_INTER", "discipline": "plat", "priority": "high"},
            {"key": "BDX_ATT", "discipline": "attele", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "plat",
            "zones": {
                "pres_rail": {"numeros": [1, 2, 3, 4, 5], "effet": "bonus_place", "poids": 1},
            },
            "plafond_total_numero": 2,
        },
        "flags_dominants": ["specialiste_bordeaux", "corde_droite", "specialiste_distance"],
        "ticket_policy": {"conseil": "mixte", "profil_rapport": "moyen"},
    },

    # 24. NANTES
    "nantes": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~52037€); disc=ouvert (attele,monte,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "ouvert", "ordre_moyen_proxy": 52037, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Favori fiable 37%; lignes longues 350/400m"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "piste_meta": {"surface_trot": 'sable', "surface_plat": 'gazon', "corde": 'gauche', "tour_m_trot": 1411, "ligne_trot": 350, "tour_m_plat": 2068, "ligne_plat": 400},
        "aliases": ["nantes"],
        "corde": "gauche",
        "disciplines": ["attele", "monte", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3737, "favori_taux_place": 0.6263, "nb_favoris_corpus": 281, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 2100, "max": 2900}, "plat_mile": {"min": 1400, "max": 1800},
            "plat_inter": {"min": 2000, "max": 2500},
        },
        "gru_keys": [
            {"key": "NAN_ATT_TENUE", "discipline": "attele", "priority": "high"},
            {"key": "NAN_PLAT", "discipline": "plat", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_nantes", "corde_gauche", "specialiste_distance"],
        "ticket_policy": {"conseil": "densifier", "profil_rapport": "moyen"},
    },

    # 25. LE CROISÉ-LAROCHE
    "croise_laroche": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=ouvert (ordre_moy~75474€); disc=ouvert (attele,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "ouvert", "discipline_bias": "ouvert", "ordre_moyen_proxy": 75474, "boost_extreme": 1.0, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Grand anneau 1665m; rendre distance souvent gagnant; favori faible 24% → élargir"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "piste_meta": {"surface_trot": 'cendree', "surface_plat": 'gazon', "corde": 'gauche', "tour_m_trot": 1665, "ligne_trot": 380, "notes": 'grand anneau; rendre distance possible; finisseurs'},
        "aliases": ["croise-laroche", "le croisé-laroche", "croisé laroche", "marcq", "lille"],
        "corde": "gauche",
        "disciplines": ["attele", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.2397, "favori_taux_place": 0.5651, "nb_favoris_corpus": 292, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 2100, "max": 2900}, "plat_inter": {"min": 1800, "max": 2500},
        },
        "gru_keys": [
            {"key": "CLR_ATT", "discipline": "attele", "priority": "high"},
            {"key": "CLR_PLAT", "discipline": "plat", "priority": "high"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_croise_laroche", "corde_gauche"],
        "ticket_policy": {"conseil": "elargir", "profil_rapport": "moyen"},
    },

    # 26. AMIENS
    "amiens": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~61613€); disc=ouvert (attele,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "ouvert", "ordre_moyen_proxy": 61613, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Virage serré + ligne courte; droitiers; favori 27% place 50% → élargir fort"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "piste_meta": {"surface_trot": 'pouzzolane', "surface_plat": 'gazon', "corde": 'droite', "tour_m_trot": 1142, "ligne_trot": 310, "notes": 'dernier virage serré; droitiers; placement precoce'},
        "aliases": ["amiens", "petit saint-jean"],
        "corde": "droite",
        "disciplines": ["attele", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.2688, "favori_taux_place": 0.5, "nb_favoris_corpus": 186, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2100, "max": 2900}, "plat_inter": {"min": 1800, "max": 2500}},
        "gru_keys": [{"key": "AMI_ATT", "discipline": "attele", "priority": "high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_amiens", "corde_gauche"],
        "ticket_policy": {"conseil": "elargir", "profil_rapport": "moyen"},
    },

    # 27. ANGERS
    "angers": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=serre (ordre_moy~23940€); disc=ouvert (attele,monte,plat,haies); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "ouvert", "ordre_moyen_proxy": 23940, "boost_extreme": 0.3, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Longues lignes; sélectif; locaux valorisés"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "piste_meta": {"surface_trot": 'sable', "surface_plat": 'gazon', "corde": 'droite', "tour_m_trot": 1468, "tour_m_plat": 1801, "notes": 'longues lignes; sélectif'},
        "aliases": ["angers"],
        "corde": "droite",
        "disciplines": ["attele", "monte", "plat", "haies"],
        "stats_corpus": {"favori_taux_gagne": 0.3097, "favori_taux_place": 0.6062, "nb_favoris_corpus": 226, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "attele_tenue": {"min": 2100, "max": 2900}, "plat_inter": {"min": 1800, "max": 2500},
            "haies_moyen": {"min": 3200, "max": 4000},
        },
        "gru_keys": [
            {"key": "ANG_ATT", "discipline": "attele", "priority": "high"},
            {"key": "ANG_HAI", "discipline": "haies", "priority": "medium"},
        ],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_angers", "corde_gauche", "qualite_saut"],
        "ticket_policy": {"conseil": "mixte", "profil_rapport": "moyen"},
    },

    # 28. ARGENTAN
    "argentan": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "medium", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": False, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~45000€); disc=ouvert (attele,monte,plat); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "ouvert", "ordre_moyen_proxy": 45000, "boost_extreme": 0.35, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}, "plat": {"openness": "ouvert", "median_desordre_indic": 345}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Ligne 350m longue; tenue + finition"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": True},
        "piste_meta": {"surface_trot": 'sable', "surface_plat": 'gazon', "corde": 'droite', "tour_m_trot": 1325, "ligne_trot": 350, "notes": 'ligne longue; tenue + finition'},
        "aliases": ["argentan"],
        "corde": "droite",
        "disciplines": ["attele", "monte", "plat"],
        "stats_corpus": {"favori_taux_gagne": 0.3481, "favori_taux_place": 0.5746, "nb_favoris_corpus": 181, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2100, "max": 2900}, "plat_inter": {"min": 1800, "max": 2500}},
        "gru_keys": [{"key": "ARG_ATT", "discipline": "attele", "priority": "high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_argentan", "corde_gauche"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "moyen"},
    },

    # 29. LA CAPELLE
    "la_capelle": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "medium", "cote_sweet_spot": [12, 26], "cote_max_utile": 115, "extreme_longshot_ok": True, "extreme_range": [35, 115], "notes": "hippo_open=moyen (ordre_moy~55583€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "serre", "ordre_moyen_proxy": 55583, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Anneau 1609m courbes 10%; difficile refaire terrain en fin; AS"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": False},
        "piste_meta": {"surface_trot": 'pouzzolane', "corde": 'gauche', "tour_m_trot": 1609, "ligne_trot": 400, "notes": 'anneau vitesse unique EU; courbes 10%; placement precoce'},
        "aliases": ["la capelle", "la-capelle", "capelle", "thiérache"],
        "corde": "gauche",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3182, "favori_taux_place": 0.5859, "nb_favoris_corpus": 198, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2100, "max": 2900}},
        "gru_keys": [{"key": "CAP_ATT_TENUE", "discipline": "attele", "priority": "very_high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 3},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 4,
        },
        "flags_dominants": ["specialiste_la_capelle", "corde_gauche", "placement_precoce"],
        "ticket_policy": {"conseil": "mixte", "profil_rapport": "moyen"},
    },

    # 30. FEURS
    "feurs": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "low", "cote_sweet_spot": [10, 22], "cote_max_utile": 110, "extreme_longshot_ok": True, "extreme_range": [35, 110], "notes": "hippo_open=serre (ordre_moy~3793€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "serre", "ordre_moyen_proxy": 3793, "boost_extreme": 0.3, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Piste régulière; favori 37%; densifier"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "piste_meta": {"surface_trot": 'sable', "corde": 'gauche', "tour_m_trot": 1300, "notes": 'piste régulière qualité; 18 partants max'},
        "aliases": ["feurs"],
        "corde": "gauche",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3673, "favori_taux_place": 0.6429, "nb_favoris_corpus": 98, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2500, "max": 3000}},
        "gru_keys": [{"key": "FEU_ATT_TENUE", "discipline": "attele", "priority": "high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_feurs", "corde_gauche"],
        "ticket_policy": {"conseil": "densifier", "profil_rapport": "moyen"},
    },

    # 31. DIEPPE
    "dieppe": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=serre (ordre_moy~37215€); disc=tres_ouvert (plat,haies,steeple); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 37215, "boost_extreme": 0.3, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": False, "autostart_critical": False, "gaucher_droitier": "gaucher", "notes": "Ligne 500m; cross très sélectif; terrain critique"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "piste_meta": {"surface_plat": 'gazon', "corde": 'gauche', "tour_m_plat": 2000, "ligne_plat": 500, "notes": 'ligne 500m; sélectif; cross difficile'},
        "aliases": ["dieppe"],
        "corde": "gauche",
        "disciplines": ["plat", "haies", "steeple"],
        "stats_corpus": {"favori_taux_gagne": 0.305, "favori_taux_place": 0.6448, "nb_favoris_corpus": 259, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "plat_mile": {"min": 1400, "max": 1800}, "plat_inter": {"min": 2000, "max": 2500},
            "haies_moyen": {"min": 3200, "max": 4000},
        },
        "gru_keys": [
            {"key": "DIE_PLAT", "discipline": "plat", "priority": "high"},
            {"key": "DIE_HAI", "discipline": "haies", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 0},
        "flags_dominants": ["specialiste_dieppe", "corde_gauche", "qualite_saut"],
        "ticket_policy": {"conseil": "mixte", "obstacle": "elargir", "profil_rapport": "moyen"},
    },

    # 32. BEAUMONT-DE-LOMAGNE
    "beaumont_lomagne": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "low", "cote_sweet_spot": [10, 22], "cote_max_utile": 110, "extreme_longshot_ok": True, "extreme_range": [35, 110], "notes": "hippo_open=serre (ordre_moy~15798€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "serre", "ordre_moyen_proxy": 15798, "boost_extreme": 0.3, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Peu sélectif; rarement de l'arrière; pilotes régionaux prioritaires"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "piste_meta": {"surface_trot": 'sable', "corde": 'droite', "tour_m_trot": 1114, "ligne_trot": 400, "notes": 'peu sélectif; placement precoce; pilotes locaux'},
        "aliases": ["beaumont-de-lomagne", "beaumont de lomagne", "lomagne"],
        "corde": "droite",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3706, "favori_taux_place": 0.6364, "nb_favoris_corpus": 143, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2100, "max": 2900}},
        "gru_keys": [{"key": "BDL_ATT", "discipline": "attele", "priority": "high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_beaumont", "corde_gauche"],
        "ticket_policy": {"conseil": "densifier", "profil_rapport": "moyen"},
    },

    # 33. MESLAY-DU-MAINE
    "meslay": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "medium", "cote_sweet_spot": [12, 26], "cote_max_utile": 115, "extreme_longshot_ok": True, "extreme_range": [35, 115], "notes": "hippo_open=moyen (ordre_moy~40000€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "serre", "ordre_moyen_proxy": 40000, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Rendre distance possible; ligne 400m; finisseurs"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "piste_meta": {"surface_trot": 'machefer', "corde": 'droite', "tour_m_trot": 1614, "ligne_trot": 400, "notes": 'rendre distance possible; finisseurs'},
        "aliases": ["meslay", "meslay-du-maine", "meslay du maine"],
        "corde": "droite",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3772, "favori_taux_place": 0.6842, "nb_favoris_corpus": 114, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2100, "max": 2900}},
        "gru_keys": [{"key": "MES_ATT", "discipline": "attele", "priority": "high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_meslay", "corde_gauche"],
        "ticket_policy": {"conseil": "densifier", "profil_rapport": "moyen"},
    },

    # 34. GRAIGNES
    "graignes": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "low", "cote_sweet_spot": [10, 22], "cote_max_utile": 110, "extreme_longshot_ok": True, "extreme_range": [35, 110], "notes": "hippo_open=serre (ordre_moy~35000€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "serre", "discipline_bias": "serre", "ordre_moyen_proxy": 35000, "boost_extreme": 0.3, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "placement_precoce", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": False, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher", "notes": "Petit anneau 1034m; favori 38.6% très fiable"},
        "rapport_profile": {"median_desordre": "bas", "ticket_width_bias": "serre", "favori_fiable": True},
        "piste_meta": {"surface_trot": 'sable', "corde": 'gauche', "tour_m_trot": 1034, "ligne_trot": 250, "notes": 'petit Vincennes normand'},
        "aliases": ["graignes"],
        "corde": "gauche",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3858, "favori_taux_place": 0.6345, "nb_favoris_corpus": 197, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2100, "max": 2900}},
        "gru_keys": [{"key": "GRA_ATT", "discipline": "attele", "priority": "high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_graignes", "corde_gauche"],
        "ticket_policy": {"conseil": "densifier", "profil_rapport": "moyen"},
    },

    # 35. HYÈRES
    "hyeres": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "medium", "cote_sweet_spot": [12, 26], "cote_max_utile": 115, "extreme_longshot_ok": True, "extreme_range": [35, 115], "notes": "hippo_open=moyen (ordre_moy~45000€); disc=serre (attele,monte); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "serre", "ordre_moyen_proxy": 45000, "boost_extreme": 0.6, "by_discipline": {"attele": {"openness": "serre", "median_desordre_indic": 95}, "monte": {"openness": "serre", "median_desordre_indic": 100}}},
        "selection_levers": {"style_dominant": "mixte", "surface_key": False, "terrain_sensible": False, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier", "notes": "Pouzzolane; AS possible; ligne 400m"},
        "rapport_profile": {"median_desordre": "moyen", "ticket_width_bias": "normal", "favori_fiable": True},
        "piste_meta": {"surface_trot": 'pouzzolane', "surface_plat": 'gazon', "corde": 'droite', "tour_m_trot": 1200, "ligne_trot": 400, "notes": 'AS possible'},
        "aliases": ["hyeres", "hyères"],
        "corde": "droite",
        "disciplines": ["attele", "monte"],
        "stats_corpus": {"favori_taux_gagne": 0.3333, "favori_taux_place": 0.6111, "nb_favoris_corpus": 144, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {"attele_tenue": {"min": 2500, "max": 3100}},
        "gru_keys": [{"key": "HYE_ATT", "discipline": "attele", "priority": "high"}],
        "numero_bias": {
            "applicable": True, "condition": "attele and autostart",
            "zones": {
                "coeur_1ere_ligne": {"numeros": [3, 4, 5, 6], "effet": "bonus", "poids": 2},
                "2e_ligne": {"numeros": list(range(9, 17)), "effet": "malus", "poids": 2},
            },
            "plafond_total_numero": 3,
        },
        "flags_dominants": ["specialiste_hyeres", "corde_gauche"],
        "ticket_policy": {"conseil": "densifier_leger", "profil_rapport": "moyen"},
    },

    # 36. LE LION-D'ANGERS
    "lion_angers": {
        "outsider_profile": {"longshot_viable": True, "outsider_weight": "high", "cote_sweet_spot": [12, 32], "cote_max_utile": 130, "extreme_longshot_ok": True, "extreme_range": [35, 130], "notes": "hippo_open=moyen (ordre_moy~50000€); disc=tres_ouvert (plat,haies,steeple,cross); 30+ top5 ~12-14% (iturf); Vincennes 4e max 108 / 5e max 68 documenté", "hippo_openness": "moyen", "discipline_bias": "tres_ouvert", "ordre_moyen_proxy": 50000, "boost_extreme": 0.6, "by_discipline": {"plat": {"openness": "ouvert", "median_desordre_indic": 345}, "haies": {"openness": "ouvert", "median_desordre_indic": 295}, "steeple": {"openness": "tres_ouvert", "median_desordre_indic": 397}, "cross": {"openness": "tres_ouvert", "median_desordre_indic": 400}}},
        "selection_levers": {"style_dominant": "finisseur", "surface_key": True, "terrain_sensible": True, "rendre_distance_ok": True, "avantage_local": True, "autostart_critical": False, "gaucher_droitier": None, "notes": "Obstacle premium Anjou-Loire; qualité saut + tenue"},
        "rapport_profile": {"median_desordre": "eleve", "ticket_width_bias": "large", "favori_fiable": False},
        "piste_meta": {"surface_plat": 'gazon', "corde": 'gauche', "notes": 'obstacle premium; Anjou-Loire Challenge'},
        "aliases": ["lion-d'angers", "le lion-d'angers", "lion d angers", "le lion d angers"],
        "corde": "gauche",
        "disciplines": ["plat", "haies", "steeple", "cross"],
        "stats_corpus": {"favori_taux_gagne": 0.341, "favori_taux_place": 0.6936, "nb_favoris_corpus": 173, "source": "turf.bzh_premium_2024_2026"},
        "distance_bins": {
            "plat_inter": {"min": 2000, "max": 2500}, "haies_moyen": {"min": 3200, "max": 4000},
            "steeple_long": {"min": 4000, "max": 5500},
        },
        "gru_keys": [
            {"key": "LIA_HAI", "discipline": "haies", "priority": "high"},
            {"key": "LIA_STP", "discipline": "steeple", "priority": "high"},
        ],
        "numero_bias": {"applicable": False, "plafond_total_numero": 0},
        "flags_dominants": ["specialiste_lion_angers", "qualite_saut", "tenue_longue"],
        "ticket_policy": {"conseil": "densifier_leger", "obstacle": "elargir", "profil_rapport": "moyen_a_eleve"},
    },
}


def normalize_hippo_key(name: str) -> Optional[str]:
    """Map any hippodrome string to catalog key."""
    if not name:
        return None
    n = name.lower().strip()
    n = n.replace("é", "e").replace("è", "e").replace("ê", "e").replace("'", " ").replace("-", " ")
    n = " ".join(n.split())  # collapse spaces
    # 1) exact key or exact alias
    for key, entry in GRU_CATALOG.items():
        if n == key or n.replace(" ", "_") == key:
            return key
        for al in entry.get("aliases", []):
            if n == al or n == al.replace("-", " "):
                return key
    # 2) fuzzy fragments — longest / most specific first (avoid angers ⊂ lion d angers)
    fragments = [
        ("clairefontaine", "clairefontaine"), ("lion d angers", "lion_angers"),
        ("lion-d angers", "lion_angers"), ("le lion", "lion_angers"),
        ("beaumont de lomagne", "beaumont_lomagne"),
        ("beaumont-de-lomagne", "beaumont_lomagne"), ("croise-laroche", "croise_laroche"),
        ("croise laroche", "croise_laroche"), ("la capelle", "la_capelle"),
        ("meslay-du-maine", "meslay"), ("meslay du maine", "meslay"),
        ("paris longchamp", "paris_longchamp"), ("saint-cloud", "saint_cloud"),
        ("saint cloud", "saint_cloud"), ("lyon-parilly", "lyon_parilly"),
        ("lyon parilly", "lyon_parilly"), ("lyon-la-soie", "lyon_la_soie"),
        ("lyon la soie", "lyon_la_soie"), ("marseille-borely", "marseille_borely"),
        ("marseille borely", "marseille_borely"), ("marseille-vivaux", "marseille_vivaux"),
        ("marseille vivaux", "marseille_vivaux"), ("pornichet-la-baule", "pornichet"),
        ("pornichet la baule", "pornichet"), ("pont-long", "pau"),
        ("vincennes", "vincennes"), ("auteuil", "auteuil"), ("enghien", "enghien"),
        ("deauville", "deauville"), ("cagnes", "cagnes"), ("chantilly", "chantilly"),
        ("vichy", "vichy"), ("longchamp", "paris_longchamp"), ("compiegne", "compiegne"),
        ("parilly", "lyon_parilly"), ("toulouse", "toulouse"), ("cepiere", "toulouse"),
        ("pau", "pau"), ("pornichet", "pornichet"), ("baule", "pornichet"),
        ("cabourg", "cabourg"), ("borely", "marseille_borely"), ("vivaux", "marseille_vivaux"),
        ("la soie", "lyon_la_soie"), ("caen", "caen"), ("fontainebleau", "fontainebleau"),
        ("laval", "laval"), ("bordeaux", "bordeaux"), ("bouscat", "bordeaux"),
        ("nantes", "nantes"), ("amiens", "amiens"), ("argentan", "argentan"),
        ("capelle", "la_capelle"), ("feurs", "feurs"), ("dieppe", "dieppe"),
        ("lomagne", "beaumont_lomagne"), ("meslay", "meslay"), ("graignes", "graignes"),
        ("hyeres", "hyeres"), ("lion", "lion_angers"), ("angers", "angers"),
    ]
    for frag, key in fragments:
        if frag in n:
            return key
    return None


def get_gru_entry(hippodrome: str) -> Optional[Dict[str, Any]]:
    key = normalize_hippo_key(hippodrome)
    if key is None:
        return None
    return GRU_CATALOG.get(key)


def resolve_distance_bin(entry: Dict[str, Any], distance_m: int, discipline: str = "") -> Optional[str]:
    bins = entry.get("distance_bins") or {}
    disc = (discipline or "").lower()
    # prefer discipline-prefixed bins when available
    candidates = []
    for bname, brange in bins.items():
        if disc and ("attele" in disc or "trot" in disc) and bname.startswith("plat"):
            continue
        if disc and "plat" in disc and bname.startswith("attele"):
            continue
        if disc and ("haie" in disc or "steeple" in disc or "obstacle" in disc) and bname.startswith("plat"):
            continue
        mn = brange.get("min", 0)
        mx = brange.get("max", 99999)
        if mn <= distance_m <= mx:
            candidates.append(bname)
    if not candidates:
        for bname, brange in bins.items():
            if brange.get("min", 0) <= distance_m <= brange.get("max", 99999):
                return bname
        return None
    return candidates[0]



# Maxima cotes observés via scrape open-pmu-api (hippo=) — 18/09/2026
# n = courses retournées (échantillon API, pas historique complet)
# max_Xe = cote max observée en place X dans le top5
OPA_OBSERVED_MAX = {
    "vincennes": {"n": 2535, "max_1er": 44.0, "max_3e": 50.0, "max_4e": 99.0, "max_5e": 68.0, "c100": 0},
    "auteuil": {"n": 597, "max_1er": 23.0, "max_3e": 57.0, "max_4e": 51.0, "max_5e": 65.0, "c100": 0},
    "deauville": {"n": 529, "max_1er": 57.0, "max_3e": 58.0, "max_4e": 67.0, "max_5e": 30.0, "c100": 0},
    "enghien": {"n": 528, "max_1er": 31.0, "max_3e": 48.0, "max_4e": 118.0, "max_5e": 123.0, "c100": 3},
    "chantilly": {"n": 415, "max_1er": 14.0, "max_3e": 64.0, "max_4e": 46.0, "max_5e": 37.0, "c100": 0},
    "cabourg": {"n": 205, "max_1er": 15.0, "max_3e": 44.0, "max_4e": 106.0, "max_5e": 143.0, "c100": 4},
    "vichy": {"n": 165, "max_1er": 14.0, "max_3e": 186.0, "max_4e": 29.0, "max_5e": 76.0, "c100": 1},
    "clairefontaine": {"n": 175, "max_1er": 24.0, "max_3e": 38.0, "max_4e": 47.0, "max_5e": 41.0, "c100": 0},
    "paris_longchamp": {"n": 550, "max_1er": 33.0, "max_3e": 46.0, "max_4e": 47.0, "max_5e": 44.0, "c100": 0},
    "caen": {"n": 67, "max_1er": 9.9, "max_3e": 45.0, "max_4e": 22.0, "max_5e": 44.0, "c100": 0},
    "pornichet": {"n": 9, "max_1er": 1.8, "max_3e": 22.0, "max_4e": 14.0, "max_5e": 47.0, "c100": 0},
    "laval": {"n": 68, "max_1er": 6.7, "max_3e": 10.0, "max_4e": 38.0, "max_5e": 27.0, "c100": 0},
}

# Alias noms hippo pour open-pmu-api (query hippo=)
OPA_HIPPO_ALIASES = {
    "vincennes": "Vincennes",
    "auteuil": "Auteuil",
    "deauville": "Deauville",
    "enghien": "Enghien",
    "chantilly": "Chantilly",
    "cabourg": "Cabourg",
    "vichy": "Vichy",
    "clairefontaine": "Clairefontaine",
    "paris_longchamp": "Paris-Longchamp",
    "longchamp": "Paris-Longchamp",
    "caen": "Caen",
    "pornichet": "Pornichet",
    "laval": "Laval",
    "toulouse": "Toulouse",
    "pau": "Pau",
    "nantes": "Nantes",
    "fontainebleau": "Fontainebleau",
    "cagnes": "Cagnes",  # partial data
}



# Extrapolation pour hippos sans scrape OPA direct.
# Basée sur pairs (discipline, ouverture, type piste) + facteur conservateur 0.90–0.95.
# effective_cote_max_utile() consomme aussi ce dict.
OPA_EXTRAPOLATED = {
    "amiens": {'source': 'extrapolated', 'peers': ['caen', 'laval', 'cabourg'], 'family': 'trot_plat_regional', 'rationale': 'Trot+plat Hauts-de-France; mix Caen/Laval + ouverture Cabourg', 'n_peers_courses': 340, 'max_1er': 14.2, 'max_3e': 42.8, 'max_4e': 100.7, 'max_5e': 135.8, 'c100_peers': 4, 'factor': 0.95, 'obs_max_raw': 143.0},
    "angers": {'source': 'extrapolated', 'peers': ['pornichet', 'laval', 'vichy'], 'family': 'multi_ouest', 'rationale': 'Multi Ouest; Vichy pour composante plat ouverte', 'n_peers_courses': 242, 'max_1er': 13.3, 'max_3e': 176.7, 'max_4e': 36.1, 'max_5e': 72.2, 'c100_peers': 1, 'factor': 0.95, 'obs_max_raw': 186.0},
    "argentan": {'source': 'extrapolated', 'peers': ['caen', 'laval', 'clairefontaine'], 'family': 'trot_plat_normand', 'rationale': 'Normandie multi; Caen+Clairefontaine', 'n_peers_courses': 310, 'max_1er': 22.8, 'max_3e': 42.8, 'max_4e': 44.6, 'max_5e': 41.8, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 47.0},
    "beaumont_lomagne": {'source': 'extrapolated', 'peers': ['laval', 'pornichet'], 'family': 'trot_provincial_serre', 'rationale': 'Petit volume provincial Sud-Ouest', 'n_peers_courses': 77, 'max_1er': 6.4, 'max_3e': 20.9, 'max_4e': 36.1, 'max_5e': 44.6, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 47.0},
    "bordeaux": {'source': 'extrapolated', 'peers': ['vichy', 'deauville', 'auteuil'], 'family': 'multi_sud_ouest', 'rationale': 'Plat+attele+haies Sud-Ouest', 'n_peers_courses': 1291, 'max_1er': 54.1, 'max_3e': 176.7, 'max_4e': 63.6, 'max_5e': 72.2, 'c100_peers': 1, 'factor': 0.95, 'obs_max_raw': 186.0},
    "cagnes": {'source': 'extrapolated', 'peers': ['enghien', 'cabourg', 'caen'], 'family': 'trot_as_national_sable', 'rationale': 'Pôle national trot (comme Caen/Enghien), sable, AS fréquent; Cabourg=corde droite mais même famille longshot', 'n_peers_courses': 800, 'max_1er': 29.4, 'max_3e': 45.6, 'max_4e': 112.1, 'max_5e': 135.8, 'c100_peers': 7, 'factor': 0.95, 'obs_max_raw': 143.0},
    "compiegne": {'source': 'extrapolated', 'peers': ['chantilly', 'auteuil', 'vichy', 'paris_longchamp'], 'family': 'plat_obstacle_herbe', 'rationale': 'Plat+obstacle herbe Nord; Chantilly/Auteuil + Vichy extrêmes', 'n_peers_courses': 1727, 'max_1er': 31.3, 'max_3e': 176.7, 'max_4e': 48.4, 'max_5e': 72.2, 'c100_peers': 1, 'factor': 0.95, 'obs_max_raw': 186.0},
    "croise_laroche": {'source': 'extrapolated', 'peers': ['enghien', 'cabourg'], 'family': 'trot_as_regional_sable', 'rationale': 'Pôle régional A trot Nord, profil AS comparable Enghien', 'n_peers_courses': 733, 'max_1er': 29.4, 'max_3e': 45.6, 'max_4e': 112.1, 'max_5e': 135.8, 'c100_peers': 7, 'factor': 0.95, 'obs_max_raw': 143.0},
    "dieppe": {'source': 'extrapolated', 'peers': ['auteuil', 'clairefontaine', 'chantilly'], 'family': 'obstacle_plat_normand', 'rationale': 'Plat+haies+steeple Normandie', 'n_peers_courses': 1187, 'max_1er': 22.8, 'max_3e': 60.8, 'max_4e': 48.4, 'max_5e': 61.8, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 65.0},
    "feurs": {'source': 'extrapolated', 'peers': ['laval', 'caen', 'pornichet'], 'family': 'trot_provincial_serre', 'rationale': 'Provincial trot/monté, volumes modestes, extrêmes rares', 'n_peers_courses': 144, 'max_1er': 9.4, 'max_3e': 42.8, 'max_4e': 36.1, 'max_5e': 44.6, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 47.0},
    "fontainebleau": {'source': 'extrapolated', 'peers': ['chantilly', 'clairefontaine', 'paris_longchamp'], 'family': 'plat_obstacle_regional', 'rationale': 'Plat+haies régional proche Clairefontaine/Chantilly', 'n_peers_courses': 1140, 'max_1er': 31.3, 'max_3e': 60.8, 'max_4e': 44.6, 'max_5e': 41.8, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 64.0},
    "graignes": {'source': 'extrapolated', 'peers': ['laval', 'caen', 'pornichet'], 'family': 'trot_provincial_serre', 'rationale': 'Idem provincial Normandie/Ouest', 'n_peers_courses': 144, 'max_1er': 9.4, 'max_3e': 42.8, 'max_4e': 36.1, 'max_5e': 44.6, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 47.0},
    "hyeres": {'source': 'extrapolated', 'peers': ['caen', 'laval', 'pornichet'], 'family': 'trot_provincial_moyen', 'rationale': 'Trot Sud, volumes moyens', 'n_peers_courses': 144, 'max_1er': 9.4, 'max_3e': 42.8, 'max_4e': 36.1, 'max_5e': 44.6, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 47.0},
    "la_capelle": {'source': 'extrapolated', 'peers': ['caen', 'laval'], 'family': 'trot_provincial_moyen', 'rationale': 'Pôle régional A trot Nord, profil Caen-like', 'n_peers_courses': 135, 'max_1er': 9.4, 'max_3e': 42.8, 'max_4e': 36.1, 'max_5e': 41.8, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 45.0},
    "lion_angers": {'source': 'extrapolated', 'peers': ['auteuil', 'vichy', 'clairefontaine'], 'family': 'obstacle_ouest', 'rationale': 'Obstacle+cross Ouest', 'n_peers_courses': 937, 'max_1er': 22.8, 'max_3e': 176.7, 'max_4e': 48.4, 'max_5e': 72.2, 'c100_peers': 1, 'factor': 0.95, 'obs_max_raw': 186.0},
    "lyon_la_soie": {'source': 'extrapolated', 'peers': ['enghien', 'cabourg'], 'family': 'trot_as_regional_sable', 'rationale': 'Piste trot régionale ouverte, profil désordre proche Enghien/Cabourg', 'n_peers_courses': 733, 'max_1er': 29.4, 'max_3e': 45.6, 'max_4e': 112.1, 'max_5e': 135.8, 'c100_peers': 7, 'factor': 0.95, 'obs_max_raw': 143.0},
    "lyon_parilly": {'source': 'extrapolated', 'peers': ['vichy', 'deauville', 'auteuil', 'enghien'], 'family': 'multi_regional_ouvert', 'rationale': 'Multi Lyon ouvert; mix plat Vichy/Deauville + obstacle Auteuil + trot Enghien', 'n_peers_courses': 1819, 'max_1er': 54.1, 'max_3e': 176.7, 'max_4e': 112.1, 'max_5e': 116.8, 'c100_peers': 4, 'factor': 0.95, 'obs_max_raw': 186.0},
    "marseille_borely": {'source': 'extrapolated', 'peers': ['enghien', 'cabourg', 'vichy'], 'family': 'trot_plat_regional_ouvert', 'rationale': 'Multi-discipline régional ouvert; Vichy pour extrêmes plat', 'n_peers_courses': 898, 'max_1er': 29.4, 'max_3e': 176.7, 'max_4e': 112.1, 'max_5e': 135.8, 'c100_peers': 8, 'factor': 0.95, 'obs_max_raw': 186.0},
    "marseille_vivaux": {'source': 'extrapolated', 'peers': ['enghien', 'cabourg', 'caen'], 'family': 'trot_as_regional_sable', 'rationale': 'Trot + plat sud, AS, outsiders fréquents en top5', 'n_peers_courses': 800, 'max_1er': 29.4, 'max_3e': 45.6, 'max_4e': 112.1, 'max_5e': 135.8, 'c100_peers': 7, 'factor': 0.95, 'obs_max_raw': 143.0},
    "meslay": {'source': 'extrapolated', 'peers': ['laval', 'pornichet', 'caen'], 'family': 'trot_provincial_moyen', 'rationale': 'Trot Ouest provincial', 'n_peers_courses': 144, 'max_1er': 9.4, 'max_3e': 42.8, 'max_4e': 36.1, 'max_5e': 44.6, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 47.0},
    "nantes": {'source': 'extrapolated', 'peers': ['pornichet', 'laval', 'caen'], 'family': 'trot_plat_ouest', 'rationale': 'Ouest multi, proche Pornichet/Laval', 'n_peers_courses': 144, 'max_1er': 9.4, 'max_3e': 42.8, 'max_4e': 36.1, 'max_5e': 44.6, 'c100_peers': 0, 'factor': 0.95, 'obs_max_raw': 47.0},
    "pau": {'source': 'extrapolated', 'peers': ['auteuil', 'vichy', 'deauville'], 'family': 'obstacle_sud_ouvert', 'rationale': 'Obstacle fort + plat; Auteuil référence obstacle, Vichy extrêmes', 'n_peers_courses': 1291, 'max_1er': 54.1, 'max_3e': 176.7, 'max_4e': 63.6, 'max_5e': 72.2, 'c100_peers': 1, 'factor': 0.95, 'obs_max_raw': 186.0},
    "saint_cloud": {'source': 'extrapolated', 'peers': ['paris_longchamp', 'deauville', 'vichy', 'chantilly'], 'family': 'plat_herbe_parisien_ouvert', 'rationale': 'Plat herbe parisien tres_ouvert, ligne droite longue; Vichy extrêmes + Longchamp/Deauville structure', 'n_peers_courses': 1659, 'max_1er': 54.1, 'max_3e': 176.7, 'max_4e': 63.6, 'max_5e': 72.2, 'c100_peers': 1, 'factor': 0.95, 'obs_max_raw': 186.0},
    "toulouse": {'source': 'extrapolated', 'peers': ['vichy', 'deauville', 'auteuil', 'cabourg'], 'family': 'multi_sud_moyen', 'rationale': 'Multi Sud (favori plutôt fiable turf.bzh 37%); peers mixtes', 'n_peers_courses': 1496, 'max_1er': 54.1, 'max_3e': 176.7, 'max_4e': 100.7, 'max_5e': 135.8, 'c100_peers': 5, 'factor': 0.95, 'obs_max_raw': 186.0},
}

def get_opa_observed(hippo_key: str) -> dict:
    """Retourne maxima OPA scrapés, sinon extrapolation par pairs similaires."""
    if hippo_key in OPA_OBSERVED_MAX:
        d = dict(OPA_OBSERVED_MAX[hippo_key])
        d["source"] = "scraped"
        return d
    if hippo_key in OPA_EXTRAPOLATED:
        return dict(OPA_EXTRAPOLATED[hippo_key])
    return {}


def effective_cote_max_utile(entry: dict, hippo_key: str = None) -> float:
    """cote_max_utile GRU, rehaussé par maxima OPA observés si disponibles."""
    op = (entry or {}).get("outsider_profile") or {}
    base = float(op.get("cote_max_utile") or 110)
    obs = get_opa_observed(hippo_key or "")
    if not obs:
        return base
    obs_max = max(obs.get("max_3e", 0), obs.get("max_4e", 0), obs.get("max_5e", 0), obs.get("max_1er", 0))
    # cushion 15%
    return max(base, obs_max * 1.15 + 5)



def _apply_opa_coherence_patch():
    """Profils outsider cohérents OPA (scraped+extrapolés) sur tous les GRU."""
    for key, entry in GRU_CATALOG.items():
        obs = get_opa_observed(key)
        op = dict(entry.get("outsider_profile") or {})
        obs_max = 0.0
        c100 = 0
        source = "none"
        if obs:
            source = obs.get("source", "scraped")
            obs_max = max(
                float(obs.get("max_3e") or 0), float(obs.get("max_4e") or 0),
                float(obs.get("max_5e") or 0), float(obs.get("max_1er") or 0),
            )
            c100 = int(obs.get("c100") or obs.get("c100_peers") or 0)

        FORCED_OPEN = {
            "enghien": ("ouvert", "high", 1.4),
            "cabourg": ("ouvert", "high", 1.4),
            "vincennes": ("moyen", "high", 1.2),
            "vichy": ("ouvert", "high", 1.5),
            "caen": ("moyen", "medium", 1.0),
            "laval": ("serre", "medium", 0.8),
            "pornichet": ("moyen", "medium", 1.0),
            "auteuil": ("tres_ouvert", "high", 1.3),
            "deauville": ("tres_ouvert", "high", 1.3),
            "chantilly": ("tres_ouvert", "high", 1.2),
            "paris_longchamp": ("tres_ouvert", "high", 1.2),
            "clairefontaine": ("ouvert", "high", 1.1),
            "cagnes": ("ouvert", "high", 1.3),
            "lyon_la_soie": ("ouvert", "high", 1.3),
            "marseille_vivaux": ("ouvert", "high", 1.3),
            "marseille_borely": ("ouvert", "high", 1.3),
            "croise_laroche": ("ouvert", "high", 1.3),
            "amiens": ("moyen", "high", 1.2),
            "saint_cloud": ("tres_ouvert", "high", 1.4),
            "compiegne": ("ouvert", "high", 1.3),
            "pau": ("ouvert", "high", 1.3),
            "lyon_parilly": ("ouvert", "high", 1.3),
            "toulouse": ("moyen", "high", 1.2),
            "bordeaux": ("moyen", "high", 1.2),
            "angers": ("moyen", "high", 1.2),
            "dieppe": ("moyen", "medium", 1.0),
            "lion_angers": ("moyen", "high", 1.2),
            "fontainebleau": ("moyen", "medium", 1.0),
            "feurs": ("serre", "low", 0.6),
            "graignes": ("serre", "low", 0.6),
            "beaumont_lomagne": ("serre", "low", 0.6),
            "hyeres": ("moyen", "medium", 0.9),
            "la_capelle": ("moyen", "medium", 0.9),
            "meslay": ("moyen", "medium", 0.9),
            "argentan": ("moyen", "medium", 1.0),
            "nantes": ("moyen", "medium", 1.0),
        }

        if key in FORCED_OPEN:
            open_, weight, boost = FORCED_OPEN[key]
        else:
            open_ = op.get("hippo_openness") or "moyen"
            weight = op.get("outsider_weight") or "medium"
            boost = float(op.get("boost_extreme") or 1.0)
            if obs_max >= 100 or c100 > 0:
                open_ = "ouvert" if open_ in ("serre", "moyen") else open_
                weight = "high"
                boost = max(boost, 1.3)

        if obs_max > 0:
            new_max = min(220, max(80, int(obs_max * 1.15) + 5))
        else:
            new_max = int(op.get("cote_max_utile") or 110)
        if open_ in ("ouvert", "tres_ouvert"):
            new_max = max(new_max, 110)
        if open_ == "serre" and 0 < obs_max < 55:
            new_max = min(new_max, max(90, int(obs_max * 1.25) + 10))

        sweet = list(op.get("cote_sweet_spot") or [12, 28])
        if open_ in ("ouvert", "tres_ouvert") and len(sweet) == 2 and sweet[1] < 35:
            sweet = [12, 35]

        _db = op.get("discipline_bias")
        disc_bias = dict(_db) if isinstance(_db, dict) else {}
        if not disc_bias:
            for d in (entry.get("disciplines") or []):
                if d in ("haies", "steeple", "cross"):
                    disc_bias[d] = 1.3
                elif d == "plat":
                    disc_bias[d] = 1.15
                elif d in ("attele", "monte"):
                    disc_bias[d] = 1.0 if open_ != "serre" else 0.7

        new_op = {
            "outsider_weight": weight,
            "longshot_viable": True,
            "cote_sweet_spot": sweet,
            "cote_max_utile": new_max,
            "extreme_longshot_ok": True,
            "extreme_range": [35, new_max],
            "hippo_openness": open_,
            "discipline_bias": disc_bias,
            "boost_extreme": boost,
            "opa_source": source,
            "opa_obs_max": round(obs_max, 1) if obs_max else None,
        }
        if source == "scraped":
            new_op["opa_c100"] = c100
        if source == "extrapolated" and obs:
            new_op["opa_peers"] = obs.get("peers")
            new_op["opa_family"] = obs.get("family")
        entry["outsider_profile"] = new_op

        tp = dict(entry.get("ticket_policy") or {})
        if open_ == "tres_ouvert":
            tp["mode"] = "elargir"
            tp["outsider_slot"] = True
        elif open_ == "ouvert":
            tp.setdefault("mode", "mixte")
            tp["outsider_slot"] = True
        elif open_ == "serre":
            tp["mode"] = "densifier"
            tp["outsider_slot"] = False
        else:
            tp.setdefault("mode", "mixte")
            tp["outsider_slot"] = True
        entry["ticket_policy"] = tp

        rp = dict(entry.get("rapport_profile") or {})
        if open_ == "tres_ouvert":
            rp["median_desordre_indic"] = "eleve"
            rp["ticket_width_bias"] = "elargi"
        elif open_ == "ouvert":
            rp["median_desordre_indic"] = "moyen_haut"
            rp["ticket_width_bias"] = "elargi"
        elif open_ == "serre":
            rp["median_desordre_indic"] = "bas"
            rp["ticket_width_bias"] = "serre"
        else:
            rp.setdefault("median_desordre_indic", "moyen")
            rp.setdefault("ticket_width_bias", "mixte")
        entry["rapport_profile"] = rp


def _apply_selection_levers_coherence():
    """selection_levers + rapport + ticket.conseil harmonisés (36 GRU)."""
    LEVER_PROFILES = {
        "trot_as_open": {
            "style_dominant": "placement_precoce", "surface_key": False,
            "terrain_sensible": False, "rendre_distance_ok": False,
            "avantage_local": False, "autostart_critical": True, "gaucher_droitier": "gaucher",
        },
        "trot_as_droitier": {
            "style_dominant": "placement_precoce", "surface_key": False,
            "terrain_sensible": False, "rendre_distance_ok": False,
            "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "droitier",
        },
        "trot_provincial": {
            "style_dominant": "mixte", "surface_key": False,
            "terrain_sensible": False, "rendre_distance_ok": True,
            "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher",
        },
        "plat_herbe_paris": {
            "style_dominant": "mixte", "surface_key": True,
            "terrain_sensible": True, "rendre_distance_ok": True,
            "avantage_local": False, "autostart_critical": False, "gaucher_droitier": "gaucher",
        },
        "obstacle": {
            "style_dominant": "finisseur", "surface_key": True,
            "terrain_sensible": True, "rendre_distance_ok": True,
            "avantage_local": False, "autostart_critical": False, "gaucher_droitier": None,
        },
        "multi_regional": {
            "style_dominant": "mixte", "surface_key": True,
            "terrain_sensible": False, "rendre_distance_ok": True,
            "avantage_local": True, "autostart_critical": True, "gaucher_droitier": "gaucher",
        },
        "psf_cagnes": {
            "style_dominant": "mixte", "surface_key": True,
            "terrain_sensible": False, "rendre_distance_ok": True,
            "avantage_local": False, "autostart_critical": True, "gaucher_droitier": "gaucher",
        },
    }
    HIPPO_LEVERS = {
        "vincennes": ("trot_as_open", "Grande piste; AS coeur 1ere ligne"),
        "enghien": ("trot_as_open", "AS critique; virages relevés; coeur 1ere ligne"),
        "cabourg": ("trot_as_droitier", "Corde droite; difficile revenir; AS coeur"),
        "caen": ("trot_as_droitier", "Pôle national trot; corde droite; AS"),
        "cagnes": ("psf_cagnes", "PSF + trot; spécialistes surface; AS"),
        "auteuil": ("obstacle", "Obstacle; saut + tenue; terrain lourd"),
        "deauville": ("plat_herbe_paris", "Plat/PSF; terrain sensible"),
        "chantilly": ("plat_herbe_paris", "Herbe; terrain sensible; spécialistes"),
        "paris_longchamp": ("plat_herbe_paris", "Grande piste; terrain sensible"),
        "saint_cloud": ("plat_herbe_paris", "Corde gauche; ligne 900m; near-rail"),
        "vichy": ("multi_regional", "Multi; désordre possible; AS + plat"),
        "compiegne": ("obstacle", "Plat+obstacle; terrain sensible"),
        "lyon_parilly": ("multi_regional", "AS + spécialistes Parilly"),
        "lyon_la_soie": ("trot_as_open", "Trot régional; AS; ouverture"),
        "toulouse": ("multi_regional", "Multi Sud; favori assez fiable"),
        "pau": ("obstacle", "Obstacle hiver + PSF; local fort"),
        "pornichet": ("trot_provincial", "Trot Ouest; densifier si favori clair"),
        "marseille_borely": ("multi_regional", "Trot+plat Sud; longshots"),
        "marseille_vivaux": ("trot_as_open", "Trot Sud; AS; longshots"),
        "fontainebleau": ("obstacle", "Plat+haies; terrain"),
        "laval": ("trot_provincial", "Trot provincial; densifier"),
        "clairefontaine": ("plat_herbe_paris", "Herbe Normandie; terrain sensible"),
        "bordeaux": ("multi_regional", "Multi Sud-Ouest; local"),
        "nantes": ("trot_provincial", "Ouest multi"),
        "croise_laroche": ("trot_as_open", "Trot Nord; AS"),
        "amiens": ("trot_provincial", "Trot+plat Hauts-de-France"),
        "angers": ("multi_regional", "Multi Ouest; local"),
        "argentan": ("trot_provincial", "Normandie trot/plat"),
        "la_capelle": ("trot_provincial", "Trot Nord provincial"),
        "feurs": ("trot_provincial", "Piste régulière; densifier; local"),
        "dieppe": ("obstacle", "Plat+haies+steeple Normandie"),
        "beaumont_lomagne": ("trot_provincial", "Petit volume; densifier"),
        "meslay": ("trot_provincial", "Trot Ouest provincial"),
        "graignes": ("trot_provincial", "Trot provincial; densifier"),
        "hyeres": ("trot_provincial", "Trot Sud"),
        "lion_angers": ("obstacle", "Obstacle+cross Ouest; local"),
    }
    CORDE = {
        "cabourg": "droitier", "caen": "droitier", "pau": "droitier",
        "vincennes": "gaucher", "enghien": "gaucher", "auteuil": "gaucher",
        "saint_cloud": "gaucher", "chantilly": "droitier",
        "paris_longchamp": "mixte", "deauville": "mixte", "clairefontaine": "mixte",
    }
    for key, entry in GRU_CATALOG.items():
        prof_name, notes = HIPPO_LEVERS.get(key, ("multi_regional", "profil par défaut"))
        base = dict(LEVER_PROFILES.get(prof_name) or LEVER_PROFILES["multi_regional"])
        if key in CORDE:
            base["gaucher_droitier"] = CORDE[key]
        old = entry.get("selection_levers") or {}
        if old.get("notes") and len(str(old.get("notes") or "")) > len(notes):
            base["notes"] = old["notes"]
        else:
            base["notes"] = notes
        entry["selection_levers"] = base

        op = entry.get("outsider_profile") or {}
        open_ = op.get("hippo_openness") or "moyen"
        rp = dict(entry.get("rapport_profile") or {})
        if open_ == "tres_ouvert":
            rp["median_desordre_indic"] = "eleve"
            rp["ticket_width_bias"] = "elargi"
            rp["favori_fiable"] = False
        elif open_ == "ouvert":
            rp["median_desordre_indic"] = "moyen_haut"
            rp["ticket_width_bias"] = "elargi"
            rp.setdefault("favori_fiable", False)
        elif open_ == "serre":
            rp["median_desordre_indic"] = "bas"
            rp["ticket_width_bias"] = "serre"
            rp["favori_fiable"] = True
        else:
            rp.setdefault("median_desordre_indic", "moyen")
            rp.setdefault("ticket_width_bias", "mixte")
        stats = entry.get("stats_corpus") or {}
        fg = stats.get("favori_taux_gagne")
        if fg is not None:
            rp["favori_fiable"] = bool(fg >= 0.34)
        entry["rapport_profile"] = rp

        tp = dict(entry.get("ticket_policy") or {})
        width = rp.get("ticket_width_bias")
        if width == "elargi":
            tp["conseil"] = "elargir" if open_ == "tres_ouvert" else "mixte"
        elif width == "serre":
            tp["conseil"] = "densifier" if rp.get("favori_fiable") else "densifier_leger"
        else:
            tp.setdefault("conseil", "mixte")
        entry["ticket_policy"] = tp


_apply_opa_coherence_patch()
_apply_selection_levers_coherence()

# Normalise aliases width
for _e in GRU_CATALOG.values():
    _rp = _e.get("rapport_profile") or {}
    if _rp.get("ticket_width_bias") == "large":
        _rp["ticket_width_bias"] = "elargi"
        _e["rapport_profile"] = _rp



def list_gru_hippodromes() -> List[str]:
    return list(GRU_CATALOG.keys())


# ======================================================================================================================
# v1.29.67 : RÉGLAGES DU TICKET B PAR PORTÉE (famille de discipline > distance > hippodrome)
# Un ajustement validé sur un hippodrome ou une discipline ne doit pas dégrader les autres : les réglages du ticket B sont résolus du plus général au
# plus spécifique, chaque niveau ne redéfinissant que les paramètres qu'il veut changer :
#     global  →  famille (TROT | GALOP | OBSTACLE)  →  famille × distance  →  hippodrome (toutes familles)  →  hippodrome × famille
#                                                                                       [fiche du catalogue : entry["reglages_b"]]
# Un niveau fin n'est justifié qu'avec assez de courses (≈ 30) : sinon il hérite de son parent (`_herite`). Une variable d'environnement
# VANTAGE_B_* explicite l'emporte sur toutes les portées (interrupteur / ablation globale).
FAMILLES_DISCIPLINE = {"TROT_ATTELE": "TROT", "TROT_MONTE": "TROT", "PLAT": "GALOP", "HAIES": "OBSTACLE", "STEEPLE": "OBSTACLE", "CROSS": "OBSTACLE"}
TRANCHES_DISTANCE = ((1400, "<=1400"), (2000, "1400-2000"), (2700, "2000-2700"), (10 ** 9, ">2700"))

REGLAGES_B_GLOBAL = {
    "alpha": 0.75,               # part du rang marché dans le mélange (C = 0,5)
    "alpha_t3": 0.8,             # part du rang marché pour les T3 (None = identique à alpha)
    "rangs_gru": 2.0,            # GRU renforcé (G10, G56, G58-G64) : rangs par point de PCH
    "rangs_classements": 0.5,    # classements B11 / B12 (poids supplémentaire)
    "rangs_pepite": 0.3, "plafond_pepite": 3.0,
    "rangs_piege": 50.0,
    "rangs_g30": 10.0,           # multiplicateur de numéro renforcé
    "rangs_corde": 1.0, "corde_actif": 1,
    "rerank": 1,                 # T3 par le marché, T4 par PCH + ordre_final + valeur PMU
    "entrees_pepite": 1,         # outsiders à pépite maximale admis dans B
    "familles": 0,               # 1 = règle « un cheval par famille de tranche »
}
# Portées par famille. Éléments chiffrés : rejeu 55 courses (23 trot, 22 plat, 10 obstacle).
REGLAGES_B_FAMILLE = {
    # TROT : le PCH sépare mieux que le marché (AUC 0,84 contre 0,77) ; un B porté sur le marché dégradait la capture (−0,30 à α = 0,75).
    # B devient un complément porté sur le PCH (α = 0,3) avec les composantes en rangs ; sans T3 « marché », sans classement T3/T4, sans entrée pépite
    # (les trois dégradaient le trot : 4,35 → 4,17). Rejeu : capture 4,35 (C 4,43), identique à C dans 39 %, couverture C∪B 4,52 (C 4,43).
    "TROT": {"alpha": 0.30, "alpha_t3": None, "rerank": 0, "entrees_pepite": 0},
    # GALOP (plat) : le marché pèse davantage ; B complet actif. Rejeu : capture 3,95 (C 3,59, +0,36), identique à C dans 9 %.
    "GALOP": {},
    # OBSTACLE (haies, steeple-chase) : 10 courses seulement → hérite de GALOP tant que l'effectif est insuffisant (rejeu : 3,80 contre 3,40).
    "OBSTACLE": {"_herite": "GALOP"},
}
# Portées famille × tranche de distance : vide tant qu'aucune n'a l'effectif requis. Exemple : ("TROT", "2000-2700"): {"alpha": 0.35}
REGLAGES_B_FAMILLE_DISTANCE: dict = {}
_CLES_REGLAGES_B = set(REGLAGES_B_GLOBAL) | {"_herite"}
_ENV_REGLAGES_B = {"VANTAGE_B_ALPHA": "alpha", "VANTAGE_B_ALPHA_T3": "alpha_t3", "VANTAGE_B_GRU_RANGS": "rangs_gru",
                   "VANTAGE_B_CLASSEMENTS_RANGS": "rangs_classements", "VANTAGE_B_PEPITE_RANGS": "rangs_pepite", "VANTAGE_B_PEPITE_PLAFOND": "plafond_pepite",
                   "VANTAGE_B_PIEGE_RANGS": "rangs_piege", "VANTAGE_B_G30_RANGS": "rangs_g30", "VANTAGE_B_CORDE_RANGS": "rangs_corde",
                   "VANTAGE_B_CORDE": "corde_actif", "VANTAGE_B_RERANK": "rerank", "VANTAGE_B_POOL_PEPITE": "_pool_pepite",
                   "VANTAGE_B_POOL_PEPITE_MAX": "entrees_pepite", "VANTAGE_B_FAMILLES": "familles"}


def famille_course(race) -> str:
    """TROT | GALOP (plat) | OBSTACLE (haies, steeple-chase, cross) ; GALOP par défaut pour une discipline inconnue."""
    d = getattr(race, "discipline", None)
    cle = (getattr(d, "value", None) or str(d or "")).upper()
    return FAMILLES_DISCIPLINE.get(cle, "TROT" if "TROT" in cle else "GALOP")


def tranche_distance(distance_m) -> str:
    try:
        dist = float(distance_m)
    except (TypeError, ValueError):
        return ">2700"
    for borne, lib in TRANCHES_DISTANCE:
        if dist <= borne:
            return lib
    return ">2700"


def _appliquer(cible: dict, source: Optional[dict], portees: list, nom: str) -> None:
    if not source:
        return
    herite = source.get("_herite")
    if herite and herite in REGLAGES_B_FAMILLE and herite != nom:
        _appliquer(cible, REGLAGES_B_FAMILLE[herite], portees, f"{nom}<-{herite}")
    utiles = {k: v for k, v in source.items() if k in _CLES_REGLAGES_B and k != "_herite"}
    if utiles:
        cible.update(utiles)
    portees.append(nom)


def reglages_b_pour(race, entry: Optional[dict] = None, env: Optional[dict] = None) -> dict:
    """Résout les réglages du ticket B pour UNE course. Retourne {"famille", "valeurs", "portees"} (portees = niveaux appliqués, du plus général
    au plus spécifique). `entry` = fiche GRU de l'hippodrome (par défaut : lue dans le catalogue). `env` : dict d'environnement (défaut os.environ)."""
    import os
    fam = famille_course(race)
    dist = tranche_distance(getattr(race, "distance_m", None))
    vals = dict(REGLAGES_B_GLOBAL)
    portees = ["global"]
    _appliquer(vals, REGLAGES_B_FAMILLE.get(fam), portees, f"famille:{fam}")
    _appliquer(vals, REGLAGES_B_FAMILLE_DISTANCE.get((fam, dist)), portees, f"famille:{fam}|distance:{dist}")
    if entry is None:
        try:
            entry = get_gru_entry(getattr(race, "hippodrome", None))
        except Exception:      # noqa: BLE001
            entry = None
    rb = (entry or {}).get("reglages_b") or {}
    hippo = normalize_hippo_key(getattr(race, "hippodrome", None)) or ""
    _appliquer(vals, rb.get("*"), portees, f"hippodrome:{hippo}")
    _appliquer(vals, rb.get(fam), portees, f"hippodrome:{hippo}|famille:{fam}")
    _appliquer(vals, rb.get(f"{fam}|{dist}"), portees, f"hippodrome:{hippo}|famille:{fam}|distance:{dist}")
    e = os.environ if env is None else env
    for var, cle in _ENV_REGLAGES_B.items():
        v = e.get(var)
        if v is None or str(v).strip() == "":
            continue
        try:
            if cle == "_pool_pepite":
                if str(v).strip().lower() in ("0", "false", "non", "off"):
                    vals["entrees_pepite"] = 0
            elif cle in ("rerank", "corde_actif", "familles"):
                vals[cle] = 1 if str(v).strip().lower() in ("1", "true", "oui", "on") else 0
            elif cle == "entrees_pepite":
                vals[cle] = int(float(v))
            else:
                vals[cle] = float(v)
            if "env" not in portees:
                portees.append("env")
        except (TypeError, ValueError):
            continue
    return {"famille": fam, "distance": dist, "valeurs": vals, "portees": portees}
