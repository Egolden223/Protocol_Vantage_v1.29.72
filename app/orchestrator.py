"""
orchestrator.py -- Exécute la séquence complète pour une course donnée,
en 100% Python (aucun appel API Anthropic) :
  1. Collecte multi-sources principales (CanalTurf, Turfoo, Zone-Turf, Geny)
  2. ENRICHISSEMENT OBLIGATOIRE — comble les lacunes via sources complémentaires
  2.7 VÉRIFICATION + ENRICHISSEMENT COMPLÉMENTAIRE — inventaire résiduel + 2e vague ciblée
  2.8 RAH-270 IA (optionnel, rythme)
  3. CONTRAT DE DONNÉES — tableau exhaustif champs/sources (pré-scoring)
     (API PMU, fiches, Frequence-Turf, Equidia, Turf.bzh, open-pmu-api)
  3. Modules qualitatifs par règles (app/engine/qualitative_engine.py)
  4. Scoring déterministe (Modules A-P, COMPOSITE, ORDRE_FINAL, IFT)
  5. GMO-V, contraintes dures, ticket P1->R2, sortie JSON

Conçu pour tourner en tâche de fond (FastAPI BackgroundTasks) ; chaque
étape est journalisée en base pour le suivi de progression et l'audit
post-course walk-forward.
"""
from __future__ import annotations
import logging
import os
import traceback
from datetime import datetime
from typing import Optional

from app import db
from app.scraping.router import scrape_race_with_fallback
from app.scraping.enrichment import enrich_chevaux
from app.scraping.base import fetch_html
from app.scraping.frequence_turf import (
    build_urls as ft_build_urls,
    parse_pronostics_presse,
    parse_base_tocard,
    apply_enrichment as apply_frequence_turf_enrichment,
    enrichir_course_frequence_turf,
    frequence_turf_enabled,
)
from app.scraping.stats_quinte import enrichir_course_stats_quinte
from app.engine.ai_rhythm import enrich_race_with_ai_rhythm
from app.scraping.pmu_api import enrich_race_with_pmu_api
from app.scraping.equidia import enrich_race_with_equidia
from app.scraping.turfbzh import enrich_race_with_turfbzh
from app.scraping.enrichment_mandatory import inventaire_lacunes, synthese_couverture, delta_couverture, run_enrichissement_complementaire, inventaire_residuel
from app.engine.qualitative_engine import compute_qualitative_signals_python
from app.engine.race_pipeline import compute_race_scores
from app.engine.discipline_detect import ensure_race_discipline
from app.version import VERSION_RULESET
from app.engine.gmo_v import run_gmo_v
from app.engine.constraints import check_hard_constraints, check_gouvernance
from app.engine.data_contract import compute_rapport_completude
from app.engine.data_contract import evaluate_data_contract
from app.engine.ticket import build_ticket, gamma_log, build_json_output
from app.engine.execution_tracer import ExecutionTracer
from app.models import RaceResult, StageStatus

logger = logging.getLogger("vantage.orchestrator")


