"""
pmu_api.py -- API JSON officielle et publique du PMU (pas de clé,
pas d'authentification). Découverte le 09/08/2026 en examinant un projet
concurrent (Manus AI) puis vérifiée en direct sur une vraie course :
https://offline.turfinfo.api.pmu.fr/rest/client/1/programme/{DDMMYYYY}/R{n}/C{m}/participants

Utilisée en usage public (macros Excel/VBA, scripts PHP) depuis au moins
2016 d'après plusieurs forums français -- suffisamment stable et ancienne
pour être considérée fiable, mais reste un usage non documenté
officiellement : garder un chemin de repli (Turfoo/CanalTurf) en
primaire, cette API en ENRICHISSEMENT complémentaire.

Ce qu'elle résout d'un coup, avec plus de fiabilité qu'un scraping HTML
(JSON structuré officiel, pas de parsing fragile) :
  - gains_totaux_eur (Bloc D) -- gainsParticipant.gainsCarriere, PLUS
    granulaire que toute autre source (gains année en cours vs précédente)
  - valeur_pmu (Bloc B, SRI) -- handicapValeur, jamais peuplé jusqu'ici
  - poids_actuel_kg (Bloc I, PLAT handicap) -- handicapPoids / 100
  - équipement -- oeilleres (œillères), catégorie différente de la
    ferrure (DA/DP/D4...) déjà couverte par Turfoo/Zone-Turf
  - pénétromètre officiel + météo officielle (jamais peuplés par
    aucune source jusqu'ici)
  - categorieParticularite -- classification officielle HANDICAP/
    CONDITIONS/etc., plus fiable que la détection par mot-clé actuelle
  - incident par cheval (ARRETE/DISQUALIFIE/NON_PARTANT/...) -- Bloc L,
    et potentiellement le déblocage de RAH-205 (DAI) si "DISTANCE" y
    apparaît comme valeur -- À VÉRIFIER sur un cas réel, pas supposé
  - ordreArrivee officiel, par cheval -- bien plus fiable que le scraping
    de la page résultats Turfoo pour l'audit post-course

Ce qu'elle NE résout PAS avec certitude :
  - musique : format différent de la convention Geny/Zone-Turf/Turfoo/
    CanalTurf déjà gérée par musique.py (ex. rangs à 2 chiffres non
    tronqués en "0", lettres de discipline en position variable) --
    stockée en repli informatif seulement, PAS injectée dans
    Cheval.musique pour ne pas casser parse_musique() sur un format non
    garanti identique. À creuser plus tard si utile.
"""
from __future__ import annotations
import re
import logging
from datetime import date as date_cls, datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel

from app.scraping.base import fetch_html
from app.models import Cheval, RaceContext, TypeCourse

logger = logging.getLogger("vantage.scraping.pmu_api")

# Bases API PMU (historique + jour + futur si programme publié).
# offline = client/1 ; online = client/61 — les deux renvoient souvent le même JSON.
_BASES = (
    "https://offline.turfinfo.api.pmu.fr/rest/client/1/programme",
    "https://online.turfinfo.api.pmu.fr/rest/client/61/programme",
)
_BASE = _BASES[0]  # compat

_CATEGORIE_TO_TYPECOURSE = {
    "HANDICAP": TypeCourse.HANDICAP, "HANDICAP_DIVISE": TypeCourse.HANDICAP,
    "CONDITIONS": TypeCourse.CONDITIONS, "A_RECLAMER": TypeCourse.CLAIMER,
}


def build_urls(d, reunion: int, course: int, base: Optional[str] = None) -> Dict[str, str]:
    if isinstance(d, str):
        d = date_cls.fromisoformat(d[:10])
    ddmmyyyy = f"{d.day:02d}{d.month:02d}{d.year:04d}"
    root = base or _BASE
    base_course = f"{root}/{ddmmyyyy}/R{reunion}/C{course}"
    return {"course": base_course, "participants": f"{base_course}/participants"}


def _get_json(url: str) -> dict:
    import json
    raw = fetch_html(url)
    return json.loads(raw)


def _get_json_multi(urls: List[str]) -> dict:
    """Tente plusieurs URLs API (offline puis online) — fail-soft."""
    last_err = None
    for u in urls:
        try:
            data = _get_json(u)
            if data:
                return data
        except Exception as e:
            last_err = e
            logger.warning("PMU API %s : %s", u, e)
    if last_err:
        raise last_err
    return {}



