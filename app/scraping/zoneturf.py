"""
zoneturf.py -- Scraper pour zone-turf.fr/programmes/{reunion-slug}.html#
{course_id}. Chaque page de réunion contient TOUTES les courses de la
réunion (6 à 9 en général) ; l'identifiant de course dans le fragment de
l'URL (#1155230 par ex.) sert à retrouver la bonne section.

⚠️ ATTENTION DOMAINES CLONES -- vérifié le 03/08/2026 : zoneturf-fr.com et
zone-turf-fr.com sont des sites miroir/SEO, PAS le site réel. Seul
zone-turf.fr (avec tiret) est légitime. Ne jamais router vers les clones.

⚠️ AVERTISSEMENT DE FIABILITÉ : structure vérifiée le 04/08/2026 sur une
vraie page réelle (réunion 6 Cabourg, 198028, 8 courses), mais uniquement
via le rendu texte/markdown de l'outil de fetch -- je n'ai jamais eu accès
au HTML brut réel (zone-turf.fr n'est pas dans l'allowlist réseau de mon
bac à sable de développement). Le découpage par course utilise un
appariement positionnel (Nème titre de section <-> Nème tableau de
partants trouvé) plutôt qu'un ancrage DOM direct -- robuste tant que la
page garde exactement un tableau de partants par course (vérifié sur
l'exemple réel), mais à revalider en conditions de production.

Ce que cette page donne QUE les autres sources (Turfoo/CanalTurf/Geny)
ne donnent pas :
  - Record ("Rec.") par cheval -- proxy Bloc C dégradé (accord du
    04/08/2026 : on sursoit au RK complet, on utilise le Record multi-
    sources à la place).
  - Code d'équipement précis (DA/DP/D4/PA/PP/P4/DA-PP/DP-PA) au lieu d'un
    simple booléen -- débloque potentiellement D09bis/D13/D45 (partiel).
  - 2 cotes simultanées (PMU officiel + PMU.fr).
Recoupe aussi (renfort, pas source unique) : gains carrière (Bloc D),
recul individuel (Bloc J, uniquement quand la colonne est "Dist." et non
"Autost." -- cf. compute_recul_m ci-dessous).

Pas géré ici (limites assumées) : pénétromètre (non affiché sur les
exemples vus). Le poids PLAT handicap EST géré depuis le 12/09/2026 (une
vraie page PLAT -- Saint-Cloud R4C8 -- a été vérifiée : la colonne
"Poids" existe et est lisible, contrairement à l'hypothèse initiale du
04/08/2026 qui ne s'appuyait que sur des pages TROT).
"""
from __future__ import annotations
import re
import logging
from datetime import date as date_cls
from typing import Dict, List, Optional, Any, Tuple
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.models import RaceContext, Cheval, Discipline, TypeCourse, Depart

logger = logging.getLogger("vantage.scraping.zoneturf")

_DISCIPLINE_PATTERNS = [
    (re.compile(r"attel[ée]", re.I), Discipline.TROT_ATTELE),
    (re.compile(r"mont[ée]", re.I), Discipline.TROT_MONTE),
    (re.compile(r"\bplat\b", re.I), Discipline.PLAT),
    (re.compile(r"\bhaies?\b", re.I), Discipline.HAIES),
    (re.compile(r"steeple", re.I), Discipline.STEEPLE),
]

_EQUIP_CODES = ["DA/PP", "DP/PA", "DA", "DP", "D4", "PA", "PP", "P4"]
_EQUIP_RE = re.compile(r"^(" + "|".join(re.escape(c) for c in sorted(_EQUIP_CODES, key=len, reverse=True)) + r")\s")

_MOIS_FR = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
            "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}

