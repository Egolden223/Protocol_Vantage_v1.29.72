"""ticket.py -- Bloc 10 (journalisation GAMMA), Bloc 11 (P1->R2), Bloc 12 (sortie finale)."""
from __future__ import annotations
from typing import List, Dict
from datetime import datetime, timezone

from app.models import HorseScore, RaceContext, TicketSlot, RaceResult
from app.version import VERSION_RULESET


def gamma_log(horses: List[HorseScore], selection: List[int]) -> List[Dict]:
    log = []
    for i in selection:
        h = horses[i]
        gamma_signals = [s for s in h.breakdown.signaux_actifs if s.get("is_gamma")]
        log.append({
            "numero": h.cheval.numero, "nom": h.cheval.nom,
            "gamma_detectes": [s["id"] for s in gamma_signals],
            "total_pch": round(h.breakdown.gamma_pch, 2),
            "cap_ok": abs(h.breakdown.gamma_pch) <= 8.01,
        })
    return log


def categorize(h: HorseScore) -> str:
    """Conservé uniquement à titre informatif dans le JSON (lisibilité
    humaine) -- n'intervient plus dans la construction du ticket depuis
    le 02/09/2026, cf. build_ticket ci-dessous."""
    cote = h.cheval.cote_matin
    ordre = h.synthesis.ordre_final
    if (cote is not None and cote <= 8) or ordre >= 0.40:
        return "Favori"
    if (cote is not None and cote <= 25) or ordre >= 0.30:
        return "Outsider"
    return "Tocard"


def build_ticket(horses: List[HorseScore], selection: List[int],
                 roles_map: Dict = None) -> List[TicketSlot]:
    """Étape 11.c (Partie 17.10a, paradigme « Objectif Désordre ») --
    HABILLAGE P1->R2, présentation uniquement : « les 8 retenus sont
    étiquetés P1 à R2 par ORDRE_SCORE décroissant ; aucune règle ne peut
    modifier la sélection sur la base de cette étiquette. »

    Corrigé le 02/09/2026 -- la version précédente re-triait les 8 par
    catégorie Favori/Outsider/Tocard avec des préférences de slot
    alternées (convention PILIER/RÉGULIER antérieure, jamais mise à jour
    après le patch). C'était un vrai bug au sens du protocole actuel :
    la sélection des 8 est déjà entièrement décidée par GMO-V (Étape
    11.b, couverture jointe gloutonne) ; cette fonction ne doit plus que
    les ordonner et les étiqueter, jamais les re-choisir ou les
    repositionner selon une catégorie."""
    sel_horses = [horses[i] for i in selection]
    sel_horses.sort(key=lambda h: h.synthesis.ordre_final, reverse=True)

    labels = ["P1", "P2", "P3", "P4", "P5", "P6", "R1", "R2"]
    slots: List[TicketSlot] = []
    for label, h in zip(labels, sel_horses):
        cat = categorize(h)
        justifs: List[str] = []
        if h.cheval.favori_unanime:
            justifs.append("FAVORI_UNANIME")
        if h.synthesis.tranche and h.synthesis.tranche.value in ("T4a", "T4b"):
            justifs.append(f"RAH-266 ({h.synthesis.tranche.value})")
        if not justifs:
            justifs.append("habillage ORDRE_SCORE (17.10a)")
        role = None  # roles retired
        slots.append(TicketSlot(position=label, numero=h.cheval.numero, nom=h.cheval.nom,
                                 ordre_final=round(h.synthesis.ordre_final, 4),
                                 cote=h.cheval.cote_matin, categorie=cat,
                                 justification_rah=justifs, role=role))
    return slots


def build_json_output(result: RaceResult) -> Dict:
    """Partie 8 -- structure JSON de sortie (champs principaux ; voir
    protocol_assets/partie8_json_template.txt pour le gabarit complet
    d'origine que la Couche LLM peut enrichir si besoin)."""
    return {
        "protocol_version": f"PROTOCOL_VANTAGE_{VERSION_RULESET}",
        "race_id": result.race_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "course": {
            "hippodrome": result.context.hippodrome,
            "discipline": result.context.discipline.value,
            "distance_m": result.context.distance_m,
            "type_course": result.context.type_course.value,
            "partants": result.context.partants_confirmes,
            "signature": result.context.signature.value if result.context.signature else None,
        },
        "chevaux": [
            {
                "numero": h.cheval.numero, "nom": h.cheval.nom,
                "cote": h.cheval.cote_matin,
                "pch_final": round(h.breakdown.pch_final, 2),
                "pch_norm": round(h.breakdown.pch_norm, 4),
                "composite": round(h.synthesis.composite, 4),
                "ordre_final": round(h.synthesis.ordre_final, 4),
                "tocard_score": round(h.breakdown.tocard_score, 3),
                "tranche": h.synthesis.tranche.value if h.synthesis.tranche else None,
                "ift": round(h.synthesis.ift, 1), "ift_label": h.synthesis.ift_label,
                "flags": list(dict.fromkeys(h.breakdown.flags + h.synthesis.flags)),
            }
            for h in result.horses
        ],
        "ticket": [t.model_dump() for t in result.ticket],
        "p_top5_in_ticket": result.p_top5_in_ticket,
        "masse_residuelle": result.masse_residuelle,
        "masse_residuelle_certifiee": (result.masse_residuelle is not None and result.masse_residuelle <= 0.15),
        "contraintes_dures": result.constraints_report,
        "validation_status": result.validation_status,
        "mention_obligatoire": (
            "Ce ticket est construit exclusivement sur des données pré-course collectées "
            "par recherche web. Aucun résultat officiel n'a été utilisé pour son élaboration."
        ),
    }


