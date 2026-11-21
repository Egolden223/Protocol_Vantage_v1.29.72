"""
collection.py -- Blocs 1-4 des instructions d'exécution (v1.22.2-test) :
accusé de réception course, identification chevaux, collecte unifiée
Bloc A-P, validation. Délégué à la Couche LLM (web_search + web_fetch)
car il s'agit de recherche web réelle sur des sources hippiques.
"""
from __future__ import annotations
from typing import Tuple, List
import logging

from app.llm.client import ClaudeClient
from app.models import RaceContext, Cheval
from app import config

logger = logging.getLogger("vantage.llm.collection")

_CHEVAL_JSON_TEMPLATE = """
{
  "numero": 1, "nom": "...",
  "age": 6, "sexe": "M", "driver_jockey": "...", "entraineur": "...", "proprietaire": "...",
  "cote_matin": 5.8, "cote_avant_course": 5.2, "valeur_pmu": 36.0, "sov_repli_utilise": false,
  "rk_derniere_sec": 74.2, "rk_champ_median_sec": 74.8, "rk_array_3_derniers_sec": [74.9, 74.5, 74.2],
  "rk_incident_flag": [false, false, false], "chrono_200m": null, "champ_median_chrono_200m": null,
  "gains_totaux_eur": 185400, "nb_courses": 42, "niveau_max": 0, "niveau_max_hors_pattern_europeen": false,
  "musique": "312421312143", "style_mpa": "MENEUR_MODERE", "p_avant": 0.55,
  "position_mi_course_hist": [1,2,1,3,2],
  "delai_j": 8, "nb_courses_30j": 1, "commentaire_derniere_course": "a fini très fort",
  "feu_equidia": "VERT", "icp_pondere": 2.9,
  "allocations_last3": [{"montant": 4500, "allocation_course": 30000}],
  "allocation_course_actuelle": 45000, "ferrure_changes": 0, "equip_changes": 0, "all_score": 0.588,
  "driver_stats": {"fenetres": [{"jours": 7, "victoires": 2, "courses": 12}], "taux_hippodrome": 0.2,
                    "taux_distance": 0.18, "taux_top1_20j": 0.22, "classement_national": 3,
                    "dq_12m": 1, "nb_courses_12m": 145},
  "trainer_stats": {"fenetres": [{"jours": 15, "victoires": 3, "courses": 20}]},
  "tandem_driver_cheval": {"courses_ensemble": 6, "victoires_ensemble": 2, "places_top5_ensemble": 3,
                            "jours_depuis_derniere_association": 8},
  "tandem_driver_ecurie": null, "driver_est_entraineur": false,
  "poids_actuel_kg": null, "poids_precedent_kg": null, "valeur_pmu_precedente": null,
  "recul_m": 25, "historique_recul": [{"valeur": 25, "rang": 3}, {"valeur": 25, "rang": 4}],
  "icp_global": 6, "citations_top5_par_source": {"Geny": true}, "favori_unanime": false,
  "dq_12m": 0, "nb_courses_12m": 14, "dq_5_dernieres_tentees": 0, "incidents_30j": 0,
  "pattern_incidents": "STABLE",
  "historique_terrain": [{"valeur": 3.1, "rang": 2}], "historique_distance": [{"valeur": 1750, "rang": 1}],
  "distance_habituelle_m": 1750,
  "confrontations_directes": [{"rang": 1, "weight": 1.5}],
  "numero_autostart": 3, "position_ligne": "1ere_ligne", "attelage_position": 1,
  "chrono_1km": 61.5, "ratio_final": 0.97, "hist_montee_avg": 1.8,
  "changement_driver": false, "changement_entraineur": false, "changement_attelage": false,
  "poids_moyen_champ_kg": null, "poids_min_champ_kg": null, "poids_max_champ_kg": null,
  "sources_manquantes": [], "flags": [], "notes": null
}
""".strip()

