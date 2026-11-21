"""
discovery_multi.py -- Point d'entrée unique pour "je donne juste
hippodrome + date (+ éventuellement n° de course), le système retrouve
l'URL sur chaque source paramétrée tout seul". Combine :
  - discovery.py (Turfoo.fr) -- le plus fiable, vérifié en conditions réelles
  - discovery_canalturf.py -- vérifié le 04/08/2026 (jour même/demain)
  - discovery_zoneturf.py -- moins vérifié (cf. son propre avertissement),
    jour même seulement

Frequence-Turf n'a pas besoin de découverte : ses URLs sont 100%
déterministes à partir de la date seule (app/scraping/frequence_turf.py::
build_urls) et sont déjà appelées automatiquement dans orchestrator.py dès
qu'une course a une date -- pas la peine de les chercher ici.

Geny.com fait partie des 4 sources principales de collecte (avec Turfoo,
CanalTurf, Zone-Turf) -- voir discovery_geny.py. CORRECTIF 19/09/2026 :
ce docstring affirmait auparavant que Geny était "volontairement absent"
en raison d'un rejet en dur de son nouveau format côté router.py ; ce
rejet reposait sur une évaluation du 29/07/2026 devenue caduque (vérifié
en conditions réelles le 19/09/2026 : la page est bien rendue côté
serveur) et a été retiré. Geny est donc bien dans _SOURCES ci-dessous et
son URL découverte est désormais exploitable de bout en bout par la
collecte (app/scraping/router.py::scrape_race).

Chaque source qui échoue (hippodrome introuvable ce jour-là, page
indisponible, structure différente...) est ignorée individuellement --
le principe RÈGLE 2 s'applique aussi ici : on ne bloque pas tout parce
qu'une source a raté, mais on ne prétend pas non plus qu'une source a
réussi si elle a échoué.
"""
from __future__ import annotations
import logging
from typing import List, Optional
from dataclasses import dataclass

from app.scraping import discovery as disco_turfoo
from app.scraping import discovery_canalturf as disco_canalturf
from app.scraping import discovery_zoneturf as disco_zoneturf
from app.scraping import discovery_geny as disco_geny

logger = logging.getLogger("vantage.scraping.discovery_multi")

_SEUIL_CONFIANCE_MIN = 0.55  # sous ce score, on préfère ignorer la source plutôt que risquer la mauvaise course
# 20/09/2026 soir : Geny est souvent anti-bot (non compté) → 3 sources applicables.
# 80% exigeait 3/3 ; en pratique Turfoo+ZT = 2/3 (67%) suffit pour un ticket
# fiable (API PMU + FT + stats-quinte comblent ensuite). Seuil ramené à 2/3.
SEUIL_TAUX_COLLECTE_MIN = 0.66  # ≥ 2 sources sur 3 hors Geny

_SOURCES = [
    # CanalTurf en premier : fiable sans curl_cffi, bonnes données partants
    ("canalturf", disco_canalturf.find_race_url),
    ("turfoo", disco_turfoo.find_race_url),
    ("zoneturf", disco_zoneturf.find_race_url),
    ("geny", disco_geny.find_race_url),
]


@dataclass
class DiscoveryReport:
    urls: List[str]
    par_source: dict          # {"turfoo": {"url":..., "score":..., "label":...} | {"erreur": ...} | {"ignore": ...}, ...}
    taux_collecte: float = 0.0
    sources_applicables: int = 0
    sources_reussies: int = 0


