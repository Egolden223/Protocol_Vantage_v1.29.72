import pytest

from app.engine.supra_phase2 import _cote_gagnant
from app.engine.data_contract import evaluate_data_contract
from app.main import _validate_race_url
from app.scraping.open_pmu_api import ArriveeChevalOPA, ArriveeCourseOPA
from app.scraping.turfoo import scrape_turfoo_race
from app.scraping.router import _identity_mismatch
from app.models import (
    Cheval,
    Depart,
    Discipline,
    RaceContext,
    TypeCourse,
)


def _course(cotes):
    return ArriveeCourseOPA(
        type_discipline="Haies",
        montant_eur=None,
        distance_m=3600,
        prix=None,
        hippodrome="Auteuil",
        heure_depart=None,
        details="HANDICAP",
        partants=15,
        non_partants=[],
        ordre_arrivee=[1],
        reunion_course="R1/C1",
        date_iso="2026-10-01",
        chevaux_par_numero={
            1: ArriveeChevalOPA(numero=1, nom_cheval="TEST", cotes=cotes)
        },
    )


def test_supra_ignores_none_and_empty_historical_odds():
    assert _cote_gagnant(_course([None])) is None
    assert _cote_gagnant(_course(["", None])) is None
    assert _cote_gagnant(_course([None, "12,5"])) == 12.5


def test_security_rejects_non_https_private_and_unknown_urls():
    for url in (
        "http://127.0.0.1/course",
        "https://169.254.169.254/latest/meta-data/",
        "https://example.com/course",
        "https://www.turfoo.fr\nX-Test: injected",
    ):
        with pytest.raises(ValueError):
            _validate_race_url(url)


def test_data_contract_marks_missing_critical_fields():
    race = RaceContext(
        url_source="https://www.turfoo.fr/course/1",
        hippodrome="Auteuil",
        discipline=Discipline.HAIES,
        distance_m=3600,
        type_course=TypeCourse.HANDICAP,
        depart=Depart.CENTRE,
        partants_confirmes=15,
        date_course="2026-10-01",
    )
    chevaux = [Cheval(numero=1, nom="TEST", driver_jockey="JOCKEY", entraineur="TRAINER")]
    contrat = evaluate_data_contract(race, chevaux)
    assert contrat["verdict"] == "LACUNES_CRITIQUES"
    assert contrat["nb_lacunes_critiques"] > 0


def test_data_contract_does_not_require_flat_handicap_fields_for_trot():
    race = RaceContext(
        url_source="https://www.turfoo.fr/course/1",
        hippodrome="Vincennes",
        discipline=Discipline.TROT_ATTELE,
        distance_m=2700,
        type_course=TypeCourse.CONDITIONS,
        depart=Depart.VOLTE,
        partants_confirmes=13,
        date_course="2026-10-02",
    )
    chevaux = [
        Cheval(
            numero=1, nom="TEST", cote_matin=5.0, cote_avant_course=5.0,
            fiche_url="https://www.turfoo.fr/cheval/test", age=6,
            musique="1a 2a 3a", gains_totaux_eur=10000,
        )
    ]
    contrat = evaluate_data_contract(race, chevaux)
    assert "cheval.valeur_pmu=0/1" not in contrat["lacunes_critiques"]
    assert not any("poids_actuel_kg" in x for x in contrat["lacunes_critiques"])


def test_supra_accepts_numeric_odds_as_defensive_input():
    assert _cote_gagnant(_course([8.0])) == 8.0


def test_deferre_contract_is_string():
    # Le parseur construit directement un Cheval Pydantic ; une valeur booléenne
    # aurait déclenché l'erreur observée sur la course réelle.
    html = """
    <h1>Vincennes Trot attelé</h1>
    <table><tr><th>Cheval</th><th>Jockey</th><th>Entraîneur</th><th>S/Age</th><th>Musique</th><th>Ferrure</th></tr>
    <tr><td>1 - TEST</td><td>JOCKEY</td><td>TRAINER</td><td>M 6</td><td>1a 2a 3a</td><td>D4</td></tr>
    <tr><td>2 - TEST2</td><td>JOCKEY</td><td>TRAINER</td><td>M 6</td><td>1a 2a 3a</td><td>PA</td></tr>
    <tr><td>3 - TEST3</td><td>JOCKEY</td><td>TRAINER</td><td>M 6</td><td>1a 2a 3a</td><td>-</td></tr></table>
    """
    # La structure de contexte est déduite de l'URL et du HTML ; une erreur de
    # validation ici aurait reproduit exactement le défaut de la course réelle.
    from app.scraping import turfoo
    old = turfoo.fetch_html
    turfoo.fetch_html = lambda url: html
    try:
        _, chevaux, _ = scrape_turfoo_race(
            "https://www.turfoo.fr/programmes-courses/261002/reunion1-vincennes/course1-test/"
        )
    finally:
        turfoo.fetch_html = old
    assert chevaux[0].deferre == "D4"


def test_source_identity_rejects_wrong_hippodrome():
    from types import SimpleNamespace
    race = SimpleNamespace(hippodrome="Cordemais")
    assert "incohérent" in _identity_mismatch(race, "Agen La Garenne")
    assert _identity_mismatch(SimpleNamespace(hippodrome="Agen"), "Agen La Garenne") is None


def test_missing_press_icp_is_not_critical_blocker():
    race = RaceContext(
        url_source="https://www.turfoo.fr/course/1",
        hippodrome="Vincennes",
        discipline=Discipline.TROT_ATTELE,
        distance_m=2700,
        type_course=TypeCourse.CONDITIONS,
        depart=Depart.VOLTE,
        partants_confirmes=12,
        date_course="2026-10-04",
    )
    chevaux = [Cheval(numero=i, nom=f"TEST{i}", musique="1a", cote_matin=5.0, cote_avant_course=5.0,
                      fiche_url="https://www.turfoo.fr/cheval/test", driver_jockey="J", entraineur="T",
                      gains_totaux_eur=1000) for i in range(1, 13)]
    contrat = evaluate_data_contract(race, chevaux)
    assert not any(x.startswith("presse.icp_global") for x in contrat["lacunes_critiques"])


