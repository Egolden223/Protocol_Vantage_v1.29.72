"""
discovery_geny.py -- Retrouve l'URL exacte d'une course sur geny.com.

Programme du jour :
  https://www.geny.com/programme/{YYYY-MM-DD}
  https://www.geny.com/programme  (aujourd'hui)

Liens course observés (2026-09) :
  /course/{id}/partants-pronostics     (pré-course)
  /course/{id}/arrivee-rapports        (post-course)
  /course/{id}-{date}-{hippo}-{prix}/partants-pronostics  (canonical slug)

Stratégie robuste (17/09/2026) :
  1) Collecter TOUS les liens /course/... (pas de filtre taille de bloc)
  2) Associer R{n} / hippodrome / C{k} via le texte du bloc parent le plus
     petit qui contient le lien, ou via le slug canonical
  3) Préférer partants-pronostics à arrivee-rapports
"""
from __future__ import annotations

import logging
import re
from datetime import date as date_cls
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.scraping.discovery import RaceCandidate, _normalize
from app.scraping.hippodrome_normalize import hippodromes_match, hippodrome_tokens

logger = logging.getLogger("vantage.scraping.discovery_geny")

_BASE = "https://www.geny.com"
_COURSE_RE = re.compile(
    r"/course/(?:(\d+)|(\d+)-(\d{4}-\d{2}-\d{2})-([a-z0-9\-]+)-([^/]+))"
    r"/(partants-pronostics|arrivee-rapports)",
    re.I,
)
_C_LABEL_RE = re.compile(r"C\s*(\d+)\b", re.I)
_R_HIPPO_RE = re.compile(
    r"R\s*(\d+)\s+([A-Za-zÀ-ü][A-Za-zÀ-ü0-9\-\s\['\]]{2,50}?)(?:\s+\d+\s+courses|\s*\(|\s*$)",
    re.I,
)


def _listing_url(d) -> str:
    if isinstance(d, str):
        d = date_cls.fromisoformat(str(d)[:10])
    elif hasattr(d, "isoformat"):
        d = d
    else:
        d = date_cls.fromisoformat(str(d)[:10])
    return f"{_BASE}/programme/{d.isoformat()}"


def _slug_hippo(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize(s)).strip("-")


def _prefer_url(current: Optional[str], new: str) -> str:
    if current is None:
        return new
    if "partants" in new and "partants" not in current:
        return new
    return current


