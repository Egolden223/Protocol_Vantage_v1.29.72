"""Equidia.fr — enrichissement PROGRAMME (pré-course) + parse ARRIVÉE (audit).

Même URL : /courses/{YYYY-MM-DD}/R{n}/C{n}
- Avant course : tableau partants (N°, musique, Pds, Cde, Val.) → ENRICHISSEMENT
- Après course : tableau arrivée / rapports → AUDIT + contexte (météo, conditions,
  équipements, musique) SANS cotes précourses (v1.29.66.3)

v1.29.66.3 :
- détection PRE/POST renforcée (marqueurs Arrivées / Rapports / Replay / Red. Km)
- enrichissement POST limité (pas de cote_matin Equidia)
- snapshot HTML précourse (EQUIDIA_SNAPSHOT_DIR)
- secours cotes matin via turf.bzh si TURFBZH_API_KEY
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.models import Cheval, RaceContext, CatalogSignal

logger = logging.getLogger("vantage.scraping.equidia")

_MUSIQUE_RE = re.compile(r"(?:[0-9DTAdta][a-zA-Z](?:\(\d{2}\))?)+" )
_GAINS_RE = re.compile(r"Gains?\s*([\d\s\xa0\u202f]+)\s*€", re.I)
_PDS_RE = re.compile(r"Pds\s*:\s*([\d.,]+)", re.I)
_CDE_RE = re.compile(r"Cde\s*:\s*(\d+)", re.I)
_VAL_RE = re.compile(r"Val\.?\s*([\d.,]+)", re.I)

_POST_MARKERS = (
    "voir le replay",
    "arrivées",
    "arrivees",
    "rapports",
    "red. km",
    "red.km",
    "l'arrivée",
    "l'arrivee",
    "ordre d'arrivée",
    "ordre d'arrivee",
)


@dataclass
class EquidiaPartant:
    numero: int
    nom: str
    musique: Optional[str] = None
    driver: Optional[str] = None
    entraineur: Optional[str] = None
    poids_kg: Optional[float] = None
    corde: Optional[int] = None
    valeur: Optional[float] = None
    gains_eur: Optional[float] = None
    note_20: Optional[float] = None
    cote: Optional[float] = None
    rang_arrivee: Optional[int] = None
    non_partant: bool = False
    oeilleres: Optional[str] = None
    deferre: Optional[str] = None
    bonnet: Optional[bool] = None
    attache_langue: Optional[bool] = None
    commentaire: Optional[str] = None
    forme_note: Optional[float] = None


def build_equidia_url(date_iso: str, reunion: int, course: int) -> str:
    return f"https://www.equidia.fr/courses/{date_iso}/R{reunion}/C{course}"


def save_equidia_snapshot(
    date_iso: str, reunion: int, course: int, html: str, mode: str
) -> Optional[str]:
    """P2 — sauvegarde HTML pour rejeu fidèle (précourse prioritaire)."""
    if not html or len(html) < 200:
        return None
    try:
        from app.config import BASE_DIR
        root = Path(os.environ.get("EQUIDIA_SNAPSHOT_DIR", str(BASE_DIR / "data" / "equidia_snapshots")))
        root.mkdir(parents=True, exist_ok=True)
        fname = f"{date_iso}_R{int(reunion)}C{int(course)}_{mode}.html"
        path = root / fname
        path.write_text(html, encoding="utf-8", errors="replace")
        logger.info("Equidia snapshot %s (%d octets)", path, len(html))
        return str(path)
    except Exception as e:
        logger.warning("Equidia snapshot échec: %s", e)
        return None


def load_equidia_snapshot(date_iso: str, reunion: int, course: int, prefer_mode: str = "programme") -> Optional[str]:
    """Charge un snapshot local s'il existe (prefer programme pour walk-forward précourse)."""
    try:
        from app.config import BASE_DIR
        root = Path(os.environ.get("EQUIDIA_SNAPSHOT_DIR", str(BASE_DIR / "data" / "equidia_snapshots")))
        candidates = [
            root / f"{date_iso}_R{int(reunion)}C{int(course)}_{prefer_mode}.html",
            root / f"{date_iso}_R{int(reunion)}C{int(course)}_programme.html",
            root / f"{date_iso}_R{int(reunion)}C{int(course)}_arrivee.html",
            root / f"{date_iso}_R{int(reunion)}C{int(course)}_unknown.html",
        ]
        for p in candidates:
            if p.is_file() and p.stat().st_size > 200:
                return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("Equidia load snapshot: %s", e)
    return None


