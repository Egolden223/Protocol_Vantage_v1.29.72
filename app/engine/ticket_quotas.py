"""ticket_quotas.py -- Tickets B et C (quotas par tranche de cotes).

v1.29.42  ticket B : règle utilisateur (8 chevaux, un par tranche, T1+T2 et T3+T4 dans [3,5]).
v1.29.55  probabilités = MÉLANGE MARCHÉ + PCH (Plackett-Luce) ; les bornes historiques restent une étape interne avant la sélection finale v1.29.70.
v1.29.57  FUSION des deux logiques du ticket B (v1.29.55 mélange marché/PCH + v1.29.56 grilles structurelles) :

  * les PROBABILITÉS viennent du mélange marché/PCH (validé hors échantillon, 52 courses) ;
  * les GRILLES de la v1.29.56 (discipline × signature IIC-v2) deviennent un A PRIORI SOUPLE : on énumère
    toutes les répartitions admissibles (T1+T2 et T3+T4 dans [3,5], au moins un cheval de chaque famille
    T1 / T2 / T3 / T4 quand elle existe) et on maximise
          Σ P(Top5)  −  λ · distance_L1(répartition, grille cible)
    donc la grille oriente le ticket sans jamais forcer un cheval peu probable quand le modèle est net ;
  * « T4 » = T4a + T4b réunis : on prend les meilleurs P(Top5) de l'ensemble T4 (plus de minimum par
    sous-tranche, qui coûtait ≈ 0,17 capture/course) ;
  * dégradation explicite : niveau 0 = tout respecté ; 1 = sans minimum par famille ; 2 = sans bornes 3-5.

Grilles cibles (T1, T2, T3, T4) :  3-2-2-1 défaut · 3-3-1-1 TROT/HAIES en LOCK/MIXTE_LOCK ·
2-3-2-1 PLAT/STEEPLE en CHAOS · 2-2-2-2 filet. λ = VANTAGE_GRID_LAMBDA (défaut 0 = a priori DÉSACTIVÉ (rejeu 55 courses : neutre ≤ 0,08, nuisible à 0,15) ; 0,08 = test prudent).

Ticket C (« ancré marché ») : probabilités d’ancrage conservées; depuis v1.29.70, la sélection finale applique aussi le minimum T1/T2/T3/T4 sans bornes [3,5].
Le sélecteur v1.29.70 est commun aux tickets A/B/C et intervient après les choix internes du builder.
Ticket A (protocole, GMO-V) conserve son score de base; sa sélection finale passe également par min1.
"""
from __future__ import annotations
import os
from itertools import product
from typing import Any, Dict, List, Sequence, Tuple

GROUPES = ("T1", "T2", "T3", "T4a", "T4b")
GAUCHE = ("T1", "T2")
DROITE = ("T3", "T4a", "T4b")

# Grilles cibles (T1, T2, T3, T4 = T4a+T4b)
GRID_3221 = (3, 2, 2, 1)
GRID_3311 = (3, 3, 1, 1)
GRID_2331 = (2, 3, 2, 1)   # PLAT/STEEPLE ouverts : T2 fort, somme 8
GRID_2222 = (2, 2, 2, 2)   # filet


def _cle(h) -> str | None:
    t = getattr(getattr(h, "synthesis", None), "tranche", None)
    if t is None:
        return None
    v = t.value if hasattr(t, "value") else str(t)
    v = {"T4A": "T4a", "T4B": "T4b"}.get(v, v)
    return v if v in GROUPES else None


def _cote_ref(h) -> float:
    c = getattr(getattr(h, "cheval", None), "cote_avant_course", None) or getattr(getattr(h, "cheval", None), "cote_matin", None)
    return float(c) if c and float(c) > 1.0 else 999.0


def blend_weights(horses: Sequence[Any], alpha: float | None = None, beta: float | None = None,
                  ajust_rang: Sequence[float] | None = None, alpha_t3: float | None = None) -> List[float]:
    """Poids Plackett-Luce w = exp(-β·(rang-1)) du MÉLANGE MARCHÉ + PCH (v1.29.58 : exposés pour structurer les tickets).
    Voir blend_probabilities pour la validation du mélange."""
    import math
    import os
    a = float(os.environ.get("VANTAGE_BLEND_ALPHA", "0.5")) if alpha is None else alpha
    b = float(os.environ.get("VANTAGE_BLEND_BETA", "0.2")) if beta is None else beta
    # v1.29.60 : α propre à T3 (part du rang marché). Défaut = α (aucun changement). Rejeu 55 courses : 0,8 → +0,11 capture
    # (8 courses meilleures / 3 pires, p = 0,23, positif dans les deux moitiés du corpus) = CANDIDAT, à valider sur un nouveau lot.
    try:
        a3 = float(os.environ.get("VANTAGE_BLEND_ALPHA_T3", a)) if alpha_t3 is None else float(alpha_t3)
    except ValueError:
        a3 = a
    n = len(horses)
    order_m = sorted(range(n), key=lambda i: (_cote_ref(horses[i]), i))
    rank_m = [0] * n
    for pos, i in enumerate(order_m, 1):
        rank_m[i] = pos

    def _pch(h):
        bd = getattr(h, "breakdown", None)
        v = getattr(bd, "pch_final", None) if bd is not None else None
        return float(v) if v is not None else float("-inf")
    order_p = sorted(range(n), key=lambda i: (-_pch(horses[i]), rank_m[i]))
    rank_p = [0] * n
    for pos, i in enumerate(order_p, 1):
        rank_p[i] = pos
    score = [((a3 if _cle(horses[i]) == "T3" else a) * rank_m[i]) + ((1 - (a3 if _cle(horses[i]) == "T3" else a)) * rank_p[i]) for i in range(n)]
    if ajust_rang is not None:          # v1.29.64 : ajustement DIRECT du score de classement (en rangs ; positif = meilleur) — ticket B / renforcement GRU
        score = [score[i] - float(ajust_rang[i]) for i in range(n)]
    order = sorted(range(n), key=lambda i: (score[i], rank_m[i]))
    rank = [0] * n
    for pos, i in enumerate(order, 1):
        rank[i] = pos
    return [math.exp(-b * (rank[i] - 1)) for i in range(n)]


