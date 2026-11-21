"""Non-régression v1.29.41 : crash Plat handicap, poids du champ, p_boost, PL exact, audit, calibration."""
import json, random, re, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from app.models import Cheval, Depart, Discipline, RaceContext, TypeCourse
from app.engine.pl_inclusion import coverage, inclusion_probs, best_expected_subset, expected_hits
from app.engine import gmo_v as G


def _field(n=16, seed=1, disc="PLAT"):
    rng = random.Random(seed)
    s = [rng.lognormvariate(0, 0.8) for _ in range(n)]
    tot = sum(x * rng.lognormvariate(0, 0.3) for x in s)
    ch = []
    for i in range(n):
        p = s[i] / sum(s)
        ch.append(Cheval(numero=i + 1, nom=f"CH{i+1}", age=5, sexe="H", driver_jockey=f"J{i%9}", entraineur=f"E{i%11}",
                         cote_matin=max(1.8, round(0.82 / p, 1)), cote_avant_course=max(1.8, round(0.82 / p, 1)),
                         musique=" ".join(str(rng.randint(1, 9)) + ("p" if disc == "PLAT" else "a") for _ in range(6)),
                         gains_totaux_eur=float(rng.randint(5, 200) * 1000), nb_courses=rng.randint(5, 30),
                         poids_actuel_kg=float(rng.choice([54, 56, 57, 58, 60]))))
    return ch


def _race(n, disc=Discipline.PLAT, tc=TypeCourse.HANDICAP):
    return RaceContext(url_source="t", hippodrome="Chantilly", discipline=disc, distance_m=1800, type_course=tc,
                       depart=list(Depart)[0], partants_confirmes=n, date_course="2026-10-03", reunion_course_label="R1C1")


def _score(n=16, seed=1):
    from app.engine.qualitative_engine import compute_qualitative_signals_python
    from app.engine.race_pipeline import compute_race_scores
    ch = _field(n, seed); race = _race(n)
    q = compute_qualitative_signals_python(race, ch)
    hs = compute_race_scores(race, ch, q)
    return race, ch, q, hs


def test_plat_handicap_with_weights_no_longer_crashes():
    race, ch, q, hs = _score()
    assert len(hs) == 16


def test_poids_champ_derived():
    race, ch, q, hs = _score()
    assert race.poids_champ_kg and len(race.poids_champ_kg) == 16
    assert all(c.poids_moyen_champ_kg is not None for c in ch)
    assert ch[0].poids_min_champ_kg == min(race.poids_champ_kg)


def test_pl_coverage_matches_legacy_recursion():
    rng = random.Random(3)
    p = [rng.random() + 0.05 for _ in range(10)]; s = sum(p); p = [x / s for x in p]
    S = [0, 2, 3, 5, 6, 7, 8]
    legacy = G._prob_top5_subset(tuple(p), frozenset(S), tuple(range(10)))
    assert coverage(p, S) == pytest.approx(legacy, abs=1e-9)


def test_pl_inclusion_sums_to_five_and_monotone():
    p = [0.3, 0.2, 0.15, 0.1, 0.08, 0.06, 0.05, 0.03, 0.02, 0.01]
    pi = inclusion_probs(p)
    assert sum(pi) == pytest.approx(5.0, abs=1e-6)
    assert all(pi[i] >= pi[i + 1] - 1e-12 for i in range(len(pi) - 1))
    assert best_expected_subset(pi, 3) == [0, 1, 2]
    assert expected_hits(pi, [0, 1, 2]) < 3.0


