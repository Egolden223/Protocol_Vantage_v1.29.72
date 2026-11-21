"""
enrichment_mandatory.py -- Phase d'enrichissement OBLIGATOIRE post-collecte.

Après identification + collecte sur les 4 sources principales
(CanalTurf, Turfoo, Zone-Turf, Geny), cette phase recherche et comble
les données manquantes / complémentaires via les sources secondaires :

  - API PMU officielle (gains, valeur, poids, déferré, pénétromètre)
  - Fiches individuelles (Turfoo / CanalTurf / Zone-Turf)
  - Frequence-Turf (ICP / citations presse)
  - Equidia (programme + fiches cheval si disponibles)
  - Pénétromètre multi-sources: FT, Equidia, CanalTurf, France Galop,
    pages réunion hippodrome, Turfoo, Zone-Turf, API PMU
  - Turf.bzh (IA Gagnant, ELO, bonus plafonnés)
  - open-pmu-api (classements maison, corpus historique — via fiches/enrichment)

Principe :
  1. Inventaire des lacunes (champs critiques vides)
  2. Enchaînement systématique des sources complémentaires
  3. Rapport de couverture avant / après
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.models import Cheval, RaceContext

logger = logging.getLogger("vantage.scraping.enrichment_mandatory")

# Champs critiques pour le scoring Top5 / GMO-V
# Noms alignés sur le modèle Cheval (models.py) — corrigé 19/09/2026
_CHAMPS_CHEVAL = (
    "cote_matin",
    "cote_avant_course",
    "musique",
    "gains_totaux_eur",
    "valeur_pmu",
    "poids_actuel_kg",
    "deferre",
    "driver_jockey",
    "entraineur",
    "icp_global",
    "delai_j",
    "victoires_carriere",
    "fiche_url",
    "numero_autostart",
    "historique_terrain",
    "historique_distance",
    # v1.29.24 — lacunes fréquentes observées (Argentan-class)
    "commentaire_derniere_course",
    "gains_moyenne_carriere_eur",
    "recul_m",
)

_CHAMPS_COURSE = (
    "penetrometre",
    "hippodrome",
    "discipline",
    "distance_m",
    "partants_confirmes",
)


def _get(obj, name: str):
    return getattr(obj, name, None)


def _est_vide(val) -> bool:
    """True si la valeur est absente / vide (None, '', [], {})."""
    if val is None or val == "" or val == [] or val == {}:
        return True
    return False


def _champ_applicable(race: RaceContext, champ: str) -> bool:
    """Retourne si un champ est pertinent pour le contexte de la course.

    Les poids et valeurs handicap ne sont pas des données manquantes sur une
    course de trot : elles ne sont généralement pas publiées pour ce format.
    Les exclure de l'inventaire évite des re-fetches inutiles et des flags
    trompeurs, sans transformer une donnée absente en valeur de substitution.
    """
    disc = getattr(race, "discipline", None)
    disc_s = getattr(disc, "value", disc) or ""
    disc_s = str(disc_s).upper()
    if "TROT" in disc_s or "ATTEL" in disc_s or "MONT" in disc_s:
        return champ not in {
            "valeur_pmu", "valeur_pmu_precedente", "poids_actuel_kg",
            "poids_precedent_kg", "historique_terrain",
        }
    # v1.29.45 : champs propres au trot (déferré, recul, autostart, chronos/RK) : jamais « manquants »
    # en plat/obstacle (avant : « deferre » manquant déclenchait 105 s de vague complémentaire inutile).
    return champ not in {"deferre", "recul_m", "numero_autostart", "rk_derniere_sec",
                         "rk_array_3_derniers_sec", "chrono_200m", "record_chrono_sec"}


def inventaire_lacunes(race: RaceContext, chevaux: List[Cheval]) -> Dict[str, Any]:
    """Compte les champs vides critiques — base du plan d'enrichissement.

    Appelé APRÈS la collecte multi-sources (4 sources principales fusionnées).
    Sert à orienter l'enrichissement secondaire (API PMU, fiches, FT, Equidia…).
    """
    n = max(len(chevaux), 1)
    par_champ: Dict[str, int] = {}
    for champ in _CHAMPS_CHEVAL:
        manquants = (
            sum(1 for c in chevaux if _est_vide(_get(c, champ)))
            if _champ_applicable(race, champ) else 0
        )
        par_champ[champ] = manquants

    course_manquants = [c for c in _CHAMPS_COURSE if _est_vide(_get(race, c))]

    # Priorité haute = champs très impactants pour capture Top5 / scoring
    _PRIORITE = (
        "cote_matin", "cote_avant_course", "musique", "gains_totaux_eur",
        "icp_global", "valeur_pmu", "poids_actuel_kg", "deferre",
    )
    priorite_haute = {k: v for k, v in par_champ.items() if k in _PRIORITE and v > 0}

    return {
        "nb_chevaux": len(chevaux),
        "par_champ_manquants": par_champ,
        "taux_completude_champs": {
            k: round(1.0 - (v / n), 3) for k, v in par_champ.items()
        },
        "course_champs_manquants": course_manquants,
        "priorite_haute": priorite_haute,
        "sources_complementaires_prevues": [
            "api_pmu",
            "fiches_turfoo_canalturf_zoneturf",
            "frequence_turf_icp",
            "stats_quinte_icp_proxy",  # repli FT (grille anti-favoris) — 20/09/2026
            "equidia_programme",
            "turfbzh_ia_elo",
            "turfomania_partants",
            "web_search_google_cse",
            "web_search_ddg",
            "open_pmu_api_via_enrichment",
        ],
        "note": (
            "Inventaire post-collecte 4 sources principales. "
            "L'enrichissement secondaire (étapes 2.1→2.6) comble ces lacunes."
        ),
    }


def synthese_couverture(race: RaceContext, chevaux: List[Cheval]) -> Dict[str, Any]:
    """Couverture après enrichissement (même métriques que l'inventaire)."""
    inv = inventaire_lacunes(race, chevaux)
    score = sum(inv["taux_completude_champs"].values()) / max(len(_CHAMPS_CHEVAL), 1)
    return {
        **inv,
        "score_completude_global": round(score, 3),
        "chevaux_avec_cote": sum(
            1 for c in chevaux
            if not _est_vide(c.cote_matin) or not _est_vide(c.cote_avant_course)
        ),
        "chevaux_avec_musique": sum(1 for c in chevaux if not _est_vide(c.musique)),
        "chevaux_avec_gains": sum(1 for c in chevaux if not _est_vide(c.gains_totaux_eur)),
        "chevaux_avec_icp": sum(1 for c in chevaux if not _est_vide(c.icp_global)),
        "chevaux_avec_valeur_pmu": sum(1 for c in chevaux if not _est_vide(c.valeur_pmu)),
        "chevaux_avec_poids": sum(1 for c in chevaux if not _est_vide(c.poids_actuel_kg)),
    }


def delta_couverture(avant: Dict[str, Any], apres: Dict[str, Any]) -> Dict[str, Any]:
    """Différence de champs comblés entre avant et après."""
    comble: Dict[str, int] = {}
    a = avant.get("par_champ_manquants") or {}
    b = apres.get("par_champ_manquants") or {}
    for k in _CHAMPS_CHEVAL:
        comble[k] = max(0, a.get(k, 0) - b.get(k, 0))
    return {
        "champs_combles": comble,
        "total_comble": sum(comble.values()),
        "score_avant": None,  # renseigné par l'appelant si besoin
        "score_apres": apres.get("score_completude_global"),
    }


# ---------------------------------------------------------------------------
# v1.29.23 — Étape 2.7 : vérification + enrichissement COMPLÉMENTAIRE
# Après la vague obligatoire (2.1→2.6), inventaire résiduel puis seconde
# vague ciblée uniquement sur les champs encore vides.
# ---------------------------------------------------------------------------

_SOURCES_PRIORITAIRES = (
    "api_pmu",
    "fiches_turfoo",
    "fiches_canalturf",
    "fiches_zoneturf",
    "fiches_geny",
)
_SOURCES_SECONDAIRES = (
    "frequence_turf_icp",
    "stats_quinte_icp",
    "equidia",
    "turfbzh",
    "open_pmu_api",
)


def inventaire_residuel(
    race: RaceContext,
    chevaux: List[Cheval],
    *,
    seuil_priorite: float = 0.0,
) -> Dict[str, Any]:
    """Inventaire post-vague obligatoire : champs encore vides + chevaux cibles."""
    inv = inventaire_lacunes(race, chevaux)
    n = max(len(chevaux), 1)
    cibles: List[Dict[str, Any]] = []
    for c in chevaux:
        manquants = [
            ch for ch in _CHAMPS_CHEVAL
            if _champ_applicable(race, ch) and _est_vide(_get(c, ch))
        ]
        manquants_prio = [ch for ch in manquants if ch in (
            "cote_matin", "cote_avant_course", "musique", "gains_totaux_eur",
            "icp_global", "valeur_pmu", "poids_actuel_kg", "deferre",
            "driver_jockey", "entraineur", "fiche_url",
            "commentaire_derniere_course", "gains_moyenne_carriere_eur", "recul_m",
        )]
        if manquants_prio:
            cibles.append({
                "numero": c.numero,
                "nom": c.nom,
                "manquants": manquants,
                "manquants_prioritaires": manquants_prio,
                "fiche_url": getattr(c, "fiche_url", None),
            })
    return {
        **inv,
        "chevaux_cibles": cibles,
        "nb_cibles": len(cibles),
        "sources_prioritaires": list(_SOURCES_PRIORITAIRES),
        "sources_secondaires": list(_SOURCES_SECONDAIRES),
        "note": (
            "Inventaire résiduel après enrichissement obligatoire. "
            "La vague complémentaire ne cible que ces lacunes."
        ),
    }


def _fill_if_empty(cheval: Cheval, field: str, value) -> bool:
    """Remplit le champ uniquement s'il est vide. Retourne True si comblé."""
    if not _est_vide(_get(cheval, field)) or _est_vide(value):
        return False
    try:
        setattr(cheval, field, value)
        return True
    except Exception:
        return False


def _try_pmu_targeted(race: RaceContext, chevaux: List[Cheval], numeros: set) -> Dict[str, Any]:
    """Re-pass API PMU limité aux chevaux encore lacunaires."""
    out = {"status": "SKIPPED", "fields_filled": 0, "warnings": []}
    try:
        from app.scraping.pmu_api import enrich_race_with_pmu_api
        # PMU API agit au niveau course ; on mesure le delta après
        avant = {c.numero: inventaire_lacunes(race, [c])["par_champ_manquants"] for c in chevaux if c.numero in numeros}
        warns = enrich_race_with_pmu_api(race, chevaux)
        filled = 0
        for c in chevaux:
            if c.numero not in numeros:
                continue
            apres = inventaire_lacunes(race, [c])["par_champ_manquants"]
            for k, v in (avant.get(c.numero) or {}).items():
                if v > 0 and apres.get(k, 0) == 0:
                    filled += 1
        out["status"] = "OK"
        out["fields_filled"] = filled
        out["warnings"] = list(warns or [])[:10]
    except Exception as e:
        out["status"] = "ERROR"
        out["warnings"] = [str(e)[:200]]
    return out


def _count_empty(cheval: Cheval) -> int:
    return sum(1 for ch in _CHAMPS_CHEVAL if _est_vide(_get(cheval, ch)))


def _try_fiches_targeted(race: RaceContext, chevaux: List[Cheval], numeros: set) -> Dict[str, Any]:
    """Re-fetch fiches individuelles pour chevaux encore incomplets.

    fields_filled = champs réellement passés de vide → non-vide (pas les flags).
    """
    out = {"status": "SKIPPED", "fields_filled": 0, "par_source": {}, "warnings": []}
    filled = 0
    try:
        from app.scraping.enrichment import enrich_cheval
        for c in chevaux:
            if c.numero not in numeros:
                continue
            try:
                avant = _count_empty(c)
                flags = enrich_cheval(c, race, skip_personne_fiches=True) or []
                apres = _count_empty(c)
                delta = max(0, avant - apres)
                filled += delta
                if delta:
                    out["par_source"]["fiche_delta"] = out["par_source"].get("fiche_delta", 0) + delta
                for f in flags[:3]:
                    if "ENRICH" in str(f).upper():
                        src = str(f).split(":")[0] if ":" in str(f) else str(f)[:40]
                        out["par_source"][src] = out["par_source"].get(src, 0) + 1
            except Exception as e:
                out["warnings"].append(f"n{c.numero}:{str(e)[:80]}")
        out["status"] = "OK"
        out["fields_filled"] = filled
    except Exception as e:
        out["status"] = "ERROR"
        out["warnings"].append(str(e)[:200])
    return out


def _try_icp_targeted(race: RaceContext, chevaux: List[Cheval], numeros: set) -> Dict[str, Any]:
    """ICP : FT puis stats-quinte uniquement si icp encore vide."""
    out = {"status": "SKIPPED", "fields_filled": 0, "sources": []}
    need = [c for c in chevaux if c.numero in numeros and _est_vide(c.icp_global)]
    if not need:
        out["status"] = "SKIPPED_NO_NEED"
        return out
    filled = 0
    try:
        from app.scraping.frequence_turf import enrichir_course_frequence_turf, frequence_turf_enabled
        if frequence_turf_enabled():
            enrichir_course_frequence_turf(race, chevaux)
            out["sources"].append("frequence_turf")
    except Exception as e:
        out.setdefault("warnings", []).append(f"FT:{e}"[:120])
    try:
        from app.scraping.stats_quinte import enrichir_course_stats_quinte
        # ne remplir que si toujours vide
        enrichir_course_stats_quinte(race, chevaux)
        out["sources"].append("stats_quinte")
    except Exception as e:
        out.setdefault("warnings", []).append(f"SQ:{e}"[:120])
    for c in need:
        if not _est_vide(c.icp_global):
            filled += 1
    out["fields_filled"] = filled
    out["status"] = "OK"
    return out


def _try_equidia_turfbzh(race: RaceContext, chevaux: List[Cheval], numeros: set) -> Dict[str, Any]:
    out = {"status": "SKIPPED", "fields_filled": 0, "sources": []}
    targets = [c for c in chevaux if c.numero in numeros]
    filled0 = sum(_count_empty(c) for c in targets)
    try:
        from app.scraping.equidia import enrich_race_with_equidia
        enrich_race_with_equidia(race, chevaux)
        out["sources"].append("equidia")
    except Exception as e:
        out.setdefault("warnings", []).append(f"EQ:{e}"[:120])
    try:
        from app.scraping.turfbzh import enrich_race_with_turfbzh
        enrich_race_with_turfbzh(race, chevaux)
        out["sources"].append("turfbzh")
    except Exception as e:
        out.setdefault("warnings", []).append(f"BZH:{e}"[:120])
    filled1 = sum(_count_empty(c) for c in targets)
    out["fields_filled"] = max(0, filled0 - filled1)
    out["status"] = "OK"
    return out


def _try_public_web_patterns(race: RaceContext, chevaux: List[Cheval], numeros: set) -> Dict[str, Any]:
    """Recherche ciblée d'URLs publiques (domaines protocole) pour lacunes résiduelles.

    Cible: fiche_url, commentaire, valeur/poids via re-pass Equidia/PMU si pages OK.
    Pas de crawling libre — uniquement domaines déjà dans le protocole.
    """
    out = {"status": "SKIPPED", "attempts": 0, "fields_filled": 0, "urls_tentees": [], "warnings": []}
    need = [c for c in chevaux if c.numero in numeros]
    if not need:
        out["status"] = "SKIPPED_NO_NEED"
        return out

    hippo = (getattr(race, "hippodrome", None) or "").strip()
    date_iso = None
    for attr in ("date_course", "date", "jour"):
        d = getattr(race, attr, None)
        if d is not None:
            date_iso = str(d)[:10]
            break
    reunion = getattr(race, "reunion", None) or getattr(race, "numero_reunion", None)
    course_n = getattr(race, "course", None) or getattr(race, "numero_course", None)

    try:
        from app.scraping.base import fetch_html
    except Exception as e:
        out["status"] = "ERROR"
        out["warnings"].append(str(e)[:120])
        return out

    candidates = []
    if date_iso:
        # Formats date FR courants pour FT / presse
        try:
            y, m, d = date_iso.split("-")
            date_fr = f"{d}-{m}-{y}"
            date_fr2 = f"{d}/{m}/{y}"
            # mois en lettres (approx) non géré ici — FT déjà tenté en 2.3
        except Exception:
            date_fr = date_iso
            date_fr2 = date_iso
        candidates.extend([
            f"https://www.equidia.fr/courses/{date_iso}",
            f"https://www.geny.com/courses-pmu/{date_iso}",
            f"https://www.zone-turf.fr/programmes/",
        ])
        if reunion and course_n:
            try:
                r, c = int(reunion), int(course_n)
                candidates.extend([
                    f"https://www.equidia.fr/courses/{date_iso}/R{r}/C{c}",
                    f"https://www.turf.bzh/pronostics-pmu-{date_iso.replace('-', '')}-R{r}C{c}.html",
                ])
            except Exception:
                pass
        if hippo:
            hippo_slug = (
                hippo.lower()
                .replace("é", "e").replace("è", "e").replace("ê", "e")
                .replace(" ", "-")
            )
            candidates.append(
                f"https://www.canalturf.com/pronostics-PMU/{date_iso}/{hippo_slug}/"
            )

    filled = 0
    pages_ok = []
    for url in candidates[:8]:
        out["attempts"] += 1
        out["urls_tentees"].append(url)
        try:
            html = fetch_html(url, timeout=12, retries=0)
            if html and len(html) >= 500:
                pages_ok.append(url)
        except Exception as e:
            out["warnings"].append(f"{url.split('/')[2]}:{str(e)[:50]}")

    out["pages_ok"] = pages_ok

    # Si pages programme OK → re-pass Equidia/PMU (compter vrais comblements)
    targets = [c for c in chevaux if c.numero in numeros]
    empty0 = sum(_count_empty(c) for c in targets)
    if pages_ok:
        try:
            from app.scraping.equidia import enrich_race_with_equidia
            enrich_race_with_equidia(race, chevaux)
        except Exception as e:
            out["warnings"].append(f"EQ_repass:{str(e)[:60]}")
        try:
            from app.scraping.pmu_api import enrich_race_with_pmu_api
            enrich_race_with_pmu_api(race, chevaux)
        except Exception as e:
            out["warnings"].append(f"PMU_repass:{str(e)[:60]}")

    # Re-attache fiches Zone-Turf si URLs programme connues
    try:
        from app.scraping.enrichment import attach_zoneturf_fiche_urls
        urls = list(
            getattr(race, "programme_urls", None)
            or getattr(race, "urls_sources", None)
            or []
        )
        if urls:
            n_att = attach_zoneturf_fiche_urls(chevaux, urls)
            filled += int(n_att or 0)
    except Exception as e:
        out["warnings"].append(f"attach:{str(e)[:80]}")

    # Re-pass fiches individuelles si fiche_url présent mais champs critiques vides
    try:
        from app.scraping.enrichment import enrich_cheval
        for c in need:
            need_fields = (
                _est_vide(getattr(c, "commentaire_derniere_course", None))
                or _est_vide(getattr(c, "valeur_pmu", None))
                or _est_vide(getattr(c, "gains_totaux_eur", None))
            )
            if need_fields and not _est_vide(getattr(c, "fiche_url", None)):
                try:
                    enrich_cheval(c, race, skip_personne_fiches=True)
                except Exception:
                    pass
    except Exception as e:
        out["warnings"].append(f"fiches_repass:{str(e)[:80]}")

    empty1 = sum(_count_empty(c) for c in targets) if targets else empty0
    out["fields_filled"] = max(0, empty0 - empty1)
    out["status"] = "OK" if (out["attempts"] or filled) else "SKIPPED"
    return out



def _derive_recul_from_flags_or_notes(race: RaceContext, chevaux: List[Cheval]) -> int:
    """Si recul encore vide en trot, tenter re-scrape Zone-Turf/CanalTurf URLs du rapport.

    Fallback local : aucun — nécessite distance_ligne absente du modèle.
    Retourne nb chevaux comblés.
    """
    disc = getattr(race, "discipline", None)
    disc_s = disc.value if hasattr(disc, "value") else str(disc or "")
    if "TROT" not in disc_s.upper() and "ATTEL" not in disc_s.upper() and "MONT" not in disc_s.upper():
        return 0
    # Rien de plus sans re-fetch : la fusion multi-sources doit avoir fait le travail.
    # Ici on normalise seulement recul=0 explicite si tous à distance base (déjà 0).
    return 0


def run_enrichissement_complementaire(
    race: RaceContext,
    chevaux: List[Cheval],
) -> Dict[str, Any]:
    """Seconde vague (v1.29.24) : inventaire résiduel → prioritaires → secondaires → web public.

    Objectif: minimiser COMMENTAIRE_ABSENT, VALEUR_PMU_MANQUANTE, PENETROMETRE,
    gains, poids, fiche_url. Ne remplit QUE les champs encore vides.
    """
    avant = inventaire_residuel(race, chevaux)
    numeros = {c["numero"] for c in avant.get("chevaux_cibles") or []}
    rapport: Dict[str, Any] = {
        "inventaire_avant": {
            "nb_cibles": avant.get("nb_cibles"),
            "priorite_haute": avant.get("priorite_haute"),
            "score_estime": round(
                sum((avant.get("taux_completude_champs") or {}).values())
                / max(len(_CHAMPS_CHEVAL), 1),
                3,
            ),
        },
        "passes": {},
        "status": "SKIPPED",
    }
    if not numeros:
        rapport["status"] = "SKIPPED_COMPLET"
        rapport["message"] = "Aucune lacune prioritaire résiduelle — vague complémentaire inutile."
        rapport["inventaire_apres"] = synthese_couverture(race, chevaux)
        return rapport

    import os as _os, time as _time
    _t0 = _time.time()
    _budget = float(_os.environ.get("ENRICH_WAVE_MAX_SEC", "40"))

    def _depasse() -> bool:
        return (_time.time() - _t0) > _budget

    # 1) Sources prioritaires ciblées
    rapport["passes"]["pmu"] = _try_pmu_targeted(race, chevaux, numeros)
    rapport["passes"]["fiches"] = _try_fiches_targeted(race, chevaux, numeros)
    try:
        from app.scraping.equidia import enrich_from_equidia_programme
        rapport["passes"]["equidia_fiches"] = enrich_from_equidia_programme(race, chevaux)
    except Exception as e:
        rapport["passes"]["equidia_fiches"] = {"status": "ERROR", "error": str(e)[:200]}

    # 2) Sources secondaires ciblées (v1.29.45 : budget de temps ENRICH_WAVE_MAX_SEC, défaut 40 s)
    if _depasse():
        rapport["passes"]["budget"] = {"status": "BUDGET_TEMPS_DEPASSE", "fields_filled": 0}
    else:
        rapport["passes"]["icp"] = _try_icp_targeted(race, chevaux, numeros)
        rapport["passes"]["equidia_turfbzh"] = _try_equidia_turfbzh(race, chevaux, numeros)

    # 2a) Pénétromètre / état terrain — multi-sources (FT, Equidia, CT, FG, Turfoo, ZT)
    try:
        from app.scraping.penetrometre import enrich_penetrometre
        rapport["passes"]["penetrometre"] = enrich_penetrometre(race, chevaux)
    except Exception as e:
        rapport["passes"]["penetrometre"] = {"status": "ERROR", "error": str(e)[:200]}

    # 2bis) Turfomania (v1.29.28) — Dist/recul/ferrure/gains
    try:
        from app.scraping.turfomania import enrich_race_with_turfomania
        tm = enrich_race_with_turfomania(race, chevaux)
        rapport["passes"]["turfomania"] = tm
    except Exception as e:
        rapport["passes"]["turfomania"] = {"status": "ERROR", "error": str(e)[:200], "fields_filled": 0}

    # 2ter) Guide IA (optionnel) — priorités + requêtes web
    ai_guide = {"status": "SKIPPED"}
    try:
        from app.llm.supervisor import guide_enrichment
        lacunes_txt = list(avant.get("priorite_haute") or [])
        for c in (avant.get("chevaux_cibles") or [])[:12]:
            lacunes_txt.extend(c.get("champs_vides") or [])
        ai_guide = guide_enrichment(race, lacunes_txt, avant.get("taux_completude_champs"))
        rapport["passes"]["ai_guide"] = {
            "status": ai_guide.get("status"),
            "provider": ai_guide.get("provider"),
            "priorites": ai_guide.get("priorites"),
            "queries": ai_guide.get("queries"),
            "conseils": ai_guide.get("conseils"),
            "fields_filled": 0,
        }
    except Exception as e:
        rapport["passes"]["ai_guide"] = {"status": "ERROR", "error": str(e)[:200], "fields_filled": 0}

    # 3) Web public (domaines connus du protocole)
    if _depasse():
        rapport["passes"]["web_public"] = {"status": "BUDGET_TEMPS_DEPASSE", "fields_filled": 0}
    else:
        rapport["passes"]["web_public"] = _try_public_web_patterns(race, chevaux, numeros)

    # 3bis) Recherches web DDG ciblées (v1.29.28)
    try:
        if _depasse():
            raise TimeoutError("budget de temps de la vague complémentaire dépassé")
        from app.scraping.web_search_enrich import run_web_search_enrichment
        lacunes_list = list(avant.get("priorite_haute") or [])
        rapport["passes"]["web_search"] = run_web_search_enrichment(
            race, chevaux, numeros, lacunes=lacunes_list, ai_guide=ai_guide
        )
    except Exception as e:
        rapport["passes"]["web_search"] = {"status": "ERROR", "error": str(e)[:200], "fields_filled": 0}

    apres = synthese_couverture(race, chevaux)
    delta = delta_couverture(avant, apres)
    rapport["inventaire_apres"] = apres
    rapport["delta"] = delta
    total_filled = sum(
        (p or {}).get("fields_filled", 0) for p in rapport["passes"].values()
    )
    rapport["total_fields_filled_proxy"] = total_filled
    rapport["status"] = "OK"
    rapport["message"] = (
        f"Vague complémentaire: {avant.get('nb_cibles')} cibles, "
        f"delta cases={delta.get('total_comble', 0)}, "
        f"complétude={apres.get('score_completude_global')}"
    )
    return rapport
