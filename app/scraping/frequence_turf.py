"""
frequence_turf.py -- Scraper pour les 2 pages quotidiennes Quinté de
frequence-turf.fr. Découvert et vérifié le 03/08/2026 (2 pages réelles
fournies par l'utilisateur, course du 19/07/2026 à Chantilly).

Ce N'EST PAS un scraper de programme/partants (Turfoo/CanalTurf font déjà
ça) -- c'est un scraper d'ENRICHISSEMENT qui, en 2 pages, couvre à lui
seul :
  - Bloc K (icp_global, citations_top5_par_source, favori_unanime,
    icp_pondere) : 7-8 sources de presse agrégées + synthèse pondérée
    DÉJÀ CALCULÉE par Frequence-Turf (colonne "Synthèse n°2").
  - Bloc H (classement_national) : table "Cravache d'Or" (jockeys, PLAT)
    ou "Sulky d'Or" (drivers, TROT) -- à confirmer sur une course TROT,
    seul un exemple PLAT a été vérifié à ce jour.
  - Bloc I (tendance poids/valeur handicap) : 3 tables stable/hausse/
    baisse, avec delta en kg pour hausse/baisse.
  - Météo (absente du modèle actuel, ajoutée ici) : température, vent,
    risque de précipitation, état de piste résultant.
  - 5 tables statistiques supplémentaires (vues en entier sur l'exemple
    du 28/08/2026, Cabourg R1C4 -- absentes de l'exemple du 19/07/2026
    utilisé pour les blocs ci-dessus, donc ce sont deux mises en page
    partiellement différentes de la même page "base-tocard", à traiter
    comme des sections indépendantes et non-exclusives) : "Moyenne de
    gains" (repli GAINS_MANQUANTS de module_a_sri), "Record absolu"
    (repli record_chrono_sec si Zone-Turf absent), "Record parcours"
    (nouveau champ informatif), "Meilleurs drivers"/"Meilleurs
    entraîneurs"/"Meilleurs tandems" (taux Top5 6 mois -- alimente
    driver_stats/trainer_stats/tandem_driver_ecurie, réduit les cas où
    ces objets restent à None faute d'autre source).

LIMITE DE VALIDATION IMPORTANTE : je n'ai pas eu accès au HTML brut de
ces pages (web_fetch renvoie du contenu déjà converti en markdown, et
frequence-turf.fr n'est pas dans l'allowlist réseau du bac à sable de
développement) -- seul le RENDU markdown a pu être inspecté (2 exemples
à ce jour : 19/07/2026 Chantilly, et 28/08/2026 Cabourg pour les 5
tables statistiques). Le parseur ci-dessous est écrit de façon
défensive (recherche par texte de titre + structure de table générique,
comme partout ailleurs dans ce projet, PAS de dépendance à des classes
CSS devinées) mais DOIT être revalidé contre le vrai HTML dès que
possible -- soit dès maintenant via une requête directe si le réseau de
l'app le permet (Render.com, pas ce bac à sable), soit à la prochaine
session avec accès réseau.

Couverture NON gérée ici (à ajouter si utile) : matching nom-cheval en
texte libre dans les paragraphes d'analyse (musique/palmarès détaillés
par cheval) -- seuls les tableaux structurés sont exploités pour
l'instant, plus fiables et moins coûteux à parser correctement.
"""
from __future__ import annotations
import os
import logging
import re
from datetime import date
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from pydantic import BaseModel

from app.scraping.base import fetch_html

logger = logging.getLogger("vantage.scraping.frequence_turf")

_JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS_FR = ["", "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
            "aout", "septembre", "octobre", "novembre", "decembre"]  # ASCII URLs FT


def frequence_turf_enabled() -> bool:
    """Flag VANTAGE_FREQUENCE_TURF (défaut: activé, aligné v1.26)."""
    val = os.environ.get("VANTAGE_FREQUENCE_TURF", "1").strip().lower()
    return val not in {"0", "false", "no", "off"}


