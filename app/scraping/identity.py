"""identity.py -- Contrôles d'identité de course (v1.29.40).

Objectif : ne jamais fusionner / enrichir une course avec les données d'une
AUTRE course (autre jour, autre réunion, autre course du même hippodrome).
Trois garde-fous complémentaires :
  1. identité attendue (date, hippodrome, réunion, course) dérivée de la
     découverte OU des URLs elles-mêmes (donc valable aussi sur /retry et en
     mode réunion+course sans hippodrome) ;
  2. concordance des NOMS de chevaux (jamais le numéro seul) ;
  3. filtre « as-of » : exclure des historiques toute perf datée du jour de la
     course ou après (anti fuite temporelle en rejeu).
"""
from __future__ import annotations
import re
import unicodedata
from collections import Counter
from datetime import date as date_cls, datetime
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

SEUIL_NOMS = 0.70


def norm_nom(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)          # suffixes pays (FR), (IRE)...
    return re.sub(r"[^a-z0-9]+", "", s)


def _meme_nom(a: str, b: str) -> bool:
    na, nb = norm_nom(a), norm_nom(b)
    if not na or not nb:
        return False
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= 0.88


def ratio_concordance(chevaux: Iterable[Any], noms_par_numero: Dict[int, str]) -> Tuple[float, int]:
    """Part des partants de `chevaux` dont le nom concorde avec celui de la
    source pour le même numéro. Retourne (ratio, nb_comparables)."""
    comparables = 0
    ok = 0
    for c in chevaux:
        autre = noms_par_numero.get(getattr(c, "numero", None))
        if not autre or not getattr(c, "nom", None):
            continue
        comparables += 1
        if _meme_nom(c.nom, autre):
            ok += 1
    return (ok / comparables if comparables else 1.0, comparables)


def noms_concordent(chevaux: Iterable[Any], noms_par_numero: Dict[int, str],
                    seuil: float = SEUIL_NOMS, min_comparables: int = 4) -> Tuple[bool, float]:
    """True si la source décrit les mêmes chevaux. Trop peu de noms
    comparables => on ne rejette pas (rien à comparer)."""
    r, n = ratio_concordance(chevaux, noms_par_numero)
    if n < min_comparables:
        return True, r
    return r >= seuil, r


# ---------------------------------------------------------------- étiquettes R/C
_RC_RE = re.compile(r"R\s*(\d+)\s*C\s*(\d+)", re.I)
_C_RE = re.compile(r"^\s*C\s*(\d+)\s*$", re.I)


