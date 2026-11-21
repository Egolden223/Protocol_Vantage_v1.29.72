"""
turfoo.py -- Scraper pour turfoo.fr/programmes-courses/... (source primaire
recommandée, vérifiée en conditions réelles le 29/07/2026).

Contrairement à Geny.com (dont le nouveau format /course/{id}/partants-
pronostics s'est révélé être une application Next.js au tableau rendu en
JavaScript), Turfoo.fr sert une table HTML classique et complète :
N°-Cheval, Jockey, Distance, S/Age, Entraîneur, Ferrure, Musique, cotes
PMU ET ZEturf. Structure confirmée par une extraction réelle -- voir
README, section Sources.

Format d'URL : turfoo.fr/programmes-courses/{AAMMJJ}/reunion{N}-{hippodrome}/
course{N}-{nom-course}/
"""
from __future__ import annotations
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.models import RaceContext, Cheval, Discipline, TypeCourse, Depart

logger = logging.getLogger("vantage.scraping.turfoo")

_DISCIPLINE_PATTERNS = [
    (re.compile(r"trot\s*attel[ée]", re.I), Discipline.TROT_ATTELE),
    (re.compile(r"trot\s*mont[ée]", re.I), Discipline.TROT_MONTE),
    (re.compile(r"\bplat\b", re.I), Discipline.PLAT),
    (re.compile(r"\bhaies?\b", re.I), Discipline.HAIES),
    (re.compile(r"steeple", re.I), Discipline.STEEPLE),
]


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


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