def test_pboost_layer_is_centered_not_saturated():
    race, ch, q, hs = _score(16, 4)
    g = G.run_gmo_v(race, hs, q)
    ratios = [pb / pi for pb, pi in zip(g["p_boost_preclamp"], g["p_i"])]
    ratios.sort()
    assert 0.95 <= ratios[len(ratios) // 2] <= 1.05
    m = re.search(r"hi(\d+)_lo(\d+)", " ".join(g["flags"]))
    if m:
        assert int(m.group(1)) + int(m.group(2)) <= 6   # avant correctif : 16/16 saturés


def test_pboost_kill_switch(monkeypatch):
    monkeypatch.setenv("VANTAGE_PBOOST_UNITS_FIX", "0")
    race, ch, q, hs = _score(16, 4)
    g = G.run_gmo_v(race, hs, q)
    assert "PBOOST_UNITS_FIX_ACTIF" not in g["flags"]


def test_ticket_is_8_and_reports_expected_captures():
    race, ch, q, hs = _score(16, 5)
    g = G.run_gmo_v(race, hs, q)
    assert len(g["selection"]) == 8
    ca = g["captures_attendues"]
    assert ca["top8_modele_pur"] >= ca["ticket_selon_modele"] - 1e-9
    assert 0 < ca["ticket_selon_modele"] <= 5


def test_gain_normalized_optin_runs(monkeypatch):
    monkeypatch.setenv("GMO_GAIN_NORMALIZED", "1")
    race, ch, q, hs = _score(16, 6)
    g = G.run_gmo_v(race, hs, q)
    assert len(g["selection"]) == 8 and "GMO_GAIN_NORMALIZED_ACTIF" in g["flags"]


def test_market_blend_env_override(monkeypatch):
    monkeypatch.setenv("VANTAGE_MARKET_BLEND", "0.4")
    assert G.market_blend_for_field(16, "PLAT") == 0.4
    monkeypatch.setenv("VANTAGE_MARKET_BLEND", "9")
    assert G.market_blend_for_field(16, "PLAT") == 0.5


def test_activity_fields_derived_before_course_only():
    from app.engine.race_pipeline import _derive_activite
    from app.models import PerfHistorique
    c = Cheval(numero=1, nom="X", historique_recent=[
        PerfHistorique(valeur=0, rang=1, date="2026-10-03"),   # le jour J : exclu
        PerfHistorique(valeur=0, rang=3, date="2026-09-20"),
        PerfHistorique(valeur=0, rang=2, date="2026-09-01"),
        PerfHistorique(valeur=0, rang=2, date="2025-09-01")],
        historique_distance=[PerfHistorique(valeur=v, rang=1) for v in (1800, 2000, 1600)])
    _derive_activite([c], _race(12))
    assert c.nb_courses_30j == 1 and c.nb_courses_12m == 2 and c.distance_habituelle_m == 1800


def test_json_output_version_is_dynamic():
    from app.version import VERSION_RULESET
    import inspect, app.engine.ticket as T
    assert "VERSION_RULESET" in inspect.getsource(T.build_json_output)


def _fake_audits(n_races=120, seed=0, ordre_noise=1.6):
    rng = random.Random(seed)
    audits = []
    for _ in range(n_races):
        n = rng.choice([14, 16, 18])
        s = [rng.lognormvariate(0, 0.8) for _ in range(n)]
        mk = [x * rng.lognormvariate(0, 0.3) for x in s]
        od = [x * rng.lognormvariate(0, ordre_noise) for x in s]
        w, idx, top = s[:], list(range(n)), []
        for _k in range(5):
            r = rng.random() * sum(w[i] for i in idx); acc = 0
            for i in idx:
                acc += w[i]
                if acc >= r:
                    top.append(i); idx.remove(i); break
        tm = sum(mk)
        rows = [{"numero": i + 1, "cote_avant_course": round(0.82 * tm / mk[i], 1), "cote_matin": None, "tranche": "T1" if mk[i] / tm > .1 else "T3",
                 "ordre_final": od[i] / sum(od), "top5": i in top, "dans_ticket": False} for i in range(n)]
        top5 = {i + 1 for i in top}
        m8 = {r["numero"] for r in sorted(rows, key=lambda r: r["cote_avant_course"])[:8]}
        o8 = {r["numero"] for r in sorted(rows, key=lambda r: -r["ordre_final"])[:8]}
        audits.append({"dataset_calibration": rows, "baselines_contrefactuelles": {
            "ticket": len(top5 & o8), "marche_top8": len(top5 & m8), "ordre_final_top8": len(top5 & o8), "hasard_attendu": 8 * 5 / n}})
    return audits


def test_calibration_script_detects_that_market_beats_noisy_engine():
    import calibrer_depuis_audits as C
    rep = C.analyser(_fake_audits(), min_courses=30)
    assert rep["ticket_moins_marche"]["moy"] < 0
    assert rep["regression"]["coef_logit_marche"] > rep["regression"]["coef_z_ordre_final"]
    assert rep["blend_marche_suggere"] >= 0.40


def test_calibration_script_small_sample_is_flagged():
    import calibrer_depuis_audits as C
    rep = C.analyser(_fake_audits(10), min_courses=30)
    assert isinstance(rep["regression"], str) and "non calculée" in rep["regression"]


def test_audit_contains_baselines_and_dataset(monkeypatch):
    from app.engine import post_race_audit as A
    src = Path(A.__file__).read_text()
    assert "baselines_contrefactuelles" in src and "dataset_calibration" in src


# ======================= Ticket B + audit par ticket (v1.29.42) =======================
"""Ticket B : quotas par tranche (règle Golden 10/10/2026)."""
import random
from itertools import combinations
import pytest
from app.engine.ticket_quotas import build_ticket_quotas, GAUCHE, DROITE, GROUPES
from app.engine import gmo_v as G


class _T:  # tranche factice
    def __init__(self, v): self.value = v
class _S:
    def __init__(self, v): self.tranche = _T(v) if v else None
class _H:
    def __init__(self, v): self.synthesis = _S(v)


def _fake(tranches, seed=0):
    rng = random.Random(seed)
    horses = [_H(t) for t in tranches]
    raw = [rng.random() + 0.05 for _ in tranches]
    s = sum(raw)
    pi = [5 * x / s for x in raw]
    return horses, pi


def _check_rule(res, tr_list):
    sel = res["selection"]
    assert len(sel) == 8 and len(set(sel)) == 8
    c = {g: sum(1 for i in sel if tr_list[i] == g) for g in GROUPES}
    assert 3 <= sum(c[g] for g in GAUCHE) <= 5
    assert 3 <= sum(c[g] for g in DROITE) <= 5
    for g in GROUPES:
        if g in tr_list:
            assert c[g] >= 1, (g, c)
    return c


def test_rule_respected_typical_field():
    tr = ["T1"] * 3 + ["T2"] * 3 + ["T3"] * 4 + ["T4a"] * 3 + ["T4b"] * 2
    h, pi = _fake(tr, 1)
    _check_rule(build_ticket_quotas(h, pi), tr)


def test_free_split_inside_bands():
    tr = ["T1"] * 1 + ["T2"] * 6 + ["T3"] * 1 + ["T4a"] * 1 + ["T4b"] * 1 + ["T3"] * 4
    h, pi = _fake(tr, 2)
    res = build_ticket_quotas(h, pi)
    c = _check_rule(res, tr)
    assert c["T2"] >= 1 and res["niveau_relaxation"] == 0


def test_optimal_vs_bruteforce():
    rng = random.Random(5)
    tr = [rng.choice(GROUPES) for _ in range(13)]
    tr[:5] = list(GROUPES)   # les 5 tranches existent
    h, pi = _fake(tr, 3)
    res = build_ticket_quotas(h, pi)
    best = -1
    for comb in combinations(range(13), 8):
        c = {g: sum(1 for i in comb if tr[i] == g) for g in GROUPES}
        if not (3 <= c["T1"] + c["T2"] <= 5 and 3 <= c["T3"] + c["T4a"] + c["T4b"] <= 5):
            continue
        if any(g in tr and c[g] < 1 for g in GROUPES):
            continue
        best = max(best, sum(pi[i] for i in comb))
    assert res["captures_attendues_modele"] == pytest.approx(best, abs=1e-3)


def test_missing_tranche_is_not_required():
    tr = ["T1"] * 3 + ["T2"] * 3 + ["T3"] * 5 + ["T4a"] * 3          # pas de T4b
    h, pi = _fake(tr, 4)
    c = _check_rule(build_ticket_quotas(h, pi), tr)
    assert c["T4b"] == 0


def test_degrades_when_bands_impossible():
    tr = ["T1"] * 10 + ["T2"] * 2 + ["T3"] * 2                      # T3+T4 = 2 max < 3
    h, pi = _fake(tr, 5)
    res = build_ticket_quotas(h, pi)
    assert len(res["selection"]) == 8 and res["niveau_relaxation"] == 2
    assert "QUOTA_B_BORNES_3_5_IMPOSSIBLES" in res["flags"]


def test_always_8_horses_on_scored_race():
    for seed in (1, 2, 3):
        race, ch, q, hs = _score(16, seed)
        g = G.run_gmo_v(race, hs, q)
        res = build_ticket_quotas(hs, g["pi_top5_modele"])
        assert len(res["selection"]) == 8
        assert res["captures_attendues_modele"] <= g["captures_attendues"]["top8_modele_pur"] + 1e-9


# ---------- audit individuel par ticket
def _fake_result_and_arrival():
    from app.scraping.turfoo_resultats import ArrivalHorse
    race, ch, q, hs = _score(16, 2)
    g = G.run_gmo_v(race, hs, q)
    from app.engine.ticket import build_ticket
    from app.models import RaceResult
    qi = build_ticket_quotas(hs, g["pi_top5_modele"])
    A = build_ticket(hs, g["selection"], roles_map={})
    B = build_ticket(hs, qi["selection"], roles_map={})
    res = RaceResult(race_id="x", context=race, horses=hs, ticket=A, ticket_quotas=B, quotas_info=qi)
    nums = [h.cheval.numero for h in hs]
    arr = [ArrivalHorse(rang=i + 1, numero=n, nom=f"CH{n}") for i, n in enumerate(nums[:5])]
    return res, arr


def test_audit_is_computed_per_ticket():
    from app.engine.post_race_audit import build_post_race_audit
    res, arr = _fake_result_and_arrival()
    a = build_post_race_audit(res, arr, None, ticket="A")
    b = build_post_race_audit(res, arr, None, ticket="B")
    top5 = {h.numero for h in arr}
    assert a["ticket_audite"] == "A" and b["ticket_audite"] == "B"
    assert a["nb_captures"] == len(top5 & {t.numero for t in res.ticket})
    assert b["nb_captures"] == len(top5 & {t.numero for t in res.ticket_quotas})
    assert a["baselines_contrefactuelles"]["ticket_B_quotas"] == b["nb_captures"]
    assert b["baselines_contrefactuelles"]["ticket_A_protocole"] == a["nb_captures"]
    assert all("dans_ticket_A" in r and "dans_ticket_B" in r for r in a["dataset_calibration"])


def test_aggregate_reports_ticket_b_rate():
    from app.engine.post_race_audit import aggregate_audit_patterns, build_post_race_audit
    res, arr = _fake_result_and_arrival()
    a = build_post_race_audit(res, arr, None, ticket="A")
    a["audit_ticket_B"] = build_post_race_audit(res, arr, None, ticket="B")
    out = aggregate_audit_patterns([{"audit": a}])
    assert out["nb_courses_ticket_B"] == 1 and out["taux_capture_moyen_ticket_B"] is not None