_COL_ALIASES = {
    "n°": "numero", "n": "numero",
    "cheval": "nom_cell",
    "sa": "sexe_age",
    "autost.": "autostart", "autost": "autostart",
    "dist.": "distance_ligne", "dist": "distance_ligne",
    "driver": "driver", "jockey": "driver",
    "entraîneur": "entraineur", "entraineur": "entraineur",
    "propriétaire": "proprietaire", "proprietaire": "proprietaire",
    "gains": "gains",
    "rec.": "record", "rec": "record",
    "dernières perf.": "perf", "dernieres perf.": "perf", "dernières perf": "perf",
    # PLAT (handicap notamment) -- absent des pages TROT vérifiées le
    # 04/08/2026, d'où l'oubli initial. Trouvé le 12/09/2026 en comparant
    # à une vraie page PLAT (Saint-Cloud R4C8) : la colonne existe et est
    # lisible, mais poids_actuel_kg restait toujours None faute de mapping
    # -- déclenchait une pénalité blocs_absents en cascade sur TOUTES les
    # courses de Plat handicap (module_h_poids, ssfo, synthesis en dépendent).
    "poids": "poids",
}


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _sanitize_cote(c: Optional[float]) -> Optional[float]:
    """Rejette cotes absurdes (bug parse HTML / multi-colonnes collées)."""
    if c is None:
        return None
    if c < 1.01 or c >= 500.0:
        return None
    return c


def _parse_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = re.sub(r"[\s\xa0]", "", s).replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else None


def _parse_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = re.sub(r"[\s\xa0]", "", s)
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


def parse_record_chrono(s: Optional[str]) -> Optional[float]:
    """Convertit un chrono trot format Zone-Turf ("1'11\"7") en secondes
    (71.7). Renvoie None si absent/illisible (cheval jamais chronométré,
    ex. les 2 ans en début de carrière -- fréquent, pas une erreur)."""
    if not s:
        return None
    m = re.match(r"(\d+)['’](\d{1,2})[\"”](\d)?", s.strip())
    if not m:
        return None
    minutes, secondes, dixiemes = m.groups()
    total = int(minutes) * 60 + int(secondes) + (int(dixiemes) / 10 if dixiemes else 0)
    return round(total, 1)


def _extract_fragment(url: str) -> Optional[str]:
    """Fragment #N = numéro de course, ou #quinte / #pick5 (observé 20/09/2026)."""
    m = re.search(r"#(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"#(quinte\+?|pick5|pick-5)", url, re.I)
    return m.group(1).lower().replace("+", "") if m else None


def _locate_course_numero(soup: BeautifulSoup, course_id: str) -> Tuple[Optional[int], Optional[str]]:
    a = None
    for cand in soup.find_all("a", href=True):
        if f"#{course_id}" in cand["href"]:
            a = cand
            break
    if a is None:
        return None, None
    titre = a.get("title") or a.get_text(strip=True)
    tr = a.find_parent("tr")
    numero = None
    if tr is not None:
        first_cell = tr.find(["td", "th"])
        if first_cell:
            numero = _parse_int(first_cell.get_text(strip=True))
    return numero, titre


def _all_partants_tables(soup: BeautifulSoup) -> List:
    tables = []
    for t in soup.find_all("table"):
        header_row = t.find("tr")
        if not header_row:
            continue
        headers = [_norm(c.get_text()) for c in header_row.find_all(["th", "td"])]
        joined = " ".join(headers)
        if "cheval" in joined and ("driver" in joined or "jockey" in joined):
            tables.append(t)
    return tables


def _course_heading_positions(full_text: str) -> List[re.Match]:
    return list(re.finditer(r"Course\s*N[°o]\s*(\d+)\s*:", full_text))


def _reunion_depuis_url(url: str) -> Optional[int]:
    m = re.search(r"/programmes/r(\d+)-", str(url or ""), re.I)
    return int(m.group(1)) if m else None


def _parse_date_reunion(full_text: str) -> Optional[str]:
    m = re.search(r"\b\d{1,2}\s+([A-ZÉÛÀ]+)\s+(\d{4})\b", full_text)
    if not m:
        return None
    jour_m = re.search(r"\b(\d{1,2})\s+[A-ZÉÛÀ]+\s+\d{4}\b", full_text)
    if not jour_m:
        return None
    jour = int(jour_m.group(1))
    mois_nom = m.group(1).lower()
    mois = _MOIS_FR.get(mois_nom)
    annee = int(m.group(2))
    if not mois:
        return None
    return f"{annee:04d}-{mois:02d}-{jour:02d}"


def _extract_race_context(section_text: str, url: str, hippodrome: str, date_course: Optional[str],
                           numero_course: int) -> RaceContext:
    discipline = Discipline.PLAT
    for pattern, disc in _DISCIPLINE_PATTERNS:
        if pattern.search(section_text):
            discipline = disc
            break

    distance_m = None
    m = re.search(r"(\d[\d\s\xa0]{2,6})\s*m[eè]tres", section_text, re.I)
    if m:
        distance_m = _parse_int(m.group(1))

    type_course = TypeCourse.AUTRE
    if re.search(r"handicap", section_text, re.I):
        type_course = TypeCourse.HANDICAP
    elif discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE) and re.search(r"Recul\s+de\s+\d+\s*m", section_text, re.I):
        type_course = TypeCourse.HANDICAP
    elif re.search(r"r[ée]clam", section_text, re.I):
        type_course = TypeCourse.CLAIMER
    elif re.search(r"condition", section_text, re.I):
        type_course = TypeCourse.CONDITIONS

    if re.search(r"autostart", section_text, re.I):
        depart = Depart.AUTOSTART
    elif re.search(r"\bvolt[ée]e?\b", section_text, re.I):
        depart = Depart.VOLTE
    elif discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE):
        depart = Depart.VOLTE  # repli : un trot sans mention explicite "autostart" est très majoritairement à la volte en France
    else:
        depart = Depart.CENTRE

    allocation_eur = None
    m = re.search(r"Allocation totale\s*:\s*([\d\s\xa0]{2,8})\s*€", section_text, re.I)
    if m:
        allocation_eur = _parse_float(m.group(1))

    recul_bands = sorted({int(v) for v in re.findall(r"Recul\s+de\s+(\d+)\s*m", section_text, re.I)})

    race = RaceContext(
        url_source=url, hippodrome=hippodrome or "INCONNU", discipline=discipline,
        distance_m=distance_m or 0, type_course=type_course, depart=depart,
        partants_confirmes=0, allocation_eur=allocation_eur, penetrometre=None,
        date_course=date_course, reunion_course_label=(f"R{_reunion_depuis_url(url)}C{numero_course}" if _reunion_depuis_url(url) else f"C{numero_course}"),  # v1.29.40 : R lue dans l'URL r{N}-, jamais R1 par défaut
    )
    race._recul_bands = recul_bands
    return race