def _extract_server_app_state(html: str) -> Optional[dict]:
    import json
    m = re.search(
        r'<script id="serverApp-state" type="application/json">(.*?)</script>',
        html or "",
        re.S,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception as e:
        logger.warning("Equidia serverApp-state JSON: %s", e)
        return None


def _oeil_code_to_label(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    c = str(code).strip().upper()
    mapping = {
        "N": "SANS_OEILLERES",
        "O": "OEILLERES",
        "A": "AUSTRALIENNES",
        "OA": "OEILLERES_AUSTRALIENNES",
        "S": "SANS_OEILLERES",
    }
    return mapping.get(c, c)


def parse_equidia_state(html: str, date_iso: str, reunion: int, course: int) -> tuple:
    state = _extract_server_app_state(html)
    if not state:
        return {}, []

    key_c = f"v2/courses/{date_iso}/R{reunion}/C{course}"
    course_obj = state.get(key_c) or {}
    meta: dict = {}
    if course_obj:
        val_p = course_obj.get("val_penetr")
        if val_p is not None:
            try:
                meta["penetrometre"] = float(str(val_p).replace(",", "."))
            except (TypeError, ValueError):
                pass
        if course_obj.get("etat_terrain"):
            meta["etat_terrain"] = str(course_obj["etat_terrain"]).strip()
        if course_obj.get("lib_piste_course"):
            meta["type_piste"] = str(course_obj["lib_piste_course"]).strip()
        if course_obj.get("distance"):
            try:
                meta["distance_m"] = int(float(str(course_obj["distance"]).replace(",", ".")))
            except (TypeError, ValueError):
                pass
        if course_obj.get("discipline") or course_obj.get("lib_discipline"):
            meta["discipline"] = str(course_obj.get("discipline") or course_obj.get("lib_discipline")).strip()
        reun = course_obj.get("reunion") or {}
        if reun.get("meteo_temperature") is not None:
            try:
                meta["meteo_temperature"] = float(str(reun["meteo_temperature"]).replace(",", "."))
            except (TypeError, ValueError):
                pass
        if reun.get("meteo_vent_force") is not None:
            try:
                meta["meteo_vent_force"] = float(str(reun["meteo_vent_force"]).replace(",", "."))
            except (TypeError, ValueError):
                pass
        neb = reun.get("meteo_nebulosite_libelle_court") or reun.get("meteo_nebulosite_code")
        if neb:
            meta["meteo_nebulosite"] = str(neb)
        vent_dir = reun.get("meteo_vent_direction")
        if isinstance(vent_dir, dict) and vent_dir.get("label"):
            meta["meteo_vent_direction"] = vent_dir["label"]
        elif isinstance(vent_dir, str):
            meta["meteo_vent_direction"] = vent_dir

    raw_parts = course_obj.get("partants") if course_obj else None
    if not raw_parts:
        note_key = f"v2/note/{date_iso}/R{reunion}/C{course}?range=[0,99]"
        raw_parts = state.get(note_key) or []
    if not raw_parts:
        for k, v in state.items():
            if k.startswith(f"v2/note/{date_iso}/R{reunion}/C{course}") and isinstance(v, list):
                raw_parts = v
                break

    partants: List[EquidiaPartant] = []
    for p in raw_parts or []:
        if not isinstance(p, dict):
            continue
        try:
            num = int(p.get("num_partant") or 0)
        except (TypeError, ValueError):
            continue
        if num <= 0:
            continue
        ch = p.get("cheval") or {}
        monte = p.get("monte") or {}
        ent = p.get("entraineur") or ch.get("entraineur") or {}
        if isinstance(ent, str):
            ent_nom = ent
        else:
            ent_nom = (ent or {}).get("nom_entraineur")
        note_obj = p.get("interne_note_partant") or {}
        note_20 = None
        forme_note = None
        if isinstance(note_obj, dict):
            if note_obj.get("note_equidia") is not None:
                try:
                    note_20 = float(note_obj["note_equidia"])
                except (TypeError, ValueError):
                    pass
            if note_obj.get("forme_cheval") is not None:
                try:
                    forme_note = float(note_obj["forme_cheval"])
                except (TypeError, ValueError):
                    pass
        poids = p.get("pds_cond_monte_partant") or p.get("pds_calc_hand_partant")
        try:
            poids_kg = float(poids) if poids is not None else None
        except (TypeError, ValueError):
            poids_kg = None
        gains = p.get("gains_carriere") or ch.get("gains_carriere")
        try:
            gains_eur = float(gains) if gains is not None else None
        except (TypeError, ValueError):
            gains_eur = None
        valeur = p.get("valeur") or ch.get("valeur")
        try:
            valeur_f = float(valeur) if valeur is not None else None
        except (TypeError, ValueError):
            valeur_f = None
        itw = p.get("interview") or {}
        commentaire = None
        if isinstance(itw, dict):
            commentaire = itw.get("texte") or None
        oeil = _oeil_code_to_label(p.get("oeil_partant"))
        defer = (p.get("deferrer_partant") or "").strip() or None
        if not defer and isinstance(ch, dict):
            idef = ch.get("intention_deferrer")
            if idef:
                defer = str(idef).strip()
        statut = str(p.get("statut_part") or "").upper()
        non_partant = statut in ("NP", "NON_PARTANT", "AR") and str(p.get("num_place_arrivee") or "") in ("", "0")
        rang = None
        npa = p.get("num_place_arrivee")
        if npa not in (None, "", "0", 0):
            try:
                rang = int(str(npa).lstrip("0") or "0") or None
            except ValueError:
                rang = None
        cote = None
        for ck in ("cote", "cote_pmu", "rapport", "cote_direct"):
            if p.get(ck) is not None:
                try:
                    cote = float(str(p[ck]).replace(",", "."))
                    if not (1.01 <= cote < 500):
                        cote = None
                except (TypeError, ValueError):
                    cote = None
                if cote is not None:
                    break
        partants.append(EquidiaPartant(
            numero=num,
            nom=str(ch.get("nom_cheval") or p.get("nom") or f"N{num}"),
            musique=(ch.get("musique") or p.get("musique") or p.get("short_musique") or None),
            driver=(monte.get("nom_monte") if isinstance(monte, dict) else None),
            entraineur=ent_nom,
            poids_kg=poids_kg,
            valeur=valeur_f,
            gains_eur=gains_eur,
            note_20=note_20,
            forme_note=forme_note,
            oeilleres=oeil,
            deferre=defer,
            bonnet=p.get("bonnet") if isinstance(p.get("bonnet"), bool) else None,
            attache_langue=p.get("attache_langue") if isinstance(p.get("attache_langue"), bool) else None,
            commentaire=commentaire,
            rang_arrivee=rang,
            non_partant=bool(non_partant),
            cote=cote,
        ))
    return meta, partants


def _parse_float(s: str) -> Optional[float]:
    s = (s or "").replace("\xa0", "").replace("\u202f", "").replace(" ", "").replace(",", ".").replace("€", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _split_blob(blob: str) -> dict:
    out: dict = {
        "nom": None, "driver": None, "entraineur": None, "musique": None,
        "poids_kg": None, "corde": None, "valeur": None, "gains_eur": None,
    }
    blob = re.sub(r"\s+", " ", (blob or "")).strip()
    if not blob:
        return out
    gm = _GAINS_RE.search(blob)
    if gm:
        out["gains_eur"] = _parse_float(gm.group(1))
    pm = _PDS_RE.search(blob)
    if pm:
        out["poids_kg"] = _parse_float(pm.group(1))
    cm = _CDE_RE.search(blob)
    if cm:
        out["corde"] = int(cm.group(1))
    vm = _VAL_RE.search(blob)
    if vm:
        out["valeur"] = _parse_float(vm.group(1))
    mus = _MUSIQUE_RE.findall(blob)
    if mus:
        out["musique"] = max(mus, key=len)
    if "|" in blob:
        left, right = blob.split("|", 1)
        left, right = left.strip(), right.strip()
        if out["musique"] and out["musique"] in right:
            right = right.replace(out["musique"], "").strip()
        right = _GAINS_RE.sub("", right)
        right = _PDS_RE.sub("", right)
        right = _VAL_RE.sub("", right)
        right = _CDE_RE.sub("", right)
        right = re.sub(r"\bInterview\b", "", right, flags=re.I)
        out["entraineur"] = re.split(r"\s{2,}", right.strip())[0][:50] or None
        dm = re.search(
            r"^(.*)\s+((?:[A-ZÀ-Ü]{1,4}\.\s*)?[A-ZÀ-Ü][A-ZÀ-Ü\-`']+(?:\s+[A-ZÀ-Ü][A-ZÀ-Ü\-`']+)?)\s*$",
            left,
        )
        if dm:
            out["nom"] = dm.group(1).strip()
            out["driver"] = dm.group(2).strip()
        else:
            out["nom"] = left[:40]
    else:
        out["nom"] = blob.split(" Pds")[0].split(" Gains")[0][:40].strip()
    return out


def detect_equidia_page_mode(html: str) -> str:
    """Retourne 'programme' | 'arrivee' | 'unknown'."""
    if not html:
        return "unknown"
    low = html[:80000].lower()
    post_hits = sum(1 for m in _POST_MARKERS if m in low)
    if post_hits >= 2:
        return "arrivee"
    if "voir le replay" in low or ("red. km" in low and "1 er" in low):
        return "arrivee"
    if re.search(r"\b1\s*er\b", html) and ("Red. Km" in html or "rapport" in low):
        return "arrivee"
    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) < 3:
            continue
        header = " ".join(c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"]))
        if "class" in header and ("cheval" in header or "driver" in header):
            return "arrivee"
        first_data = rows[1].get_text(" ", strip=True) if len(rows) > 1 else ""
        if re.match(r"^\d+\s*(er|e)\b", first_data, re.I):
            return "arrivee"
        if (("n°" in header or header.strip().startswith("n")) and "cheval" in header):
            return "programme"
    if "Pds :" in html or "Pds:" in html:
        return "programme"
    if post_hits >= 1:
        return "arrivee"
    return "unknown"


def parse_equidia_programme(html: str) -> List[EquidiaPartant]:
    soup = BeautifulSoup(html, "lxml")
    out: List[EquidiaPartant] = []
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) < 4:
            continue
        header = " ".join(c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"]))
        if any(x in header for x in ("gagnant", "placé", "combinaison", "rapport", "class")):
            continue
        if not (("n°" in header or header.strip().startswith("n")) and "cheval" in header):
            continue
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not cells or not cells[0].isdigit():
                continue
            num = int(cells[0])
            if not 1 <= num <= 20:
                continue
            blob = cells[1] if len(cells) > 1 else ""
            info = _split_blob(blob)
            cote = _parse_float(cells[2]) if len(cells) > 2 else None
            if cote is not None and not (1.01 <= cote < 500):
                cote = None
            nom = info.get("nom") or f"#{num}"
            if re.match(r"^[\d\s,./]+$", nom):
                continue
            out.append(EquidiaPartant(
                numero=num, nom=nom, musique=info.get("musique"), driver=info.get("driver"),
                entraineur=info.get("entraineur"), poids_kg=info.get("poids_kg"),
                corde=info.get("corde"), valeur=info.get("valeur"), gains_eur=info.get("gains_eur"), cote=cote,
            ))
        if out:
            break
    return out


def parse_equidia_arrivee(html: str) -> List[EquidiaPartant]:
    soup = BeautifulSoup(html, "lxml")
    by_num: Dict[int, EquidiaPartant] = {}
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) < 4:
            continue
        header = " ".join(c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"]))
        if any(x in header for x in ("gagnant", "placé", "combinaison", "rapport", "tiercé", "quarté", "multi")):
            continue
        if "class" not in header and "cheval" not in header:
            continue
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            c0 = cells[0].strip()
            rang = num = None
            is_np = False
            if re.match(r"^\d+\s*(er|e|ème)?$", c0, re.I) and cells[1].isdigit():
                rang = int(re.sub(r"\D", "", c0) or "0") or None
                num = int(cells[1])
            elif re.search(r"disqual|NP|non\s*partant", c0, re.I) and cells[1].isdigit():
                num = int(cells[1])
                is_np = bool(re.search(r"NP|non\s*partant", c0, re.I))
            else:
                continue
            if not 1 <= num <= 20:
                continue
            info = _split_blob(cells[2])
            by_num[num] = EquidiaPartant(
                numero=num, nom=info.get("nom") or f"#{num}", musique=info.get("musique"),
                driver=info.get("driver"), entraineur=info.get("entraineur"),
                gains_eur=info.get("gains_eur"), rang_arrivee=rang, non_partant=is_np,
            )
        if by_num:
            break
    return [by_num[k] for k in sorted(by_num.keys())]


def parse_equidia_partants(html: str) -> List[EquidiaPartant]:
    mode = detect_equidia_page_mode(html)
    if mode == "arrivee":
        return parse_equidia_arrivee(html)
    return parse_equidia_programme(html)


def fetch_equidia_html(date_iso: str, reunion: int, course: int) -> str:
    return fetch_html(build_equidia_url(date_iso, reunion, course))


def _apply_meta_to_race(race: RaceContext, meta: dict, html: str) -> None:
    if meta.get("penetrometre") is not None and getattr(race, "penetrometre", None) is None:
        race.penetrometre = meta["penetrometre"]
    if meta.get("etat_terrain") and not getattr(race, "etat_terrain", None):
        try:
            race.etat_terrain = meta["etat_terrain"]
        except Exception:
            pass
    for mk in ("meteo_temperature", "meteo_vent_force", "meteo_nebulosite", "meteo_vent_direction", "type_piste"):
        if meta.get(mk) is not None:
            try:
                setattr(race, mk, meta[mk])
            except Exception:
                pass
    if getattr(race, "penetrometre", None) is None:
        try:
            from app.scraping.penetrometre import _parse_html_terrain
            _pv, _pl, _ph = _parse_html_terrain(html)
            if _pv is not None:
                race.penetrometre = float(_pv)
            if _pl and not getattr(race, "etat_terrain", None):
                try:
                    race.etat_terrain = _pl
                except Exception:
                    pass
        except Exception:
            pass


def _apply_partant_fields(chevaux: List[Cheval], partants: List[EquidiaPartant], *, allow_cote: bool) -> int:
    by_num = {p.numero: p for p in partants}
    n_filled = 0
    for ch in chevaux:
        p = by_num.get(ch.numero)
        if not p:
            continue
        if not ch.musique and p.musique:
            ch.musique = p.musique
            n_filled += 1
        if ch.poids_actuel_kg is None and p.poids_kg is not None:
            ch.poids_actuel_kg = p.poids_kg
            n_filled += 1
        if ch.valeur_pmu is None and p.valeur is not None:
            ch.valeur_pmu = p.valeur
            n_filled += 1
        if ch.gains_totaux_eur is None and p.gains_eur is not None:
            ch.gains_totaux_eur = p.gains_eur
            n_filled += 1
        if allow_cote and (ch.cote_matin is None or ch.cote_matin >= 500) and p.cote and 1.01 <= p.cote < 500:
            ch.cote_matin = p.cote
            n_filled += 1
        if not ch.driver_jockey and p.driver:
            ch.driver_jockey = p.driver
            n_filled += 1
        if not ch.entraineur and p.entraineur:
            ch.entraineur = p.entraineur
            n_filled += 1
        if getattr(p, "oeilleres", None) and not ch.oeilleres:
            ch.oeilleres = p.oeilleres
            if p.oeilleres not in ("SANS_OEILLERES", "SANS", "N", None, ""):
                ch.equip_changes = max(ch.equip_changes or 0, 1)
            n_filled += 1
        if getattr(p, "deferre", None) and not ch.deferre:
            ch.deferre = str(p.deferre).strip()
            if ch.ferrure_type is None:
                ch.ferrure_type = ch.deferre
                ch.ferrure_changes = max(ch.ferrure_changes or 0, 1)
            n_filled += 1
        if getattr(p, "bonnet", None) is True:
            ch.flags = list(dict.fromkeys((ch.flags or []) + ["EQ_BONNET"]))
        if getattr(p, "attache_langue", None) is True:
            ch.flags = list(dict.fromkeys((ch.flags or []) + ["EQ_ATTACHE_LANGUE"]))
        if getattr(p, "commentaire", None) and not ch.commentaire_derniere_course:
            ch.commentaire_derniere_course = str(p.commentaire)[:800]
            n_filled += 1
        if getattr(p, "forme_note", None) is not None:
            try:
                setattr(ch, "_equidia_forme", float(p.forme_note))
            except (TypeError, ValueError):
                pass
        if getattr(p, "note_20", None) is not None:
            try:
                note = float(p.note_20)
                if note >= 14:
                    conf = min(0.85, 0.45 + (note - 14) * 0.05)
                    val = min(8.0, (note - 13) * 1.2)
                    ch.signals = list(ch.signals or []) + [
                        CatalogSignal(
                            id="B60", valeur_brute=val, catalog="B", famille="C",
                            confiance=conf, justification=f"Note Equidia {note}/20",
                        )
                    ]
                    ch.flags = list(dict.fromkeys((ch.flags or []) + ["EQ_NOTE_BONUS"]))
                    n_filled += 1
            except (TypeError, ValueError):
                pass
        ch.flags = list(dict.fromkeys((ch.flags or []) + ["ENRICHI_EQUIDIA"]))
        if not allow_cote:
            ch.flags = list(dict.fromkeys((ch.flags or []) + ["EQUIDIA_POST_SANS_COTE"]))
    return n_filled


def enrich_race_with_equidia(race: RaceContext, chevaux: List[Cheval]) -> Dict[str, object]:
    """Enrichissement Equidia — PRE complet ; POST = contexte sans cotes (v1.29.66.3)."""
    from app.scraping.pmu_api import extraire_reunion_course, resolve_rc_from_programme
    from app.scraping.identity import noms_concordent

    rc = extraire_reunion_course(race) or resolve_rc_from_programme(race)
    if not rc or not race.date_course:
        return {"status": "SKIP", "reason": "R/C ou date absents", "n_filled": 0}
    reunion, course = rc
    date_iso = str(race.date_course)[:10]
    url = build_equidia_url(date_iso, reunion, course)

    html = None
    source_html = "live"
    snap = load_equidia_snapshot(date_iso, reunion, course, prefer_mode="programme")
    if snap:
        html = snap
        source_html = "snapshot_programme"
    else:
        try:
            html = fetch_equidia_html(date_iso, reunion, course)
        except Exception as e:
            logger.warning("Equidia fetch échec: %s", e)
            return {"status": "ERROR", "reason": str(e), "n_filled": 0, "url": url}

    meta, state_partants = parse_equidia_state(html, date_iso, reunion, course)
    if state_partants:
        _ok, _r = noms_concordent(chevaux, {p.numero: p.nom for p in state_partants if p.nom})
        if not _ok:
            return {
                "status": "SKIP",
                "reason": f"IDENTITE_EQUIDIA_REJETEE: noms concordants à {_r:.0%} (R{reunion}C{course})",
                "url": url,
                "n_filled": 0,
            }

    _apply_meta_to_race(race, meta, html)
    mode = detect_equidia_page_mode(html)

    snapshot_path = None
    if mode == "programme" and source_html == "live":
        snapshot_path = save_equidia_snapshot(date_iso, reunion, course, html, "programme")
    elif mode == "arrivee" and source_html == "live":
        snapshot_path = save_equidia_snapshot(date_iso, reunion, course, html, "arrivee")

    allow_cote = mode == "programme"
    if mode == "arrivee":
        partants = state_partants if state_partants else parse_equidia_arrivee(html)
    else:
        partants = state_partants if state_partants else parse_equidia_programme(html)
        if partants and not state_partants:
            _ok, _r = noms_concordent(chevaux, {p.numero: p.nom for p in partants if p.nom})
            if not _ok:
                return {
                    "status": "SKIP",
                    "reason": f"IDENTITE_EQUIDIA_REJETEE: noms concordants à {_r:.0%} (R{reunion}C{course})",
                    "url": url,
                    "n_filled": 0,
                }

    n_filled = _apply_partant_fields(chevaux, partants, allow_cote=allow_cote)

    # API payante turf.bzh retirée (v1.29.66.4, module turfbzh_api supprimé en v1.29.67.1) : l'enrichissement gratuit est dans turfbzh.py.
    tbz = {"status": "SKIP", "reason": "API turf.bzh désactivée (pas d'abonnement) — HTML public via turfbzh.py", "n_filled": 0,
           "source": "turfbzh_api_disabled"}

    return {
        "status": "OK" if partants or meta else "EMPTY",
        "mode": mode,
        "allow_cote_equidia": allow_cote,
        "url": url,
        "source_html": source_html,
        "snapshot": snapshot_path,
        "n_partants_eq": len(partants),
        "n_filled": n_filled,
        "turfbzh": tbz,
    }


def fetch_equidia_arrivee_for_audit(date_iso: str, reunion: int, course: int) -> Dict[str, object]:
    url = build_equidia_url(date_iso, reunion, course)
    try:
        html = fetch_html(url)
    except Exception as e:
        return {"status": "ERROR", "reason": str(e), "url": url}
    mode = detect_equidia_page_mode(html)
    if mode != "arrivee":
        return {"status": "SKIP", "reason": f"page mode={mode}, pas encore d'arrivée", "url": url}
    partants = parse_equidia_arrivee(html)
    ordre = [p.numero for p in sorted(
        [p for p in partants if p.rang_arrivee], key=lambda x: x.rang_arrivee or 99
    )]
    return {
        "status": "OK",
        "url": url,
        "mode": "arrivee",
        "ordre_arrivee": ordre,
        "partants": [
            {
                "numero": p.numero, "nom": p.nom, "rang": p.rang_arrivee,
                "np": p.non_partant, "gains": p.gains_eur, "musique": p.musique,
            }
            for p in partants
        ],
    }


def enrich_from_equidia_programme(race, chevaux: list) -> dict:
    out = {"status": "SKIPPED", "fields_filled": 0, "source": "equidia_programme"}
    try:
        before = sum(
            1 for c in chevaux
            for f in ("musique", "poids_actuel_kg", "valeur_pmu", "gains_totaux_eur")
            if getattr(c, f, None) in (None, "", [])
        )
        res = enrich_race_with_equidia(race, chevaux)
        after = sum(
            1 for c in chevaux
            for f in ("musique", "poids_actuel_kg", "valeur_pmu", "gains_totaux_eur")
            if getattr(c, f, None) in (None, "", [])
        )
        out["fields_filled"] = max(0, before - after)
        out["status"] = res.get("status", "OK")
        out["mode"] = res.get("mode")
        out["allow_cote_equidia"] = res.get("allow_cote_equidia")
    except Exception as e:
        out["status"] = "ERROR"
        out["error"] = str(e)[:200]
    return out
