"""
enrichment.py -- Enrichit chaque Cheval avec les données de sa fiche
individuelle Turfoo.fr (app/scraping/turfoo_fiche_cheval.py) : delai_j
(Module B / IFF), historique_terrain et historique_distance (Modules J/K),
nb_courses. Enrichit aussi driver_stats/trainer_stats depuis les fiches
jockey/entraîneur (app/scraping/turfoo_fiche_personne.py) pour les
Modules D/E (BSH/BSC) -- voir avertissement de fiabilité dans ce dernier
fichier (structure non vérifiée en conditions réelles, contrairement aux
fiches chevaux).

Résilient par construction : une fiche introuvable ou mal parsée pour un
cheval n'interrompt jamais le pipeline -- ce cheval reste simplement sans
enrichissement (flag ajouté), le reste de la course continue normalement.
Ajoute jusqu'à 3N requêtes HTTP par course (cheval + jockey + entraîneur,
N = nombre de partants) -- désactivable via le paramètre `enabled`.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from app.models import Cheval, RaceContext, PerfHistorique, DriverStats, TrainerStats, DriverTrainerWindow, CatalogSignal, TandemStats
from app.scraping.turfoo_fiche_cheval import fetch_fiche_cheval, compute_delai_j
from app.scraping.turfoo_fiche_personne import fetch_historique_personne, fenetres_victoires
from app.scraping.canalturf_fiche_cheval import fetch_canalturf_fiche_cheval
from app.scraping.canalturf_fiche_personne import fetch_canalturf_fiche_personne
from app.scraping.zoneturf_fiche_cheval import fetch_zoneturf_fiche_cheval
from app.scraping.zoneturf_fiche_personne import fetch_zoneturf_fiche_personne
from app.scraping.geny_fiche_cheval import fetch_geny_fiche_cheval, chrono_to_seconds
from app.scraping.identity import asof_attr, filtrer_avant, est_rejeu
from app.engine.historique_signals import compute_historique_signals
from app.engine.tranches import classify_tranche


def _hist_rang(h):
    """Compat ZoneTurfPerf.rang / Turfoo.notre_rang / Geny."""
    for attr in ("notre_rang", "rang", "place", "position"):
        v = getattr(h, attr, None)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def _hist_penetrometre(h):
    """Terrain label → approx pénétromètre, ou valeur numérique déjà présente."""
    for attr in ("penetrometre_approx", "penetrometre", "valeur_penetrometre"):
        v = getattr(h, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    terr = getattr(h, "terrain", None) or getattr(h, "etat_terrain", None)
    if not terr:
        return None
    s = str(terr).upper().replace("É", "E").replace("È", "E")
    s = re.sub(r"\s+", " ", s).strip()
    # Labels ZT: TR SOUPLE, SOUPLE, LOURD, COLLANT, BON, PSF...
    if "PSF" in s or "SYNTH" in s:
        return 2.8
    if "TRES LOURD" in s or "TR LOURD" in s:
        return 4.9
    if "LOURD" in s:
        return 4.5
    if "COLLANT" in s or "PROFOND" in s:
        return 4.2
    if "TRES SOUPLE" in s or "TR SOUPLE" in s:
        return 3.9
    if "SOUPLE" in s:
        return 3.5
    if "BON SOUPLE" in s:
        return 3.3
    if "BON" in s or "LEGGER" in s or "LEGER" in s:
        return 3.0
    return None


logger = logging.getLogger("vantage.scraping.enrichment")

_FENETRES_JOURS = [7, 14, 15, 28, 30, 45, 60]


def enrich_cheval(
    cheval: Cheval,
    race: RaceContext,
    *,
    skip_personne_fiches: bool = False,
) -> List[str]:
    """Modifie `cheval` en place. Retourne la liste des flags générés.

    skip_personne_fiches (v1.29.25) : si True, ne refetch pas jockey/entraîneur
    (évite le double fetch quand Geny + source d'origine appellent enrich_cheval
    deux fois — driver_fiche_url inchangé entre les deux passes).
    """
    flags = []
    if est_rejeu(race.date_course):
        flags.append("BACKTEST_CUMULS_FICHE_NON_FIGES")  # courses/victoires/gains cumulés de la fiche = état actuel
    if not cheval.fiche_url:
        flags.append("FICHE_URL_ABSENTE")
    elif "canalturf.com" in cheval.fiche_url:
        # CanalTurf : fiche plus simple mais donne les GAINS (absents de Turfoo)
        try:
            fiche_ct = fetch_canalturf_fiche_cheval(cheval.fiche_url)
            asof_attr(fiche_ct, "dernieres_perfs", race.date_course)  # v1.29.40 : anti fuite temporelle
            if cheval.gains_totaux_eur is None:
                cheval.gains_totaux_eur = fiche_ct.gains_totaux_eur
            if cheval.nb_courses is None:
                cheval.nb_courses = fiche_ct.nb_courses
            # nb_victoires/nb_places étaient scrapés mais jamais lus --
            # débloqué le 03/09/2026, même lacune que Turfoo découverte
            # la veille (victoires_carriere/places_carriere).
            if cheval.victoires_carriere is None and fiche_ct.nb_victoires is not None:
                cheval.victoires_carriere = fiche_ct.nb_victoires
            if cheval.places_carriere is None and fiche_ct.nb_places is not None:
                cheval.places_carriere = fiche_ct.nb_places
            # proprietaire : scrapé par fetch_canalturf_fiche_cheval mais
            # jamais recopié sur Cheval -- même classe de lacune que
            # nb_victoires/nb_places, débloqué le 19/09/2026 (Golden).
            if getattr(fiche_ct, "proprietaire", None) and not cheval.proprietaire:
                cheval.proprietaire = fiche_ct.proprietaire
            if cheval.gains_moyenne_carriere_eur is None and cheval.gains_totaux_eur and cheval.nb_courses:
                cheval.gains_moyenne_carriere_eur = cheval.gains_totaux_eur / max(1, cheval.nb_courses)
            if getattr(fiche_ct, "musique", None) and not cheval.musique:
                cheval.musique = fiche_ct.musique
            if fiche_ct.dernieres_perfs and race.date_course:
                perfs_triees = sorted(fiche_ct.dernieres_perfs, key=lambda p: p.date, reverse=True)
                dates = [p.date for p in perfs_triees]
                try:
                    d_course = datetime.fromisoformat(race.date_course).date()
                    d_derniere = datetime.fromisoformat(dates[0]).date()
                    cheval.delai_j = (d_course - d_derniere).days
                except ValueError:
                    pass
                if cheval.driver_precedent is None and perfs_triees[0].jockey:
                    cheval.driver_precedent = perfs_triees[0].jockey
                if cheval.historique_recent is None:
                    cheval.historique_recent = [PerfHistorique(valeur=0.0, rang=p.rang, date=p.date)
                                                 for p in fiche_ct.dernieres_perfs]
                # historique_hippodrome et tandem_driver_cheval : jockey/
                # hippodrome par performance passée étaient déjà extraits
                # (CanalturfPerf.jockey/.hippodrome), jamais exploités --
                # débloqué le 03/09/2026. Portée limitée aux quelques
                # "dernières performances" affichées par CanalTurf (pas
                # la carrière complète comme Turfoo.historique) : sous-
                # estime probablement les vraies statistiques, jamais
                # sur-estime -- documenté par un flag dédié plutôt que
                # présenté comme un décompte exhaustif.
                if cheval.historique_hippodrome is None and race.hippodrome:
                    hippo_norm = race.hippodrome.strip().upper()
                    matches = [PerfHistorique(valeur=0.0, rang=p.rang, date=p.date)
                               for p in fiche_ct.dernieres_perfs if p.hippodrome.strip().upper() == hippo_norm]
                    if matches:
                        cheval.historique_hippodrome = matches
                if cheval.tandem_driver_cheval is None and cheval.driver_jockey:
                    driver_norm = cheval.driver_jockey.strip().upper()
                    perfs_tandem = [p for p in fiche_ct.dernieres_perfs if p.jockey.strip().upper() == driver_norm]
                    if perfs_tandem:
                        cheval.tandem_driver_cheval = TandemStats(
                            courses_ensemble=len(perfs_tandem),
                            victoires_ensemble=sum(1 for p in perfs_tandem if p.rang == 1),
                            places_top5_ensemble=sum(1 for p in perfs_tandem if p.rang <= 5))
                        flags.append("TANDEM_DRIVER_CHEVAL_PARTIEL_CANALTURF")
            flags.append("ENRICHI_FICHE_CANALTURF")
        except Exception as e:
            logger.warning("Échec enrichissement fiche CanalTurf pour #%s %s : %s", cheval.numero, cheval.nom, e)
            flags.append(f"FICHE_ENRICHISSEMENT_ECHEC(CanalTurf): {e}")
    elif "zone-turf.fr" in cheval.fiche_url:
        try:
            fiche_zt = fetch_zoneturf_fiche_cheval(cheval.fiche_url, cheval.nom)
            asof_attr(fiche_zt, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
            if fiche_zt.nb_courses is not None and cheval.nb_courses is None:
                cheval.nb_courses = fiche_zt.nb_courses
            if fiche_zt.nb_victoires is not None and cheval.victoires_carriere is None:
                cheval.victoires_carriere = fiche_zt.nb_victoires
            if getattr(fiche_zt, "nb_places", None) is not None and cheval.places_carriere is None:
                cheval.places_carriere = fiche_zt.nb_places
            if getattr(fiche_zt, "gains_totaux_eur", None) is not None and cheval.gains_totaux_eur is None:
                cheval.gains_totaux_eur = fiche_zt.gains_totaux_eur
            if getattr(fiche_zt, "valeur_handicap", None) is not None and cheval.valeur_pmu is None:
                cheval.valeur_pmu = fiche_zt.valeur_handicap
            if cheval.gains_moyenne_carriere_eur is None and cheval.gains_totaux_eur and cheval.nb_courses:
                cheval.gains_moyenne_carriere_eur = cheval.gains_totaux_eur / max(1, cheval.nb_courses)
            if fiche_zt.historique and race.date_course:
                perfs = fiche_zt.historique
                try:
                    d_course = datetime.fromisoformat(race.date_course).date()
                    d_derniere = datetime.fromisoformat(perfs[0].date).date()
                    cheval.delai_j = (d_course - d_derniere).days
                except ValueError:
                    pass
                if cheval.historique_recent is None:
                    cheval.historique_recent = [
                        PerfHistorique(valeur=0.0, rang=p.rang, date=p.date,
                                       discipline=p.discipline)
                        for p in perfs if p.rang is not None
                    ]
                cheval.historique_distance = [
                    PerfHistorique(valeur=float(p.distance_m or 0), rang=p.rang, date=p.date,
                                   discipline=p.discipline)
                    for p in perfs if p.rang is not None and p.distance_m
                ]
                # Poids de la dernière sortie (plat) si dispo sur fiche ZT
                if cheval.poids_precedent_kg is None:
                    for p in perfs:
                        pk = getattr(p, "poids_kg", None)
                        if pk is not None and 45.0 <= float(pk) <= 78.0:
                            cheval.poids_precedent_kg = float(pk)
                            break
                # terrain approx stocké dans valeur si pas de pénétromètre numérique
                # Pas d'historique_terrain factice (valeur=0.0) : pénalisait IFT
                # et modules SSFO sans signal réel de pénétromètre.
                # Les labels terrain ZT restent exploitables via discipline/distance.
                if cheval.historique_terrain is None:
                    cheval.historique_terrain = []
                if race.hippodrome:
                    hippo_norm = race.hippodrome.strip().upper()
                    cheval.historique_hippodrome = [
                        PerfHistorique(valeur=float(p.distance_m or 0), rang=p.rang, date=p.date,
                                       discipline=p.discipline)
                        for p in perfs
                        if p.hippodrome and p.hippodrome.strip().upper() == hippo_norm and p.rang is not None
                    ]
                if cheval.driver_jockey and cheval.tandem_driver_cheval is None:
                    dn = cheval.driver_jockey.strip().upper()
                    perfs_t = [p for p in perfs if p.jockey and p.jockey.strip().upper() == dn]
                    if perfs_t:
                        cheval.tandem_driver_cheval = TandemStats(
                            courses_ensemble=len(perfs_t),
                            victoires_ensemble=sum(1 for p in perfs_t if p.rang == 1),
                            places_top5_ensemble=sum(1 for p in perfs_t if p.rang is not None and p.rang <= 5),
                        )
                        flags.append("TANDEM_DRIVER_CHEVAL_ZONETURF")
                # Pas de proxy IRP/pente inventé : les modules J/K/historique
                # consomment historique_* directement. IRP/pente restent à
                # compute_historique_signals quand le format Turfoo est dispo.
                flags.append("ENRICHI_FICHE_ZONETURF")
            else:
                flags.append("FICHE_ZONETURF_HISTORIQUE_VIDE")
        except Exception as e:
            logger.warning("Échec enrichissement fiche Zone-Turf pour #%s %s : %s", cheval.numero, cheval.nom, e)
            flags.append(f"FICHE_ENRICHISSEMENT_ECHEC(ZoneTurf): {e}")
    elif "geny.com" in cheval.fiche_url:
        try:
            fiche_gn = fetch_geny_fiche_cheval(cheval.fiche_url, cheval.nom)
            asof_attr(fiche_gn, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
            if fiche_gn.nb_courses is not None and cheval.nb_courses is None:
                cheval.nb_courses = fiche_gn.nb_courses
            if fiche_gn.victoires_carriere is not None and cheval.victoires_carriere is None:
                cheval.victoires_carriere = fiche_gn.victoires_carriere
            # places_carriere = victoires + places 2e/3e (hypothèse de
            # convention, à confirmer -- voir docstring geny_fiche_cheval.py).
            if cheval.places_carriere is None and fiche_gn.places_2e_3e is not None:
                cheval.places_carriere = (fiche_gn.victoires_carriere or 0) + fiche_gn.places_2e_3e
            if fiche_gn.gains_carriere_eur is not None and cheval.gains_totaux_eur is None:
                cheval.gains_totaux_eur = fiche_gn.gains_carriere_eur
            if cheval.gains_moyenne_carriere_eur is None and cheval.gains_totaux_eur and cheval.nb_courses:
                cheval.gains_moyenne_carriere_eur = cheval.gains_totaux_eur / max(1, cheval.nb_courses)
            if fiche_gn.musique and not cheval.musique:
                cheval.musique = fiche_gn.musique
            if fiche_gn.entraineur and not cheval.entraineur:
                cheval.entraineur = fiche_gn.entraineur
            if fiche_gn.proprietaire and not cheval.proprietaire:
                cheval.proprietaire = fiche_gn.proprietaire
            # delai_j : Geny l'affiche directement ("Dernière course : N
            # jours"), pas besoin de le recalculer depuis l'historique
            # comme pour Turfoo/Zone-Turf.
            if fiche_gn.delai_j_affiche is not None and cheval.delai_j is None:
                cheval.delai_j = fiche_gn.delai_j_affiche
            if cheval.record_chrono_sec is None:
                # Priorité : record dans LA discipline courue aujourd'hui >
                # record absolu (toutes disciplines) > record sur la
                # distance précise (moins pertinent si le cheval change
                # souvent de distance). Golden a confirmé (capture d'écran
                # 20/09/2026) que Geny scinde bien les records par
                # discipline (filtre "Monté & Attelé" / "Attelé" observé) --
                # un ancien code ne gardait qu'une seule discipline au hasard.
                _DISC_MAP = {"TROT_ATTELE": "Attelé", "TROT_MONTE": "Monté",
                             "PLAT": "Plat", "HAIES": "Haies", "STEEPLE": "Steeple"}
                label_du_jour = _DISC_MAP.get(race.discipline)
                chrono_pertinent = (
                    fiche_gn.records_par_discipline.get(label_du_jour) if label_du_jour else None
                ) or fiche_gn.record_absolu or fiche_gn.record_distance
                cheval.record_chrono_sec = chrono_to_seconds(chrono_pertinent)
            if cheval.record_parcours_sec is None:
                cheval.record_parcours_sec = chrono_to_seconds(fiche_gn.record_parcours)

            if fiche_gn.historique:
                perfs = fiche_gn.historique
                if cheval.historique_recent is None:
                    cheval.historique_recent = [
                        PerfHistorique(valeur=0.0, rang=p.rang, date=p.date, discipline=p.discipline)
                        for p in perfs if p.rang is not None and p.date
                    ]
                cheval.historique_distance = [
                    PerfHistorique(valeur=float(p.distance_m or 0), rang=p.rang, date=p.date,
                                    discipline=p.discipline)
                    for p in perfs if p.rang is not None and p.distance_m and p.date
                ]
                if race.hippodrome:
                    hippo_norm = race.hippodrome.strip().upper()
                    cheval.historique_hippodrome = [
                        PerfHistorique(valeur=float(p.distance_m or 0), rang=p.rang, date=p.date,
                                        discipline=p.discipline)
                        for p in perfs
                        if p.hippodrome and p.hippodrome.strip().upper() == hippo_norm and p.rang is not None and p.date
                    ]
                # Pas d'historique_terrain : Dur/Herbe (surface Geny) n'est
                # pas un pénétromètre -- même prudence que pour Zone-Turf,
                # pour ne pas fausser IFT/SSFO avec un proxy non comparable.
                if cheval.historique_terrain is None:
                    cheval.historique_terrain = []
                if cheval.driver_jockey and cheval.tandem_driver_cheval is None:
                    dn = cheval.driver_jockey.strip().upper()
                    perfs_t = [p for p in perfs if p.driver and p.driver.strip().upper() == dn]
                    if perfs_t:
                        cheval.tandem_driver_cheval = TandemStats(
                            courses_ensemble=len(perfs_t),
                            victoires_ensemble=sum(1 for p in perfs_t if p.rang == 1),
                            places_top5_ensemble=sum(1 for p in perfs_t if p.rang is not None and p.rang <= 5),
                        )
                        flags.append("TANDEM_DRIVER_CHEVAL_GENY")
                flags.append("ENRICHI_FICHE_GENY")
            else:
                flags.append("FICHE_GENY_HISTORIQUE_VIDE")
        except Exception as e:
            logger.warning("Échec enrichissement fiche Geny pour #%s %s : %s", cheval.numero, cheval.nom, e)
            flags.append(f"FICHE_ENRICHISSEMENT_ECHEC(Geny): {e}")
    else:
        try:
            fiche = fetch_fiche_cheval(cheval.fiche_url, cheval.nom)
            asof_attr(fiche, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
        except Exception as e:
            logger.warning("Échec enrichissement fiche cheval pour #%s %s : %s", cheval.numero, cheval.nom, e)
            fiche = None
            flags.append(f"FICHE_ENRICHISSEMENT_ECHEC(Turfoo/générique): {e}")

        if fiche:
            if cheval.age is None and fiche.age is not None:
                cheval.age = fiche.age
            if cheval.sexe is None and fiche.sexe is not None:
                cheval.sexe = fiche.sexe
            if cheval.nb_courses is None and fiche.courses_carriere is not None:
                cheval.nb_courses = fiche.courses_carriere
            if cheval.victoires_carriere is None and fiche.victoires_carriere is not None:
                cheval.victoires_carriere = fiche.victoires_carriere
            if cheval.places_carriere is None and fiche.places_carriere is not None:
                cheval.places_carriere = fiche.places_carriere
            # proprietaire : scrapé par fetch_fiche_cheval (Turfoo) mais
            # jamais recopié sur Cheval -- débloqué le 19/09/2026 (Golden),
            # même correctif que côté CanalTurf ci-dessus.
            if cheval.proprietaire is None and getattr(fiche, "proprietaire", None):
                cheval.proprietaire = fiche.proprietaire

            if fiche.historique and race.date_course:
                delai = compute_delai_j(fiche.historique, race.date_course)
                if delai is not None:
                    cheval.delai_j = delai
                else:
                    flags.append("DELAI_J_NON_CALCULABLE")

                cheval.historique_terrain = [
                    PerfHistorique(
                        valeur=_hist_penetrometre(h), rang=_hist_rang(h), date=h.date,
                        discipline=getattr(h, "discipline", None),
                    )
                    for h in fiche.historique if _hist_penetrometre(h) is not None and _hist_rang(h) is not None
                ]
                if cheval.historique_recent is None:
                    cheval.historique_recent = [
                        PerfHistorique(valeur=0.0, rang=_hist_rang(h), date=h.date)
                        for h in fiche.historique if _hist_rang(h) is not None and h.date
                    ]
                cheval.historique_distance = [
                    PerfHistorique(
                        valeur=h.distance_m, rang=_hist_rang(h), date=h.date,
                        discipline=getattr(h, "discipline", None),
                    )
                    for h in fiche.historique if h.distance_m is not None and _hist_rang(h) is not None
                ]
                if race.hippodrome:
                    hippo_norm = race.hippodrome.strip().upper()
                    cheval.historique_hippodrome = [
                        PerfHistorique(valeur=h.distance_m or 0.0, rang=_hist_rang(h), date=h.date)
                        for h in fiche.historique
                        if h.hippodrome and h.hippodrome.strip().upper() == hippo_norm and _hist_rang(h) is not None
                    ]
                hist_signaux, hist_valeurs_brutes = compute_historique_signals(
                    fiche.historique, race.hippodrome, race.distance_m, race.penetrometre, race.date_course,
                    tranche=classify_tranche(cheval.cote_matin).value if classify_tranche(cheval.cote_matin) else None)
                cheval.signaux_precalcules = hist_signaux
                # v1.29.36 — delai_j depuis historique fiche si manquant
                if cheval.delai_j is None and fiche.historique:
                    try:
                        from datetime import date as _date
                        race_d = race.date_course
                        if hasattr(race_d, "year"):
                            rd = race_d
                        else:
                            rd = _date.fromisoformat(str(race_d)[:10])
                        dates = []
                        for h in fiche.historique:
                            d = getattr(h, "date", None)
                            if not d:
                                continue
                            try:
                                hd = d if hasattr(d, "year") else _date.fromisoformat(str(d)[:10])
                                if hd < rd:
                                    dates.append((rd - hd).days)
                            except Exception:
                                pass
                        if dates:
                            cheval.delai_j = min(dates)
                    except Exception:
                        pass

                # Exposés en champs numériques propres depuis le 02/09/2026
                # (cf. historique_signals.py docstring) pour p5p6.py/ssfo.py.
                cheval.irp_score = hist_valeurs_brutes.get("irp_final")
                cheval.pente_score = hist_valeurs_brutes.get("pente_brut")
                flags.append("ENRICHI_FICHE_CHEVAL")
            else:
                flags.append("FICHE_CHEVAL_HISTORIQUE_VIDE")
                # A3 — repli musique / hippo si historique fiche vide
                try:
                    from app.scraping.musique import parse_musique, rangs_recents
                    perfs = parse_musique(cheval.musique or "")
                    rangs = [p.rang for p in perfs[:8] if getattr(p, "rang", None)]
                    if rangs:
                        tops = sum(1 for r in rangs if r <= 5)
                        if tops >= 3:
                            cheval.signaux_precalcules = list(getattr(cheval, "signaux_precalcules", None) or []) + [
                                CatalogSignal(id="B04_REPLI", valeur_brute=2.5, catalog="B",
                                              confiance="MINIMAL",
                                              justification="repli musique: forme récente (historique fiche vide)")
                            ]
                            flags.append("HISTORIQUE_REPLI_MUSIQUE")
                        # pente approximative
                        if len(rangs) >= 4:
                            early = sum(rangs[:2]) / 2.0
                            late = sum(rangs[-2:]) / 2.0
                            if late + 1.5 < early:  # amélioration (rangs baissent)
                                cheval.pente_score = 0.12
                                flags.append("PENTE_REPLI_MUSIQUE")
                except Exception:
                    flags.append("HISTORIQUE_REPLI_ECHEC")

    # --- Jockey/driver ---
    hist_j_raw = None  # capturé pour B09 (tandem), cf. plus bas -- ajouté le 09/08/2026
    hist_e_raw = None
    if skip_personne_fiches:
        flags.append("PERSONNE_FICHES_SKIP_DEJA_TENTE")
    elif not race.date_course:
        flags.append("STATS_PERSONNE_SANS_DATE_REFERENCE")
    else:
        if cheval.driver_fiche_url and cheval.driver_jockey and "turfoo.fr" in cheval.driver_fiche_url:
            try:
                hist_j = fetch_historique_personne(cheval.driver_fiche_url, "jockeys", cheval.driver_jockey)
                hist_j = filtrer_avant(hist_j, race.date_course)  # v1.29.40 : anti fuite temporelle
                hist_j_raw = hist_j
                fenetres = fenetres_victoires(hist_j, race.date_course, _FENETRES_JOURS)
                if fenetres:
                    cheval.driver_stats = DriverStats(
                        fenetres=[DriverTrainerWindow(**f) for f in fenetres])
                    flags.append("ENRICHI_FICHE_JOCKEY")
                else:
                    flags.append("FICHE_JOCKEY_HISTORIQUE_VIDE")
                # tandem_driver_cheval réel (historique complet, pas
                # limité aux "dernières perfs" comme CanalTurf) --
                # débloqué le 03/09/2026 via la colonne "Cheval" de la
                # fiche jockey Turfoo (cf. turfoo_fiche_personne.py).
                # Priorité sur un éventuel tandem déjà posé par CanalTurf
                # (plus complet ici) -- pas un simple repli.
                nom_norm = re.sub(r"\s+", " ", cheval.nom.strip().upper())
                perfs_tandem = [h for h in hist_j if h.cheval and re.sub(r"\s+", " ", h.cheval.strip().upper()) == nom_norm]
                if perfs_tandem:
                    cheval.tandem_driver_cheval = TandemStats(
                        courses_ensemble=len(perfs_tandem),
                        victoires_ensemble=sum(1 for p in perfs_tandem if p.rang == 1),
                        places_top5_ensemble=sum(1 for p in perfs_tandem if p.rang is not None and p.rang <= 5))
                    flags.append("TANDEM_DRIVER_CHEVAL_TURFOO")
            except Exception as e:
                logger.warning("Échec enrichissement jockey pour #%s %s : %s", cheval.numero, cheval.driver_jockey, e)
                flags.append("FICHE_JOCKEY_ECHEC")
        elif cheval.driver_fiche_url and "canalturf.com" in cheval.driver_fiche_url:
            try:
                stats_j = fetch_canalturf_fiche_personne(cheval.driver_fiche_url, "jockeys")
                asof_attr(stats_j, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
                hist_j_raw = stats_j.historique
                fenetres = fenetres_victoires(stats_j.historique, race.date_course, _FENETRES_JOURS)
                cheval.driver_stats = DriverStats(
                    fenetres=[DriverTrainerWindow(**f) for f in fenetres] if fenetres else [],
                    taux_victoire_carriere=stats_j.taux_victoire_pmu,
                    nb_courses_quinte=stats_j.nb_courses_quinte,
                    taux_victoire_quinte=stats_j.taux_victoire_quinte)
                if fenetres:
                    flags.append("ENRICHI_FICHE_JOCKEY_CANALTURF")
                else:
                    flags.append("FICHE_JOCKEY_HISTORIQUE_INSUFFISANT")  # trop peu de recul pour la + petite fenêtre (7j)
            except Exception as e:
                logger.warning("Échec enrichissement jockey CanalTurf pour #%s %s : %s", cheval.numero, cheval.driver_jockey, e)
                flags.append("FICHE_JOCKEY_ECHEC")
        elif cheval.driver_fiche_url and "zone-turf.fr" in cheval.driver_fiche_url:
            try:
                stats_j = fetch_zoneturf_fiche_personne(cheval.driver_fiche_url)
                asof_attr(stats_j, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
                hist_j_raw = stats_j.historique
                fenetres = fenetres_victoires(stats_j.historique, race.date_course, _FENETRES_JOURS)
                taux = None
                if stats_j.nb_victoires and stats_j.nb_courses:
                    taux = 100.0 * stats_j.nb_victoires / max(1, stats_j.nb_courses)
                cheval.driver_stats = DriverStats(
                    fenetres=[DriverTrainerWindow(**f) for f in fenetres] if fenetres else [],
                    taux_victoire_carriere=taux,
                )
                if fenetres:
                    flags.append("ENRICHI_FICHE_JOCKEY_ZONETURF")
                else:
                    flags.append("FICHE_JOCKEY_ZT_HISTORIQUE_VIDE")
                nom_norm = re.sub(r"\s+", " ", cheval.nom.strip().upper())
                perfs_t = [h for h in hist_j_raw if h.cheval and re.sub(r"\s+", " ", h.cheval.strip().upper()) == nom_norm]
                if perfs_t and cheval.tandem_driver_cheval is None:
                    cheval.tandem_driver_cheval = TandemStats(
                        courses_ensemble=len(perfs_t),
                        victoires_ensemble=sum(1 for p in perfs_t if p.rang == 1),
                        places_top5_ensemble=sum(1 for p in perfs_t if p.rang is not None and p.rang <= 5),
                    )
                    flags.append("TANDEM_DRIVER_CHEVAL_ZONETURF")
            except Exception as e:
                logger.warning("Échec enrichissement jockey ZT pour #%s %s : %s", cheval.numero, cheval.driver_jockey, e)
                flags.append("FICHE_JOCKEY_ECHEC")
        else:
            flags.append("FICHE_JOCKEY_URL_ABSENTE")

        # --- Entraîneur ---
        if cheval.entraineur_fiche_url and cheval.entraineur and "turfoo.fr" in cheval.entraineur_fiche_url:
            try:
                hist_e = fetch_historique_personne(cheval.entraineur_fiche_url, "entraineurs", cheval.entraineur)
                hist_e = filtrer_avant(hist_e, race.date_course)  # v1.29.40 : anti fuite temporelle
                hist_e_raw = hist_e
                fenetres = fenetres_victoires(hist_e, race.date_course, _FENETRES_JOURS)
                if fenetres:
                    cheval.trainer_stats = TrainerStats(
                        fenetres=[DriverTrainerWindow(**f) for f in fenetres])
                    flags.append("ENRICHI_FICHE_ENTRAINEUR")
                else:
                    flags.append("FICHE_ENTRAINEUR_HISTORIQUE_VIDE")
            except Exception as e:
                logger.warning("Échec enrichissement entraîneur pour #%s %s : %s", cheval.numero, cheval.entraineur, e)
                flags.append("FICHE_ENTRAINEUR_ECHEC")
        elif cheval.entraineur_fiche_url and "canalturf.com" in cheval.entraineur_fiche_url:
            try:
                stats_e = fetch_canalturf_fiche_personne(cheval.entraineur_fiche_url, "entraineurs")
                asof_attr(stats_e, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
                hist_e_raw = stats_e.historique
                fenetres = fenetres_victoires(stats_e.historique, race.date_course, _FENETRES_JOURS)
                cheval.trainer_stats = TrainerStats(
                    fenetres=[DriverTrainerWindow(**f) for f in fenetres] if fenetres else [],
                    taux_victoire_carriere=stats_e.taux_victoire_pmu,
                    nb_courses_quinte=stats_e.nb_courses_quinte,
                    taux_victoire_quinte=stats_e.taux_victoire_quinte)
                if fenetres:
                    flags.append("ENRICHI_FICHE_ENTRAINEUR_CANALTURF")
                else:
                    flags.append("FICHE_ENTRAINEUR_HISTORIQUE_INSUFFISANT")
            except Exception as e:
                logger.warning("Échec enrichissement entraîneur CanalTurf pour #%s %s : %s", cheval.numero, cheval.entraineur, e)
                flags.append("FICHE_ENTRAINEUR_ECHEC")
        elif cheval.entraineur_fiche_url and "zone-turf.fr" in cheval.entraineur_fiche_url:
            try:
                stats_e = fetch_zoneturf_fiche_personne(cheval.entraineur_fiche_url)
                asof_attr(stats_e, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
                hist_e_raw = stats_e.historique
                fenetres = fenetres_victoires(stats_e.historique, race.date_course, _FENETRES_JOURS)
                taux = None
                if stats_e.nb_victoires and stats_e.nb_courses:
                    taux = 100.0 * stats_e.nb_victoires / max(1, stats_e.nb_courses)
                cheval.trainer_stats = TrainerStats(
                    fenetres=[DriverTrainerWindow(**f) for f in fenetres] if fenetres else [],
                    taux_victoire_carriere=taux,
                )
                if fenetres:
                    flags.append("ENRICHI_FICHE_ENTRAINEUR_ZONETURF")
                else:
                    flags.append("FICHE_ENTRAINEUR_ZT_HISTORIQUE_VIDE")
            except Exception as e:
                logger.warning("Échec enrichissement entraîneur ZT pour #%s %s : %s", cheval.numero, cheval.entraineur, e)
                flags.append("FICHE_ENTRAINEUR_ECHEC")
        else:
            flags.append("FICHE_ENTRAINEUR_URL_ABSENTE")

    # --- B09 Association jockey-entraîneur (tandem) -- ajouté le 09/08/2026.
    # Aucune source dédiée trouvée malgré recherche (letrot.com/classements
    # n'a pas de vue "par équipe", pas plus que les sources presse) --
    # solution retenue : recouper les 2 historiques déjà récupérés
    # ci-dessus (driver ET entraîneur) sur (date, hippodrome) pour
    # détecter les courses courues ENSEMBLE, sans requête supplémentaire.
    # Repose sur l'hypothèse que même hippodrome + même date = même course
    # (pas garanti à 100% s'il y a 2 réunions le même jour au même
    # hippodrome, cas rare) -- approximation documentée, pas une certitude.
    if hist_j_raw and hist_e_raw and race.date_course:
        try:
            d_ref = datetime.fromisoformat(race.date_course).date()
        except ValueError:
            d_ref = None
        if d_ref:
            seuil = d_ref - timedelta(days=180)
            cles_e = {}
            for h in hist_e_raw:
                if not h.date or not h.hippodrome:
                    continue
                try:
                    d = datetime.fromisoformat(h.date).date()
                except ValueError:
                    continue
                if seuil <= d <= d_ref:
                    cles_e[(h.date, h.hippodrome.upper())] = h.rang
            victoires_ensemble, top5_ensemble = 0, 0
            for h in hist_j_raw:
                if not h.date or not h.hippodrome:
                    continue
                rang_e = cles_e.get((h.date, h.hippodrome.upper()))
                if rang_e is not None and h.rang == rang_e:  # même course, même résultat pour les 2 -> ensemble
                    if h.rang == 1:
                        victoires_ensemble += 1
                    if h.rang <= 5:
                        top5_ensemble += 1
            if victoires_ensemble >= 2:
                cheval.signaux_precalcules = list(cheval.signaux_precalcules) + [CatalogSignal(
                    id="B09", valeur_brute=10.0, catalog="B", famille="C",
                    justification=f"{victoires_ensemble} victoires ensemble sur 6 mois (recoupement historiques)",
                    confiance="STRICT")]
                flags.append("B09_TANDEM_RECOUPEMENT")
            elif victoires_ensemble >= 1 or top5_ensemble >= 2:
                cheval.signaux_precalcules = list(cheval.signaux_precalcules) + [CatalogSignal(
                    id="B09", valeur_brute=5.0, catalog="B", famille="C",
                    justification=f"{victoires_ensemble} victoire(s)/{top5_ensemble} Top5 ensemble sur 6 mois (recoupement historiques)")]
                flags.append("B09_TANDEM_RECOUPEMENT")

    # Classement national entraîneur (hors ligne, cf. classement_entraineur.py)
    # -- ajouté le 06/09/2026, débloque B12 (Entraîneur Top national).
    # Correction du commentaire d'origine : ce n'est PAS D45/B11 que ça
    # débloque (B11 concerne le classement DRIVER, pas entraîneur --
    # confusion de ma part signalée et corrigée le 06/09/2026 ; D45 n'a
    # aucune formule définie nulle part dans le texte source, cf.
    # PASSATION).
    if cheval.entraineur:
        from app.engine.classements import get_classement_entraineur as get_classement_national
        rang = get_classement_national(cheval.entraineur)
        if rang is not None:
            if cheval.trainer_stats is None:
                cheval.trainer_stats = TrainerStats()
            cheval.trainer_stats.classement_national = rang
            flags.append("CLASSEMENT_ENTRAINEUR_HORS_LIGNE")

            # B12 Entraîneur Top national -- jamais implémenté avant
            # cette session (la donnée n'existait pas). Classement MAISON
            # (open-pmu-api), pas le Cravache/Sulky d'Or officiel -- géré
            # avec la même prudence que B09 ci-dessus (signal ajouté
            # directement à signaux_precalcules, confiance abaissée d'un
            # cran vs le texte source pour refléter que la source n'est
            # pas officielle).
            if rang <= 2:
                cheval.signaux_precalcules = list(cheval.signaux_precalcules) + [CatalogSignal(
                    id="B12", valeur_brute=7.0, catalog="B", famille="C",
                    justification=f"Entraîneur classé #{rang} (classement maison open-pmu-api)",
                    confiance="DEGRADE")]
            elif rang <= 5:
                cheval.signaux_precalcules = list(cheval.signaux_precalcules) + [CatalogSignal(
                    id="B12", valeur_brute=4.0, catalog="B", famille="C",
                    justification=f"Entraîneur classé #{rang} (classement maison open-pmu-api)")]
            elif rang <= 10:
                cheval.signaux_precalcules = list(cheval.signaux_precalcules) + [CatalogSignal(
                    id="B12", valeur_brute=2.0, catalog="B", famille="C",
                    justification=f"Entraîneur classé #{rang} (classement maison open-pmu-api)")]
            if rang <= 10:
                flags.append("B12_CLASSEMENT_MAISON")

    # B11 Changement positif driver/jockey -- jamais implémenté avant
    # cette session (pas de classement driver consultable par NOM
    # arbitraire jusqu'ici ; seul classement_national_par_numero,
    # limité aux partants du jour, existait). Palier BOOKING (driver
    # nommé alors qu'il montait un autre cheval mieux placé pour la
    # même réunion) non implémenté : c'est une donnée du jour même
    # (autres engagements du driver), pas une donnée historique --
    # open-pmu-api ne peut rien dire là-dessus.
    if cheval.changement_driver and cheval.driver_jockey and cheval.driver_precedent:
        from app.engine.classements import get_classement_driver as classement_driver_par_nom
        rang_nouveau = (cheval.driver_stats.classement_national
                        if cheval.driver_stats and cheval.driver_stats.classement_national is not None
                        else classement_driver_par_nom(cheval.driver_jockey))
        rang_ancien = classement_driver_par_nom(cheval.driver_precedent)
        if rang_nouveau is not None and rang_ancien is not None:
            b11_val, b11_conf = None, None
            if rang_nouveau <= 3 and rang_ancien > 10:
                b11_val, b11_conf = 12.0, "STRICT"
            elif rang_nouveau <= 5 and rang_ancien > 10:
                b11_val, b11_conf = 7.0, "DEGRADE"
            elif rang_nouveau <= 10 and rang_ancien > 20:
                b11_val, b11_conf = 3.0, "MINIMAL"
            if b11_val is not None:
                cheval.signaux_precalcules = list(cheval.signaux_precalcules) + [CatalogSignal(
                    id="B11", valeur_brute=b11_val, catalog="B", famille="C", confiance=b11_conf,
                    justification=f"Driver #{rang_nouveau} remplace driver #{rang_ancien} "
                                  f"(classement maison open-pmu-api)")]
                flags.append("B11_CLASSEMENT_MAISON")

    return flags


def enrich_chevaux(
    chevaux: List[Cheval],
    race: RaceContext,
    enabled: bool = True,
    programme_urls: Optional[List[str]] = None,
    geny_url: Optional[str] = None,
) -> List[str]:
    """Enrichit chaque cheval. Retourne la liste à plat de tous les flags.

    geny_url (ajouté le 20/09/2026, Golden) : URL de la page course Geny
    déjà trouvée à l'identification (discover_all_sources), si Geny a pu
    être joint ce jour-là. Quand fourni, la fiche Geny (la plus riche des
    4 -- historique complet, records par discipline, propriétaire...) est
    tentée en PRIORITÉ pour CHAQUE cheval, quelle que soit sa source de
    collecte d'origine (CanalTurf/Turfoo/Zone-Turf). L'enrichissement par
    la source de collecte d'origine reste ENSUITE obligatoire en
    complément -- précisé par Golden le 20/09/2026 : ce n'est PAS un
    simple repli déclenché seulement si Geny échoue. Même quand Geny
    réussit, il ne couvre pas forcément tous les champs (chaque source a
    ses propres trous -- ex. Zone-Turf n'a pas de champ propriétaire).
    Chaque enrich_cheval() ne remplit un champ que s'il est encore None,
    donc Geny garde la priorité de fait sans qu'un ordre d'écrasement
    explicite soit nécessaire. Et si Geny échoue purement et simplement
    (anti-bot, confirmé intermittent sur Render le 20/09/2026), la source
    d'origine comble alors l'intégralité de l'enrichissement comme avant
    -- pas de régression possible par rapport à la situation actuelle."""
    all_flags: List[str] = []
    if not enabled:
        return all_flags
    # P2 : rattacher fiches Zone-Turf si absentes (gains / délai / hist.)
    zt_urls = [u for u in (programme_urls or []) if "zone-turf.fr" in (u or "")]
    if zt_urls:
        try:
            n_att = attach_zoneturf_fiche_urls(chevaux, zt_urls)
            if n_att:
                all_flags.append(f"ZT_FICHE_URL_ATTACHEES_{n_att}")
        except Exception as e:
            logger.warning("attach_zoneturf_fiche_urls: %s", e)
            all_flags.append("ZT_FICHE_ATTACH_ECHEC")

    geny_fiche_par_numero: Dict[int, str] = {}
    if geny_url:
        from app.scraping.geny import fetch_geny_numero_to_fiche_map
        try:
            geny_fiche_par_numero = fetch_geny_numero_to_fiche_map(geny_url)
            if geny_fiche_par_numero:
                all_flags.append(f"GENY_FICHES_PRIORITAIRES_TROUVEES_{len(geny_fiche_par_numero)}")
            else:
                all_flags.append("GENY_FICHES_PRIORITAIRES_INDISPONIBLES")
        except Exception as e:
            logger.warning("fetch_geny_numero_to_fiche_map a levé une exception inattendue : %s", e)
            all_flags.append("GENY_FICHES_PRIORITAIRES_INDISPONIBLES")

    for cheval in chevaux:
        fiche_url_origine = cheval.fiche_url
        flags: List[str] = []
        if cheval.numero in geny_fiche_par_numero:
            # 1) Geny en PRIORITÉ (source la plus riche -- historique complet,
            # records par discipline, propriétaire...).
            cheval.fiche_url = geny_fiche_par_numero[cheval.numero]
            flags = enrich_cheval(cheval, race)
            # 2) L'enrichissement par la source de collecte d'origine reste
            # OBLIGATOIRE en complément -- ce n'est PAS un simple repli en
            # cas d'échec Geny (précisé par Golden le 20/09/2026) : même
            # quand Geny réussit, il ne couvre pas tout (ex. Zone-Turf n'a
            # pas de champ propriétaire, mais Geny si -- l'inverse existe
            # aussi selon les champs). Chaque enrich_cheval() ne remplit un
            # champ QUE s'il est encore None, donc Geny garde la priorité
            # de fait : la source d'origine ne comble que ce que Geny a
            # laissé vide, jamais n'écrase une valeur déjà posée par Geny.
            cheval.fiche_url = fiche_url_origine
            if cheval.fiche_url:
                # v1.29.25 : skip jockey/entraîneur (déjà tentés en passe Geny)
                flags += enrich_cheval(cheval, race, skip_personne_fiches=True)
                flags.append("ENRICHISSEMENT_COMPLEMENTAIRE_SOURCE_ORIGINE")
        else:
            flags = enrich_cheval(cheval, race)
        # P2 secondaire : si fiche CT sans gains/délai, tenter ZT si URL déjà ZT
        # (cas multi-source où CT a gagné le merge mais ZT fiche était dispo)
        if (
            cheval.gains_totaux_eur is None
            and cheval.delai_j is None
            and cheval.fiche_url
            and "zone-turf.fr" in cheval.fiche_url
            and "ENRICHI_FICHE_ZONETURF" not in flags
        ):
            try:
                extra = []
                fiche_zt = fetch_zoneturf_fiche_cheval(cheval.fiche_url, cheval.nom)
                asof_attr(fiche_zt, "historique", race.date_course)  # v1.29.40 : anti fuite temporelle
                if fiche_zt.nb_courses is not None and cheval.nb_courses is None:
                    cheval.nb_courses = fiche_zt.nb_courses
                if fiche_zt.nb_victoires is not None and cheval.victoires_carriere is None:
                    cheval.victoires_carriere = fiche_zt.nb_victoires
                if fiche_zt.historique and race.date_course and cheval.delai_j is None:
                    try:
                        d_course = datetime.fromisoformat(race.date_course).date()
                        d_derniere = datetime.fromisoformat(fiche_zt.historique[0].date).date()
                        cheval.delai_j = (d_course - d_derniere).days
                        extra.append("ENRICHI_DELAI_ZT")
                    except ValueError:
                        pass
                if extra:
                    flags = flags + extra + ["ENRICHI_FICHE_ZONETURF_SECONDAIRE"]
            except Exception as e:
                logger.debug("ZT secondaire #%s: %s", cheval.numero, e)
        cheval.flags = list(dict.fromkeys((cheval.flags or []) + flags))
        # Chaque flag est préfixé par le cheval concerné -- corrigé le
        # 20/09/2026 (Golden, demande de traçabilité intégrale) : avant, la
        # liste était aplatie sans savoir QUEL cheval avait échoué/réussi
        # quoi, rendant un Counter(flags) inutile pour localiser un cheval
        # précis en échec d'enrichissement (on ne savait que "5 échecs",
        # jamais lesquels). Signature de retour inchangée (List[str]) pour
        # ne pas casser les appelants existants.
        all_flags.extend(f"#{cheval.numero} {cheval.nom}: {f}" for f in flags)
    return all_flags


def attach_zoneturf_fiche_urls(chevaux: List[Cheval], programme_urls: List[str]) -> int:
    """Associe fiche_url Zone-Turf aux chevaux via slug /cheval/{slug}-{id}/.
    Retourne le nombre de matchs. Ne scrape pas les fiches (voir enrich_chevaux).
    """
    import re as _re
    import unicodedata as _ud
    from bs4 import BeautifulSoup as _BS
    from app.scraping.base import fetch_html as _fetch

    def _norm(s: str) -> str:
        s = _ud.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
        return _re.sub(r"[^a-z0-9]+", "", s.lower())

    mapping = {}
    for url in programme_urls:
        try:
            soup = _BS(_fetch(url), "lxml")
        except Exception as e:
            logger.warning("attach_zoneturf: échec %s : %s", url, e)
            continue
        for a in soup.find_all("a", href=True):
            m = _re.search(r"/cheval/([a-z0-9\-]+)-(\d+)/?", a["href"])
            if not m:
                continue
            slug_name = m.group(1).replace("-", " ")
            full = a["href"] if a["href"].startswith("http") else f"https://www.zone-turf.fr{a['href']}"
            full = full.split("#")[0]
            mapping[_norm(slug_name)] = full
    n = 0
    for ch in chevaux:
        if ch.fiche_url:
            continue
        k = _norm(ch.nom)
        if k in mapping:
            ch.fiche_url = mapping[k]
            n += 1
    return n