def _parse_header(table) -> Dict[int, str]:
    col_kind: Dict[int, str] = {}
    header_row = table.find("tr")
    for i, cell in enumerate(header_row.find_all(["th", "td"])):
        img = cell.find("img", src=True)
        if img and "cote-pmu-logo" in img["src"]:
            col_kind[i] = "cote_pmu"
            continue
        if img and "cote-pmufr-logo" in img["src"]:
            col_kind[i] = "cote_pmufr"
            continue
        h = _norm(cell.get_text())
        if h in _COL_ALIASES:
            col_kind[i] = _COL_ALIASES[h]
    return col_kind


def _parse_cheval_cell(cell) -> Dict[str, Any]:
    a = cell.find("a", href=True)
    result: Dict[str, Any] = {"nom": None, "fiche_url": None, "equip_code": None}
    if a is None:
        return result
    nom = a.get("title")
    if not nom:
        b_tag = a.find("b")
        nom = b_tag.get_text(strip=True) if b_tag else None
    # le code d'équipement (D4/DA/...) est un texte FRÈRE de <a> dans la
    # cellule (pas un descendant) -- il faut donc le texte de la cellule
    # entière, pas seulement celui du lien, pour le retrouver.
    full_text = cell.get_text(" ", strip=True)
    result["fiche_url"] = a["href"] if a["href"].startswith("http") else f"https://www.zone-turf.fr{a['href']}"
    if nom:
        result["nom"] = nom.strip()
        remainder = full_text[len(nom):].strip() if full_text.startswith(nom) else full_text
        m = _EQUIP_RE.match(remainder)
        if m:
            result["equip_code"] = m.group(1)
    return result