def blend_probabilities(horses: Sequence[Any], alpha: float | None = None, beta: float | None = None) -> List[float]:
    """P(cheval ∈ Top 5) par MÉLANGE MARCHÉ + PCH (v1.29.55).

    Étude hors échantillon sur 52 courses (export du 24/10/2026) : le rang moyen « 50 % marché / 50 % PCH » capte 4,04 chevaux
    du Top 5 dans un ticket de 8, contre 3,44 pour le ticket A (protocole), 3,79 pour les 8 plus petites cotes et 3,54 pour le
    PCH seul ; α = 0,5 retenu dans les 4 blocs de validation croisée. Le PCH est plus informatif que l'ordre_final (AUC 0,70 vs
    0,68 ; bande de rang marché 4-12 : 0,65 vs 0,59) que les multiplicateurs de synthèse dégradent.
    Les rangs deviennent des probabilités par un modèle de Plackett-Luce exact, w = exp(-β·(rang-1)) ; β = 0,2 minimise le Brier ;
    calibration vérifiée : probabilité moyenne 0,15 / observé 0,17, 0,36 / 0,39, 0,65 / 0,56, 0,74 / 0,81 (par tranche de π).
    Réglages : VANTAGE_BLEND_ALPHA (poids du marché) et VANTAGE_BLEND_BETA."""
    from app.engine.pl_inclusion import inclusion_probs
    return inclusion_probs(blend_weights(horses, alpha, beta))


def _disc_bucket(discipline: Any) -> str:
    d = discipline.value if hasattr(discipline, "value") else str(discipline or "")
    d = d.upper()
    if "TROT" in d or "ATTEL" in d or "MONTE" in d:
        return "TROT"
    if "STEEPLE" in d:
        return "STEEPLE"
    if "HAIES" in d or "OBST" in d or "CROSS" in d:
        return "HAIES"
    return "PLAT"


def _sig_name(signature: Any) -> str:
    if signature is None:
        return "STANDARD"
    return signature.value if hasattr(signature, "value") else str(signature)


def target_quotas(discipline: Any, signature: Any) -> Tuple[int, int, int, int]:
    """Grille cible (T1, T2, T3, T4) selon discipline × signature (v1.29.56)."""
    disc = _disc_bucket(discipline)
    sig = _sig_name(signature)
    if sig in ("LOCK", "MIXTE_LOCK") and disc in ("TROT", "HAIES"):
        return GRID_3311
    if sig == "CHAOS" and disc in ("PLAT", "STEEPLE"):
        return GRID_2331
    return GRID_3221


def _lambda_grille() -> float:
    try:
        return max(0.0, float(os.environ.get("VANTAGE_GRID_LAMBDA", "0.0")))
    except ValueError:
        return 0.0


def _build_ticket_quotas_core(horses: Sequence[Any], pi: Sequence[float], size: int = 8,
                        qmin: int = 3, qmax: int = 5, un_par_tranche: bool = True,
                        discipline: Any = None, signature: Any = None, grille: bool = False,
                        lam: float | None = None) -> Dict[str, Any]:
    """Ticket B/C. grille=True : a priori souple « grille discipline × signature » (v1.29.57), voir l'en-tête du module."""
    if grille:
        return _build_grille(horses, pi, size, qmin, qmax, discipline, signature, lam)
    n = len(horses)
    size = min(size, n)
    groupes: Dict[str, List[int]] = {g: [] for g in GROUPES}
    for i, h in enumerate(horses):
        k = _cle(h)
        if k:
            groupes[k].append(i)
    for g in GROUPES:
        groupes[g].sort(key=lambda i: (-pi[i], i))
    cum = {g: [0.0] for g in GROUPES}
    for g in GROUPES:
        for i in groupes[g]:
            cum[g].append(cum[g][-1] + pi[i])
    dispo = {g: len(groupes[g]) for g in GROUPES}

    def chercher(un_par_tranche: bool):
        best, best_score = None, -1.0
        rangs = [range(0, min(dispo[g], size) + 1) for g in GROUPES]
        for c in product(*rangs):
            if sum(c) != size:
                continue
            cd = dict(zip(GROUPES, c))
            gauche = sum(cd[g] for g in GAUCHE)
            droite = sum(cd[g] for g in DROITE)
            if not (qmin <= gauche <= qmax and qmin <= droite <= qmax):
                continue
            if un_par_tranche and any(dispo[g] > 0 and cd[g] < 1 for g in GROUPES):
                continue
            score = sum(cum[g][cd[g]] for g in GROUPES)
            if score > best_score + 1e-12:
                best, best_score = cd, score
        return best

    flags: List[str] = []
    niveau = 0
    comp = chercher(True) if un_par_tranche else None
    if comp is None and un_par_tranche:
        niveau = 1
        flags.append("QUOTA_B_UN_PAR_TRANCHE_IMPOSSIBLE")
        comp = chercher(False)
    elif comp is None:                      # ticket C : pas de minimum par tranche, seulement T1+T2 et T3+T4 dans [3,5]
        comp = chercher(False)
    if comp is None:
        niveau = 2
        flags.append("QUOTA_B_BORNES_3_5_IMPOSSIBLES")
        sel = sorted(range(n), key=lambda i: (-pi[i], i))[:size]
        comp = {g: sum(1 for i in sel if i in groupes[g]) for g in GROUPES}
    else:
        sel = []
        for g in GROUPES:
            sel.extend(groupes[g][:comp[g]])
    sel = sorted(sel, key=lambda i: (-pi[i], i))
    return {
        "selection": sel,
        "composition": {g: comp[g] for g in GROUPES},
        "t1_t2": sum(comp[g] for g in GAUCHE),
        "t3_t4": sum(comp[g] for g in DROITE),
        "tranches_disponibles": dispo,
        "captures_attendues_modele": round(sum(pi[i] for i in sel), 3),
        "niveau_relaxation": niveau,
        "flags": flags,
    }


