"""
discovery.py -- Retrouve l'URL exacte d'une course sur Turfoo.fr à partir
de détails simples (date, hippodrome, numéro/nom de course), sans avoir
besoin de coller une URL toi-même.

Principe : la page programme du jour (turfoo.fr/programmes-courses/{AAMMJJ}/)
liste tous les liens vers toutes les courses de la journée, dans des <a
href> dont le chemin encode déjà réunion/hippodrome/course
(/reunionN-hippodrome/courseN-nom-course/). On scanne ces liens (robuste
aux changements de classes CSS, on ne dépend que du format d'URL déjà
vérifié) et on les met en correspondance avec ce que l'utilisateur a fourni.

Ceci n'est PAS de la recherche web générale : uniquement de la navigation
déterministe sur une seule page connue et déjà vérifiée. Zéro coût, zéro
dépendance API.
"""
from __future__ import annotations
import re
import unicodedata
import logging
from dataclasses import dataclass
from datetime import date as date_cls
from typing import List, Optional
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.scraping.hippodrome_normalize import hippodromes_match, hippodrome_tokens, normalize_hippodrome

logger = logging.getLogger("vantage.scraping.discovery")

_LINK_RE = re.compile(
    r"/(?:programmes|resultats)-courses/(?P<date>\d{6})/reunion(?P<reunion>\d+)-(?P<hippo_slug>[\w\-]+)"
    r"/course(?P<course>\d+)-(?P<course_slug>[\w\-]+)/?$"
)
# Bug réel trouvé le 05/08/2026 (course du 19/07/2026, Chantilly) : la page
# listing du jour lie chaque course déjà courue vers /resultats-courses/...
# et seulement les courses pas encore courues vers /programmes-courses/...
# L'ancien regex ne matchait QUE /programmes-courses/, donc une réunion
# entièrement terminée (typiquement le cas dès qu'on teste sur une date
# passée, ce qui est le scénario normal pour un audit walk-forward)
# n'apparaissait JAMAIS dans les candidats -- pas un cas limite, le cas
# principal d'usage de ce module pour les tests/audits.


@dataclass
class RaceCandidate:
    url: str
    reunion: int
    course: int
    hippodrome_slug: str
    course_slug: str
    label: str          # texte du lien tel qu'affiché (nom, heure, discipline, partants)
    score: float = 0.0  # confiance du matching (0-1)


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s


def _date_to_aammjj(d) -> str:
    if isinstance(d, date_cls):
        return d.strftime("%y%m%d")
    s = str(d).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)  # ISO "2026-07-30"
    if m:
        return m.group(1)[2:] + m.group(2) + m.group(3)
    m = re.match(r"(\d{2})(\d{2})(\d{2})$", s)  # déjà au format AAMMJJ
    if m:
        return s
    raise ValueError(f"Format de date non reconnu : {d!r} (attendu AAAA-MM-JJ)")


def list_races_for_date(date) -> List[RaceCandidate]:
    """Liste les courses Turfoo pour une date (passée, jour ou future).

    Tente /programmes-courses/ puis /resultats-courses/ (courses déjà
    courues) — solution définitive pour l'historique sans dépendre du
    basculement soirée de la page « programmes ».
    """
    aammjj = _date_to_aammjj(date)
    candidates = []
    seen = set()
    for base_path in (
        f"https://www.turfoo.fr/programmes-courses/{aammjj}/",
        f"https://www.turfoo.fr/resultats-courses/{aammjj}/",
    ):
        try:
            html = fetch_html(base_path)
        except Exception as e:
            logger.warning("Turfoo listing %s échec: %s", base_path, e)
            continue
        if not html or len(html) < 500:
            continue
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            m = _LINK_RE.search(a["href"])
            if not m or m.group("date") != aammjj:
                continue
            key = (m.group("reunion"), m.group("course"))
            if key in seen:
                continue
            seen.add(key)
            label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            raw_url = a["href"] if a["href"].startswith("http") else f"https://www.turfoo.fr{a['href']}"
            # Toujours normaliser vers /programmes-courses/ (fiche complète)
            full_url = raw_url.replace("/resultats-courses/", "/programmes-courses/")
            candidates.append(RaceCandidate(
                url=full_url, reunion=int(m.group("reunion")), course=int(m.group("course")),
                hippodrome_slug=m.group("hippo_slug"), course_slug=m.group("course_slug"), label=label,
            ))
        if candidates:
            logger.info("Turfoo: %d courses via %s", len(candidates), base_path)
            # On continue quand même resultats pour compléter si programmes partiel
    return candidates


