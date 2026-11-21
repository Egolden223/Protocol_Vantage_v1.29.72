"""
post_race_audit.py -- Audit post-course automatique et mécanique (sans LLM).

Ce module fait ce qu'un calcul peut faire honnêtement :
  - Récupérer l'arrivée officielle (app/scraping/turfoo_resultats.py)
  - Calculer le taux de capture en ordre libre (désordre)
  - Lister les chevaux du top 5 réel manqués par notre ticket, avec leurs
    cotes et ce que notre moteur avait dit d'eux avant la course
  - Lister nos chevaux du ticket qui finissent hors du top 5 réel
  - Diagnostiquer mécaniquement les causes probables : pour chaque manqué,
    quels modules/signaux ont tiré le score vers le bas alors que le
    cheval a gagné (signal contredit par le résultat) ; pour chaque
    sur-évalué, l'inverse

Ce qui N'EST PAS fait ici (nécessiterait une lecture de texte/recherche
web, donc un LLM) : rechercher des comptes-rendus et analyses de presse
sur la course. Le rapport laisse une section dédiée, explicitement vide,
pour ce point -- voir README.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import logging

from app.models import RaceResult, HorseScore
from app.scraping.turfoo_resultats import ArrivalHorse, fetch_arrival
from app.scraping.pmu_api import fetch_official_arrival_pmu, extraire_reunion_course

logger = logging.getLogger("vantage.engine.post_race_audit")

_DOMAIN_LABELS = {
    "turfoo.fr": "Turfoo",
    "www.turfoo.fr": "Turfoo",
    "canalturf.com": "CanalTurf",
    "www.canalturf.com": "CanalTurf",
    "zone-turf.fr": "Zone-Turf",
    "www.zone-turf.fr": "Zone-Turf",
    "geny.com": "Geny",
    "www.geny.com": "Geny",
}


def _label_source_secondaire(url: Optional[str]) -> str:
    """CORRECTIF 19/09/2026 (Golden) : cette source était auparavant
    toujours étiquetée "Turfoo" dans confirmation_sources, quel que soit
    le domaine réel de urls[0] -- ex. un audit du 19/09 étiquetait
    "Turfoo" une URL canalturf.com. Le label suit maintenant le vrai
    domaine (Turfoo/CanalTurf/Zone-Turf/Geny), avec un repli générique
    pour tout autre domaine plutôt qu'un mensonge par défaut."""
    if not url:
        return "Source secondaire"
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()
    return _DOMAIN_LABELS.get(domain, f"Source secondaire ({domain})")


