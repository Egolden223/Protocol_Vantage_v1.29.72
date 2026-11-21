"""
canalturf.py -- Scraper pour canalturf.com/pronostics-PMU/... (source
principale recommandée -- structure vérifiée en conditions réelles sur
deux courses distinctes le 01/08/2026 : trot attelé Cabourg et plat
handicap Clairefontaine).

Avantages confirmés sur Turfoo.fr :
  - Poids ET valeur handicap (Val.) présents sur les courses PLAT
  - 3 bookmakers (PMU, ZEturf, BetClic) avec cote horodatée ("à Nh")
  - Jusqu'à 3 pronostics structurés indépendants : Canalturf (BASE/
    CHANCES RÉGULIÈRES/OUTSIDERS), ZEturf, et pour les Quinté+ une
    synthèse "Presse" (10 chevaux, ~13 titres de presse hippique)
  - Recul (trot handicap) affiché en clair dans les conditions de course
  - idcheval/idjockey/identraineur extraits directement des URLs de fiche

Format d'URL : canalturf.com/pronostics-PMU/{AAAA-MM-JJ}/{hippodrome}/
{id}_{nom-course}.html
"""
from __future__ import annotations
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from bs4 import BeautifulSoup

from app.scraping.base import fetch_html
from app.models import RaceContext, Cheval, Discipline, TypeCourse, Depart

logger = logging.getLogger("vantage.scraping.canalturf")

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
    m = re.match(r"([A-Za-zÀ-ÿ]+)(\d+)", s.strip())
    if m:
        return m.group(1).upper()[:1], int(m.group(2))
    return None, None


def _find_partants_table(soup: BeautifulSoup):
    for t in soup.find_all("table"):
        header_row = t.find("tr")
        if not header_row:
            continue
        headers = [_norm(c.get_text()) for c in header_row.find_all(["th", "td"])]
        joined = " ".join(headers)
        if "cheval" in joined and ("jockey" in joined or "driver" in joined):
            return t
    return None


def _extract_idcheval(href: str) -> Optional[int]:
    m = re.search(r"idcheval=(\d+)", href)
    return int(m.group(1)) if m else None


def _parse_cheval_cell(cell) -> Dict[str, Any]:
    """Cellule 'Cheval' : lien avec texte '**NOM (SA)** musique PERE - MERE'."""
    a = cell.find("a", href=True)
    text = cell.get_text(" ", strip=True)
    result: Dict[str, Any] = {"fiche_url": None, "idcheval": None}
    if a:
        result["fiche_url"] = a["href"] if a["href"].startswith("http") else f"https://www.canalturf.com{a['href']}"
        result["idcheval"] = _extract_idcheval(a["href"])

    m = re.match(r"([A-ZÀ-Ü0-9'\.\-\s]+?)\s*\(([A-Za-z]\d+)\)\s*(.*)", text)
    if not m:
        result["nom"] = text.strip().title()
        return result
    result["nom"] = m.group(1).strip().title()
    sexe, age = _parse_sexe_age(m.group(2))
    result["sexe"], result["age"] = sexe, age

    reste = m.group(3).strip()
    # reste = "<musique> PERE - MERE" -- la musique est la 1ère séquence de tokens rang+lettre
    mus_m = re.match(r"((?:[0-9DTAdta][a-zA-Z](?:\(\d{2}\))?)+)\s*(.*)", reste)
    if mus_m:
        result["musique"] = mus_m.group(1)
        origine = mus_m.group(2).strip()
    else:
        result["musique"] = None
        origine = reste
    if " - " in origine:
        pere, mere = origine.split(" - ", 1)
        result["pere"], result["mere"] = pere.strip(), mere.strip()
    return result


