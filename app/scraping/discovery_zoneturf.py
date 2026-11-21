"""
discovery_zoneturf.py -- Découverte automatique sur zone-turf.fr.

Étape 1 : page programmes du JOUR demandé
  - aujourd'hui : https://www.zone-turf.fr/programmes/
  - date passée/future : https://www.zone-turf.fr/programmes/{jour}-{j}-{mois}-{année}/
    ex. jeudi-17-septembre-2026  (vérifié 18/09/2026)
  -> liens /programmes/r{N}-{hippo}-{id}.html

Étape 2 : page de réunion -> titres "Course N°X" -> URL {reunion}#{numero}

Correctif 18/09/2026 : avant, seule la page /programmes/ (aujourd'hui) était
lue, d'où l'échec "Aucune réunion ne correspond..." pour une date passée
(ex. Vincennes 17/09/2026 alors qu'on est le 18).
"""
from __future__ import annotations
import re
import unicodedata
import logging
from dataclasses import dataclass
from datetime import date as date_cls, datetime
from typing import List, Optional, Union
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.scraping.zoneturf import _course_heading_positions
from app.scraping.hippodrome_normalize import (
    hippodromes_match, hippodrome_tokens, normalize_hippodrome,
    resolve_hippodrome, extract_zone_turf_hippo_slug,
)

logger = logging.getLogger("vantage.scraping.discovery_zoneturf")

_REUNION_PAGE_RE = re.compile(r"/programmes/(r\d+-[\w\-]+)\.html", re.I)

_JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS_FR = [
    "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
]


@dataclass
class RaceCandidate:
    url: str
    reunion: Optional[int]
    course: Optional[int]
    hippodrome_slug: str
    titre: str
    score: float = 0.0


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s


def _to_date(d) -> date_cls:
    if isinstance(d, date_cls):
        return d
    if isinstance(d, datetime):
        return d.date()
    s = str(d)[:10]
    return date_cls.fromisoformat(s)


def _programme_urls_for_date(d: date_cls) -> List[str]:
    """URLs de listing pour passé / jour / futur.

    Priorité absolue à la page **datée** (carte complète du jour demandé).
    `/programmes/` en soirée bascule sur les réunions de nuit et omet
    souvent Vincennes/Quinté (constaté 20/09/2026 22h UTC).
    """
    slug = f"{_JOURS_FR[d.weekday()]}-{d.day}-{_MOIS_FR[d.month - 1]}-{d.year}"
    # Variantes observées ZT (slash final, sans slash, ancien pattern courses-du-)
    urls = [
        f"https://www.zone-turf.fr/programmes/{slug}/",
        f"https://www.zone-turf.fr/programmes/{slug}",
        f"https://www.zone-turf.fr/programmes/courses-du-{d.day}-{_MOIS_FR[d.month - 1]}-{d.year}.html",
    ]
    # Complément générique : UNIQUEMENT pour la date du jour (Paris). v1.29.40 :
    # pour toute autre date cette page listait les réunions d'AUJOURD'HUI et
    # une course du mauvais jour pouvait être retenue.
    try:
        from zoneinfo import ZoneInfo
        _today = datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        _today = date_cls.today()
    if d == _today:
        urls.append("https://www.zone-turf.fr/programmes/")
    return urls


def _list_reunion_pages(d) -> List[str]:
    """URLs de pages de réunion pour la date demandée.

    Fusionne **tous** les listings (ne s'arrête plus au premier non vide) :
    sinon `/programmes/` (soir) masque la page datée qui contient Vincennes.
    """
    target = _to_date(d)
    urls_found: List[str] = []
    seen = set()
    last_err = None
    for listing in _programme_urls_for_date(target):
        try:
            html = fetch_html(listing)
        except Exception as e:
            last_err = e
            logger.warning("Zone-Turf listing %s échec: %s", listing, e)
            continue
        n_before = len(urls_found)
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            m = _REUNION_PAGE_RE.search(a["href"])
            if not m:
                continue
            full = a["href"] if a["href"].startswith("http") else f"https://www.zone-turf.fr{a['href']}"
            base = full.split("#")[0]
            if base not in seen:
                seen.add(base)
                urls_found.append(base)
        added = len(urls_found) - n_before
        if added:
            logger.info("Zone-Turf: +%d réunions via %s (total %d)", added, listing, len(urls_found))
    if not urls_found and last_err:
        raise ValueError(f"Aucune réunion zone-turf pour {target} (dernier erreur: {last_err})")
    return urls_found