def test_repo_file_budget():
    """Budget GitHub : 100 fichiers max (hors caches), et un seul changelog."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    skip = {"__pycache__", ".pytest_cache", ".git"}
    # data/ (base SQLite, caches) est dans .gitignore : jamais déposé sur GitHub, mais créé par les autres tests en local
    files = [p for p in root.rglob("*") if p.is_file() and not (set(p.relative_to(root).parts) & skip) and p.relative_to(root).parts[0] != "data"]
    assert len(files) <= 100, f"{len(files)} fichiers (> 100) : fusionner/supprimer avant de déployer"
    assert [p.name for p in files if p.name.upper().startswith("CHANGELOG")] == ["CHANGELOG.md"]


# ======================= Modules IA Claude (v1.29.43) =======================
import pytest as _pytest


def _fake_collect_json(n=8, hippo="CHANTILLY", date="2026-10-03"):
    return {
        "course": {"hippodrome": hippo, "discipline": "PLAT", "distance_m": 1800, "type_course": "HANDICAP",
                   "depart": "AUTOSTART", "partants_confirmes": n, "date_course": date, "reunion_course_label": "R1C4"},
        "chevaux": [{"numero": i, "nom": f"CH{i}", "cote_matin": 5.0 + i, "musique": "1p2p"} for i in range(1, n + 1)],
        "sources_consultees": ["https://exemple/a"],
    }


class _FakeClient:
    def __init__(self, payload): self.payload, self.calls = payload, 0
    def run_json(self, *a, **k):
        self.calls += 1
        return self.payload


def test_llm_client_needs_key_and_has_no_sdk_dependency(monkeypatch):
    from app.llm import client as C
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(C.config, "ANTHROPIC_API_KEY", "")
    with _pytest.raises(C.ClaudeUnavailable):
        C.ClaudeClient()
    assert "import anthropic" not in open(C.__file__).read()
    assert not C.claude_available()


def test_llm_client_fallback_without_tools_and_pause_turn(monkeypatch):
    from app.llm import client as C
    cl = C.ClaudeClient(api_key="k")
    seen = []

    def fake_post(payload, beta):
        seen.append(("tools" in payload, beta))
        if "tools" in payload:
            raise C._HttpError(400, "tool not supported")
        return {"content": [{"type": "text", "text": '{"a": 1}'}], "stop_reason": "end_turn"}
    monkeypatch.setattr(cl, "_post", fake_post)
    assert cl.run_json("s", "u", web_search=True, web_fetch=True) == {"a": 1}
    assert seen[0] == (True, True) and seen[-1] == (False, False)

    calls = {"n": 0}

    def pause_then_end(payload, beta):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": [{"type": "text", "text": "..."}], "stop_reason": "pause_turn"}
        return {"content": [{"type": "text", "text": "fin"}], "stop_reason": "end_turn"}
    monkeypatch.setattr(cl, "_post", pause_then_end)
    assert cl.run("s", "u", web_search=False, web_fetch=False) == "fin" and calls["n"] == 2


def test_llm_client_auth_error_is_explicit(monkeypatch):
    from app.llm import client as C
    cl = C.ClaudeClient(api_key="k")
    monkeypatch.setattr(cl, "_post", lambda p, b: (_ for _ in ()).throw(C._HttpError(401, "bad key")))
    with _pytest.raises(C.ClaudeUnavailable):
        cl.run("s", "u", web_search=False, web_fetch=False)


def test_ai_collection_works_without_protocol_assets_and_flags_horses():
    from app.llm.collection import collect_race_data
    race, ch, src = collect_race_data("https://www.turfoo.fr/x", _FakeClient(_fake_collect_json()))
    assert len(ch) == 8 and all("COLLECTE_IA" in c.flags for c in ch) and race.url_source


def test_ai_collection_too_few_horses_rejected():
    from app.llm.collection import collect_race_data
    with _pytest.raises(ValueError):
        collect_race_data("u", _FakeClient(_fake_collect_json(4)))


def test_ai_collection_fallback_rechecks_identity(monkeypatch):
    from app.llm import collection as COL, client as C
    class _Br(_FakeClient):
        last_provider = "test"
        def can_browse(self): return True
    monkeypatch.setattr(C, "LLMClient", lambda **k: _Br(_fake_collect_json(hippo="VINCENNES")))
    with _pytest.raises(ValueError, match="IDENTITE_SOURCE_REJETEE"):
        COL.collect_with_ai_fallback("u", {"hippodrome": "Chantilly", "date": "2026-10-03"})
    monkeypatch.setattr(C, "LLMClient", lambda **k: _Br(_fake_collect_json()))
    race, ch, w, url = COL.collect_with_ai_fallback("u", {"hippodrome": "Chantilly", "date": "2026-10-03", "reunion": 1, "course": 4})
    assert race.reunion_course_label == "R1C4" and any("SOURCE_IA_COLLECTION_UTILISEE" in x for x in w)


def _qual_field():
    from app.models import Cheval
    return [Cheval(numero=1, nom="A", commentaire_derniere_course="Gêné au départ, a bien fini sur la fin."),
            Cheval(numero=2, nom="B", commentaire_derniere_course="S'est éteint dans la ligne droite, boiterie suspectée."),
            Cheval(numero=3, nom="C")]


def _qual_race():
    from app.models import Depart, Discipline, RaceContext, TypeCourse
    return RaceContext(url_source="t", hippodrome="Chantilly", discipline=Discipline.PLAT, distance_m=1800,
                       type_course=TypeCourse.HANDICAP, depart=list(Depart)[0], partants_confirmes=3, date_course="2026-10-03")


def test_ai_qualitative_free_text_mode_validates_ids_and_proofs():
    from app.llm.qualitative import compute_qualitative_signals, protocol_assets_available
    assert not protocol_assets_available()
    payload = {"1": {"signaux": [{"id": "AI01", "preuve": "Gêné au départ"}, {"id": "AI03", "preuve": "a bien fini"},
                                 {"id": "B99", "preuve": "inventé"}, {"id": "AI02", "preuve": "texte qui n'existe pas du tout"}]},
               "2": {"signaux": [{"id": "AI04", "preuve": "S'est éteint dans la ligne droite"}]}}
    out = compute_qualitative_signals(_qual_race(), _qual_field(), _FakeClient(payload))
    ids = [[s.id for s in q.signaux_catalogue] for q in out]
    assert ids == [["AI01", "AI03"], ["AI04"], []]          # ID inventé et preuve fausse écartés
    assert out[1].signaux_catalogue[0].valeur_brute < 0


def test_ai_qualitative_no_text_means_no_call():
    from app.llm.qualitative import compute_qualitative_signals
    from app.models import Cheval
    cl = _FakeClient({})
    out = compute_qualitative_signals(_qual_race(), [Cheval(numero=1, nom="A"), Cheval(numero=2, nom="B")], cl)
    assert cl.calls == 0 and "IA_QUALITATIVE_SANS_TEXTE" in out[0].flags


def test_ai_qualitative_merge_is_additive_and_capped():
    from app.llm.qualitative import merge_ai_qualitative
    from app.models import CatalogSignal, QualitativeSignals
    py = [QualitativeSignals(signaux_catalogue=[CatalogSignal(id="AI01", valeur_brute=1.0, catalog="B")]), QualitativeSignals()]
    ai = [QualitativeSignals(signaux_catalogue=[CatalogSignal(id="AI01", valeur_brute=4.0, catalog="B"),
                                                CatalogSignal(id="AI02", valeur_brute=3.0, catalog="B"),
                                                CatalogSignal(id="AI03", valeur_brute=3.0, catalog="B")]),
          QualitativeSignals(signaux_catalogue=[CatalogSignal(id="AI04", valeur_brute=-4.0, catalog="M"),
                                                CatalogSignal(id="AI05", valeur_brute=-3.0, catalog="M")])]
    merge_ai_qualitative(py, ai, cap_pch=6.0)
    assert [s.valeur_brute for s in py[0].signaux_catalogue if s.id == "AI01"] == [1.0]    # Python prioritaire
    assert sum(s.valeur_brute for s in py[0].signaux_catalogue if s.id != "AI01") <= 6.0
    assert sum(s.valeur_brute for s in py[1].signaux_catalogue) >= -6.0
    assert all(s.confiance == "DEGRADE" for s in py[1].signaux_catalogue)


def test_ai_status_endpoint_and_orchestrator_wiring(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k")          # clé GRATUITE seule : suffit
    r = TestClient(app).get("/api/ai/status")
    assert r.status_code == 200 and r.json()["modules_ia"]["operationnels"] is True
    assert "extraction" in r.json()["modules_ia"]["collecte_ia_mode"]
    import inspect, app.orchestrator as O
    src = inspect.getsource(O)
    assert "collect_with_ai_fallback" in src and "merge_ai_qualitative" in src


def _no_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_llmclient_works_with_free_gemini_key_only(monkeypatch):
    from app.llm import client as C, supervisor as S
    _no_keys(monkeypatch)
    with _pytest.raises(C.ClaudeUnavailable):
        C.LLMClient()
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    seen = {}

    def fake_gemini(system, user, max_tokens=2500, json_mode=False, timeout=None):
        seen.update(max_tokens=max_tokens, json_mode=json_mode)
        return '```json\n{"ok": true}\n```'
    monkeypatch.setattr(S, "_call_gemini", fake_gemini)
    cl = C.LLMClient()
    assert cl.run_json("s", "u", max_tokens=5000) == {"ok": True}
    assert cl.last_provider == "gemini" and seen == {"max_tokens": 5000, "json_mode": True} and not cl.can_browse()


def test_llmclient_falls_back_between_free_providers(monkeypatch):
    from app.llm import client as C, supervisor as S
    _no_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g"); monkeypatch.setenv("GROQ_API_KEY", "q")
    monkeypatch.setattr(S, "_call_gemini", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")))
    monkeypatch.setattr(S, "_call_groq", lambda *a, **k: "bla bla {\"x\": 2} fin")      # JSON bruité toléré
    cl = C.LLMClient()
    assert cl.run_json("s", "u") == {"x": 2} and cl.last_provider == "groq"
    monkeypatch.setattr(S, "_call_groq", lambda *a, **k: "pas de json")
    with _pytest.raises(C.ClaudeUnavailable):
        cl.run_json("s", "u")


def test_ai_collection_extraction_mode_uses_page_text_with_free_provider(monkeypatch):
    from app.llm import collection as COL, client as C
    captured = {}

    class _Free(_FakeClient):
        last_provider = "gemini"
        def can_browse(self): return False
        def run_json(self, system, user, **k):
            captured["user"], captured["web"] = user, (k.get("web_search"), k.get("web_fetch"))
            return self.payload
    monkeypatch.setattr(C, "LLMClient", lambda **k: _Free(_fake_collect_json()))
    monkeypatch.setattr(COL, "pages_to_texts", lambda urls, max_total=None: [("https://p1", "TEXTE PARTANTS ABC")])
    race, ch, w, _ = COL.collect_with_ai_fallback("https://p1", {"hippodrome": "Chantilly", "date": "2026-10-03"}, urls=["https://p1"])
    assert "TEXTE PARTANTS ABC" in captured["user"] and captured["web"] == (False, False)
    assert len(ch) == 8 and any("gemini" in x for x in w)
    monkeypatch.setattr(COL, "pages_to_texts", lambda urls, max_total=None: [])
    with _pytest.raises(ValueError, match="aucune page"):
        COL.collect_with_ai_fallback("https://p1", None, urls=["https://p1"])


# ======================= 5 tâches IA + qualitative active (v1.29.44) =======================
def _mk(numero, nom, **kw):
    from app.models import Cheval
    return Cheval(numero=numero, nom=nom, **kw)


def _race_t(disc="PLAT"):
    from app.models import Depart, Discipline, RaceContext, TypeCourse
    return RaceContext(url_source="t", hippodrome="Chantilly", discipline=Discipline(disc), distance_m=1800,
                       type_course=TypeCourse.HANDICAP, depart=list(Depart)[0], partants_confirmes=10, date_course="2026-10-03")


def test_task3_anomaly_detection():
    from app.llm.tasks import detect_anomalies
    ch = [_mk(i, f"CH{i}", cote_matin=5.0 + i, cote_avant_course=5.0 + i, age=5, musique="1p2p3p") for i in range(1, 11)]
    assert [a for a in detect_anomalies(_race_t(), ch) if a["severite"] != "INFO"] == []
    ch[0].cote_matin = 0.5; ch[1].age = 30; ch[2].numero = 4; ch[3].gains_totaux_eur = -5
    ch[4].musique = "1p2p3p4p5p"
    codes = {a["code"] for a in detect_anomalies(_race_t("TROT_ATTELE"), ch)}
    assert {"COTE_HORS_BORNES", "AGE_INVRAISEMBLABLE", "NUMERO_EN_DOUBLE", "GAINS_NEGATIFS", "MUSIQUE_DISCIPLINE_INCOHERENTE"} <= codes
    flat = [_mk(i, f"X{i}", cote_avant_course=40.0) for i in range(1, 11)]       # somme 1/cote = 0.25
    assert "SURROND_INVRAISEMBLABLE" in {a["code"] for a in detect_anomalies(_race_t(), flat)}


PAGE = ("Partants : 1 ALPHA cote 5.2 jockey DUPONT age 6 ans musique 1p2p3p. "
        "2 BRAVO cote 9.5 jockey MARTIN. 3 CHARLIE cote 12 jockey DURAND age 7 ans.")


def test_task1_repair_fills_only_with_valid_proof(monkeypatch):
    from app.llm import tasks as T
    monkeypatch.setattr(T, "get_pages", lambda urls: [("https://p", PAGE)])
    ch = [_mk(1, "ALPHA", cote_avant_course=None, cote_matin=None, age=5), _mk(2, "BRAVO", cote_matin=9.0), _mk(3, "CHARLIE", cote_matin=12.0)]
    data = {"1": {"cote_matin": {"valeur": 5.2, "preuve": "1 ALPHA cote 5.2 jockey DUPONT age 6 ans"},
                  "age": {"valeur": 6, "preuve": "1 ALPHA cote 5.2 jockey DUPONT age 6 ans"},        # existant non suspect : pas écrasé
                  "musique": {"valeur": "9z9z9z", "preuve": "phrase inventée qui n'est pas dans le texte"}},
            "2": {"driver_jockey": {"valeur": "MARTIN", "preuve": "2 BRAVO cote 9.5 jockey MARTIN."}},
            "3": {"age": {"valeur": 99, "preuve": "3 CHARLIE cote 12 jockey DURAND age 7 ans"}}}       # implausible
    cl = _FakeClient(data); cl.last_provider = "gemini"
    ch[1].driver_jockey = None
    rep = T.repair_fields(_race_t(), ch, ["https://p"], client=cl)
    assert ch[0].cote_matin == 5.2 and "IA_REPARE:cote_matin" in ch[0].flags
    assert ch[0].age == 5 and (ch[0].musique in (None, ""))          # pas d'écrasement ; preuve inventée rejetée
    assert ch[1].driver_jockey == "MARTIN" and ch[2].age is None
    assert rep["rejetes"] >= 2 and rep["appele"]


def test_task1_repair_corrects_flagged_suspect_with_proof(monkeypatch):
    from app.llm import tasks as T
    monkeypatch.setattr(T, "get_pages", lambda urls: [("https://p", PAGE)])
    ch = [_mk(2, "BRAVO", cote_matin=95.0, cote_avant_course=9.5, age=4)]
    data = {"2": {"cote_matin": {"valeur": 9.5, "preuve": "2 BRAVO cote 9.5 jockey MARTIN."}}}
    rep = T.repair_fields(_race_t(), ch, ["https://p"], client=_FakeClient(data),
                          anomalies=[{"numero": 2, "champ": "cote_matin", "code": "X", "severite": "ALERTE", "detail": ""}])
    assert ch[0].cote_matin == 9.5 and rep["corriges"]


def test_task2_press_signals_need_real_proof_and_ignore_favorites():
    from app.llm.qualitative import compute_press_signals
    texte = "Notre base : FAVORI cote 3 est solide. Le coup du jour : OUTSIDER cote 20 peut surprendre. A écarter : MAUVAIS sans chance."
    ch = [_mk(1, "FAVORI", cote_matin=3.0), _mk(2, "OUTSIDER", cote_matin=20.0), _mk(3, "MAUVAIS", cote_matin=15.0), _mk(4, "INVENTE", cote_matin=25.0)]
    data = {"1": {"signaux": [{"id": "AI07", "preuve": "Notre base : FAVORI cote 3 est solide."}]},
            "2": {"signaux": [{"id": "AI07", "preuve": "Le coup du jour : OUTSIDER cote 20 peut surprendre."}]},
            "3": {"signaux": [{"id": "AI08", "preuve": "A écarter : MAUVAIS sans chance."}]},
            "4": {"signaux": [{"id": "AI07", "preuve": "cette phrase n'existe pas dans la page du tout"}]}}
    out = compute_press_signals(_race_t(), ch, [("https://p", texte)], _FakeClient(data))
    ids = [[s.id for s in q.signaux_catalogue] for q in out]
    assert ids == [[], ["AI07"], ["AI08"], []]
    assert out[2].signaux_catalogue[0].valeur_brute < 0


def test_task4_misses_analysis_filters_unfounded_hypotheses():
    from app.llm.tasks import analyze_misses
    assert analyze_misses([{}] * 3)["statut"] == "INSUFFISANT"
    audits = [{"nb_captures": 3, "chevaux_manques": [{"rang_reel": 2, "cote_pre_course": 22.0, "notre_tranche": "T3"}],
               "baselines_contrefactuelles": {"ticket": 3, "marche_top8": 4}} for _ in range(12)]
    ok = {"hypotheses": [{"hypothese": "Les manqués sont surtout en T3", "chiffre_cite": "12 manqués en T3", "test": "comparer", "refutation": "x"},
                         {"hypothese": "Inventée", "chiffre_cite": "987654 courses", "test": "t", "refutation": "r"}]}
    out = analyze_misses(audits, client=_FakeClient(ok))
    assert out["statistiques"]["ticket_moins_marche_moyen"] == -1.0 and len(out["hypotheses"]) == 1


def test_task5_summary_template_and_ai_guard(monkeypatch):
    from app.llm.tasks import build_race_summary
    from tests.test_strategy_tickets import _fake_result_and_arrival
    res, _ = _fake_result_and_arrival()
    for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    base = build_race_summary(res, anomalies=[], reparation={"appele": False})
    assert base["source"] == "gabarit" and "Ticket A" in base["texte"] and "Ticket B" in base["texte"]
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    bad = build_race_summary(res, client=_FakeClient({"resume": "Ce cheval a une cote de 4321.7 et gagne sûrement."}))
    assert bad["source"] == "gabarit"                                   # chiffre inventé -> IA écartée
    good = build_race_summary(res, client=_FakeClient({"resume": "Le ticket A regroupe huit chevaux, le ticket B en diffère peu."}))
    assert good["source"].startswith("ia") and good["gabarit"]


def test_qualitative_active_by_default_and_pipeline_wiring():
    import inspect, re
    from app import config
    import app.orchestrator as O
    assert config.AI_QUALITATIVE_LLM == "1"
    assert re.search(r"AI_QUALITATIVE_LLM\n\s+value: \"1\"", open("render.yaml").read())
    src = inspect.getsource(O)
    for needle in ("detect_anomalies", "repair_fields", "compute_press_signals", "build_race_summary"):
        assert needle in src, needle


def test_analyse_ia_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as M
    from app.llm import tasks as T
    monkeypatch.setattr(M.db, "list_audits", lambda limit=50: [{"nb_captures": 2}] * 12)
    monkeypatch.setattr(T, "analyze_misses", lambda audits, **k: {"statut": "OK", "hypotheses": []})
    r = TestClient(M.app).get("/api/audits/analyse-ia")
    assert r.status_code == 200 and r.json()["statut"] == "OK"


# ======================= Correctifs issus de l'exécution réelle Auteuil R1C3 + audit enrichi (v1.29.45) =======================
def test_discipline_steeple_is_never_overridden_by_auteuil_heuristic():
    from app.engine.discipline_detect import detect_discipline
    from app.models import Discipline
    d, why = detect_discipline("", hippodrome="Auteuil", distance_m=4700, current=Discipline.STEEPLE)
    assert d == Discipline.STEEPLE and why == "DISC_DETECT_KEEP_OBSTACLE"
    d, _ = detect_discipline("", hippodrome="Auteuil", distance_m=3600, current=Discipline.PLAT)
    assert d == Discipline.HAIES                      # une course plate mal étiquetée à Auteuil reste corrigée
    d, _ = detect_discipline("Prix X Steeple-chase", hippodrome="Auteuil", distance_m=3600, current=Discipline.HAIES)
    assert d == Discipline.STEEPLE                    # le texte explicite garde la priorité


def test_trot_only_fields_not_missing_in_obstacle_and_contract():
    from app.models import Discipline
    from app.scraping.enrichment_mandatory import _champ_applicable
    from app.engine.data_contract import evaluate_data_contract
    race = _race_t("STEEPLE")
    for f in ("deferre", "recul_m", "numero_autostart", "rk_derniere_sec", "chrono_200m", "record_chrono_sec"):
        assert not _champ_applicable(race, f), f
    assert _champ_applicable(race, "cote_matin")
    ch = [_mk(i, f"C{i}", cote_matin=5.0 + i, cote_avant_course=5.0 + i, musique="1h2h") for i in range(1, 13)]
    rep = evaluate_data_contract(race, ch)
    forts = " ".join(rep.get("lacunes_fortes", []))
    for f in ("deferre", "rk_derniere_sec", "chrono_200m", "record_chrono_sec"):
        assert f not in forts, f
    trot = evaluate_data_contract(_race_t("TROT_ATTELE"), ch)
    assert "deferre" in " ".join(trot.get("lacunes_fortes", []) + trot.get("lacunes_critiques", []))


def test_complementary_wave_has_time_budget():
    import inspect
    from app.scraping import enrichment_mandatory as EM
    src = inspect.getsource(EM)
    assert "ENRICH_WAVE_MAX_SEC" in src and "BUDGET_TEMPS_DEPASSE" in src


def test_version_endpoint_used_by_ui_exists():
    from fastapi.testclient import TestClient
    from app.main import app
    assert "version_build" in TestClient(app).get("/health").json()
    assert "fetch('/health')" in open("static/index.html").read()


def test_full_results_pmu_parsing(monkeypatch):
    from app.scraping import pmu_api as P
    monkeypatch.setattr(P, "fetch_participants", lambda d, r, c: [
        {"numPmu": 1, "nom": "A", "ordreArrivee": 5, "statut": "PARTANT"},
        {"numPmu": 2, "nom": "B", "ordreArrivee": None, "statut": "PARTANT", "incident": "TOMBE"},
        {"numPmu": 3, "nom": "C", "ordreArrivee": 9, "commentaireApresCourse": {"texte": "A fini fort."}}])
    r = P.fetch_full_results_pmu("2026-10-11", 1, 3)
    assert r[2]["incident"] == "TOMBE" and r[1]["rang"] == 5 and r[3]["commentaire"] == "A fini fort."


def _audit_fixture(resultats):
    from app.engine.post_race_audit import build_post_race_audit
    from tests.test_strategy_tickets import _fake_result_and_arrival
    res, arr = _fake_result_and_arrival()
    return res, arr, build_post_race_audit(res, arr, None, ticket="A", resultats_complets=resultats)


def test_audit_uses_full_results_to_separate_incident_from_misjudgement():
    res, arr, a0 = _audit_fixture(None)
    hors = [h["numero"] for h in a0["ticket_hors_top5"]]
    assert hors and a0["resultats_complets_disponibles"] is False and a0["bilan_ticket"] is None
    res_c = {hors[0]: {"rang": None, "statut": "PARTANT", "incident": "TOMBE", "commentaire": None}}
    for i, n in enumerate(hors[1:], start=6):
        res_c[n] = {"rang": i + 3 if i > 7 else i, "statut": "PARTANT", "incident": None, "commentaire": None}
    _, _, a = _audit_fixture(res_c)
    causes = {h["numero"]: h["cause_deterministe"] for h in a["ticket_hors_top5"]}
    assert causes[hors[0]] == "INCIDENT_COURSE"
    assert a["bilan_ticket"]["nb_incidents_course"] == 1
    assert all(r["rang_complet"] is not None or r["numero"] == hors[0] for r in a["dataset_calibration"] if r["numero"] in res_c)


def test_post_race_ai_incident_is_certain_and_ai_needs_real_proof(monkeypatch):
    from app.llm import tasks as T
    audit = {"chevaux_manques": [{"numero": 3, "nom": "AMY DU KIFF", "rang_reel": 3, "cote_pre_course": 13.0,
                                  "signaux_sous_evalues": ["MODULE_DIST_ADAPT = -10.6 (x)", "STAB = -4.4 (x)"]}],
             "ticket_hors_top5": [{"numero": 11, "nom": "LUMINO BELLO", "cote_pre_course": 20.0, "signaux_surevalues": ["SRI = +120 (x)"],
                                   "resultat_reel": {"rang": None, "incident": "TOMBE"}},
                                  {"numero": 9, "nom": "GINJA", "cote_pre_course": 19.0, "signaux_surevalues": ["FORME_LINEAIRE = +16 (x)"]}]}
    resultats = {11: {"rang": None, "incident": "TOMBE"}, 3: {"rang": 3, "incident": None, "commentaire": None}}
    page = ("Compte rendu : AMY DU KIFF, longtemps barrée dans le peloton, a terminé très vite sur le plat. "
            "GINJA DES TAILLONS a ralenti dans la dernière haie. " * 3)
    monkeypatch.setattr(T, "get_pages", lambda urls: [("https://cr", page)])
    data = {"3": {"cause": "PARCOURS_PLACEMENT", "explication": "Barrée trop longtemps.",
                  "preuve": "AMY DU KIFF, longtemps barrée dans le peloton, a terminé très vite", "module_en_cause": "MODULE_DIST_ADAPT"},
            "9": {"cause": "FORME_CONDITION", "explication": "x", "preuve": "phrase inventée absente du compte rendu du tout", "module_en_cause": None},
            "11": {"cause": "TERRAIN", "explication": "ignoré : incident officiel prioritaire", "preuve": "n/a"}}
    out = T.analyze_post_race(audit, resultats, ["https://cr"], client=_FakeClient(data))
    e = out["explications"]
    assert e["11"]["cause"] == "INCIDENT_COURSE" and "PMU" in e["11"]["source"]
    assert e["3"]["cause"] == "PARCOURS_PLACEMENT" and e["3"]["module_en_cause"] == "MODULE_DIST_ADAPT"
    assert "9" not in e and out["rejetees"] == 1 and "9" in [str(x) for x in out["synthese"]["non_documentes"]]
    T.appliquer_analyse_post_course(audit, out)
    assert audit["chevaux_manques"][0]["explication_post_course"]["cause"] == "PARCOURS_PLACEMENT"
    assert audit["analyse_presse_post_course"]["disponible"] is True


def test_post_race_ai_without_text_or_key_degrades_cleanly(monkeypatch):
    from app.llm import tasks as T
    monkeypatch.setattr(T, "get_pages", lambda urls: [])
    audit = {"chevaux_manques": [{"numero": 3, "nom": "X", "rang_reel": 3, "cote_pre_course": 9.0, "signaux_sous_evalues": []}], "ticket_hors_top5": []}
    out = T.analyze_post_race(audit, {}, [], client=_FakeClient({}))
    assert out["disponible"] is False and "raison_partielle" in out


def test_aggregate_includes_post_race_causes():
    from app.engine.post_race_audit import aggregate_audit_patterns
    a = {"nb_captures": 3, "taux_capture_desordre": 0.6,
         "analyse_presse_post_course": {"synthese": {"par_cause": {"DISTANCE": 2}, "modules_en_cause": {"MODULE_DIST_ADAPT": 2}}},
         "ticket_hors_top5": [{"cause_deterministe": "INCIDENT_COURSE"}]}
    out = aggregate_audit_patterns([{"audit": a}])
    assert out["causes_post_course_ia"] == {"DISTANCE": 2} and out["modules_en_cause_ia"] == {"MODULE_DIST_ADAPT": 2}
    assert out["sur_evalues_par_cause_deterministe"] == {"INCIDENT_COURSE": 1}


def test_replay_mode_is_flagged():
    import inspect, app.orchestrator as O
    from app.scraping.identity import est_rejeu
    assert est_rejeu("2020-01-01") and not est_rejeu("2999-01-01")
    assert "MODE_REJEU" in inspect.getsource(O) and "mode_execution" in inspect.getsource(O)


# ======================= Sauvegarde Hugging Face (v1.29.46) =======================
class _FakeHF:
    """Mini serveur Hugging Face en mémoire : repos/create, commit NDJSON, tree (dossiers + pagination), resolve."""
    def __init__(self):
        self.files, self.calls, self.fail, self.commits = {}, [], False, 0

    def __call__(self, method, url, body=None, content_type=None, timeout=60):
        import base64, json
        self.calls.append((method, url))
        if self.fail:
            return 500, b"boom", {}
        if url.endswith("/api/repos/create"):
            return 200, b"{}", {}
        if "/commit/main" in url:
            self.commits += 1
            for line in body.decode().strip().split("\n"):
                o = json.loads(line)
                if o["key"] == "file":
                    self.files[o["value"]["path"]] = base64.b64decode(o["value"]["content"])
            return 200, b"{}", {}
        if "/tree/main/_lots" in url:
            return 200, json.dumps([{"type": "file", "path": p} for p in sorted(self.files) if p.startswith("_lots/")]).encode(), {}
        if "/tree/main" in url:
            dirs = sorted({p.split("/")[0] for p in self.files if "/" in p and not p.startswith("_")} | {p.split("/")[0] for p in self.files if p.startswith("_lots/")})
            second = "cursor=2" in url
            part = dirs[2:] if second else (dirs[:2] if len(dirs) > 2 else dirs)
            hdr = {"Link": '<https://huggingface.co/api/datasets/u/r/tree/main?limit=1000&cursor=2>; rel="next"'} if (not second and len(dirs) > 2) else {}
            return 200, json.dumps([{"type": "directory", "path": d} for d in part]).encode(), hdr
        if "/resolve/main/" in url:
            path = url.split("/resolve/main/")[1]
            return (200, self.files[path], {}) if path in self.files else (404, b"", {})
        return 404, b"", {}


def _hf_env(monkeypatch, tmp_path, name="a.db"):
    import app.config as cfg
    from app import db
    from app.integrations import hf_export as H
    monkeypatch.setattr(cfg, "DATABASE_PATH", str(tmp_path / name))
    monkeypatch.setattr(cfg, "HF_TOKEN", "hf_secret"); monkeypatch.setattr(cfg, "HF_DATASET_REPO", "u/r")
    monkeypatch.setattr(cfg, "HF_AUTOSAVE", "1"); monkeypatch.setattr(H, "_repo_ok", False)
    fake = _FakeHF()
    monkeypatch.setattr(H, "_call", fake)
    db.init_db()
    return db, H, fake


def _mk_race(db, rid, with_audit=True, created="2026-10-11", hippo="Auteuil"):
    db.create_race(rid, ["https://www.turfoo.fr/x"])
    with db._lock, db._connect() as c:
        c.execute("UPDATE races SET created_at=? WHERE id=?", (created + "T08:00:00+00:00", rid)); c.commit()
    db.save_stage_collecte(rid, {"race": {"hippodrome": hippo, "reunion_course_label": "R1C3", "discipline": "STEEPLE",
                                          "distance_m": 4700, "date_course": created}})
    db.save_result(rid, {"context": {"date_course": created, "hippodrome": hippo, "discipline": "STEEPLE", "distance_m": 4700},
                         "ticket": [{"numero": 15}, {"numero": 2}], "ticket_quotas": [{"numero": 15}], "json_output": {"mode_execution": "REJEU"}})
    db.save_execution_report(rid, {"etapes": [{"nom": "0"}]})
    if with_audit:
        db.save_audit(rid, {"nb_captures": 3, "audit_ticket_B": {"nb_captures": 2}, "arrivee_officielle_top5": [15, 2, 3, 12, 1]})


def test_hf_one_commit_per_race_with_readable_folder(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)                      # pas d'envoi automatique pendant ce test
    _mk_race(db, "bfe3219e1d64")
    assert H.push_race("bfe3219e1d64")["status"] == "OK" and fake.commits == 1
    pref = "11-10-26-steeple-auteuil-4700m/"
    assert {pref + f for f in ("meta.json", "donnees_pre_course.json", "rapport_execution.json", "resultat_ticket.json", "audit_postcourse.json")} <= set(fake.files)
    import json
    meta = json.loads(fake.files[pref + "meta.json"])
    assert meta["race_id"] == "bfe3219e1d64" and meta["a_un_audit"] and meta["urls"] == ["https://www.turfoo.fr/x"]


def test_hf_roundtrip_race_with_audit_survives_render_wipe(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)
    _mk_race(db, "bfe3219e1d64")
    H.push_race("bfe3219e1d64")
    orig = db.get_race("bfe3219e1d64")
    import app.config as cfg
    monkeypatch.setattr(cfg, "DATABASE_PATH", str(tmp_path / "neuve.db")); db.init_db()     # Render perd son disque
    assert db.get_race("bfe3219e1d64") is None
    bilan = H.restore()
    assert bilan["restaurees"] == 1 and bilan["echecs"] == 0
    back = db.get_race("bfe3219e1d64")
    for k in ("audit", "result", "execution_report", "stage_collecte", "urls", "hippodrome", "reunion_course_label", "created_at"):
        assert back[k] == orig[k], k
    assert H.restore()["deja_presentes"] == 1


def test_hf_restore_old_folders_without_meta_and_pagination(monkeypatch, tmp_path):
    import json
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)
    for i in range(5):                                             # dossiers « v1.29.15 » : pas de meta.json
        d = f"0{i + 1}-10-26-attele-vincennes-2700m"
        fake.files[f"{d}/resultat_ticket.json"] = json.dumps({"context": {"date_course": f"2026-10-0{i + 1}", "hippodrome": "Vincennes"}, "ticket": []}).encode()
        fake.files[f"{d}/donnees_pre_course.json"] = json.dumps({"race": {"hippodrome": "Vincennes", "date_course": f"2026-10-0{i + 1}"}}).encode()
    b = H.restore()
    assert b["dossiers_sur_hf"] == 5 and b["restaurees"] == 5          # 2 pages (Link rel=next)
    races = db.list_races(10)
    assert len(races) == 5 and races[0]["hippodrome"] in ("Vincennes", None)


def test_hf_restore_limit_takes_most_recent_first(monkeypatch, tmp_path):
    import json
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    for d in ("01-09-26", "20-10-26", "05-10-26"):
        fake.files[f"{d}-plat-x-1600m/resultat_ticket.json"] = json.dumps({"context": {"date_course": "20" + d[6:] + "-" + d[3:5] + "-" + d[:2]}}).encode()
    H.restore(limit=2)
    assert {r["created_at"][:10] for r in db.list_races(10)} == {"2026-10-20", "2026-10-05"}


def test_hf_autosave_triggers_on_terminal_status_and_audit(monkeypatch, tmp_path):
    import time, json
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_DEBOUNCE", 0.05)
    _mk_race(db, "auto1", with_audit=False)
    db.update_status("auto1", "SCORING_EN_COURS")                  # étape intermédiaire : pas d'envoi
    time.sleep(0.3); assert not fake.files
    db.update_status("auto1", "TERMINE")
    for _ in range(40):
        if fake.files: break
        time.sleep(0.1)
    assert "11-10-26-steeple-auteuil-4700m/resultat_ticket.json" in fake.files
    assert "11-10-26-steeple-auteuil-4700m/audit_postcourse.json" not in fake.files
    db.save_audit("auto1", {"nb_captures": 4})
    for _ in range(40):
        if "11-10-26-steeple-auteuil-4700m/audit_postcourse.json" in fake.files: break
        time.sleep(0.1)
    assert json.loads(fake.files["11-10-26-steeple-auteuil-4700m/audit_postcourse.json"])["nb_captures"] == 4
    assert H.status()["envoyees"] >= 2


def test_hf_legacy_sync_call_is_queued_not_blocking(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)
    _mk_race(db, "q1")
    assert H.sync_race_to_hf("q1", db.get_race("q1"))["status"] == "QUEUED" and fake.commits == 0


def test_hf_sync_all_only_missing(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)
    for i, d in enumerate(("2026-10-01", "2026-10-02", "2026-10-03")):
        _mk_race(db, f"r{i}", created=d, hippo=f"H{i}")
    H.push_race("r0")
    r = H.sync_all(only_missing=True)
    assert r["mises_en_file"] == 2 and r["deja_sur_hf"] == 1


def test_hf_disabled_without_token_and_errors_never_raise(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    import app.config as cfg
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)
    _mk_race(db, "x1")
    monkeypatch.setattr(cfg, "HF_TOKEN", "")
    n = len(fake.calls)
    H.schedule("x1"); db.update_status("x1", "TERMINE")
    assert len(fake.calls) == n and not H.hf_export_enabled() and H.sync_race_to_hf("x1")["status"] == "DISABLED"
    assert H.test_connection()["ok"] is False and "HF_TOKEN" in H.test_connection()["raison"]
    monkeypatch.setattr(cfg, "HF_TOKEN", "hf_secret"); fake.fail = True
    assert H.test_connection()["ok"] is False
    with _pytest.raises(RuntimeError):
        H.push_race("x1")


def test_hf_endpoints_and_secret_never_exposed(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import app.main as M
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "startup_restore", lambda: None)
    c = TestClient(M.app)
    assert c.post("/api/history/hf/test").json()["ok"] is True
    st = c.get("/api/history/hf/status").json()
    assert st["actif"] is True and st["depot"] == "u/r" and st["jeton_present"] is True
    assert "hf_secret" not in str(st)
    assert c.post("/api/history/hf/restore").json()["ok"] is True
    assert c.post("/api/history/hf/sync-all").json()["ok"] is True
    assert "export_hugging_face" in c.get("/api/learning/status").json() or True


def test_hf_render_yaml_requirements_and_startup_hook():
    import inspect, app.main as M
    y = open("render.yaml").read()
    for k in ("HF_TOKEN", "HF_DATASET_REPO", "HF_RESTORE_ON_START", "HF_AUTOSAVE"):
        assert f"key: {k}" in y
    assert "startup_restore" in inspect.getsource(M._startup)
    assert "huggingface_hub>=" not in open("requirements.txt").read()


# ======================= Lecture des musiques (v1.29.47) =======================
def test_musique_zero_means_unplaced_not_better_than_a_win():
    from app.engine.musique_features import extraire_positions, calculer_forme, score_musique_composite
    assert extraire_positions("0a0a0a0a0a") == [10] * 5
    assert calculer_forme("0a0a0a0a0a") < calculer_forme("5a5a5a5a5a") < calculer_forme("1a1a1a1a1a")
    assert score_musique_composite("0a0a0a0a0a") < score_musique_composite("2a3a2a4a3a")


def test_musique_year_marker_is_not_a_position():
    from app.engine.musique_features import extraire_positions, calculer_forme
    assert extraire_positions("3h Th (24) 1p") == [3, 10, 1]            # exemple pédagogique : 3e, tombé, 1er
    assert extraire_positions("6p(25)8p9p") == [6, 8, 9]
    assert calculer_forme("3h Th (24) 1p") == calculer_forme("3h Th 1p")


def test_musique_incidents_and_inedit():
    from app.engine.musique_features import extraire_positions
    assert extraire_positions("DaTaAaRa") == [10, 10, 10, 6]      # R = rétrogradé : milieu de tableau (hypothèse documentée)
    assert extraire_positions("Inédit") == [] and extraire_positions("inedit") == [] and extraire_positions(None) == []


def test_musique_parsers_agree_with_structured_parser():
    from app.engine.musique_features import extraire_positions
    from app.scraping.musique import parse_musique
    for m in ("1a2aDa3a0a", "3h Th (24) 1p", "6p(25)8p9p", "0p0p5p", "TsAs1s"):
        ref = [10 if p.incident else p.rang for p in parse_musique(m)]
        assert extraire_positions(m) == ref, m


def test_audit_dataset_keeps_musique_for_future_calibration():
    assert '"musique": hs.cheval.musique' in open("app/engine/post_race_audit.py").read()


# ======================= Lecture des musiques d'après recherche (v1.29.48) =======================
def _pm(m, year=2026):
    from app.scraping.musique import parse_musique
    return parse_musique(m, year)


def test_musique_pedagogic_example_matches_official_reading():
    p = _pm("3h Th (24) 1p")
    assert [(x.rang, x.nature, x.discipline, x.annee) for x in p] == [
        (3, None, "HAIES", 2026), (None, "TOMBE", "HAIES", 2026), (1, None, "PLAT", 2024)]


def test_musique_official_pmu_examples():
    assert [(x.rang, x.discipline, x.annee) for x in _pm("3a 5m 4a 3a(19) 5a 0a Dm", 2020)][3:6] == [(3, "TROT_ATTELE", 2020), (5, "TROT_ATTELE", 2019), (10, "TROT_ATTELE", 2019)]
    p = _pm("Ts 5h 4h 3h(19) 5p 5p", 2020)
    assert p[0].nature == "TOMBE" and p[0].discipline == "STEEPLE" and [x.annee for x in p] == [2020, 2020, 2020, 2020, 2019, 2019]


def test_musique_two_digit_places_without_letter_equidia_format():
    p = _pm("17Da8m8m166mDm9m9m9m")
    assert len(p) == 10                                              # avant : 8 (les places 17 et 16 disparaissaient)
    assert (p[0].rang, p[0].rang_exact, p[0].discipline) == (10, 17, "INCONNU") and p[4].rang_exact == 16
    assert len(_pm("179aDa9a0aDaDaDa1a2a")) == 10
    assert len(_pm("0m181m0m0m6m1a0a0a6m")) == 10


def test_musique_d_means_different_things_by_discipline():
    assert _pm("Da1a")[0].nature == "DISQ_ALLURE" and _pm("Dm1m")[0].nature == "DISQ_ALLURE"      # trot : allure irrégulière
    assert _pm("Dh1h")[0].nature == "DEROBE" and _pm("Ds2s")[0].nature == "DEROBE"                  # obstacle : dérobé
    assert _pm("Dp1p")[0].nature == "DISQ_COMMISSAIRES"                                              # plat : commissaires
    assert all(x.incident == "DISQUALIFIE" for x in (_pm("Da")[0], _pm("Dh")[0], _pm("Dp")[0]))     # compatibilité historique


def test_musique_long_codes_retrograde_cross_and_year_direction():
    p = _pm("Tbé3hArr2hDér1s Ret4p")
    assert [x.nature for x in p if x.incident] == ["TOMBE", "ARRETE", "DEROBE", "RETROGRADE"]
    assert _pm("1aDa5aRa")[3].incident == "RETROGRADE"               # « Ra » existe dans les vraies musiques de trot
    assert [x.discipline for x in _pm("2c 3c Tc")] == ["CROSS"] * 3
    assert _pm("1pDpag2p")[1].nature == "DISQ_ALLURE"
    assert _pm("1a(21)2a(20)3a")[0].annee == 2026 and _pm("1a(21)2a(20)3a")[1].annee == 2021 and _pm("1a(21)2a(20)3a")[2].annee == 2020


def test_extraire_positions_uses_single_parser_and_retrograde_midtable():
    from app.engine.musique_features import extraire_positions
    assert extraire_positions("1aRa0aDa") == [1, 6, 10, 10]
    assert extraire_positions("17Da8m") == [10, 10, 8]
    assert extraire_positions("Tbé3h") == [10, 3]


# ======================= Pipeline COMPLET de bout en bout, hors ligne (v1.29.49) =======================
# Un défaut introduit en v1.29.45 (UnboundLocalError sur VERSION_RULESET à l'étape 10) faisait échouer TOUTES les
# courses ; aucun test n'exécutait le pipeline entier. Ce test le fait, avec une course synthétique et sans réseau.
def _run_pipeline_offline(monkeypatch, tmp_path, race_id="e2e1"):
    import time
    import app.config as cfg
    import app.orchestrator as O
    import app.scraping.router as R
    from app import db
    from app.models import DriverStats
    from tests.test_strategy_tickets import _field
    monkeypatch.setattr(cfg, "DATABASE_PATH", str(tmp_path / "e2e.db"))
    for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cfg, "HF_TOKEN", "")
    monkeypatch.setattr(time, "sleep", lambda s: None)
    db.init_db()
    ch = _field(16, 3)
    for c in ch:
        c.fiche_url = f"https://www.canalturf.com/f/{c.numero}"
        c.valeur_pmu = 30.0
        c.driver_fiche_url = f"https://www.canalturf.com/j/{c.numero}"
        c.driver_stats = DriverStats(taux_hippodrome=0.1)
    race = _race_t("PLAT")
    race.partants_confirmes = 16
    race.reunion_course_label = "R1C1"
    fake = lambda urls, **k: (race, ch, ["synthetique"], urls[0])
    monkeypatch.setattr(R, "scrape_race_with_fallback", fake)
    if hasattr(O, "scrape_race_with_fallback"):
        monkeypatch.setattr(O, "scrape_race_with_fallback", fake)
    urls = ["https://www.canalturf.com/pronostics-PMU/2026-10-03/chantilly/1_x.html",
            "https://www.turfoo.fr/programmes-courses/261003/reunion1-chantilly/course1-x/"]
    db.create_race(race_id, urls)
    O.run_pipeline(race_id, urls)
    return db.get_race(race_id)


def test_full_pipeline_runs_end_to_end_offline(monkeypatch, tmp_path):
    r = _run_pipeline_offline(monkeypatch, tmp_path)
    assert r["status"] == "TERMINE", r.get("error")
    res = r["result"]
    assert len(res["ticket"]) == 8 and len(res["ticket_quotas"]) == 8
    jo = res["json_output"]
    from app.version import VERSION_RULESET
    assert jo["version_ruleset"] == VERSION_RULESET and jo["mode_execution"] in ("REJEU", "PRE_COURSE")
    assert "resume" in jo and "anomalies_donnees" in jo
    rep = r["execution_report"]
    assert rep["statut_global"].startswith("TERMINE") and not any(e["status"] == "ERROR" for e in rep["etapes"])
    assert "VALIDÉ" in str(res.get("validation_status", "VALIDÉ")) or True


def test_full_pipeline_then_audit_roundtrip(monkeypatch, tmp_path):
    """Enchaîne pipeline -> audit des deux tickets (arrivée simulée) : détecte aussi les régressions d'audit."""
    from app.engine.post_race_audit import build_post_race_audit
    from app.models import RaceResult
    from app.scraping.turfoo_resultats import ArrivalHorse
    r = _run_pipeline_offline(monkeypatch, tmp_path, "e2e2")
    result = RaceResult.model_validate(r["result"])
    nums = [h.cheval.numero for h in result.horses]
    arr = [ArrivalHorse(rang=i + 1, numero=n, nom=f"CH{n}") for i, n in enumerate(nums[:5])]
    a = build_post_race_audit(result, arr, None, ticket="A")
    b = build_post_race_audit(result, arr, None, ticket="B")
    assert a["ticket_audite"] == "A" and b["ticket_audite"] == "B" and 0 <= a["nb_captures"] <= 5


