"""
router.py -- Sélectionne le scraper approprié selon le domaine de l'URL.
Turfoo.fr est la source primaire recommandée (structure HTML vérifiée en
conditions réelles le 29/07/2026, voir turfoo.py). Geny.com est une des 4
sources principales de collecte (avec Turfoo, CanalTurf, Zone-Turf) : son
ancien format (/partants-pmu/...) et son nouveau format Next.js
(/course/{id}/partants-pronostics) sont tous deux acceptés -- voir geny.py
pour la stratégie table HTML puis repli sur le payload RSC embarqué.

CORRECTIF 19/09/2026 (Golden) : le nouveau format Geny était auparavant
rejeté en dur ici en le présumant "rendu en JavaScript, non exploitable en
scraping HTTP classique" (évaluation du 29/07/2026). Vérification en
conditions réelles le 19/09/2026 (fetch direct d'une page /course/{id}/...) :
c'est faux -- la page est bien rendue côté serveur (Next.js SSR), le HTML
brut contient déjà toutes les données (partants, arrivée, cotes) sans
exécution JS. L'hypothèse de juillet n'avait jamais été retestée depuis.
Le rejet en dur est retiré : on laisse scrape_geny_race() tenter (table
HTML, puis repli RSC JSON) et échouer proprement avec un message clair si
aucune des deux stratégies ne trouve de partants -- au lieu d'un refus
systématique qui empêchait même l'essai. Les autres domaines passent par
un parseur générique best-effort.
"""
from __future__ import annotations
from urllib.parse import urlparse
from typing import List, Tuple
import logging

from bs4 import BeautifulSoup

from app.models import RaceContext, Cheval
from app.scraping.base import fetch_html
from app.scraping.turfoo import scrape_turfoo_race
from app.scraping.canalturf import scrape_canalturf_race
from app.scraping.zoneturf import scrape_zoneturf_race
from app.scraping.base import validate_chevaux
from app.scraping.geny import scrape_geny_race, _find_partants_table, _parse_partants_table, \
    _extract_race_context, _parse_int, _parse_float, _parse_sexe_age
from app.scraping.hippodrome_normalize import hippodromes_match
from app.scraping.identity import (
    identite_incoherente, identite_depuis_urls, noms_concordent, parse_label_rc,
)

logger = logging.getLogger("vantage.scraping.router")

_JS_HEAVY_DOMAINS = {
    "turf.bzh", "www.turf.bzh", "pmu.fr", "www.pmu.fr",
    "letrot.com", "www.letrot.com",
}


def _generic_scrape(url: str) -> Tuple[RaceContext, List[Cheval], List[str]]:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    race = _extract_race_context(soup, url)
    table = _find_partants_table(soup)
    if table is None:
        raise ValueError(
            f"Impossible d'extraire un tableau de partants exploitable depuis {url}. "
            "Ce domaine n'est pas encore couvert par un parseur dédié -- utilise de "
            "préférence une URL geny.com (voir README, section Sources)."
        )
    rows = _parse_partants_table(table)
    chevaux = []
    warnings = []
    for i, row in enumerate(rows, start=1):
        numero = _parse_int(row.get("numero")) or i
        sexe, age = _parse_sexe_age(row.get("sexe_age"))
        chevaux.append(Cheval(
            numero=numero, nom=row.get("nom", f"Cheval{numero}").strip(), age=age, sexe=sexe,
            driver_jockey=row.get("driver"), entraineur=row.get("entraineur"),
            musique=row.get("musique"), valeur_pmu=_parse_float(row.get("valeur")),
            cote_matin=_parse_float(row.get("cote_matin")) or _parse_float(row.get("cote_avant_course")),
            cote_avant_course=_parse_float(row.get("cote_avant_course")),
        ))
    if len(chevaux) < 3:
        raise ValueError(f"Seulement {len(chevaux)} partant(s) extrait(s) depuis {url}.")
    validate_chevaux(chevaux, url)
    return race, chevaux, warnings