def _build_grille(horses: Sequence[Any], pi: Sequence[float], size: int, qmin: int, qmax: int,
                  discipline: Any, signature: Any, lam: float | None) -> Dict[str, Any]:
    """Ticket B v1.29.57 : mélange marché/PCH (pi) + grille structurelle comme a priori souple."""
    n = len(horses)
    size = min(size, n)
    lam = _lambda_grille() if lam is None else max(0.0, float(lam))
    groupes: Dict[str, List[int]] = {g: [] for g in GROUPES}
    for i, h in enumerate(horses):
        k = _cle(h)
        if k:
            groupes[k].append(i)
    for g in GROUPES:
        groupes[g].sort(key=lambda i: (-pi[i], i))
    cum = {g: [0.0] for g in GROUPES}
    for g in GROUPES:
        for i in groupes[g]:
            cum[g].append(cum[g][-1] + pi[i])
    dispo = {g: len(groupes[g]) for g in GROUPES}
    dispo4 = (dispo["T1"], dispo["T2"], dispo["T3"], dispo["T4a"] + dispo["T4b"])
    target = target_quotas(discipline, signature)

    # T4 = T4a ∪ T4b : l'énumération des 5 comptes (c_T4a, c_T4b) retient le meilleur cumul de P(Top5)
    # de l'ensemble T4, sans minimum par sous-tranche.

    def _c4(cd: Dict[str, int]) -> Tuple[int, int, int, int]:
        return (cd["T1"], cd["T2"], cd["T3"], cd["T4a"] + cd["T4b"])

    def chercher(familles: bool, bornes: bool):
        best, best_val, best_pur, best_pur_val = None, -1e18, None, -1.0
        rangs = [range(0, min(dispo[g], size) + 1) for g in GROUPES]
        for c in product(*rangs):
            if sum(c) != size:
                continue
            cd = dict(zip(GROUPES, c))
            c4 = _c4(cd)
            if bornes:
                gauche, droite = c4[0] + c4[1], c4[2] + c4[3]
                if not (qmin <= gauche <= qmax and qmin <= droite <= qmax):
                    continue
            if familles and any(dispo4[k] > 0 and c4[k] < 1 for k in range(4)):
                continue
            pur = sum(cum[g][cd[g]] for g in GROUPES)
            dist = sum(abs(c4[k] - target[k]) for k in range(4))
            val = pur - lam * dist
            if val > best_val + 1e-12:
                best, best_val = cd, val
            if pur > best_pur_val + 1e-12:
                best_pur, best_pur_val = cd, pur
        return best, best_pur

    flags: List[str] = []
    niveau = 0
    comp, comp_pur = chercher(True, True)
    if comp is None:
        niveau = 1
        flags.append("QUOTA_B_UNE_PAR_FAMILLE_IMPOSSIBLE")
        comp, comp_pur = chercher(False, True)
    if comp is None:
        niveau = 2
        flags.append("QUOTA_B_BORNES_3_5_IMPOSSIBLES")
        sel = sorted(range(n), key=lambda i: (-pi[i], i))[:size]
        comp = {g: sum(1 for i in sel if i in groupes[g]) for g in GROUPES}
        comp_pur = dict(comp)
    else:
        sel = []
        for g in GROUPES:
            sel.extend(groupes[g][:comp[g]])
    sel = sorted(sel, key=lambda i: (-pi[i], i))
    c4 = _c4(comp)
    pur_sel = sum(pi[i] for i in sel)
    pur_best = sum(cum[g][comp_pur[g]] for g in GROUPES) if comp_pur else pur_sel
    return {
        "selection": sel,
        "composition": {g: comp[g] for g in GROUPES},
        "target_grid": list(target),
        "applied_grid": list(c4),
        "grid_mode": "prior_souple_melange_marche_pch",
        "grid_lambda": lam,
        "grid_actif": lam > 0,
        "ecart_grille": sum(abs(c4[k] - target[k]) for k in range(4)),
        "t1_t2": c4[0] + c4[1],
        "t3_t4": c4[2] + c4[3],
        "tranches_disponibles": dispo,
        "captures_attendues_modele": round(pur_sel, 3),
        "captures_attendues_sans_grille": round(pur_best, 3),   # optimum du modèle sans a priori : mesure ce que coûte la grille
        "niveau_relaxation": niveau,
        "flags": flags,
        "discipline_bucket": _disc_bucket(discipline),
        "signature": _sig_name(signature),
    }


# ======================= v1.29.61 : classement PROPRE À CHAQUE TRANCHE (candidat, désactivé par défaut) =======================
# Rejeu 55 courses, à nombre de places par tranche FIXÉ (les quotas ne changent pas, seul le choix des chevaux dans la tranche) :
#   T3 : marché seul (cote croissante) → 54 → 60 arrivées captées ; le PCH n'y sépare pas arrivées / non-arrivées (AUC 0,48) ;
#   T4 : rang moyen PCH + ordre_final + valeur PMU → 12 → 15 ; le marché n'y sépare pas (AUC 0,55) ;
#   T1, T2 : aucun classement alternatif ne fait mieux que le mélange actuel (inchangés).
# Combiné : +9 arrivées / 55 courses (+0,16 capture), 12 courses meilleures / 3 pires, p = 0,04, +0,15 puis +0,18 selon la moitié du
# corpus. RÈGLES CHOISIES SUR CE MÊME CORPUS → à valider sur un nouveau lot avant de les rendre défaut (VANTAGE_RERANK_TRANCHE=1).

