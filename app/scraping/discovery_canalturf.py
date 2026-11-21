"""
discovery_canalturf.py -- Même principe que discovery.py (Turfoo) mais
pour CanalTurf.com. Vérifié le 04/08/2026 sur la page du jour réelle
(courses_liste_pronostics.php, 14 réunions, structure "## HH:MM Réunion N
- HIPPODROME" suivie des liens de courses au format déjà connu de
canalturf.py : /pronostics-PMU/{AAAA-MM-JJ}/{hippodrome-slug}/{id}_{slug}.html

Limite : CanalTurf n'expose une page listing que pour Aujourd'hui/Demain/
Hier de façon garantie. Pour une date plus lointaine, on tente le pattern
daté observé sur "Hier" (pronostics-PMU/{AAAA-MM-JJ}_pronostics-cotes-
des-courses-du-{jour}-{jj}-{mois}-{aaaa}.html) en best-effort -- non
vérifié au-delà de J-1, peut échouer silencieusement (exception claire).
"""
from __future__ import annotations
import re
import unicodedata
import logging
from dataclasses import dataclass
from datetime import date as date_cls, timedelta
from typing import List, Optional
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.scraping.hippodrome_normalize import hippodromes_match, hippodrome_tokens, normalize_hippodrome

logger = logging.getLogger("vantage.scraping.discovery_canalturf")

_JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
            "août", "septembre", "octobre", "novembre", "décembre"]

_RACE_LINK_RE = re.compile(
    r"/pronostics-PMU/(?P<date>\d{4}-\d{2}-\d{2})/(?P<hippo_slug>[\w\-]+)/(?P<course_id>\d+)_(?P<course_slug>[\w\-]+)\.html"
)


@dataclass
class RaceCandidate:
    url: str
    reunion: Optional[int]
    course: int
    hippodrome_slug: str
    course_slug: str
    label: str
    score: float = 0.0


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s