def _parse_partants_table(table) -> List[Dict[str, Any]]:
    rows = table.find_all("tr")
    if not rows:
        return []
    header_cells = rows[0].find_all(["th", "td"])
    headers = [_norm(c.get_text()) for c in header_cells]

    col_kind = []
    cote_col_idx = 0  # index séquentiel des colonnes de cotes horodatées
    for h in headers:
        if h in ("n°", "n", "num", "numero"):
            col_kind.append("numero")
        elif "cheval" in h:
            col_kind.append("cheval")
        elif h == "corde":
            col_kind.append("corde")
        elif h in ("def.", "def"):
            col_kind.append("ferrure")
        elif "jockey" in h or "driver" in h:
            col_kind.append("jockey_entr")
        elif h == "poids":
            col_kind.append("poids")
        elif h in ("val.", "valeur"):
            col_kind.append("valeur")
        elif h.startswith("dist"):
            col_kind.append("distance")
        elif (h.startswith("à ") or re.search(r"\d{1,2}\s*h", h)
              or "pmu" in h or "zeturf" in h or "betclic" in h or "bet clic" in h):
            # Colonnes de cotes : "à 10h", "à 12h", logos bookmakers
            book = "PMU"
            if "zeturf" in h or "ze turf" in h:
                book = "ZETURF"
            elif "betclic" in h or "bet clic" in h:
                book = "BETCLIC"
            heure_m = re.search(r"(\d{1,2})\s*h", h)
            heure = f"{heure_m.group(1)}h" if heure_m else None
            col_kind.append(("cote", cote_col_idx, book, heure))
            cote_col_idx += 1
        else:
            col_kind.append(None)

    partants = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 4:
            continue
        row: Dict[str, Any] = {}
        for i, cell in enumerate(cells):
            kind = col_kind[i] if i < len(col_kind) else None
            if kind == "cheval":
                row.update(_parse_cheval_cell(cell))
            elif kind == "numero":
                row["numero"] = _parse_int(cell.get_text(strip=True))
            elif kind == "corde":
                row["corde_numero"] = _parse_int(cell.get_text(strip=True))
            elif kind == "jockey_entr":
                links = cell.find_all("a", href=True)
                texts = [a.get_text(strip=True) for a in links]
                if len(texts) >= 1:
                    row["driver"] = texts[0]
                    row["driver_fiche_url"] = "https://www.canalturf.com" + links[0]["href"] if not links[0]["href"].startswith("http") else links[0]["href"]
                if len(texts) >= 2:
                    row["entraineur"] = texts[1]
                    row["entraineur_fiche_url"] = "https://www.canalturf.com" + links[1]["href"] if not links[1]["href"].startswith("http") else links[1]["href"]
            elif kind == "poids":
                row["poids"] = cell.get_text(strip=True)
            elif kind == "valeur":
                row["valeur"] = cell.get_text(strip=True)
            elif kind == "distance":
                row["distance"] = cell.get_text(strip=True)
            elif isinstance(kind, tuple) and kind[0] == "cote":
                _, idx, book, heure = kind
                val = _parse_float(cell.get_text(strip=True))
                if val is not None:
                    timeline = row.setdefault("cotes_timeline", [])
                    timeline.append({"heure": heure, "cote": val, "bookmaker": book, "col_idx": idx})
                    bms = row.setdefault("cotes_bookmakers", {})
                    # dernière valeur vue pour ce bookmaker gagne
                    bms[book] = val
                    # compat : première cote PMU → cote_pmu
                    if book == "PMU" and "cote_pmu" not in row:
                        row["cote_pmu"] = val
                    if "cote_pmu" not in row and book in ("PMU", "ZETURF", "BETCLIC"):
                        row["cote_pmu"] = val
        if row.get("nom"):
            partants.append(row)
    return partants