def build_urls(d: date) -> Dict[str, str]:
    """URLs Fréquence-Turf pour une date (passée / jour / futur si publié).

    Patterns vérifiés 20/09/2026 :
      - pronostics-presse-quinte-pmu-{jour}-{j}-{mois}-{aaaa}/
      - pronostic-quinte-pmu-{jour}-{j}-{mois}-{aaaa}/
    Anciens patterns (meilleurs-pronostics-…, base-tocard-…) conservés en repli.
    """
    jour = _JOURS_FR[d.weekday()]
    mois = _MOIS_FR[d.month]
    suffixe = f"{jour}-{d.day}-{mois}-{d.year}"
    return {
        "presse": f"https://frequence-turf.fr/pronostics-presse-quinte-pmu-{suffixe}/",
        "base_tocard": f"https://frequence-turf.fr/pronostic-quinte-pmu-{suffixe}/",
    }


def _all_ft_urls_for_date(d: date) -> Dict[str, List[str]]:
    """Tous les candidats URL (passé/jour/futur) pour maximiser le rappel."""
    jour = _JOURS_FR[d.weekday()]
    mois = _MOIS_FR[d.month]
    suffixes = [
        f"{jour}-{d.day}-{mois}-{d.year}",
        f"{jour}-{d.day:02d}-{mois}-{d.year}",
        d.strftime("%d-%m-%Y"),
    ]
    presse: List[str] = []
    bt: List[str] = []
    for suf in suffixes:
        presse.extend([
            f"https://frequence-turf.fr/pronostics-presse-quinte-pmu-{suf}/",
            f"https://frequence-turf.fr/meilleurs-pronostics-presse-quinte-pmu-{suf}/",
            f"https://frequence-turf.fr/pronostics-presse-pmu-quinte-{suf}/",
        ])
        bt.extend([
            f"https://frequence-turf.fr/pronostic-quinte-pmu-{suf}/",
            f"https://frequence-turf.fr/pronostic-quinte-pmu-base-tocard-{suf}/",
            f"https://frequence-turf.fr/pronostics-quinte-pmu-{suf}/",
        ])
    # Pages « du jour » : uniquement si d = aujourd'hui Paris (évite de
    # coller le Quinté du 21 sur une course du 19).
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        paris_today = datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        paris_today = date.today()
    if d == paris_today:
        presse.insert(0, "https://frequence-turf.fr/pronostics-presse-pmu-quinte-du-jour/")
        bt.insert(0, "https://frequence-turf.fr/pronostics-quinte/")
    # Dédup en conservant l'ordre
    return {
        "presse": list(dict.fromkeys(presse)),
        "base_tocard": list(dict.fromkeys(bt)),
    }


class PressConsensus(BaseModel):
    picks_par_source: Dict[str, List[int]] = {}          # "Genybet" -> [6,1,12,13,2,8,5,3]
    citations_par_numero: Dict[int, int] = {}             # numero -> nb de sources qui le citent (top8)
    points_pondere_par_numero: Dict[int, float] = {}      # numero -> "Synthèse n°2", déjà pondéré position
    nb_sources: int = 0
    warnings: List[str] = []

    def to_bloc_k(self, numero: int) -> Dict[str, object]:
        """Traduit vers les champs Bloc K du modèle Cheval."""
        citations_top5 = {
            src: (numero in picks[:5])
            for src, picks in self.picks_par_source.items()
        }
        icp_global = sum(1 for cited in citations_top5.values() if cited)
        favori_unanime = self.nb_sources > 0 and all(
            picks and picks[0] == numero for picks in self.picks_par_source.values()
        )
        return {
            "icp_global": icp_global,
            "citations_top5_par_source": citations_top5,
            "favori_unanime": favori_unanime,
            "icp_pondere": self.points_pondere_par_numero.get(numero),
        }


class BaseTocardExtras(BaseModel):
    classement_national_par_numero: Dict[int, int] = {}   # numero -> rang (jockey OU driver, selon discipline)
    poids_delta_kg_par_numero: Dict[int, float] = {}      # numero -> delta signé (hausse>0, baisse<0)
    pronostic_stats_ordre: List[int] = []                 # "Pronostic Quinté stats", 8e source indépendante
    meteo_temp_c: Optional[float] = None
    meteo_vent_kmh_max: Optional[float] = None
    meteo_risque_pluie: Optional[bool] = None
    # 5 tables ajoutées le 02/09/2026 (vues en entier sur l'exemple du
    # 28/08/2026, Cabourg R1C4 -- absentes de l'exemple initial du
    # 19/07/2026, qui n'avait pas ces tables statistiques) :
    gains_moyenne_par_numero: Dict[int, float] = {}       # "Moyenne de gains" (€/course)
    record_absolu_sec_par_numero: Dict[int, float] = {}   # "Record absolu" (RK toutes pistes)
    record_parcours_sec_par_numero: Dict[int, float] = {} # "Record parcours" (RK sur l'hippodrome du jour)
    driver_taux_top5_par_numero: Dict[int, float] = {}    # "Meilleurs drivers" (% Top5, 6 mois, champ du jour)
    entraineur_taux_top5_par_numero: Dict[int, float] = {}  # "Meilleurs entraîneurs" (idem, entraîneur)
    tandem_taux_top5_par_numero: Dict[int, float] = {}    # "Meilleurs tandems" (idem, driver-entraîneur)
    warnings: List[str] = []


