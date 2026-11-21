#!/usr/bin/env python3
"""calibrer_depuis_audits.py -- Mesure RÉELLE de ce que le moteur apporte (v1.29.41).

Entrée : dossier(s) ou fichier(s) JSON d'audit post-course (bouton « bundle » / audit.json)
         produits par la v1.29.41+ (clé `dataset_calibration`).
Sortie : 1. captures moyennes : ticket vs marché top8 vs ordre_final top8 vs hasard (IC bootstrap)
         2. calibration par tranche : taux Top5 observé vs attendu par le marché
         3. régression logistique P(Top5) ~ logit(marché) + z(ordre_final) : le moteur ajoute-t-il
            de l'information AU-DELÀ du marché ? -> poids marché suggéré (VANTAGE_MARKET_BLEND)

Usage :  python scripts/calibrer_depuis_audits.py audits/ [--min-courses 30]

NOUVEAU (v1.29.54) -- à partir de l'export global (« exporter toutes les courses pour analyse (zip) ») :
         python scripts/calibrer_depuis_audits.py vantage_analyse_XXXX.zip --regles        # règles de ticket + validation croisée
         python scripts/calibrer_depuis_audits.py vantage_analyse_XXXX.zip --composantes   # pouvoir discriminant de chaque composante
  --regles       : simule des variantes de ticket (marché, ordre, mélange marché/ordre, filet de semi-favoris, quota T1+T2 relâché)
                   sur TOUS les partants stockés, avec IC95 % et validation croisée par blocs de dates (le paramètre est choisi sur
                   les blocs d'entraînement et évalué sur le bloc laissé de côté : protège du sur-ajustement) ;
  --composantes  : AUC intra-course de chaque colonne (cote, ordre_final, PCH, bd_*, sy_*, ch_*) pour prédire le Top 5, au global
                   et dans la bande de cotes 6-25 (où se jouent les erreurs de cotation) -- en comparant AUX CHEVAUX CAPTURÉS, pas
                   seulement aux manqués.
Pure Python (aucune dépendance), reproductible (graine fixe).
"""
from __future__ import annotations
import argparse, json, math, os, random, sys
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.pl_inclusion import inclusion_probs  # noqa: E402


def charger(paths):
    out = []
    for p in paths:
        p = Path(p)
        files = [p] if p.is_file() else sorted(p.rglob("*.json"))
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for cand in (d, d.get("audit") if isinstance(d, dict) else None, (d.get("rapport_audit") if isinstance(d, dict) else None)):
                if isinstance(cand, dict) and cand.get("dataset_calibration"):
                    out.append(cand)
                    break
    return out


def _cote(r):
    c = r.get("cote_avant_course") or r.get("cote_matin")
    return float(c) if c and float(c) > 1.01 else None


def pi_marche(rows):
    inv = [1.0 / _cote(r) if _cote(r) else 0.0 for r in rows]
    if sum(inv) <= 0:
        return None
    return inclusion_probs(inv)


def _logit(x):
    x = min(max(x, 1e-4), 1 - 1e-4)
    return math.log(x / (1 - x))


def _z(v):
    m, s = mean(v), (pstdev(v) or 1.0)
    return [(x - m) / s for x in v]


