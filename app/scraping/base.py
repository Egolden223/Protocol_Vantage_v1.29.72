"""base.py -- Utilitaires HTTP communs aux scrapers de sources hippiques.

Utilise curl_cffi (impersonation d'empreinte TLS de navigateur) plutôt que
`requests` brut : plusieurs sites hippiques modernes sont derrière des
protections anti-bot (Cloudflare ou équivalent) qui détectent les clients
HTTP "nus" à la poignée de main TLS/HTTP2, indépendamment du User-Agent
déclaré. Si tu observes malgré tout des blocages en usage réel, l'étape
suivante est un navigateur headless (Playwright) -- voir README.

ScraperAPI (ajouté le 20/09/2026, Golden) : curl_cffi masque bien
l'empreinte TLS/navigateur, mais pas l'adresse IP elle-même -- Render
(comme tout hébergeur cloud) utilise des plages IP de datacenter connues
et blacklistées par certains WAF, indépendamment des headers/TLS.
Confirmé sur Geny.com le 20/09/2026 (GENY_ANTIBOT: Accès refusé /
rate-limit) malgré curl_cffi déjà en place. ScraperAPI fait passer la
requête par ses propres IP (rotation + résidentiel selon plan), ce que
curl_cffi ne peut pas résoudre à lui seul. Appliqué UNIQUEMENT aux
requêtes Geny (via_scraperapi=True, passé explicitement par geny.py /
discovery_geny.py / geny_fiche_cheval.py) -- les 3 autres sources
(Turfoo/CanalTurf/Zone-Turf) n'en ont pas besoin, ça préserve le quota
gratuit (5000 requêtes/mois) pour l'endroit où il sert vraiment.
"""
from __future__ import annotations
import os
import re
import time
import random
import logging
import threading
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

try:
    import certifi
except ImportError:  # requests/curl_cffi peuvent fournir leur propre bundle
    certifi = None

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:  # ne devrait plus arriver : curl_cffi est dans requirements.txt
    cffi_requests = None  # type: ignore
    HAS_CFFI = False

logger = logging.getLogger("vantage.scraping")

if not HAS_CFFI:
    logger.warning(
        "curl_cffi absent — Turfoo.fr renverra souvent 403. "
        "Installer: pip install curl_cffi>=0.7"
    )

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")
SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com/"


class NonRetryableHTTPError(RuntimeError):
    """Erreur HTTP définitive pour cette URL (notamment 4xx non transitoire)."""