def _find_heading(soup: BeautifulSoup, *texts: str):
    """Trouve un h2/h3 dont le texte contient un des `texts` (insensible
    casse/accents approximatif -- comparaison simple sur texte normalisé)."""
    for tag in soup.find_all(["h2", "h3"]):
        t = tag.get_text(" ", strip=True).lower()
        if any(needle.lower() in t for needle in texts):
            return tag
    return None


def _next_table(tag) -> Optional[BeautifulSoup]:
    """Premier <table> après un tag donné (frère suivant ou descendant
    d'un frère suivant)."""
    if tag is None:
        return None
    for sib in tag.find_all_next("table"):
        # on s'arrête si on a dépassé la section suivante (heuristique :
        # pas de garde-fou strict ici, cf. limite de validation en tête
        # de fichier -- à resserrer une fois le vrai HTML consultable)
        return sib
    return None


def _parse_numero_nom(cell_text: str) -> Optional[int]:
    """Extrait le numéro d'une cellule du type 'N° 11 – Nom' ou '11'."""
    m = re.search(r"\d+", cell_text)
    return int(m.group(0)) if m else None


def _parse_chrono_fr(s: str) -> Optional[float]:
    """Convertit un chrono trot format Frequence-Turf ("1'11″2" ou
    "1’13″70") en secondes. Variante locale de
    zoneturf.parse_record_chrono : FT utilise le caractère double prime
    (″, U+2033) plutôt que le guillemet droit -- non géré par la version
    Zone-Turf, d'où cette fonction dédiée plutôt qu'un réemploi direct."""
    if not s:
        return None
    m = re.search(r"(\d+)['’](\d{1,2})[\"”″](\d{1,2})?", s.strip())
    if not m:
        return None
    minutes, secondes, dixiemes = m.groups()
    total = int(minutes) * 60 + int(secondes) + (int(dixiemes) / 10 if dixiemes else 0)
    return round(total, 2)


def _parse_pct(s: str) -> Optional[float]:
    m = re.search(r"([\d,.]+)\s*%", s)
    return float(m.group(1).replace(",", ".")) if m else None


def _parse_eur(s: str) -> Optional[float]:
    m = re.search(r"([\d\s\u00a0]+(?:[,.]\d+)?)\s*€", s)
    if not m:
        return None
    cleaned = re.sub(r"[\s\u00a0]", "", m.group(1)).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_stat_table(table, value_parser) -> Dict[int, float]:
    """Générique pour les 5 tables N°/valeur (gains, record, %) : 1re
    colonne = numéro, dernière colonne = valeur à parser."""
    out: Dict[int, float] = {}
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        numero = _parse_numero_nom(cells[0].get_text(strip=True))
        if numero is None:
            continue
        valeur = value_parser(cells[-1].get_text(strip=True))
        if valeur is not None:
            out[numero] = valeur
    return out