def parse_label_rc(label: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    s = str(label or "")
    m = _RC_RE.search(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _C_RE.match(s)
    if m:
        return None, int(m.group(1))
    return None, None


# ---------------------------------------------------------------- identité via URLs
def identite_depuis_urls(urls: Iterable[str]) -> Dict[str, Any]:
    """Déduit (date, réunion, course, hippodromes) des URLs de collecte, par
    VOTE majoritaire entre sources. Ne s'appuie que sur des motifs d'URL
    vérifiés : Turfoo (/AAMMJJ/reunionN-hippo/courseM), CanalTurf
    (/AAAA-MM-JJ/hippo/), Zone-Turf (/rN-hippo-id.html#M), Geny (slug daté)."""
    dates: List[str] = []
    reunions: List[int] = []
    courses: List[int] = []
    hippos: List[str] = []
    for u in urls or []:
        u = str(u)
        m = re.search(r"turfoo\.fr/(?:programmes|resultats)-courses/(\d{2})(\d{2})(\d{2})/reunion(\d+)-([\w\-]+)/course(\d+)", u)
        if m:
            dates.append(f"20{m.group(1)}-{m.group(2)}-{m.group(3)}")
            reunions.append(int(m.group(4))); hippos.append(m.group(5).replace("-", " "))
            courses.append(int(m.group(6)))
            continue
        m = re.search(r"canalturf\.com/pronostics-PMU/(\d{4}-\d{2}-\d{2})/([\w\-]+)/", u)
        if m:
            dates.append(m.group(1)); hippos.append(m.group(2).replace("-", " "))
            continue
        m = re.search(r"zone-turf\.fr/programmes/r(\d+)-([a-z\-]+?)-\d+\.html(?:#(\d+))?", u, re.I)
        if m:
            reunions.append(int(m.group(1))); hippos.append(m.group(2).replace("-", " "))
            if m.group(3):
                courses.append(int(m.group(3)))
            continue
        m = re.search(r"geny\.com/course/\d+-(\d{4}-\d{2}-\d{2})-([a-z0-9\-]+?)-", u, re.I)
        if m:
            dates.append(m.group(1)); hippos.append(m.group(2).replace("-", " "))

    def _vote(xs):
        return Counter(xs).most_common(1)[0][0] if xs else None
    return {"date": _vote(dates), "reunion": _vote(reunions), "course": _vote(courses),
            "hippodrome": _vote(hippos)}


def construire_identite_attendue(discovery_report: Optional[dict], urls: Iterable[str]) -> Dict[str, Any]:
    """Identité attendue = demande explicite (découverte) complétée par les URLs."""
    d = dict(identite_depuis_urls(urls))
    for k_src, k_dst in (("hippodrome_attendu", "hippodrome"), ("date", "date"),
                         ("reunion_num", "reunion"), ("course_num", "course")):
        v = (discovery_report or {}).get(k_src)
        if v not in (None, ""):
            d[k_dst] = v
    return d


def identite_incoherente(race: Any, attendu: Optional[Dict[str, Any]]) -> Optional[str]:
    """Message d'incohérence ou None. Ne rejette que sur contradiction EXPLICITE."""
    if not attendu:
        return None
    from app.scraping.hippodrome_normalize import hippodromes_match
    exp_h = attendu.get("hippodrome")
    act_h = str(getattr(race, "hippodrome", "") or "").strip()
    if exp_h and act_h and act_h.upper() not in {"INCONNU", "UNKNOWN"}:
        try:
            ok = hippodromes_match(str(exp_h), act_h)
        except Exception:
            ok = str(exp_h).lower() in act_h.lower()
        if not ok:
            return f"hippodrome incohérent: attendu={exp_h!r}, trouvé={act_h!r}"
    exp_d = attendu.get("date")
    act_d = getattr(race, "date_course", None)
    if exp_d and act_d and str(exp_d)[:10] != str(act_d)[:10]:
        return f"date incohérente: attendue={str(exp_d)[:10]}, trouvée={str(act_d)[:10]}"
    r_act, c_act = parse_label_rc(getattr(race, "reunion_course_label", None))
    exp_r, exp_c = attendu.get("reunion"), attendu.get("course")
    if exp_r is not None and r_act is not None and int(exp_r) != r_act:
        return f"réunion incohérente: attendue=R{exp_r}, trouvée=R{r_act}"
    if exp_c is not None and c_act is not None and int(exp_c) != c_act:
        return f"course incohérente: attendue=C{exp_c}, trouvée=C{c_act}"
    return None


# ---------------------------------------------------------------- as-of
def _to_date(d) -> Optional[date_cls]:
    if d is None or d == "":
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date_cls):
        return d
    try:
        return date_cls.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def filtrer_avant(items, date_course, attr: str = "date"):
    """Garde les perfs STRICTEMENT antérieures au jour de la course (les perfs
    sans date exploitable sont conservées : rien ne permet de les exclure)."""
    ref = _to_date(date_course)
    if ref is None or not items:
        return items
    out = []
    for it in items:
        d = _to_date(getattr(it, attr, None))
        if d is None or d < ref:
            out.append(it)
    return out


def asof_attr(obj, attr: str, date_course) -> None:
    if obj is None:
        return
    cur = getattr(obj, attr, None)
    if cur:
        try:
            setattr(obj, attr, filtrer_avant(cur, date_course))
        except Exception:
            pass


def est_rejeu(date_course) -> bool:
    d = _to_date(date_course)
    if d is None:
        return False
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        today = date_cls.today()
    return d < today
