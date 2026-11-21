"""
web_search_enrich.py — Vague web étape 2.7 (complémentaire).

Chaîne de recherche (ordre) :
  1. Google Custom Search JSON API  (GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX)
     — ou GOOGLE_API_KEY + GOOGLE_CSE_CX
  2. SerpAPI Google                  (SERPAPI_KEY)  optionnel
  3. DuckDuckGo HTML                 (sans clé, repli)

Objectif : découvrir des pages programme/fiches puis extraire des champs
encore vides (recul, gains, commentaire, valeur…).

L'IA (si disponible) priorise les requêtes et les champs cibles.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote_plus, unquote

from bs4 import BeautifulSoup

from app.models import Cheval, RaceContext
from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.web_search_enrich")

_ALLOWED_DOMAINS = (
    "turfomania.fr",
    "letrot.com",
    "turfoo.fr",
    "canalturf.com",
    "zone-turf.fr",
    "geny.com",
    "equidia.fr",
    "frequence-turf.fr",
    "turf.bzh",
    "pmu.fr",
    "paris-turf.com",
    "zeturf.fr",
    "courses-france.com",
    "turf-fr.com",
)


def _env(*names: str) -> Optional[str]:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return None


def _domain_ok(url: str) -> bool:
    low = (url or "").lower()
    return any(d in low for d in _ALLOWED_DOMAINS)


def _filter_urls(candidates: List[str], max_results: int) -> List[str]:
    out: List[str] = []
    for href in candidates:
        if not href or not href.startswith("http"):
            continue
        if not _domain_ok(href):
            continue
        if href not in out:
            out.append(href)
        if len(out) >= max_results:
            break
    return out


def google_cse_search_urls(query: str, max_results: int = 8) -> List[str]:
    """Google Custom Search JSON API (officiel).

    Secrets Render :
      GOOGLE_CSE_API_KEY  (ou GOOGLE_API_KEY)
      GOOGLE_CSE_CX       (ID du moteur de recherche programmable)
    Doc : https://developers.google.com/custom-search/v1/overview
    Quota gratuit typique : 100 requêtes/jour.
    """
    key = _env("GOOGLE_CSE_API_KEY", "GOOGLE_API_KEY")  # v1.29.40 : plus de clé Gemini envoyée à Custom Search
    cx = _env("GOOGLE_CSE_CX", "GOOGLE_SEARCH_CX", "GOOGLE_CSE_ID")
    if not key or not cx:
        return []
    try:
        params = urllib.parse.urlencode({
            "key": key,
            "cx": cx,
            "q": query,
            "num": min(max_results, 10),
            "hl": "fr",
            "gl": "fr",
            "safe": "off",
        })
        url = f"https://www.googleapis.com/customsearch/v1?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "VantageProtocol/1.29"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        items = data.get("items") or []
        return _filter_urls([it.get("link") or "" for it in items], max_results)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        logger.warning("google_cse_search_urls HTTP %s: %s", e.code, body)
        return []
    except Exception as e:
        logger.warning("google_cse_search_urls: %s", e)
        return []


def serpapi_google_search_urls(query: str, max_results: int = 8) -> List[str]:
    """SerpAPI (Google organique) — optionnel si SERPAPI_KEY présent."""
    key = _env("SERPAPI_KEY", "SERP_API_KEY")
    if not key:
        return []
    try:
        params = urllib.parse.urlencode({
            "engine": "google",
            "q": query,
            "api_key": key,
            "hl": "fr",
            "gl": "fr",
            "num": min(max_results, 10),
        })
        url = f"https://serpapi.com/search.json?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "VantageProtocol/1.29"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        links = []
        for it in (data.get("organic_results") or []):
            links.append(it.get("link") or "")
        return _filter_urls(links, max_results)
    except Exception as e:
        logger.warning("serpapi_google_search_urls: %s", e)
        return []


def duckduckgo_search_urls(query: str, max_results: int = 8) -> List[str]:
    """Recherche DDG HTML → liste d'URL (domaines hippiques privilégiés)."""
    urls: List[str] = []
    try:
        q = quote_plus(query)
        html = fetch_html(f"https://html.duckduckgo.com/html/?q={q}")
        soup = BeautifulSoup(html or "", "html.parser")
        for a in soup.select("a.result__a, a.result-link, a[href]"):
            href = a.get("href") or ""
            if "uddg=" in href:
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    href = unquote(m.group(1))
            if not href.startswith("http"):
                continue
            if _domain_ok(href) and href not in urls:
                urls.append(href)
            if len(urls) >= max_results:
                break
        if len(urls) < 3:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "uddg=" in href:
                    m = re.search(r"uddg=([^&]+)", href)
                    if m:
                        href = unquote(m.group(1))
                if href.startswith("http") and _domain_ok(href) and href not in urls:
                    urls.append(href)
                if len(urls) >= max_results:
                    break
    except Exception as e:
        logger.warning("duckduckgo_search_urls: %s", e)
    return urls[:max_results]