def parse_pronostics_presse(html: str) -> PressConsensus:
    soup = BeautifulSoup(html, "lxml")
    result = PressConsensus()

    h_picks = _find_heading(soup, "pronostics quinté du jour", "pronostics presse")
    table_picks = _next_table(h_picks)
    if table_picks is None:
        result.warnings.append("Table des pronostics par source introuvable (structure de page changée ?)")
    else:
        for tr in table_picks.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            source = cells[0].get_text(strip=True).strip("* ")
            if not source:
                continue
            picks = []
            for c in cells[1:]:
                n = _parse_numero_nom(c.get_text(strip=True))
                if n is not None:
                    picks.append(n)
            if picks:
                result.picks_par_source[source] = picks
        result.nb_sources = len(result.picks_par_source)
        for picks in result.picks_par_source.values():
            for n in picks:
                result.citations_par_numero[n] = result.citations_par_numero.get(n, 0) + 1

    h_pond = _find_heading(soup, "synthèse de la presse n°2", "pondération par points")
    table_pond = _next_table(h_pond)
    if table_pond is None:
        result.warnings.append("Table de synthèse pondérée (n°2) introuvable.")
    else:
        for tr in table_pond.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            numero = _parse_numero_nom(cells[0].get_text(strip=True))
            m = re.search(r"[\d,.]+", cells[1].get_text(strip=True))
            if numero is not None and m:
                result.points_pondere_par_numero[numero] = float(m.group(0).replace(",", "."))

    # "Synthèse n°1" (comptage de citations) est parsée DIRECTEMENT plutôt
    # que recalculée depuis la table à 7 sources ci-dessus : elle inclut
    # en réalité le pick propre de Frequence-Turf (page base-tocard,
    # absent de la table de comparaison) -- vérifié sur l'exemple du
    # 19/07/2026 (Most Glamorous : 6 citations dans les 7 sources
    # comparées, mais 7 dans la Synthèse n°1 -- écart de +1 cohérent avec
    # l'ajout du pick Frequence-Turf comme 8e source implicite).
    h_cit = _find_heading(soup, "synthèse de la presse n°1", "les plus cités")
    table_cit = _next_table(h_cit)
    if table_cit is not None:
        for tr in table_cit.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            numero = _parse_numero_nom(cells[0].get_text(strip=True))
            m = re.search(r"\d+", cells[1].get_text(strip=True))
            if numero is not None and m:
                result.citations_par_numero[numero] = int(m.group(0))
    elif not result.citations_par_numero:
        result.warnings.append("Table de synthèse des citations (n°1) introuvable -- repli sur comptage dérivé des 7 sources (sous-estime probablement de 1 les chevaux aussi retenus par Frequence-Turf).")

    if not result.picks_par_source:
        result.warnings.append("Aucune source de pronostic extraite -- page probablement non conforme au patron attendu, ne pas utiliser telle quelle.")
    return result


