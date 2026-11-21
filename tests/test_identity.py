"""Non-régression v1.29.40 : identité de course, fusion, fuite temporelle, découverte."""
import pytest

from app.models import Cheval, Depart, Discipline, RaceContext, TypeCourse
from app.scraping import router, discovery_multi as dm, discovery_zoneturf as dz
from app.scraping.hippodrome_normalize import hippodromes_match
from app.scraping.identity import (
    filtrer_avant, identite_depuis_urls, identite_incoherente, noms_concordent, parse_label_rc,
)
from app.scraping.pmu_api import extraire_reunion_course


def _race(disc=Discipline.PLAT, hippo="Chantilly", date="2026-10-03", label=None, url="u"):
    return RaceContext(url_source=url, hippodrome=hippo, discipline=disc, distance_m=2000,
                       type_course=TypeCourse.CONDITIONS, depart=list(Depart)[0],
                       partants_confirmes=14, date_course=date, reunion_course_label=label)


def _chevaux(prefix="H", n=14, **kw):
    out = []
    for i in range(1, n + 1):
        c = Cheval(numero=i, nom=f"{prefix}{i}", cote_matin=5.0 + i, cote_avant_course=5.0 + i, musique="1p2p")
        for k, v in kw.items():
            setattr(c, k, v)
        out.append(c)
    return out


def _run(store, **kw):
    router.scrape_race = lambda u: store[u]
    return router.scrape_race_with_fallback(list(store), **kw)


# ---------- R/C
def test_zoneturf_url_reunion_3_is_r3_not_r1():
    r = _race(label="R3C4", url="https://www.zone-turf.fr/programmes/r3-vincennes-198944.html#4")
    assert extraire_reunion_course(r) == (3, 4)


def test_no_default_r1_for_course_only_label():
    assert extraire_reunion_course(_race(label="C4", url="https://www.canalturf.com/x")) is None


def test_zoneturf_scraper_label_uses_url_reunion():
    from app.scraping.zoneturf import _reunion_depuis_url
    assert _reunion_depuis_url("https://www.zone-turf.fr/programmes/r5-vincennes-1.html#2") == 5


def test_identity_from_urls_vote():
    d = identite_depuis_urls([
        "https://www.turfoo.fr/programmes-courses/261003/reunion3-vincennes/course4-prix-x/",
        "https://www.zone-turf.fr/programmes/r3-vincennes-198944.html#4",
        "https://www.canalturf.com/pronostics-PMU/2026-10-03/vincennes/123_prix-x.html"])
    assert (d["date"], d["reunion"], d["course"]) == ("2026-10-03", 3, 4)


def test_identity_rejects_other_reunion_and_date():
    att = {"hippodrome": "Chantilly", "date": "2026-10-03", "reunion": 3, "course": 4}
    assert "réunion" in identite_incoherente(_race(label="R1C4"), att)
    assert "date" in identite_incoherente(_race(date="2026-10-04", label="R3C4"), att)
    assert identite_incoherente(_race(label="R3C4"), att) is None


def test_label_forced_by_expected_identity():
    store = {"https://www.zone-turf.fr/programmes/r1-chantilly-1.html#4": (_race(label="C4"), _chevaux(), [])}
    race, *_ = _run(store, expected_identity={"reunion": 3, "course": 4})
    assert race.reunion_course_label == "R3C4"


# ---------- noms
def test_names_guard_basic():
    ok, r = noms_concordent(_chevaux("A"), {i: f"B{i}" for i in range(1, 15)})
    assert not ok and r == 0


def test_merge_rejects_source_with_other_horses():
    base = _chevaux("Alpha", gains_totaux_eur=1000, valeur_pmu=30.0, driver_jockey="X", entraineur="Y", fiche_url="f")
    autre = _chevaux("ZZZ", poids_actuel_kg=59.5)
    store = {"https://www.turfoo.fr/a": (_race(), base, []), "https://www.canalturf.com/b": (_race(url="b"), autre, [])}
    _, ch, w, _ = _run(store, expected_hippodrome="Chantilly")
    assert ch[0].nom == "Alpha1" and ch[0].poids_actuel_kg is None
    assert any("IDENTITE_SOURCE_REJETEE" in x for x in w)


def test_merge_accepts_same_horses():
    base = _chevaux("H", gains_totaux_eur=1000, valeur_pmu=30.0, driver_jockey="X", entraineur="Y", fiche_url="f")
    store = {"https://www.turfoo.fr/a": (_race(), base, []), "https://www.canalturf.com/b": (_race(url="b"), _chevaux("H", poids_actuel_kg=59.5), [])}
    _, ch, _, _ = _run(store)
    assert ch[0].poids_actuel_kg == 59.5


def test_merge_rejects_other_date():
    store = {"https://www.turfoo.fr/a": (_race(date="2026-10-03"), _chevaux(gains_totaux_eur=5), []),
             "https://www.canalturf.com/b": (_race(date="2026-10-04", url="b"), _chevaux(), [])}
    _, _, w, _ = _run(store, expected_identity={"date": "2026-10-03"})
    assert any("date incohérente" in x for x in w)


# ---------- discipline
def test_discipline_tie_does_not_flip_plat_to_trot(monkeypatch):
    monkeypatch.setattr(router, "_discipline_exacte_pmu", lambda a, r: None)
    store = {"https://www.turfoo.fr/a": (_race(Discipline.PLAT), _chevaux(gains_totaux_eur=1, valeur_pmu=1.0, driver_jockey="a", entraineur="b"), []),
             "https://www.canalturf.com/b": (_race(Discipline.TROT_ATTELE, url="b"), _chevaux(), [])}
    race, _, w, _ = _run(store)
    assert race.discipline == Discipline.PLAT
    assert any("DISCIPLINE_CONFLIT_NON_ARBITRE" in x for x in w)