def confirm_arrival(result: RaceResult, urls: List[str]) -> Tuple[List[ArrivalHorse], Dict[str, Any]]:
    """Récupère l'arrivée officielle en exigeant 2 sources indépendantes
    (API PMU officielle + la source secondaire donnée dans urls[0], quel
    que soit son domaine -- Turfoo, CanalTurf, Zone-Turf, Geny...),
    demandé explicitement le 06/09/2026 : "doit être obligatoirement
    confirmé par au moins 2 sources". Ne bloque jamais l'audit si une
    seule source répond -- mais le dit clairement (confirmation_sources.
    statut) plutôt que de faire croire à une confirmation qui n'a pas eu
    lieu.

    CORRECTIF 19/09/2026 (Golden) : la 2e source était auparavant TOUJOURS
    étiquetée "Turfoo" dans le rapport, même quand urls[0] pointait vers
    un autre domaine (ex. CanalTurf) -- et pire, quand fetch_arrival()
    (spécifique à la structure Turfoo) échouait silencieusement sur ce
    domaine puis qu'Equidia prenait le relais en repli, le rapport
    continuait à afficher "Turfoo: confirmé" alors que la vraie 2e source
    était Equidia. _label_source_secondaire() dérive maintenant le nom
    affiché du domaine réel de urls[0], et le bascule explicitement sur
    "Equidia" quand le repli a lieu -- voir un audit du 19/09/2026
    (course 3ea4f3cdde07) qui illustrait exactement ce cas.

    Retourne (arrivee_retenue, confirmation) où confirmation contient :
      - statut : "CONFIRME_2_SOURCES" | "NON_CONFIRME_1_SOURCE" | "ECHEC_TOTAL"
      - sources_tentees / sources_reussies
      - desaccord : détail si les 2 sources donnent un Top5 différent
        (l'API PMU officielle est alors retenue comme référence, mais le
        désaccord est montré, jamais caché)
    """
    ctx = result.context
    arrivee_pmu, arrivee_turfoo = None, None
    erreurs = {}

    # R/C : label → URLs → resolve programme PMU (hippo+distance)
    from app.scraping.pmu_api import resolve_rc_from_programme
    rc = extraire_reunion_course(ctx)
    if rc is None:
        try:
            rc = resolve_rc_from_programme(ctx)
            if rc:
                ctx.reunion_course_label = f"R{rc[0]}C{rc[1]}"
        except Exception as e:
            erreurs["resolve_rc"] = str(e)

    if rc and ctx.date_course:
        try:
            arrivee_pmu = fetch_official_arrival_pmu(ctx.date_course, rc[0], rc[1])
        except Exception as e:
            erreurs["API PMU officielle"] = str(e)
    else:
        erreurs["API PMU officielle"] = (
            f"réunion/course ou date non identifiables "
            f"(label={getattr(ctx, 'reunion_course_label', None)!r}, "
            f"date={getattr(ctx, 'date_course', None)!r})"
        )

    # Source secondaire : privilégier une URL Turfoo (parseur dédié),
    # sinon tenter chaque URL fournie (échec silencieux par source).
    url_list = list(urls or [])
    if ctx.url_source and ctx.url_source not in url_list:
        url_list.append(ctx.url_source)
    turfoo_urls = [u for u in url_list if u and "turfoo" in u.lower()]
    other_urls = [u for u in url_list if u and "turfoo" not in u.lower()]
    ordered = turfoo_urls + other_urls

    arrivee_turfoo = None
    label_secondaire = "source_secondaire"
    last_err = None
    for candidate in ordered:
        label_secondaire = _label_source_secondaire(candidate)
        if "turfoo" not in (candidate or "").lower():
            # fetch_arrival est spécifique Turfoo — skip autres domaines
            last_err = f"{label_secondaire}: parseur arrivée non supporté (URL non-Turfoo)"
            continue
        try:
            arrivee_turfoo = fetch_arrival(candidate)
            if arrivee_turfoo:
                break
        except Exception as e:
            last_err = str(e)
            arrivee_turfoo = None
    if arrivee_turfoo is None and last_err:
        erreurs[label_secondaire] = last_err

    # Equidia post-course : source de confirmation tertiaire (audit uniquement)
    arrivee_equidia = None
    if rc and ctx.date_course:
        try:
            from app.scraping.equidia import fetch_equidia_arrivee_for_audit
            from app.scraping.turfoo_resultats import ArrivalHorse as AH
            eq = fetch_equidia_arrivee_for_audit(str(ctx.date_course)[:10], rc[0], rc[1])
            if eq.get("status") == "OK" and eq.get("ordre_arrivee"):
                by_nom = {p["numero"]: p.get("nom") or "" for p in (eq.get("partants") or [])}
                arrivee_equidia = [
                    AH(rang=i + 1, numero=n, nom=by_nom.get(n, ""))
                    for i, n in enumerate(eq["ordre_arrivee"])
                ]
        except Exception as e:
            erreurs["Equidia"] = str(e)

    # Si la source secondaire (urls[0]) est absente, Equidia peut servir de 2e source
    if arrivee_turfoo is None and arrivee_equidia is not None:
        arrivee_turfoo = arrivee_equidia
        erreurs.pop(label_secondaire, None)
        erreurs[f"{label_secondaire}_remplace_par"] = "Equidia (arrivée post-course)"
        label_secondaire = "Equidia"


    # Liens exacts des sources d'arrivée (audit)
    # secondary_url peut être None si aucune URL Turfoo ; on journalise
    # la meilleure URL candidate utilisée (ou la première de la liste).
    secondary_url = None
    for candidate in ordered:
        if candidate and "turfoo" in candidate.lower():
            secondary_url = candidate
            break
    if secondary_url is None and ordered:
        secondary_url = ordered[0]
    liens_audit = {
        "api_pmu_officielle": (
            f"https://offline.turfinfo.api.pmu.fr/rest/client/1/programme/"
            f"{(str(ctx.date_course)[:10].replace('-', '') if ctx.date_course else '')}/"
            f"R{rc[0]}/C{rc[1]}/participants"
            if rc and ctx.date_course else None
        ),
        f"{_label_source_secondaire(secondary_url).lower().replace(' ', '_').replace('(', '').replace(')', '')}_programme": secondary_url,
        "equidia_arrivee": None,
    }
    if rc and ctx.date_course:
        try:
            from app.scraping.equidia import build_equidia_url
            liens_audit["equidia_arrivee"] = build_equidia_url(str(ctx.date_course)[:10], rc[0], rc[1])
        except Exception:
            pass

    sources_reussies = [n for n, a in (("API PMU officielle", arrivee_pmu), (label_secondaire, arrivee_turfoo)) if a]

    if arrivee_pmu and arrivee_turfoo:
        top5_pmu = [h.numero for h in arrivee_pmu[:5]]
        top5_turfoo = [h.numero for h in arrivee_turfoo[:5]]
        accord = top5_pmu == top5_turfoo
        confirmation = {
            "statut": "CONFIRME_2_SOURCES" if accord else "DESACCORD_ENTRE_SOURCES",
            "sources_tentees": ["API PMU officielle", label_secondaire],
            "sources_reussies": sources_reussies,
            "liens_sources": liens_audit,
            "top5_api_pmu_officielle": top5_pmu,
            f"top5_{label_secondaire.lower().replace(' ', '_').replace('(', '').replace(')', '')}": top5_turfoo,
        }
        if not accord:
            confirmation["desaccord"] = (
                "Les 2 sources donnent un ordre d'arrivée Top5 différent -- l'API PMU officielle "
                "est retenue comme référence (source primaire officielle), mais cet audit repose "
                "sur un désaccord non résolu : à vérifier manuellement avant d'en tirer des "
                "conclusions sur le protocole.")
            logger.warning("Désaccord arrivée %s vs %s (course %s)", top5_pmu, top5_turfoo, ctx.hippodrome)
        return arrivee_pmu, confirmation

    if arrivee_pmu or arrivee_turfoo:
        arrivee = arrivee_pmu or arrivee_turfoo
        confirmation = {
            "statut": "NON_CONFIRME_1_SOURCE",
            "sources_tentees": ["API PMU officielle", label_secondaire],
            "sources_reussies": sources_reussies,
            "liens_sources": liens_audit,
            "erreurs": erreurs,
            "avertissement": (
                "Une seule source a répondu -- cet audit N'EST PAS confirmé par 2 sources "
                "indépendantes comme requis. Les chiffres ci-dessous restent probablement "
                "corrects (source officielle ou Turfoo, toutes deux généralement fiables prises "
                "isolément) mais n'ont pas été recoupés."),
        }
        return arrivee, confirmation

    raise ValueError(f"Aucune source d'arrivée n'a répondu (PMU: {erreurs.get('API PMU officielle')} ; "
                      f"{label_secondaire}: {erreurs.get(label_secondaire)})")