def parse_base_tocard(html: str) -> BaseTocardExtras:
    soup = BeautifulSoup(html, "lxml")
    result = BaseTocardExtras()

    # --- Classement national (Cravache d'Or PLAT ou Sulky d'Or TROT) ---
    h_classement = _find_heading(soup, "cravache d'or", "sulky d'or", "étrier d'or")
    table_classement = _next_table(h_classement)
    if table_classement is None:
        result.warnings.append("Table de classement national (Cravache/Sulky d'Or) introuvable.")
    else:
        for tr in table_classement.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            numero = _parse_numero_nom(cells[0].get_text(strip=True))
            rang_txt = cells[2].get_text(strip=True)
            m = re.search(r"\d+", rang_txt)
            if numero is not None and m:
                result.classement_national_par_numero[numero] = int(m.group(0))

    # --- Tendance poids (3 tables : stable / hausse / baisse) ---
    for needle, signe in [("baisse de poids", -1.0), ("hausse de poids", 1.0)]:
        h = _find_heading(soup, needle)
        table = _next_table(h)
        if table is None:
            continue
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            numero = _parse_numero_nom(cells[0].get_text(strip=True))
            m = re.search(r"[\d,.]+", cells[2].get_text(strip=True))
            if numero is not None and m:
                delta = float(m.group(0).replace(",", ".")) * signe
                # le tableau donne parfois déjà un signe (ex "-0,5 kg") ;
                # on normalise sur la valeur absolue x signe de la section
                result.poids_delta_kg_par_numero[numero] = abs(delta) * (1 if signe > 0 else -1)

    # --- 5 tables statistiques (vues en entier le 28/08/2026, Cabourg
    # R1C4) : gains, records, % drivers/entraîneurs/tandems ---
    h_gains = _find_heading(soup, "moyenne de gains")
    t_gains = _next_table(h_gains)
    if t_gains is not None:
        result.gains_moyenne_par_numero = _parse_stat_table(t_gains, _parse_eur)
    else:
        result.warnings.append("Table 'Moyenne de gains' introuvable.")

    h_rec_abs = _find_heading(soup, "record absolu")
    t_rec_abs = _next_table(h_rec_abs)
    if t_rec_abs is not None:
        result.record_absolu_sec_par_numero = _parse_stat_table(t_rec_abs, _parse_chrono_fr)
    else:
        result.warnings.append("Table 'Record absolu' introuvable.")

    h_rec_par = _find_heading(soup, "record parcours")
    t_rec_par = _next_table(h_rec_par)
    if t_rec_par is not None:
        result.record_parcours_sec_par_numero = _parse_stat_table(t_rec_par, _parse_chrono_fr)
    else:
        result.warnings.append("Table 'Record parcours' introuvable.")

    h_drivers = _find_heading(soup, "meilleurs drivers")
    t_drivers = _next_table(h_drivers)
    if t_drivers is not None:
        result.driver_taux_top5_par_numero = _parse_stat_table(t_drivers, _parse_pct)
    else:
        result.warnings.append("Table 'Meilleurs drivers' introuvable (course PLAT/OBSTACLE ? -- vocabulaire jockeys à vérifier).")

    h_entraineurs = _find_heading(soup, "meilleurs entraîneurs", "meilleurs entraineurs")
    t_entraineurs = _next_table(h_entraineurs)
    if t_entraineurs is not None:
        result.entraineur_taux_top5_par_numero = _parse_stat_table(t_entraineurs, _parse_pct)
    else:
        result.warnings.append("Table 'Meilleurs entraîneurs' introuvable.")

    h_tandems = _find_heading(soup, "meilleurs tandems")
    t_tandems = _next_table(h_tandems)
    if t_tandems is not None:
        result.tandem_taux_top5_par_numero = _parse_stat_table(t_tandems, _parse_pct)
    else:
        result.warnings.append("Table 'Meilleurs tandems' introuvable.")

    # --- "Pronostic Quinté stats" (8e classement indépendant) ---
    h_stats = _find_heading(soup, "pronostic quinté stats")
    if h_stats is not None:
        p = h_stats.find_next("p")
        if p is not None:
            nums = [int(x) for x in re.findall(r"\b\d{1,2}\b", p.get_text(strip=True))]
            if nums:
                result.pronostic_stats_ordre = nums

    # --- Météo (texte libre, extraction par regex) ---
    h_meteo = _find_heading(soup, "météo du quinté", "météo")
    if h_meteo is not None:
        p = h_meteo.find_next("p")
        if p is not None:
            txt = p.get_text(" ", strip=True)
            m_temp = re.search(r"(\d+)\s*°C", txt)
            if m_temp:
                result.meteo_temp_c = float(m_temp.group(1))
            m_vent = re.search(r"rafales?[^.]{0,60}?(\d+)\s*km/h", txt, re.I)
            if not m_vent:
                m_vent = re.search(r"vent[^.]{0,60}?(\d+)\s*(?:à\s*\d+\s*)?km/h", txt, re.I)
            if m_vent:
                result.meteo_vent_kmh_max = float(m_vent.group(1))
            result.meteo_risque_pluie = bool(re.search(r"pluie|précipitation|averse", txt, re.I)) and not re.search(r"sans\s+(?:aucun\s+)?risque\s+de\s+précipitation", txt, re.I)
    else:
        result.warnings.append("Section météo introuvable.")

    if not any([result.classement_national_par_numero, result.poids_delta_kg_par_numero,
                result.gains_moyenne_par_numero, result.record_absolu_sec_par_numero,
                result.driver_taux_top5_par_numero, result.entraineur_taux_top5_par_numero,
                result.tandem_taux_top5_par_numero]):
        result.warnings.append("Aucune table statistique exploitée -- page probablement non conforme au patron attendu.")
    return result