def _parse_sexe_age(s: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    if not s:
        return None, None
    m = re.match(r"([A-Za-zÀ-ÿ]+)\s*(\d+)", s.strip())
    if m:
        return m.group(1).upper()[:1], int(m.group(2))
    return None, _parse_int(s)


def _find_etude_table(soup: BeautifulSoup):
    """La page contient deux rendus de la liste des partants (cartes +
    table) ; on cible explicitement le <table>, identifié par ses en-têtes."""
    for t in soup.find_all("table"):
        header_row = t.find("tr")
        if not header_row:
            continue
        headers = [_norm(c.get_text()) for c in header_row.find_all(["th", "td"])]
        joined = " ".join(headers)
        if "cheval" in joined and ("musique" in joined or "entraineur" in joined or "entraîneur" in joined):
            return t
    return None


def _odds_columns(header_row) -> Dict[int, str]:
    """Les colonnes de cotes n'ont pas de texte d'en-tête (icônes) -- on les
    identifie via alt/title des images, ou par les liens /book/{bookmaker}/
    dans la première ligne de données si besoin."""
    mapping = {}
    cells = header_row.find_all(["th", "td"])
    for i, cell in enumerate(cells):
        img = cell.find("img")
        alt = (img.get("alt", "") + img.get("title", "")).lower() if img else ""
        if "pmu" in alt:
            mapping[i] = "cote_pmu"
        elif "zeturf" in alt or "ze turf" in alt:
            mapping[i] = "cote_zeturf"
    return mapping


def _detect_odds_by_links(rows, col_count: int) -> Dict[int, str]:
    mapping = {}
    for tr in rows[1:3]:
        cells = tr.find_all(["td", "th"])
        for i, cell in enumerate(cells):
            a = cell.find("a", href=True)
            if not a:
                continue
            href = a["href"].lower()
            if "/book/pmu/" in href and i not in mapping:
                mapping[i] = "cote_pmu"
            elif "/book/zeturf/" in href and i not in mapping:
                mapping[i] = "cote_zeturf"
    return mapping


def _parse_partants_table(table) -> List[Dict[str, Any]]:
    rows = table.find_all("tr")
    if not rows:
        return []
    header_cells = rows[0].find_all(["th", "td"])
    headers = [_norm(c.get_text()) for c in header_cells]

    col_map: Dict[int, str] = {}
    for i, h in enumerate(headers):
        if "cheval" in h:
            col_map[i] = "numero_nom"
        elif h == "jockey":
            col_map[i] = "driver"
        elif "entraineur" in h or "entraîneur" in h:
            col_map[i] = "entraineur"
        elif h.startswith("s/age") or h == "sa":
            col_map[i] = "sexe_age"
        elif "musique" in h:
            col_map[i] = "musique"
        elif "ferr" in h:
            col_map[i] = "ferrure"
        elif h.startswith("dist") or h in ("distance", "dist."):
            col_map[i] = "distance_ligne"
        elif "gain" in h and "moy" not in h:
            col_map[i] = "gains"
        elif "record" in h:
            col_map[i] = "record"

    odds_map = _odds_columns(rows[0])
    if not odds_map:
        odds_map = _detect_odds_by_links(rows, len(headers))
    col_map.update(odds_map)

    partants = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 4:
            continue  # lignes de séparation (casaque/lien "voir la fiche")
        row: Dict[str, Any] = {}
        for i, cell in enumerate(cells):
            key = col_map.get(i)
            if not key:
                continue
            row[key] = cell.get_text(strip=True)
            if key in ("numero_nom", "driver", "entraineur"):
                a = cell.find("a", href=True)
                if a:
                    full = a["href"] if a["href"].startswith("http") else f"https://www.turfoo.fr{a['href']}"
                    row[f"{key}_fiche_url"] = full
        if row.get("numero_nom"):
            partants.append(row)
    return partants


def _extract_race_context(soup: BeautifulSoup, url: str) -> RaceContext:
    text = soup.get_text(" ", strip=True)

    hippodrome = None
    m = re.search(r"reunion\d+-([a-z0-9\-]+)/", url)
    if m:
        hippodrome = m.group(1).replace("-", " ").upper()

    discipline = Discipline.PLAT
    for pattern, disc in _DISCIPLINE_PATTERNS:
        if pattern.search(text):
            discipline = disc
            break

    distance_m = None
    m = re.search(r"Distance\s*:\s*(\d[\d\s\xa0\u202f]*)\s*m\b", text, re.I)
    if m:
        distance_m = _parse_int(m.group(1))

    type_course = TypeCourse.AUTRE
    if re.search(r"handicap", text, re.I):
        type_course = TypeCourse.HANDICAP
    elif discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE) and re.search(
        r"Recul\s+de\s+\d+\s*m|Grand National du Trot|\bGNT\b", text, re.I
    ):
        # Handicap à gains (échelons) même sans le mot "handicap" — v1.29.27
        type_course = TypeCourse.HANDICAP
    elif re.search(r"r[ée]clam", text, re.I):
        type_course = TypeCourse.CLAIMER
    elif re.search(r"condition", text, re.I):
        type_course = TypeCourse.CONDITIONS

    # Trot : volte par défaut si pas autostart explicite (GNT = volte + reculs)
    if discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE):
        if re.search(r"autostart", text, re.I):
            depart = Depart.AUTOSTART
        else:
            depart = Depart.VOLTE
    else:
        depart = Depart.CENTRE
    if re.search(r"\bvolt[ée]e?\b", text, re.I):
        depart = Depart.VOLTE

    partants_confirmes = None
    m = re.search(r"Nb\s*chevaux\s*:\s*(\d+)", text, re.I)
    if m:
        partants_confirmes = int(m.group(1))

    allocation_eur = None
    m = re.search(r"Prix\s*:\s*([\d\s\xa0\u202f]+)\s*€", text, re.I)
    if m:
        allocation_eur = _parse_float(m.group(1))

    date_course = None
    m = re.search(r"/programmes-courses/(\d{2})(\d{2})(\d{2})/", url)
    if m:
        date_course = f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"

    reunion_label = None
    m = re.search(r"reunion(\d+)-.*?/course(\d+)-", url)
    if m:
        reunion_label = f"R{m.group(1)}C{m.group(2)}"

    return RaceContext(
        url_source=url, hippodrome=hippodrome or "INCONNU", discipline=discipline,
        distance_m=distance_m or 0, type_course=type_course, depart=depart,
        partants_confirmes=partants_confirmes or 0, allocation_eur=allocation_eur,
        date_course=date_course, reunion_course_label=reunion_label,
    )