def scrape_race(url: str) -> Tuple[RaceContext, List[Cheval], List[str]]:
    domain = urlparse(url).netloc.lower()

    if domain in _JS_HEAVY_DOMAINS:
        raise ValueError(
            f"{domain} charge son contenu en JavaScript : un scraping HTTP classique ne "
            "peut pas le récupérer de façon fiable (vérifié le 29/07/2026 -- voir README, "
            "section Sources). Utilise une URL turfoo.fr pour cette course."
        )

    if "turfoo.fr" in domain:
        return scrape_turfoo_race(url)

    if "canalturf.com" in domain:
        return scrape_canalturf_race(url)

    if domain in ("zone-turf.fr", "www.zone-turf.fr"):
        return scrape_zoneturf_race(url)
    if domain in ("zoneturf-fr.com", "www.zoneturf-fr.com", "zone-turf-fr.com", "www.zone-turf-fr.com"):
        raise ValueError(
            f"{domain} est un site clone/miroir de zone-turf.fr, PAS le site réel (vérifié le "
            "03/08/2026) -- rejeté explicitement pour éviter toute donnée non fiable. "
            "Utilise https://www.zone-turf.fr/ (avec tiret, sans 'fr' après turf)."
        )

    if "geny.com" in domain:
        # Ancien format (/partants-pmu/...) et nouveau format Next.js
        # (/course/{id}/partants-pronostics, éventuellement avec slug
        # canonique /course/{id}-AAAA-MM-JJ-hippo-prix/...) passent tous
        # les deux par scrape_geny_race, qui tente une table HTML puis un
        # repli sur le payload RSC JSON embarqué (voir geny.py). Si aucune
        # des deux stratégies ne trouve de partants, scrape_geny_race lève
        # une ValueError explicite -- pas de refus préventif ici.
        return scrape_geny_race(url)

    logger.info("Domaine %s sans parseur dédié -- tentative générique.", domain)
    return _generic_scrape(url)


def _score_richesse(race: RaceContext, chevaux: List[Cheval]) -> int:
    """Score de richesse d'une source (nombre de champs non-vides utiles).
    Sert à choisir la meilleure base quand plusieurs sources réussissent."""
    score = 0
    if race.penetrometre is not None:
        score += 3
    if race.allocation_eur is not None:
        score += 2
    if race.distance_m:
        score += 1
    champs_cheval = (
        "cote_matin", "cote_avant_course", "musique", "gains_totaux_eur",
        "valeur_pmu", "poids_actuel_kg", "deferre", "driver_jockey",
        "entraineur", "fiche_url", "delai_j", "victoires_carriere",
        "numero_autostart", "ferrure_type",
    )
    for c in chevaux:
        for ch in champs_cheval:
            v = getattr(c, ch, None)
            if v is not None and v != "" and v != []:
                score += 1
    return score


def _discipline_family(value) -> str:
    s = str(getattr(value, "value", value) or "").upper()
    if "TROT" in s or "ATTEL" in s or "MONTE" in s:
        return "TROT"
    if "PLAT" in s or "GALOP" in s:
        return "PLAT"
    if "HAIE" in s or "STEEP" in s or "OBST" in s:
        return "OBSTACLE"
    return s


def _identity_mismatch(race: RaceContext, expected_hippodrome: str | None) -> str | None:
    """Compat v1.29.39 : contrôle hippodrome seul (voir identity.identite_incoherente)."""
    return identite_incoherente(race, {"hippodrome": expected_hippodrome} if expected_hippodrome else None)


def _discipline_exacte_pmu(attendu: dict, race: RaceContext):
    """Arbitre officiel de discipline (API PMU), best-effort. None si indisponible.
    Utilisé UNIQUEMENT pour départager des sources en désaccord."""
    try:
        from app.scraping.pmu_api import fetch_course_meta
        from app.models import Discipline
        r, c = attendu.get("reunion"), attendu.get("course")
        if r is None or c is None:
            r2, c2 = parse_label_rc(getattr(race, "reunion_course_label", None))
            r, c = r if r is not None else r2, c if c is not None else c2
        d = attendu.get("date") or getattr(race, "date_course", None)
        if r is None or c is None or not d:
            return None
        meta = fetch_course_meta(str(d)[:10], int(r), int(c)) or {}
        raw = str(meta.get("discipline") or meta.get("specialite") or "").upper()
        if "ATTEL" in raw:
            return Discipline.TROT_ATTELE
        if "MONT" in raw:
            return Discipline.TROT_MONTE
        if "STEEP" in raw or "CROSS" in raw:
            return Discipline.STEEPLE
        if "HAIE" in raw:
            return Discipline.HAIES
        if "PLAT" in raw:
            return Discipline.PLAT
    except Exception as e:  # noqa: BLE001
        logger.info("Arbitrage discipline PMU indisponible: %s", e)
    return None


def _composantes_accord(succes):
    """Regroupe les sources qui décrivent les MÊMES chevaux (noms concordants
    sur le même numéro, effectifs voisins). Retourne une liste de groupes d'indices."""
    n = len(succes)
    noms = [{c.numero: c.nom for c in item[2]} for item in succes]
    adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            ok, _ = noms_concordent(succes[i][2], noms[j])
            ok2, _ = noms_concordent(succes[j][2], noms[i])
            if ok and ok2 and abs(len(succes[i][2]) - len(succes[j][2])) <= 3:
                adj[i].add(j); adj[j].add(i)
    vus, groupes = set(), []
    for i in range(n):
        if i in vus:
            continue
        pile, comp = [i], set()
        while pile:
            k = pile.pop()
            if k in comp:
                continue
            comp.add(k); pile.extend(adj[k] - comp)
        vus |= comp
        groupes.append(sorted(comp))
    return groupes


