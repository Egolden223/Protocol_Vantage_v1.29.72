"""
gamma_signals.py -- RAH-179 à 186 (Section M, "GAMMA"), plafond +8 PCH par
cheval (toutes signaux GAMMA confondus, RAH-179-209). Formules retranscrites
depuis partie17_supra_longshot_gmo.txt.

Implémentés (calculables avec les données déjà collectées + historique
fiche cheval) : RAH-179, RAH-181, RAH-182, RAH-183, RAH-184. RAH-181
débloqué le 03/09/2026 grâce à tandem_driver_cheval (CanalTurf) --
approximé comme duo jockey+entraîneur sous l'hypothèse d'entraîneur
inchangé (cf. _rah181, consigne explicite Golden 03/09/2026 :
tout changement d'entraîneur est notifié ailleurs dans le pipeline,
donc son absence = continuité fiable).
Non implémentés (données non collectées -- modèle prédictif Turf.bzh,
rythme par course historique) : RAH-180, RAH-186.
"""
from __future__ import annotations
from typing import List, Optional
from statistics import mean

from app.models import Cheval, RaceContext, CatalogSignal
from app.scraping.musique import parse_musique, rangs_recents

GAMMA_CAP = 8.0


def _rah179(cheval: Cheval, champ_moyennes: List[float]) -> Optional[CatalogSignal]:
    if cheval.cote_matin is None or cheval.cote_matin <= 15:
        return None
    perfs = parse_musique(cheval.musique)
    rangs3 = rangs_recents(perfs, 3)
    if len(rangs3) < 3 or not champ_moyennes:
        return None
    moy_cheval = mean(rangs3)
    moy_champ = mean(champ_moyennes)
    if moy_cheval < moy_champ:
        return CatalogSignal(id="RAH-179", valeur_brute=2.0, catalog="B", famille="F", is_gamma=True,
                              confiance="DEGRADE",
                              justification=f"moy. 3 dernières positions ({moy_cheval:.1f}) < moyenne champ ({moy_champ:.1f}), cote>15/1")
    return None


def _rah182(cheval: Cheval, race: RaceContext) -> Optional[CatalogSignal]:
    if cheval.cote_matin is None or cheval.cote_matin <= 15 or not cheval.historique_distance:
        return None
    exact = [h for h in cheval.historique_distance if abs(h.valeur - race.distance_m) <= 50]
    if len(exact) < 2 or any(h.rang > 5 for h in exact):
        return None
    # dernière performance globale (toutes courses) ailleurs doit être >8e
    autres = sorted(cheval.historique_distance, key=lambda h: h.date or "", reverse=True)
    plus_recente_ailleurs = next((h for h in autres if abs(h.valeur - race.distance_m) > 50), None)
    if plus_recente_ailleurs and plus_recente_ailleurs.rang > 8:
        return CatalogSignal(id="RAH-182", valeur_brute=3.0, catalog="B", famille="L", is_gamma=True,
                              confiance="DEGRADE",
                              justification=f"100% Top5 sur ce tracé exact ({len(exact)} courses), dernière perf ailleurs >8e")
    return None


def _rah183(cheval: Cheval, race: RaceContext) -> Optional[CatalogSignal]:
    if race.hippodrome.upper() != "AUTEUIL" or race.partants_confirmes < 17:
        return None
    if cheval.numero_autostart is None or cheval.numero_autostart < 13:
        return None
    valeur = 3.0 if (cheval.cote_matin or 0) > 15 else 1.0
    return CatalogSignal(id="RAH-183", valeur_brute=valeur, catalog="B", famille="L", is_gamma=True,
                          confiance="DEGRADE", justification=f"Auteuil, {race.partants_confirmes} partants, corde/n°{cheval.numero_autostart}")


def _rah184(cheval: Cheval, race: RaceContext, champ: List[Cheval]) -> Optional[CatalogSignal]:
    if race.hippodrome.upper() != "AUTEUIL" or not cheval.entraineur:
        return None
    meme_ecurie = [c for c in champ if c.entraineur == cheval.entraineur and c.cote_matin is not None]
    if len(meme_ecurie) < 3:
        return None
    cote_max = max(c.cote_matin for c in meme_ecurie)
    if cheval.cote_matin == cote_max:
        return CatalogSignal(id="RAH-184", valeur_brute=2.0, catalog="B", famille="C", is_gamma=True,
                              confiance="DEGRADE",
                              justification=f"écurie {cheval.entraineur} engage {len(meme_ecurie)} chevaux à Auteuil, cote la plus élevée du lot")
    return None


def _rah181(cheval: Cheval) -> Optional[CatalogSignal]:
    """SYNERGIE_JC : duo jockey+entraîneur >=3 courses ensemble sur CE
    cheval en 12 mois ET taux de victoires du duo >30% ET cote>10/1.

    Débloqué le 03/09/2026 : tandem_driver_cheval n'est réellement peuplé
    que depuis l'ajout de l'enrichissement CanalTurf (jockey par
    performance passée) -- MAIS cette source ne donne que le jockey, pas
    l'entraîneur de l'époque, donc pas moyen de vérifier que c'était bien
    le MÊME DUO (pas seulement le même jockey). Sur consigne explicite de
    Golden (03/09/2026) : on suppose l'entraîneur inchangé sur la période
    couverte SAUF si cheval.changement_entraineur est actif (un
    changement d'entraîneur étant toujours notifié/détecté par ailleurs
    dans le pipeline) -- dans ce cas seulement, le jockey-match équivaut
    au duo-match. Fenêtre "12 mois" non vérifiable précisément
    (TandemStats n'a pas de dates par course) -- on utilise l'ensemble
    des dernières performances CanalTurf disponibles, qui sont
    récentes par construction (mêmes limites que le reste de
    tandem_driver_cheval, cf. enrichment.py)."""
    if cheval.changement_entraineur:
        return None
    td = cheval.tandem_driver_cheval
    if not td or td.courses_ensemble < 3 or (cheval.cote_matin or 0) <= 10:
        return None
    taux_victoires = td.victoires_ensemble / td.courses_ensemble
    if taux_victoires > 0.30:
        return CatalogSignal(id="RAH-181", valeur_brute=2.0, catalog="B", famille="C", is_gamma=True,
                              confiance="DEGRADE",
                              justification=f"duo jockey/entraîneur (supposé constant) {td.courses_ensemble} courses, "
                                            f"{taux_victoires:.0%} victoires, cote>10/1")
    return None


def compute_gamma_signals(cheval: Cheval, race: RaceContext, champ: List[Cheval]) -> List[CatalogSignal]:
    champ_moyennes = []
    for c in champ:
        rangs3 = rangs_recents(parse_musique(c.musique), 3)
        if len(rangs3) == 3:
            champ_moyennes.append(mean(rangs3))

    signaux = [s for s in [
        _rah179(cheval, champ_moyennes),
        _rah181(cheval),
        _rah182(cheval, race),
        _rah183(cheval, race),
        _rah184(cheval, race, champ),
    ] if s is not None]

    total = sum(s.valeur_brute for s in signaux)
    if total > GAMMA_CAP:
        facteur = GAMMA_CAP / total
        for s in signaux:
            s.valeur_brute = round(s.valeur_brute * facteur, 2)

    return signaux