_PRONOSTIC_RE = re.compile(
    r"(?:s[ée]lectionn[ée]s?\s+par\s+Turfoo|pronostic\s+Turfoo|notre\s+pronostic).*?"
    r"num[ée]ros?\s*:?\s*([\d\-\s]{5,60})",
    re.I | re.S,
)


def _extract_pronostic_turfoo(text: str) -> Optional[List[int]]:
    """Extrait le pronostic propre de Turfoo (liste ordonnée de numéros,
    ex 'sélectionnés par Turfoo ... sont les numéros : 3-4-7-5-6-2-8-11'),
    structuré et sans lecture de texte libre."""
    m = _PRONOSTIC_RE.search(text)
    if not m:
        return None
    numeros = [int(n) for n in re.findall(r"\d+", m.group(1))]
    return numeros if 3 <= len(numeros) <= 20 else None


def _apply_pronostic_turfoo(chevaux: List[Cheval], text: str) -> None:
    pronostic = _extract_pronostic_turfoo(text)
    if not pronostic:
        return
    top5 = set(pronostic[:5])
    for c in chevaux:
        cite = c.numero in top5
        c.citations_top5_par_source = {"Turfoo": cite}
        c.icp_global = (c.icp_global or 0) + (1 if cite else 0)
    # NB : favori_unanime n'est PAS déduit d'une seule source (Turfoo) --
    # ce champ suppose un consensus multi-sources que nous n'avons pas ici.