def _parse_partants_table(table) -> List[Dict[str, Any]]:
    col_kind = _parse_header(table)
    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        row: Dict[str, Any] = {}
        for i, cell in enumerate(cells):
            kind = col_kind.get(i)
            if not kind:
                continue
            if kind == "numero":
                row["numero"] = _parse_int(cell.get_text(strip=True))
            elif kind == "nom_cell":
                row.update(_parse_cheval_cell(cell))
            elif kind == "sexe_age":
                m = re.match(r"([A-Za-z])(\d+)", cell.get_text(strip=True))
                if m:
                    row["sexe"] = m.group(1).upper()
                    row["age"] = int(m.group(2))
            elif kind == "distance_ligne":
                row["distance_ligne"] = _parse_int(cell.get_text(strip=True))
            elif kind == "driver":
                row["driver"] = cell.get_text(strip=True)
                lien = cell.find("a", href=True)
                row["driver_fiche_url"] = (
                    (lien["href"] if lien["href"].startswith("http") else f"https://www.zone-turf.fr{lien['href']}")
                    if lien else None
                )
            elif kind == "entraineur":
                row["entraineur"] = cell.get_text(strip=True)
                lien = cell.find("a", href=True)
                row["entraineur_fiche_url"] = (
                    (lien["href"] if lien["href"].startswith("http") else f"https://www.zone-turf.fr{lien['href']}")
                    if lien else None
                )
            elif kind == "gains":
                row["gains"] = _parse_float(cell.get_text(strip=True))
            elif kind == "autostart":
                row["autostart"] = _parse_int(cell.get_text(strip=True))
            elif kind == "poids":
                row["poids_kg"] = _parse_float(cell.get_text(strip=True))
            elif kind == "record":
                row["record_sec"] = parse_record_chrono(cell.get_text(strip=True))
            elif kind == "perf":
                tokens = [x.get_text(strip=True) for x in cell.find_all("a")]
                row["musique"] = "".join(tokens) if tokens else cell.get_text(strip=True).replace(" ", "")
            elif kind == "cote_pmu":
                row["cote_pmu"] = _parse_float(cell.get_text(strip=True))
            elif kind == "cote_pmufr":
                row["cote_pmufr"] = _parse_float(cell.get_text(strip=True))
        if row.get("numero") is not None and row.get("nom"):
            rows.append(row)
    return rows


