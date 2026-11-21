"""compliance_guard.py — Garde de conformité protocolaire (déterministe).

Vérifie règles, invariants de pipeline, flags GMO et cohérence indices
AVANT toute intervention IA. Gratuit, auditables, toujours actifs.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from app.models import HorseScore, RaceContext, Tranche


def run_compliance_guard(
    race: RaceContext,
    horses: List[HorseScore],
    selection: List[int],
    gmo_flags: Optional[List[str]] = None,
    constraints_report: Optional[List[Dict]] = None,
    version_flags: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retourne un rapport de conformité structuré."""
    checks: List[Dict[str, Any]] = []
    gmo_flags = gmo_flags or []
    constraints_report = constraints_report or []
    version_flags = version_flags or {}

    def add(rule: str, status: str, detail: str) -> None:
        checks.append({"rule": rule, "status": status, "detail": detail})

    n = len(horses)
    sel = [horses[i] for i in selection if 0 <= i < n]

    # --- Taille ticket ---
    if len(selection) == 8:
        add("TICKET_SIZE_8", "PASS", "8 chevaux sélectionnés")
    else:
        add("TICKET_SIZE_8", "FAIL", f"{len(selection)} chevaux (8 attendus)")

    # --- Modules / breakdown présents ---
    missing_bd = [h.cheval.numero for h in horses if h.breakdown is None]
    if missing_bd:
        add("MODULES_BREAKDOWN", "FAIL", f"breakdown absent: {missing_bd}")
    else:
        add("MODULES_BREAKDOWN", "PASS", f"breakdown présent sur {n} partants")

    # --- PCH bornes raisonnables ---
    pch_out = []
    for h in horses:
        if h.breakdown is None:
            continue
        pch = h.breakdown.pch_final
        if pch is not None and (pch < -50 or pch > 400):
            pch_out.append(h.cheval.numero)
    if pch_out:
        add("PCH_BORNES", "WARN", f"PCH hors plage attendue: {pch_out}")
    else:
        add("PCH_BORNES", "PASS", "PCH dans plage indicative")

    # --- Tranche cohérente avec cote (si les deux connus) ---
    incoh = []
    for h in horses:
        t = h.synthesis.tranche if h.synthesis else None
        c = h.cheval.cote_avant_course or h.cheval.cote_matin
        if t is None or c is None or c <= 0:
            continue
        expected = None
        if c < 9:
            expected = "T1"
        elif c < 15:
            expected = "T2"
        elif c < 35:
            expected = "T3"
        else:
            expected = "T4"
        tv = t.value if hasattr(t, "value") else str(t)
        if expected == "T4" and not tv.startswith("T4"):
            incoh.append(f"#{h.cheval.numero}:{tv}@cote{c}")
        elif expected != "T4" and tv != expected and not (expected == "T3" and tv.startswith("T3")):
            # tolère T4a/T4b
            if not (expected.startswith("T") and tv.startswith(expected[:2])):
                incoh.append(f"#{h.cheval.numero}:{tv}@cote{c}")
    if incoh[:8]:
        add("TRANCHE_VS_COTE", "WARN", f"écarts possibles: {incoh[:8]}")
    else:
        add("TRANCHE_VS_COTE", "PASS", "tranches alignées cotes (ou données absentes)")

    # --- Style retiré : pas de STYLE_FORCE dans flags ---
    style_forces = [f for f in gmo_flags if "STYLE_FORCE" in f or "diversite_style" in f.lower()]
    if style_forces:
        add("STYLE_RETIRE", "FAIL", f"flags style encore actifs: {style_forces[:5]}")
    else:
        add("STYLE_RETIRE", "PASS", "aucun forçage style (RAH-07 retiré)")

    # --- Hiérarchie / flags noyau ---
    has_core = any(f.startswith("CORE_PROTECT=") for f in gmo_flags)
    has_marche = any("MARCHE_COUVERTURE" in f or "MARCHE_TOP3" in f for f in gmo_flags)
    if has_core:
        add("CORE_PROTECT_FLAG", "PASS", "noyau documenté dans flags GMO")
    else:
        add("CORE_PROTECT_FLAG", "WARN", "CORE_PROTECT absent des flags (sélection ancienne?)")
    if has_marche:
        add("MARCHE_FLAGS", "PASS", "couverture marché journalisée")
    else:
        add("MARCHE_FLAGS", "WARN", "flags marché absents")

    # --- Constraints report statuses ---
    fails = [r for r in constraints_report if r.get("status") == "FAIL"]
    warns = [r for r in constraints_report if r.get("status") == "WARN"]
    if fails:
        add(
            "CONSTRAINTS_FAIL",
            "FAIL",
            f"{len(fails)} FAIL: " + ", ".join(r.get("rule", "?") for r in fails),
        )
    else:
        add("CONSTRAINTS_FAIL", "PASS", "aucun FAIL checklist Bloc 9")
    if warns:
        add("CONSTRAINTS_WARN", "WARN", f"{len(warns)} WARN documentés")
    else:
        add("CONSTRAINTS_WARN", "PASS", "aucun WARN checklist")

    # --- Version flags clés ---
    expected_on = [
        "intra_tranche_qualite",
        "contraintes_hierarchie",
        "style_greedy_retire",
        "couverture_favoris_marche",
    ]
    missing_flags = [k for k in expected_on if version_flags and not version_flags.get(k)]
    if version_flags and missing_flags:
        add("FUSION_FLAGS", "WARN", f"flags attendus absents/false: {missing_flags}")
    elif version_flags:
        add("FUSION_FLAGS", "PASS", "flags protocole récents présents")
    else:
        add("FUSION_FLAGS", "INFO", "version_flags non fournis")

    # --- RAH-270 IA (v1.29.14) : traçabilité de l'influence IA sur le ticket ---
    ai_touches = [
        h.cheval.numero for h in horses
        if h.breakdown is not None and abs(h.breakdown.rah270_ai_pch) > 0.01
    ]
    if ai_touches:
        add(
            "RAH270_AI_INFLUENCE",
            "INFO",
            f"signal IA rythme appliqué (borné +/-3) sur {len(ai_touches)} cheval(aux): {ai_touches}",
        )
    else:
        add("RAH270_AI_INFLUENCE", "INFO", "aucun signal IA rythme appliqué (désactivé, indisponible, ou 0.0 partout)")

    # --- ICP vs marché (anomalie informative) ---
    icp_high = []
    for h in sel:
        icp = h.cheval.icp_global or 0
        if icp >= 6:
            icp_high.append(h.cheval.numero)
    add(
        "ICP_TICKET",
        "INFO",
        f"{len(icp_high)} cheval(aux) ICP>=6 dans le ticket: {icp_high}",
    )

    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_warn = sum(1 for c in checks if c["status"] == "WARN")
    verdict = "CONFORME" if n_fail == 0 else "NON_CONFORME"
    if n_fail == 0 and n_warn > 0:
        verdict = "CONFORME_AVEC_RESERVES"

    return {
        "verdict": verdict,
        "nb_fail": n_fail,
        "nb_warn": n_warn,
        "checks": checks,
        "actions_autorisees": [
            "NONE",
            "LOG_ONLY",
            "SUGGEST_REFETCH_SOURCE",
            "SUGGEST_SWAP_HORS_NOYAU",  # jamais appliqué sans validation humaine / flag explicite
        ],
        "note": (
            "Garde déterministe v1.29.13 — les actions IA éventuelles sont bornées "
            "à la liste actions_autorisees et ne modifient le ticket que si "
            "AI_APPLY_BOUNDED_REPAIRS=1 (désactivé par défaut)."
        ),
    }