def _extraire_label_module(diagnostic: str) -> str:
    """'MODULE_POIDS = -5.2 (...)' -> 'MODULE_POIDS'"""
    return diagnostic.split(" = ")[0].strip()


def _stats_portee(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    import math
    n = len(rows)

    def moy(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(v) / len(v), 3) if v else None
    diff = [r["B"] - r["C"] for r in rows if r.get("B") is not None and r.get("C") is not None]
    ic = None
    if len(diff) >= 2:
        m = sum(diff) / len(diff)
        sd = math.sqrt(sum((x - m) ** 2 for x in diff) / (len(diff) - 1))
        ic = round(1.96 * sd / math.sqrt(len(diff)), 3)
    return {"nb_courses": n, "capture_A": moy("A"), "capture_B": moy("B"), "capture_C": moy("C"),
            "ecart_B_moins_C": (round(sum(diff) / len(diff), 3) if diff else None), "ic95_ecart": ic, "effectif_suffisant": n >= 30}


def _par_portee(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"famille": {}, "famille_distance": {}, "hippodrome": {}}
    groupes = (("famille", lambda r: r["famille"]), ("famille_distance", lambda r: f"{r['famille']}|{r['distance']}"),
               ("hippodrome", lambda r: r["hippodrome"]))
    for nom, cle in groupes:
        g: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            g.setdefault(cle(r), []).append(r)
        out[nom] = {k: _stats_portee(v) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}
    return out


def aggregate_audit_patterns(audits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrège les audits de plusieurs courses pour répondre à la demande
    du 06/09/2026 : "comprendre en quoi le protocole a fauté afin de
    préparer les prochaines mises à jour du système si les mêmes erreurs
    se reproduisent sur plusieurs courses". Compte la récurrence des
    modules cités comme cause de manqué/sur-évalué -- un module qui
    revient souvent est un vrai candidat de correctif, un module cité
    une seule fois est probablement du bruit ponctuel."""
    from collections import Counter

    nb_courses_avec_audit = len(audits)
    taux_captures = []
    taux_captures_B = []
    taux_captures_C = []
    causes_ia: Dict[str, int] = {}
    modules_ia: Dict[str, int] = {}
    causes_det: Dict[str, int] = {}
    causes_manques = Counter()
    causes_surevalues = Counter()
    flags_manques = Counter()
    flags_surevalues = Counter()
    nb_manques_total = nb_surevalues_total = 0
    profil_manques_agrege = Counter()
    gains_struct = {k: {"nb_courses": 0, "desordre": 0, "bonus": 0, "ordre": 0, "bases_dans_top5": 0}
                    for k in ("A", "B", "C")}
    portee_rows: List[Dict[str, Any]] = []      # v1.29.67 : une ligne par course (famille, distance, hippodrome, captures A / B / C)

    for row in audits:
        audit = row["audit"]
        if audit.get("taux_capture_desordre") is not None:
            taux_captures.append(audit["taux_capture_desordre"])
        _syn = ((audit.get("analyse_presse_post_course") or {}).get("synthese")) or {}
        for _k, _v in (_syn.get("par_cause") or {}).items():
            causes_ia[_k] = causes_ia.get(_k, 0) + _v
        for _k, _v in (_syn.get("modules_en_cause") or {}).items():
            modules_ia[_k] = modules_ia.get(_k, 0) + _v
        for _c in audit.get("ticket_hors_top5") or []:
            _cd = _c.get("cause_deterministe")
            if _cd:
                causes_det[_cd] = causes_det.get(_cd, 0) + 1
        for _l, _src in (("A", audit), ("B", audit.get("audit_ticket_B") or {}), ("C", audit.get("audit_ticket_C") or {})):
            _iss = ((_src.get("structure_bases_complements") or {}).get("issue")) or {}
            if _iss and not _iss.get("arrivee_incomplete") and "desordre" in _iss:
                g = gains_struct[_l]
                g["nb_courses"] += 1
                g["desordre"] += bool(_iss["desordre"]); g["bonus"] += bool(_iss["bonus"]); g["ordre"] += bool(_iss["ordre"])
                g["bases_dans_top5"] += _iss.get("nb_bases_dans_top5", 0)
        try:   # v1.29.67 : ligne de portée de la course (famille de discipline, tranche de distance, hippodrome) + captures A / B / C
            from app.engine.gru_catalog import famille_course, tranche_distance, normalize_hippo_key
            _rt = audit.get("recap_technique") or {}
            _fa = famille_course(type("_R", (), {"discipline": _rt.get("discipline")})())
            _ca = audit.get("taux_capture_desordre")
            _cb = (audit.get("audit_ticket_B") or {}).get("taux_capture_desordre")
            _cc = (audit.get("audit_ticket_C") or {}).get("taux_capture_desordre")
            if _ca is not None or _cb is not None or _cc is not None:
                portee_rows.append({"famille": _fa, "distance": tranche_distance(_rt.get("distance_m")),
                                    "hippodrome": normalize_hippo_key(_rt.get("hippodrome")) or str(_rt.get("hippodrome") or "?").lower(),
                                    "A": None if _ca is None else _ca * 5, "B": None if _cb is None else _cb * 5,
                                    "C": None if _cc is None else _cc * 5})
        except Exception:   # noqa: BLE001 -- l'agrégation par portée ne doit jamais faire échouer l'audit
            pass
        _c = audit.get("audit_ticket_C") or {}
        if _c.get("taux_capture_desordre") is not None:
            taux_captures_C.append(_c["taux_capture_desordre"])
        _b = audit.get("audit_ticket_B") or {}
        if _b.get("taux_capture_desordre") is not None:
            taux_captures_B.append(_b["taux_capture_desordre"])
        for m in audit.get("chevaux_manques", []):
            nb_manques_total += 1
            for diag in m.get("signaux_sous_evalues", []):
                causes_manques[_extraire_label_module(diag)] += 1
            for flag in m.get("flags", []):
                flags_manques[flag] += 1
        pm = audit.get("profil_manques_marche") or {}
        for k in ("T1_FAVORI", "T2_SEMI_FAVORI", "T3", "T4_OUTSIDER", "COTE_INCONNUE"):
            profil_manques_agrege[k] += pm.get(k, 0)
        for h in audit.get("ticket_hors_top5", []):
            nb_surevalues_total += 1
            for diag in h.get("signaux_surevalues", []):
                causes_surevalues[_extraire_label_module(diag)] += 1
            for flag in h.get("flags", []):
                flags_surevalues[flag] += 1

    def _top(counter: Counter, n=8):
        return [{"cause": k, "nb_occurrences": v,
                  "pct_courses_analysees": round(100 * v / max(nb_courses_avec_audit, 1), 1)}
                for k, v in counter.most_common(n)]

    return {
        "nb_courses_analysees": nb_courses_avec_audit,
        "taux_capture_moyen": round(sum(taux_captures) / len(taux_captures), 3) if taux_captures else None,
        "taux_capture_moyen_ticket_B": round(sum(taux_captures_B) / len(taux_captures_B), 3) if taux_captures_B else None,
        "nb_courses_ticket_B": len(taux_captures_B),
        "taux_capture_moyen_ticket_C": round(sum(taux_captures_C) / len(taux_captures_C), 3) if taux_captures_C else None,
        "nb_courses_ticket_C": len(taux_captures_C),
        # v1.29.67 : captures par PORTÉE (famille, famille x distance, hippodrome) avec IC95 ; effectif_suffisant = au moins 30 courses
        "par_portee": _par_portee(portee_rows),
        # v1.29.58 : gains « champ réduit » par ticket (nb de courses où désordre / bonus / ordre sont atteints)
        "gains_champ_reduit": {k: {**g, "taux_desordre": (round(g["desordre"] / g["nb_courses"], 3) if g["nb_courses"] else None),
                                   "bases_moyennes_dans_top5": (round(g["bases_dans_top5"] / g["nb_courses"], 2) if g["nb_courses"] else None)}
                               for k, g in gains_struct.items()},
        "causes_post_course_ia": causes_ia,
        "modules_en_cause_ia": modules_ia,
        "sur_evalues_par_cause_deterministe": causes_det,
        "nb_chevaux_manques_total": nb_manques_total,
        "nb_chevaux_surevalues_total": nb_surevalues_total,
        "causes_recurrentes_manques": _top(causes_manques),
        "causes_recurrentes_surevalues": _top(causes_surevalues),
        "flags_recurrents_manques": _top(flags_manques),
        "flags_recurrents_surevalues": _top(flags_surevalues),
        "profil_manques_marche_agrege": {
            **dict(profil_manques_agrege),
            "note": (
                "v1.29.17 -- si T1_FAVORI+T2_SEMI_FAVORI dépasse une part "
                "significative de nb_chevaux_manques_total sur cet échantillon, "
                "la série d'assouplissements récents (malus M, MPA, quota) est "
                "probablement allée trop loin et mérite d'être resserrée."
            ),
        },
        "note": (
            "Une cause citée sur une part significative des courses analysées (ex. >20-30%) est "
            "un vrai candidat de correctif du protocole -- une cause isolée à 1-2 courses est "
            "probablement du bruit. Comparer nb_occurrences à nb_courses_analysees avant d'agir."
        ),
    }


def _horse_by_numero(horses: List[HorseScore], numero: int) -> Optional[HorseScore]:
    for h in horses:
        if h.cheval.numero == numero:
            return h
    return None


_MODULE_LABELS = {
    "sri_v2": "SRI (référence individuelle)", "iff_v2": "IFF (forme/fitness)",
    "nrc": "NRC (normalisation champ)", "bsh_v3v4": "BSH (driver/jockey)",
    "bsc_v3": "BSC (entraîneur)", "stab_pch": "STAB (stabilité/risque DQ)",
    "module_poids": "MODULE_POIDS", "module_recul": "MODULE_RECUL",
    "module_terrain_dyn": "MODULE_TERRAIN_DYN", "module_dist_adapt": "MODULE_DIST_ADAPT",
    "mpa_champ": "MPA_CHAMP (rythme)", "cre_total": "CRE (chrono relatif)",
    "tandem_final": "TANDEM_BONUS", "bonus_b_sum_module": "Bonus catalogue B",
    "malus_m_sum_module": "Malus catalogue M", "forme_lineaire_pch": "FORME_LINEAIRE",
    # Postes ajoutés le 07/08/2026 -- absents jusqu'ici, alors que tous
    # contribuent réellement à PCH_FINAL (cf. pch_final.py::pch_avant_penalite).
    # Sans eux, l'audit ne pouvait jamais citer GAMMA ou les correctifs
    # Phase 1 (M04/RAH-200/etc.) comme cause d'un manqué ou d'un sur-évalué,
    # même quand ils pesaient réellement dans le score.
    "gamma_pch": "GAMMA (RAH-179/182/183/184)", "rah200_pch": "RAH-200 (convergence familles)",
    "m04_pch": "M04 (correction intention, poste 21)", "d45_pch": "D45 (Ghost synergy, toujours 0 -- non implémenté)",
    "d46_d22_pch": "D46-D22 (toujours 0 -- non implémenté)", "d02_b59_pch": "D02-B59 (toujours 0 -- non implémenté)",
    "m48_b42_pch": "M48-B42 (toujours 0 -- non implémenté)", "rah186_pch": "RAH-186 (toujours 0 -- non implémenté)",
    "m33_pch": "M33 (toujours 0 -- non implémenté)", "discipline_specifique_pch": "Module discipline-spécifique",
}


def _diagnostic_modules(bd, direction: str) -> List[str]:
    """direction='sous_evalue' -> cherche les postes négatifs qui ont tiré
    le score vers le bas (candidat manqué qui a gagné) ; direction=
    'surevalue' -> cherche les postes positifs qui ont gonflé le score
    (cheval du ticket fini hors top5)."""
    items = []
    for field, label in _MODULE_LABELS.items():
        val = getattr(bd, field, 0.0)
        if direction == "sous_evalue" and val < -3:
            items.append(f"{label} = {val:+.1f} (a pénalisé un cheval qui a pourtant bien couru)")
        elif direction == "surevalue" and val > 5:
            items.append(f"{label} = {val:+.1f} (a valorisé un cheval qui n'a pas confirmé)")
    items.sort(key=lambda s: abs(float(s.split('=')[1].split('(')[0])), reverse=True)
    return items[:4]


_INCIDENTS_GRAVES = ("TOMB", "ARRET", "DISQ", "DISTANC", "POTEAU", "REFUS", "ALLURE", "DEROB", "ELIMIN")


def _resultat_reel(num: int, resultats: Optional[Dict[int, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Ce qui s'est réellement passé pour ce cheval (rang, incident officiel, commentaire)."""
    r = (resultats or {}).get(num)
    if not r:
        return None
    return {"rang": r.get("rang"), "statut": r.get("statut"), "incident": r.get("incident"),
            "ecart": r.get("ecart"), "commentaire": r.get("commentaire")}


def _cause_deterministe(res: Optional[Dict[str, Any]]) -> str:
    """Classement SANS IA d'un cheval de notre ticket hors Top 5 :
    INCIDENT_COURSE (tombé/arrêté/disqualifié : malchance, pas une erreur d'évaluation),
    PROCHE_DU_TOP5 (6e-8e), HORS_PLACE (9e et plus), NON_DOCUMENTE (résultat complet indisponible)."""
    if not res:
        return "NON_DOCUMENTE"
    inc = (res.get("incident") or "").upper()
    if inc and any(k in inc for k in _INCIDENTS_GRAVES):
        return "INCIDENT_COURSE"
    rang = res.get("rang")
    if rang is None:
        return "INCIDENT_COURSE" if (res.get("statut") or "").upper() not in ("", "PARTANT") else "NON_DOCUMENTE"
    return "PROCHE_DU_TOP5" if rang <= 8 else "HORS_PLACE"


def _structure_audit(result, ticket: str, arrival) -> Optional[Dict[str, Any]]:
    """Structure 3 bases + 5 compléments du ticket + issue (désordre/bonus/ordre) face à l'arrivée officielle."""
    try:
        from app.engine.ticket import evaluer_structure
        structure = (getattr(result, "structures_tickets", None) or {}).get(ticket)
        if not structure:
            return None
        issue = evaluer_structure(structure, [h.numero for h in arrival[:5]])
        return {"structure": structure, "issue": issue}
    except Exception as e:  # noqa: BLE001 -- l'audit ne doit jamais échouer pour cette section
        return {"erreur": str(e)}


def build_post_race_audit(result: RaceResult, arrival: List[ArrivalHorse],
                           confirmation: Optional[Dict[str, Any]] = None,
                           ticket: str = "A",
                           resultats_complets: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Audit d'UN ticket : "A" = protocole actuel, "B" = quotas par tranche (v1.29.42), "C" = ancré marché (v1.29.55).
    Chaque ticket est audité individuellement (captures, manqués, hors top 5)."""
    top5 = arrival[:5]
    top5_numeros = {h.numero for h in top5}
    ticket_list = (list(result.ticket) if ticket == "A" else
                   list(getattr(result, "ticket_ancre", None) or []) if ticket == "C" else
                   list(getattr(result, "ticket_quotas", None) or []))
    ticket_numeros = {t.numero: t for t in ticket_list}
    numeros_A = {t.numero for t in result.ticket}
    numeros_B = {t.numero for t in (getattr(result, "ticket_quotas", None) or [])}
    numeros_C = {t.numero for t in (getattr(result, "ticket_ancre", None) or [])}

    captures = [h for h in top5 if h.numero in ticket_numeros]
    manques = [h for h in top5 if h.numero not in ticket_numeros]
    ticket_hors_top5 = [t for t in ticket_list if t.numero not in top5_numeros]

    taux_capture = len(captures) / 5.0 if top5 else None

    manques_detail = []
    for h in manques:
        hs = _horse_by_numero(result.horses, h.numero)
        detail = {
            "rang_reel": h.rang, "numero": h.numero, "nom": h.nom,
            "cote_pre_course": hs.cheval.cote_matin if hs else None,
            "notre_tranche": hs.synthesis.tranche.value if hs and hs.synthesis.tranche else None,
            "notre_pch": round(hs.breakdown.pch_final, 1) if hs else None,
            "notre_ordre_final": round(hs.synthesis.ordre_final, 4) if hs else None,
            "signaux_sous_evalues": _diagnostic_modules(hs.breakdown, "sous_evalue") if hs else [],
            "flags": (hs.breakdown.flags[:5] if hs else []),
        }
        if not hs:
            detail["note"] = "Ce cheval n'était pas dans notre pool analysé (donnée pré-course absente ou hors partants collectés)."
        _rr = _resultat_reel(h.numero, resultats_complets)
        if _rr:
            detail["resultat_reel"] = _rr
        manques_detail.append(detail)

    # v1.29.17 -- profil marché des manques (favori vs outsider), pour
    # suivre si la série d'assouplissements récents (malus M, MPA, quota)
    # déplace les manques du top5 vers des favoris non détectés plutôt que
    # des outsiders mal notés. Mêmes seuils de tranche que le reste du
    # moteur (9 / 15 / 35).
    def _classe_marche(cote):
        if cote is None:
            return "COTE_INCONNUE"
        if cote < 9:
            return "T1_FAVORI"
        if cote < 15:
            return "T2_SEMI_FAVORI"
        if cote < 35:
            return "T3"
        return "T4_OUTSIDER"

    profil_manques = {"T1_FAVORI": 0, "T2_SEMI_FAVORI": 0, "T3": 0, "T4_OUTSIDER": 0, "COTE_INCONNUE": 0}
    for d in manques_detail:
        profil_manques[_classe_marche(d["cote_pre_course"])] += 1

    hors_top5_detail = []
    for t in ticket_hors_top5:
        hs = _horse_by_numero(result.horses, t.numero)
        hors_top5_detail.append({
            "position_ticket": t.position, "numero": t.numero, "nom": t.nom,
            "cote_pre_course": t.cote,
            "notre_ordre_final": t.ordre_final,
            "signaux_surevalues": _diagnostic_modules(hs.breakdown, "surevalue") if hs else [],
            "flags": (hs.breakdown.flags[:5] if hs else []),
            "resultat_reel": _resultat_reel(t.numero, resultats_complets),
            "cause_deterministe": _cause_deterministe(_resultat_reel(t.numero, resultats_complets)),
        })

    # --- v1.29.41 : baselines contrefactuelles + jeu de données de calibration ---
    # Sans point de comparaison, "3 captures sur 5" ne dit pas si le moteur ajoute quelque chose :
    # le marché seul (8 plus petites cotes) en fait ~3.2-3.5 sur un champ de 16-18.
    rang_reel = {h.numero: h.rang for h in top5}
    def _cote_ref(hs):
        c = hs.cheval.cote_avant_course or hs.cheval.cote_matin
        return float(c) if c else 999.0
    horses_all = list(result.horses or [])
    n_champ = len(horses_all)
    market8 = {hs.cheval.numero for hs in sorted(horses_all, key=_cote_ref)[:8]}
    ordre8 = {hs.cheval.numero for hs in sorted(horses_all, key=lambda x: -(x.synthesis.ordre_final or 0.0))[:8]}
    baselines = {
        "ticket": len(captures),
        "marche_top8": len(top5_numeros & market8),
        "ordre_final_top8": len(top5_numeros & ordre8),
        "hasard_attendu": round(8 * 5 / n_champ, 2) if n_champ else None,
        "ticket_A_protocole": len(top5_numeros & numeros_A),
        "ticket_B_quotas": (len(top5_numeros & numeros_B) if numeros_B else None),
        "ticket_C_ancre": (len(top5_numeros & numeros_C) if numeros_C else None),
        "ticket_moins_marche": len(captures) - len(top5_numeros & market8),
        "ticket_moins_ordre": len(captures) - len(top5_numeros & ordre8),
        "note": "Agréger sur >=30 courses : si ticket_moins_marche reste <= 0, le moteur ne bat pas le marché brut.",
    }
    try:      # v1.29.68 : captures des sélections alternatives (shadow) — comparaison appariée aux tickets réels
        _sh68 = ((getattr(result, "json_output", None) or {}).get("shadow_v1_29_68") or {})
        baselines["shadow_captures"] = {t_: (len(top5_numeros & set(v_["min1_melange"])) if v_.get("min1_melange") else None) for t_, v_ in _sh68.items()}
        baselines["shadow_captures_plafond2"] = {t_: (len(top5_numeros & set(v_["plafond2"])) if v_.get("plafond2") else None) for t_, v_ in _sh68.items()}
    except Exception:  # noqa: BLE001
        baselines["shadow_captures"] = {}
    try:      # v1.29.69 : résultat des bases « score propre » (k=2 et k=3), de la garde T1 et du filtre de courses
        _s69 = ((getattr(result, "json_output", None) or {}).get("shadow_v1_29_69") or {})
        _res69: dict = {}
        for _t, _v in (_s69.get("tickets") or {}).items():
            _nums = set(_v.get("selection") or [])
            _d = {}
            for _k in (2, 3):
                _b = set((_v.get(f"bases_k{_k}") or [])[:_k])
                _d[f"k{_k}"] = {"bases_dans_top5": len(_b & top5_numeros), "desordre": bool(_nums and top5_numeros <= _nums and _b <= top5_numeros)}
            _g = _v.get("garde_t1")
            _d["captures_garde_t1"] = (len(top5_numeros & set(_g)) if _g else None)
            _res69[_t] = _d
        baselines["shadow_v69"] = {"tickets": _res69, "signal_course": _s69.get("signal_course")}
    except Exception:  # noqa: BLE001
        baselines["shadow_v69"] = {}
    bilan_ticket = None
    if resultats_complets:
        rangs = {t.numero: (resultats_complets.get(t.numero) or {}).get("rang") for t in ticket_list}
        valides = [r for r in rangs.values() if isinstance(r, int)]
        causes = [d["cause_deterministe"] for d in hors_top5_detail]
        bilan_ticket = {
            "rangs_reels_du_ticket": rangs,
            "rang_moyen_reel": round(sum(valides) / len(valides), 2) if valides else None,
            "nb_incidents_course": causes.count("INCIDENT_COURSE"),
            "nb_proches_6e_8e": causes.count("PROCHE_DU_TOP5"),
            "nb_hors_place": causes.count("HORS_PLACE"),
            "lecture": ("Les chevaux du ticket hors Top 5 qui ont eu un INCIDENT DE COURSE (tombé, arrêté, disqualifié) "
                        "ne sont pas des erreurs d'évaluation ; les 6e-8e étaient proches ; les 9e et + sont les vraies erreurs."),
        }
    dataset_calibration = [
        {
            "rang_complet": (resultats_complets or {}).get(hs.cheval.numero, {}).get("rang") if resultats_complets else None,
            "incident": (resultats_complets or {}).get(hs.cheval.numero, {}).get("incident") if resultats_complets else None,
            "numero": hs.cheval.numero,
            "cote_matin": hs.cheval.cote_matin, "cote_avant_course": hs.cheval.cote_avant_course,
            "tranche": hs.synthesis.tranche.value if hs.synthesis and hs.synthesis.tranche else None,
            "ordre_final": round(hs.synthesis.ordre_final or 0.0, 5),
            "composite": round(hs.synthesis.composite or 0.0, 5),
            "pch_final": round(hs.breakdown.pch_final, 2) if hs.breakdown else None,
            "tocard_score": round(hs.breakdown.tocard_score or 0.0, 4) if hs.breakdown else None,
            "dans_ticket": hs.cheval.numero in ticket_numeros,
            "musique": hs.cheval.musique, "age": hs.cheval.age, "sexe": hs.cheval.sexe,
            "dans_ticket_A": hs.cheval.numero in numeros_A,
            "dans_ticket_B": hs.cheval.numero in numeros_B,
            "dans_ticket_C": hs.cheval.numero in numeros_C,
            "top5": hs.cheval.numero in top5_numeros,
            "rang_reel": rang_reel.get(hs.cheval.numero),
        }
        for hs in horses_all
    ]

    out = {
        "resultats_complets_disponibles": bool(resultats_complets),
        "bilan_ticket": bilan_ticket,
        "ticket_audite": ticket,
        # v1.29.58 : champ réduit 3 bases + 5 compléments -> désordre / bonus / ordre (règle de paiement du pays de Golden)
        "structure_bases_complements": _structure_audit(result, ticket, arrival),
        "libelle_ticket": ("Ticket A — protocole actuel" if ticket == "A" else
                           "Ticket C — ancré marché (mélange marché + PCH)" if ticket == "C" else "Ticket B — quotas par tranche"),
        "baselines_contrefactuelles": baselines,
        "dataset_calibration": dataset_calibration,
        "contexte_dataset": {
            "partants": n_champ, "discipline": result.context.discipline.value,
            "mode_execution": (result.json_output or {}).get("mode_execution", "INCONNU"),
            "date_course": result.context.date_course, "hippodrome": result.context.hippodrome,
        },
        "sources_collecte_et_enrichissement": (
            (result.json_output or {}).get("sources_liens")
            or getattr(result, "sources_liens", None)
            or {}
        ),
        "confirmation_sources": confirmation or {
            "statut": "NON_VERIFIE",
            "note": "build_post_race_audit appelé sans passer confirmation (usage direct hors API) -- "
                    "utiliser confirm_arrival() en amont pour une vraie vérification à 2 sources.",
        },
        "recap_technique": {
            "hippodrome": result.context.hippodrome, "discipline": result.context.discipline.value,
            "distance_m": result.context.distance_m, "type_course": result.context.type_course.value,
            "depart": result.context.depart.value, "allocation_eur": result.context.allocation_eur,
            "partants": result.context.partants_confirmes, "penetrometre": result.context.penetrometre,
            "signature_estimee": result.context.signature.value if result.context.signature else None,
            "iic_v2": getattr(result.context, "iic_v2", None),                      # v1.29.57
            "iic_marche": getattr(result.context, "iic_market", None),
            "grille_B_cible": (result.quotas_info or {}).get("target_grid"),
            "grille_B_appliquee": (result.quotas_info or {}).get("applied_grid"),
        },
        "arrivee_officielle_top5": [{"rang": h.rang, "numero": h.numero, "nom": h.nom} for h in top5],
        "cotes_top5_reel": [
            {"numero": h.numero, "nom": h.nom,
             "cote_pre_course": (hs.cheval.cote_matin if (hs := _horse_by_numero(result.horses, h.numero)) else None)}
            for h in top5
        ],
        "taux_capture_desordre": taux_capture,
        "nb_captures": len(captures),
        "chevaux_captures": [{"numero": h.numero, "nom": h.nom, "rang_reel": h.rang} for h in captures],
        "chevaux_manques": manques_detail,
        "profil_manques_marche": {
            **profil_manques,
            "note": (
                "v1.29.17 -- suivi de la tendance : les assouplissements récents "
                "(malus M, MPA, quota) visent tous à moins pénaliser les favoris/"
                "semi-favoris. Si T1_FAVORI/T2_SEMI_FAVORI grimpe sur plusieurs "
                "courses, la tendance est probablement allée trop loin."
            ),
        },
        "ticket_hors_top5": hors_top5_detail,
        "impact_supra_note": (
            "SUPRA n'est, dans ce moteur 100% Python, qu'une heuristique approximative "
            "(supra_score_sim) -- pas les 7 phases complètes du protocole. Son impact réel "
            "ne peut être évalué avec la même rigueur qu'une exécution avec lecture de texte. "
            "Valeurs indicatives seulement."
        ),
        "analyse_presse_post_course": {
            "disponible": False,
            "raison": (
                "Distinct de la collecte ICP pré-course (Frequence-Turf/Bloc K, faite normalement "
                "pendant l'analyse -- voir le rapport d'exécution, étape 3) : ceci concerne une "
                "recherche de COMPTES-RENDUS ET ANALYSES DE PRESSE APRÈS la course (ex. \"le driver "
                "a expliqué que...\"), qui nécessiterait une recherche web + lecture de texte libre -- "
                "non disponible en mode 100% Python sans API. Cette section est laissée vide plutôt "
                "que fabriquée. Voir README, section Audit post-course."
            ),
        },
    }
    # v1.29.13 — supervision IA post-course (optionnelle, free-tier)
    try:
        from app.llm.supervisor import enrich_post_race_audit
        out["supervision_ia"] = enrich_post_race_audit(out)
    except Exception as _e:
        out["supervision_ia"] = {"status": "ERROR", "error": str(_e)[:200]}
    return out


# ===== post_audit_hooks.py (fusionné en v1.29.42) =====
# post_audit_hooks.py -- v1.29.15. Point d'ancrage UNIQUE appelé après
# confirmation d'un audit post-course (arrivée réelle connue), que ce
# soit via l'audit automatique (orchestrator.py, auto_audit=True) ou
# l'audit manuel (main.py, POST /api/races/{race_id}/audit). Évite de
# dupliquer la logique d'apprentissage continu et de sync Hugging Face
# dans deux endroits.
# 
# Chaque étape est indépendamment protégée (try/except) : un échec de
# l'apprentissage continu n'empêche jamais la sync HF de s'exécuter, et
# réciproquement -- aucune des deux ne doit jamais faire échouer l'audit
# lui-même, qui reste la donnée de référence (déjà persistée en base
# avant l'appel à cette fonction).

import logging
from typing import Any, Dict, List

from app.models import RaceResult

_hooks_logger = logging.getLogger("vantage.post_audit_hooks")


def on_audit_confirmed(race_id: str, result: RaceResult, arrival: List[Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}

    try:
        from app.ml.continuous_learning import record_race_outcome, maybe_retrain
        rec = record_race_outcome(race_id, result, arrival)
        summary["apprentissage_continu"] = rec
        if rec.get("status") == "OK":
            summary["reentrainement"] = maybe_retrain()
    except Exception as e:
        _hooks_logger.warning("post_audit_hooks: apprentissage continu en échec pour %s: %s", race_id, e)
        summary["apprentissage_continu"] = {"status": "ERROR", "error": str(e)}

    try:
        from app import db
        from app.integrations.hf_export import sync_race_to_hf
        r = db.get_race(race_id)
        if r:
            summary["hf_export"] = sync_race_to_hf(race_id, r)
    except Exception as e:
        _hooks_logger.warning("post_audit_hooks: sync Hugging Face en échec pour %s: %s", race_id, e)
        summary["hf_export"] = {"status": "ERROR", "error": str(e)}

    return summary



# ===== Audit post-course COMPLET, point d'entrée unique (v1.29.53) =====
class _NoAI:
    """Client factice : sans clé IA, seules les causes déterministes (incidents officiels) sont posées."""
    last_provider = None

    def run_json(self, *a, **k):
        raise RuntimeError("aucune clé IA configurée")


def run_full_audit(race_id: str, result: RaceResult, urls: List[str]) -> Dict[str, Any]:
    """Arrivée confirmée (2 sources) -> résultat complet PMU -> audit ticket A + ticket B -> comparaison ->
    analyse IA post-course -> sauvegarde -> hooks. Utilisé par le bouton « Audit post-course » ET par l'audit
    automatique du mode walk-forward (avant : ce dernier restait à l'ancienne version, sans ticket B ni résultats
    complets ni analyse IA). Lève ValueError si l'arrivée n'est pas disponible / confirmée."""
    from app import db, config as _cfg
    arrival, confirmation = confirm_arrival(result, urls or [])

    resultats_complets = None
    try:
        from app.scraping.pmu_api import extraire_reunion_course, fetch_full_results_pmu
        _rc = extraire_reunion_course(result.context)
        if _rc and result.context.date_course:
            resultats_complets = fetch_full_results_pmu(str(result.context.date_course)[:10], _rc[0], _rc[1]) or None
    except Exception as e:  # noqa: BLE001  (jamais bloquant : l'audit de base reste valable)
        logger.info("Résultat complet PMU indisponible : %s", e)

    audit = build_post_race_audit(result, arrival, confirmation, ticket="A", resultats_complets=resultats_complets)
    if getattr(result, "ticket_quotas", None):
        try:
            audit["audit_ticket_B"] = build_post_race_audit(result, arrival, confirmation, ticket="B",
                                                            resultats_complets=resultats_complets)
        except Exception as e:  # noqa: BLE001
            audit["audit_ticket_B"] = {"erreur": str(e)}
    if getattr(result, "ticket_ancre", None):
        try:
            audit["audit_ticket_C"] = build_post_race_audit(result, arrival, confirmation, ticket="C",
                                                            resultats_complets=resultats_complets)
        except Exception as e:  # noqa: BLE001
            audit["audit_ticket_C"] = {"erreur": str(e)}
    audit["comparaison_tickets"] = {"A_captures": audit.get("nb_captures"),
                                    "B_captures": (audit.get("audit_ticket_B") or {}).get("nb_captures"),
                                    "C_captures": (audit.get("audit_ticket_C") or {}).get("nb_captures")}
    try:
        from app.llm.client import ai_available
        if _cfg.AI_POSTRACE != "0":
            from app.llm.tasks import analyze_post_race, appliquer_analyse_post_course
            from app.scraping.turfoo_resultats import resultats_url_from_pronostics_url
            urls_post = list(urls or [])
            for u in list(urls_post):
                if "turfoo.fr" in u:
                    try:
                        urls_post.append(resultats_url_from_pronostics_url(u))
                    except Exception:  # noqa: BLE001
                        pass
            ok = ai_available()
            analyse = analyze_post_race(audit, resultats_complets, urls_post if ok else [], client=None if ok else _NoAI())
            appliquer_analyse_post_course(audit, analyse)
    except Exception as e:  # noqa: BLE001
        audit["analyse_presse_post_course"] = {"disponible": False, "raison": f"analyse indisponible : {str(e)[:160]}"}
    db.save_audit(race_id, audit)
    audit["_post_audit_hooks"] = on_audit_confirmed(race_id, result, arrival)      # informatif, jamais bloquant
    return audit