def scrape_zoneturf_race(url: str) -> Tuple[RaceContext, List[Cheval], List[str]]:
    course_id = _extract_fragment(url)
    if not course_id:
        raise ValueError("URL Zone-Turf sans fragment #<numéro de course> -- impossible de déterminer "
                          "quelle course de la réunion extraire (une page = toute la réunion).")

    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    full_text = soup.get_text(" ", strip=True)
    headings = _course_heading_positions(full_text)
    # #quinte / #pick5 : résoudre via le titre de section (ex. « Quinté+ »)
    if course_id in ("quinte", "pick5", "pick-5"):
        target_idx = None
        for i, m in enumerate(headings):
            fin = headings[i + 1].start() if i + 1 < len(headings) else min(m.end() + 120, len(full_text))
            titre = full_text[m.end():fin].lower()
            if course_id.startswith("quinte") and "quinte" in titre:
                target_idx = i
                break
            if course_id.startswith("pick") and "pick" in titre:
                target_idx = i
                break
        if target_idx is None and headings:
            # repli : souvent la course « événement » est la plus longue / centrale
            target_idx = 0
        numero_course = int(headings[target_idx].group(1)) if target_idx is not None else None
        if numero_course is None:
            raise ValueError(f"Fragment #{course_id} non résolu en n° de course sur {url}.")
    else:
        numero_course = int(course_id)
        target_idx = next((i for i, m in enumerate(headings) if int(m.group(1)) == numero_course), None)
    if target_idx is None:
        raise ValueError(f"Section 'Course N°{numero_course}' introuvable dans le texte de la page {url}.")
    start = headings[target_idx].start()
    end = headings[target_idx + 1].start() if target_idx + 1 < len(headings) else len(full_text)
    section_text = full_text[start:end]

    tables = _all_partants_tables(soup)
    # Garde-fou ajouté le 16/09/2026 : l'appariement Nème titre <-> Nème
    # tableau n'est fiable QUE si les deux listes ont exactement la même
    # longueur (une course annulée sans tableau, ou une table parasite
    # ailleurs sur la page, décale silencieusement tout ce qui suit sans
    # qu'aucune erreur ne se déclenche autrement -- cf. avertissement de
    # fiabilité en tête de fichier). On refuse plutôt que de risquer
    # d'associer la mauvaise course au mauvais tableau, y compris pour
    # les courses qui, prises isolément, auraient un index valide.
    if len(tables) != len(headings):
        raise ValueError(
            f"Appariement positionnel incohérent sur {url} : {len(headings)} titre(s) de "
            f"course détecté(s) pour {len(tables)} tableau(x) de partants trouvé(s). "
            "L'hypothèse d'un tableau par course (vérifiée le 04/08/2026) ne tient pas sur "
            "cette page -- extraction refusée pour éviter d'associer la mauvaise course au "
            "mauvais tableau."
        )
    if target_idx >= len(tables):
        raise ValueError(f"Tableau des partants introuvable pour la course N°{numero_course} sur {url} (appariement positionnel en échec -- structure de page probablement différente de celle vérifiée le 04/08/2026).")
    table = tables[target_idx]

    m_hippo = re.search(r"R[éÉ]union\s+\d+\s+à\s+([A-ZÀ-Üa-zà-ü\-' ]+?)\s*-\s*\d{1,2}h\d{2}", full_text)
    hippodrome = m_hippo.group(1).strip() if m_hippo else None
    date_course = _parse_date_reunion(full_text)

    race = _extract_race_context(section_text, url, hippodrome, date_course, numero_course)
    rows = _parse_partants_table(table)

    # v1.29.27 : Dist. présente en trot suffit (GNT / handicap gains)
    is_recul_eligible = race.discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE)
    warnings: List[str] = []
    chevaux: List[Cheval] = []
    for row in rows:
        numero = row["numero"]
        recul_m = None
        if is_recul_eligible and row.get("distance_ligne") and race.distance_m:
            delta = row["distance_ligne"] - race.distance_m
            if delta >= 0:
                recul_m = delta
        cote = _sanitize_cote(row.get("cote_pmu") or row.get("cote_pmufr"))
        cheval = Cheval(
            numero=numero, nom=row.get("nom", f"Cheval{numero}"),
            age=row.get("age"), sexe=row.get("sexe"),
            driver_jockey=row.get("driver"), entraineur=row.get("entraineur"),
            driver_fiche_url=row.get("driver_fiche_url"), entraineur_fiche_url=row.get("entraineur_fiche_url"),
            musique=row.get("musique"),
            gains_totaux_eur=row.get("gains"),
            recul_m=recul_m,
            cote_matin=cote, cote_avant_course=cote,
            fiche_url=row.get("fiche_url"),
            poids_actuel_kg=row.get("poids_kg"),
            numero_autostart=row.get("autostart"),
        )
        # Si colonne Autost. absente mais départ AUTOSTART : le N° de corde
        # est le numéro de partant (convention française standard).
        if cheval.numero_autostart is None and race.depart == Depart.AUTOSTART:
            cheval.numero_autostart = numero
        if row.get("equip_code"):
            cheval.ferrure_changes = 1
            cheval.ferrure_type = row["equip_code"]
        if row.get("record_sec") is not None:
            cheval.record_chrono_sec = row["record_sec"]
        if not cheval.musique:
            warnings.append(f"#{numero} {cheval.nom} : musique introuvable")
        if not cheval.cote_matin:
            warnings.append(f"#{numero} {cheval.nom} : cote introuvable")
        chevaux.append(cheval)

    race.partants_confirmes = len(chevaux)
    if not chevaux:
        warnings.append("Aucun partant extrait -- structure de page probablement différente de celle vérifiée le 04/08/2026, ne pas utiliser telle quelle.")
    # Garde-fou anti faux-positifs ajouté le 16/09/2026 : appelé partout
    # ailleurs (turfoo.py/canalturf.py/geny.py) mais manquait ici -- Zone-
    # Turf est justement la source la plus fragile structurellement
    # (appariement positionnel, cf. avertissement en tête de fichier).
    from app.scraping.base import validate_chevaux
    validate_chevaux(chevaux, url)
    return race, chevaux, warnings
