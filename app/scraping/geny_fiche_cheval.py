"""
geny_fiche_cheval.py -- Fiche individuelle d'un cheval sur geny.com
(/cheval/{id}-{slug}/ ou /cheval/{id}-{slug}/course/{course_id}).

Construit le 19/09/2026 (Golden) à partir d'UNE SEULE vraie page fetchée
(King de Larré, https://www.geny.com/cheval/2769193-king-de-larre/course/1673688) :
contrairement à /course/{id}/partants-pronostics (dont la table des
partants ne s'affiche pas dans le HTML rendu servi -- voir geny.py), la
fiche cheval individuelle EST intégralement rendue côté serveur (confirmé
avec 2 méthodes d'extraction différentes) : identité, records, et un
historique de carrière complet (58 courses dans l'exemple observé).

AVERTISSEMENT HONNÊTE : contrairement à turfoo_fiche_cheval.py ou
zoneturf_fiche_cheval.py (bâtis et affinés sur plusieurs pages réelles au
fil du temps), ce module n'a été vérifié que sur CET UNIQUE exemple. La
structure ligne par ligne du tableau carrière n'a pas de séparateurs
fiables entre cellules dans le texte extrait (get_text), donc le
parsing par ancres (discipline en tête de ligne) + fenêtre glissante est
une hypothèse raisonnable mais non éprouvée sur d'autres disciplines
(Plat/Haies/Steeple) ou d'autres mises en page (ex. cheval avec beaucoup
moins de courses). À tester en conditions réelles et ajuster.

Champs observés mais non exploités ici car absents du modèle Cheval :
père/mère (pedigree), robe. Laissés de côté volontairement (pas de champ
correspondant, voir models.py).

Utilisation prévue : enrichment.py::enrich_cheval(), nouvelle branche
`elif "geny.com" in cheval.fiche_url`, une fois geny.py mis à jour pour
construire fiche_url à partir de idCheval (voir _parse_geny_rsc_partants).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.geny_fiche")

_DISCIPLINES = ("Attelé", "Monté", "Plat", "Haies", "Steeple", "Cross")
_DISC_RE = re.compile(r"^(" + "|".join(_DISCIPLINES) + r")$")

# Ligne juste avant la discipline : "04/08" puis (éventuellement séparée
# par une ligne vide) "2026". On accepte 1 à 3 lignes intermédiaires
# vides ou non pour rester tolérant à des variations de mise en page.
_DATE_JOUR_MOIS_RE = re.compile(r"^(\d{2})/(\d{2})$")
_ANNEE_RE = re.compile(r"^(\d{4})$")

_ALLOCATION_RE = re.compile(r"([\d\s\xa0\u202f]{2,7})\s*€")
_DISTANCE_RE = re.compile(r"(\d[\d\s\xa0\u202f]{2,6})\s*m\b", re.I)
_CORDE_RE = re.compile(r"^(Gauche|Droite)$", re.I)
_SURFACE_RE = re.compile(r"^(Dur|Herbe|Sable|PSF|Cendrée|Mixte)$", re.I)
_CATEGORIE_RE = re.compile(r"^Crse\s*([A-Z])$", re.I)
_PARCOURS_RE = re.compile(r"^(GP{1,2})$")
# Rang : "1er", "2e"/"2ᵉ", "9e", "Dai" (disqualifié/distancé), "Nc" (non
# classé), "Ret"/"NP" -- observés sur la page réelle ou par analogie avec
# turfoo_fiche_cheval.py.
_RANG_RE = re.compile(r"^(\d{1,2})(?:er|e|ᵉ)$|^(Dai|Nc|Ret|NP|Disq)$", re.I)
_CHRONO_RE = re.compile(r"^\d'\d{2}(?:''|\"|′′)\d$")
_COTE_RE = re.compile(r"^\d{1,3}(?:[.,]\d{1,2})?$")
# Nom de driver/jockey observé : "P. P. Ploquin" (double initiale),
# "T. Borodajko" (initiale simple). Le point de l'initiale doit être
# obligatoire à CHAQUE répétition -- sinon la 1ère lettre du nom de
# famille se fait avaler comme une fausse initiale (bug trouvé en test
# le 19/09/2026 : "T. Borodajko" ne matchait pas avec un point optionnel).
_DRIVER_RE = re.compile(r"^[A-ZÀ-Ü]\.(?:\s*[A-ZÀ-Ü]\.)*\s+[A-ZÀ-Ü][A-Za-zà-ÿ\-']+$")


@dataclass
class GenyFicheHistorique:
    date: Optional[str]              # ISO YYYY-MM-DD
    hippodrome: str
    discipline: Optional[str]        # Attelé|Monté|Plat|Haies|Steeple
    corde: Optional[str]             # Gauche|Droite
    surface: Optional[str]           # Dur|Herbe|Sable|PSF|...
    categorie: Optional[str]         # lettre de classe (E, D, ...)
    allocation_eur: Optional[float]
    distance_m: Optional[int]
    parcours: Optional[str]          # GP|GPP|None
    autostart: bool
    rang: Optional[int]              # None si Dai/Nc/non numérique
    rang_brut: Optional[str]         # valeur telle quelle (ex. "Dai", "9e")
    driver: Optional[str]
    chrono: Optional[str]            # "1'14''0" tel quel (pas reconverti ici)
    cote: Optional[float]


@dataclass
class GenyFicheCheval:
    nom: str
    age: Optional[int] = None
    sexe: Optional[str] = None       # H|M|F (1ère lettre : Hongre/Mâle/Femelle)
    musique: Optional[str] = None
    delai_j_affiche: Optional[int] = None   # "Dernière course : N jours", donné par Geny lui-même
    entraineur: Optional[str] = None
    proprietaire: Optional[str] = None
    gains_carriere_eur: Optional[float] = None
    record_distance: Optional[str] = None   # chrono brut (record sur la distance couverte)
    record_parcours: Optional[str] = None
    records_par_discipline: dict = field(default_factory=dict)  # ex. {"Attelé": "1'11''7", "Monté": "..."}
    record_absolu: Optional[str] = None      # meilleur chrono toutes disciplines confondues
    nb_courses: Optional[int] = None
    victoires_carriere: Optional[int] = None
    places_2e_3e: Optional[int] = None
    places_4e_5e: Optional[int] = None
    historique: List[GenyFicheHistorique] = field(default_factory=list)


def _normalize_slug(nom: str) -> str:
    """Reproduit le format observé dans l'URL canonique Geny
    ("King de Larré" -> "king-de-larre") : minuscules, accents retirés,
    tout sauf alphanumérique -> tiret. Hypothèse non garantie : si le
    slug ne correspond pas exactement à celui attendu par Geny, à
    vérifier si le site 200 quand même (redirection sur l'ID) ou 404."""
    s = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "cheval"


def build_geny_fiche_url(id_cheval: int, nom: str) -> str:
    return f"https://www.geny.com/cheval/{id_cheval}-{_normalize_slug(nom)}"


def _parse_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = re.sub(r"[\s\xa0\u202f]", "", s).replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _parse_rang(brut: str) -> Optional[int]:
    m = re.match(r"^(\d{1,2})", brut)
    return int(m.group(1)) if m else None


def chrono_to_seconds(chrono: Optional[str]) -> Optional[float]:
    """Convertit un chrono format Geny ("1'14''0") en secondes (74.0).
    Même logique que zoneturf.py::parse_record_chrono, adaptée au séparateur
    observé ici (deux apostrophes ou un guillemet double, pas de guillemet
    typographique)."""
    if not chrono:
        return None
    m = re.match(r"^(\d+)'(\d{2})(?:''|\"|′′)(\d)?$", chrono.strip())
    if not m:
        return None
    minutes, secondes, dixiemes = m.groups()
    total = int(minutes) * 60 + int(secondes) + (int(dixiemes) / 10 if dixiemes else 0)
    return round(total, 1)


def _parse_identite(text: str) -> dict:
    out: dict = {"age": None, "sexe": None, "musique": None, "delai_j_affiche": None,
                 "entraineur": None, "proprietaire": None, "gains_carriere_eur": None}

    m = re.search(r"\b(Hongre|M[aâ]le|Femelle|Jument)\s+de\s+(\d+)\s+ans?\b", text, re.I)
    if m:
        out["sexe"] = m.group(1).upper()[0]
        out["age"] = int(m.group(2))

    m = re.search(r"Musique\s*\n?\s*([0-9A-Za-z()\s]{2,40}?)(?:\n\n|\nDernière course)", text)
    if m:
        out["musique"] = re.sub(r"\s+", "", m.group(1))

    m = re.search(r"Dernière course\s*:\s*\n?\s*(\d+)\s*jours?", text, re.I)
    if m:
        out["delai_j_affiche"] = int(m.group(1))

    m = re.search(r"Entra[iî]neur\s*\n\s*(.+)", text, re.I)
    if m:
        out["entraineur"] = m.group(1).strip()

    m = re.search(r"Propri[ée]taire\s*\n\s*(.+)", text, re.I)
    if m:
        out["proprietaire"] = m.group(1).strip()

    m = re.search(r"Gains de carri[èe]re\s*\n\s*([\d\s\xa0\u202f]+)\s*€", text, re.I)
    if m:
        out["gains_carriere_eur"] = _parse_float(m.group(1))

    return out


def _parse_carriere_stats(text: str) -> dict:
    out = {"nb_courses": None, "victoires_carriere": None, "places_2e_3e": None, "places_4e_5e": None}
    m = re.search(r"(\d+)\s*Victoires?\s*\(", text, re.I)
    if m:
        out["victoires_carriere"] = int(m.group(1))
    m = re.search(r"(\d+)\s*Places?\s*2[eᵉ]\s*et\s*3[eᵉ]\s*\(", text, re.I)
    if m:
        out["places_2e_3e"] = int(m.group(1))
    m = re.search(r"(\d+)\s*Places?\s*4[eᵉ]\s*et\s*5[eᵉ]\s*\(", text, re.I)
    if m:
        out["places_4e_5e"] = int(m.group(1))
    m = re.search(r"sur\s*(\d+)\s*courses", text, re.I)
    if m:
        out["nb_courses"] = int(m.group(1))
    return out


def _parse_records(text: str) -> dict:
    """Section RECORDS : une entrée par catégorie (Distance, Parcours, une
    par discipline courue -- Attelé/Monté/Plat/..., puis Absolu), chacune
    suivie de son chrono SI le cheval en a un dans cette catégorie (sinon
    la ligne suivante est directement la catégorie suivante ou CARRIÈRE).
    Golden a confirmé (capture d'écran 20/09/2026, filtre "Monté & Attelé"
    / "Attelé" sur la page course) que les records sont bien scindés par
    discipline -- un ancien code ne gardait que la 1ère discipline
    trouvée ; corrigé pour capturer toutes les disciplines présentes."""
    out = {"record_distance": None, "record_parcours": None,
           "records_par_discipline": {}, "record_absolu": None}

    m_start = re.search(r"\bRECORDS\b", text)
    m_end = re.search(r"\bCARRI[ÈE]RE\b", text)
    if not m_start:
        return out
    bloc = text[m_start.end():m_end.start() if m_end else m_start.end() + 2000]
    lines = [l.strip() for l in bloc.splitlines() if l.strip()]

    _CHRONO_LINE = re.compile(r"^\d'\d{2}(?:''|\"|′′)\d$")
    _CATEGORIES = {"Distance", "Parcours", "Absolu"} | set(_DISCIPLINES)

    i = 0
    n = len(lines)
    _DATE_LINE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    while i < n:
        label = lines[i]
        if label in _CATEGORIES:
            chrono = lines[i + 1] if i + 1 < n and _CHRONO_LINE.match(lines[i + 1]) else None
            if label == "Distance":
                out["record_distance"] = chrono
            elif label == "Parcours":
                out["record_parcours"] = chrono
            elif label == "Absolu":
                out["record_absolu"] = chrono
            elif chrono:
                out["records_par_discipline"][label] = chrono
            if chrono:
                # Consomme le détail qui suit le chrono (date, hippo, rang,
                # distance, discipline-de-cette-course, "Auto" éventuel) --
                # sinon la mention de discipline qu'il contient serait prise
                # à tort pour une nouvelle ancre de catégorie de record.
                j = i + 2
                if j < n and _DATE_LINE.match(lines[j]):
                    j += 1        # date
                    if j < n:
                        j += 1    # hippodrome
                    if j < n and _RANG_RE.match(lines[j]):
                        j += 1    # rang
                    if j < n and _DISTANCE_RE.search(lines[j]):
                        j += 1    # distance (éventuellement + code parcours, ex. "2 100m GP")
                    if j < n and lines[j] in _DISCIPLINES:
                        j += 1    # discipline de cette course (souvent redondante avec le label)
                    if j < n and lines[j].lower() == "auto":
                        j += 1    # indicateur autostart
                    i = j
                    continue
        i += 1
    return out


def _parse_historique(text: str, nom_cheval: str) -> List[GenyFicheHistorique]:
    """Parsing par ancre (ligne de discipline) + fenêtre glissante jusqu'à
    l'ancre suivante, dans le même esprit que turfoo_fiche_cheval.py --
    nécessaire ici car le tableau carrière n'a pas de séparateur de
    cellule fiable dans get_text(), seulement des lignes."""
    lines = [l.strip() for l in text.splitlines()]

    # Le tableau carrière (une entrée par course) vient TOUJOURS après le
    # bloc RECORDS + CARRIÈRE -- qui contient lui aussi le mot "Attelé"
    # (comme libellé de record ET comme valeur de discipline dans chaque
    # ligne de record), ce qui produit de faux positifs si on ne le
    # sait pas. On démarre la recherche d'ancres après "sur N courses".
    start_idx = 0
    for i, l in enumerate(lines):
        if re.match(r"^sur\s+\d+\s+courses$", l, re.I):
            start_idx = i + 1
            break

    anchors = [i for i in range(start_idx, len(lines)) if _DISC_RE.match(lines[i])]
    historique: List[GenyFicheHistorique] = []

    for k, i in enumerate(anchors):
        discipline = lines[i]
        window_end = anchors[k + 1] if k + 1 < len(anchors) else min(i + 30, len(lines))
        window = [l for l in lines[i + 1:window_end] if l]

        # Date : 1 à 3 lignes AVANT l'ancre (jour/mois puis année, avec
        # parfois une ligne vide entre les deux -- déjà filtrée ci-dessus
        # côté "lines" brut, donc on cherche dans les lignes non filtrées).
        date_iso = None
        jour_mois = None
        for back in range(1, 5):
            j = i - back
            if j < 0:
                break
            l = lines[j].strip()
            if not l:
                continue
            if _ANNEE_RE.match(l) and jour_mois is None:
                # on continue à chercher jour/mois plus loin en arrière
                annee_candidate = l
                for back2 in range(back + 1, back + 4):
                    j2 = i - back2
                    if j2 < 0:
                        break
                    l2 = lines[j2].strip()
                    if _DATE_JOUR_MOIS_RE.match(l2):
                        jm = _DATE_JOUR_MOIS_RE.match(l2)
                        date_iso = f"{annee_candidate}-{jm.group(2)}-{jm.group(1)}"
                        break
                break

        hippodrome = window[0] if window else "INCONNU"

        corde = surface = categorie = parcours = rang_brut = driver = chrono = None
        allocation = distance = cote = None
        autostart = False
        rang: Optional[int] = None

        for l in window:
            if corde is None and _CORDE_RE.match(l):
                corde = l
                continue
            if surface is None and _SURFACE_RE.match(l):
                surface = l
                continue
            if categorie is None:
                m = _CATEGORIE_RE.match(l)
                if m:
                    categorie = m.group(1).upper()
                    continue
            if allocation is None:
                m = _ALLOCATION_RE.match(l)
                if m:
                    allocation = _parse_float(m.group(1))
                    continue
            if distance is None:
                m = _DISTANCE_RE.match(l)
                if m:
                    raw = re.sub(r"[^\d]", "", m.group(1))
                    distance = int(raw) if raw else None
                    continue
            if parcours is None and _PARCOURS_RE.match(l):
                parcours = l.upper()
                continue
            if l.lower() == "auto":
                autostart = True
                continue
            if rang_brut is None and _RANG_RE.match(l):
                rang_brut = l
                rang = _parse_rang(l)
                continue
            if driver is None and _DRIVER_RE.match(l):
                driver = l
                continue
            if chrono is None and _CHRONO_RE.match(l.replace('"', "''").replace("′′", "''")):
                chrono = l
                continue
            if cote is None and rang_brut is not None and _COTE_RE.match(l):
                cote = _parse_float(l)
                continue

        historique.append(GenyFicheHistorique(
            date=date_iso, hippodrome=hippodrome, discipline=discipline,
            corde=corde, surface=surface, categorie=categorie,
            allocation_eur=allocation, distance_m=distance, parcours=parcours,
            autostart=autostart, rang=rang, rang_brut=rang_brut,
            driver=driver, chrono=chrono, cote=cote,
        ))

    return historique


def fetch_geny_fiche_cheval(url_or_id, nom_cheval: Optional[str] = None) -> GenyFicheCheval:
    """url_or_id : soit une URL complète geny.com/cheval/{id}-{slug}[/course/{cid}],
    soit un id_cheval entier (nécessite alors nom_cheval pour construire l'URL
    via build_geny_fiche_url -- slug non garanti, voir avertissement en tête
    de fichier)."""
    if isinstance(url_or_id, str) and url_or_id.startswith("http"):
        url = url_or_id
    else:
        if not nom_cheval:
            raise ValueError("nom_cheval requis quand url_or_id n'est pas une URL complète.")
        url = build_geny_fiche_url(int(url_or_id), nom_cheval)

    html = fetch_html(url, via_scraperapi=True)
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)

    nom = nom_cheval or "INCONNU"
    m = re.search(r"^\d+\.\s*(.+)$", text, re.M)
    if m:
        nom = m.group(1).strip()

    identite = _parse_identite(text)
    stats = _parse_carriere_stats(text)
    records = _parse_records(text)
    historique = _parse_historique(text, nom)

    if not historique and stats.get("nb_courses"):
        logger.warning(
            "geny_fiche_cheval: stats carrière trouvées (%s courses) mais aucun "
            "historique détaillé extrait pour %s (%s) -- structure de page probablement "
            "différente de l'exemple de référence (King de Larré), à vérifier.",
            stats.get("nb_courses"), nom, url,
        )

    return GenyFicheCheval(
        nom=nom,
        age=identite["age"], sexe=identite["sexe"], musique=identite["musique"],
        delai_j_affiche=identite["delai_j_affiche"],
        entraineur=identite["entraineur"], proprietaire=identite["proprietaire"],
        gains_carriere_eur=identite["gains_carriere_eur"],
        record_distance=records["record_distance"], record_parcours=records["record_parcours"],
        records_par_discipline=records["records_par_discipline"], record_absolu=records["record_absolu"],
        nb_courses=stats["nb_courses"], victoires_carriere=stats["victoires_carriere"],
        places_2e_3e=stats["places_2e_3e"], places_4e_5e=stats["places_4e_5e"],
        historique=historique,
    )