def logistique(X, y, l2=1.0, it=40):
    """Newton-Raphson, régularisation L2 légère (intercept non pénalisé)."""
    k = len(X[0])
    w = [0.0] * k
    for _ in range(it):
        g = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for xi, yi in zip(X, y):
            z = sum(a * b for a, b in zip(w, xi))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            for a in range(k):
                g[a] += (p - yi) * xi[a]
                for b in range(k):
                    H[a][b] += p * (1 - p) * xi[a] * xi[b]
        for a in range(1, k):
            g[a] += l2 * w[a]
            H[a][a] += l2
        step = _solve(H, g)
        w = [wi - si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return w


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        d = M[i][i] or 1e-12
        for j in range(i, n + 1):
            M[i][j] /= d
        for r in range(n):
            if r != i:
                f = M[r][i]
                for j in range(i, n + 1):
                    M[r][j] -= f * M[i][j]
    return [M[i][n] for i in range(n)]


def logloss(w, X, y):
    tot = 0.0
    for xi, yi in zip(X, y):
        z = sum(a * b for a, b in zip(w, xi))
        p = min(max(1 / (1 + math.exp(-max(-30, min(30, z)))), 1e-6), 1 - 1e-6)
        tot -= yi * math.log(p) + (1 - yi) * math.log(1 - p)
    return tot / len(y)


def boot_ci(vals, n=2000, seed=7):
    rng = random.Random(seed)
    ms = sorted(mean(rng.choices(vals, k=len(vals))) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def _mode(a):
    return (a.get("contexte_dataset") or {}).get("mode_execution", "INCONNU")


def analyser(audits, min_courses=30, verbose=True, mode="ALL"):
    """mode : ALL | REJEU | PRE_COURSE. Les rejeux (course déjà courue) utilisent des cotes FINALES et des cumuls de fiches
    d'après-course : à ne jamais mélanger sans le savoir avec des courses analysées AVANT le départ."""
    repartition = {}
    for a in audits:
        repartition[_mode(a)] = repartition.get(_mode(a), 0) + 1
    if mode != "ALL":
        audits = [a for a in audits if _mode(a) == mode]
    rep = {"n_courses": len(audits), "repartition_par_mode": repartition, "mode_analyse": mode}
    # 1. captures
    cap = {"ticket": [], "marche_top8": [], "ordre_final_top8": [], "hasard": []}
    capB = [(a.get("baselines_contrefactuelles") or {}).get("ticket_B_quotas") for a in audits]
    capB = [x for x in capB if x is not None]
    for a in audits:
        b = a.get("baselines_contrefactuelles") or {}
        if "ticket" in b:
            cap["ticket"].append(b["ticket"]); cap["marche_top8"].append(b["marche_top8"])
            cap["ordre_final_top8"].append(b["ordre_final_top8"]); cap["hasard"].append(b.get("hasard_attendu") or 0)
    if cap["ticket"]:
        rep["captures"] = {k: round(mean(v), 3) for k, v in cap.items()}
        d = [t - m for t, m in zip(cap["ticket"], cap["marche_top8"])]
        lo, hi = boot_ci(d)
        rep["ticket_moins_marche"] = {"moy": round(mean(d), 3), "ic95": [round(lo, 3), round(hi, 3)]}
        d2 = [t - m for t, m in zip(cap["ticket"], cap["ordre_final_top8"])]
        lo2, hi2 = boot_ci(d2)
        rep["ticket_moins_ordre8"] = {"moy": round(mean(d2), 3), "ic95": [round(lo2, 3), round(hi2, 3)]}
    if capB:
        rep["captures_ticket_B_quotas"] = {"n": len(capB), "moy": round(mean(capB), 3)}
    # 2. calibration par tranche + 3. régression
    X, y, groups = [], [], []
    par_tranche = {}
    for gi, a in enumerate(audits):
        rows = a["dataset_calibration"]
        pm = pi_marche(rows)
        if pm is None or len(rows) < 8:
            continue
        zo = _z([r["ordre_final"] for r in rows])
        for r, p_m, z_o in zip(rows, pm, zo):
            t = r.get("tranche") or "?"
            d = par_tranche.setdefault(t, {"n": 0, "obs": 0, "att": 0.0})
            d["n"] += 1; d["obs"] += 1 if r["top5"] else 0; d["att"] += p_m
            X.append([1.0, _logit(p_m), z_o]); y.append(1 if r["top5"] else 0); groups.append(gi)
    rep["calibration_tranche"] = {
        t: {"n": d["n"], "top5_observe": round(d["obs"] / d["n"], 3), "top5_attendu_marche": round(d["att"] / d["n"], 3)}
        for t, d in sorted(par_tranche.items())
    }
    if len(audits) >= min_courses and X:
        w_full = logistique(X, y)
        # validation croisée par course (leave-one-race-out par blocs de 5)
        folds = 5
        ll_m = ll_f = 0.0; cnt = 0
        for f in range(folds):
            tr = [i for i, g in enumerate(groups) if g % folds != f]
            te = [i for i, g in enumerate(groups) if g % folds == f]
            if not te or not tr:
                continue
            Xm = [[X[i][0], X[i][1]] for i in tr]; ytr = [y[i] for i in tr]
            wm = logistique(Xm, ytr); wf = logistique([X[i] for i in tr], ytr)
            ll_m += logloss(wm, [[X[i][0], X[i][1]] for i in te], [y[i] for i in te]) * len(te)
            ll_f += logloss(wf, [X[i] for i in te], [y[i] for i in te]) * len(te)
            cnt += len(te)
        rep["regression"] = {
            "coef_intercept": round(w_full[0], 3), "coef_logit_marche": round(w_full[1], 3),
            "coef_z_ordre_final": round(w_full[2], 3),
            "logloss_cv_marche_seul": round(ll_m / cnt, 4), "logloss_cv_marche_plus_ordre": round(ll_f / cnt, 4),
        }
        gain = (ll_m - ll_f) / cnt
        rep["regression"]["gain_logloss_ordre"] = round(gain, 5)
        if gain <= 0.0005:
            rep["verdict"] = ("ordre_final N'AJOUTE PAS d'information mesurable au-delà du marché : "
                              "viser un blend marché élevé (>= 0.40) tant que le moteur ne le prouve pas.")
            rep["blend_marche_suggere"] = 0.45
        else:
            sm = abs(w_full[1]) * pstdev([x[1] for x in X]); so = abs(w_full[2])
            blend = sm / (sm + so) if (sm + so) else 0.3
            rep["blend_marche_suggere"] = round(min(0.50, max(0.12, blend)), 2)
            rep["verdict"] = "ordre_final apporte de l'information au-delà du marché ; blend suggéré = part relative du marché."
    else:
        rep["regression"] = f"non calculée : {len(audits)} courses < {min_courses} (résultats instables en dessous)"
    return rep


# ======================================================================================================
# Export global (partants.csv) : simulation de règles de ticket + discrimination des composantes
# ======================================================================================================
import csv as _csv
import io as _io
import zipfile as _zipfile

_ID_COLS = {"race_id", "date_course", "hippodrome", "discipline", "mode", "partants", "numero", "tranche", "musique", "sexe",
            "incident", "top5", "dans_ticket_A", "dans_ticket_B", "rang_reel", "rang_complet"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def charger_partants(chemin):
    p = Path(chemin)
    if p.suffix == ".zip":
        with _zipfile.ZipFile(p) as z:
            raw = z.read("partants.csv").decode("utf-8")
    else:
        raw = (p / "partants.csv" if p.is_dir() else p).read_text(encoding="utf-8")
    rows = list(_csv.DictReader(_io.StringIO(raw), delimiter=";"))
    courses = {}
    for r in rows:
        r["_cote"] = _f(r.get("cote_avant_course")) or _f(r.get("cote_matin")) or 999.0
        r["_ordre"] = _f(r.get("ordre_final")) or 0.0
        r["_top5"] = str(r.get("top5")).lower() == "true"
        r["_inA"] = str(r.get("dans_ticket_A")).lower() == "true"
        r["_inB"] = str(r.get("dans_ticket_B")).lower() == "true"
        r["_inC"] = str(r.get("dans_ticket_C")).lower() == "true"
        courses.setdefault(r["race_id"], []).append(r)
    for rid, hs in courses.items():
        for i, h in enumerate(sorted(hs, key=lambda x: x["_cote"]), start=1):
            h["_rg_m"] = i
        for i, h in enumerate(sorted(hs, key=lambda x: -x["_ordre"]), start=1):
            h["_rg_o"] = i
    return courses


def _date(hs):
    return min(h.get("date_course") or "" for h in hs)


def _sel_marche(hs, k=8):
    return {h["numero"] for h in sorted(hs, key=lambda x: x["_rg_m"])[:k]}


def _sel_ordre(hs, k=8):
    return {h["numero"] for h in sorted(hs, key=lambda x: x["_rg_o"])[:k]}


def _sel_A(hs, k=8):
    return {h["numero"] for h in hs if h["_inA"]}


def _sel_B(hs, k=8):
    return {h["numero"] for h in hs if h["_inB"]}


def _sel_C(hs, k=8):
    return {h["numero"] for h in hs if h["_inC"]}


def _rang(hs, col):
    vals = [(_f(h.get(col)) if col != "_cote" else -h["_cote"]) for h in hs]
    vals = [v if v is not None else -1e9 for v in vals]
    ordre = sorted(range(len(hs)), key=lambda i: -vals[i])
    r = [0] * len(hs)
    for pos, i in enumerate(ordre, 1):
        r[i] = pos
    return r


def _sel_blend_col(hs, col, alpha, k=8):
    """Mélange de RANGS : alpha x rang marché + (1-alpha) x rang de `col` (ex. pch_final)."""
    rm, rc = _rang(hs, "_cote"), _rang(hs, col)
    sc = [alpha * rm[i] + (1 - alpha) * rc[i] for i in range(len(hs))]
    return {hs[i]["numero"] for i in sorted(range(len(hs)), key=lambda i: (sc[i], rm[i]))[:k]}


def _sel_blend(hs, alpha, k=8):
    return {h["numero"] for h in sorted(hs, key=lambda x: alpha * x["_rg_m"] + (1 - alpha) * x["_rg_o"])[:k]}


def _sel_filet(hs, nb, k=8, cmin=6.0, cmax=15.0, rang_m=8, rang_o=10):
    """Ticket A où jusqu'à `nb` semi-favoris (cote 6-15, top8 marché, top10 ordre) absents prennent la place des outsiders
    (cote >= 20) les moins bien classés par l'ordre ; à défaut, des moins bien classés du ticket."""
    sel = _sel_A(hs, k)
    if nb <= 0 or not sel:
        return sel
    par = {h["numero"]: h for h in hs}
    cands = sorted([h for h in hs if h["numero"] not in sel and cmin <= h["_cote"] <= cmax and h["_rg_m"] <= rang_m and h["_rg_o"] <= rang_o],
                   key=lambda x: x["_rg_m"])[:nb]
    for c in cands:
        victimes = sorted([par[n] for n in sel], key=lambda x: (x["_cote"] < 20, -x["_rg_o"]))
        sel.remove(victimes[0]["numero"])
        sel.add(c["numero"])
    return sel


def _sel_quota(hs, m, k=8):
    """8 meilleurs par ordre, avec AU MOINS m chevaux de tranche T1/T2 (le quota actuel plafonne T1+T2 à 5)."""
    ranked = sorted(hs, key=lambda x: x["_rg_o"])
    t12 = [h for h in ranked if h.get("tranche") in ("T1", "T2")]
    sel = list(ranked[:k])
    manque = max(0, m - sum(1 for h in sel if h.get("tranche") in ("T1", "T2")))
    for h in t12:
        if manque <= 0:
            break
        if h not in sel:
            autres = [x for x in reversed(sel) if x.get("tranche") not in ("T1", "T2")]
            if not autres:
                break
            sel.remove(autres[0]); sel.append(h); manque -= 1
    return {h["numero"] for h in sel}


def _captures(courses, selector):
    out = {}
    for rid, hs in courses.items():
        top5 = {h["numero"] for h in hs if h["_top5"]}
        out[rid] = len(selector(hs) & top5)
    return out


def _ci(vals, n=3000, seed=11):
    rng = random.Random(seed)
    ms = sorted(mean(rng.choices(vals, k=len(vals))) for _ in range(n))
    return round(ms[int(0.025 * n)], 3), round(ms[int(0.975 * n)], 3)


def simuler_regles(courses, blocs=4):
    ids = sorted(courses, key=lambda r: _date(courses[r]))
    if len(ids) < 8:
        return {"erreur": f"{len(ids)} course(s) : trop peu pour simuler"}
    base = {"A_actuel": _sel_A, "marche_top8": _sel_marche, "ordre_top8": _sel_ordre}
    if any(h["_inB"] for hs in courses.values() for h in hs):
        base["B_actuel"] = _sel_B
    if any(h["_inC"] for hs in courses.values() for h in hs):
        base["C_actuel"] = _sel_C
    familles = {
        "melange_marche_PCH (alpha=poids du marché)": {a: (lambda hs, a=a: _sel_blend_col(hs, "pch_final", a)) for a in [x / 10 for x in range(0, 11)]},
        "melange_marche_ordre (alpha=poids du marché)": {a: (lambda hs, a=a: _sel_blend(hs, a)) for a in [x / 10 for x in range(0, 11)]},
        "A + filet de semi-favoris (nb max)": {k: (lambda hs, k=k: _sel_filet(hs, k)) for k in range(0, 5)},
        "ordre + quota T1/T2 minimal (m)": {m: (lambda hs, m=m: _sel_quota(hs, m)) for m in range(2, 8)},
    }
    res_a = _captures(courses, _sel_A); res_m = _captures(courses, _sel_marche)
    out = {"n_courses": len(ids), "baselines": {}, "familles": {}}
    for nom, sel in base.items():
        c = _captures(courses, sel)
        d_m = [c[r] - res_m[r] for r in ids]; d_a = [c[r] - res_a[r] for r in ids]
        out["baselines"][nom] = {"captures_moy": round(mean(c.values()), 3), "vs_marche": round(mean(d_m), 3), "vs_marche_ic95": _ci(d_m),
                                 "vs_A": round(mean(d_a), 3), "vs_A_ic95": _ci(d_a)}
    # validation croisée par blocs de dates
    taille = max(1, len(ids) // blocs)
    parts = [ids[i * taille:(i + 1) * taille] if i < blocs - 1 else ids[i * taille:] for i in range(blocs)]
    for nom, params in familles.items():
        tab = {p: _captures(courses, sel) for p, sel in params.items()}
        glob = {str(p): round(mean(tab[p].values()), 3) for p in params}
        hors_ech, choix = [], []
        for i, test in enumerate(parts):
            train = [r for j, pt in enumerate(parts) if j != i for r in pt]
            best = max(params, key=lambda p: mean(tab[p][r] for r in train))
            choix.append(best)
            hors_ech += [tab[best][r] for r in test]
        d_a = [h - res_a[r] for h, r in zip(hors_ech, [r for pt in parts for r in pt])]
        out["familles"][nom] = {"captures_moy_par_parametre": glob, "parametres_choisis_par_bloc": choix,
                                "captures_HORS_ECHANTILLON": round(mean(hors_ech), 3),
                                "gain_vs_A_hors_echantillon": round(mean(d_a), 3), "ic95": _ci(d_a)}
    return out


def _auc(pos, neg):
    if not pos or not neg:
        return None
    gt = sum(1 for p in pos for q in neg if p > q) + 0.5 * sum(1 for p in pos for q in neg if p == q)
    return gt / (len(pos) * len(neg))


def discriminer_composantes(courses, min_courses=10):
    colonnes = set()
    for hs in courses.values():
        for h in hs:
            for k, v in h.items():
                if not k.startswith("_") and k not in _ID_COLS and _f(v) is not None:
                    colonnes.add(k)
    res = []
    for col in sorted(colonnes | {"_cote_inv"}):
        aucs, aucs_bande, n_vals = [], [], 0
        for hs in courses.values():
            def val(h):
                return (-h["_cote"]) if col == "_cote_inv" else _f(h.get(col))
            vals = [(val(h), h["_top5"], h["_rg_m"]) for h in hs if val(h) is not None]
            n_vals += len(vals)
            if len({v for v, _, _ in vals}) < 3:
                continue
            a = _auc([v for v, t, _ in vals if t], [v for v, t, _ in vals if not t])
            if a is not None:
                aucs.append(a)
            band = [(v, t) for v, t, rg in vals if 4 <= rg <= 12]            # bande où le marché est le moins informatif
            ab = _auc([v for v, t in band if t], [v for v, t in band if not t])
            if ab is not None:
                aucs_bande.append(ab)
        if len(aucs) >= min_courses:
            res.append({"colonne": "marche (-cote)" if col == "_cote_inv" else col, "auc_intra_course": round(mean(aucs), 3),
                        "auc_bande_rang_marche_4_12": round(mean(aucs_bande), 3) if aucs_bande else None, "n_courses": len(aucs),
                        "taux_renseigne": round(n_vals / max(1, sum(len(h) for h in courses.values())), 2)})
    res.sort(key=lambda r: -abs(r["auc_intra_course"] - 0.5))
    return {"lecture": "AUC 0.5 = aucune information ; > 0.5 : valeur haute => plus de chances d'être Top 5 ; < 0.5 : relation INVERSE. "
                       "Comparer chaque composante au MARCHÉ et regarder la bande de rang marché 4-12.", "colonnes": res[:40]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chemins", nargs="+")
    ap.add_argument("--min-courses", type=int, default=30)
    ap.add_argument("--mode", choices=["ALL", "REJEU", "PRE_COURSE"], default="ALL", help="filtrer par mode d'exécution")
    ap.add_argument("--regles", action="store_true", help="export zip : simuler des règles de ticket (validation croisée)")
    ap.add_argument("--composantes", action="store_true", help="export zip : pouvoir discriminant de chaque composante")
    a = ap.parse_args()
    if a.regles or a.composantes:
        courses = charger_partants(a.chemins[0])
        if a.mode != "ALL":
            courses = {r: hs for r, hs in courses.items() if hs[0].get("mode") == a.mode}
        out = {}
        if a.regles:
            out["regles"] = simuler_regles(courses)
        if a.composantes:
            out["composantes"] = discriminer_composantes(courses)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    audits = charger(a.chemins)
    if not audits:
        print("Aucun audit avec `dataset_calibration` trouvé (v1.29.41+ requise pour les générer).")
        return 1
    print(json.dumps(analyser(audits, a.min_courses, mode=a.mode), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
