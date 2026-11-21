"""ai_rhythm.py -- RAH-270 (v1.29.14) : signal qualitatif de rythme/allure
optionnel, dérivé par IA de Cheval.commentaire_derniere_course.

Contexte protocole : RAH-270 stipule que le commentaire qualitatif de
rythme devrait primer sur chrono_sectionnel (jamais scrapé, cf.
qualitative_engine.py). Jusqu'ici resté "NON_EVALUE" faute de lecture de
texte libre fiable en pur Python -- signalé comme "spéculatif/non validé"
lors de l'audit du 19/09/2026.

Conception délibérément bornée et réversible :
  - Un SEUL appel LLM par course (tous les chevaux d'un coup), pas un par
    cheval -- coût et latence maîtrisés.
  - Désactivé par défaut (AI_QUALITATIVE_SIGNAL=0) -- activer le
    superviseur IA (AI_SUPERVISOR) seul ne suffit pas.
  - Signal individuel plafonné +/-3 (RAH270_CAP), et de toute façon
    ensuite soumis au plafond RAH-242 (bonus secondaires <= bonus
    primaires positifs) dans pch_final.py -- double borne.
  - Aucune exception ne doit jamais remonter jusqu'à l'orchestrateur :
    en cas d'échec (timeout, clé invalide, JSON non parseable...), tous
    les chevaux gardent rah270_ai_signal=None -> rah270_ai_pch=0.0,
    comportement strictement identique à avant v1.29.14.
  - Non validé en walk-forward -- à surveiller via les flags posés ici
    avant de lui faire confiance en conditions réelles.
"""
from __future__ import annotations

import logging
from typing import List

from app.models import Cheval

logger = logging.getLogger("vantage.ai_rhythm")

MIN_COMMENTAIRE_LEN = 10


def enrich_race_with_ai_rhythm(champ: List[Cheval]) -> List[str]:
    """Point d'entrée orchestrateur. Retourne des flags pour le rapport
    de traçabilité (étape dédiée, cf. orchestrator.py). Ne lève jamais.
    """
    flags: List[str] = []
    try:
        from app.llm.supervisor import is_qualitative_ai_enabled, classify_race_rhythm
    except Exception as e:  # pragma: no cover -- import ne devrait jamais échouer
        logger.warning("ai_rhythm: import supervisor impossible: %s", e)
        return ["RAH270_AI_INDISPONIBLE:import_supervisor"]

    if not is_qualitative_ai_enabled():
        return ["RAH270_AI_DESACTIVE"]

    candidats = [
        c for c in champ
        if c.commentaire_derniere_course and len(c.commentaire_derniere_course.strip()) >= MIN_COMMENTAIRE_LEN
    ]
    if not candidats:
        return ["RAH270_AI_AUCUN_COMMENTAIRE_EXPLOITABLE"]

    payload = [
        {"numero": c.numero, "nom": c.nom, "commentaire": c.commentaire_derniere_course.strip()[:500]}
        for c in candidats
    ]

    try:
        res = classify_race_rhythm(payload)
    except Exception as e:
        logger.warning("ai_rhythm: appel classify_race_rhythm a levé une exception: %s", e)
        return [f"RAH270_AI_ECHEC:exception_{type(e).__name__}"]

    status = res.get("status")
    if status != "OK":
        detail = res.get("error") or res.get("note") or status
        return [f"RAH270_AI_ECHEC:{detail}"]

    par_numero = res.get("par_numero") or {}
    n_appliques = 0
    for c in candidats:
        entry = par_numero.get(c.numero)
        if not entry:
            continue
        c.rah270_ai_signal = entry["signal"]
        c.rah270_ai_rationale = entry["rationale"]
        if abs(entry["signal"]) > 0.01:
            n_appliques += 1

    flags.append(f"RAH270_AI_APPLIQUE:provider={res.get('provider')}:chevaux_signal_non_nul={n_appliques}")
    return flags