_RACE_JSON_TEMPLATE = """
{
  "hippodrome": "VINCENNES", "discipline": "TROT_ATTELE", "distance_m": 2100,
  "type_course": "HANDICAP", "depart": "AUTOSTART", "partants_confirmes": 10,
  "allocation_eur": 45000, "penetrometre": null, "terrain_qualificatif": null,
  "conditions_particulieres": null, "date_course": "2026-07-25", "reunion_course_label": "R1C3"
}
""".strip()


_SOURCES_PAR_DEFAUT = """Sources prioritaires : LeTrot.com (trot), France-Galop.com (galop), Geny.com, Zone-Turf.fr,
Turfoo.fr, CanalTurf.com, Paris-Turf, PMU.fr (programme officiel uniquement), Equidia, Frequence-Turf.fr,
Turf.bzh. Par cheval : numéro, nom, âge, sexe, driver/jockey, entraîneur, cote matin et cote ~30-60 min avant
le départ, musique, gains, poids (galop), valeur PMU, déferré/oeillères, commentaire de la dernière course.
Par course : hippodrome, discipline, distance, type (CONDITIONS/HANDICAP/CLAIMER/AUTRE), départ, allocation,
terrain/pénétromètre, date, étiquette réunion/course (ex. R1C3)."""
_GLOSSAIRE_PAR_DEFAUT = """Disciplines : TROT_ATTELE, TROT_MONTE, PLAT, HAIES, STEEPLE. Départs trot : AUTOSTART, VOLTE.
Musique : suite de places récentes (0 = non placé, D = disqualifié, A = arrêté, T = tombé) suivies de la
discipline (a=attelé, m=monté, p=plat, h=haies, s=steeple, c=cross)."""