def run_pipeline(race_id: str, urls: list, auto_audit: bool = False,
                  discovery_report: Optional[dict] = None) -> None:
    """auto_audit (ajouté le 08/09/2026, pour le mode walk-forward
    historique) : si True, tente automatiquement l'audit post-course
    juste après la fin du pipeline -- utile pour une course PASSÉE dont
    le résultat est déjà disponible, sans avoir à cliquer manuellement
    sur "Audit post-course" ensuite. Un échec de l'audit automatique
    (résultat pas encore publié, course future malgré la demande, etc.)
    ne fait jamais échouer le pipeline lui-même -- juste consigné en
    avertissement, l'audit manuel reste possible ensuite.

    discovery_report (ajouté le 20/09/2026, Golden : le rapport fusionné
    doit tracer TOUTE la chaîne, "de l'identification à l'audit
    post-course") : le résultat de discover_all_sources() (par_source,
    taux_collecte, urls) quand la course vient de /api/races/auto --
    jusqu'ici calculé, renvoyé une fois dans la réponse HTTP de création,
    puis PERDU (jamais rattaché à l'ExecutionReport que le pipeline
    construit). None quand les URLs ont été collées manuellement
    (/api/races) : il n'y a alors pas eu de découverte à tracer, l'étape
    0 le dit explicitement plutôt que de laisser un silence ambigu."""
    tracer = ExecutionTracer(race_id)
    try:
        with tracer.stage("0. Identification -- découverte multi-sources (avant collecte)") as st:
            geny_url_identification: Optional[str] = None
            if discovery_report:
                par_source = discovery_report.get("par_source") or {}
                # Taux effectif hors Geny antibot (20/09/2026, fusionné) :
                # ne pas afficher un taux_collecte trompeur à 100% quand Geny
                # a en réalité été exclu (ignore) pour cause anti-bot plutôt
                # que réellement introuvable.
                sources_utiles = 0
                sources_ok = 0
                geny_antibot = False
                for src, info in par_source.items():
                    if not isinstance(info, dict):
                        continue
                    if src == "geny" and info.get("ignore"):
                        geny_antibot = True
                        continue
                    sources_utiles += 1
                    if info.get("url") or info.get("score"):
                        sources_ok += 1
                taux_effectif = (sources_ok / sources_utiles) if sources_utiles else discovery_report.get("taux_collecte")
                st.details = {
                    "urls_decouvertes": discovery_report.get("urls"),
                    "taux_collecte": discovery_report.get("taux_collecte"),
                    "taux_collecte_effectif": taux_effectif,
                    "geny_antibot": geny_antibot,
                    "detail_par_source": par_source,
                }
                msg_parts = []
                if discovery_report.get("taux_collecte") is not None and discovery_report["taux_collecte"] < 1.0:
                    st.status = StageStatus.WARNING
                    msg_parts.append(
                        f"Taux de collecte à l'identification : {discovery_report['taux_collecte']:.0%} "
                        f"(< 100%, au moins une source n'a pas trouvé la course)."
                    )
                if geny_antibot:
                    st.status = StageStatus.WARNING
                    msg_parts.append(
                        f"Geny exclus (antibot) — taux effectif hors Geny : "
                        f"{(taux_effectif or 0):.0%} ({sources_ok}/{sources_utiles} sources)"
                    )
                if msg_parts:
                    st.message = " ".join(msg_parts)
                # URL de course Geny déjà trouvée ici (si Geny a pu être
                # joint ce jour-là) -- réutilisée en priorité pour les
                # fiches individuelles à l'étape 2.2, SANS refaire de
                # requête Geny : discover_all_sources tente déjà les 4
                # sources à l'identification, que Geny soit ou non retenu
                # comme source de collecte principale.
                geny_url_identification = (par_source.get("geny") or {}).get("url")
            else:
                st.status = StageStatus.SKIPPED
                st.message = "URLs fournies manuellement (/api/races) -- pas de découverte automatique à tracer ici."
                st.details = {"urls_fournies_manuellement": urls}

        # --- Blocs 1+2+3 : collecte INTÉGRALE multi-sources (4 sources principales) ---
        # TOUTES les URLs sont scrapées ; la plus riche devient la base ; les autres
        # fusionnent leurs champs manquants. Puis enrichissement secondaire comble le reste.
        db.update_status(race_id, "COLLECTE_EN_COURS")
        with tracer.stage("1. Collecte (Blocs 1+2+3 -- 4 sources principales, fusion intégrale)") as st:
            # v1.29.40 : identité attendue = demande (si connue) + vote des URLs ;
            # fonctionne donc aussi sur /retry et en mode réunion+course sans hippodrome.
            from app.scraping.identity import construire_identite_attendue
            identite_attendue = construire_identite_attendue(discovery_report, urls)
            expected_hippodrome = identite_attendue.get("hippodrome")
            try:
                race, chevaux, warnings, url_utilisee = scrape_race_with_fallback(
                    urls, expected_hippodrome=expected_hippodrome, expected_identity=identite_attendue,
                )
            except ValueError as _e_py:
                # v1.29.43 : module IA de collecte (app/llm/collection.py) en SECOURS uniquement,
                # quand toutes les sources Python ont échoué.
                from app import config as _cfg
                from app.llm.client import ai_available
                if _cfg.AI_COLLECTION_FALLBACK == "0" or not ai_available():
                    raise
                from app.llm.collection import collect_with_ai_fallback
                logger.warning("Sources Python en échec (%s) -- tentative de collecte IA de secours", str(_e_py)[:200])
                _url0 = next((u for u in urls if u and u.startswith("http")), None)
                if not _url0:
                    raise
                race, chevaux, warnings, url_utilisee = collect_with_ai_fallback(_url0, identite_attendue, urls=urls)
                warnings.append(f"Échec des sources Python : {str(_e_py)[:300]}")
            st.details = {
                "urls_fournies": urls,
                "url_retenue_principale": url_utilisee,
                "urls_complementaires": [u for u in urls if u and u != url_utilisee],
                "liens_sources_collecte": {
                    "primaire": url_utilisee,
                    "toutes": list(urls),
                },
                "identite_attendue": identite_attendue,
                "reunion_course_label": race.reunion_course_label, "date_course": race.date_course,
                "hippodrome": race.hippodrome, "discipline": str(race.discipline),
                "nb_chevaux_trouves": len(chevaux), "nb_avertissements": len(warnings),
                "note_fusion": (
                    "Collecte intégrale : TOUTES les sources fournies sont scrapées. "
                    "La plus riche (score de champs non-vides) devient la base primaire ; "
                    "les autres fusionnent les champs manquants (jamais d'écrasement). "
                    "Ensuite inventaire des lacunes → enrichissement secondaire."
                ),
            }
            if len(chevaux) == 0:
                st.status = StageStatus.ERROR
                st.message = "Aucun cheval extrait -- pipeline interrompu (résultat inexploitable)."
            elif warnings:
                st.status = StageStatus.WARNING
                st.message = f"{len(warnings)} avertissement(s) de collecte (musique/cote manquantes, etc.)"
        if len(chevaux) == 0:
            raise ValueError("Collecte : 0 cheval extrait sur toutes les sources fournies.")

        # v1.29.18 -- Golden (22/09) : cibler uniquement les courses à
        # partants suffisants, minimum configurable (défaut 12). Un champ
        # trop restreint dilue peu le pari (moins de valeur relative à
        # capturer) et fausse plusieurs modules calibrés sur des champs
        # moyens/grands (RAH-90, quota T1-T4, bande prioritaire 10-15).
        MIN_PARTANTS = int(os.environ.get("VANTAGE_MIN_PARTANTS", "12"))
        if len(chevaux) < MIN_PARTANTS:
            db.update_status(race_id, "REJETEE_CHAMP_TROP_PETIT")
            raise ValueError(
                f"Course rejetée : {len(chevaux)} partants < minimum requis "
                f"({MIN_PARTANTS}, VANTAGE_MIN_PARTANTS). Décision Golden du "
                f"22/09/2026 : cibler uniquement les champs à partants suffisants."
            )

        # =====================================================================
        # PHASE ENRICHISSEMENT OBLIGATOIRE (post-collecte 4 sources principales)
        # -----------------------------------------------------------------
        # Les 4 sources principales (CanalTurf, Turfoo, Zone-Turf, Geny) ont
        # fourni le socle partants/cotes. Cette phase EST OBLIGATOIRE : elle
        # recherche et comble systématiquement les données manquantes ou
        # complémentaires sur les sources secondaires :
        #   API PMU · fiches CT/Turfoo/ZT · Frequence-Turf · Equidia ·
        #   Turf.bzh · open-pmu-api (via enrichment)
        # Une absence de données sur une source secondaire = WARNING/SKIP,
        # jamais un court-circuit silencieux de toute la phase.
        # =====================================================================
        db.update_status(race_id, "ENRICHISSEMENT_EN_COURS")

        with tracer.stage(
            "2.0 Enrichissement obligatoire -- inventaire des lacunes (post 4 sources)",
            optionnelle=False,
        ) as st:
            lacunes_avant = inventaire_lacunes(race, chevaux)
            st.details = lacunes_avant
            st.message = (
                f"Lacunes prioritaires: {list(lacunes_avant.get('priorite_haute', {}).keys()) or 'aucune'} — "
                f"sources complémentaires prévues: {len(lacunes_avant.get('sources_complementaires_prevues', []))}"
            )

        # --- 2.1 API PMU (1ère passe, avant fiches) ---
        with tracer.stage(
            "2.1 Enrichissement obligatoire -- API PMU (gains/valeur/poids/deferre)",
            optionnelle=False,
        ) as st:
            pmu_warnings = enrich_race_with_pmu_api(race, chevaux)
            warnings = warnings + [f"[API PMU] {w}" for w in pmu_warnings]
            st.details = {
                "penetrometre": race.penetrometre,
                "chevaux_avec_gains": sum(1 for c in chevaux if c.gains_totaux_eur is not None),
                "chevaux_avec_deferre": sum(1 for c in chevaux if c.deferre is not None),
                "chevaux_avec_victoires": sum(1 for c in chevaux if c.victoires_carriere is not None),
            }
            if any("inaccessible" in w or "inconnus" in w for w in pmu_warnings):
                st.status = StageStatus.WARNING

        # --- 2.2 Fiches individuelles (sources principales en profondeur) ---
        with tracer.stage(
            "2.2 Enrichissement obligatoire -- fiches Geny prioritaires + complément Turfoo/CanalTurf/Zone-Turf (+ open-pmu classements)",
            optionnelle=False,
        ) as st:
            flags_enrichissement = enrich_chevaux(chevaux, race, programme_urls=urls, geny_url=geny_url_identification)
            nb_driver_stats = sum(1 for c in chevaux if c.driver_stats and c.driver_stats.fenetres)
            nb_historique_enrichi = sum(1 for c in chevaux if c.historique_terrain or c.historique_distance)
            nb_gains = sum(1 for c in chevaux if c.gains_totaux_eur is not None)
            from collections import Counter
            # Counter perd l'exception exacte dans les clés FICHE_..._ECHEC(...): <msg>
            # (une par cheval, jamais deux identiques) -- gardé pour la vue
            # d'ensemble, mais complété par la liste brute pour retrouver
            # QUEL cheval a échoué et POURQUOI sans consulter les logs serveur.
            # BUG trouvé le 20/09/2026 sur un vrai rapport d'audit (Golden) :
            # les flags sont maintenant préfixés "#N Nom: TYPE" (voir
            # enrich_chevaux) -- split(": ",1)[0] prenait à tort le PRÉFIXE
            # CHEVAL comme clé au lieu du TYPE de flag, donnant un Counter
            # de noms de chevaux au lieu d'une distribution de flags.
            # maxsplit=2 en plus pour les flags d'échec qui embarquent le
            # texte d'exception après un 2e ": " (sinon chaque échec est
            # unique et le Counter ne peut plus rien agréger).
            def _type_flag(f: str) -> str:
                parts = f.split(": ", 2)
                return parts[1] if len(parts) > 1 else f
            repartition_flags = dict(Counter(_type_flag(f) for f in flags_enrichissement))
            st.details = {
                "geny_url_priorite_utilisee": geny_url_identification,
                "chevaux_avec_driver_stats": f"{nb_driver_stats}/{len(chevaux)}",
                "chevaux_avec_historique_terrain_distance": f"{nb_historique_enrichi}/{len(chevaux)}",
                "chevaux_avec_gains": f"{nb_gains}/{len(chevaux)}",
                "repartition_flags": repartition_flags,
                "flags_bruts_par_cheval": flags_enrichissement,
                "note": "open-pmu-api classements maison injectés via enrichment.enrich_cheval si dispo",
            }
            if nb_driver_stats == 0 and nb_historique_enrichi == 0:
                st.status = StageStatus.WARNING
                st.message = (
                    "Couverture d'enrichissement fiche faible — sources secondaires vont tenter le comblement"
                )

        # --- 2.3 Frequence-Turf ICP ---
        with tracer.stage(
            "2.3 Enrichissement obligatoire -- Frequence-Turf ICP (citations Top5)",
            optionnelle=False,
        ) as st:
            if not frequence_turf_enabled():
                st.status = StageStatus.SKIPPED
                st.message = "Frequence-Turf désactivé (flag / config)"
                st.details = {"enabled": False}
            else:
                try:
                    ft_rapport = enrichir_course_frequence_turf(race, chevaux)
                    st.details = ft_rapport if isinstance(ft_rapport, dict) else {"raw": str(ft_rapport)[:500]}
                    n_icp = sum(1 for c in chevaux if c.icp_global is not None)
                    st.message = f"ICP renseigné: {n_icp}/{len(chevaux)}"
                    if n_icp == 0:
                        st.status = StageStatus.WARNING
                except Exception as e:
                    st.status = StageStatus.WARNING
                    st.message = f"Frequence-Turf: {e}"

        # --- 2.3bis stats-quinte ICP proxy (repli FT, grille anti-favoris) ---
        with tracer.stage(
            "2.3bis Enrichissement obligatoire -- stats-quinte ICP proxy (repli FT)",
            optionnelle=False,
        ) as st:
            try:
                sq_rapport = enrichir_course_stats_quinte(race, chevaux)
                st.details = sq_rapport if isinstance(sq_rapport, dict) else {"raw": str(sq_rapport)[:500]}
                n_icp = sum(1 for c in chevaux if c.icp_global is not None and c.icp_global > 0)
                status = (sq_rapport or {}).get("status", "?")
                n_app = (sq_rapport or {}).get("nb_icp_appliques", 0)
                st.message = f"stats-quinte status={status} appliqués={n_app} ICP total={n_icp}/{len(chevaux)}"
                if status in ("ERROR", "EMPTY", "MISMATCH") and n_app == 0:
                    st.status = StageStatus.WARNING
                elif status == "SKIPPED":
                    st.status = StageStatus.SKIPPED
                # Attache pour le rapport d'exécution
                try:
                    race._stats_quinte_rapport = sq_rapport  # type: ignore[attr-defined]
                except Exception:
                    pass
            except Exception as e:
                st.status = StageStatus.WARNING
                st.message = f"stats-quinte: {e}"

        # --- 2.4 Equidia (programme only) ---
        with tracer.stage(
            "2.4 Enrichissement obligatoire -- Equidia (musique/poids/valeur, programme only)",
            optionnelle=False,
        ) as st:
            try:
                eq_rapport = enrich_race_with_equidia(race, chevaux)
                st.details = eq_rapport if isinstance(eq_rapport, dict) else {"raw": str(eq_rapport)[:500]}
                if isinstance(eq_rapport, dict) and eq_rapport.get("status") in ("SKIP", "EMPTY", "ERROR", "ARRIVEE"):
                    st.status = StageStatus.SKIPPED
                    st.message = str(eq_rapport.get("reason") or eq_rapport.get("status"))
                else:
                    st.message = f"Equidia: {eq_rapport.get('n_filled', 0) if isinstance(eq_rapport, dict) else '?'} champs comblés"
            except Exception as e:
                st.status = StageStatus.WARNING
                st.message = f"Equidia: {e}"

        # --- 2.5 Turf.bzh IA / ELO ---
        with tracer.stage(
            "2.5 Enrichissement obligatoire -- Turf.bzh (IA Gagnant + ELO, bonus plafonnés)",
            optionnelle=False,
        ) as st:
            try:
                bzh_rapport = enrich_race_with_turfbzh(race, chevaux)
                st.details = bzh_rapport if isinstance(bzh_rapport, dict) else {"raw": str(bzh_rapport)[:500]}
                if isinstance(bzh_rapport, dict) and bzh_rapport.get("status") in ("SKIP", "EMPTY", "ERROR"):
                    st.status = StageStatus.SKIPPED
                    st.message = str(bzh_rapport.get("reason") or bzh_rapport.get("status"))
                else:
                    st.message = (
                        f"Turf.bzh: {bzh_rapport.get('n_filled', 0) if isinstance(bzh_rapport, dict) else '?'} champs, "
                        f"{bzh_rapport.get('n_bonus', 0) if isinstance(bzh_rapport, dict) else '?'} bonus IA/ELO"
                    )
            except Exception as e:
                st.status = StageStatus.WARNING
                st.message = f"Turf.bzh: {e}"

        # --- 2.6 Re-pass API PMU + synthèse couverture ---
        with tracer.stage(
            "2.6 Enrichissement obligatoire -- re-pass PMU + synthèse couverture",
            optionnelle=False,
        ) as st:
            pmu_warnings = enrich_race_with_pmu_api(race, chevaux)
            warnings = warnings + [f"[API PMU 2e passe] {w}" for w in pmu_warnings]
            couverture = synthese_couverture(race, chevaux)
            delta = delta_couverture(lacunes_avant, couverture)
            st.details = {
                "penetrometre": race.penetrometre,
                "meteo_temp_c": getattr(race, "meteo_temp_c", None),
                "couverture": couverture,
                "delta_depuis_inventaire": delta,
                "chevaux_avec_valeur_pmu": sum(1 for c in chevaux if c.valeur_pmu is not None),
                "chevaux_avec_gains": sum(1 for c in chevaux if c.gains_totaux_eur is not None),
            }
            st.message = (
                f"Complétude {couverture.get('score_completude_global', '?')} — "
                f"{delta.get('total_comble', 0)} cases comblées depuis inventaire"
            )
            # Garde-fou lacunes prioritaires (20/09/2026, fusionné)
            n = max(len(chevaux), 1)
            n_sans_valeur = sum(1 for c in chevaux if c.valeur_pmu is None or c.valeur_pmu <= 0)
            n_sans_poids = sum(1 for c in chevaux if c.poids_actuel_kg is None)
            ratio_valeur = n_sans_valeur / n
            ratio_poids = n_sans_poids / n
            st.details["lacunes_critiques"] = {
                "sans_valeur_pmu": n_sans_valeur,
                "sans_poids": n_sans_poids,
                "ratio_valeur": round(ratio_valeur, 3),
                "ratio_poids": round(ratio_poids, 3),
            }
            if ratio_valeur > 0.30 or ratio_poids > 0.30:
                st.status = StageStatus.WARNING
                st.message += (
                    f" — LACUNE_CRITIQUE: valeur_pmu manquante {n_sans_valeur}/{n}, "
                    f"poids manquant {n_sans_poids}/{n} (seuils >30%)"
                )
                warnings.append(
                    f"LACUNE_CRITIQUE_VALEUR_POIDS valeur={n_sans_valeur}/{n} poids={n_sans_poids}/{n}"
                )
            if "reunion/course ou date_course inconnus" in " ".join(pmu_warnings):
                st.status = StageStatus.WARNING
            elif any("inaccessible" in w for w in pmu_warnings):
                st.status = StageStatus.WARNING

        # --- 2.7 Vérification + enrichissement COMPLÉMENTAIRE (v1.29.23) ---
        # Après la vague obligatoire : inventaire résiduel, puis seconde vague
        # ciblée (sources prioritaires → secondaires → web public domaines connus).
        with tracer.stage(
            "2.7 Vérification + enrichissement complémentaire (lacunes résiduelles)",
            optionnelle=False,
        ) as st:
            try:
                residuel = inventaire_residuel(race, chevaux)
                rapport_comp = run_enrichissement_complementaire(race, chevaux)
                st.details = {
                    "residuel_nb_cibles": residuel.get("nb_cibles"),
                    "residuel_priorite_haute": residuel.get("priorite_haute"),
                    "complementaire": {
                        "status": rapport_comp.get("status"),
                        "message": rapport_comp.get("message"),
                        "delta": rapport_comp.get("delta"),
                        "passes": {
                            k: {
                                "status": (v or {}).get("status"),
                                "fields_filled": (v or {}).get("fields_filled"),
                            }
                            for k, v in (rapport_comp.get("passes") or {}).items()
                        },
                        "inventaire_apres_score": (rapport_comp.get("inventaire_apres") or {}).get(
                            "score_completude_global"
                        ),
                    },
                }
                st.message = rapport_comp.get("message") or rapport_comp.get("status", "?")
                if rapport_comp.get("status") == "SKIPPED_COMPLET":
                    st.status = StageStatus.SKIPPED
                elif rapport_comp.get("status") == "OK":
                    delta_tot = (rapport_comp.get("delta") or {}).get("total_comble") or 0
                    if delta_tot == 0 and (residuel.get("nb_cibles") or 0) > 0:
                        st.status = StageStatus.WARNING
                        st.message += " — lacunes persistantes après vague complémentaire"
                else:
                    st.status = StageStatus.WARNING
                # Mettre à jour couverture globale pour les étapes suivantes
                try:
                    couverture = synthese_couverture(race, chevaux)
                except Exception:
                    pass
            except Exception as e:
                st.status = StageStatus.WARNING
                st.message = f"Enrichissement complémentaire non bloquant: {e}"
                st.details = {"error": str(e)[:300]}

        # --- 2.8 RAH-270 IA -- signal rythme/allure optionnel (v1.29.14) ---
        # Désactivé par défaut (AI_QUALITATIVE_SIGNAL=0) -- SKIPPED explicite
        # dans ce cas, comportement 100% déterministe inchangé. Un seul
        # appel LLM pour toute la course. N'échoue jamais le pipeline.
        with tracer.stage(
            "2.8 Enrichissement optionnel -- RAH-270 IA (signal rythme/allure, borné +/-3)",
            optionnelle=True,
        ) as st:
            try:
                ai_flags = enrich_race_with_ai_rhythm(chevaux)
                st.details = {"flags": ai_flags}
                st.message = "; ".join(ai_flags)
                if any(f.startswith("RAH270_AI_DESACTIVE") for f in ai_flags):
                    st.status = StageStatus.SKIPPED
                elif any(f.startswith("RAH270_AI_ECHEC") or f.startswith("RAH270_AI_INDISPONIBLE") for f in ai_flags):
                    st.status = StageStatus.WARNING
                elif any(f.startswith("RAH270_AI_AUCUN_COMMENTAIRE") for f in ai_flags):
                    st.status = StageStatus.SKIPPED
            except Exception as e:
                # Garde-fou ultime : même une exception inattendue ici ne
                # doit jamais bloquer la course.
                st.status = StageStatus.WARNING
                st.message = f"RAH270 IA: exception inattendue non bloquante: {e}"


        # Registre des liens sources (collecte + enrichissement) pour rapports
        sources_liens = {
            "collecte": {
                "urls_fournies": list(urls),
                "url_primaire": url_utilisee,
                "urls_complementaires": [u for u in urls if u and u != url_utilisee],
            },
            "enrichissement": {},
            "note": "Liens exacts utilisés pour cette course (collecte multi-sources + enrichissement obligatoire).",
        }
        # Extraire URLs depuis les détails des étapes d'enrichissement déjà tracées
        for et in tracer.report.etapes:
            det = et.details or {}
            nom = et.nom or ""
            if "Frequence-Turf" in nom:
                sources_liens["enrichissement"]["frequence_turf"] = {
                    "urls": det.get("urls"),
                    "urls_tentees": det.get("urls_tentees"),
                    "status": et.status.value if hasattr(et.status, "value") else str(et.status),
                }
            if "Equidia" in nom:
                sources_liens["enrichissement"]["equidia"] = {
                    "url": det.get("url"),
                    "status": det.get("status") or (et.status.value if hasattr(et.status, "value") else str(et.status)),
                    "reason": det.get("reason") or (str(et.message)[:160] if getattr(et, "message", None) else None),   # v1.29.63
                    "n_filled": det.get("n_filled"),
                }
            if "Turf.bzh" in nom or "Turf.bzh" in nom:
                sources_liens["enrichissement"]["turf_bzh"] = {
                    "url": det.get("url"),
                    "status": det.get("status") or (et.status.value if hasattr(et.status, "value") else str(et.status)),
                    "reason": det.get("reason") or (str(et.message)[:160] if getattr(et, "message", None) else None),   # v1.29.63
                }
            if "API PMU" in nom and "2.1" in nom:
                sources_liens["enrichissement"]["api_pmu"] = {
                    "note": "API officielle PMU (gains/valeur/poids)",
                    "status": et.status.value if hasattr(et.status, "value") else str(et.status),
                }
            if "fiches" in nom.lower() or "2.2" in nom:
                fiche_urls = sorted({c.fiche_url for c in chevaux if getattr(c, "fiche_url", None)})[:30]
                sources_liens["enrichissement"]["fiches_chevaux"] = {
                    "nb": len([c for c in chevaux if getattr(c, "fiche_url", None)]),
                    "exemples_urls": fiche_urls[:10],
                }

        tracer.report.sources_liens = sources_liens
        tracer._persist()

        db.save_stage_collecte(race_id, {
            "race": race.model_dump(mode="json"),
            "chevaux": [c.model_dump(mode="json") for c in chevaux],
            "sources": list(urls),
            "url_primaire": url_utilisee,
            "sources_liens": sources_liens,
            "warnings": warnings,
        })

        # --- Modules qualitatifs (prépare Bloc 5 + Bloc 7bis SUPRA) ---
        db.update_status(race_id, "ANALYSE_QUALITATIVE_EN_COURS")

        # --- v1.29.45 : mode d'exécution (course déjà courue = REJEU, pas un test pré-course) ---
        from app.scraping.identity import est_rejeu as _est_rejeu
        mode_execution = "REJEU" if _est_rejeu(race.date_course) else "PRE_COURSE"
        if mode_execution == "REJEU":
            warnings.append("MODE_REJEU: course déjà courue -- cotes finales, cumuls des fiches (courses/victoires/gains) et "
                            "pages Equidia/Turf.bzh peuvent refléter l'après-course ; résultat NON comparable à un test pré-course.")
        # --- v1.29.68 : valeur PMU du trot = chrono du jour déguisé (fuite) -> ramenée à zéro en REJEU / chrono du jour présent ; courses à venir : normal ---
        valeur_pmu_attenuation: dict = {"actif": False}
        try:
            from app.engine.common import attenuer_valeur_pmu_trot as _att_vp
            valeur_pmu_attenuation = _att_vp(chevaux, race.discipline, mode_execution)
            if valeur_pmu_attenuation.get("actif"):
                _lib = "valeur PMU ramenée à zéro (traitée comme absente)" if valeur_pmu_attenuation.get("mode") == "zero" else f"valeur PMU ramenée vers la moyenne (x{valeur_pmu_attenuation['mult']:g})"
                warnings.append(f"VALEUR_PMU_TROT_NEUTRALISEE: {_lib} ({valeur_pmu_attenuation['raison']}) -- "
                                "fuite du chrono du jour ; SRI/NRC reviennent au repli par les gains, M09/M22 inactifs. Courses à venir : traitement normal.")
        except Exception as _eatt:  # noqa: BLE001
            logger.info("Atténuation valeur PMU trot indisponible: %s", _eatt)

        # --- 2.8 (v1.29.44) Contrôle de cohérence des données + réparation IA des champs manquants/suspects ---
        anomalies_donnees: list = []
        reparation_ia: dict = {"appele": False}
        ia_qual_info: dict = {"active": False}
        with tracer.stage("2.9 Contrôle des données (anomalies) + réparation IA des champs manquants (preuve vérifiée)",
                          optionnelle=True) as st:
            from app.llm.tasks import detect_anomalies, repair_fields
            from app.llm.client import ai_available as _ai_ok
            from app import config as _cfg28
            anomalies_donnees = detect_anomalies(race, chevaux)
            _rejeu_bloque = (mode_execution == "REJEU" and _cfg28.AI_REJEU_INFLUENCE != "1")
            if _rejeu_bloque:
                warnings.append("IA_INFLUENCE_DESACTIVEE_EN_REJEU: réparation IA des champs non appliquée (les pages d'une course déjà "
                                "courue contiennent l'après-course) -- AI_REJEU_INFLUENCE=1 pour forcer.")
            if _cfg28.AI_REPAIR != "0" and _ai_ok() and not _rejeu_bloque:
                try:
                    reparation_ia = repair_fields(race, chevaux, urls, anomalies=anomalies_donnees)
                except Exception as _e_rep:  # l'IA ne doit jamais faire échouer l'analyse
                    reparation_ia = {"appele": False, "erreur": str(_e_rep)[:200]}
                if reparation_ia.get("remplis") or reparation_ia.get("corriges"):
                    anomalies_donnees = detect_anomalies(race, chevaux)      # recontrôle après réparation
            for a_ in [x for x in anomalies_donnees if x["severite"] in ("ERREUR", "ALERTE")][:12]:
                warnings.append(f"ANOMALIE_DONNEE [{a_['severite']}] #{a_['numero']} {a_['champ']}: {a_['detail']}")
                for c_ in chevaux:
                    if c_.numero == a_["numero"] and f"DONNEE_SUSPECTE:{a_['champ']}" not in c_.flags:
                        c_.flags.append(f"DONNEE_SUSPECTE:{a_['champ']}")
            st.details = {
                "nb_anomalies": len(anomalies_donnees),
                "erreurs": sum(1 for x in anomalies_donnees if x["severite"] == "ERREUR"),
                "alertes": sum(1 for x in anomalies_donnees if x["severite"] == "ALERTE"),
                "anomalies": anomalies_donnees[:25],
                "reparation_ia": {k: (v[:25] if isinstance(v, list) else v) for k, v in reparation_ia.items()},
            }

        # --- 3. Contrat de données exhaustif (post-enrichissement, pré-scoring) ---
        contrat = {}
        with tracer.stage(
            "3. Contrat de données -- vérification exhaustive champs/sources (pré-scoring)",
            optionnelle=False,
        ) as st:
            try:
                contrat = evaluate_data_contract(race, chevaux)
                st.details = {
                    "verdict": contrat.get("verdict"),
                    "score_completude_global": contrat.get("score_completude_global"),
                    "score_completude_critique": contrat.get("score_completude_critique"),
                    "nb_lacunes_critiques": contrat.get("nb_lacunes_critiques"),
                    "nb_lacunes_fortes": contrat.get("nb_lacunes_fortes"),
                    "lacunes_critiques": contrat.get("lacunes_critiques"),
                    "lacunes_fortes": contrat.get("lacunes_fortes"),
                    "resume_par_cible": contrat.get("resume_par_cible"),
                    # tableau complet (peut être long) — conservé pour audit
                    "tableau": contrat.get("tableau"),
                    "note": contrat.get("note"),
                }
                st.message = (
                    f"{contrat.get('verdict')} — score global {contrat.get('score_completude_global')} "
                    f"/ critique {contrat.get('score_completude_critique')} — "
                    f"lacunes critiques={contrat.get('nb_lacunes_critiques')} "
                    f"fortes={contrat.get('nb_lacunes_fortes')}"
                )
                if contrat.get("verdict") == "LACUNES_CRITIQUES":
                    st.status = StageStatus.WARNING
                elif contrat.get("verdict") == "LACUNES_FORTES":
                    st.status = StageStatus.WARNING
                # Expose pour json_output / audit
                try:
                    race._data_contract = contrat  # type: ignore[attr-defined]
                except Exception:
                    pass
            except Exception as e:
                st.status = StageStatus.WARNING
                st.message = f"Contrat de données: {e}"
                st.details = {"error": str(e)[:300]}

        # Un ticket certifié ne doit jamais être produit avec des lacunes
        # critiques connues. On termine avec un statut métier explicite,
        # distinct d'une erreur logicielle, et on conserve le rapport.
        if not contrat or contrat.get("verdict") == "LACUNES_CRITIQUES":
            db.update_status(
                race_id,
                "REJETEE_DONNEES_INSUFFISANTES",
                error=(
                    "Course rejetée avant scoring : contrat absent ou "
                    f"{contrat.get('nb_lacunes_critiques', 'inconnu')} lacune(s) critique(s)."
                ),
            )
            tracer.finish("REJETEE_DONNEES_INSUFFISANTES")
            return

        with tracer.stage("4. Analyse qualitative -- signaux B/M/GAMMA + SUPRA approx. (prépare Blocs 5 et 7bis)") as st:
            qualitatifs = compute_qualitative_signals_python(race, chevaux)
            # v1.29.43 : couche qualitative IA (app/llm/qualitative.py), opt-in AI_QUALITATIVE_LLM=1.
            # Additive et bornée (+/- AI_QUALITATIVE_CAP_PCH par cheval) ; Python reste prioritaire.
            try:
                from app import config as _cfg
                from app.llm.client import ai_available
                if mode_execution == "REJEU" and _cfg.AI_REJEU_INFLUENCE != "1":
                    ia_qual_info = {"active": False, "raison": "désactivée en REJEU (pages contenant l'après-course) -- AI_REJEU_INFLUENCE=1 pour forcer"}
                elif _cfg.AI_QUALITATIVE_LLM == "1" and ai_available():
                    from app.llm.client import LLMClient
                    from app.llm.qualitative import compute_qualitative_signals, merge_ai_qualitative
                    _client_q = LLMClient(timeout=90)
                    _ai_q = compute_qualitative_signals(race, chevaux, _client_q)
                    # v1.29.44 : + pronostics/presse (outsider signalé / déconseillé), mêmes plafonds
                    try:
                        from app.llm.qualitative import compute_press_signals
                        from app.llm.tasks import get_pages
                        _press = compute_press_signals(race, chevaux, get_pages(urls), _client_q)
                        for _a, _p in zip(_ai_q, _press):
                            _a.signaux_catalogue.extend(_p.signaux_catalogue)
                            _a.flags.extend(_p.flags)
                    except Exception as _e_pr:
                        logger.warning("Lecture presse IA indisponible: %s", _e_pr)
                    _fl = merge_ai_qualitative(qualitatifs, _ai_q)
                    ia_qual_info = {"active": True, "signaux_ajoutes": sum(
                        1 for q in qualitatifs for f in q.flags if f.startswith("IA_QUALITATIVE:")), "notes": _fl}
            except Exception as _e_ia:  # l'IA ne doit jamais faire échouer l'analyse
                ia_qual_info = {"active": False, "erreur": str(_e_ia)[:200]}
                logger.warning("Couche qualitative IA indisponible: %s", _e_ia)
            nb_signaux_moyen = round(sum(len(q.signaux_catalogue) for q in qualitatifs) / max(len(qualitatifs), 1), 1)
            st.details = {
                "nb_chevaux_analyses": len(qualitatifs),
                "ia_qualitative": ia_qual_info,
                "signaux_catalogue_par_cheval_moyenne": nb_signaux_moyen,
                "flags_non_implemente": qualitatifs[0].flags if qualitatifs else [],
            }
            if nb_signaux_moyen == 0:
                st.status = StageStatus.ERROR
                st.message = "0 signal catalogue calculé en moyenne -- résultat suspect, à vérifier avant de faire confiance au ticket."

        # --- Blocs 5+7 : scoring déterministe. Fusionnés dans le code
        # (race_pipeline.py) depuis une session antérieure, pour une
        # raison structurelle et non une simplification arbitraire :
        # OVERBET (Bloc 5) a besoin d'ORDRE_SCORE (Bloc 7) qui a besoin de
        # COMPOSITE (Bloc 7) qui a besoin de PCH (Bloc 5) -- dépendance
        # circulaire que le protocole, écrit pour une exécution linéaire
        # bloc par bloc, ne résout pas explicitement. Le code la résout
        # en 2 passes (cf. docstring de race_pipeline.py). Séparer ça
        # artificiellement en 2 étapes ici donnerait une fausse
        # impression de séquentialité qui ne correspond pas à comment le
        # calcul tourne réellement.
        db.update_status(race_id, "SCORING_EN_COURS")
        with tracer.stage("5. Scoring déterministe -- Blocs 5+7 fusionnés (PCH_FINAL + Composite/Ordre)") as st:
            try:
                ensure_race_discipline(race)
            except Exception:
                pass
            horses = compute_race_scores(race, chevaux, qualitatifs)
            pch_values = [h.breakdown.pch_final for h in horses if h.breakdown and h.breakdown.pch_final is not None]
            # Détail intégral par cheval (demandé par Golden le 20/09/2026,
            # explicitement "tous les modules, indices, catalogues... pour
            # faciliter la détection des failles"). breakdown et synthesis
            # existent déjà en mémoire avec ~40 champs chacun (un par
            # module/indice PCH + catalogue RAH) -- jusqu'ici seuls
            # pch_final_min/max étaient exportés dans le rapport, tout le
            # reste n'était visible qu'en re-scorant la course en debug.
            # cheval lui-même n'est PAS dupliqué ici (déjà tracé à l'étape
            # Collecte) -- seulement numero/nom pour identifier la ligne.
            detail_par_cheval = [
                {
                    "numero": h.cheval.numero,
                    "nom": h.cheval.nom,
                    "breakdown": h.breakdown.model_dump(mode="json") if h.breakdown else None,
                    "synthesis": h.synthesis.model_dump(mode="json") if h.synthesis else None,
                }
                for h in horses
            ]
            st.details = {
                "nb_chevaux_scores": len(horses),
                "pch_final_min": min(pch_values) if pch_values else None,
                "pch_final_max": max(pch_values) if pch_values else None,
                "note_fusion": "Blocs 5 et 7 entrelacés en 2 passes dans race_pipeline.py pour "
                               "résoudre une dépendance circulaire OVERBET<->COMPOSITE -- pas "
                               "séparables sans fausser la représentation du calcul réel.",
                "detail_par_cheval": detail_par_cheval,
            }
            if len(set(round(v, 3) for v in pch_values)) <= 1 and len(pch_values) > 1:
                st.status = StageStatus.WARNING
                st.message = "Tous les PCH_FINAL sont identiques -- suspect (perte de discrimination), à vérifier."

        # --- Bloc 4 : rapport de complétude (TAUX_LEGACY, IFT_COURSE_BASE).
        # Absent du moteur jusqu'au 05/08/2026 -- ajouté ici, APRÈS le
        # scoring plutôt qu'avant comme l'ordre linéaire du protocole le
        # suggère : IFT_COURSE_BASE agrège les IFT par cheval, eux-mêmes
        # calculés en Bloc 5. TAUX_LEGACY seul serait calculable avant,
        # mais je préfère un rapport de complétude unique et cohérent
        # plutôt que de le scinder artificiellement en 2 étapes.
        # Reporting SEUL, décision explicite du 04/08/2026 : Phase B
        # reste toujours activée quel que soit le taux (écart assumé au
        # mécanisme de dégradation du protocole source, cf. completude.py).
        with tracer.stage("4bis. Rapport de complétude -- Bloc 4 (TAUX_LEGACY, IFT_COURSE_BASE)") as st:
            rapport_completude = compute_rapport_completude(chevaux, horses)
            st.details = {
                "taux_legacy": rapport_completude["taux_legacy"],
                "seuil_protocole_franchi": rapport_completude["seuil_protocole_franchi"],
                "ift_course_base": rapport_completude["ift_course_base"],
                "phase_b_neutralisee": rapport_completude["phase_b_neutralisee"],
            }
            if rapport_completude["taux_legacy"] >= 0.60:
                st.status = StageStatus.WARNING
                st.message = ("TAUX_LEGACY >= 0,60 -- normalement Phase B neutralisée par le protocole "
                              "source ; reste activée ici par décision explicite (voir 'note' du détail).")
                st.details["note"] = rapport_completude["note"]

        # --- Bloc 6 : gouvernance (RAH175/176/191/195). Absent du moteur
        # jusqu'au 05/08/2026 -- porte sur le champ entier, pas le ticket. ---
        db.update_status(race_id, "TICKET_EN_COURS")
        with tracer.stage("6. Gouvernance -- Bloc 6 (RAH175/176/191/195)") as st:
            gouvernance = check_gouvernance(horses)
            nb_fail_gouv = sum(1 for r in gouvernance if r["status"] == "FAIL")
            st.details = {"regles": gouvernance}
            if nb_fail_gouv > 0:
                st.status = StageStatus.ERROR
                st.message = f"{nb_fail_gouv} règle(s) de gouvernance en échec -- ne devrait jamais arriver (cap déjà appliqué en amont)."

        # --- Bloc 8 : GMO-V ---
        with tracer.stage("7. GMO-V -- Bloc 8 (construction du pool élargi + sélection)") as st:
            gmo = run_gmo_v(race, horses, qualitatifs)
            st.details = {
                "taille_pool_elargi": len(gmo["pool_elargi"]), "taille_selection": len(gmo["selection"]),
                "p_top5_in_ticket": gmo.get("p_top5_in_ticket"), "statut_couverture": gmo.get("statut_couverture"),
                "captures_attendues": gmo.get("captures_attendues"),
                "pi_top5_modele": gmo.get("pi_top5_modele"),
                "p_boost_preclamp": gmo.get("p_boost_preclamp"), "p_boost": gmo.get("p_boost"),
                "flags": gmo.get("flags", []),
                "roles_ticket": {},  # retired
                "roles_report": {"status": "DISABLED"},
            }
            if len(gmo["selection"]) != 8:
                st.status = StageStatus.WARNING
                st.message = f"Sélection à {len(gmo['selection'])} chevaux (8 attendus en désordre) -- à vérifier."

        # --- Bloc 9 : contraintes dures ---
        # v1.29.10 : FAIL = bloquant checklist ; WARN = assoupli (noyau) ;
        # INFO / PASS / NON_APPLICABLE = non comptés en échec.
        with tracer.stage("8. Contraintes dures -- Bloc 9 (validation GMO-V)") as st:
            report = check_hard_constraints(
                race, horses, gmo["selection"],
                roles_report=None,
            )
            nb_fail = sum(1 for r in report if r["status"] == "FAIL")
            nb_warn = sum(1 for r in report if r["status"] == "WARN")
            st.details = {
                "nb_contraintes": len(report),
                "nb_echecs": nb_fail,
                "nb_avertissements_contraintes": nb_warn,
                "toutes_les_contraintes": report,
                "contraintes_en_echec": [r for r in report if r["status"] == "FAIL"],
                "contraintes_en_warn": [r for r in report if r["status"] == "WARN"],
                "hierarchie": "noyau > marché ≥2/3 > quota 4+4 > RAH-90",
            }
            if nb_fail > 0:
                st.status = StageStatus.WARNING
                st.message = (
                    f"{nb_fail} contrainte(s) FAIL"
                    + (f", {nb_warn} WARN" if nb_warn else "")
                    + " -- ticket livré 'AVEC RÉSERVES'."
                )
            elif nb_warn > 0:
                st.status = StageStatus.WARNING
                st.message = (
                    f"{nb_warn} contrainte(s) en WARN (assouplies par hiérarchie noyau) "
                    "-- ticket livré OK avec réserves documentées."
                )

        compliance = None
        ai_supervision = None
        # --- Bloc 9bis : garde conformité + supervision IA (v1.29.13) ---
        with tracer.stage("8b. Garde conformité protocole + supervision IA") as st:
            compliance = None
            ai_supervision = None
            try:
                from app.engine.compliance_guard import run_compliance_guard
                from app.version import FUSION_FLAGS
                compliance = run_compliance_guard(
                    race, horses, gmo["selection"],
                    gmo_flags=gmo.get("flags") or [],
                    constraints_report=report,
                    version_flags=FUSION_FLAGS,
                )
                ticket_sum = []
                roles_map = {}  # roles retired
                for i in gmo["selection"]:
                    h = horses[i]
                    ticket_sum.append({
                        "numero": h.cheval.numero,
                        "nom": h.cheval.nom,
                        "tranche": h.synthesis.tranche.value if h.synthesis and h.synthesis.tranche else None,
                        "role": None,
                        "pch": round(h.breakdown.pch_final, 1) if h.breakdown else None,
                        "cote": h.cheval.cote_avant_course or h.cheval.cote_matin,
                        "icp": h.cheval.icp_global,
                    })
                race_sum = {
                    "hippodrome": race.hippodrome,
                    "discipline": getattr(race.discipline, "value", str(race.discipline)),
                    "partants": len(horses),
                }
                from app.llm.supervisor import supervise_pre_ticket, diagnose_execution_anomalies
                ai_supervision = supervise_pre_ticket(
                    compliance, gmo.get("flags") or [], ticket_sum, race_sum,
                )
                anomalies = diagnose_execution_anomalies(
                    gmo_flags=gmo.get("flags") or [],
                    roles_report={},
                    coverage={},
                    sources_warnings=[],
                )
                if isinstance(ai_supervision, dict):
                    ai_supervision["anomalies_execution"] = anomalies
                st.details = {
                    "compliance": compliance,
                    "anomalies_execution": anomalies,
                    "supervision_ia": {
                        k: ai_supervision.get(k)
                        for k in (
                            "compliance_verdict", "synthese", "actions_proposees",
                            "actions_appliquees", "ai", "risques_protocole", "confiance",
                            "anomalies_execution",
                        )
                        if k in ai_supervision
                    },
                }
                v = compliance.get("verdict")
                if v == "NON_CONFORME":
                    st.status = StageStatus.WARNING
                    st.message = f"Conformité {v} ({compliance.get('nb_fail')} FAIL)"
                elif v == "CONFORME_AVEC_RESERVES":
                    st.status = StageStatus.WARNING
                    st.message = f"Conformité avec réserves ({compliance.get('nb_warn')} WARN)"
                else:
                    st.message = f"Conformité {v}"
                    if ai_supervision.get("ai", {}).get("status") == "OK":
                        st.message += f" — IA {ai_supervision['ai'].get('provider')}"
                    elif ai_supervision.get("ai", {}).get("status") in (
                        "SKIPPED_NO_KEY", "DISABLED",
                    ):
                        st.message += " — IA inactive (pas de clé / désactivée)"
            except Exception as _e:
                st.status = StageStatus.WARNING
                st.message = f"Garde/IA erreur non bloquante: {_e}"
                st.details = {"error": str(_e)[:300]}
                compliance = None
                ai_supervision = None

        # --- Bloc 11 : ticket final ---
        with tracer.stage("9. Construction du ticket -- Bloc 11 (Réorganisation P1->R2)") as st:
            _gmo_selection_initiale = list(gmo["selection"])
            _v68: dict = {}          # v1.29.68 : sélections alternatives (shadow) + application éventuelle (drapeaux par ticket)
            try:
                from app.engine.ticket_quotas import appliquer_v68 as _ap68
                _v68["A"] = _ap68(horses, "A", gmo["selection"])
                if _v68["A"]["appliquee"]:
                    gmo["selection_avant_v68"] = list(gmo["selection"])
                    gmo["selection"] = list(_v68["A"]["selection"])
            except Exception as _e68a:  # noqa: BLE001
                logger.info("Recalibrage v1.29.68 (A) indisponible: %s", _e68a)
            ticket = build_ticket(horses, gmo["selection"], roles_map={})
            all_pass = all(r["status"] in ("PASS", "NON_APPLICABLE", "INFO", "WARN") for r in report)
            if compliance and compliance.get("verdict") == "NON_CONFORME":
                all_pass = False
            st.details = {"nb_slots_ticket": len(ticket)}
            # --- Tickets B et C (v1.29.42 / v1.29.55) : probabilité = MÉLANGE MARCHÉ + PCH (calibrée, validée hors échantillon) ---
            ticket_b, quotas_info = [], None
            ticket_c, ancre_info = [], None
            horses_b, _w_b = None, None          # v1.29.64 : univers du ticket B (marché α=0,75 + GRU renforcé)
            try:
                from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities
                _pi = blend_probabilities(horses)
                _pi_moteur = gmo.get("pi_top5_modele")
                # B (v1.29.57) : probabilités mélange marché/PCH + grille discipline × signature (IIC-v2) en a priori souple,
                # T1+T2 et T3+T4 dans [3,5], au moins un cheval par famille T1/T2/T3/T4 quand elle existe
                # v1.29.64 : B ne doublonnait C que par construction (même mélange, 40 % de sélections identiques, 7,4 chevaux communs sur 8,
                # couverture ajoutée +0,04 sur 55 courses). B devient un ticket DIFFÉRENCIÉ : poids du marché α = 0,75 (VANTAGE_B_ALPHA ; C et A
                # inchangés) ET renforcements GRU à poids maîtrisé portés par le PCH (profil « renforcé »). Rejeu 55 courses : B ≈ 4,00 (bornes [3;5] sans minimum par
                # famille ; 3,82 avec « une par famille »), identique à C dans 24 % des courses (avant : 40 %), recouvrement 6,9/8, couverture C∪B 4,29.
                from app.engine.ticket_quotas import blend_weights, entrees_pepite, _cle as _cle_tq, GROUPES as _GROUPES_TQ
                from app.engine.pl_inclusion import inclusion_probs
                from app.engine.gru_signals import renforcer_horses
                from app.engine.gru_catalog import reglages_b_pour
                _rg = reglages_b_pour(race)               # v1.29.67 : réglages par portée — famille (trot / galop / obstacle) > distance > hippodrome
                _rv = _rg["valeurs"]
                _alpha_b = float(_rv["alpha"])
                _alpha_t3_b = _rv["alpha_t3"]             # None = identique à alpha
                _biais_corde = None
                if int(_rv["corde_actif"]):               # corde empirique V2 (taux Top 5 rétréci) : B seulement, vide si corpus < 30 courses similaires
                    try:
                        from app.engine import pmu_corpus_analyse as _pc
                        _biais_corde = _pc._biais_corde_v2(race) or None
                    except Exception as _ec:          # noqa: BLE001
                        logger.info("Biais de corde V2 indisponible: %s", _ec)
                try:
                    horses_b, _gru_stats = renforcer_horses(horses, race, _biais_corde, _rv)
                except Exception as _eb:          # noqa: BLE001
                    logger.warning("Renforcement du ticket B indisponible: %s", _eb)
                    horses_b, _gru_stats = list(horses), {"erreur": str(_eb)[:80]}
                _aj_b = [getattr(h, "ajust_rang", 0.0) for h in horses_b]
                _w_b = blend_weights(horses_b, alpha=_alpha_b, alpha_t3=_alpha_t3_b, ajust_rang=_aj_b)   # six composantes injectées DANS le score de classement
                _pi_b = inclusion_probs(_w_b)
                _fam = bool(int(_rv["familles"]))                                          # 1 = ancienne règle « une par famille »
                _kw_b = dict(un_par_tranche=_fam, grille=_fam, discipline=getattr(race, "discipline", None), signature=getattr(race, "signature", None))
                quotas_info = build_ticket_quotas(horses_b, _pi_b, rerank=bool(int(_rv["rerank"])), **_kw_b)   # T3 par le marché, T4 par PCH+ordre_final+valeur PMU
                quotas_info["pepite_entrees"] = 0
                if int(_rv["entrees_pepite"]) > 0:    # droit d'entrée pépite (score maximal), au plus `entrees_pepite` outsiders, même moitié T3/T4
                    try:
                        _ep = entrees_pepite(horses_b, quotas_info["selection"], _pi_b, [getattr(h, "pepite", 0.0) for h in horses_b],
                                             max_entrees=int(_rv["entrees_pepite"]))
                        if _ep["entrees"]:
                            quotas_info["selection_avant_entrees_pepite"] = quotas_info["selection"]
                            quotas_info["selection"] = _ep["selection"]
                            _comp = {g_: 0 for g_ in _GROUPES_TQ}
                            for i_ in _ep["selection"]:
                                if _cle_tq(horses_b[i_]) in _comp:
                                    _comp[_cle_tq(horses_b[i_])] += 1
                            quotas_info["composition"] = _comp
                            quotas_info["captures_attendues_modele"] = round(sum(_pi_b[i_] for i_ in _ep["selection"]), 3)
                            quotas_info["pepite_entrees"] = len(_ep["entrees"])
                    except Exception as _ee:      # noqa: BLE001
                        logger.warning("Entrées pépite du ticket B indisponibles: %s", _ee)
                quotas_info["pi_source"] = f"melange_alpha_{_alpha_b:g}_lab_b"
                quotas_info["alpha_marche"] = _alpha_b
                quotas_info["alpha_t3"] = _alpha_t3_b
                quotas_info["reglages_b"] = {"famille": _rg["famille"], "distance": _rg["distance"], "portees": _rg["portees"],
                                             "valeurs": {k: _rv[k] for k in ("alpha", "alpha_t3", "rerank", "entrees_pepite", "rangs_gru", "familles")}}
                try:        # effet GLOBAL des améliorations : sélection de référence = marché α, sans aucun renforcement
                    _sel_ref = build_ticket_quotas(horses_b, inclusion_probs(blend_weights(horses_b, alpha=_alpha_b)), rerank=False, **_kw_b)["selection"]
                    quotas_info["lab_chevaux_changes"] = len(set(quotas_info["selection"]) - set(_sel_ref))
                except Exception:   # noqa: BLE001
                    quotas_info["lab_chevaux_changes"] = None
                quotas_info["gru_renforce"] = {k: v for k, v in _gru_stats.items() if k != "par_cheval"}
                quotas_info["gru_renforce_par_cheval"] = _gru_stats.get("par_cheval")
                quotas_info["iic_v2"] = getattr(race, "iic_v2", None)
                quotas_info["recouvrement_avec_ticket_A"] = len(set(quotas_info["selection"]) & set(gmo["selection"]))
                quotas_info["captures_attendues_ticket_A"] = round(sum(_pi[i] for i in gmo["selection"]), 3)
                if _pi_moteur:
                    quotas_info["captures_attendues_pi_moteur"] = round(sum(_pi_moteur[i] for i in quotas_info["selection"]), 3)
                try:
                    _v68["B"] = _ap68(horses, "B", quotas_info["selection"])
                    if _v68["B"]["appliquee"]:
                        quotas_info["selection_avant_v68"] = list(quotas_info["selection"])
                        quotas_info["selection"] = list(_v68["B"]["selection"])
                        _comp68 = {g_: 0 for g_ in _GROUPES_TQ}
                        for i_ in quotas_info["selection"]:
                            if _cle_tq(horses_b[i_]) in _comp68:
                                _comp68[_cle_tq(horses_b[i_])] += 1
                        quotas_info["composition"] = _comp68
                        quotas_info["captures_attendues_modele"] = round(sum(_pi_b[i_] for i_ in quotas_info["selection"]), 3)
                        quotas_info["v1_29_68"] = _v68["B"]["origine"]
                except Exception as _e68b:  # noqa: BLE001
                    logger.info("Recalibrage v1.29.68 (B) indisponible: %s", _e68b)
                ticket_b = build_ticket(horses, quotas_info["selection"], roles_map={})
                # C : « ancré marché » = mêmes bornes T1+T2 / T3+T4 [3,5] SANS minimum par tranche (ce minimum coûte ~0,25 capture/course)
                ancre_info = build_ticket_quotas(horses, _pi, un_par_tranche=False)
                ancre_info["pi_source"] = "melange_marche_pch"
                ancre_info["recouvrement_avec_ticket_A"] = len(set(ancre_info["selection"]) & set(gmo["selection"]))
                ancre_info["captures_attendues_ticket_A"] = quotas_info["captures_attendues_ticket_A"]
                try:
                    _v68["C"] = _ap68(horses, "C", ancre_info["selection"])
                    if _v68["C"]["appliquee"]:
                        ancre_info["selection_avant_v68"] = list(ancre_info["selection"])
                        ancre_info["selection"] = list(_v68["C"]["selection"])
                        ancre_info["captures_attendues_modele"] = round(sum(_pi[i_] for i_ in ancre_info["selection"]), 3)
                        ancre_info["v1_29_68"] = _v68["C"]["origine"]
                except Exception as _e68c:  # noqa: BLE001
                    logger.info("Recalibrage v1.29.68 (C) indisponible: %s", _e68c)
                ticket_c = build_ticket(horses, ancre_info["selection"], roles_map={})
                quotas_info["recouvrement_avec_ticket_C"] = len(set(quotas_info["selection"]) & set(ancre_info["selection"]))
                quotas_info["identique_ticket_C"] = set(quotas_info["selection"]) == set(ancre_info["selection"])
                st.details["ticket_B_quotas"] = {k: quotas_info[k] for k in ("composition", "target_grid", "applied_grid", "ecart_grille", "t1_t2", "t3_t4", "captures_attendues_modele", "captures_attendues_sans_grille", "niveau_relaxation", "flags", "discipline_bucket", "signature", "iic_v2", "alpha_marche", "alpha_t3", "recouvrement_avec_ticket_C", "identique_ticket_C", "gru_renforce", "lab_chevaux_changes", "pepite_entrees", "rerank_tranche") if k in quotas_info}
                st.details["ticket_C_ancre_marche"] = {k: ancre_info[k] for k in ("composition", "t1_t2", "t3_t4", "captures_attendues_modele", "niveau_relaxation", "flags")}
            except Exception as _e:  # B et C ne doivent jamais faire échouer le ticket A
                logger.warning("Tickets B/C indisponibles: %s", _e)
            # --- v1.29.58 : chaque ticket est réorganisé en 3 BASES + 5 COMPLÉMENTS classés (champ réduit, désordre / bonus / ordre) ---
            structures: dict = {}
            try:
                from app.engine.ticket import structurer_bases_complements
                from app.engine.ticket_quotas import blend_weights
                _w = blend_weights(horses)
                for _lettre, _sel in (("A", gmo["selection"]),
                                      ("B", (quotas_info or {}).get("selection")),
                                      ("C", (ancre_info or {}).get("selection"))):
                    if _sel:
                        _hs, _ww = ((horses_b, _w_b) if (_lettre == "B" and horses_b is not None and _w_b is not None) else (horses, _w))
                        _forc = None
                        try:      # v1.29.69.1 : bases par score propre figé hors trot (part des bases dans le top 5 : 0,65-0,69 contre 0,53-0,59) ; trot : Plackett-Luce conservé
                            from app.engine.common import disc_bucket as _db
                            from app.engine.ticket_quotas import bases_propres as _bp2
                            if _db(race.discipline) != "TROT" and os.environ.get("VANTAGE_BASES_SCORE_PROPRE", "1").strip().upper() not in ("0", "NONE", "OFF", "NON"):
                                _forc = _bp2(horses, list(_sel), 3, race.discipline)
                        except Exception as _eb:  # noqa: BLE001
                            logger.info("Bases score propre indisponibles: %s", _eb)
                        _s = structurer_bases_complements(_hs, list(_sel), _ww, bases_forcees=_forc)
                        if _s:
                            try:
                                from app.engine.ticket_quotas import probas_recalibrees as _prc
                                _s["probabilites_recalibrees"] = _prc(_lettre, _s.get("probabilites_modele"))
                            except Exception:  # noqa: BLE001
                                pass
                            structures[_lettre] = _s
                st.details["structures_bases_complements"] = {
                    k: {"ordre_prevu": v["ordre_prevu"], **v["probabilites_modele"]} for k, v in structures.items()}
                try:      # v1.29.69.1 : filtre de courses (cote du favori) — signalé, jamais bloquant
                    from app.engine.ticket_quotas import signal_course as _sig
                    _fc = _sig(horses)
                    st.details["filtre_course"] = _fc
                    if _fc.get("niveau") == "reduit":
                        warnings.append(f"FILTRE_COURSE_REDUIT: favori coté {_fc['favori_cote']:g} > {_fc['seuil']:g} -- 5/5 observé ~8 % contre 21-22 % "
                                        "quand le favori est coté <= 4 ; mise réduite conseillée.")
                except Exception:  # noqa: BLE001
                    pass
            except Exception as _e:  # la structuration ne doit jamais faire échouer les tickets
                logger.warning("Structure bases/compléments indisponible: %s", _e)

        tracer.set_regle_20(
            respectee=True,
            note="Aucun appel à un résultat officiel (arrivée PMU) n'a lieu dans run_pipeline avant "
                 "la construction du ticket -- vérifiable directement dans ce fichier : "
                 "turfoo_resultats.fetch_arrival n'est importé et utilisé que dans main.py, "
                 "pour l'audit POST-course, jamais ici."
        )

        # --- Blocs 10+12 : journalisation GAMMA + présentation finale ---
        with tracer.stage("10. Finalisation -- Blocs 10+12 (journalisation GAMMA + présentation finale)") as st:
            result = RaceResult(
                race_id=race_id, context=race, horses=horses,
                pool_elargi=gmo["pool_elargi"], ticket=ticket, ticket_quotas=ticket_b, quotas_info=quotas_info, ticket_ancre=ticket_c, ancre_info=ancre_info, structures_tickets=(structures or None),
                p_top5_in_ticket=gmo["p_top5_in_ticket"], masse_residuelle=gmo["masse_residuelle"],
                constraints_report=report,
                validation_status=(f"VALIDÉ {VERSION_RULESET} (moteur Python)" if all_pass
                                    else "VALIDÉ AVEC RÉSERVES (voir contraintes dures)"),
            )
            result.json_output = build_json_output(result)
            result.json_output["gamma_log"] = gamma_log(horses, gmo["selection"])
            try:      # v1.29.68 : sélections alternatives publiées (numéros) pour comparaison appariée sur les prochains lots
                result.json_output["shadow_v1_29_68"] = {
                    t_: {"min1_melange": [horses[i].cheval.numero for i in (r_.get("shadow_min1_melange") or [])] or None,
                         "plafond2": [horses[i].cheval.numero for i in (r_.get("shadow_plafond2") or [])] or None,
                         "origine": r_.get("origine"), "appliquee": bool(r_.get("appliquee")), "erreur": r_.get("erreur")}
                    for t_, r_ in _v68.items()}
                result.json_output["valeur_pmu_trot_neutralisee"] = valeur_pmu_attenuation
                try:      # v1.29.69 : bases par score propre figé, probabilités recalibrées, filtre de courses, garde T1 (tout en shadow)
                    from app.engine.ticket_quotas import bases_propres as _bp, probas_recalibrees as _pr, signal_course as _sc, SCORE_PROPRE_DATE as _spd
                    _sels = {"A": gmo.get("selection"), "B": (quotas_info or {}).get("selection"), "C": (ancre_info or {}).get("selection")}
                    _num = lambda idxs: [horses[i].cheval.numero for i in idxs]   # noqa: E731
                    _t69 = {}
                    for _t, _s in _sels.items():
                        if not _s:
                            continue
                        _g = ((_v68.get(_t) or {}).get("shadow_garde_t1")) if _t == "A" else None
                        _t69[_t] = {"selection": _num(_s), "bases_k2": _num(_bp(horses, _s, 2, race.discipline)), "bases_k3": _num(_bp(horses, _s, 3, race.discipline)),
                                    "garde_t1": (_num(_g) if _g else None),
                                    "p_recal": _pr(_t, (structures.get(_t) or {}).get("probabilites_modele"))}
                    result.json_output["filtre_course"] = _sc(horses)
                    result.json_output["shadow_v1_29_69"] = {"signal_course": _sc(horses), "score_propre_date": _spd, "tickets": _t69}
                except Exception as _e69:  # noqa: BLE001
                    logger.info("Shadow v1.29.69 indisponible: %s", _e69)
            except Exception as _esh:  # noqa: BLE001
                logger.info("Publication shadow v1.29.68 indisponible: %s", _esh)
            if quotas_info:
                result.json_output["ticket_B_quotas"] = {
                    "regle": "8 chevaux ; mélange 50 % marché + 50 % PCH (Plackett-Luce) ; grille discipline × signature IIC-v2 en a priori souple ; T1+T2 et T3+T4 dans [3,5] ; au moins 1 cheval par famille T1/T2/T3/T4 disponible",
                    **{k: v for k, v in quotas_info.items() if k != "selection"},
                    "ticket": [t.model_dump() for t in ticket_b],
                }
            if ancre_info:
                result.json_output["ticket_C_ancre_marche"] = {
                    "regle": "8 chevaux ; mélange 50 % marché + 50 % PCH (probabilités Plackett-Luce calibrées) ; T1+T2 et T3+T4 dans [3,5] ; pas de minimum par tranche",
                    **{k: v for k, v in ancre_info.items() if k != "selection"},
                    "ticket": [t.model_dump() for t in ticket_c],
                }
            if structures:
                result.json_output["structures_bases_complements"] = structures
            try:   # v1.29.63 : état des données qui conditionnent B11 / B12 / classements, corde empirique, p_avant (diagnostic, aucun effet)
                from app.engine.classements import diagnostic as _diag_cl
                from app.engine.pmu_corpus_analyse import diagnostic_race as _diag_corde
                _pav = {round(float(h.cheval.p_avant), 3) for h in horses if getattr(h.cheval, "p_avant", None) is not None}
                result.json_output["diagnostic_donnees"] = {
                    **_diag_cl(), **_diag_corde(race),
                    "chevaux_avec_place_corde": sum(1 for h in horses if getattr(h.cheval, "numero_autostart", None) is not None),
                    "p_avant_valeurs_distinctes": len(_pav),
                    "p_avant_proxy_musique": not any(getattr(h.cheval, "position_mi_course_hist", None) for h in horses),
                    "chevaux_avec_driver": sum(1 for h in horses if getattr(h.cheval, "driver_jockey", None)),
                    "chevaux_avec_changement_driver": sum(1 for h in horses if getattr(h.cheval, "changement_driver", False)),
                }
                try:    # v1.29.66 : état des fournisseurs anti-bot (quel quota est épuisé, qui a servi)
                    from app.scraping.base import provider_stats as _prov_stats
                    result.json_output["diagnostic_donnees"]["fetch_providers"] = _prov_stats()
                except Exception:   # noqa: BLE001
                    pass
            except Exception as _e:  # noqa: BLE001
                logger.warning("diagnostic_donnees indisponible: %s", _e)
            _iic = getattr(race, "iic_v2", None)
            if _iic is not None:   # v1.29.60 : informatif — rejeu 55 courses : IIC < 72 → capture 4,19 (36 courses) ; IIC ≥ 72 → 3,37 (19 courses)
                result.json_output["confiance_capture"] = {
                    "iic_v2": round(float(_iic), 1), "niveau": ("FAIBLE_COURSE_OUVERTE" if _iic >= 72 else "NORMALE"),
                    "seuil_iic": 72, "reference_rejeu_55": {"iic_lt_72": 4.19, "iic_ge_72": 3.37}}
            result.json_output["gmo_v_log"] = gmo["log"]
            result.json_output["gmo_v_flags"] = gmo["flags"]
            result.json_output["gmo_v_pool_trace"] = gmo.get("pool_trace", [])
            result.json_output["gmo_v_selection_initiale"] = [horses[i].cheval.numero for i in _gmo_selection_initiale]
            result.json_output["gmo_v_selection_finale_A"] = [slot.numero for slot in ticket]
            result.json_output["gmo_v_trace_version"] = "pool-admissions-v1"
            result.json_output["top5_metrics"] = gmo.get("top5_metrics")
            result.json_output["operational_model"] = gmo.get("operational_model")
            result.json_output["compliance_guard"] = compliance
            try:
                from app.llm.supervisor import ai_runtime_status
                result.json_output["ai_runtime"] = ai_runtime_status()
            except Exception:
                pass
            result.json_output["supervision_ia"] = ai_supervision
            result.json_output["mode_execution"] = mode_execution
            result.json_output["anomalies_donnees"] = anomalies_donnees[:40]
            result.json_output["reparation_ia"] = {k: (v[:40] if isinstance(v, list) else v) for k, v in reparation_ia.items()}
            result.json_output["ia_qualitative"] = ia_qual_info
            try:
                from app.llm.tasks import build_race_summary
                result.json_output["resume"] = build_race_summary(result, anomalies_donnees, reparation_ia, ia_qual_info)
            except Exception as _e_sum:
                logger.warning("Résumé de course indisponible: %s", _e_sum)
            try:
                from app.ml.ranker_shadow import apply_ranker_shadow
                result.json_output["ml_shadow"] = apply_ranker_shadow(horses)
            except Exception as _e:
                result.json_output["ml_shadow"] = {"status": "ERROR", "detail": str(_e)}
            from app.version import VERSION_BUILD
            result.json_output["version_build"] = VERSION_BUILD
            result.json_output["version_ruleset"] = VERSION_RULESET
            result.json_output["gain_weights"] = gmo.get("gain_weights")
            result.json_output["guidance"] = gmo.get("guidance")
            # Qualité data Top5
            n_cotes = sum(1 for c in chevaux if c.cote_matin is not None)
            n_icp = sum(1 for c in chevaux if c.icp_global is not None)
            result.json_output["data_quality_top5"] = {
                "cotes_matin": f"{n_cotes}/{len(chevaux)}",
                "icp_renseigne": f"{n_icp}/{len(chevaux)}",
                "ft_sans_boost": (getattr(race, "_ft_rapport", None) or {}).get("sans_boost_icp"),
                "sources_count": len(urls),
                "recommandation": (
                    "OK" if n_cotes >= len(chevaux) * 0.8 and len(urls) >= 1
                    else "FOURNIR_2_SOURCES_ET_COTES_MATIN"
                ),
            }
            result.json_output["sources_consultees"] = [url_utilisee]
            result.json_output["sources_fournies"] = urls
            result.json_output["avertissements_collecte"] = warnings
            result.json_output["rapport_completude"] = rapport_completude
            result.json_output["data_contract"] = getattr(race, "_data_contract", None)
            result.json_output["gouvernance"] = gouvernance
            result.json_output["mode"] = "100% Python -- sans API Anthropic (voir README, Limites)"
            result.json_output["sources_liens"] = getattr(tracer.report, "sources_liens", None) or {}
            result.json_output["frequence_turf"] = getattr(race, "_ft_rapport", None)
            result.json_output["icp_summary"] = {
                "n_with_icp": sum(1 for c in chevaux if c.icp_global is not None),
                "max_icp": max((c.icp_global or 0) for c in chevaux) if chevaux else 0,
                "favoris_unanimes": [c.numero for c in chevaux if c.favori_unanime],
            }

            db.save_result(race_id, result.model_dump(mode="json"))
            st.details = {"nb_entrees_journal_gamma": len(result.json_output["gamma_log"])}

        # Export Hugging Face (v1.29.15, optionnel) -- pousse les données
        # pré-course + rapport d'exécution + ticket dès qu'ils sont
        # disponibles, avant même l'audit post-course (qui viendra
        # compléter le même dossier plus tard). Jamais bloquant.
        try:
            from app.integrations.hf_export import sync_race_to_hf
            r_record = db.get_race(race_id)
            if r_record:
                sync_race_to_hf(race_id, r_record)
        except Exception as e:
            logger.warning("Export Hugging Face (pré-audit) en échec pour %s : %s", race_id, e)

        db.update_status(race_id, "TERMINE")
        tracer.finish()

        if auto_audit:
            try:
                db.update_status(race_id, "AUDIT_EN_COURS")
                from app.engine.post_race_audit import run_full_audit
                audit = run_full_audit(race_id, result, urls)      # v1.29.53 : même audit que le bouton (A + B + résultats complets + IA)
                db.update_status(race_id, "TERMINE")
                logger.info("Audit automatique (walk-forward) réussi pour %s (A=%s, B=%s)", race_id,
                            audit.get("nb_captures"), (audit.get("audit_ticket_B") or {}).get("nb_captures"))
            except Exception as e:
                db.update_status(race_id, "TERMINE")
                logger.warning("Audit automatique (walk-forward) échoué pour %s : %s -- "
                                "l'audit manuel reste possible depuis l'interface.", race_id, e)

    except Exception as e:
        logger.exception("Erreur pipeline pour la course %s", race_id)
        db.update_status(race_id, "ERREUR", error=f"{e}\n{traceback.format_exc()[-2000:]}")
        tracer.finish("ECHEC")