def test_discipline_tie_uses_pmu_arbiter(monkeypatch):
    monkeypatch.setattr(router, "_discipline_exacte_pmu", lambda a, r: Discipline.TROT_ATTELE)
    store = {"https://www.turfoo.fr/a": (_race(Discipline.PLAT), _chevaux(gains_totaux_eur=1, valeur_pmu=1.0, driver_jockey="a", entraineur="b"), []),
             "https://www.canalturf.com/b": (_race(Discipline.TROT_ATTELE, url="b"), _chevaux(), [])}
    race, *_ = _run(store)
    assert race.discipline == Discipline.TROT_ATTELE


def test_discipline_majority_wins():
    store = {f"https://www.canalturf.com/{i}": (_race(Discipline.PLAT if i < 2 else Discipline.TROT_ATTELE, url=str(i)), _chevaux(), []) for i in range(3)}
    race, *_ = _run(store)
    assert race.discipline == Discipline.PLAT


# ---------- hippodromes
@pytest.mark.parametrize("a,b", [("Saint-Cloud", "Saint-Brieuc"), ("Saint-Cloud", "Saint-Malo"),
                                 ("La Teste", "La Capelle"), ("Saint-Galmier", "Saint-Cloud"), ("Cordemais", "Agen")])
def test_hippodrome_no_false_positive(a, b):
    assert not hippodromes_match(a, b)


@pytest.mark.parametrize("a,b", [("Saint-Cloud", "Saint-Cloud"), ("Maisons-Laffitte", "Maisons Laffitte"),
                                 ("Cagnes-sur-Mer", "cagnes sur mer"), ("Vincennes", "Vincennes")])
def test_hippodrome_true_positive(a, b):
    assert hippodromes_match(a, b)


# ---------- fuite temporelle
class _H:
    def __init__(self, d): self.date = d


def test_filtrer_avant_excludes_day_j_and_future():
    out = filtrer_avant([_H("2026-10-03"), _H("2026-10-10"), _H("2026-09-12")], "2026-10-03")
    assert [h.date for h in out] == ["2026-09-12"]


def test_delai_j_ignores_race_itself_and_future():
    from app.scraping.turfoo_fiche_cheval import compute_delai_j, FicheChevalHistorique
    f = FicheChevalHistorique.__dataclass_fields__

    def h(d):
        kw = {k: None for k in f}; kw["date"] = d
        return FicheChevalHistorique(**kw)
    assert compute_delai_j([h("2026-10-03"), h("2026-10-10"), h("2026-09-12")], "2026-10-03") == 21


def test_fenetres_exclude_day_j():
    from app.scraping.turfoo_fiche_personne import fenetres_victoires

    class C:
        def __init__(s, d, r): s.date, s.rang = d, r
    hp = [C("2026-10-03", 1), C("2026-10-01", 3), C("2026-09-20", 1), C("2026-08-01", 1)]
    f = {w["jours"]: w for w in fenetres_victoires(hp, "2026-10-03", [7, 30])}
    assert f[7] == {"jours": 7, "victoires": 0, "courses": 1}


# ---------- découverte
class _C:
    def __init__(s, u): s.url, s.score, s.label = u, 0.9, "x"


def _ok(u): return lambda *a, **k: [_C(u)]


def _boom(msg):
    def f(*a, **k): raise RuntimeError(msg)
    return f


def test_antibot_exemption_only_for_geny(monkeypatch):
    monkeypatch.setattr(dm, "_SOURCES", [("canalturf", _ok("https://www.canalturf.com/x")),
                                         ("turfoo", _boom("HTTP 403 Forbidden")),
                                         ("zoneturf", _ok("https://www.zone-turf.fr/programmes/r1-v-1.html#1")),
                                         ("geny", _boom("GENY_ANTIBOT"))])
    rep = dm.discover_all_sources("2026-10-03", "Vincennes", 1, None, 1)
    assert "erreur" in rep.par_source["turfoo"]
    assert "ignore" in rep.par_source["geny"]
    assert rep.sources_applicables == 3 and rep.sources_reussies == 2


def test_zoneturf_no_today_fallback_for_other_date(monkeypatch):
    html_today = '<a href="/programmes/r1-vincennes-198944.html">R1</a>'

    def fake(url, **k):
        if url.rstrip("/").endswith("/programmes"):
            return html_today
        raise RuntimeError("404")
    monkeypatch.setattr(dz, "fetch_html", fake)
    with pytest.raises(ValueError):
        dz._list_reunion_pages("2020-01-02")


def test_label_parse():
    assert parse_label_rc("R3C4") == (3, 4) and parse_label_rc("C4") == (None, 4)


def test_main_requires_two_sources(monkeypatch):
    from fastapi import HTTPException
    from app import main
    from app.scraping.discovery_multi import DiscoveryReport
    monkeypatch.setattr(main, "discover_all_sources", lambda *a, **k: DiscoveryReport(
        urls=["https://www.canalturf.com/x"], par_source={}, taux_collecte=1.0, sources_applicables=1, sources_reussies=1))
    with pytest.raises(HTTPException) as e:
        main.create_race_auto(main.AutoRaceRequest(date="2026-10-03", reunion_num=1, course_num=1), None)
    assert e.value.status_code == 422