def _rerank_actif(rerank: bool | None) -> bool:
    if rerank is not None:
        return bool(rerank)
    return os.environ.get("VANTAGE_RERANK_TRANCHE", "0").strip().lower() in ("1", "true", "oui", "on")


def _val_ordre_final(h: Any) -> float | None:
    v = getattr(getattr(h, "synthesis", None), "ordre_final", None)
    return float(v) if v is not None else (float(h.ordre_final) if getattr(h, "ordre_final", None) is not None else None)


def _val_pch(h: Any) -> float | None:
    v = getattr(getattr(h, "breakdown", None), "pch_final", None)
    return float(v) if v is not None else None


def _val_valeur_pmu(h: Any) -> float | None:
    v = getattr(getattr(h, "cheval", None), "valeur_pmu", None)
    return float(v) if v is not None else None


def _rangs_moyens(vals: List[float | None], haut_est_bon: bool = True) -> List[float]:
    """Rang moyen (1 = meilleur), ex æquo en rang moyen, valeurs absentes classées en dernier."""
    n = len(vals)
    cle = [(-v if haut_est_bon else v) if v is not None else float("inf") for v in vals]
    ordre = sorted(range(n), key=lambda i: (cle[i], i))
    rang = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and cle[ordre[j + 1]] == cle[ordre[i]]:
            j += 1
        for t in range(i, j + 1):
            rang[ordre[t]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return rang


def rerank_par_tranche(horses: Sequence[Any], selection: Sequence[int]) -> Dict[str, Any]:
    """Re-choisit, SANS CHANGER le nombre de chevaux par tranche, les T3 (marché) et les T4 (PCH + ordre_final + valeur PMU)."""
    sel = list(selection)
    groupes = {i: _cle(horses[i]) for i in range(len(horses))}
    nouveau = list(sel)
    info: Dict[str, Any] = {"T3": None, "T4": None}
    # --- T3 : marché seul ---
    pool3 = [i for i in range(len(horses)) if groupes[i] == "T3"]
    k3 = sum(1 for i in sel if groupes[i] == "T3")
    if pool3 and k3:
        choix = sorted(pool3, key=lambda i: (_cote_ref(horses[i]), i))[:k3]
        nouveau = [i for i in nouveau if groupes[i] != "T3"] + choix
        info["T3"] = {"places": k3, "critere": "marché", "modifie": set(choix) != {i for i in sel if groupes[i] == "T3"}}
    # --- T4 (a+b) : rang moyen PCH + ordre_final + valeur PMU (signaux disponibles uniquement) ---
    pool4 = [i for i in range(len(horses)) if groupes[i] in ("T4a", "T4b")]
    k4 = sum(1 for i in sel if groupes[i] in ("T4a", "T4b"))
    if pool4 and k4:
        series = [(n, [f(horses[i]) for i in pool4]) for n, f in (("PCH", _val_pch), ("ordre_final", _val_ordre_final), ("valeur_pmu", _val_valeur_pmu))]
        dispo = [(n, v) for n, v in series if any(x is not None for x in v)]
        if dispo:
            rangs = [_rangs_moyens(v) for _, v in dispo]
            score = [sum(r[t] for r in rangs) for t in range(len(pool4))]
            choix = [pool4[t] for t in sorted(range(len(pool4)), key=lambda t: (score[t], pool4[t]))[:k4]]
            nouveau = [i for i in nouveau if groupes[i] not in ("T4a", "T4b")] + choix
            info["T4"] = {"places": k4, "critere": "+".join(n for n, _ in dispo),
                          "modifie": set(choix) != {i for i in sel if groupes[i] in ("T4a", "T4b")}}
    return {"selection": nouveau, "info": info}


def build_ticket_quotas(horses: Sequence[Any], pi: Sequence[float], size: int = 8,
                        qmin: int = 3, qmax: int = 5, un_par_tranche: bool = True,
                        discipline: Any = None, signature: Any = None, grille: bool = False,
                        lam: float | None = None, rerank: bool | None = None) -> Dict[str, Any]:
    """Ticket B/C (voir _build_ticket_quotas_core). rerank=True (ou VANTAGE_RERANK_TRANCHE=1) : classement propre à T3 et T4."""
    res = _build_ticket_quotas_core(horses, pi, size, qmin, qmax, un_par_tranche, discipline, signature, grille, lam)
    if not _rerank_actif(rerank):
        return res
    rr = rerank_par_tranche(horses, res["selection"])
    sel = sorted(rr["selection"], key=lambda i: (-pi[i], i))
    res["selection_avant_rerank"] = res["selection"]
    res["selection"] = sel
    comp = {g: 0 for g in GROUPES}
    for i in sel:
        g = _cle(horses[i])
        if g in comp:
            comp[g] += 1
    res["composition"] = comp
    res["captures_attendues_modele"] = round(sum(pi[i] for i in sel), 3)
    res["rerank_tranche"] = {"actif": True, **rr["info"]}
    return res


def entrees_pepite(horses: Sequence[Any], selection: Sequence[int], pi: Sequence[float], pepites: Sequence[float],
                   max_entrees: int = 1, seuil: float = 8.0) -> Dict[str, Any]:
    """Droit d'entrée « pépite » du ticket B (équivalent, pour B, de l'entrée de pool de GMO-V) : jusqu'à `max_entrees` outsiders (cote ≥ 12) au score
    de pépite maximal (≥ `seuil`) remplacent, DANS LA MÊME MOITIÉ (T3/T4), le retenu le moins probable qui n'est pas lui-même une pépite maximale :
    les bornes T1+T2 / T3+T4 et le nombre de chevaux restent inchangés. Rejeu 55 courses : −0,02 de capture, 21 tickets sur 55 modifiés."""
    sel = list(selection)
    droite = ("T3", "T4a", "T4b")
    cands = [i for i in range(len(horses)) if i not in sel and _cote_ref(horses[i]) >= 12.0 and float(pepites[i] or 0.0) >= seuil]
    cands.sort(key=lambda i: (-float(pepites[i]), -pi[i], i))
    entrees: List[int] = []
    for i in cands[:max(0, int(max_entrees))]:
        pool = [j for j in sel if _cle(horses[j]) in droite and float(pepites[j] or 0.0) < seuil]
        if not pool:
            break
        v = min(pool, key=lambda j: (pi[j], j))
        sel[sel.index(v)] = i
        entrees.append(i)
    return {"selection": sorted(sel, key=lambda i: (-pi[i], i)), "entrees": entrees}


# ======================================================================================================================
# v1.29.68 — RECALIBRAGE : sélection par tranche conservée en shadow; plafond outsider activé en v1.29.69
#
# Constat (160 courses, walk-forward chronologique, 96 courses de test) : à répartition par tranche inchangée, changer le profil
# choisi dans chaque tranche ne rapporte presque rien (+0,06 à +0,22 hors trot) ; en gardant AU MOINS UN cheval par tranche et en
# choisissant librement le reste par z(ordre_final) + λ·z(−log cote) (λ = 1, aucun paramètre ajusté), les 8 chevaux captent
# +0,33 (A) et +0,49 (B) de plus que les tickets actuels ; C inchangé (+0,04).
# v1.29.70 : la sélection min1 est active par défaut pour A, B et C; un override non vide peut restreindre les tickets concernés.
# Les mesures comparatives restent publiées dans json_output["shadow_v1_29_68"].
#   VANTAGE_SELECT_MIN1_TICKETS = "B" | "A,B" | "A,B,C"   (défaut actif A,B,C) : tickets soumis à min1 + mélange ordre/cote
#   VANTAGE_CAP_OUTSIDERS       = "A:2,B:2"               (défaut v1.29.69 actif)  : plafond de chevaux de rang marché ≥ 9
#   VANTAGE_MIN1_LAMBDA         = 1.0                                    : poids de la cote dans le mélange
# Règle v1.29.70 : chaque ticket A/B/C a au moins un cheval en T1, T2, T3 et T4=T4a∪T4b, si le groupe existe.
# Les anciennes bornes [3,5] / [5,3] entre T1+T2 et T3+T4 ne sont plus appliquées à la sélection finale.
# ======================================================================================================================
TRANCHES_REQUISES = {"A": ("T1", "T2", "T3", "T4"), "B": ("T1", "T2", "T3", "T4"), "C": ("T1", "T2", "T3", "T4")}   # v1.29.70 (Grok) : T4 = T4a ∪ T4b ; A, B et C
RANG_OUTSIDER = 9
_GAUCHE_V68 = frozenset(("T1", "T2"))
_DROITE_V68 = frozenset(("T3", "T4a", "T4b"))


def _liste_env(nom: str, defaut: str = "") -> List[str]:
    """Liste lue dans l'environnement ; variable absente → `defaut` ; « none / off / 0 » → liste vide (désactivé)."""
    brut = os.environ.get(nom)
    if brut is None or not brut.strip():
        brut = defaut
    if brut.strip().upper() in ("NONE", "OFF", "NON", "0", "-"):
        return []
    return [x.strip().upper() for x in brut.replace(";", ",").split(",") if x.strip()]


def tickets_selection_min1() -> List[str]:
    """A/B/C : au moins un cheval en T1, T2, T3 et T4 (T4a et T4b regroupées). Défaut actif : les trois tickets (v1.29.70).
    VANTAGE_SELECT_MIN1_TICKETS : vide ou absent = A,B,C ; « none / off » = désactivé ; « A,B » = restreint."""
    return [t for t in _liste_env("VANTAGE_SELECT_MIN1_TICKETS", "A,B,C") if t in TRANCHES_REQUISES]


def plafonds_outsiders() -> Dict[str, int]:
    """VANTAGE_CAP_OUTSIDERS="A:2,B:2" → {"A": 2, "B": 2} (défaut actif A:2,B:2, C inchangé ; « none » désactive)."""
    out: Dict[str, int] = {}
    for part in _liste_env("VANTAGE_CAP_OUTSIDERS", "A:2,B:2"):
        if ":" in part:
            t, v = part.split(":", 1)
            try:
                if t in TRANCHES_REQUISES and int(v) >= 0:
                    out[t] = int(v)
            except ValueError:
                continue
    return out


def _lambda_min1() -> float:
    try:
        return float(os.environ.get("VANTAGE_MIN1_LAMBDA", "1.0"))
    except ValueError:
        return 1.0


def _z(vals: Sequence[float | None]) -> List[float]:
    xs = [v for v in vals if v is not None]
    if len(xs) < 2:
        return [0.0] * len(vals)
    m = sum(xs) / len(xs)
    sd = (sum((v - m) ** 2 for v in xs) / len(xs)) ** 0.5
    if sd <= 1e-12:
        return [0.0] * len(vals)
    return [0.0 if v is None else (v - m) / sd for v in vals]


def scores_melange(horses: Sequence[Any], lam: float | None = None) -> List[float]:
    """z(ordre_final) + λ · z(−log cote) calculés dans la course (aucun paramètre ajusté ; λ = 1 par défaut)."""
    import math
    lam = _lambda_min1() if lam is None else lam
    z_o = _z([_val_ordre_final(h) for h in horses])
    z_c = _z([-math.log(max(_cote_ref(h), 1.01)) if _cote_ref(h) < 999.0 else None for h in horses])
    return [a + lam * b for a, b in zip(z_o, z_c)]


def _cte(sel: Sequence[int], tr: Sequence[str | None], groupe) -> int:
    return sum(1 for i in sel if tr[i] in groupe)


def _groupe_min1(tranche: str | None) -> str | None:
    """Regroupe T4a et T4b sous le seul quota min1 T4."""
    t = str(tranche or "").upper()
    return "T4" if t in ("T4A", "T4B", "T4") else (t or None)


def _retirable(i: int, sel: Sequence[int], tr: Sequence[str | None], requises: Sequence[str]) -> bool:
    groupe = _groupe_min1(tr[i])
    return groupe not in requises or sum(1 for j in sel if _groupe_min1(tr[j]) == groupe) > 1


def _reparer_bornes(sel: List[int], scores: Sequence[float], tr: Sequence[str | None], requises: Sequence[str],
                    qmin: int, qmax: int) -> List[int]:
    """Ramène T1+T2 et T3+T4 dans [qmin, qmax] par échanges de moindre perte de score, sans casser « un par tranche »."""
    n = len(scores)
    for _ in range(2 * len(sel) + 2):
        nl, nr = _cte(sel, tr, _GAUCHE_V68), _cte(sel, tr, _DROITE_V68)
        if nl > qmax:
            sortir, entrer = _GAUCHE_V68, _DROITE_V68
        elif nr > qmax:
            sortir, entrer = _DROITE_V68, _GAUCHE_V68
        elif nl < qmin:
            sortir, entrer = _DROITE_V68, _GAUCHE_V68
        elif nr < qmin:
            sortir, entrer = _GAUCHE_V68, _DROITE_V68
        else:
            break
        sortants = sorted((i for i in sel if tr[i] in sortir and _retirable(i, sel, tr, requises)), key=lambda i: (scores[i], -i))
        entrants = sorted((i for i in range(n) if i not in sel and tr[i] in entrer), key=lambda i: (-scores[i], i))
        if not sortants or not entrants:
            break
        sel = [i for i in sel if i != sortants[0]] + [entrants[0]]
    return sel


def choisir_min1(scores: Sequence[float], tr: Sequence[str | None], requises: Sequence[str], size: int = 8,
                 bornes: Tuple[int, int] | None = None) -> List[int]:
    """Meilleur cheval de chaque groupe requis (T4a/b réunis en T4), puis meilleurs scores restants; bornes optionnelles pour compatibilité."""
    n = len(scores)
    ordre = sorted(range(n), key=lambda i: (-scores[i], i))
    if n <= size:
        return sorted(range(n))
    sel: List[int] = []
    for t in requises:
        for i in ordre:
            if _groupe_min1(tr[i]) == _groupe_min1(t):
                sel.append(i)
                break
    for i in ordre:
        if len(sel) >= size:
            break
        if i not in sel:
            sel.append(i)
    if bornes:
        sel = _reparer_bornes(sel, scores, tr, requises, bornes[0], bornes[1])
    return sorted(sel, key=lambda i: (-scores[i], i))


def plafonner_outsiders(sel: Sequence[int], scores: Sequence[float], tr: Sequence[str | None], rangs_marche: Sequence[int],
                        cap: int, requises: Sequence[str], bornes: Tuple[int, int] | None = None) -> List[int]:
    """Au plus `cap` chevaux de rang marché ≥ 9 ; remplaçants = meilleurs scores de rang < 9, en respectant « un par tranche » et les bornes."""
    sel = list(sel)
    n = len(scores)
    for _ in range(len(sel)):
        outs = [i for i in sel if rangs_marche[i] >= RANG_OUTSIDER]
        if len(outs) <= cap:
            break
        fait = False
        for sortant in sorted(outs, key=lambda i: (scores[i], -i)):
            if not _retirable(sortant, sel, tr, requises):
                continue
            for entrant in sorted((i for i in range(n) if i not in sel and rangs_marche[i] < RANG_OUTSIDER), key=lambda i: (-scores[i], i)):
                cand = [i for i in sel if i != sortant] + [entrant]
                if bornes and not (bornes[0] <= _cte(cand, tr, _GAUCHE_V68) <= bornes[1] and bornes[0] <= _cte(cand, tr, _DROITE_V68) <= bornes[1]):
                    continue
                sel, fait = cand, True
                break
            if fait:
                break
        if not fait:
            break
    return sorted(sel, key=lambda i: (-scores[i], i))


def _rangs_marche(horses: Sequence[Any]) -> List[int]:
    ordre = sorted(range(len(horses)), key=lambda i: (_cote_ref(horses[i]), i))
    r = [0] * len(horses)
    for k, i in enumerate(ordre, start=1):
        r[i] = k
    return r


def appliquer_v68(horses: Sequence[Any], ticket: str, selection: Sequence[int], size: int = 8) -> Dict[str, Any]:
    """Calcule la comparaison shadow et applique min1 T1/T2/T3/T4 (T4a/b fusionnées) sans bornes 3–5.
    Ne lève jamais : en cas d'anomalie la sélection actuelle est renvoyée inchangée."""
    sel0 = list(selection)
    base = {"selection": sel0, "origine": "live", "appliquee": False, "shadow_min1_melange": None, "shadow_plafond2": None,
            "shadow_garde_t1": None, "erreur": None}
    try:
        t = ticket.upper()
        requises = TRANCHES_REQUISES[t]
        bornes = None  # v1.29.70 : plus de quota 3–5 / 5–3 sur les tickets finaux
        sc = scores_melange(horses)
        tr = [_cle(h) for h in horses]
        rg = _rangs_marche(horses)
        sh = choisir_min1(sc, tr, requises, size, bornes)
        base["shadow_min1_melange"] = sh
        if t in ("A", "B"):
            base["shadow_plafond2"] = plafonner_outsiders(sel0, sc, tr, rg, 2, requises, bornes)
        if t == "A":
            base["shadow_garde_t1"] = garder_t1(sel0, sc, tr, rg, 3, requises, bornes)
        sel, origine = sel0, "live"
        if t in tickets_selection_min1():
            sel, origine = list(sh), "min1_melange"
        if t in _liste_env("VANTAGE_GARDE_T1", "A") and origine == "live":   # garde T1 : repli quand la sélection n'est pas appliquée (redondante sinon : −0,02)
            sel_g = garder_t1(sel, sc, tr, rg, 3, requises, bornes)
            if set(sel_g) != set(sel):
                sel, origine = sel_g, origine + "+garde_t1"
        cap = plafonds_outsiders().get(t)
        if cap is not None:
            sel2 = plafonner_outsiders(sel, sc, tr, rg, cap, requises, bornes)
            if set(sel2) != set(sel):
                sel, origine = sel2, origine + "+plafond"
        if len(set(sel)) != len(sel0) or any(i < 0 or i >= len(horses) for i in sel):
            return base                      # garde-fou : taille ou indices incohérents → on garde le ticket actuel
        base.update({"selection": list(sel), "origine": origine, "appliquee": set(sel) != set(sel0)})
    except Exception as e:                    # noqa: BLE001  (le recalibrage ne doit jamais faire échouer un ticket)
        base["erreur"] = str(e)[:120]
    return base


# ======================================================================================================================
# v1.29.69 — SHADOW : bases choisies par un « score propre » figé, probabilités recalibrées, filtre de courses, garde T1
# (tout est PUBLIÉ dans json_output["shadow_v1_29_69"] ; rien ne modifie les tickets réels, sauf VANTAGE_GARDE_T1 pour A)
#
# Constat (audits, 106 courses par ticket, walk-forward) : hors trot, la part des bases présentes dans le top 5 passe de 0,53 (bases
# actuelles, Plackett-Luce marché/PCH) à 0,65–0,69 avec un score propre ; désordre à 3 bases 2,6 % → 8,3 % (60 tickets-courses).
# En trot, les bases actuelles bénéficient de la fuite de la valeur PMU : comparaison non fiable avant correction as-of.
# Les coefficients ci-dessous sont ajustés sur les 160 courses du 11/11/2026 (régression logistique régularisée, z-scores dans la course) ;
# ils sont figés : le score est à re-mesurer sur les prochains lots via les colonnes captures_shadow_* / shadow_bases_*.
# ======================================================================================================================
SCORE_PROPRE_COEF = {"TROT": {"c_lcote": 0.8434, "x_forme": 0.0892, "x_stab": 0.0155, "x_tact": -0.0184, "x_iff": 0.1153, "m_pos5": -0.4124, "m_top3_5": -0.0772, "m_dq5": -0.1158, "m_win5": -0.1201, "m_pos10": -0.2328, "m_top3_10": -0.1887, "c_lgm": -0.0212, "c_vict_rate": 0.0291, "c_age": -0.1523}, "NONTROT": {"c_lcote": 0.4397, "x_forme": 0.5354, "x_stab": 0.1859, "x_tact": -0.0671, "x_iff": 0.0408, "m_pos5": -0.4274, "m_top3_5": -0.2729, "m_dq5": 0.0, "m_win5": -0.1843, "m_pos10": -0.0311, "m_top3_10": 0.0222, "c_lgm": 0.1019, "c_vict_rate": 0.0296, "c_age": 0.0661}}  # m_dq5 hors trot neutralisé (coefficient ajusté +0,41 sur 89 chevaux d’obstacle : artefact ; effet nul sur les mesures)
SCORE_PROPRE_DATE = "2026-11-13"
# facteurs observé/prédit des probabilités publiées (audits, 106 courses ; bornés [0,5 ; 2,0]) — appliqués à moitié (retrait vers 1)
FACTEURS_CALIBRAGE = {"A": {"desordre": 1.63, "top5_dans_ticket": 1.57}, "B": {"desordre": 1.12, "top5_dans_ticket": 0.81}, "C": {"desordre": 0.86, "top5_dans_ticket": 0.83}}
SEUIL_FAVORI_DEFAUT = 4.0       # 5/5 : 21–22 % quand la cote du favori est <= 4 (76 courses) contre 8 % au-delà (84 courses)


def _musique_feats(m, n: int):
    import re
    if not isinstance(m, str):
        return (None, None, None, None)
    toks = re.findall(r"([0-9]|D|A|T|R)([a-z])", re.sub(r"\(\d+\)", "", m))[:n]
    if not toks:
        return (None, None, None, None)
    pos = [(10 if t[0] == "0" else int(t[0])) for t in toks if t[0].isdigit()]
    return ((sum(pos) / len(pos)) if pos else None, (sum(1 for x in pos if x <= 3) / len(pos)) if pos else None,
            sum(1 for t in toks if t[0] in "DAT") / len(toks), sum(1 for t in toks if t[0] == "1") / len(toks))


def _z1(vals):
    """z-score intra-course (ddof=1, comme à l'ajustement) ; valeurs absentes → 0."""
    xs = [v for v in vals if v is not None]
    if len(xs) < 2:
        return [0.0] * len(vals)
    m = sum(xs) / len(xs)
    sd = (sum((v - m) ** 2 for v in xs) / (len(xs) - 1)) ** 0.5
    if sd <= 1e-12:
        return [0.0] * len(vals)
    return [0.0 if v is None else (v - m) / sd for v in vals]


def score_propre(horses: Sequence[Any], discipline: Any = None) -> List[float]:
    """Score propre figé (sans valeur_pmu, donc sans fuite) : cote, forme, stabilité, tactique, IFF, musique 5/10 courses, gains, victoires, âge."""
    import math
    from app.engine.common import disc_bucket
    coefs = SCORE_PROPRE_COEF["TROT" if disc_bucket(discipline) == "TROT" else "NONTROT"]
    cols = {k: [] for k in coefs}
    for h in horses:
        ch, bd = h.cheval, h.breakdown
        c = _cote_ref(h)
        cols["c_lcote"].append(-math.log(max(c, 1.01)) if c < 999.0 else None)
        cols["x_forme"].append(getattr(bd, "forme_lineaire_pch", None))
        cols["x_stab"].append(getattr(bd, "stab_pch", None))
        cols["x_tact"].append(getattr(bd, "tact_pch", None))
        cols["x_iff"].append(getattr(bd, "iff_v2", None))
        p5, t35, d5, w5 = _musique_feats(getattr(ch, "musique", None), 5)
        p10, t310, _d10, _w10 = _musique_feats(getattr(ch, "musique", None), 10)
        cols["m_pos5"].append(p5); cols["m_top3_5"].append(t35); cols["m_dq5"].append(d5); cols["m_win5"].append(w5)
        cols["m_pos10"].append(p10); cols["m_top3_10"].append(t310)
        g = getattr(ch, "gains_moyenne_carriere_eur", None)
        cols["c_lgm"].append(math.log1p(g) if (g is not None and g >= 0) else None)
        v, n = getattr(ch, "victoires_carriere", None), getattr(ch, "nb_courses", None)
        cols["c_vict_rate"].append((v / max(n, 1)) if (v is not None and n) else None)
        cols["c_age"].append(getattr(ch, "age", None))
    tot = [0.0] * len(horses)
    for k, w in coefs.items():
        zs = _z1(cols[k])
        for i, z in enumerate(zs):
            tot[i] += w * z
    return tot


def bases_propres(horses: Sequence[Any], selection: Sequence[int], k: int, discipline: Any = None) -> List[int]:
    """k bases parmi les 8 du ticket : meilleurs scores propres, de préférence en T1/T2 (les bases de T3 ne sortent que 34 % du temps) ;
    B1 = la plus petite cote des bases retenues, le reste par score."""
    sc = score_propre(horses, discipline)
    sel = list(dict.fromkeys(selection))
    pref = [i for i in sel if _cle(horses[i]) in ("T1", "T2")]
    autres = [i for i in sel if i not in pref]
    ordre = sorted(pref, key=lambda i: (-sc[i], i)) + sorted(autres, key=lambda i: (-sc[i], i))
    bases = ordre[:k]
    bases.sort(key=lambda i: (_cote_ref(horses[i]), -sc[i], i))
    return bases


def probas_recalibrees(ticket: str, probas: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Probabilités publiées × facteur observé/prédit, appliqué à moitié (retrait vers 1 : 106 courses seulement)."""
    if not probas:
        return None
    out: Dict[str, Any] = {}
    for k, f in FACTEURS_CALIBRAGE.get(ticket.upper(), {}).items():
        v = probas.get(k)
        if v is not None:
            out[k] = round(min(1.0, float(v) * (1.0 + 0.5 * (f - 1.0))), 4)
    out["facteurs_bruts"] = FACTEURS_CALIBRAGE.get(ticket.upper(), {})
    return out


def signal_course(horses: Sequence[Any]) -> Dict[str, Any]:
    """Filtre de courses (publié seulement) : « plein » si le favori est coté <= seuil (VANTAGE_FILTRE_FAVORI_MAX, défaut 4,0), sinon « reduit »."""
    try:
        seuil = float(os.environ.get("VANTAGE_FILTRE_FAVORI_MAX", str(SEUIL_FAVORI_DEFAUT)))
    except ValueError:
        seuil = SEUIL_FAVORI_DEFAUT
    cotes = [c for c in (_cote_ref(h) for h in horses) if c < 999.0]
    fav = min(cotes) if cotes else None
    return {"favori_cote": fav, "seuil": seuil, "niveau": (None if fav is None else ("plein" if fav <= seuil else "reduit"))}


def garder_t1(sel: Sequence[int], scores: Sequence[float], tr: Sequence[str | None], rangs_marche: Sequence[int],
              kmax: int, requises: Sequence[str], bornes: Tuple[int, int] | None = None) -> List[int]:
    """Aucun cheval de rang marché <= kmax n'est écarté : échange contre le sélectionné de rang > kmax au plus faible score
    (« un par tranche » et bornes respectés). Mesure : garde T1 rang<=3 = +0,10 capture/course pour A, nul pour B."""
    sel = list(sel)
    n = len(scores)
    for _ in range(kmax + 1):
        absents = sorted((i for i in range(n) if i not in sel and rangs_marche[i] <= kmax), key=lambda i: (rangs_marche[i], i))
        if not absents:
            break
        fait = False
        for entrant in absents:
            for sortant in sorted((i for i in sel if rangs_marche[i] > kmax), key=lambda i: (scores[i], -i)):
                if not _retirable(sortant, sel, tr, requises):
                    continue
                cand = [i for i in sel if i != sortant] + [entrant]
                if bornes and not (bornes[0] <= _cte(cand, tr, _GAUCHE_V68) <= bornes[1] and bornes[0] <= _cte(cand, tr, _DROITE_V68) <= bornes[1]):
                    continue
                sel, fait = cand, True
                break
            if fait:
                break
        if not fait:
            break
    return sorted(sel, key=lambda i: (-scores[i], i))