def _extract_race_context(soup: BeautifulSoup, url: str) -> RaceContext:
    text = soup.get_text(" ", strip=True)

    hippodrome = None
    m = re.search(r"R\d+\s+Course\s+\d+\s*-\s*([A-ZÀ-Ü][A-ZÀ-Ü\-']*(?:\s[A-ZÀ-Ü\-']+)*?)(?=\s+(?:PLAT|TROT|HAIES|STEEPLE|OBSTACLE)\b|\s-\s)", text)
    if m:
        hippodrome = m.group(1).strip()
    if not hippodrome:
        m = re.search(r"/pronostics-PMU/\d{4}-\d{2}-\d{2}/([a-z0-9\-]+)/", url)
        if m:
            hippodrome = m.group(1).replace("-", " ").upper()

    discipline = Discipline.PLAT
    for pattern, disc in _DISCIPLINE_PATTERNS:
        if pattern.search(text):
            discipline = disc
            break

    distance_m = None
    m = re.search(r"-\s*(\d[\d\s\xa0]{2,6})\s*m\s*-", text)
    if m:
        distance_m = _parse_int(m.group(1))

    type_course = TypeCourse.AUTRE
    if re.search(r"handicap", text, re.I):
        type_course = TypeCourse.HANDICAP
    elif discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE) and re.search(r"Recul\s+de\s+\d+\s*m", text, re.I):
        # Certaines courses de trot à recul (ex. étapes du Grand National du
        # Trot, "Groupe III") n'affichent jamais le mot "handicap" en toutes
        # lettres mais appliquent bien un recul par palier de gains -- c'est
        # ce mécanisme, pas l'étiquette, qui définit le TROT HANDICAP au
        # sens du protocole (déclencheur de MODULE_RECUL / Bloc J).
        type_course = TypeCourse.HANDICAP
    elif re.search(r"r[ée]clam", text, re.I):
        type_course = TypeCourse.CLAIMER
    elif re.search(r"condition", text, re.I):
        type_course = TypeCourse.CONDITIONS

    depart = Depart.AUTOSTART if discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE) else Depart.CENTRE
    if re.search(r"\bvolt[ée]e?\b", text, re.I):
        depart = Depart.VOLTE

    allocation_eur = None
    m = re.search(r"(\d[\d\s\xa0]{2,7})\.00\s*€|(\d[\d\s\xa0]{2,7})€", text)
    if m:
        allocation_eur = _parse_float(m.group(1) or m.group(2))

    penetrometre = None
    # Le texte des conditions de course annonce des PALIERS de recul par
    # gains ("Recul de 25 mètres à 286.000€, recul de 50 mètres 464.000€"),
    # pas le recul individuel de chaque partant. Ces paliers servent
    # uniquement de garde-fou de cohérence (cf. scrape_canalturf_race, qui
    # calcule le vrai recul par cheval = distance de sa ligne - distance de
    # base de la course, à partir de la colonne "Dist." du tableau des
    # partants -- vérifié en conditions réelles le 02/08/2026).
    recul_bands = sorted({int(v) for v in re.findall(r"Recul\s+de\s+(\d+)\s*m", text, re.I)})

    date_course = None
    m = re.search(r"/pronostics-PMU/(\d{4}-\d{2}-\d{2})/", url)
    if m:
        date_course = m.group(1)

    reunion_label = None
    m = re.search(r"(R\d+)\s+Course\s+(\d+)", text)
    if m:
        reunion_label = f"{m.group(1)}C{m.group(2)}"
    if reunion_label is None:
        m = re.search(r"\bR(\d+)\s*C(\d+)\b", text, re.I)
        if m:
            reunion_label = f"R{m.group(1)}C{m.group(2)}"

    race = RaceContext(
        url_source=url, hippodrome=hippodrome or "INCONNU", discipline=discipline,
        distance_m=distance_m or 0, type_course=type_course, depart=depart,
        partants_confirmes=0, allocation_eur=allocation_eur, penetrometre=penetrometre,
        date_course=date_course, reunion_course_label=reunion_label,
    )
    race._recul_bands = recul_bands  # attaché de façon informelle -- garde-fou, voir scrape_canalturf_race
    return race


def _apply_press_picks(chevaux: List[Cheval], soup: BeautifulSoup) -> None:
    """Fusionne jusqu'à 3 pronostics structurés (Canalturf/ZEturf/Presse) --
    chacun compte comme une 'source' pour icp_global (Bloc K)."""
    text = soup.get_text("\n", strip=True)
    by_numero = {c.numero: c for c in chevaux}

    # Canalturf : BASE + CHANCES REGULIERES (les 5 premiers = "top5" pour ce pronostiqueur)
    base_m = re.search(r"BASE\s*\n(.+?)(?=CHANCES REGULIERES|OUTSIDERS|$)", text, re.S)
    chances_m = re.search(r"CHANCES REGULIERES\s*\n(.+?)(?=OUTSIDERS|Synthèse|$)", text, re.S)
    ct_numeros = []
    for m in (base_m, chances_m):
        if m:
            ct_numeros += [int(n) for n in re.findall(r"^\s*(\d{1,2})\s", m.group(1), re.M)]

    # ZEturf et Presse : tableaux "N° | Cheval | Jockey" -- on prend les 5 premières lignes
    for label in ("La sélection ZEturf.fr", "La sélection de la presse"):
        idx = text.find(label)
        if idx == -1:
            continue
        segment = text[idx:idx + 600]
        numeros = [int(n) for n in re.findall(r"\n(\d{1,2})\s", segment)][:5]
        for n in numeros:
            if n in by_numero:
                key = "ZEturf" if "ZEturf" in label else "Presse"
                by_numero[n].citations_top5_par_source = {
                    **(by_numero[n].citations_top5_par_source or {}), key: True}
                by_numero[n].icp_global = (by_numero[n].icp_global or 0) + 1

    for n in ct_numeros[:5]:
        if n in by_numero:
            by_numero[n].citations_top5_par_source = {
                **(by_numero[n].citations_top5_par_source or {}), "Canalturf": True}
            by_numero[n].icp_global = (by_numero[n].icp_global or 0) + 1


