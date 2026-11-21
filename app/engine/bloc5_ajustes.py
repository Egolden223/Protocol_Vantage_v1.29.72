"""
bloc5_ajustes.py -- Bloc 5, postes 21-22 (M04/M30 "ajustés") et 29
(RAH-200, convergence de familles), patch v1.22.2-test.

Poste 28 (B11 extension, "Driver Top10 abandonne monte supérieure") reste
NON IMPLÉMENTÉ ici : il nécessite un classement national hebdomadaire des
drivers/jockeys (Top10) ET les montes disponibles ce jour-là pour ce
driver sur les autres courses de la réunion -- aucune des deux données
n'est scrapée à ce jour (cf. catalog_rules.py, commentaire "B09/B11/M02/
M14 -- non scrapées"). Rien n'est fabriqué pour combler ce vide (RÈGLE 2).

Postes 21-22 -- M04/M30 ajustés :
  Le M04 "de base" (historique_signals.py) et le nouveau M30 (ci-dessous)
  sont injectés comme signaux catalogue B/M ordinaires. Ils traversent
  donc automatiquement la décote de famille PUIS RAH-310 (atténuation
  générique -50% en tranche T3/T4, déjà implémentée dans tranches.py :
  sommer_bonus_malus). Cette seule mécanique reproduit déjà, sans code
  supplémentaire, les 2 premières lignes du patch pour M04 (Favori -10 /
  Outsider sans intention -5) et les 2 lignes de M30 (Favori -15 /
  Outsider -7,5).
  Il ne manque que la 2e atténuation, SPÉCIFIQUE à M04, quand un signal
  d'intention est actif pour un outsider (-5 -> -2,5) : c'est l'unique
  rôle de compute_m04_correction ci-dessous, calculé en poste séparé et
  ajouté hors modulation générique (même schéma que D46-D22/M48-B42 dans
  pch_final.py), pour ne pas modifier rétroactivement la somme déjà
  attribuée par sommer_bonus_malus.
"""
from __future__ import annotations
from typing import List, Optional, Sequence, Tuple

from app.models import Cheval, Tranche, CatalogSignal
from app.engine.tranches import appliquer_decote_famille
from app.scraping.musique import MusiquePerf

_TRANCHES_OUTSIDER = (Tranche.T3, Tranche.T4A, Tranche.T4B)


def _top5_sans_victoire_streak(perfs: Sequence[MusiquePerf]) -> int:
    """Nombre de courses consécutives les PLUS RÉCENTES finies en Top5
    (rang 2 à 5 inclus) sans aucune victoire. La série s'arrête à la
    première victoire, au premier rang > 5 ou au premier incident."""
    streak = 0
    for p in perfs:
        if p.rang is not None and 2 <= p.rang <= 5:
            streak += 1
        else:
            break
    return streak


def compute_m30(cheval: Cheval, perfs: Sequence[MusiquePerf]) -> Optional[CatalogSignal]:
    """M30 -- Stagnation sans victoire (Partie 4.2). Déclencheur et valeurs
    de référence identiques à la version originale du catalogue -- seule
    l'atténuation T3/T4 change, et elle est déjà générique (RAH-310).
    Non implémenté ici (nécessite ICP_global / FAVORI_UNANIME / fenêtre 5
    courses, hors périmètre de ce chantier) : M30_PARADOXE_FAVORI,
    M30_ETENDU_5COURSES, pénalité additionnelle ICP_global>=6."""
    streak = _top5_sans_victoire_streak(perfs)
    if streak >= 3:
        valeur = -18.0 if (cheval.cote_matin is not None and cheval.cote_matin < 6) else -15.0
        return CatalogSignal(id="M30", valeur_brute=valeur, catalog="M", famille="F",
                              confiance="STRICT",
                              justification=f"{streak} courses consécutives Top5 sans victoire")
    if streak == 2:
        return CatalogSignal(id="M30", valeur_brute=-8.0, catalog="M", famille="F",
                              confiance="DEGRADE",
                              justification=f"{streak} courses consécutives Top5 sans victoire")
    if streak == 1:
        return CatalogSignal(id="M30", valeur_brute=-4.0, catalog="M", famille="F",
                              confiance="MINIMAL",
                              justification="dernière course Top5 sans victoire")
    return None


def intention_active(score_sim: Optional[float]) -> bool:
    """Intention = D46-D22/RAH-308 actif OU M48-B42/RAH-304 actif OU
    D02-B59/RAH-307 actif OU SCORE_SIM >= 0,70 (Partie 4.2, note M04 ;
    Partie 4.4 RAH-306 pour la sous-famille "intention" de RAH-200).
    D46-D22, M48-B42 et D02-B59 ne sont pas encore implémentés (toujours
    inactifs) -- seul SCORE_SIM (heuristique SUPRA simplifiée) peut
    déclencher ce booléen aujourd'hui. À réévaluer une fois ces 3 modules
    construits."""
    return score_sim is not None and score_sim >= 0.70


def compute_m04_correction(signaux: Sequence[CatalogSignal], tranche: Optional[Tranche],
                            intention: bool) -> Tuple[float, List[str]]:
    """Poste 21 (correction). Calcule la valeur EXACTE de M04 après décote
    de famille (peut différer de -10/-5 bruts en cas de collision avec un
    autre signal famille L de plus grande magnitude pour ce cheval) et
    ajoute la 2e atténuation d'intention si applicable : correction =
    |valeur_apres_decote| x 0,25, ajoutée en poste séparé (jamais reprise
    dans MALUS_TRANCHE_MULT, comme D46-D22/M48-B42)."""
    if tranche not in _TRANCHES_OUTSIDER or not intention:
        return 0.0, []
    decote = appliquer_decote_famille(list(signaux))
    for s, v in zip(signaux, decote):
        if s.id == "M04" and v < 0:
            return round(abs(v) * 0.25, 3), ["M04_INTENTION_ATTENUATION"]
    return 0.0, []


def compute_rah200(signaux: Sequence[CatalogSignal], intention: bool) -> Tuple[float, List[str]]:
    """Poste 29 -- RAH-200 : convergence de signaux actifs sur >= 4
    familles distinctes (C/L/F/M/P, Partie 1.5/1.4). +3 PCH, flag
    CONVERGENCE_4_FAMILLES ; +4 PCH (au lieu de +3) si la convergence
    inclut un signal de la sous-famille "intention" -- ici approximée via
    intention_active() (voir limitation ci-dessus : seul SCORE_SIM>=0,70
    est réellement disponible pour l'instant, B11/déclaration entraîneur/
    M48-B42 ne le sont pas)."""
    familles_actives = {s.famille for s in signaux if s.famille and s.valeur_brute}
    if len(familles_actives) < 4:
        return 0.0, []
    if intention:
        return 4.0, ["CONVERGENCE_4_FAMILLES_INTENTION"]
    return 3.0, ["CONVERGENCE_4_FAMILLES"]
