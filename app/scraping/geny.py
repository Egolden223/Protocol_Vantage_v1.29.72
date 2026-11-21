"""
geny.py -- Scraper pour geny.com/partants-pmu/... (source primaire).

Geny.com est rendu côté serveur (pas de JavaScript nécessaire pour la table
des partants), ce qui en fait la source la plus fiable pour un scraping
Python classique parmi celles listées dans l'annexe du protocole. Voir
README pour le comparatif avec Turf.bzh (JS-rendu, non fiable en scraping
simple) et PMU.fr.

AVERTISSEMENT : les sélecteurs ci-dessous sont construits par
correspondance d'en-têtes de colonnes (robuste aux changements de classes
CSS) plutôt que par chemin CSS/XPath figé, mais n'ont pu être validés que
sur du texte extrait, pas sur le HTML brut réel (contrainte de
l'environnement de développement). Un ajustement des alias de colonnes
(`COLUMN_ALIASES`) est probable au premier run réel -- voir README.
"""
from __future__ import annotations
import re
import logging
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.scraping.musique import parse_musique
from app.models import RaceContext, Cheval, Discipline, TypeCourse, Depart

logger = logging.getLogger("vantage.scraping.geny")

COLUMN_ALIASES: Dict[str, str] = {
    "n°": "numero", "n": "numero", "num": "numero",
    "cheval": "nom", "nom": "nom",
    "c": "corde", "corde": "corde",
    "sa": "sexe_age", "s/a": "sexe_age", "age": "age", "âge": "age",
    "poids": "poids", "kg": "poids",
    "déch.": "dech", "dech.": "dech", "déch": "dech", "oeil.": "dech",
    "jockey": "driver", "driver": "driver", "j/e": "driver_entraineur",
    "entraîneur": "entraineur", "entraineur": "entraineur",
    "musique": "musique", "music": "musique",
    "valeur": "valeur",
    "cotes références": "cote_matin", "cote référence": "cote_matin", "cote ref": "cote_matin",
    "dernières cotes": "cote_avant_course", "dernière cote": "cote_avant_course", "cote": "cote_avant_course",
}

_DISCIPLINE_PATTERNS = [
    (re.compile(r"trot\s*attel[ée]", re.I), Discipline.TROT_ATTELE),
    (re.compile(r"trot\s*mont[ée]", re.I), Discipline.TROT_MONTE),
    (re.compile(r"\bplat\b", re.I), Discipline.PLAT),
    (re.compile(r"\bhaies?\b", re.I), Discipline.HAIES),
    (re.compile(r"steeple", re.I), Discipline.STEEPLE),
]


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower()).replace("’", "'")


def _find_partants_table(soup: BeautifulSoup):
    best, best_score = None, 0
    for t in soup.find_all("table"):
        header_row = t.find("tr")
        if not header_row:
            continue
        headers = [_norm(c.get_text()) for c in header_row.find_all(["th", "td"])]
        score = sum(1 for h in headers if h in COLUMN_ALIASES)
        if score > best_score and score >= 4:
            best, best_score = t, score
    return best


def _parse_partants_table(table) -> List[Dict[str, Any]]:
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [_norm(c.get_text()) for c in rows[0].find_all(["th", "td"])]
    col_map = [COLUMN_ALIASES.get(h) for h in headers]

    partants = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells or len(cells) < 3:
            continue
        row: Dict[str, Any] = {}
        for i, cell in enumerate(cells):
            if i >= len(col_map) or col_map[i] is None:
                continue
            row[col_map[i]] = cell.get_text(strip=True)
        if row.get("nom"):
            partants.append(row)
    return partants


def _parse_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = re.sub(r"\s", "", s).replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else None


def _parse_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = re.sub(r"\s", "", s)
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


