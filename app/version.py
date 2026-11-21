"""Version build et flags fusion."""
from __future__ import annotations

VERSION_RULESET = "v1.29.72"
VERSION_BUILD = "v1.29.72-FUSION-V69-1-GROK-V71-TOCARD-T3-T4-18112026"
VERSION_PACKAGE = "2026-11-18"

FUSION_FLAGS = {
    "gru_catalog_v1": True,
    "gru_catalog_full_21": True,
    "gru_catalog_full_36": True,
    "gru_enriched_stats": True,
    "gru_selection_levers": True,
    "gru_outsider_profile": True,
    "gru_extreme_longshot": True,
    "opa_observed_max": True,
    "opa_extrapolated": True,
    "gru_opa_coherent": True,
    "all_levers_g50_g57": True,
    "gru_signals_g_series": True,
    "gru_numero_bias": True,
    "gru_ticket_policy": True,
    "operational_model_v1_1_top5": True,
    "proxy_blended_p_top5": True,
    "gain_hybrid_060_040": True,
    "top5_metrics": True,
    "frequence_turf_icp": True,
    "musique_features": True,
    "race_resolver_rc": True,
    "ml_shadow": True,
    "roles_retired": True,
    "a1_tact_pch": True,
    "a2_b11_b12_d45": True,
    "a3_historique_repli": True,
    "mix_interne_t1t2t3t4": True,
    "forme_top6_intelligente": True,
    "penetrometre_multi_sources": True,
    "equidia_fiches": True,
    "equidia_serverapp_state": True,
    "equidia_equipements": True,
    "equidia_meteo_penetrometre": True,
    "longshot_slot_t34": True,
    "ghost_d_wave5": True,
    "ghost_d_wave6_complete": True,
    "ghost_d_full42": True,
    "ghost_d_catalog_formal": True,
    "longshot_f_catalog": True,
    "longshot_t3t4": True,
    "tocard_v2_p1p3": True,
    "t2_value_module": True,
    "prio1_7_formulas": True,
    "deploy_clean": True,
    "unique_engine": True,
    "tact_galop_plat_obstacle": True,
    "gru_g_in_pch": True,
    "gru_pepite_profile_fix": True,
    "gru_piege_score": True,
    "branch_29e_retired": True,
    "hf_export_module": True,
    "tocard_t3t4_only": True,
    "tocard_t3t4_only": True,
    "ghost_d_t34_replacements": True,
    "bsh_repli_degrade_30": True,
    "mpa_sans_penetro_attenue": True,
    "malus_m_t12_sans_commentaire": True,
    "gmo_soft_protect_t12_market": True,
    "ml_shadow_ticket_impact": False,
    "field_adaptive_market_blend": True,
    "ordre_market_blend_035": True,
    "proxy_sans_double_marche": True,
    "softmax_tau_field": True,
    "icp_blend_conditional": True,
    "hillclimb_pl_top5": True,
    "hippodrome_normalize_top25": True,
    "hippodrome_dropdown_quinte": True,
    "hippodrome_sort_volume_quinte": True,
    "zone_turf_fragment_course": True,
    "zt_pair_tables_headings": True,
    "zt_validate_chevaux": True,
    "cote_sanitize_zt": True,
    "pmu_api_deferre_gains": True,
    "pmu_early_before_fiches": True,
    "fusion_cote_saine": True,
    "discovery_canalturf_first": True,
    "discovery_geny_primary": True,
    "geny_discovery_robust_v2": True,
    "zt_fiche_gains_valeur": True,
    "zt_fiche_personne": True,
    "ct_fiche_musique": True,
    "poids_precedent_from_hist": True,
    "equidia_enrich_programme_only": True,
    "equidia_audit_arrivee": True,
    "turfbzh_ia_elo_bonus": True,
    "enrichissement_obligatoire": True,
    "enrichissement_phase_formelle": True,
    "seuil_collecte_80": True,
    "geny_nouveau_format_debloque": True,
    "geny_collecte_4e_source_reelle": True,
    "audit_label_source_dynamique": True,
    "frontend_watchrace_fix": True,
    "t4_penalties_half": True,   # RAH-310bis : pénalités modules ×0.50 pour T4a/T4b
    "t3_penalties_25": True,     # RAH-310ter : pénalités modules ×0.75 (−25 %) pour T3
    "collecte_4_sources_integrale": True,  # scrape ALL urls, merge by richness (19/09/2026)
    "inventaire_lacunes_aligne_modele": True,  # champs inventaire = noms modèles Cheval
    "enrichissement_proprietaire_fiches": True,  # proprietaire (CanalTurf+Turfoo) enfin recopié
    "geny_fiche_cheval": True,  # nouvelle source d'enrichissement : fiche individuelle Geny (SSR confirmée)
    "geny_records_par_discipline": True,  # records scindés par discipline (Monté/Attelé/...) + record_absolu
    "rapport_execution_tracabilite_integrale": True,  # étape 0 Identification + breakdown/synthesis par cheval (scoring) + toutes contraintes + flags enrichissement par cheval
    "geny_fiche_priorite_plus_complement_obligatoire": True,  # Geny en 1er (réutilise l'URL de l'étape 0 Identification) + source d'origine TOUJOURS en complément, jamais sautée
    # --- Fusion v1.29.4 (20/09/2026 soir) ---
    "sri_valeur_fallback_proxy": True,        # proxy gains/cote/floor si valeur_pmu absente
    "bsh_bsc_repli_degrade_50": True,         # bonus driver/entraîneur ×0.50 en mode REPLI
    "poids_malus_attenue_midcote": True,      # malus POIDS ×0.55 cotes 15-40 sans historique
    "quota_tranche_4_plus_4_force": False,    # v1.29.21: officiel = plage flexible 3-5
    "style_diversite_force_swap": True,       # swaps forcés si style majoritaire > cap
    "lacune_critique_valeur_poids": True,     # warning si >30% sans valeur_pmu ou poids
    "taux_collecte_effectif_hors_geny": True, # n'affiche plus 100% si Geny antibot
    "icp_proxy_stats_quinte": True,           # repli FT : scrape stats-quinte.com/presse-quinte
    "icp_grille_anti_favoris": True,          # T1/T2=1pt pos1-3 ; T3=2 ; T4=3 ; pos4-7 demi
    "pmu_api_valeur_poids_gains": True,       # handicapValeur / handicapPoids / gainsCarriere (déjà en pmu_api)
    "bundle_zip_execution_audit": True,
    "discovery_all_dates_robust": True,      # ZT daté+merge, CT Paris multi-URL, Turfoo resultats, seuil 2/3
    "discovery_seuil_2_sur_3": True,
    "enrich_secondaire_all_dates": True,
    "couverture_favoris_marche": True,     # ≥2/3 cotes courtes (remplace style)
    "malus_t12_assouplis": True,            # T1×1.10/0.90 T2×1.00/0.95
    "style_diversite_retiree": True,
    "valeur_pmu_proxy_rk": True,           # réduction km → valeur trot si pas handicap
    "rah90_force_max2_icp": True,          # post-GMO plafond ICP>=6
    "sri_proxy_gains_plafonne": True,
    "intra_tranche_qualite": True,
    "contraintes_hierarchie": True,         # noyau>marché>4+4>RAH90
    "checklist_warn_vs_fail": True,         # WARN si noyau bloque
    "style_greedy_retire": True,            # plus de cap_style en sélection
    "malus_t2_plus_doux": True,
    "geny_scraperapi_fallback": True,        # Geny via ScraperAPI si SCRAPERAPI_KEY
    "geny_throttling_2_5s": True,            # pause 2-5s avant fetch Geny
    "ai_supervisor_compliance": True,       # garde déterministe + IA optionnelle
    "ai_post_audit_enrich": True,           # audit post-course enrichi IA
    "ai_bounded_repairs_default_off": True, # swaps ticket non auto (AI_SUPERVISOR seul n'influence jamais le ticket)
    "rah90_tolere_3_si_top_marche": True,   # plafond ICP assoupli si top marché
    "rah90_protege_marche_qualite": True,   # choix p_boost dans bande + core protect ; ne sort plus un T1 marché/top PCH

    # --- v1.29.14 (21/09/2026) : RAH-270 signal IA rythme/allure, optionnel ---
    "rah270_ai_optionnel": True,            # AI_QUALITATIVE_SIGNAL=1 requis en plus d'une clé (Groq/Gemini/Anthropic)
    "rah270_ai_borne_pm3": True,            # signal clampé +/-3, double clamp (supervisor.py + pch_final.py)
    "rah270_ai_soumis_rah242": True,        # plafonné en plus par le cap bonus-secondaires <= bonus-primaires
    "rah270_ai_un_appel_par_course": True,  # 1 appel LLM batché, pas un par cheval

    # --- v1.29.15 (21/09/2026) : apprentissage continu + export Hugging Face ---
    "apprentissage_continu_actif": True,     # accumule + réentraîne après chaque audit
    "apprentissage_continu_shadow_only": True,  # ticket_impact reste False, comme ranker_shadow.py
    "hf_export_disponible": True,           # actif seulement si HF_TOKEN + HF_DATASET_REPO renseignés

    # --- v1.29.16 (22/09/2026) : fusion des correctifs walk-forward (port Grok) ---
    "malus_m_plafond_toutes_tranches": True,   # |malus_final| <= 12, port verbatim
    "quota_protect_top_quartile_pboost": False, # v1.29.20: quartile hors noyau
    "poids_attenuation_malus_plat": True,      # port verbatim
    "ai_provider_fallback_chain": True,        # port verbatim (Groq->Gemini->Anthropic si échec)
    "mpa_attenuation_marche_discipline": True, # RETRAVAILLÉ : cf. mpa_reduction_non_cumulative
    "mpa_reduction_non_cumulative": True,      # une seule réduction (la + forte), jamais leur produit

    # --- v1.29.17 (22/09/2026) : cohérence inter-règles (audit sur demande) ---
    "gmo_v_injection_respecte_rah266": True,   # _best_inject priorise les T4 justifiables RAH-266
    "audit_profil_manques_marche": True,       # suivi favori/outsider des manqués, par course + agrégé

    # --- v1.29.18 (22/09/2026, Golden) : gouvernance globale du ticket ---
    "min_12_partants": True,             # VANTAGE_MIN_PARTANTS (défaut 12) -- course rejetée sinon
    "t1t2_verrouillage_double_validation": True,  # marché SEUL ne suffit plus pour le noyau protégé
    "couverture_marche_assouplie_1_sur_3": True,  # 2/3 -> 1/3 (moins guidé par le marché)
    "rah266_enforcement_ticket_final": True,      # tout T3/T4 du ticket, pas seulement les injectés
    "quota_flexible_3_5": True,                   # remplace le 4+4 rigide (T1+T2 et T3+T4 dans [3,5])

    # --- v1.29.19 (22/09/2026) : fusion Grok + note opérationnelle tranches ---
    "market_blend_capped_035": True,        # plafond blend marché 0.50->0.35 (port Grok)
    "internal_validated_riche": True,       # top-quartile/top3-ordre/favori-unanime-seuillé (port Grok, remplace le simple rang médian)
    "forme_boost_pboost": True,             # multiplicateur p_boost soft selon régularité Top5 récente (port Grok)
    "catalog_b_top5_regulier": True,        # B_TOP5_REGULIER / M_FORME_MORTE au catalogue (port Grok)
    "tocard_ok_t3_t4_enrichi": True,        # RAH-266 étendu T3 (0.22) + T4 (0.25) + forme/GRU extrême (port Grok)
    "champ_traitement_uniforme_ge12": True, # suppression bande_prioritaire 10-15 / hors_kpi>=17 (port Grok)
    "t4b_plafond_2": True,                  # max 2 extrêmes 100-300/1 dans le ticket (note 22/09)
    "favori_unanime_malus_sans_forme": True,  # malus ciblé si favori unanime + musique morte (note 22/09)
    "noyau_sans_quartile_elargi": True,      # core = marché validé + top3 qualité
    "pch_saturation_damp_favoris": True,     # p_boost ×0.94 si PCH≥210 et cote<10
    "turfbzh_outsider_boost_t34": True,      # B61/B63 → p_boost ×1.12 sur T3/T4
    "malus_m_plafond_t34_10": True,          # malus M max −10 en T3/T4 (−12 T1/T2)
    "roles_ticket_pivot_value": True,        # PIVOT/SEMI/VALUE/SAUVAGE sur T1-T4
    "forme_top5_discipline_filter": True,   # musique filtrée disc. course
    "discipline_router_selection": True,    # mult soft unique 0.96-1.04
    "drift_sov_in_pboost": True,            # SOV dans p_boost, anti-stack Turf.bzh
    "role_soft_value_fill": True,           # 1 swap VALUE si grand champ sans VALUE
    "forme_top5_filtre_discipline": True,    # musique même disc. que la course
    "quota_officiel_3_5": True,
    "ai_diagnostic_structurel_post": True,   # post-audit: diagnostic + hypothèses
    "ai_journal_hypotheses": True,           # journal leviers structurels (pas de n°)
    "ai_anomalies_execution": True,          # garde déterministe anomalies sources/rôles
    "ai_experiments_batch": True,
    "enrichissement_complementaire_2_7": True,
    "enrich_comp_web_repass": True,              # 2.7: web public + re-pass fiches/valeur
    "enrich_comp_champs_argentan": True,
    "skip_personne_fiches_double_pass": True,   # anti double-fetch jockey/entraîneur 2.2
    "fields_filled_real_delta": True,          # 2.7 compte None→valeur, pas les flags
    "sri_proxy_attenue": True,
    "data_contract_prescoring": True,
    "recul_dist_mapping": True,              # Dist. ligne → recul_m (GNT/trot)
    "fusion_recul_gains_moy": True,          # fusion multi-sources recul/gains_moy/ferrure
    "turfoo_dist_ferrure": True,
    "turfomania_secondary": True,           # source secondaire Turfomania
    "web_search_ddg_2_7": True,             # recherches DDG étape 2.7
    "ai_guide_enrichment": True,
    "noyau_desactive": True,                # plus de CORE_PROTECT
    "roles_desactives": True,               # plus PIVOT/VALUE/SAUVAGE
    "quota_t12_t34_3_5": True,
    "hybrid_select_p1p6": True,             # q_i + contraintes greedy + Σq + axes
    "hybrid_market_blend_light": True,      # marché allégé dans p
    "hybrid_p_boost_clamp": True,
    "ai_multi_model_fallback": True,        # Groq/Gemini modèles de repli
    "ai_key_strip": True,                   # clés API strip spaces/quotes
    "enrich_turfomania_web_2_7": True,
    "capture_boost_v32": True,
    "discipline_detect_v33": True,
    "discipline_modules_v33": True,  # trot/plat/haies/steeple research
              # recul, disc-weights, Harville, mid-outsider
    "favori_top5_stats_2014_2026": True,    # trot 72% plat 59% obstacle ~55%
    "supra_none_odds_guard": True,
    "data_contract_blocks_critical_gaps": True,
    "http_retry_4xx_guard": True,
    "ssrf_source_allowlist": True,
    "deferre_string_normalization": True,
    "source_identity_validation": True,
    "discipline_consensus_filter": True,
    "press_icp_degraded_non_blocking": True,
    "data_contract_context_adaptive": True,
    "targeted_enrichment_context": True,
    "identity_names_guard": True,           # v1.29.40 : noms de chevaux (fusion, PMU, Equidia, Turf.bzh)
    "identity_expected_from_urls": True,    # identité attendue déduite des URLs (retry, R+C sans hippodrome)
    "zoneturf_reunion_from_url": True,      # fin du R1 codé en dur
    "pmu_no_default_r1": True,
    "asof_no_future_leak": True,            # perfs/fenêtres strictement avant le jour J
    "hippodrome_generic_tokens": True,
    "discipline_arbiter_pmu": True,
    "antibot_exemption_geny_only": True,
    "min_2_sources_always": True,
    "plat_handicap_crash_fix": True,        # v1.29.41 : race.chevaux inexistant -> AttributeError
    "poids_champ_derive": True,             # poids_{moyen,min,max}_champ_kg enfin renseignés
    "pboost_units_fix": True,               # mélange probabilité/score + renormalisation
    "pl_inclusion_exact": True,             # DP exacte P(Top5), E[captures] par ticket
    "audit_baselines_dataset": True,        # ticket vs marché vs ordre + jeu de calibration
    "activite_derivee_historique": True,    # nb_courses_30j/12m, distance_habituelle_m
    "ticket_c_ancre_marche": True,          # v1.29.55 : mélange marché + PCH, probabilités Plackett-Luce calibrées (B et C)
    "export_analyse_zip": True,             # v1.29.54 : un zip pour analyser tout l'historique
    "batch_walkforward": True,              # v1.29.53 : lot de courses, file persistante, export CSV
    "ai_rejeu_influence_off": True,
    "audit_unique_run_full_audit": True,
    "musique_lecture_par_discipline": True,  # v1.29.48 : D trot/obstacle/plat, 2 chiffres, Ret, cross
    "musique_zero_annee_corriges": True,    # v1.29.47
    "hf_autosave_restore": True,            # v1.29.46 : sauvegarde HF auto + restauration au démarrage
    "audit_resultats_complets": True,       # v1.29.45 : rang/incident de TOUS les partants
    "ai_post_race_analysis": True,
    "discipline_obstacle_preservee": True,
    "mode_rejeu_marque": True,
    "ai_repair_fields": True,               # v1.29.44 : réparation IA des champs (preuve vérifiée)
    "ai_press_signals": True,
    "data_anomaly_detection": True,
    "ai_misses_analysis": True,
    "ai_race_summary": True,
    "ai_collection_fallback": True,         # v1.29.43 : collecte IA de secours (llm/collection.py)
    "ai_qualitative_llm_optin": True,       # v1.29.43 : signaux IA AI01-AI06 (llm/qualitative.py), AI_QUALITATIVE_LLM=1
    "claude_client_http_no_sdk": True,
    "ticket_b_quotas_par_tranche": True,    # v1.29.42 : 2e ticket (1 par tranche, T1+T2 / T3+T4 dans [3,5])
    "ticket_b_quotas_structure_v156": True,  # v1.29.56→59 : grilles 3221/3311/2331/2222 = a priori souple, DÉSACTIVÉ par défaut (λ=0) depuis le rejeu 55 courses
    "reglages_b_par_portee": True,            # v1.29.67 : B résolu par famille (trot / galop / obstacle) > distance > hippodrome ; audit par portée
    "turfbzh_html_p012": True,                # v1.29.66.5 (déclaré en v1.29.67.1) : Turf.bzh HTML gratuit B65–B74 + P2 ; API payante no-op
    "anti_doublon_prior_race": True,          # v1.29.65.1 (déclaré en v1.29.67.1) : alerte course déjà traitée + taux de capture
    "recalibrage_v68_shadow_min1_melange": True,   # v1.29.68 : sélection « un cheval par tranche + z(ordre)+z(cote) » calculée en shadow pour A/B/C (VANTAGE_SELECT_MIN1_TICKETS pour l'appliquer)
    "recalibrage_v68_plafond_outsiders": True,     # v1.29.68 : plafond de chevaux de rang marché >= 9 (VANTAGE_CAP_OUTSIDERS, défaut inactif)
    "recalibrage_v68_tocard_mult_t123": True,      # v1.29.68 : poids tocard x0,25..1 en T1-T3 (VANTAGE_TOCARD_MULT_T123, défaut 1 = inactif)
    "recalibrage_v68_valeur_pmu_trot_rejeu_zero": True,  # v1.29.68 : valeur PMU du trot ramenée à zéro en REJEU / chrono du jour présent ; courses à venir normales
    "recalibrage_v69_bases_score_propre_shadow": True,   # v1.29.69 : bases (k=2/3) par score propre figé, publiées en shadow (json_output["shadow_v1_29_69"])
    "recalibrage_v69_probas_recalibrees_shadow": True,   # v1.29.69 : probabilités désordre / 5-5 recalibrées (facteurs observé/prédit, appliqués à moitié) en shadow
    "recalibrage_v69_filtre_courses_shadow": True,       # v1.29.69 : signal « plein / réduit » selon la cote du favori (VANTAGE_FILTRE_FAVORI_MAX), publié seulement
    "recalibrage_v69_garde_t1": True,                    # v1.29.69 : garde T1 (rang marché <= 3 jamais écarté) ; shadow pour A, application par VANTAGE_GARDE_T1=A
    "leviers_actives_v69_1": True,                       # v1.29.69.1 : sélection un-par-tranche (A,B), plafond, bases score propre hors trot, probas recalibrées, filtre de courses ACTIFS par défaut
    "fetch_providers_chain": True,            # v1.29.66 : ScraperAPI → Firecrawl → … avec bascule sur quota épuisé
    "ticket_b_laboratoire": True,             # v1.29.65 : B = α 0,75 + α_T3 0,8 + 6 composantes en rangs + classement T3/T4 + entrées pépite ; A et C = v1.29.63
    "ticket_b_differencie": True,             # v1.29.64 : B = marché α 0,75 + GRU renforcé (poids maîtrisé) ; A et C inchangés
    "gru_profils_neutre_renforce": True,      # v1.29.64 : profils GRU (G10, G56, G30, piège, pool, G58-G64) ; défaut neutre = v1.29.63
    "classements_auto_hors_ligne": True,      # v1.29.63 : B11/B12/classements construits seuls depuis le cache du corpus ; noms normalisés
    "corde_cle_reelle": True,                 # v1.29.63 : bonus corde empirique sur la place de corde (numero_autostart), plus sur le n° du cheval
    "diagnostic_donnees": True,               # v1.29.63 : json_output['diagnostic_donnees'] + colonnes diag_* / n_signal_* / equidia_reason de l'export
    "export_donnees_brutes": True,            # v1.29.62 : analyse.zip avec driver, entraîneur, œillères, ferrure/déferrage, stats, bookmakers + couv_*
    "rerank_tranche_candidat": True,          # v1.29.61 : VANTAGE_RERANK_TRANCHE=1 -> T3 par le marché, T4 par PCH+ordre_final+valeur PMU (défaut OFF)
    "alpha_t3_candidat": True,                # v1.29.60 : VANTAGE_BLEND_ALPHA_T3 (défaut = α, neutre) — à valider sur nouveau lot
    "confiance_capture_iic": True,            # v1.29.60 : indicateur informatif (IIC-v2 ≥ 72 = course ouverte)
    "champ_reduit_bases_complements": True,  # v1.29.58 : chaque ticket = 3 bases classées + 5 compléments classés ; désordre / bonus / ordre calculés et audités
    "iic_v2_hybride": True,                  # v1.29.56→57 : signature = 70 % marché + 30 % contexte (règle meneurs retirée)
    "archive_names_lisibles": True,          # v1.29.56→57 : noms d'archives locales AAAA-MM-JJ_RnCm_discipline_hippo_distance
    "gmo_gain_normalized_optin": True,      # GMO_GAIN_NORMALIZED=1 (OFF par défaut)


    "recalibrage_v69_actif": True,  # SRI proxy, B/M confidence, MPA confidence, tocard and outsider caps active
    "recalibrage_v69_shadow_min1_inactif": True,  # Historical v1.29.69 state only
    "recalibrage_v70_min1_tickets_abc_actif": True,  # Minimum one per required tranche, A/B/C
    "recalibrage_v71_t2_rangs_relatifs_actif": True,  # PCH and market ranks computed after full field PCH pass
    "recalibrage_v71_rah242_gru_tactique_cap_actif": True,  # Include positive GRU and tactical secondary contributions
    "recalibrage_v71_gmo_pool_trace_actif": True,  # Per-run admission/exclusion reasons by horse number
    "recalibrage_v71_pmu_provenance_actif": True,  # Source/raw/collection timestamp and consumed trot value
    "fusion_v72_v69_1_grok_v71": True,  # v1.29.72 : fusion de la branche v1.29.69.1 (bases score propre, probas recalibrées, filtre, garde T1, e2e) et de la branche Grok v1.29.71 ; erreurs de code corrigées, rien désactivé
    "recalibrage_v72_tocard_t3_t4_seulement": True,  # v1.29.72 : multiplicateur tocard (x0,75) appliqué à T3 et T4 uniquement (VANTAGE_TOCARD_MULT_T34, alias T123)
            # propose_structural_experiments (batch)
}