def discover_all_sources(date, hippodrome: Optional[str] = None, course_num: Optional[int] = None,
                          course_name: Optional[str] = None, reunion_num: Optional[int] = None) -> DiscoveryReport:
    """Identification changée le 07/09/2026 (demande de Golden) :
    hippodrome devient FACULTATIF -- réunion_num + course_num suffisent
    à identifier une course de façon exacte sur Turfoo et CanalTurf (cf.
    leurs find_race_url respectifs). zone-turf.fr reste une exception
    structurelle : son schéma d'URL exige de connaître l'hippodrome pour
    localiser la page de réunion -- sans lui, cette source est exclue du
    calcul de taux (ce n'est pas un échec de collecte, la source n'était
    simplement pas exploitable pour cette identification, cf. son propre
    message d'erreur).

    "Toutes les sources configurées doivent être tentées" : les 4
    sources sont TOUJOURS appelées (jamais d'arrêt au premier succès
    comme le faisait auparavant scrape_race_with_fallback pour le
    scraping lui-même) -- ceci ne concerne QUE la phase de découverte
    d'URL, la fusion réelle des données se fait ensuite dans
    scrape_race_with_fallback (app/scraping/router.py), inchangé.

    taux_collecte = sources_reussies / sources_applicables (0.0 si
    aucune source n'était applicable, ce qui ne devrait arriver que si
    hippodrome ET reunion_num/course_num manquent tous en même temps)."""
    if not hippodrome and not (reunion_num is not None and course_num is not None):
        raise ValueError(
            "Il faut fournir soit l'hippodrome, soit (réunion + course) pour identifier une course. "
            "Date seule ne suffit pas."
        )

    urls: List[str] = []
    par_source = {}
    sources_applicables = 0
    sources_reussies = 0

    for nom, finder in _SOURCES:
        if nom == "zoneturf" and not hippodrome:
            par_source[nom] = {
                "ignore": "hippodrome non fourni -- zone-turf.fr en a structurellement besoin "
                          "(cf. discovery_zoneturf.py), non compté comme un échec de collecte."
            }
            continue
        sources_applicables += 1
        try:
            candidats = finder(date, hippodrome, course_num=course_num,
                                course_name=course_name, reunion_num=reunion_num)
            meilleur = candidats[0] if candidats else None
            if meilleur is None or meilleur.score < _SEUIL_CONFIANCE_MIN:
                par_source[nom] = {
                    "erreur": f"aucun candidat suffisamment fiable (meilleur score : {meilleur.score if meilleur else 'aucun'})"
                }
                continue
            url_ok = meilleur.url
            # P0 Zone-Turf : scrape exige fragment #N (numéro de course)
            if nom == "zoneturf" and "#" not in url_ok:
                cn = getattr(meilleur, "course", None) or course_num
                if cn is not None:
                    url_ok = f"{url_ok.rstrip('#')}#{int(cn)}"
                else:
                    par_source[nom] = {
                        "erreur": "URL Zone-Turf sans #course — scrape impossible"
                    }
                    continue
            urls.append(url_ok)
            sources_reussies += 1
            par_source[nom] = {"url": url_ok, "score": meilleur.score,
                                "label": getattr(meilleur, "label", None) or getattr(meilleur, "titre", None)}
        except Exception as e:
            msg = str(e)
            logger.info("Découverte %s échouée pour %s le %s : %s", nom, hippodrome, date, e)
            # Anti-bot / rate-limit : source NON APPLICABLE (ne pénalise pas le taux)
            antibot_markers = (
                "GENY_ANTIBOT", "accès refusé", "acces refuse", "trop de requ",
                "Access Denied", "cf-browser-verification", "just a moment",
                "403 Forbidden", "403 forbidden", "error_status", "anti-bot",
                "cloudflare", "rate limit", "rate-limit",
            )
            # v1.29.40 : exemption anti-bot réservée à Geny (IP datacenter connue).
            # Un 403/rate-limit sur Turfoo/CanalTurf/Zone-Turf est un VRAI échec.
            if nom == "geny" and any(m.lower() in msg.lower() for m in antibot_markers):
                sources_applicables -= 1  # on l'avait incrémenté avant le try
                par_source[nom] = {
                    "ignore": f"anti-bot/rate-limit — non compté dans le taux. Détail: {msg[:200]}"
                }
            else:
                par_source[nom] = {"erreur": msg}

    taux_collecte = round(sources_reussies / sources_applicables, 3) if sources_applicables else 0.0

    if not urls:
        raise ValueError(
            f"Aucune source n'a pu retrouver la course (réunion {reunion_num}/course {course_num}"
            f"{f', hippodrome {hippodrome!r}' if hippodrome else ''}) pour le {date}. "
            f"Détail par source : {par_source}"
        )
    return DiscoveryReport(urls=urls, par_source=par_source, taux_collecte=taux_collecte,
                            sources_applicables=sources_applicables, sources_reussies=sources_reussies)