def _norm_hippo(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def resolve_rc_from_programme(race: RaceContext) -> Optional[Tuple[int, int]]:
    """Si R/C absents : matcher hippodrome (+ distance) sur le programme PMU du jour."""
    if not race.date_course:
        return None
    from datetime import date as date_cls
    d = race.date_course
    if isinstance(d, date_cls):
        dstr = d.strftime("%d%m%Y")
    else:
        s = str(d)
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        dstr = (m.group(3) + m.group(2) + m.group(1)) if m else s.replace("-", "")
        if len(dstr) == 8 and dstr[:4].isdigit() and int(dstr[:4]) > 1900:
            # YYYYMMDD -> DDMMYYYY
            dstr = dstr[6:8] + dstr[4:6] + dstr[0:4]
    try:
        data = _get_json_multi([f"{b}/{dstr}" for b in _BASES])
    except Exception:
        return None
    reunions = (data.get("programme") or {}).get("reunions") or []
    target = _norm_hippo(race.hippodrome or "")
    if not target:
        return None
    from app.scraping.hippodrome_normalize import hippodromes_match
    hint = extraire_course_seule(race)
    matches = []
    for r in reunions:
        hip = r.get("hippodrome") or {}
        lib = hip.get("libelleLong") or hip.get("libelleCourt") or ""
        if not hippodromes_match(target, lib):
            continue
        num_r = r.get("numOfficiel")
        for co in r.get("courses") or []:
            num_c = co.get("numOrdre") or co.get("numCourse")
            if num_r is None or num_c is None:
                continue
            dist = co.get("distance")
            if hint is not None and int(num_c) != int(hint):
                continue
            if race.distance_m and dist and abs(int(dist) - int(race.distance_m)) > 25:
                continue
            matches.append((int(num_r), int(num_c)))
    # v1.29.40 : un seul candidat exact, sinon None (jamais « première course de la réunion »)
    return matches[0] if len(set(matches)) == 1 else None


def extraire_reunion_course(race: RaceContext) -> Optional[Tuple[int, int]]:
    """Extrait (R, C) depuis label, URLs sources, ou heuristique C-seul → R1.

    Zone-Turf ne pose souvent que "C4" (sans R) — regex historique exigeait
    un chiffre avant C → échec systématique → audit "arrivée indisponible"
    alors que l'API PMU a bien les résultats.
    """
    candidates: list[str] = []
    if race.reunion_course_label:
        candidates.append(str(race.reunion_course_label))
    if getattr(race, "url_source", None):
        candidates.append(str(race.url_source))
    for attr in ("sources_urls", "urls"):
        for u in getattr(race, attr, None) or []:
            candidates.append(str(u))

    # 1) R1C4 / R1 C4 / reunion1-course4 / course4 dans path turfoo
    for s in candidates:
        m = re.search(r"R\s*([0-9]+)\s*C\s*([0-9]+)", s, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r"reunion\s*([0-9]+)[^0-9]{0,12}course\s*([0-9]+)", s, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r"/reunion([0-9]+)[^/]*/course([0-9]+)", s, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))

    # 1bis) Zone-Turf : /programmes/r3-vincennes-198944.html#4 -> R3 C4
    for s_ in candidates:
        m = re.search(r"/programmes/r(\d+)-[^#?]*#(\d+)", s_, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))

    # v1.29.40 : plus AUCUN repli « C seul -> R1 » (ce défaut interrogeait la
    # mauvaise course dès que la réunion n'était pas la 1). Une étiquette « C4 »
    # sans réunion est traitée par resolve_rc_from_programme (course_hint).
    return None


def extraire_course_seule(race: RaceContext) -> Optional[int]:
    """N° de course seul (étiquette « C4 », fragment #4, ?course=4), sans réunion."""
    cands = [str(getattr(race, "reunion_course_label", "") or ""), str(getattr(race, "url_source", "") or "")]
    for s_ in cands:
        m = re.search(r"(?<![A-Za-z0-9])C\s*([0-9]+)(?![A-Za-z0-9])", s_, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"#[Cc]?([0-9]+)\b", s_) or re.search(r"[?&]course=([0-9]+)", s_, re.I)
        if m:
            return int(m.group(1))
    return None


def fetch_course_meta(d, reunion: int, course: int) -> Dict[str, Any]:
    """Pénétromètre, météo, categorieParticularite, incidents, distance,
    allocation, ordreArrivee -- au niveau course, avant tout partant.
    Tente offline puis online (passé / jour / futur si publié)."""
    candidates = [build_urls(d, reunion, course, b)["course"] for b in _BASES]
    return _get_json_multi(candidates)