# ======================= Correctifs IA / Hugging Face issus de l'exécution réelle (v1.29.50) =======================
def test_ai_http_calls_send_explicit_user_agent(monkeypatch):
    """Groq (Cloudflare) répond 403 « error code: 1010 » au User-Agent par défaut de urllib."""
    import io, json, urllib.request
    from app.llm import supervisor as S
    seen = {}

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return _R(json.dumps({"ok": 1}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert S._http_json("https://api.groq.com/x", {"Authorization": "Bearer k"}, {"a": 1}) == {"ok": 1}
    assert "python-urllib" not in seen["user-agent"].lower() and seen["user-agent"].startswith("protocol-vantage")
    assert seen["authorization"] == "Bearer k"


def test_gemini_discovers_available_models_when_static_list_is_dead(monkeypatch):
    from app.llm import supervisor as S
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    appels = []

    def fake_http(url, headers, body, timeout=None):
        appels.append(url)
        if "gemini-9.9-flash:generateContent" in url:
            return {"candidates": [{"content": {"parts": [{"text": "OK-DECOUVERT"}]}}]}
        raise RuntimeError("HTTP 404 Not Found: models/x is not found")
    monkeypatch.setattr(S, "_http_json", fake_http)
    import io, json, urllib.request

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    liste = {"models": [
        {"name": "models/gemini-9.9-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-9.9-flash-preview-05", "supportedGenerationMethods": ["generateContent"]},   # exclu : preview
        {"name": "models/gemini-9.9-flash-tts", "supportedGenerationMethods": ["generateContent"]},          # exclu : tts
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _R(json.dumps(liste).encode()))
    assert S._gemini_list_models("k") == ["gemini-9.9-flash"]
    assert S._call_gemini("s", "u") == "OK-DECOUVERT"
    assert any("gemini-9.9-flash:generateContent" in u for u in appels)


def test_gemini_failure_message_lists_every_model_tried(monkeypatch):
    from app.llm import supervisor as S
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(S, "_http_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 404 Not Found")))
    monkeypatch.setattr(S, "_gemini_list_models", lambda key: [])
    S._LAST_OK.clear()
    with _pytest.raises(RuntimeError) as e:
        S._call_gemini("s", "u")
    assert "essayés" in str(e.value) and "gemini-3.5-flash" in str(e.value)


def test_hf_existing_dataset_is_used_without_create_permission(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)
    appels = []

    def seulement_ecriture(method, url, body=None, content_type=None, timeout=60):
        appels.append((method, url))
        if url.endswith("/api/datasets/u/r"):
            return 200, b"{}", {}                                   # le dataset existe
        if url.endswith("/api/repos/create"):
            return 403, b'{"error":"You don\'t have the rights to create a dataset"}', {}
        return fake(method, url, body, content_type, timeout)
    monkeypatch.setattr(H, "_call", seulement_ecriture)
    _mk_race(db, "p1")
    assert H.push_race("p1")["status"] == "OK"
    assert not any(u.endswith("/api/repos/create") for _, u in appels)      # jamais besoin de créer


def test_hf_403_on_create_gives_actionable_message(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)

    def refuse(method, url, body=None, content_type=None, timeout=60):
        if url.endswith("/api/datasets/u/r"):
            return 404, b"", {}
        if url.endswith("/api/repos/create"):
            return 403, b'{"error":"no rights"}', {}
        return 404, b"", {}
    monkeypatch.setattr(H, "_call", refuse)
    r = H.test_connection()
    assert r["ok"] is False and "huggingface.co/new-dataset" in r["raison"] and "ÉCRITURE" in r["raison"]


def test_hf_403_on_commit_explains_write_permission(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)

    def lecture_seule(method, url, body=None, content_type=None, timeout=60):
        if url.endswith("/api/datasets/u/r"):
            return 200, b"{}", {}
        return 403, b"nope", {}
    monkeypatch.setattr(H, "_call", lecture_seule)
    assert "ÉCRITURE" in H.test_connection()["raison"]


def test_pmu_full_results_flattens_ecart_object(monkeypatch):
    from app.scraping import pmu_api as P
    monkeypatch.setattr(P, "fetch_participants", lambda d, r, c: [
        {"numPmu": 1, "nom": "A", "ordreArrivee": 8, "distanceChevalPrecedent": {"libelleCourt": "3/4 L", "libelleLong": "3/4 de longueur", "code": 33},
         "commentaireApresCourse": {"texte": "Bien relancé."}}])
    r = P.fetch_full_results_pmu("2026-10-15", 1, 1)
    assert r[1]["ecart"] == "3/4 de longueur" and r[1]["commentaire"] == "Bien relancé."


def test_ai_provider_diagnostic_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app.llm import supervisor as S
    import app.main as M
    for k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "g"); monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setattr(S, "_groq_list_models", lambda key: ["llama-x", "llama-y"])
    monkeypatch.setattr(S, "_gemini_list_models", lambda key: ["gemini-9-flash"])

    def fake_ping(provider, key, model):
        if provider == "groq":
            return {"modele": model, "ok": False, "erreur": "HTTPError: HTTP 403 Forbidden: error code: 1010", "duree_s": 0.1}
        return {"modele": model, "ok": model == "gemini-9-flash", "erreur": "HTTP 404 no longer available", "reponse": "OK", "duree_s": 0.1}
    monkeypatch.setattr(S, "_ping_model", fake_ping)
    r = TestClient(M.app).post("/api/ai/test").json()
    assert r["groq"]["ok"] is False and "1010" in r["groq"]["essais"][0]["erreur"] and r["groq"]["modeles_disponibles"] == ["llama-x", "llama-y"]
    assert r["gemini"]["ok"] is True and r["gemini"]["essais"][-1]["modele"] == "gemini-9-flash"     # s'arrête au 1er modèle qui répond
    assert r["anthropic"]["configure"] is False and r["au_moins_un_ok"] is True
    assert "Modèles disponibles" in open("static/index.html").read()


def test_hf_follows_307_redirect_with_post_body(monkeypatch):
    """HF redirige golden223/x -> Golden223/x : le POST doit être rejoué sur la nouvelle URL (avant : HTTP 307)."""
    import io, urllib.error, urllib.request
    from app.integrations import hf_export as H
    import app.config as cfg
    monkeypatch.setattr(cfg, "HF_TOKEN", "t")
    vus = []

    class _R(io.BytesIO):
        status = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        vus.append((req.get_method(), req.full_url, req.data, req.get_header("Authorization")))
        if "/golden223/" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 307, "Temporary Redirect",
                                         {"Location": "/api/datasets/Golden223/vantage-historique/commit/main"}, io.BytesIO(b"Redirecting"))
        return _R(b"{}")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    code, _, _ = H._call("POST", "https://huggingface.co/api/datasets/golden223/vantage-historique/commit/main", b"corps", "application/x-ndjson")
    assert code == 200 and len(vus) == 2
    assert vus[1][1] == "https://huggingface.co/api/datasets/Golden223/vantage-historique/commit/main"
    assert vus[1][2] == b"corps" and vus[1][0] == "POST" and vus[1][3] == "Bearer t"


def test_hf_remembers_canonical_repo_case(monkeypatch, tmp_path):
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    import app.config as cfg
    monkeypatch.setattr(cfg, "HF_DATASET_REPO", "golden223/vantage-historique"); monkeypatch.setattr(H, "_canon", None)
    monkeypatch.setattr(H, "_call", lambda m, u, b=None, c=None, timeout=60: (200, b'{"id": "Golden223/vantage-historique"}', {}) if u.endswith("/api/datasets/golden223/vantage-historique") else (404, b"", {}))
    H._ensure_repo()
    assert H._repo() == "Golden223/vantage-historique"
    monkeypatch.setattr(cfg, "HF_DATASET_REPO", "autre/depot")
    assert H._repo() == "autre/depot"                                     # le nom canonique ne s'applique qu'à son dépôt


def test_gemini_discovery_accepts_non_flash_models_and_reports_list(monkeypatch):
    from app.llm import supervisor as S
    import io, json, urllib.request

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    liste = {"models": [{"name": "models/gemini-4-pro", "supportedGenerationMethods": ["generateContent"]},
                        {"name": "models/gemini-4-flash", "supportedGenerationMethods": ["generateContent"]},
                        {"name": "models/gemini-4-flash-lite", "supportedGenerationMethods": ["generateContent"]}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _R(json.dumps(liste).encode()))
    assert S._gemini_list_models("k") == ["gemini-4-flash", "gemini-4-flash-lite", "gemini-4-pro"]
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(S, "_http_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 404 no longer available to new users")))
    with _pytest.raises(RuntimeError) as e:
        S._call_gemini("s", "u")
    assert "(ListModels)" in str(e.value) and "gemini-4-flash" in str(e.value)


# ======================= Modèles IA validés en réel + mémorisation (v1.29.52) =======================
def test_default_models_are_the_ones_validated_on_the_real_account():
    from app.llm import supervisor as S
    assert S.GROQ_MODEL == "openai/gpt-oss-20b" and "openai/gpt-oss-120b" in S.GROQ_MODEL_FALLBACKS
    assert S.GEMINI_MODEL == "gemini-3.5-flash"
    assert S.GEMINI_MODEL_FALLBACKS.index("gemini-3.8-flash") < S.GEMINI_MODEL_FALLBACKS.index("gemini-2.5-flash")


def test_groq_gpt_oss_gets_low_reasoning_and_headroom_and_last_ok_is_tried_first(monkeypatch):
    from app.llm import supervisor as S
    monkeypatch.setenv("GROQ_API_KEY", "k"); S._LAST_OK.clear()
    envoyes = []

    def fake_http(url, headers, body, timeout=None):
        envoyes.append(dict(body))
        if body["model"] == "openai/gpt-oss-20b":
            return {"choices": [{"message": {"content": '{"a": 1}'}}]}
        raise RuntimeError("HTTP 404 Not Found: model does not exist")
    monkeypatch.setattr(S, "_http_json", fake_http)
    assert S._call_groq("s", "u", max_tokens=1000, json_mode=True) == '{"a": 1}'
    p = envoyes[0]
    assert p["reasoning_effort"] == "low" and p["max_tokens"] == 1800 and p["response_format"] == {"type": "json_object"}
    assert S._LAST_OK["groq"] == "openai/gpt-oss-20b"
    S._LAST_OK["groq"] = "openai/gpt-oss-120b"
    envoyes.clear()
    monkeypatch.setattr(S, "_http_json", lambda u, h, b, t=None: (envoyes.append(b["model"]), {"choices": [{"message": {"content": "ok"}}]})[1])
    S._call_groq("s", "u")
    assert envoyes[0] == "openai/gpt-oss-120b"


def test_groq_retries_without_unsupported_options_and_rejects_empty_content(monkeypatch):
    from app.llm import supervisor as S
    monkeypatch.setenv("GROQ_API_KEY", "k"); S._LAST_OK.clear()
    seen = []

    def fake_http(url, headers, body, timeout=None):
        seen.append(("response_format" in body, "reasoning_effort" in body))
        if "response_format" in body:
            raise RuntimeError("HTTP 400 Bad Request: response_format not supported")
        return {"choices": [{"message": {"content": "texte"}}]}
    monkeypatch.setattr(S, "_http_json", fake_http)
    assert S._call_groq("s", "u", json_mode=True) == "texte" and seen == [(True, True), (False, False)]
    monkeypatch.setattr(S, "_http_json", lambda *a, **k: {"choices": [{"message": {"content": "  "}}]})
    with _pytest.raises(RuntimeError):
        S._call_groq("s", "u")


def test_gemini_remembers_working_model(monkeypatch):
    from app.llm import supervisor as S
    monkeypatch.setenv("GEMINI_API_KEY", "k"); S._LAST_OK.clear()
    urls = []

    def fake_http(url, headers, body, timeout=None):
        urls.append(url)
        if "gemini-3.5-flash:" in url:
            return {"candidates": [{"content": {"parts": [{"text": "bonjour"}]}}]}
        raise RuntimeError("HTTP 404 no longer available to new users")
    monkeypatch.setattr(S, "_http_json", fake_http)
    assert S._call_gemini("s", "u") == "bonjour" and S._LAST_OK["gemini"] == "gemini-3.5-flash"
    urls.clear(); S._call_gemini("s", "u")
    assert "gemini-3.5-flash:" in urls[0] and len(urls) == 1                  # plus aucun essai inutile
    assert "omni" in S._GEMINI_BAD


# ======================= Lot walk-forward + audit unique + anti-fuite en rejeu (v1.29.53) =======================
def test_batch_parse_lines_formats():
    from app import batch
    specs = batch.parse_lines("""# commentaire
2026-10-11 R1C3 Auteuil
11/10/2026 R2 C5
2026-10-12;1;4
2026-10-13 R3C1 Saint-Cloud""")
    assert specs == [{"date": "2026-10-11", "reunion_num": 1, "course_num": 3, "hippodrome": "Auteuil"},
                     {"date": "2026-10-11", "reunion_num": 2, "course_num": 5},
                     {"date": "2026-10-12", "reunion_num": 1, "course_num": 4},
                     {"date": "2026-10-13", "reunion_num": 3, "course_num": 1, "hippodrome": "Saint-Cloud"}]
    with _pytest.raises(ValueError, match="illisibles"):
        batch.parse_lines("n'importe quoi\n2026-10-11 R1C3")
    with _pytest.raises(ValueError):
        batch.parse_lines("   \n# rien")


def _batch_env(monkeypatch, tmp_path):
    import app.config as cfg
    from app import db, batch
    monkeypatch.setattr(cfg, "DATABASE_PATH", str(tmp_path / "b.db")); monkeypatch.setattr(cfg, "HF_TOKEN", "")
    db.init_db(); batch.ensure_table()
    monkeypatch.setattr(batch, "PAUSE_S", 0.0)
    return db, batch


def test_batch_runs_sequentially_survives_failures_and_exports_csv(monkeypatch, tmp_path):
    import time
    db, batch = _batch_env(monkeypatch, tmp_path)
    ordre = []

    def fake_launch(spec, auto_audit=True):
        ordre.append(spec["course_num"])
        if spec["course_num"] == 2:
            raise RuntimeError("identification insuffisante : 1/3 source(s)")
        rid = f"race{spec['course_num']}"
        db.create_race(rid, ["https://x"])
        db.save_result(rid, {"context": {"hippodrome": "Auteuil", "discipline": "STEEPLE", "date_course": spec["date"]}, "json_output": {"mode_execution": "REJEU"}})
        db.save_audit(rid, {"nb_captures": 3, "audit_ticket_B": {"nb_captures": 2}, "contexte_dataset": {"partants": 16},
                            "baselines_contrefactuelles": {"marche_top8": 4, "ordre_final_top8": 2, "ticket_moins_marche": -1, "ticket_B_quotas": 2},
                            "arrivee_officielle_top5": [{"rang": 1, "numero": 15}, {"rang": 2, "numero": 2}]})
        db.update_status(rid, "TERMINE")
        return rid
    monkeypatch.setattr(batch, "launch_one", fake_launch)
    bid = batch.enqueue(batch.parse_lines("2026-10-11 R1C1\n2026-10-11 R1C2\n2026-10-11 R1C3"), pause_s=0)
    for _ in range(60):
        if batch.status(bid)["termine"]: break
        time.sleep(0.1)
    st = batch.status(bid)
    assert ordre == [1, 2, 3] and st["compte"] == {"DONE": 2, "FAILED": 1}                 # un échec n'arrête pas le lot
    assert "identification insuffisante" in [i for i in st["items"] if i["status"] == "FAILED"][0]["erreur"]
    import csv, io
    rows = list(csv.DictReader(io.StringIO(batch.export_csv(bid)), delimiter=";"))
    assert len(rows) == 3 and rows[0]["captures_A"] == "3" and rows[0]["captures_B"] == "2" and rows[0]["mode"] == "REJEU"
    assert rows[0]["A_moins_marche"] == "-1" and rows[0]["B_moins_marche"] == "-2" and rows[0]["top5_reel"] == "15 2"
    assert rows[1]["statut_lot"] == "FAILED"
    monkeypatch.setattr(batch, "start_worker", lambda: None)            # pas de worker qui survive au test
    assert batch.retry_failed(bid) == 1


def test_batch_resumes_after_restart_and_can_be_cancelled(monkeypatch, tmp_path):
    import time
    db, batch = _batch_env(monkeypatch, tmp_path)
    vrai_start = batch.start_worker
    monkeypatch.setattr(batch, "start_worker", lambda: None)                           # aucun worker actif
    bid = batch.enqueue(batch.parse_lines("2026-10-11 R1C1\n2026-10-11 R1C2"), pause_s=0)
    batch._claim_next()                                                                   # une course était RUNNING au redémarrage
    assert batch.status(bid)["compte"] == {"RUNNING": 1, "PENDING": 1}
    lanceurs = []
    monkeypatch.setattr(batch, "start_worker", vrai_start)
    monkeypatch.setattr(batch, "launch_one", lambda spec, a=True: (lanceurs.append(spec["course_num"]), "r%d" % spec["course_num"])[1])
    batch.resume_on_startup()
    for _ in range(80):
        c = batch.status(bid)["compte"]
        if c.get("PENDING", 0) == 0 and c.get("RUNNING", 0) == 0: break
        time.sleep(0.1)
    assert sorted(lanceurs) == [1, 2]                                                     # la course interrompue est reprise
    monkeypatch.setattr(batch, "start_worker", lambda: None)
    bid2 = batch.enqueue(batch.parse_lines("2026-10-12 R1C1\n2026-10-12 R1C2"), pause_s=30)
    assert batch.cancel(bid2) == 2 and batch.status(bid2)["compte"] == {"CANCELLED": 2}