def scrape_race_with_fallback(
    urls: List[str], expected_hippodrome: str | None = None,
    expected_identity: dict | None = None,
) -> Tuple[RaceContext, List[Cheval], List[str], str]:
    """Collecte multi-sources intégrale (4 sources principales).

    1. TOUTES les URLs sont tentées. 2. Chaque page est confrontée à l'identité
    attendue (date, hippodrome, réunion, course) -- v1.29.40 : déduite aussi des
    URLs, donc active sur /retry et en mode réunion+course. 3. Les sources qui
    ne décrivent pas les mêmes chevaux (noms) sont écartées. 4. Désaccord de
    discipline : consensus, sinon arbitre officiel PMU, sinon base conservée.
    5. La plus riche sert de base, les autres comblent les champs vides.
    """
    errors: List[str] = []
    warnings: List[str] = []
    succes: List[Tuple[str, RaceContext, List[Cheval], List[str], int]] = []

    urls_propres = [u.strip() for u in urls if u and u.strip()]
    if not urls_propres:
        raise ValueError("Aucune URL fournie pour la collecte.")

    attendu = dict(identite_depuis_urls(urls_propres))
    for k, v in (expected_identity or {}).items():
        if v not in (None, ""):
            attendu[k] = v
    if expected_hippodrome:
        attendu["hippodrome"] = expected_hippodrome

    for url in urls_propres:
        try:
            race, chevaux, w = scrape_race(url)
            mismatch = identite_incoherente(race, attendu)
            if mismatch:
                raise ValueError(f"IDENTITE_SOURCE_REJETEE: {mismatch}")
            richesse = _score_richesse(race, chevaux)
            succes.append((url, race, chevaux, w, richesse))
            logger.info("Source OK %s — %d chevaux, richesse=%d", url, len(chevaux), richesse)
        except Exception as e:
            logger.warning("Échec source %s : %s", url, e)
            errors.append(f"{url} -> {e}")
            warnings.append(f"Source échouée : {url} ({e})")

    if not succes:
        raise ValueError(
            "Aucune des sources fournies n'a pu être exploitée :\n"
            + "\n".join(f"- {e}" for e in errors)
        )

    # --- Concordance des chevaux (noms) : même course ? ---
    if len(succes) >= 2:
        groupes = _composantes_accord(succes)
        if len(groupes) > 1:
            def _score_groupe(g):
                exact = 0
                for i in g:
                    r_, c_ = parse_label_rc(succes[i][1].reunion_course_label)
                    if attendu.get("reunion") is not None and r_ == int(attendu["reunion"]) \
                            and attendu.get("course") is not None and c_ == int(attendu["course"]):
                        exact += 1
                return (len(g), exact, sum(succes[i][4] for i in g))
            retenu = set(max(groupes, key=_score_groupe))
            for i, item in enumerate(succes):
                if i not in retenu:
                    msg = f"{item[0]} -> IDENTITE_SOURCE_REJETEE: noms de partants différents du groupe majoritaire"
                    errors.append(msg); warnings.append("Source rejetée: " + msg)
            succes = [item for i, item in enumerate(succes) if i in retenu]

    # --- Discipline : consensus, sinon arbitre officiel, sinon base conservée ---
    from collections import Counter
    from app.models import Discipline
    succes.sort(key=lambda x: x[4], reverse=True)
    familles = Counter(_discipline_family(item[1].discipline) for item in succes)
    if len(familles) > 1:
        fam_maj, nb_maj = familles.most_common(1)[0]
        official = None
        if not (nb_maj >= 2 and nb_maj > sum(familles.values()) - nb_maj):
            official = _discipline_exacte_pmu(attendu, succes[0][1])
            if official is not None:
                fam_maj = _discipline_family(official)
                warnings.append(f"Discipline arbitrée par l'API PMU : {official.value}")
            else:
                fam_maj = _discipline_family(succes[0][1].discipline)
                warnings.append(
                    "DISCIPLINE_CONFLIT_NON_ARBITRE: sources en désaccord "
                    f"({dict(familles)}), discipline de la source la plus riche conservée ({fam_maj})."
                )
        for url_bad, race_bad, _, _, _ in [i for i in succes if _discipline_family(i[1].discipline) != fam_maj]:
            warnings.append(f"Source écartée: discipline incohérente ({url_bad} -> {race_bad.discipline}, retenue={fam_maj})")
            errors.append(f"{url_bad} -> discipline incohérente: {race_bad.discipline}")
        succes = [i for i in succes if _discipline_family(i[1].discipline) == fam_maj]
        if official is not None and succes:
            succes[0][1].discipline = official
    if not succes:
        raise ValueError("Toutes les sources ont été rejetées pour incohérence d'identité.")

    succes.sort(key=lambda x: x[4], reverse=True)
    url_primaire, race, chevaux, w_prim, score_prim = succes[0]
    warnings = list(w_prim) + warnings
    warnings.append(
        f"Source primaire retenue : {url_primaire} "
        f"(richesse={score_prim}, {len(succes)}/{len(urls_propres)} sources OK)"
    )

    total_combles = 0
    for url, race_supp, chevaux_supp, _, score_supp in succes[1:]:
        nb = _fusionner_champs_manquants(chevaux, chevaux_supp)
        for attr in (
            "date_course", "distance_m", "hippodrome",
            "penetrometre", "allocation_eur", "terrain_qualificatif",
            "type_course", "depart", "nom_course",
        ):
            cur = getattr(race, attr, None)
            alt = getattr(race_supp, attr, None)
            if cur in (None, "", 0) and alt not in (None, "", 0):
                setattr(race, attr, alt)
                nb += 1
        # Label R/C : une source qui connaît la réunion complète une étiquette « C4 » seule
        lab = getattr(race, "reunion_course_label", None) or ""
        lab2 = getattr(race_supp, "reunion_course_label", None) or ""
        r1, _c1 = parse_label_rc(lab)
        r2, _c2 = parse_label_rc(lab2)
        if lab2 and (not lab or (r1 is None and r2 is not None)):
            race.reunion_course_label = lab2
            nb += 1
        elif r1 is not None and r2 is not None and r1 != r2:
            warnings.append(f"R_CONFLIT: {url} annonce R{r2}, base R{r1} (base conservée, identité attendue prioritaire)")
        total_combles += nb
        warnings.append(
            f"Fusion depuis {url} (richesse={score_supp}) : {nb} champ(s) comblé(s)" if nb
            else f"Source {url} exploitée (richesse={score_supp}) mais rien de nouveau à combler"
        )

    # Identité attendue = autorité pour R/C et date
    if attendu.get("reunion") is not None and attendu.get("course") is not None:
        etiquette = f"R{int(attendu['reunion'])}C{int(attendu['course'])}"
        if race.reunion_course_label != etiquette:
            if race.reunion_course_label:
                warnings.append(f"R/C fixés par l'identité attendue : {etiquette} (source: {race.reunion_course_label})")
            race.reunion_course_label = etiquette
    if not race.date_course and attendu.get("date"):
        race.date_course = str(attendu["date"])[:10]

    if len(succes) > 1:
        warnings.append(
            f"Collecte multi-sources : {len(succes)} sources fusionnées, "
            f"{total_combles} champ(s) comblé(s) au total"
        )
    if errors:
        warnings.append(f"{len(errors)} source(s) en échec sur {len(urls_propres)}")
    return race, chevaux, warnings, url_primaire