def fetch_participants(d, reunion: int, course: int) -> List[dict]:
    candidates = [build_urls(d, reunion, course, b)["participants"] for b in _BASES]
    data = _get_json_multi(candidates)
    return data.get("participants", []) if isinstance(data, dict) else []


def enrich_race_with_pmu_api(race: RaceContext, chevaux: List[Cheval]) -> List[str]:
    """Enrichissement complémentaire (pas une source primaire) : mute
    race/chevaux en place, renvoie les avertissements. Ne lève jamais
    d'exception -- best-effort, comme Frequence-Turf."""
    warnings: List[str] = []
    collected_at = datetime.now(timezone.utc).isoformat()
    field_audit: Dict[int, Dict[str, Any]] = {}
    for c in chevaux:
        field_audit[c.numero] = {}
        for field in ("valeur_pmu", "cote_matin", "cote_avant_course"):
            before = getattr(c, field, None)
            field_audit[c.numero][field] = {
                "source": "preexistant_non_attribue" if before is not None else "absent_avant_api_pmu",
                "source_field": None, "raw_value": before, "value_before": before,
                "value_after": before, "observed_at_utc": None, "collected_at_utc": None,
                "api_enrichment_attempted_at_utc": collected_at,
            }
        object.__setattr__(c, "_vantage_pmu_field_audit", field_audit[c.numero])
    rc = extraire_reunion_course(race)
    if rc is None:
        rc = resolve_rc_from_programme(race)
        if rc:
            race.reunion_course_label = f"R{rc[0]}C{rc[1]}"
            warnings.append(f"R/C déduits du programme PMU : R{rc[0]}C{rc[1]}")
    if rc is None or not race.date_course:
        return ["reunion/course ou date_course inconnus -- URL API PMU non calculable."]
    reunion, course = rc

    try:
        meta = fetch_course_meta(race.date_course, reunion, course)
    except Exception as e:
        return [f"Course PMU API inaccessible : {e}"]

    # --- v1.29.40 : la course interrogée est-elle bien celle analysée ? ---
    try:
        d_meta = meta.get("distance")
        if d_meta and race.distance_m and abs(int(d_meta) - int(race.distance_m)) > 150:
            return [f"IDENTITE_PMU_REJETEE: distance PMU {d_meta} m != {race.distance_m} m (R{reunion}C{course})"]
    except (TypeError, ValueError):
        pass
    try:
        participants = fetch_participants(race.date_course, reunion, course)
    except Exception as e:
        warnings.append(f"Participants PMU API inaccessibles : {e}")
        participants = []
    if participants:
        from app.scraping.identity import noms_concordent, est_rejeu
        ok_noms, ratio = noms_concordent(chevaux, {p.get("numPmu"): p.get("nom") for p in participants if p.get("nom")})
        if not ok_noms:
            return [f"IDENTITE_PMU_REJETEE: noms de partants concordants à {ratio:.0%} seulement (R{reunion}C{course}) -- API PMU ignorée"]
        if est_rejeu(race.date_course):
            warnings.append("BACKTEST_CUMULS_PMU_NON_FIGES: course passée, gains/victoires cumulés potentiellement postérieurs à la course")

    if race.penetrometre is None:
        pen = meta.get("penetrometre")
        if pen and pen.get("valeurMesure") is not None:
            # Bug corrigé le 08/09/2026 : affectation directe de la valeur
            # brute de l'API PMU sans conversion -- pour certaines courses
            # (Haies à Auteuil observé en test réel), valeurMesure arrive
            # en chaîne de caractères plutôt qu'en nombre, ce qui plantait
            # plus tard toute comparaison numérique (module_j_terrain,
            # common.py::terrain_category) avec un TypeError. Jamais
            # d'affectation d'une valeur non convertible : on la jette
            # proprement avec un avertissement plutôt que de laisser passer
            # une donnée qui fera planter le pipeline plus loin.
            brut = pen["valeurMesure"]
            try:
                race.penetrometre = float(str(brut).replace(",", "."))
                warnings.append(f"Pénétromètre officiel PMU : {brut} ({pen.get('correction', '')})")
            except (TypeError, ValueError):
                warnings.append(f"Pénétromètre officiel PMU ignoré -- valeur non numérique reçue : {brut!r}")
    if getattr(race, "meteo_temp_c", None) is None:
        meteo = meta.get("meteo")
        if meteo and meteo.get("temperature") is not None:
            race.meteo_temp_c = meteo["temperature"]
            race.meteo_vent_kmh_max = meteo.get("forceVent")

    categorie = meta.get("categorieParticularite")
    if categorie and categorie in _CATEGORIE_TO_TYPECOURSE and race.type_course == TypeCourse.AUTRE:
        race.type_course = _CATEGORIE_TO_TYPECOURSE[categorie]
        warnings.append(f"type_course précisé via categorieParticularite officielle PMU : {categorie}")

    ordre_arrivee_officiel = meta.get("ordreArrivee")
    if ordre_arrivee_officiel:
        race._ordre_arrivee_pmu = ordre_arrivee_officiel  # attaché de façon informelle, pour l'audit

    by_numero = {c.numero: c for c in chevaux}
    nb_combles = 0
    for p in participants:
        numero = p.get("numPmu")
        cheval = by_numero.get(numero)
        if cheval is None:
            continue

        gains = p.get("gainsParticipant") or {}
        if cheval.gains_totaux_eur is None and gains.get("gainsCarriere") is not None:
            try:
                cheval.gains_totaux_eur = float(gains["gainsCarriere"]) / 100.0  # centimes -> euros
                nb_combles += 1
            except (TypeError, ValueError):
                pass
        # Gains année en cours (souvent plus discriminants que carrière)
        if getattr(cheval, "gains_annee_en_cours_eur", None) is None and gains.get("gainsAnneeEnCours") is not None:
            try:
                setattr(cheval, "gains_annee_en_cours_eur", float(gains["gainsAnneeEnCours"]) / 100.0)
            except (TypeError, ValueError):
                pass
        if cheval.valeur_pmu is None and p.get("handicapValeur") is not None:
            try:
                cheval.valeur_pmu = float(p["handicapValeur"])
                field_audit[numero]["valeur_pmu"] = {
                    "source": "API_PMU", "source_field": "participants.handicapValeur",
                    "raw_value": p["handicapValeur"], "value_before": None,
                    "value_after": cheval.valeur_pmu, "observed_at_utc": None,
                    "collected_at_utc": collected_at,
                }
                nb_combles += 1
            except (TypeError, ValueError):
                field_audit[numero]["valeur_pmu"].update({"source": "API_PMU_invalide",
                    "source_field": "participants.handicapValeur", "raw_value": p["handicapValeur"]})
                warnings.append(f"API PMU: handicapValeur non numérique pour le cheval {numero}: {p['handicapValeur']!r}")
        if cheval.poids_actuel_kg is None and p.get("handicapPoids") is not None:
            try:
                # PMU : parfois /10 (trot rare), parfois /100 (plat) — heuristique
                raw = float(p["handicapPoids"])
                cheval.poids_actuel_kg = raw / 10.0 if raw > 200 else raw
                nb_combles += 1
            except (TypeError, ValueError):
                pass
        # Réduction km (trot) : stockée pour proxy SRI si pas de valeur handicap
        rk = p.get("reductionKilometrique")
        if rk is not None:
            try:
                setattr(cheval, "_reduction_km_pmu", float(rk))
                field_audit[numero]["reduction_km"] = {
                    "source": "API_PMU", "source_field": "participants.reductionKilometrique",
                    "raw_value": rk, "value_after": float(rk), "observed_at_utc": None,
                    "collected_at_utc": collected_at,
                }
            except (TypeError, ValueError):
                field_audit[numero]["reduction_km"] = {"source": "API_PMU_invalide",
                    "source_field": "participants.reductionKilometrique", "raw_value": rk}
        if cheval.nb_courses is None and p.get("nombreCourses") is not None:
            cheval.nb_courses = p["nombreCourses"]
            nb_combles += 1
        if cheval.victoires_carriere is None and p.get("nombreVictoires") is not None:
            cheval.victoires_carriere = p["nombreVictoires"]
            nb_combles += 1
        if cheval.places_carriere is None and p.get("nombrePlaces") is not None:
            cheval.places_carriere = p["nombrePlaces"]
            nb_combles += 1
        # Musique API si absente côté HTML
        if not cheval.musique and p.get("musique"):
            cheval.musique = str(p["musique"]).strip()
            nb_combles += 1
        # Driver / jockey + entraîneur (API: champs string "driver" / "entraineur")
        drv = p.get("driver") or p.get("nomJockey") or p.get("jockey")
        if drv and not cheval.driver_jockey:
            cheval.driver_jockey = str(drv).strip()
            nb_combles += 1
        ent = p.get("entraineur") or p.get("nomEntraineur")
        if ent and not cheval.entraineur:
            cheval.entraineur = str(ent).strip()
            nb_combles += 1
        # Gains moyenne carrière
        if getattr(cheval, "gains_moyenne_carriere_eur", None) is None:
            gc = gains.get("gainsCarriere")
            nc = p.get("nombreCourses")
            if gc is not None and nc:
                try:
                    cheval.gains_moyenne_carriere_eur = (float(gc) / 100.0) / max(int(nc), 1)
                    nb_combles += 1
                except (TypeError, ValueError):
                    pass
        # Déferrage PMU (D4/DP/DA…)
        deferre = p.get("deferre")
        if deferre and str(deferre).upper() not in ("", "NONE", "NULL", "FERRE", "FERRÉ"):
            code = str(deferre).strip().upper()
            if cheval.deferre is None:
                cheval.deferre = code
                nb_combles += 1
            if cheval.ferrure_type is None:
                cheval.ferrure_type = code
                cheval.ferrure_changes = max(cheval.ferrure_changes or 0, 1)
        # Œillères PMU — conserver le code (D16 Ghost D), pas seulement un booléen
        if p.get("oeilleres"):
            code_oe = str(p["oeilleres"]).strip().upper()
            if cheval.oeilleres is None:
                cheval.oeilleres = code_oe
            if code_oe and code_oe not in ("SANS_OEILLERES", "SANS", "NONE", "NULL", ""):
                cheval.equip_changes = max(cheval.equip_changes or 0, 1)
        if p.get("incident"):
            cheval._incident_pmu = p["incident"]  # informel -- Bloc L, à exploiter plus tard
        if p.get("driverChange"):
            cheval.changement_driver = True
            cheval._driver_change_pmu = True
        # Corde / place départ (parfois utile en repli AS)
        if cheval.numero_autostart is None and p.get("placeCorde") is not None:
            try:
                cheval.numero_autostart = int(p["placeCorde"])
                nb_combles += 1
            except (TypeError, ValueError):
                pass
        # Cote officielle PMU, en repli SEULEMENT si la source principale
        # n'a rien donné (elle reste la référence -- 2 points de collecte
        # Bloc B déjà couverts par ailleurs).
        if cheval.cote_matin is None:
            ref = p.get("dernierRapportReference") or {}
            if ref.get("rapport") is not None:
                cheval.cote_matin = ref["rapport"]
                field_audit[numero]["cote_matin"] = {
                    "source": "API_PMU", "source_field": "participants.dernierRapportReference.rapport",
                    "raw_value": ref["rapport"], "value_before": None, "value_after": cheval.cote_matin,
                    "observed_at_utc": None, "collected_at_utc": collected_at,
                }
                nb_combles += 1
        if cheval.cote_avant_course is None:
            direct = p.get("dernierRapportDirect") or {}
            if direct.get("rapport") is not None:
                cheval.cote_avant_course = direct["rapport"]
                field_audit[numero]["cote_avant_course"] = {
                    "source": "API_PMU", "source_field": "participants.dernierRapportDirect.rapport",
                    "raw_value": direct["rapport"], "value_before": None, "value_after": cheval.cote_avant_course,
                    "observed_at_utc": None, "collected_at_utc": collected_at,
                }
                nb_combles += 1

    # Post-passe : gains_moyenne + proxy valeur_pmu pour TROT (handicapValeur
    # absent sur conditions / européennes — constaté Vincennes 20/09/2026).
    rk_vals = []
    for c in chevaux:
        rk = getattr(c, "_reduction_km_pmu", None)
        if rk is not None and rk > 0:
            rk_vals.append(rk)
        if c.gains_moyenne_carriere_eur is None and c.gains_totaux_eur and c.nb_courses:
            try:
                c.gains_moyenne_carriere_eur = float(c.gains_totaux_eur) / max(int(c.nb_courses), 1)
                nb_combles += 1
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    if rk_vals:
        rk_best = min(rk_vals)  # plus bas = plus rapide
        rk_worst = max(rk_vals)
        span = max(rk_worst - rk_best, 1.0)
        n_proxy = 0
        for c in chevaux:
            if c.valeur_pmu is not None:
                continue
            rk = getattr(c, "_reduction_km_pmu", None)
            if rk is None or rk <= 0:
                continue
            # Map réduction → échelle type valeur handicap 18–58
            # meilleur chrono → valeur haute
            rel = (rk_worst - rk) / span  # 0 worst → 1 best
            c.valeur_pmu = round(18.0 + 40.0 * rel, 2)
            field_audit[c.numero]["valeur_pmu"] = {
                "source": "proxy_derive_API_PMU", "source_field": "participants.reductionKilometrique",
                "raw_value": rk, "value_before": None, "value_after": c.valeur_pmu,
                "formula": "18 + 40*(rk_max-rk)/(rk_max-rk_min)",
                "observed_at_utc": None, "collected_at_utc": collected_at,
            }
            n_proxy += 1
            nb_combles += 1
        if n_proxy:
            warnings.append(
                f"API PMU : {n_proxy} valeur_pmu proxy via réduction km "
                f"(trot/conditions sans handicapValeur)"
            )

    n_lacunes_prio1 = sum(1 for c in chevaux if getattr(c, "valeur_pmu", None) is None)
    if n_lacunes_prio1:
        warnings.append(f"COLLECTE_PRIO1: {n_lacunes_prio1} partants sans valeur_pmu après API PMU")
    if nb_combles:
        warnings.append(f"API PMU officielle : {nb_combles} valeur(s) complétée(s) (gains/valeur/poids/nb/victoires/places/musique/deferre/cote/rk).")
    for c in chevaux:
        for field in ("valeur_pmu", "cote_matin", "cote_avant_course"):
            field_audit[c.numero][field]["value_after"] = getattr(c, field, None)
    return warnings