def apply_enrichment(race, chevaux: list, press: Optional[PressConsensus],
                      extras: Optional[BaseTocardExtras]) -> List[str]:
    """Applique les données Frequence-Turf aux objets Cheval/RaceContext
    déjà construits par le scraper programme (Turfoo/CanalTurf), par
    matching sur `numero` (identique entre les sources -- numéro de
    corde/ligne du jour, pas d'ambiguïté de nom). Mute en place, renvoie
    les avertissements (ex. numéro non partant, page non conforme)."""
    from app.models import DriverStats

    warnings: List[str] = []
    by_numero = {c.numero: c for c in chevaux}

    if press is not None:
        warnings.extend(f"[presse] {w}" for w in press.warnings)
        for numero in by_numero:
            bk = press.to_bloc_k(numero)
            cheval = by_numero[numero]
            # Fusion (pas écrasement) avec ce que Turfoo/CanalTurf avaient
            # déjà posé dans citations_top5_par_source -- corrigé le
            # 03/09/2026. Turfoo et CanalTurf incrémentent icp_global de
            # leur côté (1 citation chacun, clés "Turfoo"/"Canalturf",
            # sans collision avec les noms de presse FT type "Genybet")
            # AVANT que cette fonction ne s'exécute ; écraser purement et
            # simplement perdait ces 2 citations réelles à chaque fois
            # qu'une page Frequence-Turf était disponible pour la course.
            # ICP_global = "nombre de sources citant le cheval Top5" (texte
            # source) n'exclut pas Turfoo/CanalTurf de la définition -- ce
            # sont des sources pronostiqueuses au même titre que la presse.
            citations_fusionnees = {**(cheval.citations_top5_par_source or {}), **bk["citations_top5_par_source"]}
            cheval.citations_top5_par_source = citations_fusionnees
            cheval.icp_global = sum(1 for cited in citations_fusionnees.values() if cited)
            cheval.favori_unanime = bk["favori_unanime"]
            if bk["icp_pondere"] is not None:
                cheval.icp_pondere = bk["icp_pondere"]

    if extras is not None:
        warnings.extend(f"[base-tocard] {w}" for w in extras.warnings)
        for numero, rang in extras.classement_national_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is None:
                warnings.append(f"Classement national : numéro {numero} absent des partants du jour (NP ?).")
                continue
            if cheval.driver_stats is None:
                cheval.driver_stats = DriverStats()
            cheval.driver_stats.classement_national = rang
        for numero, delta in extras.poids_delta_kg_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is None:
                continue
            if cheval.poids_actuel_kg is not None:
                cheval.poids_precedent_kg = round(cheval.poids_actuel_kg - delta, 2)
            # si poids_actuel_kg n'est pas encore collecté (PLAT non
            # vérifié à ce jour, cf. CARTOGRAPHIE_DONNEES.md Bloc I), on
            # ne peut pas dériver poids_precedent_kg -- pas d'invention.

        # --- 5 tables ajoutées le 02/09/2026 -- toutes en REPLI seulement
        # (n'écrasent jamais une valeur déjà collectée par une source plus
        # précise/complète : Turfoo/CanalTurf/Zone-Turf pour gains/record,
        # ou une association driver-cheval déjà connue pour le tandem).
        from app.models import TrainerStats, TandemStats
        for numero, gains_moy in extras.gains_moyenne_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is not None and cheval.gains_moyenne_carriere_eur is None:
                cheval.gains_moyenne_carriere_eur = gains_moy
        for numero, rec in extras.record_absolu_sec_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is not None and cheval.record_chrono_sec is None:
                cheval.record_chrono_sec = rec
        for numero, rec_p in extras.record_parcours_sec_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is not None and cheval.record_parcours_sec is None:
                cheval.record_parcours_sec = rec_p
        for numero, taux in extras.driver_taux_top5_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is None:
                continue
            if cheval.driver_stats is None:
                cheval.driver_stats = DriverStats()
            cheval.driver_stats.taux_top5_6m = taux
        for numero, taux in extras.entraineur_taux_top5_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is None:
                continue
            if cheval.trainer_stats is None:
                cheval.trainer_stats = TrainerStats()
            cheval.trainer_stats.taux_top5_6m = taux
        for numero, taux in extras.tandem_taux_top5_par_numero.items():
            cheval = by_numero.get(numero)
            if cheval is None:
                continue
            if cheval.tandem_driver_ecurie is None:
                cheval.tandem_driver_ecurie = TandemStats()
            cheval.tandem_driver_ecurie.taux_top5_6m = taux

        if race is not None:
            race.meteo_temp_c = extras.meteo_temp_c
            race.meteo_vent_kmh_max = extras.meteo_vent_kmh_max
            race.meteo_risque_pluie = extras.meteo_risque_pluie

        # 8e source ICP : Pronostic Quinté stats (v1.26 / FT base-tocard)
        if extras.pronostic_stats_ordre:
            top5_stats = set(extras.pronostic_stats_ordre[:5])
            for cheval in chevaux:
                citations = dict(cheval.citations_top5_par_source or {})
                citations["Frequence-Turf-stats"] = cheval.numero in top5_stats
                cheval.citations_top5_par_source = citations
                cheval.icp_global = sum(1 for cited in citations.values() if cited)

    if press is None and extras is None:
        warnings.append(
            "Aucune des 2 pages Frequence-Turf n'a pu être exploitée "
            "(course non-Quinté, pause du site, ou page introuvable)."
        )
    return warnings