def _cote_saine(c) -> bool:
    return c is not None and 1.01 <= float(c) < 500.0


def _fusionner_champs_manquants(primaire: List[Cheval], supplementaire: List[Cheval]) -> int:
    """Comble les champs None de `primaire` avec les valeurs correspondantes
    de `supplementaire` (apparié par numéro), sans jamais écraser une
    valeur déjà présente (sauf cote absurde). Retourne le nombre de champs comblés."""
    by_numero = {c.numero: c for c in supplementaire}
    combles = 0
    champs = [
        "valeur_pmu", "poids_actuel_kg", "poids_precedent_kg", "age", "sexe",
        "gains_totaux_eur", "gains_moyenne_carriere_eur", "nb_courses",
        "record_chrono_sec", "ferrure_type", "ferrure_changes",
        "deferre", "recul_m", "numero_autostart", "cotes_timeline", "cotes_bookmakers",
        "musique", "fiche_url", "delai_j", "victoires_carriere", "places_carriere",
        "driver_jockey", "entraineur", "proprietaire",
        "driver_fiche_url", "entraineur_fiche_url",
        "historique_terrain", "historique_distance", "historique_hippodrome",
        "historique_recent", "driver_stats", "trainer_stats",
        "tandem_driver_cheval", "commentaire_derniere_course",
        "rk_derniere_sec", "record_parcours_sec",
    ]
    for c in primaire:
        autre = by_numero.get(c.numero)
        if not autre:
            continue
        for champ in champs:
            if getattr(c, champ, None) in (None, "", []) and getattr(autre, champ, None) not in (None, "", []):
                setattr(c, champ, getattr(autre, champ))
                combles += 1
        # Cotes : combler si absentes OU absurdes côté primaire
        for ck in ("cote_matin", "cote_avant_course"):
            cv, av = getattr(c, ck, None), getattr(autre, ck, None)
            if _cote_saine(av) and not _cote_saine(cv):
                setattr(c, ck, av)
                combles += 1
    return combles