def list_races_for_date(d) -> List[RaceCandidate]:
    if isinstance(d, str):
        d = date_cls.fromisoformat(str(d)[:10])
    url = _listing_url(d)
    try:
        html = fetch_html(url, via_scraperapi=True)
    except Exception as e:
        # v1.29.40 : le repli /programme (= aujourd'hui) n'est valable que pour la date du jour
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime as _dt
            _today = _dt.now(ZoneInfo("Europe/Paris")).date()
        except Exception:
            _today = date_cls.today()
        if d != _today:
            logger.warning("Geny programme %s échec (%s) — pas de repli (date ≠ aujourd'hui)", url, e)
            return []
        logger.warning("Geny programme %s échec (%s) — repli /programme", url, e)
        try:
            html = fetch_html(f"{_BASE}/programme", via_scraperapi=True)
        except Exception as e2:
            logger.error("Geny /programme repli échoué: %s", e2)
            return []

    if not html or len(html) < 500:
        logger.warning("Geny programme HTML trop court (%s octets)", len(html or ""))
        return []

    # Anti-bot / refus d'accès Geny
    low = html.lower()
    if "accès refusé" in low or "acces refuse" in low or "trop de requêtes" in low or "trop de requetes" in low:
        raise RuntimeError(
            "GENY_ANTIBOT: page programme inaccessible (Accès refusé / rate-limit). "
            "Source temporairement non applicable — non comptée dans le taux de collecte."
        )

    # Normalise escapes RSC / JSON embarqué
    html_norm = html.replace('\\"', '"').replace("\\/", "/")

    soup = BeautifulSoup(html_norm, "lxml")
    by_id: Dict[str, RaceCandidate] = {}

    # --- Pass 1 : <a href="/course/..."> ---
    anchors = [
        a for a in soup.find_all("a", href=True)
        if "/course/" in a["href"]
    ]
    logger.info("Geny programme %s : %d liens <a /course/>", url, len(anchors))

    for a in anchors:
        href = a["href"]
        m2 = re.search(r"/course/(\d+)(?:/([a-z0-9\-]+))?", href, re.I)
        if not m2:
            continue
        course_id = m2.group(1)
        kind = m2.group(2) or ""
        full = urljoin(_BASE, href)
        # Prefer partants URL
        if "arrivee" in kind or not kind:
            full = urljoin(_BASE, f"/course/{course_id}/partants-pronostics")
        elif "partants" not in kind:
            full = urljoin(_BASE, f"/course/{course_id}/partants-pronostics")

        label = a.get_text(" ", strip=True)
        cm = _C_LABEL_RE.search(label) or _C_LABEL_RE.search(
            a.parent.get_text(" ", strip=True) if a.parent else ""
        )
        course_n = int(cm.group(1)) if cm else 0

        reunion = 0
        hippo_raw = ""
        el = a
        for _ in range(14):
            el = el.parent
            if el is None:
                break
            tx = el.get_text(" ", strip=True)
            if len(tx) > 3000:
                continue
            rm = _R_HIPPO_RE.search(tx)
            if rm:
                reunion = int(rm.group(1))
                hippo_cand = re.sub(r"\s*[\(\[][^)\]]+[\)\]].*$", "", rm.group(2).strip()).strip()
                if len(hippo_cand) >= 3:
                    hippo_raw = hippo_cand
                break

        hippo_slug = _slug_hippo(hippo_raw) if hippo_raw else "unknown"
        prev = by_id.get(course_id)
        if prev is None:
            by_id[course_id] = RaceCandidate(
                url=full,
                reunion=reunion,
                course=course_n,
                hippodrome_slug=hippo_slug,
                course_slug=course_id,
                label=f"R{reunion}C{course_n} {hippo_raw} {label}".strip(),
            )
        else:
            prev.url = _prefer_url(prev.url, full)
            if reunion and not prev.reunion:
                prev.reunion = reunion
            if course_n and not prev.course:
                prev.course = course_n
            if hippo_slug != "unknown" and prev.hippodrome_slug == "unknown":
                prev.hippodrome_slug = hippo_slug

    # --- Pass 2 : JSON courseInfos (RSC / Next.js) — TOUJOURS exécuté pour enrichir ---
    # Pattern: "id":1684430 ... "nomPrix":"Prix de Mehun..."
    for m in re.finditer(
        r'"id"\s*:\s*(\d{6,}).{0,400}?"nomPrix"\s*:\s*"([^"]*)".{0,120}?"heureCourse"\s*:\s*"([^"]*)"',
        html_norm,
        re.S,
    ):
        cid, nom_prix, heure = m.group(1), m.group(2), m.group(3)
        full = urljoin(_BASE, f"/course/{cid}/partants-pronostics")
        if cid not in by_id:
            by_id[cid] = RaceCandidate(
                url=full,
                reunion=0,
                course=0,
                hippodrome_slug="unknown",
                course_slug=cid,
                label=f"{nom_prix} {heure}".strip(),
            )
        else:
            if nom_prix and nom_prix not in (by_id[cid].label or ""):
                by_id[cid].label = f"{by_id[cid].label} {nom_prix}".strip()

    # --- Pass 2b : associer hippodrome via blocs "nom":"Vincennes" ... course ids ---
    for m in re.finditer(
        r'"nom"\s*:\s*"([^"]{3,40})".{0,120}?"trigramme"\s*:\s*"([A-Z]{2,5})".{0,500}?"courseInfos"\s*:\s*\[(.*?)\]',
        html_norm,
        re.S,
    ):
        hippo_name, tri, body = m.group(1), m.group(2), m.group(3)
        # limit body size for safety
        if len(body) > 50000:
            body = body[:50000]
        ids_in = re.findall(r'"id"\s*:\s*(\d{6,})', body)
        # order = course number proxy (C1, C2, ...)
        for i, cid in enumerate(ids_in, start=1):
            if cid in by_id:
                c = by_id[cid]
                if c.hippodrome_slug in ("", "unknown"):
                    c.hippodrome_slug = _slug_hippo(hippo_name)
                if not c.course:
                    c.course = i
                if not c.reunion:
                    # will try R from surrounding text later
                    pass
                if hippo_name.lower() not in (c.label or "").lower():
                    c.label = f"{hippo_name} C{c.course} {c.label}".strip()

    # --- Pass 2c : slugs date-hippo-prix dans le HTML ---
    for m in re.finditer(
        r'(\d{6,}).{0,30}?(20\d{2}-\d{2}-\d{2})-([a-z0-9\-]+)-([a-z0-9\-]+)',
        html_norm,
        re.I,
    ):
        cid, date_s, hippo_s, prix_s = m.group(1), m.group(2), m.group(3), m.group(4)
        if cid in by_id and by_id[cid].hippodrome_slug in ("", "unknown"):
            by_id[cid].hippodrome_slug = hippo_s
        if cid not in by_id:
            by_id[cid] = RaceCandidate(
                url=urljoin(_BASE, f"/course/{cid}/partants-pronostics"),
                reunion=0,
                course=0,
                hippodrome_slug=hippo_s,
                course_slug=cid,
                label=f"{hippo_s} {prix_s}",
            )

    # --- Pass 3 : IDs bruts /course/N sans path ---
    if not by_id:
        for cid in set(re.findall(r"/course/(\d{6,})", html_norm)):
            by_id[cid] = RaceCandidate(
                url=urljoin(_BASE, f"/course/{cid}/partants-pronostics"),
                reunion=0,
                course=0,
                hippodrome_slug="unknown",
                course_slug=cid,
                label=f"course-{cid}",
            )
        logger.warning("Geny: fallback IDs bruts n=%d", len(by_id))

    candidates = list(by_id.values())
    for c in candidates:
        if "arrivee-rapports" in c.url:
            c.url = c.url.replace("arrivee-rapports", "partants-pronostics")

    logger.info("Geny list_races_for_date(%s) -> %d candidats", d, len(candidates))
    return candidates