class ArrivalHorsePMU(BaseModel):
    rang: int
    numero: int
    nom: str


def fetch_official_arrival_pmu(d, reunion: int, course: int) -> List[ArrivalHorsePMU]:
    """Bien plus fiable que le scraping de la page résultats Turfoo pour
    l'audit post-course : ordreArrivee est structuré, officiel, et donné
    par cheval dans le flux participants lui-même (pas de parsing de
    texte libre)."""
    participants = fetch_participants(d, reunion, course)
    arrival = [
        ArrivalHorsePMU(rang=p["ordreArrivee"], numero=p["numPmu"], nom=p.get("nom", ""))
        for p in participants if p.get("ordreArrivee") is not None
    ]
    if not arrival:
        raise ValueError(f"Aucune arrivée officielle PMU trouvée pour R{reunion}C{course} le {d} (course pas encore courue ?).")
    arrival.sort(key=lambda h: h.rang)
    return arrival


def _libelle_ecart(e) -> Optional[str]:
    """L'API PMU renvoie l'écart sous forme d'objet {libelleCourt, libelleLong, code...} : on garde le libellé."""
    if isinstance(e, dict):
        return e.get("libelleLong") or e.get("libelleCourt")
    return str(e) if e else None


def fetch_full_results_pmu(d, reunion: int, course: int) -> Dict[int, Dict[str, Any]]:
    """Résultat COMPLET de la course (tous les partants, pas seulement le Top 5) -- v1.29.45.

    Pour chaque numéro : rang d'arrivée, statut, INCIDENT officiel (tombé, arrêté, disqualifié, distancé,
    resté au poteau...), écart, temps, et commentaire d'après-course s'il est publié. Les noms de champs
    PMU varient selon les versions : on lit plusieurs variantes, sans jamais rien inventer.
    Sert à distinguer, dans l'audit, une MAUVAISE ÉVALUATION d'un simple INCIDENT DE COURSE."""
    out: Dict[int, Dict[str, Any]] = {}
    for p in fetch_participants(d, reunion, course):
        num = p.get("numPmu")
        if num is None:
            continue
        incident = p.get("incident") or p.get("incidents") or p.get("statutIncident")
        if isinstance(incident, (list, tuple)):
            incident = ",".join(str(x) for x in incident) or None
        comm = p.get("commentaireApresCourse") or p.get("commentaire") or p.get("commentaireAvantCourse")
        if isinstance(comm, dict):
            comm = comm.get("texte") or comm.get("text")
        out[int(num)] = {
            "nom": p.get("nom", ""),
            "rang": p.get("ordreArrivee"),
            "statut": p.get("statut"),
            "incident": str(incident) if incident else None,
            "ecart": _libelle_ecart(p.get("distanceChevalPrecedent") or p.get("ecartPrecedent")),
            "temps_ms": p.get("tempsObtenu"),
            "reduction_km": p.get("reductionKilometrique"),
            "commentaire": str(comm).strip()[:400] if comm else None,
        }
    return out