def _paris_today() -> date_cls:
    """Date civile Europe/Paris (Render UTC : 22h UTC = déjà J+1 à Paris)."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        return date_cls.today()


def _listing_urls_for_date(d: date_cls) -> List[str]:
    """Plusieurs URLs candidates selon le calendrier Paris."""
    today = _paris_today()
    urls: List[str] = []
    if d == today:
        urls.append("https://www.canalturf.com/courses_liste_pronostics.php")
    elif d == today + timedelta(days=1):
        urls.append("https://www.canalturf.com/courses_liste_pronostics_demain.php")
    elif d == today - timedelta(days=1):
        urls.append("https://www.canalturf.com/courses_liste_pronostics_hier.php")
        urls.append("https://www.canalturf.com/courses_liste_pronostics.php")
    jour = _JOURS_FR[d.weekday()]
    mois = _MOIS_FR[d.month]
    urls.append(
        f"https://www.canalturf.com/pronostics-PMU/{d.isoformat()}"
        f"_pronostics-cotes-des-courses-du-{jour}-{d.day}-{mois}-{d.year}.html"
    )
    mois_ascii = mois.replace("é", "e").replace("û", "u").replace("ô", "o")
    if mois_ascii != mois:
        urls.append(
            f"https://www.canalturf.com/pronostics-PMU/{d.isoformat()}"
            f"_pronostics-cotes-des-courses-du-{jour}-{d.day}-{mois_ascii}-{d.year}.html"
        )
    return urls


def list_races_for_date(d) -> List[RaceCandidate]:
    if isinstance(d, str):
        d = date_cls.fromisoformat(d[:10])
    candidates: List[RaceCandidate] = []
    seen = set()
    for url in _listing_urls_for_date(d):
        try:
            html = fetch_html(url)
        except Exception as e:
            logger.warning("CanalTurf listing %s échec: %s", url, e)
            continue
        if "introuvable" in (html or "")[:800].lower():
            continue
        soup = BeautifulSoup(html, "lxml")
        reunion_courante = None
        for el in soup.find_all(["h2", "a"]):
            if el.name == "h2":
                m = re.search(r"R[ée]union\s+(\d+)", el.get_text(" ", strip=True))
                if m:
                    reunion_courante = int(m.group(1))
                continue
            href = el.get("href", "")
            m = _RACE_LINK_RE.search(href)
            if not m or m.group("date") != d.isoformat():
                continue
            key = m.group("course_id")
            if key in seen:
                continue
            seen.add(key)
            label = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            full_url = href if href.startswith("http") else f"https://www.canalturf.com{href}"
            candidates.append(RaceCandidate(
                url=full_url, reunion=reunion_courante, course=int(m.group("course_id")),
                hippodrome_slug=m.group("hippo_slug"), course_slug=m.group("course_slug"), label=label,
            ))
        if candidates:
            logger.info("CanalTurf: +courses via %s (total %d)", url, len(candidates))
            # Ne pas break : fusionner tous les listings (jour/hier/daté)
            # pour maximiser le rappel sur courses passées.
    return candidates


def find_race_url(date, hippodrome: Optional[str] = None, course_num: Optional[int] = None,
                   course_name: Optional[str] = None, reunion_num: Optional[int] = None) -> List[RaceCandidate]:
    """course_num ici = position de la course DANS la réunion (1-8 en
    général), PAS l'identifiant numérique interne CanalTurf (course_id) --
    contrairement à Turfoo, CanalTurf ne l'expose pas dans l'URL. On la
    déduit du texte du lien (préfixe "N HH:MM").

    Priorité de matching changée le 07/09/2026 (même correctif que
    discovery.py::find_race_url, cf. sa docstring pour le détail) :
    réunion+course, quand les deux sont fournis, identifient la course
    de façon exacte et suffisante -- hippodrome et course_name ne sont
    alors que des bonus de confiance, jamais des filtres d'exclusion."""
    all_candidates = list_races_for_date(date)
    if not all_candidates:
        raise ValueError(f"Aucune course trouvée sur CanalTurf.com pour le {date}.")

    identification_exacte = reunion_num is not None and course_num is not None
    hippo_norm = _normalize(hippodrome) if hippodrome else ""
    hippo_tokens = hippodrome_tokens(hippodrome) if hippodrome else set()

    scored = []
    for c in all_candidates:
        m_pos = re.match(r"\s*(\d+)\s", c.label)
        position_course = int(m_pos.group(1)) if m_pos else None

        if identification_exacte:
            if c.reunion != reunion_num or position_course != course_num:
                continue
            score = 0.70
        else:
            slug_readable = c.hippodrome_slug.replace("-", " ")
            slug_tokens = hippodrome_tokens(slug_readable)
            if not hippo_tokens or not slug_tokens:
                continue
            overlap = len(hippo_tokens & slug_tokens) / max(len(hippo_tokens), 1)
            if overlap == 0 and not hippodromes_match(hippodrome or "", slug_readable):
                continue
            if hippodromes_match(hippodrome or "", slug_readable):
                overlap = max(overlap, 0.85)
            score = overlap * 0.6
            if reunion_num is not None and c.reunion == reunion_num:
                score += 0.15
            if course_num is not None:
                if position_course == course_num:
                    score += 0.35
                else:
                    continue

        if hippo_tokens:
            slug_readable = c.hippodrome_slug.replace("-", " ")
            slug_tokens = hippodrome_tokens(slug_readable)
            overlap = len(hippo_tokens & slug_tokens) / max(len(hippo_tokens), 1)
            if hippodromes_match(hippodrome or "", slug_readable):
                overlap = max(overlap, 0.9)
            score += overlap * 0.15
        if course_name:
            name_tokens = set(_normalize(course_name).split())
            label_tokens = set(_normalize(c.label).split())
            if name_tokens:
                score += (len(name_tokens & label_tokens) / len(name_tokens)) * 0.15

        c.score = round(min(1.0, score), 3)
        scored.append(c)

    scored.sort(key=lambda c: c.score, reverse=True)
    if not scored:
        if identification_exacte:
            raise ValueError(
                f"Aucune course ne correspond à réunion {reunion_num}/course {course_num} "
                f"pour le {date} sur CanalTurf.com. Réunions trouvées ce jour-là : "
                f"{sorted({c.reunion for c in all_candidates})}"
            )
        raise ValueError(
            f"Aucune course ne correspond à l'hippodrome {hippodrome!r} pour le {date} sur CanalTurf.com. "
            f"Hippodromes trouvés ce jour-là : {sorted({c.hippodrome_slug for c in all_candidates})}"
        )
    return scored