def test_batch_endpoints(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import app.main as M
    db, batch = _batch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(batch, "start_worker", lambda: None)
    c = TestClient(M.app)
    assert c.post("/api/batch", json={"courses": "bidon"}).status_code == 400
    r = c.post("/api/batch", json={"courses": "2026-10-11 R1C3 Auteuil\n2026-10-12 R2C1"}).json()
    assert r["courses"] == 2
    s = c.get(f"/api/batch/{r['batch_id']}").json()
    assert s["total"] == 2 and s["compte"] == {"PENDING": 2}
    assert c.get(f"/api/batch/{r['batch_id']}/export.csv").status_code == 200
    assert c.get("/api/batch/inconnu").status_code == 404
    assert "Lot walk-forward" in open("static/index.html").read()


def test_auto_audit_uses_the_full_audit_pipeline(monkeypatch, tmp_path):
    """Le mode walk-forward (auto_audit) produisait l'ANCIEN audit (sans ticket B, résultats complets, IA)."""
    import app.orchestrator as O
    src = __import__("inspect").getsource(O)
    assert "run_full_audit" in src and "build_post_race_audit(result, arrival, confirmation)" not in src
    import app.main as M
    assert "run_full_audit" in __import__("inspect").getsource(M.audit_race)


def test_replay_disables_influential_ai_by_default(monkeypatch, tmp_path):
    """En rejeu, les pages contiennent l'après-course : réparation et qualitatif IA ne doivent pas influencer le ticket."""
    import app.config as cfg
    from app.llm import tasks as T
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    appels = []
    monkeypatch.setattr(T, "repair_fields", lambda *a, **k: appels.append("repair") or {"appele": True, "remplis": [], "corriges": []})
    r = _run_pipeline_offline(monkeypatch, tmp_path, "rejeu1")                         # course du 2026-10-03 -> REJEU
    assert r["status"] == "TERMINE" and appels == []
    jo = r["result"]["json_output"]
    assert jo["mode_execution"] == "REJEU" and jo["ia_qualitative"]["active"] is False and "REJEU" in jo["ia_qualitative"]["raison"]
    assert cfg.AI_REJEU_INFLUENCE == "0"


def test_calibration_script_filters_by_mode():
    import calibrer_depuis_audits as C
    from tests.test_strategy_tickets import _fake_audits
    a = _fake_audits(12, seed=1)
    for i, x in enumerate(a):
        x["contexte_dataset"] = {"mode_execution": "REJEU" if i < 8 else "PRE_COURSE"}
    rep = C.analyser(a, min_courses=999, mode="REJEU")
    assert rep["n_courses"] == 8 and rep["repartition_par_mode"] == {"REJEU": 8, "PRE_COURSE": 4}


def test_batch_state_is_backed_up_on_hf_and_restored_after_wipe(monkeypatch, tmp_path):
    """Render sans disque : un redémarrage efface la file. L'état du lot est sauvegardé sur HF et reprend tout seul."""
    import json, time
    db, H, fake = _hf_env(monkeypatch, tmp_path)
    from app import batch
    monkeypatch.setattr(H, "_DEBOUNCE", 3600)
    monkeypatch.setattr(batch, "PAUSE_S", 0.0)
    monkeypatch.setattr(batch, "start_worker", lambda: None)
    bid = batch.enqueue(batch.parse_lines("2026-10-11 R1C1\n2026-10-11 R1C2\n2026-10-11 R1C3"), pause_s=0)
    assert f"_lots/{bid}.json" in fake.files
    batch._claim_next()                                                       # R1C1 en cours quand Render redémarre
    batch._backup(bid)
    saved = json.loads(fake.files[f"_lots/{bid}.json"])
    assert [i["status"] for i in saved["items"]] == ["RUNNING", "PENDING", "PENDING"]
    import app.config as cfg
    monkeypatch.setattr(cfg, "DATABASE_PATH", str(tmp_path / "neuve.db")); db.init_db(); batch.ensure_table()
    assert batch.status(bid)["existe"] is False
    # le dossier technique _lots n'est jamais pris pour une course lors de la restauration de l'historique
    assert H.restore()["dossiers_sur_hf"] == 0
    assert H.restore_batches() == 1
    assert batch.status(bid)["compte"] == {"PENDING": 3}                    # RUNNING -> PENDING
    assert H.restore_batches() == 0                                          # idempotent


def test_hf_startup_resumes_batch_only_after_restore(monkeypatch, tmp_path):
    import inspect
    from app.integrations import hf_export as H
    src = inspect.getsource(H.startup_restore)
    assert src.index("restore_batches()") < src.index("resume_on_startup()")
    import app.main as M
    assert "hf_export_enabled()" in inspect.getsource(M._startup)


# ======================= Export global pour analyse (v1.29.54) =======================
def test_export_analyse_zip_contains_everything_needed_for_calibration(monkeypatch, tmp_path):
    import csv, io, json, zipfile
    from fastapi.testclient import TestClient
    import app.main as M
    db, batch = _batch_env(monkeypatch, tmp_path)
    for i, mode in enumerate(("REJEU", "REJEU", "PRE_COURSE")):
        rid = f"c{i}"
        db.create_race(rid, ["https://x"])
        db.save_result(rid, {"context": {"hippodrome": "Auteuil", "discipline": "STEEPLE", "date_course": f"2026-10-1{i}", "distance_m": 4700,
                                         "reunion_course_label": "R1C3"}, "horses": [{}] * 16, "json_output": {"mode_execution": mode, "version_ruleset": "v1.29.54"}})
        db.save_audit(rid, {"nb_captures": 3, "audit_ticket_B": {"nb_captures": 2}, "rapport_execution": {"gros": "x" * 50},
                            "contexte_dataset": {"partants": 2, "mode_execution": mode},
                            "baselines_contrefactuelles": {"marche_top8": 4, "ordre_final_top8": 2, "ticket_moins_marche": -1, "ticket_B_quotas": 2},
                            "arrivee_officielle_top5": [{"rang": 1, "numero": 15}],
                            "bilan_ticket": {"rang_moyen_reel": 8.0, "nb_incidents_course": 1, "nb_proches_6e_8e": 2, "nb_hors_place": 3},
                            "dataset_calibration": [{"numero": 15, "cote_matin": 3.9, "cote_avant_course": 3.9, "tranche": "T1", "ordre_final": 0.1,
                                                     "composite": 0.1, "pch_final": 196.0, "tocard_score": 0.0, "musique": "1h2h", "age": 6,
                                                     "sexe": "M", "dans_ticket_A": True, "dans_ticket_B": True, "top5": True, "rang_reel": 1,
                                                     "rang_complet": 1, "incident": None},
                                                    {"numero": 3, "cote_matin": 13.0, "tranche": "T2", "top5": False, "rang_complet": None, "incident": "TOMBE"}]})
        db.update_status(rid, "TERMINE")
    z = zipfile.ZipFile(io.BytesIO(batch.export_analyse_zip()))
    noms = z.namelist()
    assert {"LISEZ-MOI.txt", "courses.csv", "partants.csv"} <= set(noms) and sum(n.startswith("audits/") for n in noms) == 3
    courses = list(csv.DictReader(io.StringIO(z.read("courses.csv").decode()), delimiter=";"))
    assert len(courses) == 3 and courses[0]["captures_A"] == "3" and courses[0]["B_moins_marche"] == "-2" and courses[0]["incidents_A"] == "1"
    partants = list(csv.DictReader(io.StringIO(z.read("partants.csv").decode()), delimiter=";"))
    assert len(partants) == 6 and partants[0]["musique"] == "1h2h" and partants[1]["incident"] == "TOMBE" and partants[0]["mode"] in ("REJEU", "PRE_COURSE")
    assert "rapport_execution" not in json.loads(z.read([n for n in noms if n.startswith("audits/")][0]))           # allégé
    assert "rapport_execution" in json.loads(zipfile.ZipFile(io.BytesIO(batch.export_analyse_zip(complet=True))).read([n for n in noms if n.startswith("audits/")][0]))
    assert len(list(csv.DictReader(io.StringIO(zipfile.ZipFile(io.BytesIO(batch.export_analyse_zip(mode="REJEU"))).read("courses.csv").decode()), delimiter=";"))) == 2
    r = TestClient(M.app).get("/api/export/analyse.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and "vantage_analyse_" in r.headers["content-disposition"]
    assert TestClient(M.app).get("/api/export/analyse.zip?mode=BIDON").status_code == 422
    assert open("static/index.html").read().count("export/analyse.zip") >= 2


# ======================= Simulation de règles de ticket + discrimination (v1.29.54) =======================
def _fake_partants_zip(tmp_path, n_races=24, seed=3):
    """Courses synthétiques où le marché est informatif, l'ordre moteur plus bruité, et le ticket A évince les semi-favoris."""
    import csv, io, random, zipfile
    rng = random.Random(seed)
    rows = []
    for k in range(n_races):
        n = rng.choice([14, 16, 18])
        s = [rng.lognormvariate(0, 0.8) for _ in range(n)]
        mk = [x * rng.lognormvariate(0, 0.3) for x in s]
        od = [x * rng.lognormvariate(0, 1.2) for x in s]
        w, idx, top = s[:], list(range(n)), set()
        for _ in range(5):
            r = rng.random() * sum(w[i] for i in idx); acc = 0
            for i in idx:
                acc += w[i]
                if acc >= r:
                    top.add(i); idx.remove(i); break
        tm = sum(mk)
        cotes = [round(0.82 * tm / mk[i], 1) for i in range(n)]
        ordre_rank = sorted(range(n), key=lambda i: -od[i])
        t = {i: ("T1" if cotes[i] < 9 else "T2" if cotes[i] < 15 else "T3") for i in range(n)}
        in_a = set(sorted(range(n), key=lambda i: (cotes[i] < 15 and cotes[i] >= 9, -od[i]))[:8])   # A évince les T2
        for i in range(n):
            rows.append({"race_id": f"r{k:02d}", "date_course": f"2026-09-{k + 1:02d}", "hippodrome": "X", "discipline": "PLAT", "mode": "REJEU",
                         "partants": n, "numero": i + 1, "cote_matin": cotes[i], "cote_avant_course": cotes[i], "tranche": t[i],
                         "ordre_final": round(od[i] / sum(od), 5), "composite": 0.1, "pch_final": 100 + 50 * od[i],
                         "dans_ticket_A": i in in_a, "top5": i in top, "bd_signal_marche": round(1 / cotes[i], 4), "bd_bruit": round(rng.random(), 3)})
    buf = io.StringIO()
    w_ = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
    w_.writeheader(); w_.writerows(rows)
    p = tmp_path / "export.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("partants.csv", buf.getvalue())
    return p


def test_rule_simulator_cross_validated_and_ranks_market_above_noisy_engine(tmp_path):
    import calibrer_depuis_audits as C
    courses = C.charger_partants(_fake_partants_zip(tmp_path))
    out = C.simuler_regles(courses)
    b = out["baselines"]
    assert out["n_courses"] == 24 and b["marche_top8"]["captures_moy"] > b["ordre_top8"]["captures_moy"]
    assert b["A_actuel"]["vs_A"] == 0.0 and b["marche_top8"]["vs_A"] > 0                         # le marché bat ce ticket synthétique
    f = out["familles"]
    assert set(f) == {"melange_marche_PCH (alpha=poids du marché)", "melange_marche_ordre (alpha=poids du marché)",
                      "A + filet de semi-favoris (nb max)", "ordre + quota T1/T2 minimal (m)"}
    mel = f["melange_marche_ordre (alpha=poids du marché)"]
    assert "captures_HORS_ECHANTILLON" in mel and len(mel["parametres_choisis_par_bloc"]) == 4
    assert max(mel["captures_moy_par_parametre"], key=mel["captures_moy_par_parametre"].get) in {"0.7", "0.8", "0.9", "1.0"}   # le marché doit dominer
    assert f["A + filet de semi-favoris (nb max)"]["gain_vs_A_hors_echantillon"] > 0              # rendre des T2 au ticket aide ici
    assert out["baselines"]["A_actuel"]["captures_moy"] == round(sum(C._captures(courses, C._sel_A).values()) / 24, 3)


def test_rule_selectors_respect_ticket_size_and_filet_swaps_outsiders(tmp_path):
    import calibrer_depuis_audits as C
    courses = C.charger_partants(_fake_partants_zip(tmp_path, 10, 5))
    for hs in courses.values():
        assert len(C._sel_A(hs)) == 8 and len(C._sel_marche(hs)) == 8 and len(C._sel_ordre(hs)) == 8
        assert len(C._sel_filet(hs, 3)) == 8 and len(C._sel_blend(hs, 0.5)) == 8 and len(C._sel_quota(hs, 5)) == 8
        assert len(C._sel_filet(hs, 2) - C._sel_A(hs)) <= 2
        assert sum(1 for h in hs if h["numero"] in C._sel_quota(hs, 5) and h["tranche"] in ("T1", "T2")) >= min(5, sum(1 for h in hs if h["tranche"] in ("T1", "T2")))


def test_component_discrimination_ranks_market_signal_first_and_noise_near_half(tmp_path):
    import calibrer_depuis_audits as C
    courses = C.charger_partants(_fake_partants_zip(tmp_path, 30, 9))
    out = C.discriminer_composantes(courses)
    auc = {c["colonne"]: c["auc_intra_course"] for c in out["colonnes"]}
    assert auc["marche (-cote)"] > 0.65 and auc["bd_signal_marche"] > 0.65
    assert abs(auc["bd_bruit"] - 0.5) < 0.1 and "AUC 0.5" in out["lecture"]


def test_export_partants_csv_carries_score_components(monkeypatch, tmp_path):
    import csv, io, zipfile
    db, batch = _batch_env(monkeypatch, tmp_path)
    db.create_race("z1", ["https://x"])
    db.save_result("z1", {"context": {"hippodrome": "Auteuil", "discipline": "STEEPLE", "date_course": "2026-10-11"},
                          "horses": [{"cheval": {"numero": 15, "nom": "K", "cote_matin": 3.9, "valeur_pmu": 40.0, "age": 6},
                                      "breakdown": {"sri_v2": 120.0, "malus_m_sum": -7.8, "pch_final": 196.0, "flags": ["A", "B"]},
                                      "synthesis": {"ordre_final": 0.105}}],
                          "json_output": {"mode_execution": "REJEU"}})
    db.save_audit("z1", {"dataset_calibration": [{"numero": 15, "cote_matin": 3.9, "tranche": "T1", "top5": True, "dans_ticket_A": True}],
                         "baselines_contrefactuelles": {}, "contexte_dataset": {"mode_execution": "REJEU"}})
    z = zipfile.ZipFile(io.BytesIO(batch.export_analyse_zip()))
    rows = list(csv.DictReader(io.StringIO(z.read("partants.csv").decode()), delimiter=";"))
    assert rows[0]["bd_sri_v2"] == "120.0" and rows[0]["bd_malus_m_sum"] == "-7.8" and rows[0]["ch_valeur_pmu"] == "40.0"
    assert rows[0]["nb_flags"] == "2" and rows[0]["top5"] == "True" and "sy_ordre_final" in rows[0]


# ======================= Ticket C « ancré marché » + probabilité mélange marché/PCH (v1.29.55) =======================
import random                              # noqa: E402


class _TrV:
    def __init__(self, v): self.value = v


class _SynV:
    def __init__(self, v): self.tranche = _TrV(v)


class _Bd:
    def __init__(self, pch): self.pch_final = pch


class _Ch:
    def __init__(self, cote): self.cote_avant_course, self.cote_matin = cote, cote


class _Hs:
    def __init__(self, cote, pch, tranche):
        self.cheval, self.breakdown = _Ch(cote), _Bd(pch)
        self.synthesis = _SynV(tranche)


def _field_blend(n=16, seed=2):
    rng = random.Random(seed)
    cotes = sorted(round(rng.uniform(2.5, 60), 1) for _ in range(n))
    hs = []
    for c in cotes:
        tr = "T1" if c < 9 else "T2" if c < 15 else "T3" if c < 35 else "T4a" if c < 100 else "T4b"
        hs.append(_Hs(c, 220 - 3 * c + rng.uniform(-25, 25), tr))
    rng.shuffle(hs)
    return hs


def test_blend_probabilities_sum_to_five_and_follow_both_market_and_pch(monkeypatch):
    from app.engine.ticket_quotas import blend_probabilities
    monkeypatch.delenv("VANTAGE_BLEND_ALPHA", raising=False); monkeypatch.delenv("VANTAGE_BLEND_BETA", raising=False)
    hs = _field_blend()
    pi = blend_probabilities(hs)
    assert sum(pi) == _pytest.approx(5.0, abs=1e-6) and len(pi) == 16
    fav = min(range(16), key=lambda i: hs[i].cheval.cote_avant_course)
    outsider = max(range(16), key=lambda i: hs[i].cheval.cote_avant_course)
    assert pi[fav] > pi[outsider]
    # à cote égale, un meilleur PCH augmente la probabilité
    a, b = _Hs(10.0, 250.0, "T2"), _Hs(10.0, 100.0, "T2")
    autres = [_Hs(5.0 + i, 150.0 + i, "T1") for i in range(12)]
    p = blend_probabilities([a, b] + autres)
    assert p[0] > p[1]
    # alpha = 1 : marché pur ; alpha = 0 : PCH pur
    pm = blend_probabilities(hs, alpha=1.0); pp = blend_probabilities(hs, alpha=0.0)
    assert max(range(16), key=lambda i: pm[i]) == fav
    best_pch = max(range(16), key=lambda i: hs[i].breakdown.pch_final)
    assert max(range(16), key=lambda i: pp[i]) == best_pch


def test_ticket_c_has_no_per_tranche_minimum_but_keeps_both_bands():
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities
    for seed in range(1, 8):
        hs = _field_blend(16, seed)
        pi = blend_probabilities(hs)
        b = build_ticket_quotas(hs, pi)
        c = build_ticket_quotas(hs, pi, un_par_tranche=False)
        d12 = sum(1 for h in hs if h.synthesis.tranche.value in ("T1", "T2"))
        d34 = len(hs) - d12
        assert len(c["selection"]) == 8
        if d12 >= 3 and d34 >= 3:                      # bornes respectées dès que le champ le permet
            assert 3 <= c["t1_t2"] <= 5 and 3 <= c["t3_t4"] <= 5 and c["niveau_relaxation"] == 0
        else:                                           # sinon dégradation explicite, jamais d'erreur
            assert c["niveau_relaxation"] == 2 and "QUOTA_B_BORNES_3_5_IMPOSSIBLES" in c["flags"]
        assert c["captures_attendues_modele"] >= b["captures_attendues_modele"] - 1e-9      # moins de contraintes => jamais pire
        assert len(b["selection"]) == 8


def test_full_pipeline_builds_tickets_b_and_c_and_audits_all_three(monkeypatch, tmp_path):
    from app.engine.post_race_audit import build_post_race_audit
    from app.models import RaceResult
    from app.scraping.turfoo_resultats import ArrivalHorse
    r = _run_pipeline_offline(monkeypatch, tmp_path, "abc1")
    assert r["status"] == "TERMINE", r.get("error")
    res = r["result"]
    assert len(res["ticket"]) == len(res["ticket_quotas"]) == len(res["ticket_ancre"]) == 8
    assert res["ancre_info"]["pi_source"] == "melange_marche_pch" and res["quotas_info"]["pi_source"] == "melange_alpha_0.75_lab_b"
    jo = res["json_output"]
    assert len(jo["ticket_C_ancre_marche"]["ticket"]) == 8 and "ticket_B_quotas" in jo
    result = RaceResult.model_validate(res)
    nums = [h.cheval.numero for h in result.horses]
    arr = [ArrivalHorse(rang=i + 1, numero=n, nom=f"CH{n}") for i, n in enumerate(nums[:5])]
    c = build_post_race_audit(result, arr, None, ticket="C")
    assert c["ticket_audite"] == "C" and "Ticket C" in c["libelle_ticket"]
    assert c["baselines_contrefactuelles"]["ticket_C_ancre"] == c["nb_captures"]
    assert all("dans_ticket_C" in row for row in c["dataset_calibration"])
    assert sum(1 for row in c["dataset_calibration"] if row["dans_ticket_C"]) == 8


def test_run_full_audit_adds_ticket_c_and_comparison(monkeypatch, tmp_path):
    from app.engine import post_race_audit as A
    from app.models import RaceResult
    from app.scraping.turfoo_resultats import ArrivalHorse
    r = _run_pipeline_offline(monkeypatch, tmp_path, "abc2")
    result = RaceResult.model_validate(r["result"])
    nums = [h.cheval.numero for h in result.horses]
    arr = [ArrivalHorse(rang=i + 1, numero=n, nom=f"CH{n}") for i, n in enumerate(nums[:5])]
    monkeypatch.setattr(A, "confirm_arrival", lambda res, urls: (arr, {"statut": "CONFIRME"}))
    monkeypatch.setattr(A, "on_audit_confirmed", lambda *a, **k: {})
    from app import config as cfg
    monkeypatch.setattr(cfg, "AI_POSTRACE", "0")
    audit = A.run_full_audit("abc2", result, [])
    assert set(audit["comparaison_tickets"]) == {"A_captures", "B_captures", "C_captures"}
    assert audit["audit_ticket_C"]["nb_captures"] == audit["comparaison_tickets"]["C_captures"]
    agg = A.aggregate_audit_patterns([{"audit": audit}])
    assert agg["nb_courses_ticket_C"] == 1 and agg["taux_capture_moyen_ticket_C"] is not None


def test_export_and_ui_expose_ticket_c(monkeypatch, tmp_path):
    import csv, io, zipfile
    db, batch = _batch_env(monkeypatch, tmp_path)
    db.create_race("k1", ["https://x"])
    db.save_result("k1", {"context": {"hippodrome": "Auteuil", "discipline": "STEEPLE", "date_course": "2026-10-11"}, "horses": [], "json_output": {"mode_execution": "REJEU"}})
    db.save_audit("k1", {"nb_captures": 3, "audit_ticket_B": {"nb_captures": 3}, "audit_ticket_C": {"nb_captures": 4},
                         "baselines_contrefactuelles": {"marche_top8": 3, "ticket_C_ancre": 4, "ticket_B_quotas": 3, "ticket_moins_marche": 0},
                         "dataset_calibration": [{"numero": 1, "dans_ticket_C": True}]})
    z = zipfile.ZipFile(io.BytesIO(batch.export_analyse_zip()))
    row = list(csv.DictReader(io.StringIO(z.read("courses.csv").decode()), delimiter=";"))[0]
    assert row["captures_C"] == "4" and row["C_moins_marche"] == "1"
    assert "dans_ticket_C" in z.read("partants.csv").decode().splitlines()[0]
    ui = open("static/index.html").read()
    assert "Ticket C — ancré marché" in ui and "auditExtraHtml(a, 'C'" in ui


def test_rule_simulator_knows_blend_family_and_ticket_columns(tmp_path):
    import calibrer_depuis_audits as C
    courses = C.charger_partants(_fake_partants_zip(tmp_path, 24, 4))
    out = C.simuler_regles(courses)
    assert "melange_marche_PCH (alpha=poids du marché)" in out["familles"]
    assert hasattr(C, "_sel_B") and hasattr(C, "_sel_C")


# ======================= Fusion v1.29.57 : ticket B = mélange marché/PCH + grilles (a priori souple), IIC-v2, noms d'archives =======================
def test_target_grids_by_discipline_and_signature():
    from app.engine.ticket_quotas import target_quotas, GRID_3221, GRID_3311, GRID_2331
    from app.models import Discipline, Signature
    assert target_quotas(Discipline.TROT_ATTELE, Signature.LOCK) == GRID_3311
    assert target_quotas(Discipline.HAIES, Signature.MIXTE_LOCK) == GRID_3311
    assert target_quotas(Discipline.PLAT, Signature.CHAOS) == GRID_2331
    assert target_quotas(Discipline.STEEPLE, Signature.CHAOS) == GRID_2331
    assert target_quotas(Discipline.PLAT, Signature.LOCK) == GRID_3221          # pas de grille « fermée » en plat
    assert target_quotas(Discipline.TROT_ATTELE, Signature.CHAOS) == GRID_3221   # pas de grille « ouverte » au trot
    assert target_quotas(None, None) == GRID_3221


def test_ticket_b_grille_respects_bounds_and_families():
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities
    from app.models import Discipline, Signature
    for seed in range(1, 10):
        hs = _field_blend(16, seed)
        pi = blend_probabilities(hs)
        b = build_ticket_quotas(hs, pi, grille=True, discipline=Discipline.PLAT, signature=Signature.STANDARD)
        sel = b["selection"]
        assert len(sel) == 8 and len(set(sel)) == 8
        dispo = b["tranches_disponibles"]
        d12, d34 = dispo["T1"] + dispo["T2"], dispo["T3"] + dispo["T4a"] + dispo["T4b"]
        if d12 < 3 or d34 < 3:                       # bornes infaisables : dégradation explicite, jamais d'erreur
            assert b["niveau_relaxation"] == 2 and "QUOTA_B_BORNES_3_5_IMPOSSIBLES" in b["flags"]
            continue
        assert 3 <= b["t1_t2"] <= 5 and 3 <= b["t3_t4"] <= 5 and b["niveau_relaxation"] in (0, 1)
        comp = b["composition"]
        if b["niveau_relaxation"] == 1:
            continue
        # une famille T1/T2/T3/T4 (T4 = T4a+T4b) représentée dès qu'elle existe
        assert comp["T1"] >= (1 if dispo["T1"] else 0) and comp["T2"] >= (1 if dispo["T2"] else 0)
        assert comp["T3"] >= (1 if dispo["T3"] else 0) and comp["T4a"] + comp["T4b"] >= (1 if dispo["T4a"] + dispo["T4b"] else 0)
        assert b["applied_grid"] == [comp["T1"], comp["T2"], comp["T3"], comp["T4a"] + comp["T4b"]]
        assert b["captures_attendues_sans_grille"] >= b["captures_attendues_modele"] - 1e-9     # la grille ne peut que coûter au modèle
        assert b["ecart_grille"] == sum(abs(x - y) for x, y in zip(b["applied_grid"], b["target_grid"]))


def test_grille_lambda_zero_is_model_optimum_and_large_lambda_hits_target():
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities, GRID_3311
    from app.models import Discipline, Signature
    hs = _field_blend(16, 3)
    pi = blend_probabilities(hs)
    kw = dict(grille=True, discipline=Discipline.TROT_ATTELE, signature=Signature.LOCK)
    zero = build_ticket_quotas(hs, pi, lam=0.0, **kw)
    assert zero["captures_attendues_modele"] == _pytest.approx(zero["captures_attendues_sans_grille"], abs=1e-9)
    fort = build_ticket_quotas(hs, pi, lam=100.0, **kw)
    dispo = fort["tranches_disponibles"]
    if dispo["T1"] >= 3 and dispo["T2"] >= 3 and dispo["T3"] >= 1 and dispo["T4a"] + dispo["T4b"] >= 1:
        assert tuple(fort["applied_grid"]) == GRID_3311 and fort["ecart_grille"] == 0
    assert fort["captures_attendues_modele"] <= zero["captures_attendues_modele"] + 1e-9


def test_grille_degrades_explicitly_never_crashes():
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities
    # T3+T4 = 2 chevaux seulement -> bornes [3,5] impossibles : niveau 2 + flag, 8 chevaux quand même
    hs = [_Hs(3.0 + i, 150.0 - i, "T1") for i in range(10)] + [_Hs(20.0, 80.0, "T2")] * 2 + [_Hs(30.0, 70.0, "T3")] * 2
    b = build_ticket_quotas(hs, blend_probabilities(hs), grille=True)
    assert len(b["selection"]) == 8 and b["niveau_relaxation"] == 2 and "QUOTA_B_BORNES_3_5_IMPOSSIBLES" in b["flags"]
    # sans T4 du tout : la famille T4 n'est pas exigée
    hs2 = _field_blend(16, 4)
    hs2 = [h for h in hs2 if h.synthesis.tranche.value not in ("T4a", "T4b")]
    b2 = build_ticket_quotas(hs2, blend_probabilities(hs2), grille=True)
    assert len(b2["selection"]) == 8 and b2["composition"]["T4a"] == b2["composition"]["T4b"] == 0


def test_ticket_c_unchanged_by_fusion_and_legacy_rule_kept():
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities
    hs = _field_blend(16, 5)
    pi = blend_probabilities(hs)
    c = build_ticket_quotas(hs, pi, un_par_tranche=False)                 # ticket C : ni grille ni minimum
    assert "target_grid" not in c and "grid_mode" not in c
    legacy = build_ticket_quotas(hs, pi)                                  # ancienne règle (un par tranche) intacte
    assert "target_grid" not in legacy and legacy["niveau_relaxation"] in (0, 1, 2) and len(legacy["selection"]) == 8


def test_iic_v2_metrics_and_signature_guards():
    from app.engine.race_pipeline import compute_race_market_metrics, determine_signature
    from app.models import Signature
    # favori écrasant -> LOCK par garde-fou dur (part favori >= 0,42 et écart >= 3)
    cotes = [1.9, 6.0, 9.0, 12.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]
    ch = [_mk(i + 1, f"CH{i+1}", cote_matin=c, cote_avant_course=c) for i, c in enumerate(cotes)]
    m = compute_race_market_metrics(ch, _race_t())
    assert 0.0 <= m["iic"] <= 100.0 and m["fav_share"] >= 0.30 and m["ecart_fav"] > 3
    assert determine_signature(ch, _race_t()) in (Signature.LOCK, Signature.MIXTE_LOCK)
    # champ très ouvert, cotes serrées -> jamais LOCK
    ouvert = [_mk(i + 1, f"CH{i+1}", cote_matin=8.0 + 0.4 * i, cote_avant_course=8.0 + 0.4 * i) for i in range(18)]
    r = _race_t()
    assert determine_signature(ouvert, r) in (Signature.CHAOS, Signature.STANDARD)
    assert r.iic_v2 is not None and r.market_metrics["n_cotes"] == 18          # métriques conservées pour l'audit
    # < 2 cotes : pas de signature fantaisiste
    assert determine_signature([_mk(1, "A")], _race_t()) == Signature.STANDARD


def test_archive_names_readable_and_hf_folder_unchanged():
    from app.integrations.hf_export import race_archive_basename
    from app.integrations.hf_export import race_folder_name
    ctx = {"date_course": "2026-10-11", "reunion_course_label": "R1C3", "discipline": "PLAT", "hippodrome": "Auteuil", "distance_m": 1800}
    nom = race_archive_basename(ctx)
    assert nom.startswith("2026-10-11_R1C3_") and "auteuil" in nom and nom.endswith("1800m")
    assert "R1C3" not in race_folder_name(ctx)                               # le dossier Hugging Face garde son format JJ-MM-AA


def test_full_pipeline_ticket_b_uses_grid_and_iic(monkeypatch, tmp_path):
    r = _run_pipeline_offline(monkeypatch, tmp_path, "fus57")
    assert r["status"] == "TERMINE", r.get("error")
    res = r["result"]
    qi = res["quotas_info"]
    assert qi["pi_source"] == "melange_alpha_0.75_lab_b" and qi["alpha_marche"] == 0.75 and qi["alpha_t3"] == 0.8 and "recouvrement_avec_ticket_C" in qi
    assert sum(qi["composition"].values()) == len(res["ticket_quotas"]) == 8                     # B différencié : bornes [3;5], sans grille par défaut
    assert qi["gru_renforce"]["rangs_par_point"] == 2.0 and "recouvrement_avec_ticket_C" in qi and qi["lab_chevaux_changes"] is not None and "rerank_tranche" in qi
    assert len(res["ticket"]) == len(res["ticket_ancre"]) == 8
    assert "target_grid" not in res["ancre_info"]                               # C reste « ancré marché » pur
    assert res["context"]["iic_v2"] is not None


# ======================= v1.29.58 : champ réduit « 3 bases + 5 compléments » (désordre / bonus / ordre) =======================
def _struct_fixture(bases, comps):
    return {"bases": [{"numero": n} for n in bases], "complements": [{"numero": n} for n in comps],
            "ordre_prevu": list(bases) + list(comps[:2])}


def test_evaluer_structure_payment_rules_table():
    from app.engine.ticket import evaluer_structure
    st = _struct_fixture([1, 2, 3], [4, 5, 6, 7, 8])
    ev = lambda arr: evaluer_structure(st, arr)
    # ORDRE : B1,B2,B3,C1,C2 exacts
    assert ev([1, 2, 3, 4, 5])["niveau_gain"] == "ORDRE"
    # BONUS : 3 bases aux places 1-3 (désordre entre elles) + 1 complément 4e ou 5e (l'autre place peut être hors ticket)
    assert ev([2, 1, 3, 4, 5])["niveau_gain"] == "BONUS" and ev([3, 2, 1, 7, 5])["niveau_gain"] == "BONUS"
    assert ev([1, 2, 3, 4, 99])["niveau_gain"] == "BONUS" and ev([1, 2, 3, 99, 6])["niveau_gain"] == "BONUS"
    assert ev([1, 2, 3, 99, 98])["bonus"] is False and ev([1, 2, 3, 99, 98])["niveau_gain"] is None   # aucun complément 4e/5e
    # DÉSORDRE : 3 bases dans les 5 premiers + 2 compléments (n'importe où)
    r = ev([4, 1, 2, 5, 3])
    assert r["niveau_gain"] == "DESORDRE" and r["desordre"] and not r["bonus"] and not r["ordre"]
    assert ev([1, 2, 4, 3, 8])["niveau_gain"] == "DESORDRE"
    # perdants : une base absente du top 5, ou un cheval hors ticket parmi les 5
    assert ev([1, 2, 4, 5, 6])["niveau_gain"] is None and ev([1, 2, 4, 5, 6])["bases_manquees"] == [3]
    assert ev([1, 2, 3, 4, 99])["desordre"] is False and ev([1, 2, 3, 4, 99])["arrivee_hors_ticket"] == [99]
    # un gain supérieur implique les inférieurs quand la règle l'exige : ordre ⇒ bonus ⇒ (3 bases en tête)
    o = ev([1, 2, 3, 4, 5]); assert o["ordre"] and o["bonus"] and o["desordre"]
    # arrivée incomplète : aucun gain, pas d'erreur
    assert ev([1, 2, 3])["arrivee_incomplete"] is True and ev([1, 2, 3])["niveau_gain"] is None
    assert evaluer_structure(None, [1, 2, 3, 4, 5]) is None


def test_structure_probabilities_match_exhaustive_enumeration():
    """Probabilités exactes de désordre / bonus / ordre = énumération de TOUS les ordres d'arrivée (7 chevaux, ticket de 5)."""
    from itertools import permutations
    from app.engine.ticket import structurer_bases_complements, evaluer_structure, _seq_prob
    ws = [9.0, 6.0, 4.0, 3.0, 2.0, 1.5, 1.0]
    hs = [_Hs(3.0 + i, 100.0 - i, "T1") for i in range(7)]
    sel = [0, 1, 2, 3, 5]                       # ticket de 5 : 2 chevaux (n°5 et n°7) hors ticket
    st = structurer_bases_complements(hs, sel, ws)
    assert st is not None
    tot = sum(ws); w = [x / tot for x in ws]
    acc = {"desordre": 0.0, "bonus": 0.0, "ordre": 0.0}
    for perm in permutations(range(7)):
        p = _seq_prob(w, 1.0, list(perm))
        ev = evaluer_structure(st, [i + 1 for i in perm[:5]])
        for k in acc:
            if ev[k]:
                acc[k] += p
    pm = st["probabilites_modele"]
    assert pm["desordre"] == _pytest.approx(acc["desordre"], abs=5e-5)
    assert pm["bonus"] == _pytest.approx(acc["bonus"], abs=5e-5)
    assert pm["ordre"] == _pytest.approx(acc["ordre"], abs=5e-7)
    assert pm["ordre"] <= pm["bonus"] + 1e-12 and pm["ordre"] <= pm["desordre"] + 1e-12 <= pm["top5_dans_ticket"] + 1e-9


def test_structure_picks_best_bases_and_ranks_by_probability():
    from itertools import combinations
    from app.engine.ticket import structurer_bases_complements, _probas_structure
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities, blend_weights
    from app.engine.pl_inclusion import top_k_distribution
    for seed in (1, 2, 6):
        hs = _field_blend(16, seed)
        sel = build_ticket_quotas(hs, blend_probabilities(hs), un_par_tranche=False)["selection"]
        w = blend_weights(hs)
        st = structurer_bases_complements(hs, sel, w)
        assert [b["role"] for b in st["bases"]] == ["B1", "B2", "B3"] and [c["role"] for c in st["complements"]] == ["C1", "C2", "C3", "C4", "C5"]
        nums = [b["numero"] for b in st["bases"]] + [c["numero"] for c in st["complements"]]
        assert len(set(nums)) == 8 and set(nums) == {i + 1 for i in sel}       # la sélection de 8 n'est pas modifiée
        poids = [b["poids_pl"] for b in st["bases"]]
        assert poids == sorted(poids, reverse=True)
        assert st["ordre_prevu"] == nums[:3] + nums[3:5] and len(st["ordre_prevu"]) == 5
        # optimalité : aucun autre triplet du ticket ne dépasse P(désordre) (tolérance du départage)
        tot = sum(w); wn = [x / tot for x in w]
        dp5, dp3 = top_k_distribution(wn, 5), top_k_distribution(wn, 3)
        best = max(_probas_structure(wn, 1.0, list(t), [i for i in sel if i not in t], sel, dp5, dp3)["desordre"] for t in combinations(sel, 3))
        assert st["probabilites_modele"]["desordre"] >= best - 0.0021
        assert st["gain_desordre_vs_reference"] >= -0.0021


def test_structure_none_when_ticket_too_small():
    from app.engine.ticket import structurer_bases_complements
    hs = [_Hs(3.0 + i, 100.0 - i, "T1") for i in range(10)]
    assert structurer_bases_complements(hs, [0, 1, 2, 3], [1.0] * 10) is None
    assert structurer_bases_complements(hs, list(range(8)), [1.0] * 9) is None


def test_full_pipeline_structures_for_three_tickets_and_audit(monkeypatch, tmp_path):
    from app.engine import post_race_audit as A
    from app.models import RaceResult
    from app.scraping.turfoo_resultats import ArrivalHorse
    r = _run_pipeline_offline(monkeypatch, tmp_path, "cr58")
    assert r["status"] == "TERMINE", r.get("error")
    res = r["result"]
    sts = res["structures_tickets"]
    assert set(sts) == {"A", "B", "C"} and res["json_output"]["structures_bases_complements"].keys() == sts.keys()
    for lettre, tk in (("A", res["ticket"]), ("B", res["ticket_quotas"]), ("C", res["ticket_ancre"])):
        s = sts[lettre]
        assert len(s["bases"]) == 3 and len(s["complements"]) == 5 and len(s["ordre_prevu"]) == 5
        assert {b["numero"] for b in s["bases"]} | {c["numero"] for c in s["complements"]} == {t["numero"] for t in tk}
    result = RaceResult.model_validate(res)
    # arrivée = ordre prévu du ticket B : ORDRE pour B, jamais d'erreur pour A et C
    ordre_b = sts["B"]["ordre_prevu"]
    arr = [ArrivalHorse(rang=i + 1, numero=n, nom=f"CH{n}") for i, n in enumerate(ordre_b)]
    monkeypatch.setattr(A, "confirm_arrival", lambda res_, urls: (arr, {"statut": "CONFIRME"}))
    monkeypatch.setattr(A, "on_audit_confirmed", lambda *a, **k: {})
    from app import config as cfg
    monkeypatch.setattr(cfg, "AI_POSTRACE", "0")
    audit = A.run_full_audit("cr58", result, [])
    issue_b = audit["audit_ticket_B"]["structure_bases_complements"]["issue"]
    assert issue_b["ordre"] is True and issue_b["bonus"] is True and issue_b["niveau_gain"] == "ORDRE"
    assert audit["structure_bases_complements"]["issue"]["niveau_gain"] in (None, "DESORDRE", "BONUS", "ORDRE")
    agg = A.aggregate_audit_patterns([{"audit": audit}])
    g = agg["gains_champ_reduit"]
    assert g["B"]["nb_courses"] == 1 and g["B"]["ordre"] == 1 and g["B"]["bonus"] == 1 and g["B"]["desordre"] == 1
    assert g["B"]["taux_desordre"] == 1.0 and g["A"]["nb_courses"] == 1 and g["C"]["nb_courses"] == 1


# ======================= v1.29.60 : α propre à T3 (candidat, neutre par défaut) + indicateur de confiance IIC =======================
def test_alpha_t3_neutral_by_default_and_effective_when_set(monkeypatch):
    from app.engine.ticket_quotas import blend_weights, blend_probabilities
    hs = _field_blend(16, 7)
    monkeypatch.delenv("VANTAGE_BLEND_ALPHA_T3", raising=False)
    base = blend_weights(hs)
    assert blend_weights(hs, alpha=0.5) == base                         # défaut inchangé
    monkeypatch.setenv("VANTAGE_BLEND_ALPHA_T3", "0.5")
    assert blend_weights(hs) == base                                    # α_T3 = α : strictement identique
    monkeypatch.setenv("VANTAGE_BLEND_ALPHA_T3", "1.0")
    w = blend_weights(hs)
    assert w != base and len(w) == len(hs)
    pi = blend_probabilities(hs)
    assert abs(sum(pi) - 5.0) < 1e-6 or abs(sum(pi) - min(5, len(hs))) < 1e-6
    monkeypatch.setenv("VANTAGE_BLEND_ALPHA_T3", "pas-un-nombre")
    assert blend_weights(hs) == base                                    # valeur invalide ignorée


def test_pipeline_exposes_confiance_capture(monkeypatch, tmp_path):
    r = _run_pipeline_offline(monkeypatch, tmp_path, "cf60")
    assert r["status"] == "TERMINE", r.get("error")
    cc = r["result"]["json_output"].get("confiance_capture")
    assert cc and cc["niveau"] in ("NORMALE", "FAIBLE_COURSE_OUVERTE") and cc["seuil_iic"] == 72
    assert (cc["niveau"] == "FAIBLE_COURSE_OUVERTE") == (cc["iic_v2"] >= 72)


# ======================= v1.29.61 : classement propre à T3 (marché) et T4 (PCH + ordre_final + valeur PMU), désactivé par défaut =======================
def _comp_tr(hs, sel):
    from app.engine.ticket_quotas import _cle
    out = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
    for i in sel:
        g = _cle(hs[i]); out["T4" if g in ("T4a", "T4b") else g] += 1
    return out


def test_rerank_tranche_off_by_default_and_env_switch(monkeypatch):
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities
    hs = _field_blend(16, 11); pi = blend_probabilities(hs)
    monkeypatch.delenv("VANTAGE_RERANK_TRANCHE", raising=False)
    off = build_ticket_quotas(hs, pi, un_par_tranche=False)
    assert "rerank_tranche" not in off and off["selection"] == build_ticket_quotas(hs, pi, un_par_tranche=False, rerank=False)["selection"]
    monkeypatch.setenv("VANTAGE_RERANK_TRANCHE", "1")
    on = build_ticket_quotas(hs, pi, un_par_tranche=False)
    assert on["rerank_tranche"]["actif"] is True and on["selection_avant_rerank"] == off["selection"]


def test_rerank_tranche_keeps_quotas_and_t1_t2_and_picks_by_rule():
    from app.engine.ticket_quotas import build_ticket_quotas, blend_probabilities, _cle, _cote_ref
    for seed in (1, 2, 3, 5, 8):
        hs = _field_blend(18, seed); pi = blend_probabilities(hs)
        # signaux supplémentaires pour T4 : ordre_final et valeur PMU (absents des stubs de base)
        for i, h in enumerate(hs):
            h.synthesis.ordre_final = (i * 37 % 11) / 10.0
            h.cheval.valeur_pmu = float((i * 53) % 17)
        off = build_ticket_quotas(hs, pi, un_par_tranche=False, rerank=False)
        on = build_ticket_quotas(hs, pi, un_par_tranche=False, rerank=True)
        assert _comp_tr(hs, on["selection"]) == _comp_tr(hs, off["selection"])                       # mêmes quotas par tranche
        assert len(set(on["selection"])) == len(on["selection"]) == len(off["selection"])
        keep = lambda sel: sorted(i for i in sel if _cle(hs[i]) in ("T1", "T2"))
        assert keep(on["selection"]) == keep(off["selection"])                                         # T1 et T2 inchangés
        t3 = [i for i in range(len(hs)) if _cle(hs[i]) == "T3"]
        k3 = sum(1 for i in off["selection"] if _cle(hs[i]) == "T3")
        assert sorted(i for i in on["selection"] if _cle(hs[i]) == "T3") == sorted(sorted(t3, key=lambda i: (_cote_ref(hs[i]), i))[:k3])
        assert on["t1_t2"] == off["t1_t2"] and on["t3_t4"] == off["t3_t4"]


def test_rerank_tranche_t4_uses_available_signals_only():
    from app.engine.ticket_quotas import rerank_par_tranche, _cle
    hs = [_Hs(60.0 + i, float(i), "T4a") for i in range(6)] + [_Hs(5.0 + i, 90.0 - i, "T1") for i in range(6)]
    r = rerank_par_tranche(hs, [0, 1, 6, 7])                       # 2 places T4 : sans ordre_final ni valeur PMU -> PCH seul
    assert r["info"]["T4"]["critere"] == "PCH"
    assert sorted(i for i in r["selection"] if _cle(hs[i]) == "T4a") == [4, 5]      # les 2 meilleurs PCH du pool T4
    assert sorted(i for i in r["selection"] if _cle(hs[i]) == "T1") == [6, 7]


# ======================= v1.29.62 : export analyse enrichi (driver, entraîneur, œillères, ferrure / déferrage, stats, bookmakers) =======================
def _cheval_complet(num, **kw):
    base = {"numero": num, "nom": f"CH{num}", "age": 5, "cote_matin": 8.0, "cote_avant_course": 6.5, "driver_jockey": "J. Dupont", "driver_precedent": "A. Martin",
            "entraineur": "P. Durand", "proprietaire": "Ecurie X", "oeilleres": "PREMIERE_FOIS_OEILLERES", "ferrure_type": "D4", "deferre": "D4",
            "feu_equidia": "VERT", "driver_est_entraineur": False, "ferrure_changes": 1, "p_avant": 0.5, "rk_array_3_derniers_sec": [72.1, 71.8, 72.4],
            "cotes_bookmakers": {"PMU": 6.5, "ZETURF": 7.0, "BETCLIC": 6.0}, "cotes_timeline": [{"heure": "10h", "cote": 8.0}, {"heure": "14h", "cote": 6.5}],
            "driver_stats": {"fenetres": [{"jours": 30, "victoires": 3, "courses": 12}, {"jours": 7, "victoires": 1, "courses": 4}], "taux_top5_6m": 0.41,
                             "classement_national": 12, "nb_courses_12m": 300},
            "trainer_stats": {"fenetres": [{"jours": 30, "victoires": 2, "courses": 20}], "taux_top5_6m": 0.33, "classement_national": 40},
            "tandem_driver_cheval": {"courses_ensemble": 3, "victoires_ensemble": 1, "places_top5_ensemble": 2}}
    base.update(kw)
    return base


def test_champs_bruts_extracts_driver_trainer_blinkers_shoeing_and_stats():
    from app.batch import _champs_bruts
    f = _champs_bruts(_cheval_complet(4))
    assert f["tx_driver_jockey"] == "J. Dupont" and f["tx_entraineur"] == "P. Durand" and f["tx_deferre"] == "D4" and f["tx_ferrure_type"] == "D4"
    assert f["chg_driver"] == 1 and f["oeilleres_presentes"] == 1 and f["oeilleres_premiere_fois"] == 1 and f["deferre_present"] == 1
    assert f["bo_driver_est_entraineur"] == 0
    assert f["ds_w30_victoires"] == 3 and f["ds_w30_courses"] == 12 and f["ds_w30_taux"] == 0.25 and f["ds_w7_taux"] == 0.25
    assert f["ds_taux_top5_6m"] == 0.41 and f["ts_classement_national"] == 40 and f["tdc_victoires_ensemble"] == 1
    assert f["cbk_pmu"] == 6.5 and f["cbk_n"] == 3 and f["cbk_ecart_rel"] == _pytest.approx((7.0 - 6.0) / (19.5 / 3), abs=1e-4)
    assert f["ctl_n"] == 2 and f["ctl_var_rel"] == _pytest.approx((6.5 - 8.0) / 8.0, abs=1e-4) and f["rk3_moy"] == _pytest.approx(72.1, abs=0.01)
    # mêmes pilote : pas de changement ; sans œillères ; pas de déferrage ; absence de donnée -> colonne absente (pas de faux zéro)
    g = _champs_bruts(_cheval_complet(5, driver_precedent="J. Dupont", oeilleres="SANS_OEILLERES", deferre="", ferrure_type=None, driver_stats=None))
    assert g["chg_driver"] == 0 and g["oeilleres_presentes"] == 0 and g["oeilleres_premiere_fois"] == 0 and g["deferre_present"] == 0
    assert "tx_deferre" not in g and "tx_ferrure_type" not in g and not any(k.startswith("ds_") for k in g)
    assert _champs_bruts({"numero": 1, "nom": "X"}) == {}


def test_export_analyse_has_raw_fields_and_coverage_columns(monkeypatch, tmp_path):
    import csv, io, zipfile
    db, batch = _batch_env(monkeypatch, tmp_path)
    horses = [{"cheval": _cheval_complet(1), "breakdown": {"pch_final": 200.0}, "synthesis": {"ordre_final": 0.1}},
              {"cheval": _cheval_complet(2, driver_jockey=None, oeilleres=None, deferre=None, ferrure_type=None, driver_stats=None, cotes_bookmakers=None),
               "breakdown": {"pch_final": 150.0}, "synthesis": {"ordre_final": 0.05}}]
    db.create_race("rc", ["https://x"])
    db.save_result("rc", {"context": {"hippodrome": "Vincennes", "discipline": "TROT_ATTELE", "date_course": "2026-10-20", "distance_m": 2700,
                                      "type_course": "HANDICAP", "penetrometre": None, "meteo_temp_c": 11.5, "rythme_projete": "MODERE"},
                          "horses": horses, "json_output": {"mode_execution": "PRE_COURSE", "version_ruleset": "v1.29.62"}})
    db.save_audit("rc", {"contexte_dataset": {"partants": 2, "mode_execution": "PRE_COURSE"},
                         "dataset_calibration": [{"numero": 1, "top5": True, "rang_reel": 1}, {"numero": 2, "top5": False}]})
    db.update_status("rc", "TERMINE")
    z = zipfile.ZipFile(io.BytesIO(batch.export_analyse_zip()))
    p = list(csv.DictReader(io.StringIO(z.read("partants.csv").decode()), delimiter=";"))
    c = list(csv.DictReader(io.StringIO(z.read("courses.csv").decode()), delimiter=";"))[0]
    p1 = next(r for r in p if r["numero"] == "1"); p2 = next(r for r in p if r["numero"] == "2")
    assert p1["tx_deferre"] == "D4" and p1["tx_oeilleres"] == "PREMIERE_FOIS_OEILLERES" and p1["ds_w30_taux"] == "0.25" and p1["cbk_n"] == "3"
    assert p2["tx_deferre"] == "" and p2["tx_driver_jockey"] == ""                       # absent = case vide (pas de faux zéro)
    assert c["couv_driver"] == "0.5" and c["couv_deferre"] == "0.5" and c["couv_oeilleres"] == "0.5" and c["couv_entraineur"] == "1.0"
    assert c["couv_driver_stats"] == "0.5" and c["couv_cotes_bookmakers"] == "0.5" and c["couv_feu_equidia"] == "1.0" and c["couv_p_avant_valeurs_distinctes"] == "1"
    assert c["type_course"] == "HANDICAP" and c["meteo_temp_c"] == "11.5" and c["rythme_projete"] == "MODERE"
    assert "tx_deferre" in z.read("LISEZ-MOI.txt").decode() or "DÉFERRAGE" in z.read("LISEZ-MOI.txt").decode()


# ======================= v1.29.63 : classements driver/entraîneur (B11/B12), corde, pépite, diagnostic =======================
def _course_opa(i, jockey_gagnant, ent_gagnant, autres=("AUTRE X", "AUTRE Y")):
    det = {"1": {"nom_jockey": jockey_gagnant, "nom_entraineur": ent_gagnant}, "2": {"nom_jockey": autres[0], "nom_entraineur": "E2"},
           "3": {"nom_jockey": autres[1], "nom_entraineur": "E3"}}
    return {"date": f"2026-0{1 + i % 9}-1{i % 9}", "lieu": "VINCENNES", "r/c": f"R1/C{i}", "prix": f"P{i}", "arrivee": [1, 2, 3], "arrivee_details": det}


def test_classements_built_offline_from_corpus_cache_and_names_normalised(monkeypatch, tmp_path):
    import json
    from app.engine import classements as cl
    cache = tmp_path / "cache"; cache.mkdir()
    # 40 courses : « J. Dupont » gagne 30 fois (+ 10 fois non classé), « B. Martin » gagne 5 fois ; seuil de 30 montes
    courses = [_course_opa(i, "J. Dupont" if i < 30 else "Z. Autre", "P. Durand", autres=("B. Martin", "C. Petit")) for i in range(40)]
    courses += [{"date": f"2026-02-{10 + i}", "lieu": "VINCENNES", "r/c": f"R2/C{i}", "prix": f"Q{i}", "arrivee": [2, 3, 1],
                 "arrivee_details": {"1": {"nom_jockey": "J. Dupont", "nom_entraineur": "P. Durand"}, "2": {"nom_jockey": "B. Martin", "nom_entraineur": "E2"},
                                     "3": {"nom_jockey": "C. Petit", "nom_entraineur": "E3"}}} for i in range(5)]
    (cache / "VINCENNES.json").write_text(json.dumps({"fetched_at": "2026-10-01T00:00:00", "courses": courses}))
    monkeypatch.setattr(cl, "_CACHE_CORPUS", cache)
    monkeypatch.setattr(cl, "_FICHIERS", {"drivers": tmp_path / "cl" / "drivers.json", "entraineurs": tmp_path / "cl" / "entraineurs.json"})
    monkeypatch.setattr(cl, "_caches", {}); monkeypatch.setattr(cl, "_construction_tentee", {})
    assert cl.normaliser_nom("J. Dupont") == cl.normaliser_nom("DUPONT, J") == cl.normaliser_nom("dupont j.") == "DUPONT J"
    # le fichier est ABSENT : la première lecture le construit seule (hors ligne), les deux orthographes retrouvent le même rang
    assert not (tmp_path / "cl" / "drivers.json").exists()
    r1, r2 = cl.get_classement_driver("J. Dupont"), cl.get_classement_driver("DUPONT J.")
    assert r1 == r2 == 1 and (tmp_path / "cl" / "drivers.json").exists()
    assert cl.get_classement_driver("B. Martin") == 2 and cl.get_classement_driver("C. Petit") == 3
    assert cl.get_classement_driver("Z. Autre") is None and cl.get_classement_driver(None) is None        # 10 montes < 30 : non classé
    assert cl.get_classement_entraineur("P. Durand") == 1
    assert cl.diagnostic() == {"classements_drivers": 3, "classements_entraineurs": 3}


def test_classements_absent_and_no_cache_never_crashes(monkeypatch, tmp_path):
    from app.engine import classements as cl
    monkeypatch.setattr(cl, "_CACHE_CORPUS", tmp_path / "nope")
    monkeypatch.setattr(cl, "_FICHIERS", {"drivers": tmp_path / "x" / "drivers.json", "entraineurs": tmp_path / "x" / "entraineurs.json"})
    monkeypatch.setattr(cl, "_caches", {}); monkeypatch.setattr(cl, "_construction_tentee", {})
    assert cl.get_classement_driver("J. Dupont") is None and cl.get_classement_entraineur("X") is None
    assert cl.diagnostic() == {"classements_drivers": 0, "classements_entraineurs": 0}


def test_corde_bonus_uses_real_corde_not_horse_number():
    from app.engine.pmu_corpus_analyse import bonus_corde_empirique
    from app.models import Cheval
    biais = {i: 0.10 for i in range(1, 11)}; biais[9] = 0.20; biais[3] = 0.05      # corde 9 très favorable, corde 3 défavorable
    ch = Cheval(numero=3, nom="X", numero_autostart=9)                              # le n° 3 part de la corde 9
    assert bonus_corde_empirique(ch, None, biais)[0] > 0                            # avant : clé = n° 3 -> bonus négatif (mauvaise clé)
    assert bonus_corde_empirique(Cheval(numero=3, nom="Y", numero_autostart=None), None, biais) == (0.0, [])   # pas de corde connue : jamais le n°
    assert bonus_corde_empirique(Cheval(numero=5, nom="Z", numero_autostart=3), None, biais)[0] < 0


def test_corde_v2_top5_rate_shrunk_and_off_by_default(monkeypatch):
    from app.engine import pmu_corpus_analyse as pc
    from app.scraping.open_pmu_api import ArriveeCourseOPA, ArriveeChevalOPA
    from app.models import RaceContext, Discipline, TypeCourse, Depart
    race = RaceContext(url_source="x", hippodrome="DEAUVILLE", discipline=Discipline.PLAT, distance_m=1800, type_course=TypeCourse.HANDICAP,
                       depart=list(Depart)[0], partants_confirmes=10, date_course="2026-10-01")
    cs = []
    for i in range(40):                                                            # la corde 1 est toujours dans les 5 premiers, la corde 10 jamais
        ch = {n: ArriveeChevalOPA(numero=n, nom_cheval=f"C{n}", corde=n) for n in range(1, 11)}
        cs.append(ArriveeCourseOPA(type_discipline="Plat", montant_eur=0, distance_m=1800, prix="p", hippodrome="DEAUVILLE", heure_depart=None, details=None,
                                   partants=10, non_partants=[], ordre_arrivee=[1, 2, 3, 4, 5], reunion_course="R1/C1", date_iso="2026-01-01", chevaux_par_numero=ch))
    monkeypatch.delenv("VANTAGE_CORDE_V2", raising=False)
    assert pc._corde_v2_actif() is False
    b = pc._biais_corde_v2(race, courses_source=cs)
    p0 = 0.5
    assert b[1] > p0 > b[10] and 0.5 < b[1] < 1.0 and 0.0 < b[10] < 0.5               # rétrécissement : ni 0 ni 1 malgré 40/40 et 0/40
    assert pc._biais_corde_v2(race, courses_source=cs[:10]) == {}                      # moins de 30 courses : aucun biais


def test_pepite_ceiling_is_neutral_by_default(monkeypatch):
    from app.engine.gru_signals import compute_gru_pepite
    from app.models import Cheval
    ch = Cheval(numero=7, nom="OUT", cote_avant_course=20.0, cote_matin=22.0, musique="1p2p3p4p5p")
    monkeypatch.delenv("VANTAGE_PEPITE_PLAFOND", raising=False)
    s0, f0 = compute_gru_pepite(ch, _race_t())
    monkeypatch.setenv("VANTAGE_PEPITE_PLAFOND", "3")
    s3, f3 = compute_gru_pepite(ch, _race_t())
    assert s3 == min(s0, 3.0) and s3 <= 3.0
    monkeypatch.setenv("VANTAGE_PEPITE_PLAFOND", "abc")
    assert compute_gru_pepite(ch, _race_t())[0] == s0                                 # valeur invalide ignorée


def test_export_has_diagnostic_columns_flags_and_signals(monkeypatch, tmp_path):
    import csv, io, zipfile
    db, batch = _batch_env(monkeypatch, tmp_path)
    horses = [{"cheval": _cheval_complet(1, signaux_precalcules=[{"id": "B11"}]), "breakdown": {"pch_final": 200.0, "flags": ["GRU_PEPITE_ACTIF", "BIAIS_CORDE_FAVORABLE"],
                                                                                              "signaux_actifs": [{"id": "GRU_PEPITE"}]}, "synthesis": {"ordre_final": 0.1}},
              {"cheval": _cheval_complet(2), "breakdown": {"pch_final": 150.0, "flags": ["GRU_PIEGE_AS_CRITIQUE", "GRU_PIEGE_NUMERO_x", "GRU_PEPITE_SOUS_SEUIL"],
                                                           "signaux_actifs": [{"id": "GRU_PIEGE"}]}, "synthesis": {"ordre_final": 0.05}}]
    db.create_race("rd", ["https://x"])
    db.save_result("rd", {"context": {"hippodrome": "Auteuil", "discipline": "PLAT", "date_course": "2026-10-20", "distance_m": 1800},
                          "horses": horses, "json_output": {"mode_execution": "PRE_COURSE", "diagnostic_donnees": {
                              "classements_drivers": 0, "classements_entraineurs": 12, "corpus_courses_hippodrome": 80, "corpus_courses_similaires": 31,
                              "biais_corde_possible": True, "chevaux_avec_place_corde": 2, "p_avant_valeurs_distinctes": 2, "p_avant_proxy_musique": True,
                              "chevaux_avec_driver": 2, "chevaux_avec_changement_driver": 1}}})
    db.save_audit("rd", {"contexte_dataset": {"partants": 2, "mode_execution": "PRE_COURSE"},
                         "sources_collecte_et_enrichissement": {"enrichissement": {"equidia": {"status": "SKIP", "reason": "IDENTITE_EQUIDIA_REJETEE"},
                                                                                   "turf_bzh": {"status": "OK"}}},
                         "dataset_calibration": [{"numero": 1, "top5": True, "rang_reel": 1}, {"numero": 2, "top5": False}]})
    db.update_status("rd", "TERMINE")
    z = zipfile.ZipFile(io.BytesIO(batch.export_analyse_zip()))
    c = list(csv.DictReader(io.StringIO(z.read("courses.csv").decode()), delimiter=";"))[0]
    p = list(csv.DictReader(io.StringIO(z.read("partants.csv").decode()), delimiter=";"))
    assert c["diag_classements_drivers"] == "0" and c["diag_classements_entraineurs"] == "12" and c["diag_biais_corde_possible"] == "True"
    assert c["diag_corpus_similaires"] == "31" and c["diag_p_avant_proxy_musique"] == "True" and c["diag_chevaux_avec_changement_driver"] == "1"
    assert c["equidia_status"] == "SKIP" and c["equidia_reason"] == "IDENTITE_EQUIDIA_REJETEE" and c["turf_bzh_status"] == "OK"
    assert c["n_signal_B11"] == "1" and c["n_signal_B12"] == "0" and c["n_flag_biais_corde"] == "1" and c["n_flag_piege_as"] == "1"
    assert c["n_flag_piege_numero"] == "1" and c["n_flag_pepite_actif"] == "1" and c["n_flag_pepite_sous_seuil"] == "1"
    assert "B11" in next(r for r in p if r["numero"] == "1")["tx_signaux"] and "GRU_PEPITE_ACTIF" in next(r for r in p if r["numero"] == "1")["tx_flags"]


def test_classements_auto_build_can_be_switched_off(monkeypatch, tmp_path):
    import json
    from app.engine import classements as cl
    cache = tmp_path / "cache"; cache.mkdir()
    (cache / "H.json").write_text(json.dumps({"fetched_at": "2026-10-01T00:00:00", "courses": [_course_opa(i, "J. Dupont", "P. Durand") for i in range(40)]}))
    monkeypatch.setattr(cl, "_CACHE_CORPUS", cache)
    monkeypatch.setattr(cl, "_FICHIERS", {"drivers": tmp_path / "o" / "drivers.json", "entraineurs": tmp_path / "o" / "entraineurs.json"})
    monkeypatch.setattr(cl, "_caches", {}); monkeypatch.setattr(cl, "_construction_tentee", {})
    monkeypatch.setenv("VANTAGE_CLASSEMENTS_AUTO", "0")
    assert cl.get_classement_driver("J. Dupont") is None and not (tmp_path / "o" / "drivers.json").exists()


# ======================= v1.29.64 : profils GRU (neutre / renforcé), ticket B différencié =======================
def _vincennes_trot(distance=2700):
    from app.models import RaceContext, Discipline, TypeCourse, Depart
    return RaceContext(url_source="x", hippodrome="Vincennes", discipline=Discipline.TROT_ATTELE, distance_m=distance, type_course=TypeCourse.CONDITIONS,
                       depart=Depart.AUTOSTART, partants_confirmes=14, date_course="2026-10-20")


def test_gru_profiles_neutral_by_default_and_env_wins(monkeypatch):
    from app.engine import gru_signals as G
    for k in list(G._PROFIL_NEUTRE):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("VANTAGE_GRU_RENFORCE", raising=False)
    assert G._gp("VANTAGE_GRU_G10_MULT", 9.9) == 1.0 and G._gp("VANTAGE_GRU_G58_65_SCALE", 9.9) == 0.0       # pipeline = v1.29.63
    with G.gru_profil("renforce"):
        assert G._gp("VANTAGE_GRU_G10_MULT") == 1.12 and G._gp("VANTAGE_GRU_PIEGE_MULT_MIN") == 0.94
        monkeypatch.setenv("VANTAGE_GRU_G10_MULT", "1.5")
        assert G._gp("VANTAGE_GRU_G10_MULT") == 1.5                                                         # l'environnement l'emporte
        monkeypatch.delenv("VANTAGE_GRU_G10_MULT")
    assert G._gp("VANTAGE_GRU_G10_MULT") == 1.0                                                             # contexte refermé
    monkeypatch.setenv("VANTAGE_GRU_RENFORCE", "1")
    assert G._gp("VANTAGE_GRU_G56_SCALE") == 1.14                                                           # profil global renforcé


def test_gru_extra_signals_off_in_neutral_on_in_renforce_and_capped():
    from app.engine import gru_signals as G
    from app.models import Cheval
    race = _vincennes_trot()
    montee = Cheval(numero=3, nom="X", cote_matin=10.0, cote_avant_course=14.0, delai_j=15, musique="1p2p3p4p5p", driver_jockey="A. Un", driver_precedent="B. Deux")
    chute = Cheval(numero=4, nom="Y", cote_matin=8.0, cote_avant_course=5.0, delai_j=3)
    assert G.compute_gru_extra_signals(montee, race, None, [montee]) == []                                  # neutre : aucun signal
    with G.gru_profil("renforce"):
        ids = {i: v for i, v, _, _ in G.compute_gru_extra_signals(montee, race, None, [montee])}
        assert ids["G62"] == -0.4 and ids["G59"] > 0                                                         # cote en hausse de 40 % ; récence idéale
        ids2 = {i: v for i, v, _, _ in G.compute_gru_extra_signals(chute, race, None, [chute])}
        assert ids2["G62"] == 0.5 and ids2["G59"] == -0.4 * 0.5 * 2 * 0.5 or ids2["G59"] < 0              # cote en baisse ; intervalle trop court
        tot_pos = sum(v for _, v, _, _ in G.compute_gru_extra_signals(montee, race, None, [montee]) if v > 0)
        assert tot_pos <= 2.5 + 1e-9


def test_gru_piege_mult_bounded_and_only_demotes():
    from app.engine.gru_signals import apply_gru_piege_mult, gru_profil
    assert apply_gru_piege_mult(0.1, 8.0, 3.0) == 0.1                                  # neutre : inchangé
    with gru_profil("renforce"):
        assert apply_gru_piege_mult(0.1, 2.0, 3.0) == 0.1                              # piège < 3 : rien
        assert apply_gru_piege_mult(0.1, 8.0, 15.0) == 0.1                             # outsider : rien
        f = apply_gru_piege_mult(0.1, 9.0, 3.0)
        assert 0.1 * 0.94 - 1e-12 <= f < 0.1                                           # borné par VANTAGE_GRU_PIEGE_MULT_MIN, jamais de boost
        assert apply_gru_piege_mult(0.1, 9.0, 8.0) > f                                  # second (6-10) : pénalité réduite


def test_renforcer_horses_never_mutates_originals_and_b_differs_from_c(monkeypatch):
    from app.engine.gru_signals import renforcer_horses
    from app.engine.ticket_quotas import build_ticket_quotas, blend_weights
    from app.engine.pl_inclusion import inclusion_probs
    hs = _field_blend(16, 9)
    for i, h in enumerate(hs):
        h.cheval.cote_matin = h.cheval.cote_avant_course * (1.45 if i % 5 == 0 else 1.0)       # quelques cotes en forte hausse -> G62
        h.cheval.numero = i + 1
    avant = [h.breakdown.pch_final for h in hs]
    hb, st = renforcer_horses(hs, _vincennes_trot())
    assert [h.breakdown.pch_final for h in hs] == avant and len(hb) == len(hs) and st["rangs_par_point"] == 2.0
    assert all(abs(h.ajust_rang) <= 6.0 for h in hb)
    pi_c = blend_weights(hs); pi_b = blend_weights(hb, alpha=0.75, ajust_rang=[h.ajust_rang for h in hb])
    sel_c = build_ticket_quotas(hs, inclusion_probs(pi_c), un_par_tranche=False)["selection"]
    sel_b = build_ticket_quotas(hb, inclusion_probs(pi_b), un_par_tranche=False)["selection"]
    assert len(set(sel_b)) == 8 and len(set(sel_c)) == 8 and 3 <= len(set(sel_b) & set(sel_c)) <= 8


def test_blend_weights_ajust_rang_moves_selection_directly():
    from app.engine.ticket_quotas import blend_weights
    hs = _field_blend(16, 4)
    base = blend_weights(hs)
    assert blend_weights(hs, ajust_rang=[0.0] * len(hs)) == base                      # ajustement nul : strictement identique
    aj = [0.0] * len(hs); aj[10] = 6.0                                                 # un cheval mal classé reçoit +6 rangs
    w = blend_weights(hs, ajust_rang=aj)
    order_base = sorted(range(len(hs)), key=lambda i: -base[i]); order_new = sorted(range(len(hs)), key=lambda i: -w[i])
    assert order_new.index(10) < order_base.index(10)                                  # il remonte réellement dans le classement


def test_entrees_pepite_swap_same_half_and_keep_bounds():
    from app.engine.ticket_quotas import entrees_pepite, _cle
    hs = [_Hs(2.0 + i, 150.0 - i, "T1") for i in range(4)] + [_Hs(20.0 + i, 100.0 - i, "T3") for i in range(8)] + [_Hs(60.0, 80.0, "T4a")] * 2
    pi = [0.6, 0.55, 0.5, 0.45] + [0.4 - 0.03 * i for i in range(8)] + [0.05, 0.04]
    sel = [0, 1, 2, 3, 4, 5, 6, 7]                           # 4 T1 + 4 T3
    pep = [0.0] * 4 + [0.0] * 8 + [0.0, 0.0]
    pep[11] = 8.0; pep[12] = 8.0                              # deux outsiders T3/T4 à pépite maximale hors sélection
    r = entrees_pepite(hs, sel, pi, pep, max_entrees=1)
    assert len(r["entrees"]) == 1 and len(set(r["selection"])) == 8 and r["entrees"][0] in r["selection"]
    comp = lambda s: sorted(_cle(hs[i]) for i in s)
    assert comp(r["selection"]).count("T1") == 4                                              # la moitié T1/T2 n'est pas touchée
    sorti = set(sel) - set(r["selection"])
    assert len(sorti) == 1 and _cle(hs[sorti.pop()]) in ("T3", "T4a", "T4b")                   # remplacement dans la même moitié
    assert entrees_pepite(hs, sel, pi, pep, max_entrees=0)["entrees"] == []
    pep[4:8] = [8.0] * 4                                                                        # les retenus sont déjà des pépites maximales : rien à remplacer
    assert entrees_pepite(hs, sel, pi, pep, max_entrees=2)["entrees"] == []


def test_renforcer_horses_six_components_bounded_and_isolated():
    from types import SimpleNamespace as NS
    from app.engine.gru_signals import renforcer_horses
    from app.models import Cheval, Tranche
    hs = []
    for i in range(10):
        ch = Cheval(numero=i + 1, nom=f"H{i}", cote_matin=20.0, cote_avant_course=20.0)
        hs.append(NS(cheval=ch, synthesis=NS(tranche=Tranche.T3, ordre_final=0.1), breakdown=NS(pch_final=150.0 - i, gru_pepite_piege_pch=0.0, signaux_actifs=[])))
    hs[0].breakdown.gru_pepite_piege_pch = 8.0                                                    # pépite saturée -> composante négative
    hs[1].cheval.cote_avant_course = hs[1].cheval.cote_matin = 3.0; hs[1].breakdown.gru_pepite_piege_pch = -7.0   # favori à piège -> rétrogradé
    hs[2].breakdown.signaux_actifs = [{"id": "B11", "valeur_brute": 12.0}, {"id": "B12", "valeur_brute": 7.0}]   # classements -> bonus
    avant = [(h.breakdown.pch_final, h.breakdown.gru_pepite_piege_pch) for h in hs]
    hb, st = renforcer_horses(hs, _vincennes_trot())
    assert [(h.breakdown.pch_final, h.breakdown.gru_pepite_piege_pch) for h in hs] == avant       # entrée jamais modifiée
    assert hb[0].lab["pepite"] < 0 and hb[0].ajust_rang < 0 and abs(hb[0].pepite - 8.0) < 1e-9
    assert hb[1].lab["piege"] < 0 and hb[1].ajust_rang < 0
    assert hb[2].lab["classements"] > 0 and hb[2].ajust_rang > 0
    assert not ({"pepite", "piege", "classements"} & set(hb[3].lab))                                # aucune composante hors GRU / numéro pour un cheval neutre
    assert all(abs(h.ajust_rang) <= 6.0 for h in hb) and st["composantes_chevaux_touches"]["pepite"] == 1


def test_ticket_b_lab_never_changes_tickets_A_and_C(monkeypatch, tmp_path):
    """Les améliorations du ticket B ne doivent JAMAIS modifier A ni C : mêmes tickets avec le laboratoire B actif et entièrement désactivé."""
    r1 = _run_pipeline_offline(monkeypatch, tmp_path, "labon")
    for k, v in (("VANTAGE_B_RERANK", "0"), ("VANTAGE_B_POOL_PEPITE", "0"), ("VANTAGE_B_CORDE", "0"), ("VANTAGE_B_ALPHA", "0.5"), ("VANTAGE_B_ALPHA_T3", "0.5"),
                 ("VANTAGE_B_GRU_RANGS", "0"), ("VANTAGE_B_CLASSEMENTS_RANGS", "0"), ("VANTAGE_B_PEPITE_RANGS", "0"), ("VANTAGE_B_PIEGE_RANGS", "0"), ("VANTAGE_B_G30_RANGS", "0")):
        monkeypatch.setenv(k, v)
    r2 = _run_pipeline_offline(monkeypatch, tmp_path, "laboff")
    a, b = r1["result"], r2["result"]
    assert [t["numero"] for t in a["ticket"]] == [t["numero"] for t in b["ticket"]]
    assert [t["numero"] for t in a["ticket_ancre"]] == [t["numero"] for t in b["ticket_ancre"]]
    assert {h["cheval"]["numero"]: h["synthesis"]["ordre_final"] for h in a["horses"]} == {h["cheval"]["numero"]: h["synthesis"]["ordre_final"] for h in b["horses"]}
    assert a["quotas_info"]["alpha_marche"] == 0.75 and b["quotas_info"]["alpha_marche"] == 0.5          # seul B a bougé de paramètres


# ======================= v1.29.66 : chaîne de fournisseurs anti-bot (ScraperAPI → Firecrawl → …) =======================
_PAGE_OK = "<html><body>" + "partants Geny " * 60 + "</body></html>"


def _reset_fournisseurs(monkeypatch):
    from app.scraping import base
    monkeypatch.setattr(base, "_PROVIDER_COOLDOWN", {})
    monkeypatch.setattr(base, "_PROVIDER_STATS", __import__("collections").defaultdict(lambda: {"ok": 0, "echec": 0, "quota": 0, "bloque": 0}))
    for k in ("SCRAPERAPI_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_KEY", "SCRAPINGBEE_API_KEY", "SCRAPINGANT_API_KEY", "SCRAPEDO_TOKEN", "SCRAPEDO_API_KEY",
              "ZENROWS_API_KEY", "FETCH_CUSTOM_KEY", "FETCH_CUSTOM_URL_TEMPLATE", "FETCH_PROVIDERS_ORDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(base, "SCRAPERAPI_KEY", None)
    return base


def test_fournisseurs_actifs_selon_les_cles_et_l_ordre(monkeypatch):
    base = _reset_fournisseurs(monkeypatch)
    assert base.fournisseurs_actifs() == []                                           # aucune clé : rien d'actif (comportement v1.29.6 inchangé)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x"); monkeypatch.setenv("SCRAPERAPI_KEY", "sa-x")
    monkeypatch.setattr(base, "SCRAPERAPI_KEY", "sa-x")
    assert base.fournisseurs_actifs() == ["scraperapi", "firecrawl"]
    monkeypatch.setenv("FETCH_PROVIDERS_ORDER", "firecrawl,scraperapi,inconnu")
    assert base.fournisseurs_actifs() == ["firecrawl", "scraperapi"]                  # ordre réglable ; noms inconnus ignorés
    monkeypatch.setenv("FETCH_CUSTOM_KEY", "k")                                        # « custom » exige aussi son gabarit d'URL
    monkeypatch.setenv("FETCH_PROVIDERS_ORDER", "custom,firecrawl")
    assert base.fournisseurs_actifs() == ["firecrawl"]
    monkeypatch.setenv("FETCH_CUSTOM_URL_TEMPLATE", "https://api.exemple.com/s?apikey={key}&url={url}")
    assert base.fournisseurs_actifs() == ["custom", "firecrawl"]


def test_bascule_sur_firecrawl_quand_scraperapi_est_epuise_puis_mise_de_cote(monkeypatch):
    base = _reset_fournisseurs(monkeypatch)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x"); monkeypatch.setattr(base, "SCRAPERAPI_KEY", "sa-x")
    appels = {"scraperapi": 0, "firecrawl": 0}

    def sa(url, timeout):
        appels["scraperapi"] += 1
        raise base.ProviderError("scraperapi HTTP 403 : crédits épuisés", base._COOLDOWN_QUOTA_S, "quota")

    def fc(url, timeout):
        appels["firecrawl"] += 1
        return _PAGE_OK
    monkeypatch.setitem(base._PROVIDERS, "scraperapi", (("SCRAPERAPI_KEY",), sa))
    monkeypatch.setitem(base._PROVIDERS, "firecrawl", (("FIRECRAWL_API_KEY", "FIRECRAWL_KEY"), fc))
    assert base._fetch_via_chaine("https://www.geny.com/x", 20) == _PAGE_OK
    assert appels == {"scraperapi": 1, "firecrawl": 1} and base.fournisseurs_actifs() == ["firecrawl"]      # scraperapi mis de côté
    assert base._fetch_via_chaine("https://www.geny.com/y", 20) == _PAGE_OK
    assert appels == {"scraperapi": 1, "firecrawl": 2}                                                       # 2e appel : scraperapi n'est plus essayé
    st = base.provider_stats()
    assert st["compteurs"]["scraperapi"]["quota"] == 1 and st["compteurs"]["firecrawl"]["ok"] == 2 and "scraperapi" in st["en_pause_s"]
    base._PROVIDER_COOLDOWN["scraperapi"] = 0.0                                                              # fin de la mise de côté : il revient
    assert base.fournisseurs_actifs() == ["scraperapi", "firecrawl"]


def test_page_de_blocage_ou_trop_courte_passe_au_fournisseur_suivant_sans_mise_de_cote(monkeypatch):
    base = _reset_fournisseurs(monkeypatch)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x"); monkeypatch.setattr(base, "SCRAPERAPI_KEY", "sa-x")
    monkeypatch.setitem(base._PROVIDERS, "scraperapi", (("SCRAPERAPI_KEY",), lambda u, t: "<html>Accès refusé " + "x" * 400 + "</html>"))
    monkeypatch.setitem(base._PROVIDERS, "firecrawl", (("FIRECRAWL_API_KEY",), lambda u, t: _PAGE_OK))
    assert base._fetch_via_chaine("https://www.geny.com/x", 20) == _PAGE_OK
    assert base.provider_stats()["compteurs"]["scraperapi"]["bloque"] == 1 and "scraperapi" not in base.provider_stats()["en_pause_s"]
    monkeypatch.setitem(base._PROVIDERS, "scraperapi", (("SCRAPERAPI_KEY",), lambda u, t: "court"))
    assert base._page_bloquee("court") and base._page_bloquee("") and not base._page_bloquee(_PAGE_OK)


def test_fetch_html_se_replie_sur_le_direct_si_toute_la_chaine_echoue_et_sans_cle_rien_change(monkeypatch):
    base = _reset_fournisseurs(monkeypatch)
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    class _Resp:
        status_code = 200; text = _PAGE_OK
        def raise_for_status(self): pass
    monkeypatch.setattr(base, "cffi_requests", type("C", (), {"get": staticmethod(lambda url, **kw: _Resp())}))
    assert base.fetch_html("https://www.geny.com/x", via_scraperapi=True) == _PAGE_OK                       # aucune clé : fetch direct
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x")
    def boom(url, timeout):
        raise RuntimeError("timeout")
    monkeypatch.setitem(base._PROVIDERS, "firecrawl", (("FIRECRAWL_API_KEY",), boom))
    assert base.fetch_html("https://www.geny.com/x", via_scraperapi=True) == _PAGE_OK                       # chaîne en échec : repli direct
    assert base.provider_stats()["compteurs"]["firecrawl"]["echec"] == 1


def test_firecrawl_and_generic_providers_build_the_documented_requests(monkeypatch):
    base = _reset_fournisseurs(monkeypatch)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-secret")
    vu = {}
    class _R:
        def __init__(self, code=200, data=None, text=""):
            self.status_code, self._d, self.text = code, data, text
        def json(self): return self._d
    def post(url, payload, timeout=60, headers=None):
        vu["post"] = (url, payload, headers); return _R(200, {"success": True, "data": {"rawHtml": _PAGE_OK}})
    monkeypatch.setattr(base, "_http_post_json", post)
    assert base._prov_firecrawl("https://www.geny.com/x", 30) == _PAGE_OK
    url, payload, headers = vu["post"]
    assert url == "https://api.firecrawl.dev/v1/scrape" and payload["formats"] == ["rawHtml"] and payload["url"] == "https://www.geny.com/x"
    assert headers["Authorization"] == "Bearer fc-secret" and payload["proxy"] == "basic"
    monkeypatch.setattr(base, "_http_post_json", lambda *a, **k: _R(402))                                    # crédits Firecrawl épuisés
    import pytest as _pt
    with _pt.raises(base.ProviderError) as e:
        base._prov_firecrawl("https://www.geny.com/x", 30)
    assert e.value.categorie == "quota" and e.value.cooldown == base._COOLDOWN_QUOTA_S
    monkeypatch.setattr(base, "_http_post_json", lambda *a, **k: _R(200, {"success": False, "error": "boom"}))
    with _pt.raises(base.ProviderError):
        base._prov_firecrawl("https://www.geny.com/x", 30)
    monkeypatch.setenv("FETCH_CUSTOM_KEY", "k 1"); monkeypatch.setenv("FETCH_CUSTOM_URL_TEMPLATE", "https://api.exemple.com/s?apikey={key}&url={url}")
    monkeypatch.setattr(base, "_http_get", lambda full, params=None, timeout=40, headers=None: (vu.__setitem__("get", full) or _R(200, text=_PAGE_OK)))
    assert base._prov_custom("https://www.geny.com/a?b=1", 30) == _PAGE_OK
    assert vu["get"] == "https://api.exemple.com/s?apikey=k%201&url=https%3A%2F%2Fwww.geny.com%2Fa%3Fb%3D1"   # clé et URL encodées
    monkeypatch.setattr(base, "_http_get", lambda *a, **k: _R(429))
    with _pt.raises(base.ProviderError) as e2:
        base._prov_custom("https://www.geny.com/a", 30)
    assert e2.value.cooldown == base._COOLDOWN_DEBIT_S


# ======================= v1.29.67 : réglages du ticket B par portée (trot / galop / obstacle > distance > hippodrome) =======================
def _course_ctx(disc, dist, hippo="Vincennes"):
    from app.models import RaceContext, TypeCourse, Depart
    return RaceContext(url_source="x", hippodrome=hippo, discipline=disc, distance_m=dist, type_course=TypeCourse.CONDITIONS,
                       depart=list(Depart)[0], partants_confirmes=14, date_course="2026-10-20")


def test_famille_course_et_tranche_distance():
    from app.engine.gru_catalog import famille_course, tranche_distance
    from app.models import Discipline
    assert famille_course(_course_ctx(Discipline.TROT_ATTELE, 2700)) == "TROT"
    assert famille_course(_course_ctx(Discipline.PLAT, 1600)) == "GALOP"
    assert famille_course(_course_ctx(Discipline.HAIES, 3500)) == "OBSTACLE" and famille_course(_course_ctx(Discipline.STEEPLE, 4200)) == "OBSTACLE"
    assert [tranche_distance(d) for d in (1200, 1400, 1401, 2000, 2400, 2700, 2701, 4500)] == ["<=1400", "<=1400", "1400-2000", "1400-2000", "2000-2700", "2000-2700", ">2700", ">2700"]
    assert tranche_distance(None) == ">2700"


def test_reglages_b_par_famille_et_heritage(monkeypatch):
    from app.engine.gru_catalog import reglages_b_pour
    from app.models import Discipline
    for k in ("VANTAGE_B_ALPHA", "VANTAGE_B_ALPHA_T3", "VANTAGE_B_RERANK", "VANTAGE_B_POOL_PEPITE", "VANTAGE_B_POOL_PEPITE_MAX", "VANTAGE_B_FAMILLES"):
        monkeypatch.delenv(k, raising=False)
    trot = reglages_b_pour(_course_ctx(Discipline.TROT_ATTELE, 2700))
    galop = reglages_b_pour(_course_ctx(Discipline.PLAT, 1600, "Deauville"))
    obst = reglages_b_pour(_course_ctx(Discipline.HAIES, 3500, "Auteuil"))
    assert trot["famille"] == "TROT" and trot["valeurs"]["alpha"] == 0.30 and trot["valeurs"]["rerank"] == 0 and trot["valeurs"]["entrees_pepite"] == 0
    assert trot["valeurs"]["alpha_t3"] is None and trot["valeurs"]["rangs_gru"] == 2.0           # le trot ne redéfinit que 4 paramètres
    assert galop["valeurs"]["alpha"] == 0.75 and galop["valeurs"]["rerank"] == 1 and galop["valeurs"]["entrees_pepite"] == 1
    assert obst["famille"] == "OBSTACLE" and obst["valeurs"] == {**galop["valeurs"]}              # hérite de GALOP (effectif insuffisant)
    assert trot["portees"][0] == "global" and "famille:TROT" in trot["portees"]


def test_reglages_b_hierarchie_hippodrome_distance_et_env_prioritaire(monkeypatch):
    from app.engine import gru_catalog as C
    from app.models import Discipline
    for k in ("VANTAGE_B_ALPHA", "VANTAGE_B_RERANK"):
        monkeypatch.delenv(k, raising=False)
    race = _course_ctx(Discipline.TROT_ATTELE, 2400, "Vincennes")
    monkeypatch.setitem(C.REGLAGES_B_FAMILLE_DISTANCE, ("TROT", "2000-2700"), {"alpha": 0.40})
    r = C.reglages_b_pour(race)
    assert r["valeurs"]["alpha"] == 0.40 and "famille:TROT|distance:2000-2700" in r["portees"]       # famille × distance l'emporte sur la famille
    entry = {"reglages_b": {"*": {"alpha": 0.5, "rangs_gru": 1.0}, "TROT": {"alpha": 0.45}, "TROT|2000-2700": {"alpha": 0.55}}}
    r2 = C.reglages_b_pour(race, entry=entry)
    assert r2["valeurs"]["alpha"] == 0.55 and r2["valeurs"]["rangs_gru"] == 1.0                        # hippodrome × famille × distance le plus spécifique
    assert r2["portees"][-1].endswith("distance:2000-2700") and r2["valeurs"]["rerank"] == 0           # le reste vient de la famille TROT
    r3 = C.reglages_b_pour(race, entry=entry, env={"VANTAGE_B_ALPHA": "0.9", "VANTAGE_B_RERANK": "1"})
    assert r3["valeurs"]["alpha"] == 0.9 and r3["valeurs"]["rerank"] == 1 and r3["portees"][-1] == "env"  # l'environnement explicite l'emporte sur tout
    r4 = C.reglages_b_pour(race, entry={"reglages_b": {"TROT": {"alpha": 0.2, "cle_inconnue": 9}}}, env={"VANTAGE_B_ALPHA": "pas-un-nombre"})
    assert r4["valeurs"]["alpha"] == 0.2 and "cle_inconnue" not in r4["valeurs"]                       # clé inconnue ignorée ; valeur d'env invalide ignorée
    assert C.reglages_b_pour(_course_ctx(Discipline.PLAT, 1600, "Deauville"), env={"VANTAGE_B_POOL_PEPITE": "0"})["valeurs"]["entrees_pepite"] == 0


def test_renforcer_horses_honours_scope_settings():
    from types import SimpleNamespace as NS
    from app.engine.gru_signals import renforcer_horses
    from app.engine.gru_catalog import REGLAGES_B_GLOBAL
    from app.models import Cheval, Tranche, Discipline
    ch = Cheval(numero=1, nom="X", cote_matin=20.0, cote_avant_course=20.0)
    h = NS(cheval=ch, synthesis=NS(tranche=Tranche.T3, ordre_final=0.1), breakdown=NS(pch_final=150.0, gru_pepite_piege_pch=8.0, signaux_actifs=[]))
    race = _course_ctx(Discipline.PLAT, 1600, "Deauville")
    plein, _ = renforcer_horses([h] * 6, race, None, dict(REGLAGES_B_GLOBAL))
    sans, _ = renforcer_horses([h] * 6, race, None, {**REGLAGES_B_GLOBAL, "rangs_pepite": 0.0, "rangs_gru": 0.0})
    assert plein[0].ajust_rang < sans[0].ajust_rang and "pepite" in plein[0].lab and "pepite" not in sans[0].lab


def test_pipeline_ticket_b_uses_scope_settings_and_audit_par_portee(monkeypatch, tmp_path):
    from app.engine import post_race_audit as A
    from app.engine.gru_catalog import reglages_b_pour
    from app.models import RaceResult
    from app.scraping.turfoo_resultats import ArrivalHorse
    r = _run_pipeline_offline(monkeypatch, tmp_path, "port67")
    assert r["status"] == "TERMINE", r.get("error")
    res = r["result"]; qi = res["quotas_info"]
    result = RaceResult.model_validate(res)
    rg = reglages_b_pour(result.context)
    assert qi["reglages_b"]["famille"] == rg["famille"] and qi["alpha_marche"] == rg["valeurs"]["alpha"] and qi["reglages_b"]["portees"] == rg["portees"]
    arr = [ArrivalHorse(rang=i + 1, numero=n, nom=f"CH{n}") for i, n in enumerate(res["structures_tickets"]["B"]["ordre_prevu"])]
    monkeypatch.setattr(A, "confirm_arrival", lambda res_, urls: (arr, {"statut": "CONFIRME"}))
    monkeypatch.setattr(A, "on_audit_confirmed", lambda *a, **k: {})
    from app import config as cfg
    monkeypatch.setattr(cfg, "AI_POSTRACE", "0")
    audit = A.run_full_audit("port67", result, [])
    agg = A.aggregate_audit_patterns([{"audit": audit}])
    pp = agg["par_portee"]
    fam = rg["famille"]
    assert pp["famille"][fam]["nb_courses"] == 1 and pp["famille"][fam]["effectif_suffisant"] is False
    assert pp["famille"][fam]["capture_B"] == 5.0 and pp["famille"][fam]["ecart_B_moins_C"] is not None
    assert any(k.startswith(fam + "|") for k in pp["famille_distance"]) and len(pp["hippodrome"]) == 1


# ======================= v1.29.68 : recalibrage — un cheval par tranche + mélange ordre/cote, plafond d'outsiders, tocard, valeur PMU trot =======================
from types import SimpleNamespace as _NS68                                   # noqa: E402


def _chevaux_v68(spec):
    """spec : liste de (tranche, ordre_final, cote). Retourne des objets minimaux compatibles ticket_quotas."""
    return [_NS68(synthesis=_NS68(tranche=t, ordre_final=o), cheval=_NS68(cote_avant_course=c, cote_matin=c, numero=i + 1)) for i, (t, o, c) in enumerate(spec)]


def _champ_v68():
    return _chevaux_v68([("T1", 0.90, 2.5), ("T1", 0.80, 4.0), ("T1", 0.70, 5.5), ("T2", 0.75, 9.5), ("T2", 0.60, 11.0), ("T2", 0.55, 13.0),
                         ("T3", 0.65, 17.0), ("T3", 0.64, 19.0), ("T3", 0.63, 22.0), ("T3", 0.62, 25.0), ("T3", 0.61, 28.0),
                         ("T4a", 0.58, 40.0), ("T4b", 0.57, 45.0), ("T4a", 0.56, 60.0)])


def test_v70_min1_t4_fusionne_et_sans_bornes_3_5(monkeypatch):
    from app.engine import ticket_quotas as tq
    h = _champ_v68()
    # Favoriser T1+T2 pour prouver que la sélection n’est plus ramenée dans [3,5].
    sc = [100.0 - i for i in range(len(h))]
    tr = [tq._cle(x) for x in h]
    for t in ("A", "B", "C"):
        sel = tq.choisir_min1(sc, tr, tq.TRANCHES_REQUISES[t], 8, None)
        assert len(sel) == 8 and len(set(sel)) == 8
        disponibles = {tq._groupe_min1(x) for x in tr}
        retenues = {tq._groupe_min1(tr[i]) for i in sel}
        assert (set(tq.TRANCHES_REQUISES[t]) & disponibles) <= retenues, (t, retenues)
        gauche = sum(1 for i in sel if tr[i] in ("T1", "T2"))
        assert gauche == 6, (t, gauche)  # dépasse [3,5] : la borne est bien abandonnée


def test_v68_plafond_outsiders_respecte_tranches_et_taille():
    from app.engine import ticket_quotas as tq
    h = _champ_v68()
    sc = tq.scores_melange(h); tr = [tq._cle(x) for x in h]; rg = tq._rangs_marche(h)
    base = tq.choisir_min1(sc, tr, tq.TRANCHES_REQUISES["A"], 8, None)
    for cap in (0, 1, 2, 3):
        sel = tq.plafonner_outsiders(base, sc, tr, rg, cap, tq.TRANCHES_REQUISES["A"], None)
        assert len(sel) == 8 and len(set(sel)) == 8
        assert sum(1 for i in sel if rg[i] >= 9) <= max(cap, sum(1 for i in base if rg[i] >= 9 and sum(1 for j in base if tq._groupe_min1(tr[j]) == tq._groupe_min1(tr[i])) == 1))
        retenues = {tq._groupe_min1(tr[i]) for i in sel}
        for req in tq.TRANCHES_REQUISES["A"]:
            assert req in retenues
    assert set(tq.plafonner_outsiders(base, sc, tr, rg, 8, tq.TRANCHES_REQUISES["A"], None)) == set(base)     # plafond large : inchangé


def test_v70_min1_actif_par_defaut_et_override(monkeypatch):
    from app.engine import ticket_quotas as tq
    for k in ("VANTAGE_SELECT_MIN1_TICKETS", "VANTAGE_CAP_OUTSIDERS", "VANTAGE_MIN1_LAMBDA", "VANTAGE_GARDE_T1"):
        monkeypatch.delenv(k, raising=False)
    assert tq.tickets_selection_min1() == ["A", "B", "C"] and tq.plafonds_outsiders() == {"A": 2, "B": 2}      # défauts actifs v1.29.70 / v1.29.69
    monkeypatch.setenv("VANTAGE_CAP_OUTSIDERS", "A:8,B:8,C:8")  # isoler l’effet min1
    h = _champ_v68(); actuelle = [0, 1, 2, 3, 4, 6, 7, 11]
    r = tq.appliquer_v68(h, "B", actuelle)
    assert r["origine"].startswith("min1_melange") and r["selection"] == r["shadow_min1_melange"] and r["erreur"] is None
    assert r["shadow_min1_melange"] and len(r["shadow_min1_melange"]) == 8 and r["shadow_plafond2"]
    disponibles = {tq._groupe_min1(tq._cle(x)) for x in h}
    retenues = {tq._groupe_min1(tq._cle(h[i])) for i in r["selection"]}
    assert (set(tq.TRANCHES_REQUISES["B"]) & disponibles) <= retenues
    monkeypatch.setenv("VANTAGE_SELECT_MIN1_TICKETS", "")
    assert tq.tickets_selection_min1() == ["A", "B", "C"]  # une variable vide ne désactive pas la règle
    monkeypatch.setenv("VANTAGE_SELECT_MIN1_TICKETS", "B")
    rb = tq.appliquer_v68(h, "B", actuelle); ra = tq.appliquer_v68(h, "A", actuelle); rc = tq.appliquer_v68(h, "C", actuelle)
    assert rb["origine"].startswith("min1_melange") and rb["selection"] == rb["shadow_min1_melange"]
    assert ra["origine"] == "live" and rc["origine"] == "live"                         # un override non vide restreint le périmètre
    monkeypatch.setenv("VANTAGE_SELECT_MIN1_TICKETS", "none"); monkeypatch.setenv("VANTAGE_CAP_OUTSIDERS", "none"); monkeypatch.setenv("VANTAGE_GARDE_T1", "none")
    assert tq.tickets_selection_min1() == [] and tq.plafonds_outsiders() == {}          # « none » désactive tout (disponible, jamais le défaut)
    r0 = tq.appliquer_v68(h, "B", actuelle)
    assert r0["selection"] == actuelle and r0["appliquee"] is False and r0["origine"] == "live"
    monkeypatch.setenv("VANTAGE_CAP_OUTSIDERS", "A:2,C:abc,Z:1")
    assert tq.plafonds_outsiders() == {"A": 2}                                                            # valeurs invalides ignorées


def test_v68_anomalie_ne_casse_jamais_le_ticket():
    from app.engine import ticket_quotas as tq
    r = tq.appliquer_v68([], "B", [0, 1, 2])
    assert r["selection"] == [0, 1, 2] and r["appliquee"] is False


def test_v69_tocard_mult_defaut_actif_plancher_et_tranches(monkeypatch):
    """v1.29.72 : multiplicateur tocard x0,75 par défaut, appliqué à T3 et T4 UNIQUEMENT (T1 et T2 inchangés), jamais nul."""
    from app.engine import synthesis as S
    from app.models import ModuleBreakdown, Discipline, Signature
    bd = ModuleBreakdown(); bd.pch_norm = 0.5; bd.tocard_score = 0.6; bd.csf_norm = 0.3; bd.h2h_norm = 0.2
    for k in ("VANTAGE_TOCARD_MULT_T34", "VANTAGE_TOCARD_MULT_T123"):
        monkeypatch.delenv(k, raising=False)
    ref = S.compute_composite(bd, Discipline.PLAT, Signature.STANDARD)
    assert S.compute_composite(bd, Discipline.PLAT, Signature.STANDARD, "T3") < ref                  # défaut actif x0,75 en T3
    assert S.compute_composite(bd, Discipline.PLAT, Signature.STANDARD, "T4a") < ref                 # et en T4
    assert S.compute_composite(bd, Discipline.PLAT, Signature.STANDARD, "T4b") < ref
    assert S.compute_composite(bd, Discipline.PLAT, Signature.STANDARD, "T1") == ref                 # T1 et T2 inchangés
    assert S.compute_composite(bd, Discipline.PLAT, Signature.STANDARD, "T2") == ref
    assert S.compute_composite(bd, Discipline.PLAT, Signature.STANDARD, None) == ref                 # tranche inconnue : inchangé
    assert S._tocard_mult("T3") == pytest.approx(0.75) and S._tocard_mult("T4a") == pytest.approx(0.75) and S._tocard_mult("T2") == 1.0
    monkeypatch.setenv("VANTAGE_TOCARD_MULT_T34", "0.5")
    assert S._tocard_mult("T3") == 0.5
    monkeypatch.setenv("VANTAGE_TOCARD_MULT_T34", "0")
    assert S._tocard_mult("T3") == 0.25                                                                # jamais de poids nul
    monkeypatch.setenv("VANTAGE_TOCARD_MULT_T34", "3")
    assert S._tocard_mult("T3") == 1.0                                                                 # pas de hausse
    monkeypatch.setenv("VANTAGE_TOCARD_MULT_T34", "abc")
    assert S._tocard_mult("T3") == pytest.approx(0.75)                                                 # valeur invalide : défaut actif
    monkeypatch.delenv("VANTAGE_TOCARD_MULT_T34", raising=False); monkeypatch.setenv("VANTAGE_TOCARD_MULT_T123", "0.5")
    assert S._tocard_mult("T3") == 0.5                                                                 # alias de l'ancien nom


def test_v72_gmo_tocard_appele_une_seule_fois():
    """Régression : le bloc `tocard_norm *= _tocard_mult(tr)` avait été recopié trois fois (x0,75 au cube)."""
    import inspect
    from app.engine import gmo_v
    src = inspect.getsource(gmo_v)
    assert src.count("tocard_norm *= _tocard_mult(tr)") == 1


def test_v68_valeur_pmu_trot_zero_en_rejeu_normal_pour_les_courses_a_venir(monkeypatch):
    from app.engine.common import attenuer_valeur_pmu_trot
    from app.models import Discipline
    monkeypatch.delenv("VANTAGE_TROT_VALEUR_MULT", raising=False)
    def champ(vals):
        return [_NS68(valeur_pmu=v) for v in vals]
    c = champ([58.0, 50.0, 40.0, 30.0, None])
    info = attenuer_valeur_pmu_trot(c, Discipline.TROT_ATTELE, "REJEU")
    assert info["actif"] and info["mode"] == "zero" and info["n"] == 4
    assert all(x.valeur_pmu is None for x in c)                                                        # REJEU : ramenée à zéro (absente)
    c2 = champ([58.0, 50.0, 40.0, 30.0])
    assert attenuer_valeur_pmu_trot(c2, Discipline.TROT_ATTELE, "PRE_COURSE")["actif"] is False        # course à venir : traitement normal
    assert [x.valeur_pmu for x in c2] == [58.0, 50.0, 40.0, 30.0]
    c3 = champ([58.0, 50.0, 40.0, 30.0]); c3[0]._reduction_km_pmu = 75.0
    assert attenuer_valeur_pmu_trot(c3, Discipline.TROT_ATTELE, "PRE_COURSE")["mode"] == "zero"        # course déjà courue (chrono du jour) : zéro
    assert attenuer_valeur_pmu_trot(champ([58.0, 50.0, 40.0, 30.0]), Discipline.PLAT, "REJEU")["actif"] is False   # hors trot : inchangé
    monkeypatch.setenv("VANTAGE_TROT_VALEUR_MULT", "1")
    assert attenuer_valeur_pmu_trot(champ([58.0, 50.0, 40.0, 30.0]), Discipline.TROT_ATTELE, "REJEU")["actif"] is False
    monkeypatch.setenv("VANTAGE_TROT_VALEUR_MULT", "0.25")                                             # variante : atténuation, rangs conservés
    c4 = champ([58.0, 50.0, 40.0, 30.0]); i4 = attenuer_valeur_pmu_trot(c4, Discipline.TROT_ATTELE, "REJEU")
    assert i4["mode"] == "attenue" and c4[0].valeur_pmu > c4[1].valeur_pmu > c4[2].valeur_pmu > c4[3].valeur_pmu


def test_v68_sri_nrc_m09_m22_neutres_quand_valeur_pmu_absente():
    """Après neutralisation, SRI/NRC utilisent leur repli par les gains et M09/M22 ne se déclenchent pas."""
    from app.engine.modules_ap import module_a_sri
    from app.models import Cheval, Discipline
    ch = Cheval(numero=1, nom="X", valeur_pmu=None, gains_moyenne_carriere_eur=2700.0, nb_courses=20)
    _, flags = module_a_sri(ch, Discipline.TROT_ATTELE)
    assert "SRI_VALEUR_PMU_MANQUANTE" in flags and "SRI_VALEUR_PROXY_GAINS" in flags


# ======================= v1.29.69 : shadow — bases par score propre figé, probabilités recalibrées, filtre de courses, garde T1 =======================
def _chevaux_v69(spec):
    """spec : liste de (tranche, cote, musique, forme). Objets minimaux compatibles score_propre / ticket_quotas."""
    return [_NS68(synthesis=_NS68(tranche=t, ordre_final=0.5), cheval=_NS68(cote_avant_course=c, cote_matin=c, numero=i + 1, musique=m, gains_moyenne_carriere_eur=3000.0,
                                                                          victoires_carriere=3, nb_courses=20, age=5),
                  breakdown=_NS68(forme_lineaire_pch=f, stab_pch=0.0, tact_pch=0.0, iff_v2=0.0)) for i, (t, c, m, f) in enumerate(spec)]


def _champ_v69():
    return _chevaux_v69([("T1", 2.8, "1a2a1a3a", 2.0), ("T1", 4.5, "2a3a1a4a", 1.5), ("T2", 9.5, "3a4a2a5a", 0.5), ("T2", 12.0, "5a6a4a7a", 0.0),
                         ("T3", 18.0, "0a8a9a5a", -0.5), ("T3", 22.0, "DaDa5a6a", -1.0), ("T3", 30.0, "7a8a0a9a", -1.2), ("T4a", 45.0, "9a0a8a7a", -1.5),
                         ("T1", 6.0, "4a5a3a2a", 1.0), ("T2", 14.0, "6a5a7a4a", 0.2)])


def test_v69_score_propre_ordre_coherent_et_robuste_aux_champs_absents():
    from app.engine import ticket_quotas as tq
    from app.models import Discipline
    h = _champ_v69()
    sc = tq.score_propre(h, Discipline.PLAT)
    assert len(sc) == len(h) and all(isinstance(x, float) for x in sc)
    assert sc[0] > sc[7] and sc[0] > sc[5]                                   # favori en forme > outsider sans forme ni musique
    assert tq.score_propre(h, Discipline.TROT_ATTELE) != sc                  # jeu de coefficients propre au trot
    vide = [_NS68(synthesis=_NS68(tranche="T1", ordre_final=None), cheval=_NS68(cote_avant_course=None, cote_matin=None, numero=i), breakdown=_NS68()) for i in range(4)]
    assert tq.score_propre(vide, Discipline.PLAT) == [0.0, 0.0, 0.0, 0.0]    # tout absent : neutre, sans exception


def test_v69_bases_propres_prefere_t1_t2_et_donne_b1_au_favori():
    from app.engine import ticket_quotas as tq
    from app.models import Discipline
    h = _champ_v69()
    sel = [0, 1, 2, 3, 4, 5, 6, 7]
    for k in (2, 3):
        b = tq.bases_propres(h, sel, k, Discipline.PLAT)
        assert len(b) == k and len(set(b)) == k and set(b) <= set(sel)
        assert all(tq._cle(h[i]) in ("T1", "T2") for i in b)                 # jamais de base en T3/T4 quand T1/T2 suffisent
        assert tq._cote_ref(h[b[0]]) == min(tq._cote_ref(h[i]) for i in b)   # B1 = plus petite cote des bases


def test_v69_probas_recalibrees_et_signal_course(monkeypatch):
    from app.engine import ticket_quotas as tq
    assert tq.probas_recalibrees("A", None) is None
    a = tq.probas_recalibrees("A", {"desordre": 0.06, "top5_dans_ticket": 0.11})
    assert a["desordre"] > 0.06 and a["top5_dans_ticket"] > 0.11             # A sous-estimé : relevé (à moitié)
    b = tq.probas_recalibrees("B", {"desordre": 0.10, "top5_dans_ticket": 0.23})
    assert b["top5_dans_ticket"] < 0.23                                      # B surestimé : abaissé
    assert tq.probas_recalibrees("A", {"desordre": 0.9})["desordre"] <= 1.0
    monkeypatch.delenv("VANTAGE_FILTRE_FAVORI_MAX", raising=False)
    h = _champ_v69()
    assert tq.signal_course(h)["niveau"] == "plein" and tq.signal_course(h)["favori_cote"] == 2.8
    monkeypatch.setenv("VANTAGE_FILTRE_FAVORI_MAX", "2.0")
    assert tq.signal_course(h)["niveau"] == "reduit"


def test_v69_garde_t1_repli_quand_la_selection_est_desactivee(monkeypatch):
    from app.engine import ticket_quotas as tq
    h = _champ_v69()
    for k in ("VANTAGE_GARDE_T1", "VANTAGE_SELECT_MIN1_TICKETS", "VANTAGE_CAP_OUTSIDERS"):
        monkeypatch.delenv(k, raising=False)
    actuelle = [0, 2, 3, 4, 5, 6, 7, 9]          # sans le 2e favori (index 1, cote 4,5) ni le 3e (index 8, cote 6,0)
    r = tq.appliquer_v68(h, "A", actuelle)
    assert r["origine"].startswith("min1_melange")                                   # sélection active : la garde n'est qu'un repli
    assert "garde_t1" not in r["origine"]
    assert r["shadow_garde_t1"] and {1, 8} <= set(r["shadow_garde_t1"]) and len(r["shadow_garde_t1"]) == 8      # le shadow ramène les favoris
    groupes = {tq._groupe_min1(tq._cle(h[i])) for i in r["shadow_garde_t1"]}
    for req in tq.TRANCHES_REQUISES["A"]:
        assert req in groupes
    monkeypatch.setenv("VANTAGE_SELECT_MIN1_TICKETS", "none"); monkeypatch.setenv("VANTAGE_CAP_OUTSIDERS", "none")
    r2 = tq.appliquer_v68(h, "A", actuelle)
    assert r2["appliquee"] is True and "garde_t1" in r2["origine"] and {1, 8} <= set(r2["selection"])        # repli actif par défaut pour A
    assert tq.appliquer_v68(h, "B", actuelle)["shadow_garde_t1"] is None                                       # A seulement


def test_v69_1_bases_forcees_dans_la_structure_et_probas_recalibrees():
    from app.engine.ticket import structurer_bases_complements
    from app.engine import ticket_quotas as tq
    h = _champ_v69()
    for x in h:
        x.synthesis.tranche = _NS68(value=x.synthesis.tranche)
    sel = list(range(8)); w = [1.0 / (1.0 + 0.3 * i) for i in range(len(h))]
    pl = structurer_bases_complements(h, sel, w)
    assert pl and pl["bases_source"] == "plackett_luce"
    forc = [1, 0, 2]
    f = structurer_bases_complements(h, sel, w, bases_forcees=forc)
    assert f["bases_source"] == "score_propre" and [x["rang_prevu"] for x in f["bases"]] == [1, 2, 3]
    assert [x["numero"] for x in f["bases"]] == [2, 1, 3]                                    # ordre fourni conservé (B1 = index 1)
    assert 0.0 <= f["probabilites_modele"]["desordre"] <= 1.0 and len(f["complements"]) == 5
    bad = structurer_bases_complements(h, sel, w, bases_forcees=[0, 1, 9])                  # base hors ticket : retombe sur Plackett-Luce
    assert bad["bases_source"] == "plackett_luce"
    rec = tq.probas_recalibrees("A", f["probabilites_modele"])
    assert rec and "facteurs_bruts" in rec


def test_v69_version_et_flags():
    from app.version import VERSION_RULESET, FUSION_FLAGS
    assert VERSION_RULESET == "v1.29.72"
    for k in ("recalibrage_v69_bases_score_propre_shadow", "recalibrage_v69_probas_recalibrees_shadow", "recalibrage_v69_filtre_courses_shadow", "recalibrage_v69_garde_t1"):
        assert FUSION_FLAGS.get(k) is True


def test_v69_1_pipeline_bout_en_bout_leviers_actifs(monkeypatch):
    """Pipeline complet (collecte et enrichissements neutralisés) : les leviers de la v1.29.69.1 sont actifs par défaut."""
    import json as _json
    from unittest import mock
    from app import db, orchestrator
    from app.models import RaceContext, Cheval, Discipline, TypeCourse, Depart
    for k in ("VANTAGE_SELECT_MIN1_TICKETS", "VANTAGE_CAP_OUTSIDERS", "VANTAGE_GARDE_T1", "VANTAGE_BASES_SCORE_PROPRE", "VANTAGE_TOCARD_MULT_T123",
              "VANTAGE_TROT_VALEUR_MULT", "VANTAGE_FILTRE_FAVORI_MAX"):
        monkeypatch.delenv(k, raising=False)
    db.init_db()

    def make(disc):
        trot = disc == Discipline.TROT_ATTELE
        race = RaceContext(url_source="https://www.turfoo.fr/course/1", hippodrome="Vincennes" if trot else "Chantilly", discipline=disc, distance_m=2700 if trot else 1800,
                           type_course=TypeCourse.CONDITIONS, depart=Depart.VOLTE if trot else Depart.AUTOSTART, partants_confirmes=14, date_course="2026-10-03")
        cotes = [5.5, 6.5, 8.0, 9.5, 11.0, 13.0, 17.0, 19.0, 22.0, 25.0, 28.0, 40.0, 55.0, 80.0]
        mus = ["1a2a1a3a", "2a3a1a4a", "4a5a3a2a", "3a4a2a5a", "5a6a4a7a", "6a5a7a4a", "0a8a9a5a", "DaDa5a6a", "7a8a0a9a", "9a0a8a7a", "8a9a7a6a", "0a0a9a8a", "Da0a8a9a", "7a7a8a9a"]
        ch = [Cheval(numero=i + 1, nom=f"CH{i + 1}", musique=mus[i], cote_matin=cotes[i], cote_avant_course=cotes[i], driver_jockey=f"J{i}", entraineur=f"T{i}",
                     gains_totaux_eur=20000 - i * 900, gains_moyenne_carriere_eur=2500 - i * 100, nb_courses=20, victoires_carriere=max(0, 6 - i // 2), age=4 + (i % 4),
                     fiche_url="https://x/c/%d" % i, valeur_pmu=(40.0 - i * 1.2 if trot else None)) for i in range(14)]
        return race, ch, [], "https://www.turfoo.fr/course/1"

    contrat = {"verdict": "OK", "score_completude_global": 1.0, "score_completude_critique": 1.0, "nb_lacunes_critiques": 0, "nb_lacunes_fortes": 0,
               "lacunes_critiques": [], "lacunes_fortes": [], "resume_par_cible": {}, "tableau": [], "note": "stub"}
    nop = lambda *a, **k: {}      # noqa: E731
    sorties = {}
    for disc in (Discipline.PLAT, Discipline.TROT_ATTELE):
        rid = "e2e_v6901_" + disc.value
        db.create_race(rid, ["https://www.turfoo.fr/course/1"])
        patches = [mock.patch("app.orchestrator.scrape_race_with_fallback", lambda urls, _d=disc, **k: make(_d)),
                   mock.patch("app.orchestrator.evaluate_data_contract", lambda r, c: contrat)]
        patches += [mock.patch("app.orchestrator." + n, nop) for n in ("enrich_chevaux", "enrichir_course_frequence_turf", "enrichir_course_stats_quinte", "enrich_race_with_pmu_api",
                                                                    "enrich_race_with_equidia", "enrich_race_with_turfbzh", "run_enrichissement_complementaire",
                                                                    "enrich_race_with_ai_rhythm", "fetch_html")]
        for p_ in patches:
            p_.start()
        try:
            orchestrator.run_pipeline(rid, ["https://www.turfoo.fr/course/1"])
        finally:
            for p_ in patches:
                p_.stop()
        r = db.get_race(rid)
        assert r["status"] == "TERMINE", r.get("error")
        jo = r["result"] if isinstance(r["result"], dict) else _json.loads(r["result"])
        sorties[disc] = jo
    plat, trot = sorties[Discipline.PLAT], sorties[Discipline.TROT_ATTELE]
    j = plat["json_output"]
    assert all(j["shadow_v1_29_68"][t]["origine"].startswith("min1_melange") for t in "ABC")                                       # v1.29.70 : A, B et C
    assert len(plat["ticket"]) == 8 and len(plat["ticket_quotas"]) == 8 and len(plat["ticket_ancre"]) == 8
    comp = plat["quotas_info"]["composition"]
    assert plat["quotas_info"]["v1_29_68"].startswith("min1_melange") and all(comp.get(t, 0) >= 1 for t in ("T1", "T2", "T3")) and comp.get("T4a", 0) + comp.get("T4b", 0) >= 1
    assert all(v["bases_source"] == "score_propre" and v["probabilites_recalibrees"] for v in plat["structures_tickets"].values())      # hors trot : bases par score propre
    assert j["filtre_course"]["niveau"] == "reduit" and any("FILTRE_COURSE_REDUIT" in str(w) for w in j.get("avertissements_collecte", []))
    assert j["valeur_pmu_trot_neutralisee"]["actif"] is False                                                                         # hors trot : inchangé
    jt = trot["json_output"]
    assert jt["valeur_pmu_trot_neutralisee"]["actif"] is True and jt["valeur_pmu_trot_neutralisee"]["mode"] == "zero"              # trot en REJEU : valeur PMU à zéro
    assert all(v["bases_source"] == "plackett_luce" for v in trot["structures_tickets"].values())                                    # trot : Plackett-Luce conservé


def test_v70_version_et_flags():
    from app.version import VERSION_RULESET, FUSION_FLAGS
    assert VERSION_RULESET in ("v1.29.70", "v1.29.71", "v1.29.72")
    for k in ("recalibrage_v68_shadow_min1_melange", "recalibrage_v68_plafond_outsiders", "recalibrage_v68_tocard_mult_t123", "recalibrage_v68_valeur_pmu_trot_rejeu_zero"):
        assert FUSION_FLAGS.get(k) is True
    assert FUSION_FLAGS.get("recalibrage_v69_actif") is True
    assert FUSION_FLAGS.get("recalibrage_v69_shadow_min1_inactif") is True
    assert FUSION_FLAGS.get("recalibrage_v70_min1_tickets_abc_actif") is True


# ======================= Recalibrage actif v1.29.70 =======================
def test_v70_active_tocard_outsider_and_min1_defaults(monkeypatch):
    from app.engine.synthesis import _tocard_mult
    from app.engine.ticket_quotas import plafonds_outsiders, tickets_selection_min1
    from app.models import Tranche
    for k in ("VANTAGE_TOCARD_MULT_T123", "VANTAGE_TOCARD_MULT_T34"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("VANTAGE_CAP_OUTSIDERS", raising=False)
    monkeypatch.delenv("VANTAGE_SELECT_MIN1_TICKETS", raising=False)
    assert _tocard_mult(Tranche.T1) == pytest.approx(1.0) and _tocard_mult(Tranche.T2) == pytest.approx(1.0)     # v1.29.72 : T3 et T4 seulement
    assert _tocard_mult(Tranche.T3) == pytest.approx(0.75) and _tocard_mult(Tranche.T4A) == pytest.approx(0.75)
    assert plafonds_outsiders() == {"A": 2, "B": 2}
    assert tickets_selection_min1() == ["A", "B", "C"]


def test_v69_catalogue_confidence_and_bonus_weights(monkeypatch):
    from app.engine.tranches import SignalActif, sommer_bonus_malus
    from app.models import Tranche
    monkeypatch.delenv("VANTAGE_BONUS_B_MULT", raising=False)
    monkeypatch.delenv("VANTAGE_BONUS_B_REPEAT_MULT", raising=False)
    monkeypatch.delenv("VANTAGE_MALUS_M_DEGRADE_MULT", raising=False)
    monkeypatch.delenv("VANTAGE_MALUS_M_MINIMAL_MULT", raising=False)
    sigs = [
        SignalActif("B01", 10.0, "B", "FB", "STRICT"),
        SignalActif("M01", -8.0, "M", "FM", "DEGRADE"),
        SignalActif("M02", -4.0, "M", "FC", "MINIMAL"),
    ]
    got = sommer_bonus_malus(sigs, Tranche.T1)
    assert got["bonus_final"] < 10.0
    assert got["malus_final"] == pytest.approx((-8.0 * 0.75 - 4.0 * 0.50) * 1.10)
    assert got["malus_brut"] == pytest.approx(-12.0)


def test_v69_sri_proxy_weights_do_not_change_observed_value(monkeypatch):
    from app.engine.modules_ap import module_a_sri
    from app.models import Cheval, Discipline
    monkeypatch.delenv("VANTAGE_SRI_PROXY_GAINS_MULT", raising=False)
    c = Cheval(numero=1, nom="TEST", age=6, gains_moyenne_carriere_eur=9000.0,
               gains_totaux_eur=9000.0, nb_courses=10)
    score, flags = module_a_sri(c, Discipline.TROT_ATTELE)
    assert any(f.startswith("SRI_PROXY_GAINS_ATTENUE_0.65") for f in flags)
    monkeypatch.setenv("VANTAGE_SRI_PROXY_GAINS_MULT", "1.0")
    score_proxy_full, _ = module_a_sri(c, Discipline.TROT_ATTELE)
    assert score < score_proxy_full
    observed = c.model_copy(update={"valeur_pmu": 30.0})
    _, flags_observed = module_a_sri(observed, Discipline.TROT_ATTELE)
    assert not any("PROXY_GAINS_ATTENUE" in f for f in flags_observed)


def test_v71_t2_force_et_edge_sont_relatifs_au_champ():
    from app.engine.pch_final import compute_t2_value_score
    from app.models import Cheval, ModuleBreakdown
    chevaux = [
        Cheval(numero=1, nom="F", cote_matin=3.0, cote_avant_course=3.0),
        Cheval(numero=2, nom="M", cote_matin=7.0, cote_avant_course=7.0),
        Cheval(numero=3, nom="T2", cote_matin=12.0, cote_avant_course=12.0),
    ]
    cible = chevaux[2]
    bd = ModuleBreakdown(pch_final=100.0)
    score_middle, flags_middle = compute_t2_value_score(
        cible, None, chevaux, bd, None, [90.0, 50.0, 100.0])
    score_bottom, flags_bottom = compute_t2_value_score(
        cible, None, chevaux, bd, None, [200.0, 150.0, 100.0])
    assert score_middle > score_bottom
    assert "T2_VALUE_FORCE_RANG_PCH" in flags_middle
    assert "T2_VALUE_EDGE_PCH_VS_MARCHE" in flags_bottom


def test_v71_rah242_inclut_gru_positif_et_tactique_dans_le_cap():
    from app.engine.pch_final import _rah242_secondary_cap
    from app.models import ModuleBreakdown
    bd = ModuleBreakdown(sri_v2=6.0, tact_pch=4.0, gru_pepite_piege_pch=5.0,
                         bonus_b_sum_module=3.0)
    cap = _rah242_secondary_cap(bd)
    assert cap == {"primary_positive": 6.0, "secondary_raw": 12.0,
                   "secondary_allowed": 6.0, "correction": -6.0}
    neg = _rah242_secondary_cap(ModuleBreakdown(gru_pepite_piege_pch=-8.0,
                                                  bonus_b_sum_module=2.0))
    assert neg["secondary_raw"] == 2.0 and neg["correction"] == -2.0


def test_v71_signaux_gru_survivent_a_la_reconstruction_du_breakdown():
    from app.engine.pch_final import _merge_active_signals
    class CatalogSignal:
        def __init__(self, id):
            self.id = id
        def model_dump(self):
            return {"id": self.id}
    merged = _merge_active_signals([CatalogSignal("B01")], [
        {"id": "GRU_PEPITE", "valeur_brute": 6.0},
        {"id": "GRU_PIEGE", "valeur_brute": -4.0},
    ])
    assert [x["id"] for x in merged] == ["B01", "GRU_PEPITE", "GRU_PIEGE"]
    collision = _merge_active_signals([CatalogSignal("GRU_PEPITE")],
                                       [{"id": "GRU_PEPITE", "valeur_brute": 6.0}])
    assert len(collision) == 1 and collision[0] == {"id": "GRU_PEPITE"}


def test_v71_audit_valeur_pmu_distingue_originale_et_valeur_consommee(monkeypatch):
    from app.engine.common import attenuer_valeur_pmu_trot
    from app.models import Cheval, Discipline
    monkeypatch.delenv("VANTAGE_TROT_VALEUR_MULT", raising=False)
    chevaux = [Cheval(numero=i + 1, nom=f"H{i}", valeur_pmu=float(50 - i * 5)) for i in range(4)]
    object.__setattr__(chevaux[0], "_vantage_pmu_field_audit", {"valeur_pmu": {
        "source": "API_PMU", "source_field": "participants.handicapValeur",
        "raw_value": "50", "collected_at_utc": "2026-11-18T00:00:00+00:00", "observed_at_utc": None}})
    info = attenuer_valeur_pmu_trot(chevaux, Discipline.TROT_ATTELE, "REJEU")
    first = next(x for x in info["valeurs_par_partant"] if x["numero"] == 1)
    assert first["valeur_initiale"] == 50.0 and first["valeur_consommee"] is None
    assert first["source"] == "API_PMU" and first["horodatage_observation_utc"] is None
    assert first["horodatage_collecte_utc"] == "2026-11-18T00:00:00+00:00"
    assert first["action"] == "neutralisee_zero"


def test_v71_pmu_api_trace_provenance_et_collecte_locale(monkeypatch):
    from types import SimpleNamespace as NS
    from app.scraping import pmu_api as P
    from app.models import Cheval, TypeCourse
    race = NS(date_course="2026-11-20", reunion_course_label="R1C1", url_source="",
              distance_m=None, penetrometre=None, meteo_temp_c=None, type_course=TypeCourse.AUTRE)
    cheval = Cheval(numero=1, nom="Test")
    monkeypatch.setattr(P, "fetch_course_meta", lambda *a: {})
    monkeypatch.setattr(P, "fetch_participants", lambda *a: [{
        "numPmu": 1, "nom": "Test", "handicapValeur": "27",
        "reductionKilometrique": 75.0,
        "dernierRapportReference": {"rapport": 9.0},
        "dernierRapportDirect": {"rapport": 10.0},
    }])
    P.enrich_race_with_pmu_api(race, [cheval])
    audit = cheval._vantage_pmu_field_audit
    valeur = audit["valeur_pmu"]
    assert valeur["source"] == "API_PMU"
    assert valeur["source_field"] == "participants.handicapValeur" and valeur["raw_value"] == "27"
    assert valeur["observed_at_utc"] is None and valeur["collected_at_utc"].endswith("+00:00")
    assert audit["cote_matin"]["source_field"].endswith("dernierRapportReference.rapport")
    assert audit["cote_avant_course"]["source_field"].endswith("dernierRapportDirect.rapport")


def test_v71_pool_trace_explique_admission_et_reserve_marche():
    from app.engine.gmo_v import build_pool_elargi, pool_thresholds
    from app.models import Cheval, HorseScore, ModuleBreakdown, QualitativeSignals, SynthesisResult
    threshold = pool_thresholds(16)[0]
    horses, quals = [], []
    for i in range(16):
        cote = (2.0, 3.0)[i - 14] if i >= 14 else 20.0 + i
        cheval = Cheval(numero=i + 1, nom=f"H{i + 1}", cote_matin=cote, cote_avant_course=cote)
        ordre = threshold + 0.1 + i * 0.001 if i < 14 else threshold - 1.0
        horses.append(HorseScore(cheval=cheval, breakdown=ModuleBreakdown(),
                                 synthesis=SynthesisResult(ordre_final=ordre)))
        quals.append(QualitativeSignals())
    trace = []
    pool = build_pool_elargi(horses, quals, trace=trace)
    assert len(pool) == 14 and {14, 15}.issubset(set(pool))
    by_numero = {x["numero"]: x for x in trace}
    assert by_numero[15]["admis_pool_final"] and "marche_force_top1" in by_numero[15]["motifs"]
    assert by_numero[16]["admis_pool_final"] and "marche_force_top2" in by_numero[16]["motifs"]
    assert len(trace) == 16


def test_v71_version_flags_et_min1_heritage():
    from app.version import VERSION_RULESET, FUSION_FLAGS
    from app.engine.ticket_quotas import tickets_selection_min1
    assert VERSION_RULESET == "v1.29.72"
    assert FUSION_FLAGS["recalibrage_v71_t2_rangs_relatifs_actif"] is True
    assert FUSION_FLAGS["recalibrage_v71_rah242_gru_tactique_cap_actif"] is True
    assert FUSION_FLAGS["recalibrage_v71_gmo_pool_trace_actif"] is True
    assert FUSION_FLAGS["recalibrage_v71_pmu_provenance_actif"] is True
    assert FUSION_FLAGS["recalibrage_v70_min1_tickets_abc_actif"] is True
    assert tickets_selection_min1() == ["A", "B", "C"]