def scrape_canalturf_race(url: str) -> Tuple[RaceContext, List[Cheval], List[str]]:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    race = _extract_race_context(soup, url)

    table = _find_partants_table(soup)
    if table is None:
        raise ValueError(
            "Table des partants introuvable sur cette page CanalTurf.com. "
            "Vérifie _find_partants_table dans app/scraping/canalturf.py."
        )

    rows = _parse_partants_table(table)
    race.partants_confirmes = len(rows)

    # v1.29.27 : calculer recul dès qu'on a Dist. en trot (GNT sans mot "handicap")
    is_trot_handicap = race.discipline in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE)

    recul_bands = getattr(race, "_recul_bands", []) or []

    chevaux: List[Cheval] = []
    warnings: List[str] = []
    for i, row in enumerate(rows, start=1):
        numero = row.get("numero")
        if numero is None:
            # Ligne sans numéro exploitable (typiquement "NP" = non-partant
            # déclaré) -- on l'exclut plutôt que de lui attribuer un numéro
            # séquentiel de repli, ce qui décalerait la numérotation de tous
            # les partants réels suivants (RÈGLE 2 : ne jamais inventer une
            # donnée manquante, ici le numéro de corde).
            warnings.append(f"Partant '{row.get('nom', '?')}' ignoré : numéro introuvable (probablement NP/non-partant déclaré).")
            continue

        recul_m = None
        if is_trot_handicap:
            dist_ligne = _parse_int(row.get("distance"))
            if dist_ligne is not None and race.distance_m:
                delta = dist_ligne - race.distance_m
                if delta < 0:
                    warnings.append(
                        f"#{numero} {row.get('nom', '?')} : distance de ligne ({dist_ligne}m) "
                        f"< distance de base de la course ({race.distance_m}m) -- recul_m ignoré, à vérifier."
                    )
                else:
                    recul_m = delta
                    if recul_bands and delta not in (0, *recul_bands):
                        warnings.append(
                            f"#{numero} {row.get('nom', '?')} : recul calculé ({delta}m) ne correspond à "
                            f"aucun palier annoncé dans les conditions de course ({recul_bands}) -- à vérifier."
                        )
            elif dist_ligne is None:
                warnings.append(f"#{numero} {row.get('nom', '?')} : colonne Dist. introuvable, recul_m non calculé (RECUL_MANQUANT).")

        timeline = row.get("cotes_timeline") or []
        # Ordonner par col_idx (ordre d'apparition = chronologie matinée → course)
        timeline = sorted(timeline, key=lambda x: x.get("col_idx", 0))
        bms = row.get("cotes_bookmakers") or {}
        cote_matin = timeline[0]["cote"] if timeline else _parse_float(row.get("cote_pmu"))
        cote_avant = timeline[-1]["cote"] if timeline else cote_matin
        # Prefer PMU for principal pair when available
        if "PMU" in bms and len(timeline) <= 1:
            cote_matin = cote_matin or bms["PMU"]
            cote_avant = bms["PMU"]
        cheval = Cheval(
            numero=numero, nom=row.get("nom", f"Cheval{numero}"),
            age=row.get("age"), sexe=row.get("sexe"),
            driver_jockey=row.get("driver"), entraineur=row.get("entraineur"),
            driver_fiche_url=row.get("driver_fiche_url"), entraineur_fiche_url=row.get("entraineur_fiche_url"),
            musique=row.get("musique"),
            valeur_pmu=_parse_float(row.get("valeur")),
            poids_actuel_kg=_parse_float(row.get("poids")),
            recul_m=recul_m,
            cote_matin=cote_matin, cote_avant_course=cote_avant,
            fiche_url=row.get("fiche_url"),
            numero_autostart=row.get("corde_numero"),
            cotes_timeline=timeline or None,
            cotes_bookmakers=bms or None,
        )
        # Repli TROT AUTOSTART : N° partant = position autostart si corde absente
        if cheval.numero_autostart is None and race.depart == Depart.AUTOSTART:
            cheval.numero_autostart = numero
        if not cheval.musique:
            warnings.append(f"#{numero} {cheval.nom} : musique introuvable")
        if not cheval.cote_matin:
            warnings.append(f"#{numero} {cheval.nom} : cote introuvable (probablement pas encore publiée)")
        chevaux.append(cheval)

    if len(chevaux) < 3:
        raise ValueError(f"Seulement {len(chevaux)} partant(s) extrait(s) depuis {url}.")

    from app.scraping.base import validate_chevaux
    validate_chevaux(chevaux, url)

    _apply_press_picks(chevaux, soup)

    return race, chevaux, warnings
