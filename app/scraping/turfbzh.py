"""Turf.bzh — enrichissement HTML gratuit (tableData) + bonus maîtrisés.

v1.29.66.5 — extension P0 / P1 / P2 (sans API payante)
Source : tableData embarqué dans /pronostics-pmu-{DDMMYYYY}-R{n}C{n}.html

P0 : avis entraîneur, IMDC, cote_bzh vs marché, Top2–5IA / Esp_Victoire, difficulté course
P1 : synergie JCh, chgt ferrure/driver, deferre4, ELO jockey/entraîneur, TP 90j,
     taux incident, exFav, alloc_ratio / rank_prec
P2 : stats carrière, corde, record distance, charge jockey du jour

Bonus CatalogSignal (famille C, plafonnés) :
  B61–B64  IA/ELO existants
  B65      avis entraîneur POSITIF
  B66      avis entraîneur NEGATIF (malus)
  B67      IMDC descente de catégorie (favorable)
  B68      value cote_bzh << cote marché
  B69      surcote marché (faux favori potentiel)
  B70      IA top5 multi-places (Top2–Top5)
  B71      synergie jockey-cheval
  B72      ex-favori
  B73      taux incident élevé (malus)
  B74      changement ferrure / D4 première fois
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.scraping.base import fetch_html
from app.models import Cheval, RaceContext, CatalogSignal

logger = logging.getLogger("vantage.scraping.turfbzh")

# Caps bonus (maîtrise)
_BONUS_IA_RANG = {1: 6.0, 2: 5.0, 3: 4.0}
_BONUS_ELO_RANG = {1: 4.0, 2: 3.0, 3: 2.0}
_BONUS_IA_PCT = 3.0
_BONUS_SYNERGIE = 2.0
_TOP1IA_SEUIL = 0.10

_BONUS_AVIS_POS = 4.0
_BONUS_AVIS_NEG = -8.0
_BONUS_IMDC_DOWN = 3.0
_BONUS_IMDC_UP = -1.5
_BONUS_VALUE_BZH = 3.5
_BONUS_SURCOTE = -2.0
_BONUS_IA_MULTI = {2: 3.0, 3: 2.5, 4: 2.0, 5: 1.5}
_BONUS_SYNERGIE_JCH = 2.5
_BONUS_EXFAV = 2.0
_BONUS_INCIDENT_MALUS = -3.0
_BONUS_CHGT_FERRURE = 1.5
_BONUS_D4 = 2.0


def _date_key(date_iso: str) -> str:
    d = str(date_iso)[:10]
    y, m, j = d.split("-")
    return f"{j}{m}{y}"


def build_turfbzh_url(date_iso: str, reunion: int, course: int) -> str:
    return f"https://www.turf.bzh/pronostics-pmu-{_date_key(date_iso)}-R{reunion}C{course}.html"


def extract_table_data(html: str) -> List[dict]:
    m = re.search(r"tableData\s*:\s*(\[)", html)
    if not m:
        return []
    start = m.start(1)
    depth = 0
    end = start
    for i, ch in enumerate(html[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(html[start:end])
    except json.JSONDecodeError as e:
        logger.warning("tableData JSON invalide: %s", e)
        return []


def _f(v) -> Optional[float]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(
            str(v)
            .replace("%", "")
            .replace(",", ".")
            .replace("\xa0", "")
            .replace(" ", "")
            .replace("€", "")
        )
    except (TypeError, ValueError):
        return None


def _i(v) -> Optional[int]:
    f = _f(v)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _truthy(v) -> bool:
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "oui", "y", "ok") or s.startswith("d4")


def _norm_avis(raw) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s or s in ("-", "NONE", "NULL", "NAN"):
        return None
    if "NEG" in s or s in ("-", "N", "-1"):
        return "NEGATIF"
    if "POS" in s or s in ("+", "P", "1", "OUI"):
        return "POSITIF"
    if "NEUT" in s or s in ("0", "=", "MOYEN"):
        return "NEUTRE"
    # HTML badge possible
    if "POSITIF" in s:
        return "POSITIF"
    if "NEGATIF" in s:
        return "NEGATIF"
    if "NEUTRE" in s:
        return "NEUTRE"
    return None


def _ia_proba(raw) -> Optional[float]:
    """Normalise proba IA 0–1 (accepte 0–100)."""
    v = _f(raw)
    if v is None:
        return None
    if v > 1.5:
        v = v / 100.0
    if 0.0 <= v <= 1.0:
        return v
    return None


def fetch_turfbzh_partants(date_iso: str, reunion: int, course: int) -> List[dict]:
    url = build_turfbzh_url(date_iso, reunion, course)
    html = fetch_html(url)
    return extract_table_data(html)


def _rank_by(rows: List[dict], key: str, reverse: bool = True) -> Dict[int, int]:
    scored = []
    for r in rows:
        num = r.get("numPmu")
        val = _f(r.get(key))
        if num is None or val is None:
            continue
        scored.append((int(num), val))
    scored.sort(key=lambda x: x[1], reverse=reverse)
    return {num: i + 1 for i, (num, _) in enumerate(scored)}


def _set_meta(race: RaceContext, key: str, value) -> None:
    """Stocke une méta course sans écraser un attr métier connu."""
    bag = getattr(race, "meta_sources", None)
    if not isinstance(bag, dict):
        bag = {}
        try:
            setattr(race, "meta_sources", bag)
        except Exception:
            return
    bzh = bag.setdefault("turfbzh", {})
    if key not in bzh or bzh[key] in (None, "", []):
        bzh[key] = value


def enrich_race_with_turfbzh(race: RaceContext, chevaux: List[Cheval]) -> Dict[str, object]:
    from app.scraping.pmu_api import extraire_reunion_course, resolve_rc_from_programme

    rc = extraire_reunion_course(race) or resolve_rc_from_programme(race)
    if not rc or not race.date_course:
        return {"status": "SKIP", "reason": "R/C ou date absents", "n_bonus": 0}
    reunion, course = rc
    date_iso = str(race.date_course)[:10]
    try:
        rows = fetch_turfbzh_partants(date_iso, reunion, course)
    except Exception as e:
        logger.warning("Turf.bzh fetch échec: %s", e)
        return {"status": "ERROR", "reason": str(e), "n_bonus": 0}

    if not rows:
        return {
            "status": "EMPTY",
            "n_bonus": 0,
            "url": build_turfbzh_url(date_iso, reunion, course),
        }

    from app.scraping.identity import noms_concordent

    _noms: Dict[int, str] = {}
    for _r in rows:
        _n = _r.get("nom") or _r.get("nomCheval") or _r.get("cheval") or _r.get("name")
        if _r.get("numPmu") is not None and _n:
            try:
                _noms[int(_r["numPmu"])] = str(_n)
            except (TypeError, ValueError):
                pass
    if _noms:
        _ok, _ratio = noms_concordent(chevaux, _noms)
        if not _ok:
            return {
                "status": "SKIP",
                "reason": (
                    f"IDENTITE_TURFBZH_REJETEE: noms concordants à {_ratio:.0%} "
                    f"(R{reunion}C{course})"
                ),
                "n_bonus": 0,
            }

    rank_ia = _rank_by(rows, "Top1IA", reverse=True)
    rank_elo = _rank_by(rows, "pointsCheval", reverse=True)
    rank_elo_j = _rank_by(rows, "pointsJockey", reverse=True)
    rank_elo_t = _rank_by(rows, "pointsTrainer", reverse=True)
    by_num = {int(r["numPmu"]): r for r in rows if r.get("numPmu") is not None}

    # P0 — difficulté course (premier non-vide)
    for r0 in rows:
        diff = r0.get("race_difficulty") or r0.get("difficulte")
        if diff not in (None, ""):
            _set_meta(race, "race_difficulty", str(diff))
            # exposer aussi en flag course lisible
            try:
                if not getattr(race, "terrain_qualificatif", None):
                    pass
                flags_r = list(getattr(race, "flags", None) or [])
                flags_r.append(f"BZH_DIFFICULTE:{str(diff)[:20]}")
                setattr(race, "flags", list(dict.fromkeys(flags_r)))
            except Exception:
                pass
            break

    n_filled = 0
    n_bonus = 0
    n_signals = {"p0": 0, "p1": 0, "p2": 0}

    for ch in chevaux:
        r = by_num.get(ch.numero)
        if not r:
            continue
        signals: List[CatalogSignal] = []
        flags_add: List[str] = []

        # ========== comblement champs (socle + P2) ==========
        if not ch.musique and r.get("musique"):
            ch.musique = str(r["musique"])
            n_filled += 1
        g = _f(r.get("gains") or r.get("Gains_Totaux") or r.get("gains_totaux"))
        if ch.gains_totaux_eur is None and g is not None:
            ch.gains_totaux_eur = g
            n_filled += 1
        if ch.delai_j is None and r.get("repos") is not None:
            try:
                ch.delai_j = int(float(str(r["repos"]).split()[0]))
                n_filled += 1
            except (TypeError, ValueError):
                pass
        pds = _f(r.get("pds_calc_hand_partant") or r.get("Poids"))
        if ch.poids_actuel_kg is None and pds is not None:
            ch.poids_actuel_kg = pds
            n_filled += 1
        val = _f(r.get("valeur") or r.get("Valeur"))
        if ch.valeur_pmu is None and val is not None:
            ch.valeur_pmu = val
            n_filled += 1

        # cote_bzh : ne pollue cote_matin que si absente ; stocke toujours en flag
        cote_b = _f(r.get("cote_bzh") or r.get("Cote_BZH"))
        cote_mkt = None
        if ch.cote_matin is not None and 1.01 <= float(ch.cote_matin) < 500:
            cote_mkt = float(ch.cote_matin)
        elif ch.cote_avant_course is not None and 1.01 <= float(ch.cote_avant_course) < 500:
            cote_mkt = float(ch.cote_avant_course)
        if cote_b and 1.01 <= cote_b < 500:
            flags_add.append(f"BZH_COTE_BZH:{cote_b:.2f}")
            if ch.cote_matin is None or ch.cote_matin >= 500:
                # fallback léger uniquement si aucune cote marché
                ch.cote_matin = cote_b
                flags_add.append("COTE_MATIN_BZH_HTML")
                n_filled += 1

        ferr = r.get("ferrure_str") or r.get("ferrure")
        if ferr and ch.ferrure_type is None:
            fs = str(ferr).lower()
            if any(x in fs for x in ("déf", "def", "d4", "dp", "da", "ferr")):
                ch.ferrure_type = str(ferr)[:20]
                if ch.deferre is None and ("déf" in fs or "def" in fs or "d4" in fs):
                    ch.deferre = str(ferr)[:10]
                n_filled += 1

        # P2 — carrière / corde / record / charge
        nb_c = _i(r.get("nbCourses") or r.get("nbCourses_numeric") or r.get("Courses_courues"))
        if ch.nb_courses is None and nb_c is not None:
            ch.nb_courses = nb_c
            n_filled += 1
        nv = _i(r.get("nombre_victoire"))
        if getattr(ch, "victoires_carriere", None) is None and nv is not None:
            ch.victoires_carriere = nv
            n_filled += 1
        np_ = _i(r.get("nombre_place"))
        if getattr(ch, "places_carriere", None) is None and np_ is not None:
            ch.places_carriere = np_
            n_filled += 1
        if ch.gains_moyenne_carriere_eur is None and ch.gains_totaux_eur and ch.nb_courses:
            ch.gains_moyenne_carriere_eur = ch.gains_totaux_eur / max(1, ch.nb_courses)

        corde = _i(r.get("placeCorde") or r.get("corde") or r.get("Place_Corde"))
        if corde is not None and getattr(ch, "numero_autostart", None) is None:
            # plat : place de corde ; stockée si autostart vide
            try:
                ch.numero_autostart = corde
                flags_add.append(f"BZH_CORDE:{corde}")
                n_filled += 1
            except Exception:
                pass

        rec = _f(r.get("distanceRecord_sec"))
        if rec is not None and getattr(ch, "record_chrono_sec", None) is None:
            ch.record_chrono_sec = rec
            n_filled += 1

        # charge jockey du jour (info)
        nj_today = _i(r.get("nbCourses_jockey_today"))
        if nj_today is not None:
            flags_add.append(f"BZH_JOCKEY_COURSES_JOUR:{nj_today}")

        # driver / entraîneur si vides
        if not ch.driver_jockey and r.get("driver"):
            ch.driver_jockey = str(r["driver"]).strip()[:60]
            n_filled += 1
        if not ch.entraineur and (r.get("coach") or r.get("entraineur")):
            ch.entraineur = str(r.get("coach") or r.get("entraineur")).strip()[:60]
            n_filled += 1

        # ========== P0 — signaux ==========
        # Avis entraîneur
        avis = _norm_avis(
            r.get("avisEntraineur") or r.get("avis") or r.get("avis_str") or r.get("avis_entraineur")
        )
        if avis == "POSITIF":
            signals.append(
                CatalogSignal(
                    id="B65",
                    valeur_brute=_BONUS_AVIS_POS,
                    catalog="B",
                    famille="C",
                    confiance="STRICT",
                    justification="Turf.bzh avis entraîneur POSITIF",
                )
            )
            flags_add.append("BZH_AVIS_POSITIF")
            n_signals["p0"] += 1
        elif avis == "NEGATIF":
            signals.append(
                CatalogSignal(
                    id="B66",
                    valeur_brute=_BONUS_AVIS_NEG,
                    catalog="B",
                    famille="C",
                    confiance="STRICT",
                    justification="Turf.bzh avis entraîneur NEGATIF (malus fort)",
                )
            )
            flags_add.append("BZH_AVIS_NEGATIF")
            n_signals["p0"] += 1
        elif avis == "NEUTRE":
            flags_add.append("BZH_AVIS_NEUTRE")

        # IMDC
        imdc = _f(r.get("IDMC") or r.get("IMDC") or r.get("imdc"))
        if imdc is not None:
            flags_add.append(f"BZH_IMDC:{imdc:.2f}")
            if imdc < -5:
                signals.append(
                    CatalogSignal(
                        id="B67",
                        valeur_brute=_BONUS_IMDC_DOWN,
                        catalog="B",
                        famille="C",
                        confiance="DEGRADE",
                        justification=f"Turf.bzh IMDC={imdc:.1f} (descente catégorie)",
                    )
                )
                n_signals["p0"] += 1
            elif imdc > 8:
                signals.append(
                    CatalogSignal(
                        id="B67",
                        valeur_brute=_BONUS_IMDC_UP,
                        catalog="B",
                        famille="C",
                        confiance="MINIMAL",
                        justification=f"Turf.bzh IMDC={imdc:.1f} (montée catégorie)",
                    )
                )
                n_signals["p0"] += 1

        # Cote BZH vs marché
        if cote_b and cote_mkt and cote_mkt > 0:
            ratio = cote_mkt / cote_b
            if ratio >= 1.35 and cote_b <= 25:
                # marché sous-estime (value)
                signals.append(
                    CatalogSignal(
                        id="B68",
                        valeur_brute=_BONUS_VALUE_BZH,
                        catalog="B",
                        famille="C",
                        confiance="DEGRADE",
                        justification=(
                            f"Value BZH: marché {cote_mkt:.1f} vs BZH {cote_b:.1f} "
                            f"(×{ratio:.2f})"
                        ),
                    )
                )
                flags_add.append("BZH_VALUE")
                n_signals["p0"] += 1
            elif ratio <= 0.75 and cote_mkt <= 8:
                # marché surjoue (faux favori potentiel)
                signals.append(
                    CatalogSignal(
                        id="B69",
                        valeur_brute=_BONUS_SURCOTE,
                        catalog="B",
                        famille="C",
                        confiance="MINIMAL",
                        justification=(
                            f"Surcote marché: PMU {cote_mkt:.1f} vs BZH {cote_b:.1f} "
                            f"(×{ratio:.2f})"
                        ),
                    )
                )
                flags_add.append("BZH_SURCOTE_MARCHE")
                n_signals["p0"] += 1

        # IA multi-places
        ri = rank_ia.get(ch.numero)
        top1 = _ia_proba(r.get("Top1IA")) or 0.0
        esp = _ia_proba(r.get("Esp_Victoire"))
        if ri is not None and ri <= 3:
            signals.append(
                CatalogSignal(
                    id="B61",
                    valeur_brute=_BONUS_IA_RANG[ri],
                    catalog="B",
                    famille="C",
                    confiance="STRICT" if ri == 1 else "DEGRADE",
                    justification=f"Turf.bzh IA Gagnant rang {ri}/{len(rank_ia)} (p={top1:.1%})",
                )
            )
            n_signals["p0"] += 1
        if top1 >= _TOP1IA_SEUIL and (ri is None or ri > 3):
            signals.append(
                CatalogSignal(
                    id="B62",
                    valeur_brute=_BONUS_IA_PCT,
                    catalog="B",
                    famille="C",
                    confiance="MINIMAL",
                    justification=f"Turf.bzh Top1IA={top1:.1%} (≥10%) hors top3 relatif",
                )
            )
            n_signals["p0"] += 1
        # Top2–Top5 proba relative dans le peloton
        for place, key in ((2, "Top2IA"), (3, "top3IA"), (3, "Top3IA"), (4, "top4IA"), (5, "top5IA")):
            if key not in r:
                continue
            # rang relatif déjà via Top1IA ; ici on boost si proba place significative
            pv = _ia_proba(r.get(key))
            if pv is not None and pv >= 0.08 and place >= 2:
                # un seul bonus multi par cheval (meilleure place)
                if not any(s.id == "B70" for s in signals):
                    signals.append(
                        CatalogSignal(
                            id="B70",
                            valeur_brute=_BONUS_IA_MULTI.get(place, 1.5),
                            catalog="B",
                            famille="C",
                            confiance="MINIMAL",
                            justification=f"Turf.bzh {key}={pv:.1%} (multi-places)",
                        )
                    )
                    n_signals["p0"] += 1
                break
        if esp is not None and esp >= 0.12:
            flags_add.append(f"BZH_ESP_VICTOIRE:{esp:.2f}")

        # ELO cheval (existant B63)
        relo = rank_elo.get(ch.numero)
        if relo is not None and relo <= 3:
            signals.append(
                CatalogSignal(
                    id="B63",
                    valeur_brute=_BONUS_ELO_RANG[relo],
                    catalog="B",
                    famille="C",
                    confiance="DEGRADE",
                    justification=(
                        f"Turf.bzh ELO cheval rang {relo}/{len(rank_elo)} "
                        f"(elo={r.get('pointsCheval')})"
                    ),
                )
            )
            n_signals["p0"] += 1
        if ri is not None and ri <= 3 and relo is not None and relo <= 3:
            signals.append(
                CatalogSignal(
                    id="B64",
                    valeur_brute=_BONUS_SYNERGIE,
                    catalog="B",
                    famille="C",
                    confiance="STRICT",
                    justification=f"Synergie IA top{ri} + ELO top{relo}",
                )
            )
            n_signals["p0"] += 1

        # ========== P1 — signaux ==========
        syn = _f(r.get("synergie_jch") or r.get("Synergie_JCh"))
        if syn is not None and syn >= 1.05:
            signals.append(
                CatalogSignal(
                    id="B71",
                    valeur_brute=_BONUS_SYNERGIE_JCH,
                    catalog="B",
                    famille="C",
                    confiance="DEGRADE",
                    justification=f"Turf.bzh synergie JCh={syn:.2f}",
                )
            )
            flags_add.append(f"BZH_SYNERGIE_JCH:{syn:.2f}")
            n_signals["p1"] += 1

        # changements ferrure / D4
        chgt_f = r.get("chgt_ferrure") or r.get("changement_ferrure")
        first_f = r.get("first_time_ferrure")
        d4 = r.get("deferre4") or r.get("deferre")
        if _truthy(d4) or (ferr and "d4" in str(ferr).lower()):
            signals.append(
                CatalogSignal(
                    id="B74",
                    valeur_brute=_BONUS_D4,
                    catalog="B",
                    famille="C",
                    confiance="DEGRADE",
                    justification="Turf.bzh déferré 4 pieds (D4)",
                )
            )
            flags_add.append("BZH_D4")
            if ch.deferre is None:
                ch.deferre = "D4"
            n_signals["p1"] += 1
        elif _truthy(chgt_f) or _truthy(first_f):
            signals.append(
                CatalogSignal(
                    id="B74",
                    valeur_brute=_BONUS_CHGT_FERRURE,
                    catalog="B",
                    famille="C",
                    confiance="MINIMAL",
                    justification="Turf.bzh changement / première ferrure",
                )
            )
            flags_add.append("BZH_CHGT_FERRURE")
            n_signals["p1"] += 1

        if _truthy(r.get("chgt_driver") or r.get("changement_driver")):
            flags_add.append("BZH_CHGT_DRIVER")

        # ELO jockey / entraîneur (flags + soft)
        rj = rank_elo_j.get(ch.numero)
        rt = rank_elo_t.get(ch.numero)
        if rj is not None and rj <= 3:
            flags_add.append(f"BZH_ELO_JOCKEY_TOP{rj}")
        if rt is not None and rt <= 3:
            flags_add.append(f"BZH_ELO_TRAINER_TOP{rt}")
        tp90 = _f(r.get("Cumul_Cheval_90D") or r.get("Moy_Points_Cheval_90D"))
        if tp90 is not None:
            flags_add.append(f"BZH_TP90:{tp90:.1f}")

        # taux incident
        ti = _f(r.get("tauxIncident_numeric") or r.get("tauxIncident") or r.get("Taux_Incident"))
        if ti is not None:
            # si en %
            if ti > 1.5:
                ti = ti / 100.0
            flags_add.append(f"BZH_TAUX_INCIDENT:{ti:.2f}")
            if ti >= 0.25:
                signals.append(
                    CatalogSignal(
                        id="B73",
                        valeur_brute=_BONUS_INCIDENT_MALUS,
                        catalog="B",
                        famille="C",
                        confiance="DEGRADE",
                        justification=f"Turf.bzh taux incident élevé ({ti:.0%})",
                    )
                )
                n_signals["p1"] += 1

        # ex-favori
        exf = r.get("ex_favori") or r.get("exFav") or r.get("ExFav")
        is_exfav = False
        if isinstance(exf, bool):
            is_exfav = exf
        elif exf is not None:
            s = str(exf)
            is_exfav = ("FG" in s) or ("Favori" in s) or _truthy(exf)
        if is_exfav:
            signals.append(
                CatalogSignal(
                    id="B72",
                    valeur_brute=_BONUS_EXFAV,
                    catalog="B",
                    famille="C",
                    confiance="MINIMAL",
                    justification="Turf.bzh ex-favori (déjà joué favori)",
                )
            )
            flags_add.append("BZH_EXFAV")
            n_signals["p1"] += 1

        # alloc ratio / rank prec
        ar = _f(r.get("alloc_ratio"))
        if ar is not None:
            flags_add.append(f"BZH_ALLOC_RATIO:{ar:.2f}")
        rp = _i(r.get("rank_prec"))
        if rp is not None:
            flags_add.append(f"BZH_RANK_PREC:{rp}")

        # ========== application signaux / flags ==========
        if signals:
            ch.signaux_precalcules = list(ch.signaux_precalcules or []) + signals
            n_bonus += len(signals)
            flags_add.append("BZH_IA_ELO_BONUS")

        if ri is not None and ri <= 5:
            ch.citations_top5_par_source = {
                **(ch.citations_top5_par_source or {}),
                "TurfBZH_IA": True,
            }
            ch.icp_global = (ch.icp_global or 0) + 1

        flags_add.append("ENRICHI_TURFBZH")
        flags_add.append("ENRICHI_TURFBZH_P012")
        ch.flags = list(dict.fromkeys((ch.flags or []) + flags_add))

    return {
        "status": "OK",
        "url": build_turfbzh_url(date_iso, reunion, course),
        "n_partants": len(rows),
        "n_filled": n_filled,
        "n_bonus": n_bonus,
        "n_signals_p0": n_signals["p0"],
        "n_signals_p1": n_signals["p1"],
        "n_signals_p2_flags": n_signals["p2"],
        "race_difficulty": (getattr(race, "meta_sources", {}) or {}).get("turfbzh", {}).get(
            "race_difficulty"
        ),
        "top_ia": [
            {"num": n, "rang": rank_ia[n]}
            for n in sorted(rank_ia, key=lambda x: rank_ia[x])[:5]
        ],
        "top_elo": [
            {"num": n, "rang": rank_elo[n]}
            for n in sorted(rank_elo, key=lambda x: rank_elo[x])[:5]
        ],
    }