def _parse_sexe_age(s: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    if not s:
        return None, None
    m = re.match(r"([A-Za-zÀ-ÿ]+)\s*(\d+)", s.strip())
    if m:
        return m.group(1).upper()[:1], int(m.group(2))
    age = _parse_int(s)
    return None, age


def _extract_race_context(soup: BeautifulSoup, url: str) -> RaceContext:
    text = soup.get_text(" ", strip=True)

    hippodrome = None
    m = re.search(r"(?:R\d+\s*[-–]\s*)([A-ZÀ-Ÿ][A-Za-zÀ-ÿ\-' ]{2,30}?)(?:\s{2,}|\s*[-–]\s*(?:Départ|Réunion))", text)
    if m:
        hippodrome = m.group(1).strip()
    if not hippodrome:
        m = re.search(r"Hippodrome\s*(?:de|d')?\s*([A-ZÀ-Ÿ][A-Za-zÀ-ÿ\-' ]{2,30})", text, re.I)
        if m:
            hippodrome = m.group(1).strip()
    if not hippodrome:
        # dernier repli : segment de l'URL geny (…-{hippodrome}-pmu-…)
        m = re.search(r"\d{4}-\d{2}-\d{2}-([a-z\-]+)-pmu-", url)
        if m:
            hippodrome = m.group(1).replace("-", " ").upper()

    discipline = Discipline.PLAT
    for pattern, disc in _DISCIPLINE_PATTERNS:
        if pattern.search(text):
            discipline = disc
            break

    distance_m = None
    m = re.search(r"(\d[\d\s\xa0\u202f]{2,6})\s*m(?:ètres)?\b", text)
    if m:
        distance_m = _parse_int(m.group(1))

    type_course = TypeCourse.AUTRE
    if re.search(r"handicap", text, re.I):
        type_course = TypeCourse.HANDICAP
    elif re.search(r"claiming|réclamer", text, re.I):
        type_course = TypeCourse.CLAIMER
    elif re.search(r"condition", text, re.I):
        type_course = TypeCourse.CONDITIONS

    depart = Depart.AUTOSTART if discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE) else Depart.CENTRE
    if re.search(r"\bvolt[ée]e?\b", text, re.I):
        depart = Depart.VOLTE

    partants_confirmes = None
    m = re.search(r"(\d{1,2})\s*partants?\b", text, re.I)
    if m:
        partants_confirmes = int(m.group(1))

    allocation_eur = None
    m = re.search(r"([\d\s\xa0\u202f]{3,7})\s*€", text)
    if m:
        allocation_eur = _parse_float(m.group(1))

    penetrometre = None
    m = re.search(r"pénétromètre\s*:?\s*(\d[\.,]?\d?)", text, re.I)
    if m:
        penetrometre = _parse_float(m.group(1))

    date_course = None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", url)
    if m:
        date_course = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return RaceContext(
        url_source=url, hippodrome=hippodrome or "INCONNU", discipline=discipline,
        distance_m=distance_m or 0, type_course=type_course, depart=depart,
        partants_confirmes=partants_confirmes or 0, allocation_eur=allocation_eur,
        penetrometre=penetrometre, date_course=date_course,
    )




def _parse_geny_rsc_partants(html: str) -> List[Dict[str, Any]]:
    """Parse partants dans le payload RSC Next.js (plus de table HTML)."""
    rows: Dict[int, Dict[str, Any]] = {}
    pat = r'\\"idParticipation\\":(\d+),\\"idCheval\\":(\d+),\\"numero\\":(\d+),\\"nomCheval\\":\\"([^\\"]+)\\"'
    for m in re.finditer(pat, html):
        num = int(m.group(3))
        nom = m.group(4).replace("\\'", "'")
        id_cheval = int(m.group(2))
        if num < 1 or num > 30 or len(nom) > 45:
            continue
        if num not in rows:
            rows[num] = {
                "numero": num,
                "nom": nom,
                # idCheval : capturé par le regex ci-dessus mais jusqu'ici
                # jeté -- débloqué le 19/09/2026 (Golden) pour construire
                # fiche_url et brancher geny_fiche_cheval.py.
                "id_cheval": id_cheval,
                "musique": None,
                "corde": None,
                "sexe_age": None,
                "poids": None,
                "driver": None,
                "entraineur": None,
                "cote_matin": None,
                "cote_avant_course": None,
                "valeur": None,
            }
    mus_by: Dict[int, str] = {}
    pat_m = (
        r'\\"etatParticipation\\":\\"PARTANT\\",\\"numero\\":(\d+),.{0,500}?'
        r'\\"casaque\\":\\"[^\\"]+\\",\\"musique\\":\{\\"resume\\":\\"([^\\"]*)\\"'
    )
    for m in re.finditer(pat_m, html, re.DOTALL):
        mus_by[int(m.group(1))] = m.group(2)
    for num, mus in mus_by.items():
        if num in rows and not rows[num]["musique"]:
            rows[num]["musique"] = mus
    return [rows[k] for k in sorted(rows.keys())]