def find_race_url(
    date,
    hippodrome: Optional[str] = None,
    course_num: Optional[int] = None,
    course_name: Optional[str] = None,
    reunion_num: Optional[int] = None,
) -> List[RaceCandidate]:
    all_candidates = list_races_for_date(date)
    if not all_candidates:
        raise RuntimeError(
            f"GENY_ANTIBOT: Aucune course listée sur Geny.com pour le {date} ({_listing_url(date)}). "
            "Page programme vide ou bloquée (anti-bot). Source non applicable pour le taux de collecte."
        )

    identification_exacte = reunion_num is not None and course_num is not None
    hippo_tokens = hippodrome_tokens(hippodrome) if hippodrome else set()
    scored: List[RaceCandidate] = []

    for c in all_candidates:
        score = 0.0
        slug_readable = (c.hippodrome_slug or "").replace("-", " ")

        if identification_exacte:
            # Si reunion/course connus sur le candidat
            if c.reunion and c.reunion != reunion_num:
                continue
            if c.course and c.course != course_num:
                continue
            # Si R/C absents (fallback IDs), on score via hippo seulement
            if c.reunion == 0 and c.course == 0:
                score = 0.35
            else:
                score = 0.70
            if hippodrome and slug_readable and slug_readable != "unknown":
                if hippodromes_match(hippodrome, slug_readable):
                    score += 0.25
                else:
                    ov = len(hippo_tokens & hippodrome_tokens(slug_readable)) / max(len(hippo_tokens), 1)
                    score += ov * 0.15
            if "partants" in c.url:
                score += 0.05
        else:
            if course_num is not None and c.course and c.course != course_num:
                continue
            if reunion_num is not None and c.reunion and c.reunion != reunion_num:
                continue
            if hippodrome and slug_readable and slug_readable != "unknown":
                if hippodromes_match(hippodrome, slug_readable):
                    score = 0.75
                else:
                    ov = len(hippo_tokens & hippodrome_tokens(slug_readable)) / max(len(hippo_tokens), 1)
                    if ov < 0.3 and c.reunion and c.course:
                        continue
                    score = max(0.3, ov * 0.7)
            else:
                score = 0.35
            if course_num is not None and c.course == course_num:
                score += 0.2
            if "partants" in c.url:
                score += 0.05
            if course_name:
                name_tokens = set(_normalize(course_name).split())
                label_tokens = set(_normalize(c.label).split())
                if name_tokens:
                    score += (len(name_tokens & label_tokens) / len(name_tokens)) * 0.1

        # v1.29.40 : un candidat dont le n° de course est INCONNU ne peut pas
        # franchir le seuil de confiance (sinon une autre course du même
        # hippodrome pouvait être retenue).
        if course_num is not None and not c.course:
            score = min(score, 0.5)
        c.score = round(min(1.0, score), 3)
        scored.append(c)


    # Si R+C demandés : privilégier les candidats dont course == course_num
    # (souvent renseigné via l'ordre courseInfos dans le bloc hippodrome)
    if identification_exacte and course_num is not None:
        exact_c = [c for c in scored if c.course == course_num]
        if exact_c:
            # boost
            for c in exact_c:
                c.score = min(1.0, c.score + 0.2)
            scored.sort(key=lambda c: c.score, reverse=True)
        # Filtre hippo strict si possible
        if hippodrome:
            hippo_ok = [
                c for c in scored
                if c.hippodrome_slug not in ("", "unknown")
                and (
                    hippodromes_match(hippodrome, c.hippodrome_slug.replace("-", " "))
                    or len(hippo_tokens & hippodrome_tokens(c.hippodrome_slug.replace("-", " "))) >= 1
                )
            ]
            if hippo_ok:
                scored = hippo_ok
                scored.sort(key=lambda c: (c.course == course_num, c.score), reverse=True)

    scored.sort(key=lambda c: c.score, reverse=True)
    if not scored:
        raise ValueError(
            f"Aucune course Geny ne correspond (hippo={hippodrome!r}, R={reunion_num}, C={course_num}) "
            f"pour le {date}. {len(all_candidates)} courses listées, réunions : "
            f"{sorted({c.reunion for c in all_candidates})}"
        )
    return scored