def _asset(name: str, default: str) -> str:
    """Texte du protocole si app/protocol_assets/<name> existe, sinon version intégrée (v1.29.43 :
    le dossier n'est pas livré dans le dépôt -> l'ancien code levait FileNotFoundError)."""
    try:
        return (config.PROTOCOL_ASSETS_DIR / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return default


_CHEVAL_COMPACT_TEMPLATE = """{"numero": 1, "nom": "...", "age": 6, "sexe": "M", "driver_jockey": "...", "entraineur": "...",
 "proprietaire": "...", "cote_matin": 5.8, "cote_avant_course": 5.2, "valeur_pmu": 36.0, "musique": "312421",
 "gains_totaux_eur": 185400, "nb_courses": 42, "poids_actuel_kg": null, "commentaire_derniere_course": "..."}"""


def build_system_prompt_extraction() -> str:
    """Mode EXTRACTION (fournisseurs gratuits Gemini/Groq, sans navigation) : le texte des pages est fourni."""
    return f"""Tu extrais les données d'une course hippique française à partir du TEXTE de pages web fourni
(programme / partants). RÈGLES : n'utilise QUE ce texte ; n'invente JAMAIS une donnée (champ introuvable = null) ;
ignore tout résultat officiel de la course du jour ; recoupe les pages entre elles si elles se contredisent.
{_GLOSSAIRE_PAR_DEFAUT}

SORTIE (JSON strict, un seul objet) :
{{"course": {_RACE_JSON_TEMPLATE},
  "chevaux": [ {_CHEVAL_COMPACT_TEMPLATE}, ... ],
  "sources_consultees": ["url1", "url2"]}}
`discipline` parmi TROT_ATTELE, TROT_MONTE, PLAT, HAIES, STEEPLE ; `type_course` parmi CONDITIONS, HANDICAP,
CLAIMER, AUTRE ; `depart` parmi AUTOSTART, VOLTE, CENTRE. Un objet par partant NON non-partant."""


def pages_to_texts(urls, max_total: int | None = None):
    """Télécharge les pages (curl_cffi / scraperapi pour Geny) et ne garde que leur texte."""
    import os, re
    from bs4 import BeautifulSoup
    from app.scraping.base import fetch_html
    max_total = max_total or int(os.environ.get("AI_PAGE_CHARS", "60000"))
    cibles = [u for u in urls if u and str(u).startswith("http")][:4]
    from concurrent.futures import ThreadPoolExecutor

    def _une(u):
        try:
            html = fetch_html(u, via_scraperapi=("geny.com" in u))
        except Exception as e:  # noqa: BLE001
            logger.warning("Page IA non téléchargée %s : %s", u, e)
            return None
        soup = BeautifulSoup(html, "lxml")
        for t in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            t.decompose()
        txt = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n")).strip()
        return (u, txt[: max_total // max(1, len(cibles))])

    # v1.29.45 : téléchargements en parallèle (avant : séquentiels, jusqu'à 4 x plusieurs secondes)
    with ThreadPoolExecutor(max_workers=max(1, len(cibles))) as ex:
        out = [r for r in ex.map(_une, cibles) if r]
    return out


def build_system_prompt() -> str:
    sources = _asset("partie2_collecte.txt", _SOURCES_PAR_DEFAUT)
    glossaire = _asset("partie1_glossaire.txt", _GLOSSAIRE_PAR_DEFAUT)
    return f"""Tu exécutes les BLOCS 1 à 4 de PROTOCOL VANTAGE v1.22.2-test : collecte
de données pré-course pour une course hippique française (PMU Quinté+ ou
autre réunion), à partir de l'URL fournie par l'utilisateur et de recherches
web complémentaires.

RÈGLES ABSOLUES :
- N'utilise QUE des données pré-course (programme, cotes, musique, presse,
  historique). Ne consulte JAMAIS de résultats officiels de la course du jour.
- Ne JAMAIS inventer une donnée. Si une donnée est introuvable, laisse le champ
  JSON à `null` et ajoute une entrée dans `sources_manquantes` / `flags` pour
  ce cheval.
- Sources prioritaires (voir tableau ci-dessous, Partie 2bis) : LeTrot.com,
  Geny.com, Zone-Turf.fr, France-Galop.com, PMU.fr (programme uniquement),
  Paris-Turf, Frequence-Turf.fr (URL exige le segment "-base-tocard-"),
  Turf.bzh (URL : pronostics-pmu-{{DDMMAAAA}}-R{{n}}C{{n}}.html), Equidia.
- Cotes : exactement 2 points de collecte (cote de parution matin/presse, et
  cote ~30-60 minutes avant le départ) -- jamais 4 relevés.
- Récupère la musique, le style de course, les 5-8 dernières performances
  (rang, terrain, distance, recul le cas échéant), les statistiques
  driver/jockey et entraîneur (fenêtres 7/14/30j selon discipline), les
  confrontations directes disponibles, et tout commentaire de presse sur la
  dernière course de chaque partant.

RÉFÉRENCE -- Partie 2bis (tableau unifié de collecte, extrait du protocole) :
{sources[:6000]}

RÉFÉRENCE -- Partie 1 (glossaire, disciplines, styles, terrain) :
{glossaire[:3000]}

SORTIE ATTENDUE (JSON strict, un seul objet) :
{{
  "course": {_RACE_JSON_TEMPLATE},
  "chevaux": [ {_CHEVAL_JSON_TEMPLATE}, ... ],
  "sources_consultees": ["url1", "url2", ...],
  "flags_globaux": ["..."]
}}

Utilise `style_mpa` parmi : MENEUR_FORT, MENEUR_MODERE, ATTENTISTE, CHASSEUR, POLYVALENT.
Utilise `discipline` parmi : TROT_ATTELE, TROT_MONTE, PLAT, HAIES, STEEPLE.
Utilise `type_course` parmi : CONDITIONS, HANDICAP, CLAIMER, AUTRE.
Utilise `depart` parmi : AUTOSTART, VOLTE, CENTRE.
Ne retourne QUE ce JSON, sans texte d'accompagnement."""


def collect_race_data(url: str, client, page_texts=None) -> Tuple[RaceContext, List[Cheval], List[str]]:
    """page_texts=None -> mode NAVIGATION (Claude + web_search/web_fetch) ; sinon mode EXTRACTION
    à partir du texte fourni (fonctionne avec Gemini/Groq gratuits)."""
    if page_texts:
        system = build_system_prompt_extraction()
        user = f"Course : {url}\n\n" + "\n\n".join(f"=== PAGE {u} ===\n{t}" for u, t in page_texts)
        data = client.run_json(system, user, max_tokens=12000, web_search=False, web_fetch=False)
        return _build_from_data(data, url)
    system = build_system_prompt()
    user = (
        f"URL de la course à traiter : {url}\n\n"
        "Récupère le programme complet (tous les partants confirmés), les cotes, "
        "la musique, les commentaires de presse, les statistiques driver/entraîneur, "
        "et toute donnée du tableau Bloc A-P disponible pour CHAQUE partant. "
        "Croise avec 2-3 sources complémentaires si la source principale est incomplète."
    )
    data = client.run_json(system, user, max_tokens=16000, web_search=True, web_fetch=True,
                            allowed_domains=config.ALLOWED_SEARCH_DOMAINS)
    return _build_from_data(data, url)


def _build_from_data(data, url: str) -> Tuple[RaceContext, List[Cheval], List[str]]:
    course_raw = data.get("course", {})
    course_raw["url_source"] = url
    race = RaceContext.model_validate(course_raw)

    chevaux = []
    for c in data.get("chevaux", []):
        try:
            chevaux.append(Cheval.model_validate(c))
        except Exception as e:
            logger.warning("Cheval ignoré (validation échouée) : %s -- %s", c.get("nom", "?"), e)

    if len(chevaux) < 6:
        raise ValueError(
            f"Collecte insuffisante : seulement {len(chevaux)} partant(s) reconnu(s) (minimum 6). "
            "Vérifie l'URL fournie ou réessaie."
        )

    for c in chevaux:
        if "COLLECTE_IA" not in c.flags:
            c.flags.append("COLLECTE_IA")      # donnée issue d'une lecture web par IA : à vérifier
    sources = data.get("sources_consultees", [])
    return race, chevaux, sources


def collect_with_ai_fallback(url: str, expected_identity: dict | None = None, urls=None):
    """Collecte IA de SECOURS (appelée seulement quand toutes les sources Python ont échoué).
    Retourne (race, chevaux, warnings, url) comme scrape_race_with_fallback, ou lève ValueError/
    ClaudeUnavailable. L'identité (hippodrome/date/réunion/course) est revérifiée comme pour les
    sources Python : une course d'un autre jour ou d'une autre réunion est rejetée."""
    from app.llm.client import LLMClient
    from app.scraping.identity import identite_incoherente
    client = LLMClient(timeout=180)
    # Anthropic (navigation web) si disponible ; sinon (Gemini/Groq gratuits) on fournit le TEXTE des pages.
    pages = None if client.can_browse() else pages_to_texts(urls or [url])
    if pages is not None and not pages:
        raise ValueError("Collecte IA impossible : aucune page téléchargeable pour l'extraction.")
    race, chevaux, sources = collect_race_data(url, client, page_texts=pages)
    incoh = identite_incoherente(race, expected_identity)
    if incoh:
        raise ValueError(f"IDENTITE_SOURCE_REJETEE (collecte IA): {incoh}")
    if expected_identity:
        if expected_identity.get("reunion") is not None and expected_identity.get("course") is not None:
            race.reunion_course_label = f"R{int(expected_identity['reunion'])}C{int(expected_identity['course'])}"
        if not race.date_course and expected_identity.get("date"):
            race.date_course = str(expected_identity["date"])[:10]
    warnings = [
        "SOURCE_IA_COLLECTION_UTILISEE: toutes les sources Python ont échoué, données lues par IA (web) -- à vérifier",
        f"Collecte IA ({client.last_provider}) : {len(chevaux)} partants, {len(sources)} source(s) consultée(s)",
    ]
    return race, chevaux, warnings, url