# ======================= v1.29.58 : tickets « champ réduit » 3 BASES + 5 COMPLÉMENTS, classés =======================
# Règle de paiement visée (pays de Golden, champ réduit « 3 bases + 5 compléments » = ticket de 8 chevaux) :
#   DÉSORDRE : les 3 bases font partie des 5 premiers de l'arrivée officielle ET les 2 autres places sont occupées par
#              2 compléments (donc 5 premiers = 3 bases + 2 compléments) ;
#   BONUS    : les 3 bases occupent les 3 premières places (dans n'importe quel ordre) ET au moins 1 complément
#              est 4e ou 5e ;
#   ORDRE    : base 1 = 1er, base 2 = 2e, base 3 = 3e, complément 1 = 4e, complément 2 = 5e.
# La sélection des 8 (tickets A, B, C) n'est PAS modifiée : on la réorganise (bases / compléments / classement).
# Les probabilités sont EXACTES (Plackett-Luce, poids = mélange marché/PCH), jamais simulées.
REGLE_BASES_COMPLEMENTS = ("3 bases classées + 5 compléments classés ; désordre = 3 bases + 2 compléments dans les 5 premiers ; "
                           "bonus = 3 bases aux places 1-3 + 1 complément 4e/5e ; ordre = B1,B2,B3,C1,C2 exacts")


def _seq_prob(w: List[float], total: float, seq: List[int]) -> float:
    """P(arrivée commence exactement par seq) sous Plackett-Luce."""
    p, rest = 1.0, total
    for i in seq:
        if rest <= 1e-15:
            return 0.0
        p *= w[i] / rest
        rest -= w[i]
    return p


def _probas_structure(w: List[float], total: float, bases: List[int], comps: List[int], sel: List[int],
                      dp5: Dict[int, float], dp3: Dict[int, float]) -> Dict[str, float]:
    """Probabilités exactes de désordre / bonus / ordre pour une structure (indices dans `horses`)."""
    n = len(w)
    tm = sum(1 << i for i in sel)
    sm = sum(1 << i for i in bases)
    p_des = sum(p for q, p in dp5.items() if (q & ~tm) == 0 and (q & sm) == sm)
    # bonus : P(top3 = bases) × P(4e ou 5e ∈ compléments | bases retirées)
    p3 = dp3.get(sm, 0.0)
    rest_w = total - sum(w[i] for i in bases)
    dehors = [i for i in range(n) if i not in sel]
    p_hors = 0.0
    if rest_w > 1e-15:
        for a in dehors:
            ra = rest_w - w[a]
            if ra <= 1e-15:
                continue
            for b in dehors:
                if b != a:
                    p_hors += (w[a] / rest_w) * (w[b] / ra)
    p_bonus = p3 * max(0.0, 1.0 - p_hors)
    seq = list(bases) + list(comps[:2])
    return {"desordre": p_des, "bonus": p_bonus, "ordre": _seq_prob(w, total, seq)}