def find_race_url(date, hippodrome: Optional[str] = None, course_num: Optional[int] = None,
                   course_name: Optional[str] = None, reunion_num: Optional[int] = None) -> List[RaceCandidate]:
    """Retourne les candidats triés par score de confiance décroissant.
    Lève ValueError si aucun candidat n'est trouvé pour cette date.

    Priorité de matching changée le 07/09/2026 (demande de Golden, suite
    à un vrai souci en test : une faute de frappe sur l'hippodrome
    bloquait toute identification alors que réunion+course suffisaient) :
    si reunion_num ET course_num sont TOUS LES DEUX fournis, ils
    identifient la course de façon EXACTE et suffisante (une réunion+
    course donnée est unique sur une date donnée) -- hippodrome et
    course_name deviennent alors de simples bonus de confiance,
    JAMAIS des filtres d'exclusion. hippodrome reste le filtre
    principal seulement quand reunion_num/course_num ne sont pas
    fournis (usage historique, toujours supporté)."""
    all_candidates = list_races_for_date(date)
    if not all_candidates:
        raise ValueError(f"Aucune course trouvée sur Turfoo.fr pour le {date}.")

    identification_exacte = reunion_num is not None and course_num is not None
    hippo_norm = _normalize(hippodrome) if hippodrome else ""
    hippo_tokens = hippodrome_tokens(hippodrome) if hippodrome else set()

    scored = []
    for c in all_candidates:
        if identification_exacte:
            if c.reunion != reunion_num or c.course != course_num:
                continue
            score = 0.70  # identification exacte réunion+course -- confiance de base déjà haute
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
                if c.course == course_num:
                    score += 0.35
                else:
                    continue  # numéro de course fourni et non correspondant -> exclu

        # Bonus de confiance (jamais un filtre d'exclusion) même en identification exacte.
        if hippo_tokens:
            slug_readable = c.hippodrome_slug.replace("-", " ")
            slug_tokens = hippodrome_tokens(slug_readable)
            overlap = len(hippo_tokens & slug_tokens) / max(len(hippo_tokens), 1)
            if hippodromes_match(hippodrome or "", slug_readable):
                overlap = max(overlap, 0.9)
            score += overlap * 0.15
        if course_name:
            name_norm = _normalize(course_name)
            label_norm = _normalize(c.label)
            name_tokens = set(name_norm.split())
            label_tokens = set(label_norm.split())
            if name_tokens:
                name_overlap = len(name_tokens & label_tokens) / len(name_tokens)
                score += name_overlap * 0.15

        c.score = round(min(1.0, score), 3)
        scored.append(c)

    scored.sort(key=lambda c: c.score, reverse=True)
    if not scored:
        if identification_exacte:
            raise ValueError(
                f"Aucune course ne correspond à réunion {reunion_num}/course {course_num} "
                f"pour le {date} sur Turfoo.fr. Réunions/courses trouvées ce jour-là : "
                f"{sorted({(c.reunion, c.course) for c in all_candidates})}"
            )
        raise ValueError(
            f"Aucune course ne correspond à l'hippodrome {hippodrome!r} pour le {date} sur Turfoo.fr. "
            f"Hippodromes trouvés ce jour-là : {sorted({c.hippodrome_slug for c in all_candidates})}"
        )
    return scored