def scrape_turfoo_race(url: str) -> Tuple[RaceContext, List[Cheval], List[str]]:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    race = _extract_race_context(soup, url)

    table = _find_etude_table(soup)
    if table is None:
        raise ValueError(
            "Table 'Étude des partants' introuvable sur cette page Turfoo.fr. "
            "La structure a peut-être changé -- vérifie _find_etude_table et "
            "_parse_partants_table dans app/scraping/turfoo.py."
        )

    rows = _parse_partants_table(table)
    if not race.partants_confirmes:
        race.partants_confirmes = len(rows)

    chevaux: List[Cheval] = []
    warnings: List[str] = []
    for i, row in enumerate(rows, start=1):
        numero_nom = row.get("numero_nom", "")
        m = re.match(r"(\d+)\s*-\s*(.+)", numero_nom)
        numero = int(m.group(1)) if m else i
        nom = m.group(2).strip().title() if m else numero_nom.strip().title()

        sexe, age = _parse_sexe_age(row.get("sexe_age"))
        cote_pmu = _parse_float(row.get("cote_pmu"))
        cote_zeturf = _parse_float(row.get("cote_zeturf"))
        cote = cote_pmu or cote_zeturf
        bms = {}
        if cote_pmu is not None:
            bms["PMU"] = cote_pmu
        if cote_zeturf is not None:
            bms["ZETURF"] = cote_zeturf

        ferrure = row.get("ferrure", "")
        ferrure_txt = ferrure.strip().upper() if ferrure else ""
        ferrure_changes = 1 if ferrure_txt and ferrure_txt not in ("", "-") else 0
        # Ajouté le 07/08/2026 : Turfoo utilise le même vocabulaire de codes
        # que Zone-Turf (DA/DP/D4/PA/PP/P4/DA-PP/DP-PA) dans sa colonne
        # "Ferr." -- jusqu'ici réduit à un simple 0/1, alors que le code
        # précis débloque D09bis/D13/D45 (partiel). Vérifié sur une vraie
        # page (Lisieux C8, 15/07/2026) : "D4" bien présent tel quel.
        # Codes ferrure élargis (LeTrot/Turfomania: PADP, Pa Dp, F4…) — v1.29.27
        _FER_OK = {
            "DA", "DP", "D4", "PA", "PP", "P4", "DA-PP", "DP-PA", "DA/PP", "DP/PA",
            "PADP", "PADP", "PA DP", "PA/DP", "F4", "H9",  # H9 n'est pas fer — filtré plus bas
        }
        fer_norm = ferrure_txt.replace(" ", "").replace("/", "").replace("-", "")
        if ferrure_txt in ("DA", "DP", "D4", "PA", "PP", "P4", "DA-PP", "DP-PA", "DA/PP", "DP/PA", "PADP", "F4"):
            ferrure_type = ferrure_txt if ferrure_txt != "PADP" else "PADP"
        elif fer_norm in ("PADP", "PADP", "PADP"):
            ferrure_type = "PADP"
        elif ferrure_txt in ("PA DP", "Pa Dp", "PA/DP"):
            ferrure_type = "PADP"
        else:
            ferrure_type = ferrure_txt if ferrure_txt in ("DA", "DP", "D4", "PA", "PP", "P4") else None

        # Code de déferrage normalisé (le modèle Cheval attend une chaîne,
        # pas un booléen). Le booléen précédent faisait rejeter la source
        # Turfoo par Pydantic dès qu'un équipement était renseigné.
        deferre_val = None
        if ferrure_type in ("D4", "DA", "DP", "PADP") or (ferrure_txt and ferrure_txt.startswith("D")):
            deferre_val = ferrure_type or ferrure_txt
        elif ferrure_type in ("PA", "PP", "P4"):
            deferre_val = "FERRE"

        # Recul individuel = Dist. ligne - distance base (handicap gains GNT) — v1.29.27
        recul_m = None
        # Trot + colonne Dist. : toujours tenter le recul (même si type_course mal détecté)
        is_trot = race.discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE)
        dist_ligne = None
        raw_dist = row.get("distance_ligne")
        if raw_dist:
            try:
                dist_ligne = int(re.sub(r"[^\d]", "", str(raw_dist)) or 0) or None
            except Exception:
                dist_ligne = None
        if is_trot and dist_ligne and race.distance_m:
            delta = dist_ligne - race.distance_m
            if delta >= 0:
                recul_m = delta
                if race.type_course != TypeCourse.HANDICAP and delta > 0:
                    race.type_course = TypeCourse.HANDICAP  # infer handicap gains
            else:
                warnings.append(
                    f"#{numero} {nom}: Dist. ligne {dist_ligne}m < base {race.distance_m}m — recul ignoré"
                )

        gains_tot = None
        if row.get("gains"):
            try:
                gains_tot = float(re.sub(r"[^\d.]", "", str(row["gains"]).replace(" ", "").replace("\xa0", "")) or 0) or None
            except Exception:
                gains_tot = None

        cheval = Cheval(
            numero=numero, nom=nom, age=age, sexe=sexe,
            driver_jockey=row.get("driver"),
            entraineur=row.get("entraineur"),
            musique=row.get("musique"),
            cote_matin=cote, cote_avant_course=cote,
            ferrure_changes=ferrure_changes,
            ferrure_type=ferrure_type,
            deferre=deferre_val,
            recul_m=recul_m,
            gains_totaux_eur=gains_tot,
            fiche_url=row.get("numero_nom_fiche_url"),
            driver_fiche_url=row.get("driver_fiche_url"),
            entraineur_fiche_url=row.get("entraineur_fiche_url"),
            cotes_bookmakers=bms or None,
        )
        # TROT AUTOSTART : N° partant = position autostart (convention FR)
        if race.depart == Depart.AUTOSTART:
            cheval.numero_autostart = numero
        if not cheval.musique:
            warnings.append(f"#{numero} {cheval.nom} : musique introuvable")
        if not cheval.cote_matin:
            warnings.append(f"#{numero} {cheval.nom} : cote introuvable")
        chevaux.append(cheval)

    if len(chevaux) < 3:
        raise ValueError(f"Seulement {len(chevaux)} partant(s) extrait(s) depuis {url}.")

    from app.scraping.base import validate_chevaux
    validate_chevaux(chevaux, url)

    _apply_pronostic_turfoo(chevaux, soup.get_text(" ", strip=True))
    if not any(c.icp_global for c in chevaux):
        warnings.append("Pronostic Turfoo non détecté sur cette page (format texte inattendu).")

    warnings.append(
        "NOTE : Turfoo.fr n'expose qu'un seul point de cote (pas de distinction "
        "matin/avant-course) -- cote_matin=cote_avant_course, ce qui neutralise "
        "SOV_v2 pour cette source (voir README)."
    )
    return race, chevaux, warnings