def find_race_url(date, hippodrome: Optional[str] = None, course_num: Optional[int] = None,
                   course_name: Optional[str] = None, reunion_num: Optional[int] = None) -> List[RaceCandidate]:
    if not hippodrome:
        raise ValueError(
            "zone-turf.fr : l'hippodrome est requis pour cette source (schéma d'URL "
            "basé sur la page de réunion hippodrome)."
        )
    reunion_urls = _list_reunion_pages(date)
    if not reunion_urls:
        raise ValueError(
            f"Aucune réunion trouvée sur zone-turf.fr pour la date {date} "
            f"(listings tentés: {_programme_urls_for_date(_to_date(date))})."
        )

    hippo_tokens = hippodrome_tokens(hippodrome)
    resolved, _ = resolve_hippodrome(hippodrome)
    candidats_reunion = []
    for url in reunion_urls:
        raw_slug = url.rstrip("/").split("/")[-1].replace(".html", "")
        # r1-vincennes-198944 -> extract reunion num + hippo
        m_r = re.match(r"r(\d+)-", raw_slug, re.I)
        url_reunion_num = int(m_r.group(1)) if m_r else None
        if reunion_num is not None and url_reunion_num is not None and url_reunion_num != reunion_num:
            continue
        hippo_slug = extract_zone_turf_hippo_slug(raw_slug)
        slug_readable = hippo_slug.replace("-", " ")
        matched = (
            hippodromes_match(hippodrome, slug_readable)
            or hippodromes_match(hippodrome, hippo_slug)
            or hippodromes_match(resolved, slug_readable)
        )
        if not matched:
            slug_tokens = hippodrome_tokens(slug_readable)
            overlap = len(hippo_tokens & slug_tokens) / max(len(hippo_tokens), 1) if hippo_tokens else 0
            if overlap <= 0:
                continue
            candidats_reunion.append((overlap, url, hippo_slug, url_reunion_num))
        else:
            slug_tokens = hippodrome_tokens(slug_readable)
            overlap = len(hippo_tokens & slug_tokens) / max(len(hippo_tokens), 1) if hippo_tokens else 1.0
            candidats_reunion.append((max(overlap, 0.85), url, hippo_slug, url_reunion_num))
    candidats_reunion.sort(key=lambda t: t[0], reverse=True)

    if not candidats_reunion:
        raise ValueError(
            f"Aucune réunion ne correspond à l'hippodrome {hippodrome!r} "
            f"(normalisé: {normalize_hippodrome(hippodrome)!r} / résolu: {resolved!r}) "
            f"sur zone-turf.fr pour la date {date}. "
            f"Réunions vues: {[u.split('/')[-1] for u in reunion_urls[:12]]}"
        )

    _, reunion_url, hippo_slug, url_reunion_num = candidats_reunion[0]
    html = fetch_html(reunion_url)
    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text(" ", strip=True)
    headings = _course_heading_positions(full_text)
    if not headings:
        raise ValueError(
            f"Réunion trouvée ({reunion_url}) mais aucun titre de course "
            f"(\"Course N°...\") n'a pu y être repéré."
        )

    resultats = []
    for i, m in enumerate(headings):
        numero = int(m.group(1))
        fin_suivante = headings[i + 1].start() if i + 1 < len(headings) else min(m.end() + 80, len(full_text))
        titre = full_text[m.end():fin_suivante].strip()[:80]
        if any(r.course == numero for r in resultats):
            continue
        score = 0.5
        if course_num is not None:
            if numero != course_num:
                continue
            score += 0.4
        if course_name and titre:
            name_tokens = set(_normalize(course_name).split())
            titre_tokens = set(_normalize(titre).split())
            if name_tokens:
                score += (len(name_tokens & titre_tokens) / len(name_tokens)) * 0.1
        resultats.append(RaceCandidate(
            url=f"{reunion_url}#{numero}",
            reunion=url_reunion_num if url_reunion_num is not None else reunion_num,
            course=numero,
            hippodrome_slug=hippo_slug,
            titre=titre,
            score=round(min(1.0, score), 3),
        ))

    resultats.sort(key=lambda c: c.score, reverse=True)
    if not resultats:
        raise ValueError(
            f"Réunion trouvée ({reunion_url}) mais aucune course ne correspond "
            f"(numéro {course_num!r}). Courses: {sorted(int(m.group(1)) for m in headings)}"
        )
    return resultats