def _fetch_via_scraperapi(url: str, timeout: int) -> str:
    """Passe la requête par ScraperAPI (rotation d'IP, gestion anti-bot
    côté leur infra). Lève une exception si la clé est absente ou l'appel
    échoue -- l'appelant (fetch_html) doit alors se replier sur le fetch
    direct, jamais planter juste parce que ScraperAPI a un souci."""
    if not SCRAPERAPI_KEY:
        raise RuntimeError("SCRAPERAPI_KEY absente (variable d'environnement non définie).")
    params = {"api_key": SCRAPERAPI_KEY, "url": url}
    if cffi_requests is not None:
        resp = cffi_requests.get(SCRAPERAPI_ENDPOINT, params=params, timeout=timeout)
    else:
        import requests as _req
        resp = _req.get(SCRAPERAPI_ENDPOINT, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.text



# ======================================================================================================================
# v1.29.66 / v1.29.66.1 : CHAÎNE DE FOURNISSEURS ANTI-BOT
# ScraperAPI → String → Firecrawl → Scrapfly → ScrapingBee → … avec bascule auto quand un quota gratuit est épuisé.
# Réservé aux requêtes `via_scraperapi=True` (Geny). Un fournisseur n'est tenté que si sa clé est présente ;
# ordre : FETCH_PROVIDERS_ORDER (liste séparée par des virgules).
# Quota / crédits épuisés (HTTP 401, 402, 403) → mis de côté 6 h ; 429 → 90 s ; autre échec → suivant SANS cooldown.
# Si tous échouent, fetch_html se replie sur le fetch direct habituel.
#   fournisseur   variable(s) d'environnement                          appel
#   scraperapi    SCRAPERAPI_KEY                                       GET  api.scraperapi.com
#   string        STRING_API_KEY (ou STRING_AI_API_KEY)                POST request.usestring.ai/v1/fetch  (format=html)
#   firecrawl     FIRECRAWL_API_KEY (ou FIRECRAWL_KEY)                 POST api.firecrawl.dev/v1/scrape  (formats = rawHtml)
#   scrapfly      SCRAPFLY_API_KEY (ou SCRAPFLY_KEY)                   GET  api.scrapfly.io/scrape  (asp=true unblocker)
#   scrapingbee   SCRAPINGBEE_API_KEY                                  GET  app.scrapingbee.com/api/v1
#   scrapingant   SCRAPINGANT_API_KEY                                  GET  api.scrapingant.com/v2/general
#   scrapedo      SCRAPEDO_TOKEN (ou SCRAPEDO_API_KEY)                 GET  api.scrape.do
#   zenrows       ZENROWS_API_KEY                                      GET  api.zenrows.com/v1
#   custom        FETCH_CUSTOM_KEY + FETCH_CUSTOM_URL_TEMPLATE         GET  gabarit {key} {url}
_COOLDOWN_QUOTA_S = 6 * 3600
_COOLDOWN_DEBIT_S = 90
_PROVIDER_ORDER_DEFAUT = "scraperapi,string,firecrawl,scrapfly,scrapingbee,scrapingant,scrapedo,zenrows,custom"
_PROVIDER_COOLDOWN: Dict[str, float] = {}
_PROVIDER_STATS: Dict[str, Dict[str, int]] = defaultdict(lambda: {"ok": 0, "echec": 0, "quota": 0, "bloque": 0})
_PROVIDER_LOCK = threading.Lock()
_BLOCK_MARKERS = ("just a moment", "attention required", "accès refusé", "acces refuse", "access denied", "cf-browser-verification",
                  "captcha", "rate limit", "too many requests", "you have been blocked")


class ProviderError(RuntimeError):
    """Échec d'un fournisseur ; `cooldown` = secondes de mise de côté (0 = aucune)."""
    def __init__(self, msg: str, cooldown: int = 0, categorie: str = "echec"):
        super().__init__(msg)
        self.cooldown = cooldown
        self.categorie = categorie


def _env_key(*noms: str) -> Optional[str]:
    for n in noms:
        v = os.environ.get(n)
        if v and v.strip():
            return v.strip()
    return None


def _http_get(url: str, params: Optional[dict] = None, timeout: int = 40, headers: Optional[dict] = None):
    if cffi_requests is not None:
        return cffi_requests.get(url, params=params, timeout=timeout, headers=headers)
    import requests as _req
    return _req.get(url, params=params, timeout=timeout, headers=headers)


def _http_post_json(url: str, payload: dict, timeout: int = 60, headers: Optional[dict] = None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    if cffi_requests is not None:
        return cffi_requests.post(url, json=payload, timeout=timeout, headers=h)
    import requests as _req
    return _req.post(url, json=payload, timeout=timeout, headers=h)


def _verifier_statut(resp, nom: str) -> None:
    code = getattr(resp, "status_code", 200)
    if code in (401, 402, 403):
        raise ProviderError(f"{nom} HTTP {code} : clé invalide ou crédits / quota épuisés", _COOLDOWN_QUOTA_S, "quota")
    if code == 429:
        raise ProviderError(f"{nom} HTTP 429 : limite de débit", _COOLDOWN_DEBIT_S, "quota")
    if code >= 400:
        raise ProviderError(f"{nom} HTTP {code}", 0, "echec")


def _prov_scraperapi(url: str, timeout: int) -> str:
    key = SCRAPERAPI_KEY or _env_key("SCRAPERAPI_KEY")
    r = _http_get(SCRAPERAPI_ENDPOINT, {"api_key": key, "url": url}, timeout)
    _verifier_statut(r, "scraperapi")
    return r.text


def _prov_string(url: str, timeout: int) -> str:
    """String Web Access API — anti-bot fort, format HTML pour parsers Geny."""
    key = _env_key("STRING_API_KEY", "STRING_AI_API_KEY")
    payload = {"url": url, "format": "html"}
    r = _http_post_json(
        "https://request.usestring.ai/v1/fetch",
        payload,
        timeout + 15,
        {"Authorization": f"Bearer {key}"},
    )
    _verifier_statut(r, "string")
    ct = (getattr(r, "headers", {}) or {}).get("content-type") or ""
    ct = ct.lower()
    html = ""
    if "json" in ct:
        try:
            j = r.json()
        except Exception as e:
            raise ProviderError(f"string : JSON invalide ({e})", 0, "echec") from e
        if isinstance(j, str):
            html = j
        elif isinstance(j, dict):
            html = j.get("html") or j.get("content") or j.get("markdown") or ""
            if not html:
                d = j.get("data") or j.get("result") or {}
                if isinstance(d, dict):
                    html = d.get("html") or d.get("content") or d.get("markdown") or d.get("rawHtml") or ""
                elif isinstance(d, str):
                    html = d
    else:
        html = r.text or ""
    if not html or len(html.strip()) < 50:
        raise ProviderError("string : contenu HTML vide ou trop court", 0, "echec")
    return html


def _prov_firecrawl(url: str, timeout: int) -> str:
    key = _env_key("FIRECRAWL_API_KEY", "FIRECRAWL_KEY")
    payload = {"url": url, "formats": ["rawHtml"], "onlyMainContent": False, "timeout": int(timeout * 1000),
               "proxy": os.environ.get("FIRECRAWL_PROXY", "basic")}
    r = _http_post_json("https://api.firecrawl.dev/v1/scrape", payload, timeout + 10, {"Authorization": f"Bearer {key}"})
    _verifier_statut(r, "firecrawl")
    j = r.json()
    if not j.get("success", True):
        raise ProviderError(f"firecrawl : {str(j.get('error') or j)[:120]}", 0, "echec")
    d = j.get("data") or {}
    html = d.get("rawHtml") or d.get("html") or ""
    if not html:
        raise ProviderError("firecrawl : rawHtml vide", 0, "echec")
    return html


def _prov_scrapfly(url: str, timeout: int) -> str:
    """Scrapfly — Unblocker (asp=true), HTML via result.content."""
    key = _env_key("SCRAPFLY_API_KEY", "SCRAPFLY_KEY")
    params = {
        "key": key,
        "url": url,
        "asp": "true",
        "country": os.environ.get("SCRAPFLY_COUNTRY", "fr"),
    }
    r = _http_get("https://api.scrapfly.io/scrape", params, timeout + 20)
    _verifier_statut(r, "scrapfly")
    try:
        j = r.json()
    except Exception as e:
        raise ProviderError(f"scrapfly : JSON invalide ({e})", 0, "echec") from e
    result = j.get("result") or {}
    html = result.get("content") or ""
    if not html:
        raise ProviderError("scrapfly : content vide", 0, "echec")
    status = result.get("status_code")
    if status is not None:
        try:
            if int(status) >= 400:
                raise ProviderError(f"scrapfly target HTTP {status}", 0, "echec")
        except (TypeError, ValueError):
            pass
    return html


def _prov_scrapingbee(url: str, timeout: int) -> str:
    r = _http_get("https://app.scrapingbee.com/api/v1/", {"api_key": _env_key("SCRAPINGBEE_API_KEY"), "url": url, "render_js": "false"}, timeout)
    _verifier_statut(r, "scrapingbee")
    return r.text


def _prov_scrapingant(url: str, timeout: int) -> str:
    r = _http_get("https://api.scrapingant.com/v2/general", {"url": url, "browser": "false"}, timeout,
                  {"x-api-key": _env_key("SCRAPINGANT_API_KEY") or ""})
    _verifier_statut(r, "scrapingant")
    return r.text


def _prov_scrapedo(url: str, timeout: int) -> str:
    r = _http_get("https://api.scrape.do/", {"token": _env_key("SCRAPEDO_TOKEN", "SCRAPEDO_API_KEY"), "url": url}, timeout)
    _verifier_statut(r, "scrapedo")
    return r.text


def _prov_zenrows(url: str, timeout: int) -> str:
    r = _http_get("https://api.zenrows.com/v1/", {"apikey": _env_key("ZENROWS_API_KEY"), "url": url}, timeout)
    _verifier_statut(r, "zenrows")
    return r.text


def _prov_custom(url: str, timeout: int) -> str:
    from urllib.parse import quote
    gabarit = os.environ.get("FETCH_CUSTOM_URL_TEMPLATE", "")
    full = gabarit.replace("{key}", quote(_env_key("FETCH_CUSTOM_KEY") or "", safe="")).replace("{url}", quote(url, safe=""))
    r = _http_get(full, None, timeout)
    _verifier_statut(r, "custom")
    return r.text


# nom -> (variables d'environnement dont l'une doit exister, fonction d'appel)
_PROVIDERS: Dict[str, Tuple[Tuple[str, ...], Callable[[str, int], str]]] = {
    "scraperapi": (("SCRAPERAPI_KEY",), _prov_scraperapi),
    "string": (("STRING_API_KEY", "STRING_AI_API_KEY"), _prov_string),
    "firecrawl": (("FIRECRAWL_API_KEY", "FIRECRAWL_KEY"), _prov_firecrawl),
    "scrapfly": (("SCRAPFLY_API_KEY", "SCRAPFLY_KEY"), _prov_scrapfly),
    "scrapingbee": (("SCRAPINGBEE_API_KEY",), _prov_scrapingbee),
    "scrapingant": (("SCRAPINGANT_API_KEY",), _prov_scrapingant),
    "scrapedo": (("SCRAPEDO_TOKEN", "SCRAPEDO_API_KEY"), _prov_scrapedo),
    "zenrows": (("ZENROWS_API_KEY",), _prov_zenrows),
    "custom": (("FETCH_CUSTOM_KEY",), _prov_custom),
}


def _ordre_fournisseurs() -> List[str]:
    brut = os.environ.get("FETCH_PROVIDERS_ORDER", _PROVIDER_ORDER_DEFAUT)
    return [n.strip().lower() for n in brut.split(",") if n.strip().lower() in _PROVIDERS]


def _fournisseur_dispo(nom: str, maintenant: Optional[float] = None) -> bool:
    cles, _ = _PROVIDERS[nom]
    if nom == "scraperapi" and SCRAPERAPI_KEY:
        pass
    elif not _env_key(*cles):
        return False
    if nom == "custom" and not os.environ.get("FETCH_CUSTOM_URL_TEMPLATE"):
        return False
    fin = _PROVIDER_COOLDOWN.get(nom, 0.0)
    return (maintenant if maintenant is not None else time.time()) >= fin


def fournisseurs_actifs() -> List[str]:
    """Fournisseurs ayant une clé ET non mis de côté (ordre d'essai)."""
    now = time.time()
    return [n for n in _ordre_fournisseurs() if _fournisseur_dispo(n, now)]


def provider_stats() -> Dict[str, object]:
    """Compteurs par fournisseur (ok / échec / quota / bloqué) et mises de côté en cours — pour le diagnostic."""
    now = time.time()
    return {"ordre": _ordre_fournisseurs(), "actifs": fournisseurs_actifs(),
            "configures": [n for n in _PROVIDERS if (n == "scraperapi" and SCRAPERAPI_KEY) or _env_key(*_PROVIDERS[n][0])],
            "en_pause_s": {n: int(t - now) for n, t in _PROVIDER_COOLDOWN.items() if t > now},
            "compteurs": {n: dict(v) for n, v in _PROVIDER_STATS.items()}}


def _page_bloquee(html: str) -> bool:
    if not html or len(html.strip()) < 300:
        return True
    debut = html[:4000].lower()
    return any(m in debut for m in _BLOCK_MARKERS)


def _fetch_via_chaine(url: str, timeout: int) -> Optional[str]:
    """Essaie les fournisseurs actifs dans l'ordre ; retourne le HTML du premier qui réussit, sinon None (l'appelant se replie sur le direct)."""
    for nom in fournisseurs_actifs():
        _, fn = _PROVIDERS[nom]
        try:
            html = fn(url, max(timeout, 30))
            if _page_bloquee(html):
                with _PROVIDER_LOCK:
                    _PROVIDER_STATS[nom]["bloque"] += 1
                logger.warning("FETCH %s : page de blocage / trop courte pour %s -- fournisseur suivant.", nom, url)
                continue
            with _PROVIDER_LOCK:
                _PROVIDER_STATS[nom]["ok"] += 1
            logger.info("FETCH fournisseur=%s url=%s (%d octets)", nom, url, len(html))
            return html
        except ProviderError as e:
            with _PROVIDER_LOCK:
                _PROVIDER_STATS[nom]["quota" if e.categorie == "quota" else "echec"] += 1
                if e.cooldown:
                    _PROVIDER_COOLDOWN[nom] = time.time() + e.cooldown
            logger.warning("FETCH %s a échoué pour %s (%s)%s -- fournisseur suivant.", nom, url, e,
                           f" ; mis de côté {e.cooldown // 60} min" if e.cooldown else "")
        except Exception as e:      # noqa: BLE001 -- réseau, timeout, JSON invalide…
            with _PROVIDER_LOCK:
                _PROVIDER_STATS[nom]["echec"] += 1
            logger.warning("FETCH %s a échoué pour %s (%s: %s) -- fournisseur suivant.", nom, url, type(e).__name__, str(e)[:100])
    return None


def fetch_html(url: str, timeout: int = 20, retries: int = 2, extra_headers: Optional[dict] = None,
                via_scraperapi: bool = False) -> str:
    """Récupère le HTML. Préfère curl_cffi (TLS Chrome) ; repli requests
    si curl_cffi absent (suffisant pour Geny / Zone-Turf / CanalTurf ;
    Turfoo reste souvent en 403 sans curl_cffi).

    via_scraperapi (20/09/2026) : réservé à Geny.com pour contourner un
    blocage anti-bot par réputation IP (pas résolu par curl_cffi seul,
    voir docstring du module). Quand True :
    - un délai aléatoire 2-5s est appliqué AVANT la requête (throttling,
      réduit le risque de déclencher l'anti-bot même hors ScraperAPI) ;
    - v1.29.66.1 : tente la CHAÎNE de fournisseurs (ScraperAPI, String,
      Firecrawl, Scrapfly, puis les autres clés présentes ; ordre :
      FETCH_PROVIDERS_ORDER). Un fournisseur dont le quota / les crédits
      sont épuisés est mis de côté (6 h) et le suivant prend le relais ;
      si tous échouent, repli sur le fetch direct habituel -- jamais de
      régression par rapport à avant ;
    - sans aucune clé, comportement inchangé (fetch direct, juste avec le
      throttling en plus)."""
    if via_scraperapi:
        time.sleep(random.uniform(2.0, 5.0))
        html_prox = _fetch_via_chaine(url, timeout)          # v1.29.66.1 : ScraperAPI → String → Firecrawl → Scrapfly → …
        if html_prox is not None:
            return html_prox
        logger.warning("Aucun fournisseur anti-bot disponible / réussi pour %s -- repli sur le fetch direct.", url)

    last_exc = None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if extra_headers:
        headers.update(extra_headers)

    for attempt in range(retries + 1):
        try:
            if cffi_requests is not None:
                kwargs = {
                    "impersonate": "chrome",
                    "headers": headers,
                    "timeout": timeout,
                }
                if certifi is not None:
                    kwargs["verify"] = certifi.where()
                resp = cffi_requests.get(
                    url, **kwargs,
                )
            else:
                import requests as _req
                resp = _req.get(url, headers=headers, timeout=timeout)
            if resp.status_code in (400, 401, 403, 404, 410):
                raise NonRetryableHTTPError(
                    f"HTTP {resp.status_code} sur {url} -- URL absente ou accès refusé."
                )
            resp.raise_for_status()
            return resp.text
        except NonRetryableHTTPError as e:
            last_exc = e
            logger.warning("Échec définitif fetch %s : %s", url, e)
            break
        except Exception as e:
            last_exc = e
            logger.warning("Échec fetch (%s/%s) %s : %s", attempt + 1, retries + 1, url, e)
            time.sleep(1.2 * (attempt + 1))
    raise last_exc


# ----------------------------------------------------------------------------------------------------------------------
# Garde-fous anti faux-positifs pour les scrapers (ex-validation.py, fusionné en v1.29.67.1 : budget de 100 fichiers)
# Le parseur générique peut se tromper de table et produire des noms de chevaux qui sont plusieurs colonnes concaténées ;
# ces fonctions rejettent la course plutôt que de produire un résultat silencieusement faux.
# ----------------------------------------------------------------------------------------------------------------------
# Signes qu'un champ "nom" contient en réalité plusieurs colonnes fusionnées :
# une distance entre crochets, une séquence musique (plusieurs tokens
# chiffre+lettre consécutifs), ou une longueur très anormale pour un nom de
# cheval (les noms PMU font au maximum 18 caractères, RAH-standard PMU).
_GARBAGE_PATTERNS = [
    re.compile(r"\[\s*\d[\d\s\xa0]*\s*m\s*\]"),        # "[2 875m]"
    re.compile(r"(?:\d[a-hA-Hp]\s*){3,}"),               # "8a 3a 8a Da 9a" (musique)
    re.compile(r"\d{3,4}\s*m\b"),                          # distance en clair "2875m"
]


def is_plausible_horse_name(nom: str) -> bool:
    if not nom or not nom.strip():
        return False
    if len(nom) > 30:
        return False
    for pattern in _GARBAGE_PATTERNS:
        if pattern.search(nom):
            return False
    return True


def validate_chevaux(chevaux: List, source: str) -> None:
    """Lève une erreur explicite si une majorité de noms semblent corrompus
    -- signe que la mauvaise table a été détectée. Mieux vaut un échec
    net qu'un ticket construit sur des données fausses."""
    if not chevaux:
        return
    noms_douteux = [c.nom for c in chevaux if not is_plausible_horse_name(c.nom)]
    taux = len(noms_douteux) / len(chevaux)
    if taux >= 0.30:
        raise ValueError(
            f"Données probablement corrompues depuis {source} : {len(noms_douteux)}/"
            f"{len(chevaux)} noms de chevaux ont un format suspect (colonnes fusionnées) "
            f"-- exemple : {noms_douteux[0]!r}. La mauvaise table a probablement été "
            "détectée sur cette page (parseur générique non fiable sur ce domaine). "
            "Utilise turfoo.fr, la seule source avec un parseur dédié vérifié."
        )