def multi_search_urls(query: str, max_results: int = 8) -> Dict[str, Any]:
    """Chaîne Google CSE → SerpAPI → DDG. Retourne urls + provider utilisé.

    Ne lève jamais : repli silencieux vers le provider suivant.
    """
    tried: List[str] = []
    # 1) Google CSE
    if _env("GOOGLE_CSE_CX", "GOOGLE_SEARCH_CX", "GOOGLE_CSE_ID") and _env(
        "GOOGLE_CSE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"
    ):
        tried.append("google_cse")
        found = google_cse_search_urls(query, max_results=max_results)
        if found:
            return {"urls": found, "provider": "google_cse", "tried": tried}
    # 2) SerpAPI
    if _env("SERPAPI_KEY", "SERP_API_KEY"):
        tried.append("serpapi")
        found = serpapi_google_search_urls(query, max_results=max_results)
        if found:
            return {"urls": found, "provider": "serpapi_google", "tried": tried}
    # 3) DuckDuckGo
    tried.append("duckduckgo")
    found = duckduckgo_search_urls(query, max_results=max_results)
    return {
        "urls": found,
        "provider": "duckduckgo" if found else "none",
        "tried": tried,
    }


def build_search_queries(
    race: RaceContext,
    chevaux: List[Cheval],
    lacunes: List[str],
    ai_queries: Optional[List[str]] = None,
) -> List[str]:
    """Requêtes déterministes + optionnelles suggérées par l'IA."""
    hippo = getattr(race, "hippodrome", "") or ""
    date_s = (getattr(race, "date_course", None) or "")[:10]
    disc = str(getattr(race, "discipline", "") or "")
    qs: List[str] = []
    if ai_queries:
        qs.extend(ai_queries[:6])
    qs.append(f"{hippo} {date_s} partants quinté")
    qs.append(f"site:turfomania.fr {hippo} {date_s}")
    qs.append(f"site:letrot.com {hippo} {date_s}")
    qs.append(f"site:turfoo.fr {hippo} {date_s}")
    qs.append(f"site:canalturf.com {hippo} {date_s}")
    if any("recul" in x for x in lacunes):
        qs.append(f"{hippo} {date_s} recul partants Dist")
    if any("valeur_pmu" in x or "gains" in x for x in lacunes):
        qs.append(f"{hippo} {date_s} gains partants valeur")
    if any("commentaire" in x for x in lacunes):
        for c in chevaux:
            if not getattr(c, "commentaire_derniere_course", None):
                qs.append(f'"{c.nom}" fiche courses commentaire OR analyse')
                if len([q for q in qs if "fiche" in q.lower()]) >= 3:
                    break
    if any("poids" in x for x in lacunes):
        qs.append(f"{hippo} {date_s} poids partants")
    # unique preserve order
    seen = set()
    out = []
    for q in qs:
        qn = q.strip().lower()
        if qn and qn not in seen:
            seen.add(qn)
            out.append(q.strip())
    return out[:12]