def structurer_bases_complements(horses: List[HorseScore], selection: List[int], weights: List[float],
                                 nb_bases: int = 3, tol: float | None = None, bases_forcees: List[int] | None = None) -> Dict | None:
    """Réorganise un ticket de 8 en 3 BASES (classées 1-2-3) + 5 COMPLÉMENTS (classés ; C1 et C2 = 4e et 5e prévus).

    Choix des bases = triplet du ticket qui MAXIMISE P(désordre) (c'est le gain minimal visé) ; si plusieurs triplets sont à
    moins de `tol` (VANTAGE_BASES_TOL, défaut 0,002) du meilleur, on prend celui qui maximise P(bonus) puis P(ordre).
    Classement = ordre décroissant des poids Plackett-Luce (c'est le classement le plus probable sous le modèle)."""
    import os
    from itertools import combinations
    from app.engine.pl_inclusion import top_k_distribution
    sel = list(dict.fromkeys(selection))
    n = len(horses)
    if len(sel) < nb_bases + 2 or len(weights) != n or n < 6:
        return None
    tot = sum(weights)
    if tot <= 0:
        return None
    w = [max(1e-12, x / tot) for x in weights]
    total = sum(w)
    if tol is None:
        try:
            tol = float(os.environ.get("VANTAGE_BASES_TOL", "0.002"))
        except ValueError:
            tol = 0.002
    dp5 = top_k_distribution(w, 5)
    dp3 = top_k_distribution(w, nb_bases)
    tm = sum(1 << i for i in sel)
    p_top5_in = sum(p for q, p in dp5.items() if (q & ~tm) == 0)

    def _classer(idx: List[int]) -> List[int]:
        return sorted(idx, key=lambda i: (-w[i], i))

    bases_source = "plackett_luce"
    if bases_forcees and len(bases_forcees) == nb_bases and len(set(bases_forcees)) == nb_bases and set(bases_forcees) <= set(sel):
        # v1.29.69.1 : bases imposées (score propre, hors trot) — classées dans l'ordre fourni (B1 = plus petite cote)
        bases = list(bases_forcees)
        comps = _classer([i for i in sel if i not in bases])
        pr = _probas_structure(w, total, bases, comps, sel, dp5, dp3)
        bases_source = "score_propre"
    else:
        cands = []
        for trip in combinations(sel, nb_bases):
            bases = _classer(list(trip))
            comps = _classer([i for i in sel if i not in trip])
            pr = _probas_structure(w, total, bases, comps, sel, dp5, dp3)
            cands.append((bases, comps, pr))
        best_des = max(c[2]["desordre"] for c in cands)
        proches = [c for c in cands if c[2]["desordre"] >= best_des - tol]
        bases, comps, pr = max(proches, key=lambda c: (round(c[2]["bonus"], 6), c[2]["ordre"], c[2]["desordre"]))
    # référence « naïve » : les 3 plus fortes probabilités du ticket comme bases
    naive = _classer(sel)[:nb_bases]
    pr_naive = _probas_structure(w, total, naive, _classer([i for i in sel if i not in naive]), sel, dp5, dp3)

    def _fiche(i: int, rang: int, role: str) -> Dict:
        h = horses[i]
        ch = h.cheval
        return {"numero": getattr(ch, "numero", i + 1), "nom": getattr(ch, "nom", ""),
                "cote": getattr(ch, "cote_avant_course", None) or getattr(ch, "cote_matin", None),
                "tranche": (h.synthesis.tranche.value if h.synthesis.tranche else None),
                "rang_prevu": rang, "role": role, "poids_pl": round(w[i], 5)}

    fiches_b = [_fiche(i, r, f"B{r}") for r, i in enumerate(bases, 1)]
    fiches_c = [_fiche(i, nb_bases + r, f"C{r}") for r, i in enumerate(comps, 1)]
    return {
        "regle": REGLE_BASES_COMPLEMENTS,
        "bases": fiches_b,
        "complements": fiches_c,
        "ordre_prevu": [f["numero"] for f in fiches_b] + [f["numero"] for f in fiches_c[:2]],
        "probabilites_modele": {
            "desordre": round(pr["desordre"], 4), "bonus": round(pr["bonus"], 5), "ordre": round(pr["ordre"], 6),
            "top5_dans_ticket": round(p_top5_in, 4),
        },
        "reference_bases_par_probabilite": {k: round(v, 5) for k, v in pr_naive.items()},
        "gain_desordre_vs_reference": round(pr["desordre"] - pr_naive["desordre"], 5),
        "poids_source": "melange_marche_pch",
        "bases_source": bases_source,
    }


def evaluer_structure(structure: Dict | None, top5_numeros: List[int]) -> Dict | None:
    """Applique la règle de paiement à l'arrivée officielle (liste des numéros dans l'ordre d'arrivée)."""
    if not structure:
        return None
    bases = [b["numero"] for b in structure["bases"]]
    comps = [c["numero"] for c in structure["complements"]]
    sb, sc = set(bases), set(comps)
    top5 = [int(x) for x in list(top5_numeros)[:5]]
    if len(top5) < 5:
        return {"arrivee_incomplete": True, "desordre": False, "bonus": False, "ordre": False, "niveau_gain": None}
    s5 = set(top5)
    desordre = sb <= s5 and (s5 - sb) <= sc
    bonus = set(top5[:3]) == sb and any(x in sc for x in top5[3:5])
    ordre = top5 == bases + comps[:2]
    niveau = "ORDRE" if ordre else "BONUS" if bonus else "DESORDRE" if desordre else None
    return {
        "desordre": desordre, "bonus": bonus, "ordre": ordre, "niveau_gain": niveau,
        "nb_bases_dans_top5": len(sb & s5), "nb_bases_dans_top3": len(sb & set(top5[:3])),
        "nb_complements_dans_top5": len(sc & s5),
        "bases_manquees": sorted(sb - s5), "arrivee_hors_ticket": sorted(s5 - sb - sc),
        "ordre_prevu": structure.get("ordre_prevu"), "arrivee_top5": top5,
    }