def scrape_geny_race(url: str) -> tuple[RaceContext, List[Cheval], List[str]]:
    html = fetch_html(url, via_scraperapi=True)
    soup = BeautifulSoup(html, "lxml")

    race = _extract_race_context(soup, url)

    table = _find_partants_table(soup)
    warnings: List[str] = []
    if table is not None:
        rows = _parse_partants_table(table)
    else:
        rows = _parse_geny_rsc_partants(html)
        if not rows:
            raise ValueError(
                "Table des partants introuvable sur cette page Geny.com (ni <table> ni payload RSC). "
                "Vérifie COLUMN_ALIASES / _parse_geny_rsc_partants, ou fournis une URL "
                "/partants-pmu/... ou /course/{id}/partants-pronostics."
            )
        warnings.append("Geny: parse RSC (pas de table HTML) — champs cotes/driver parfois absents")
    if not race.partants_confirmes:
        race.partants_confirmes = len(rows)

    chevaux: List[Cheval] = []
    for i, row in enumerate(rows, start=1):
        numero = (row["numero"] if isinstance(row.get("numero"), int) else _parse_int(str(row.get("numero") or ""))) or i
        sexe, age = _parse_sexe_age(row.get("sexe_age"))
        corde_val = _parse_int(row.get("corde"))
        cheval = Cheval(
            numero=numero,
            nom=row.get("nom", f"Cheval{numero}").strip(),
            age=age, sexe=sexe,
            driver_jockey=row.get("driver"),
            entraineur=row.get("entraineur"),
            poids_actuel_kg=_parse_float(row.get("poids")),
            musique=row.get("musique"),
            valeur_pmu=_parse_float(row.get("valeur")),
            cote_matin=_parse_float(row.get("cote_matin")),
            cote_avant_course=_parse_float(row.get("cote_avant_course")) or _parse_float(row.get("cote_matin")),
            numero_autostart=corde_val,
        )
        if row.get("id_cheval"):
            # slug reconstruit depuis le nom -- non garanti exact (voir
            # avertissement dans geny_fiche_cheval.py), mais Geny sert la
            # page par id quel que soit le slug dans la plupart des cas
            # Next.js de ce type. À confirmer en conditions réelles.
            from app.scraping.geny_fiche_cheval import build_geny_fiche_url
            cheval.fiche_url = build_geny_fiche_url(row["id_cheval"], cheval.nom)
        if cheval.numero_autostart is None and race.depart == Depart.AUTOSTART:
            cheval.numero_autostart = numero
        if not cheval.cote_matin and cheval.cote_avant_course:
            cheval.cote_matin = cheval.cote_avant_course
        if cheval.driver_jockey is None and row.get("driver_entraineur"):
            parts = row["driver_entraineur"].split("/")
            cheval.driver_jockey = parts[0].strip() if parts else None
            cheval.entraineur = parts[1].strip() if len(parts) > 1 else cheval.entraineur

        if not cheval.musique:
            warnings.append(f"#{numero} {cheval.nom} : musique introuvable")
        if not cheval.cote_matin:
            warnings.append(f"#{numero} {cheval.nom} : cote introuvable")

        chevaux.append(cheval)

    if len(chevaux) < 3:
        raise ValueError(f"Seulement {len(chevaux)} partant(s) extrait(s) -- vérifie la page source.")

    from app.scraping.base import validate_chevaux
    validate_chevaux(chevaux, url)

    return race, chevaux, warnings


def fetch_geny_numero_to_fiche_map(url: str) -> Dict[int, str]:
    """Récupère, pour une URL de course Geny (peu importe le format --
    ancien ou nouveau), la correspondance numero -> URL de fiche cheval
    individuelle Geny (construite via geny_fiche_cheval.build_geny_fiche_url).

    Ajouté le 20/09/2026 (Golden) : permet de réutiliser une URL de course
    Geny déjà trouvée à l'identification (discover_all_sources) pour
    alimenter TOUS les chevaux en fiche Geny à l'enrichissement --  même
    quand Geny n'a pas été retenu comme source de collecte principale
    (CanalTurf/Turfoo/Zone-Turf). Réutilise le même regex RSC JSON que
    _parse_geny_rsc_partants (idCheval était déjà extrait là mais jusqu'ici
    seulement pour construire fiche_url quand Geny EST la source de
    collecte -- ici on le fait indépendamment, juste pour la table
    numero<->idCheval, sans avoir besoin du reste des partants).

    Retourne {} (jamais d'exception) sur tout échec -- anti-bot, page
    introuvable, structure inattendue -- pour que l'appelant puisse
    basculer sans drame sur les fiches CanalTurf/Turfoo/Zone-Turf
    existantes plutôt que de faire échouer tout l'enrichissement."""
    try:
        html = fetch_html(url, via_scraperapi=True)
    except Exception as e:
        logger.warning("fetch_geny_numero_to_fiche_map: page Geny inaccessible (%s) : %s", url, e)
        return {}

    from app.scraping.geny_fiche_cheval import build_geny_fiche_url

    out: Dict[int, str] = {}
    for row in _parse_geny_rsc_partants(html):
        if row.get("id_cheval") and row.get("numero"):
            out[row["numero"]] = build_geny_fiche_url(row["id_cheval"], row["nom"])

    if not out:
        logger.warning("fetch_geny_numero_to_fiche_map: aucun idCheval extrait de %s "
                        "(structure de page inattendue, ou payload RSC absent).", url)
    return out