def _extract_loose_fields(html: str, race: RaceContext) -> Dict[int, Dict[str, Any]]:
    """Heuristique légère: N° + distance 2875/2900/2925 + codes fer dans le HTML."""
    by_num: Dict[int, Dict[str, Any]] = {}
    if not html:
        return by_num
    base = race.distance_m or 0
    for m in re.finditer(
        r"(?:^|>|\s)(\d{1,2})\s+[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][A-Za-zàâäéèêëïîôùûüç\-'\s]{2,40}.{0,120}?(\d{4})\s*m?",
        html,
        re.I,
    ):
        num = int(m.group(1))
        dist = int(m.group(2))
        if dist < 2000 or dist > 4000:
            continue
        recul = dist - base if base else None
        if recul is not None and recul < 0:
            continue
        by_num.setdefault(num, {})
        if recul is not None:
            by_num[num]["recul_m"] = recul
    for m in re.finditer(
        r"(?:^|>|\s)(\d{1,2})\b[^<]{0,80}\b(D4|DA|DP|PADP|PA|PP|P4)\b",
        html,
        re.I,
    ):
        num = int(m.group(1))
        fer = m.group(2).upper()
        by_num.setdefault(num, {})
        by_num[num]["ferrure"] = fer
    # gains type 12 345 € près d'un numéro
    for m in re.finditer(
        r"(?:^|>|\s)(\d{1,2})\b[^<]{0,100}?(\d[\d\s]{2,9})\s*€",
        html,
    ):
        num = int(m.group(1))
        try:
            gains = float(m.group(2).replace(" ", "").replace("\xa0", ""))
        except ValueError:
            continue
        if gains < 1000 or gains > 5_000_000:
            continue
        by_num.setdefault(num, {})
        by_num[num].setdefault("gains_totaux_eur", gains)
    return by_num


def run_web_search_enrichment(
    race: RaceContext,
    chevaux: List[Cheval],
    numeros: Set[int],
    lacunes: Optional[List[str]] = None,
    ai_guide: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Vague web 2.7 : Google CSE / SerpAPI / DDG → pages → extraction champs vides."""
    lacunes = lacunes or []
    ai_queries = (ai_guide or {}).get("queries") if ai_guide else None
    queries = build_search_queries(race, chevaux, lacunes, ai_queries)
    report: Dict[str, Any] = {
        "status": "SKIPPED",
        "fields_filled": 0,
        "queries": queries,
        "urls_tentees": [],
        "urls_ok": [],
        "providers_used": [],
        "search_backend": {
            "google_cse_configured": bool(
                _env("GOOGLE_CSE_CX", "GOOGLE_SEARCH_CX", "GOOGLE_CSE_ID")
                and _env("GOOGLE_CSE_API_KEY", "GOOGLE_API_KEY")  # v1.29.40 : plus de clé Gemini envoyée à Custom Search
            ),
            "serpapi_configured": bool(_env("SERPAPI_KEY", "SERP_API_KEY")),
            "duckduckgo_fallback": True,
        },
        "ai_guide_used": bool(ai_guide and ai_guide.get("status") == "OK"),
        "warnings": [],
    }
    if not queries:
        return report

    urls: List[str] = []
    providers_seen: List[str] = []
    for q in queries[:8]:
        try:
            res = multi_search_urls(q, max_results=5)
            prov = res.get("provider") or "none"
            if prov not in providers_seen and prov != "none":
                providers_seen.append(prov)
            for u in res.get("urls") or []:
                if u not in urls:
                    urls.append(u)
        except Exception as e:
            report["warnings"].append(f"search:{q[:40]}:{str(e)[:60]}")

    report["providers_used"] = providers_seen
    report["urls_tentees"] = urls[:20]
    by_cheval = {c.numero: c for c in chevaux}
    filled = 0
    for url in urls[:12]:
        try:
            html = fetch_html(url)
            if not html or len(html) < 500:
                continue
            report["urls_ok"].append(url)
            extracted = _extract_loose_fields(html, race)
            for num, data in extracted.items():
                if num not in numeros and numeros:
                    continue
                c = by_cheval.get(num)
                if not c:
                    continue
                for field, val in data.items():
                    if val is None:
                        continue
                    cur = getattr(c, field, None)
                    if cur is None or cur == "":
                        setattr(c, field, val)
                        filled += 1
                        fl = list(c.flags or [])
                        fl.append(f"ENRICHI_WEBSEARCH_{field.upper()}")
                        c.flags = fl
            if "turfomania.fr" in url:
                try:
                    from app.scraping.turfomania import parse_turfomania_partants
                    by_num, _ = parse_turfomania_partants(html, race)
                    for num, data in by_num.items():
                        c = by_cheval.get(num)
                        if not c:
                            continue
                        for field, val in data.items():
                            if field == "distance_ligne" or val is None:
                                continue
                            if getattr(c, field, None) in (None, "", []):
                                setattr(c, field, val)
                                filled += 1
                except Exception as e:
                    report["warnings"].append(f"tm_parse:{str(e)[:60]}")
        except Exception as e:
            report["warnings"].append(f"fetch:{url[:50]}:{str(e)[:50]}")

    report["fields_filled"] = filled
    report["status"] = "OK" if (filled or report["urls_ok"]) else "EMPTY"
    return report