def scrape_frequence_turf_enrichissement(d: date) -> Dict[str, object]:
    """Point d'entrée : renvoie les 2 objets pour une date donnée, avec
    les URLs utilisées. Ne lève pas d'exception si une page échoue
    (Frequence-Turf peut être en pause -- vérifié en pause estivale du
    19/07 au 17/08/2026 -- ou la course du jour n'est pas un Quinté).

    Aligné v1.26 : champ `status` (OK / PARTIAL / EMPTY / DISABLED).
    """
    if not frequence_turf_enabled():
        return {
            "status": "DISABLED",
            "urls": {},
            "presse": None,
            "base_tocard": None,
            "warnings": ["VANTAGE_FREQUENCE_TURF=0"],
        }
    urls = build_urls(d)
    all_u = _all_ft_urls_for_date(d)
    presse_urls = all_u["presse"]
    bt_urls = all_u["base_tocard"]

    out: Dict[str, object] = {
        "status": "EMPTY",
        "urls": urls,
        "urls_tentees": {"presse": presse_urls, "base_tocard": bt_urls},
        "presse": None,
        "base_tocard": None,
        "warnings": [],
        "note_jour_j": (
            "Fréquence-Turf : pages datées (passé/jour/futur si publiées). "
            "EMPTY hors Quinté ou page absente → repli stats-quinte / ticket sans boost ICP."
        ),
    }
    for u in presse_urls:
        try:
            html_presse = fetch_html(u)
            out["presse"] = parse_pronostics_presse(html_presse)
            out["urls"]["presse"] = u
            break
        except Exception as e:
            out["warnings"].append(f"presse {u} : {e}")
            logger.warning("FT presse %s : %s", u, e)
    for u in bt_urls:
        try:
            html_bt = fetch_html(u)
            out["base_tocard"] = parse_base_tocard(html_bt)
            out["urls"]["base_tocard"] = u
            break
        except Exception as e:
            out["warnings"].append(f"base_tocard {u} : {e}")
            logger.warning("FT base_tocard %s : %s", u, e)

    has_p = out["presse"] is not None
    has_b = out["base_tocard"] is not None
    if has_p and has_b:
        out["status"] = "OK"
    elif has_p or has_b:
        out["status"] = "PARTIAL"
    else:
        out["status"] = "EMPTY"
    return out


def enrichir_course_frequence_turf(race, chevaux: list) -> Dict[str, object]:
    """Hook unique v1.26 : scrape + apply sur RaceContext / List[Cheval].

    Fail-soft : ne lève jamais. Retourne un rapport pour json_output.
    """
    if not frequence_turf_enabled():
        return {"status": "DISABLED", "n_icp": 0, "nb_sources_presse": 0, "warnings": []}
    if not getattr(race, "date_course", None):
        return {"status": "SKIP", "reason": "date_course absente", "n_icp": 0, "warnings": []}
    try:
        d = date.fromisoformat(str(race.date_course)[:10])
    except ValueError:
        return {"status": "SKIP", "reason": f"date invalide: {race.date_course}", "n_icp": 0, "warnings": []}

    ft = scrape_frequence_turf_enrichissement(d)
    press = ft.get("presse")
    extras = ft.get("base_tocard")
    warnings = list(ft.get("warnings") or [])
    warnings.extend(apply_enrichment(race, chevaux, press, extras))
    n_icp = sum(1 for c in chevaux if c.icp_global is not None)
    nb_src = getattr(press, "nb_sources", 0) if press is not None else 0
    return {
        "status": ft.get("status"),
        "n_icp": n_icp,
        "nb_sources_presse": nb_src,
        "urls": ft.get("urls"),
        "urls_tentees": ft.get("urls_tentees"),
        "warnings": warnings,
        "note_jour_j": ft.get("note_jour_j"),
        "sans_boost_icp": ft.get("status") in ("EMPTY", "SKIP", "DISABLED") or n_icp == 0,
        "meteo": {
            "temp_c": getattr(race, "meteo_temp_c", None),
            "vent_kmh_max": getattr(race, "meteo_vent_kmh_max", None),
            "risque_pluie": getattr(race, "meteo_risque_pluie", None),
        },
    }
