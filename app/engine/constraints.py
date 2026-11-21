"""constraints.py -- Bloc 9 CONTRAINTES DURES (checklist RAH) + Bloc 6
GOUVERNANCE (ajouté le 05/08/2026, absent du moteur jusque-là)."""
from __future__ import annotations
from typing import List, Dict
from app.models import HorseScore, RaceContext, Tranche, Signature
from app.engine.gamma_signals import GAMMA_CAP


def check_gouvernance(horses: List[HorseScore]) -> List[Dict]:
    """Bloc 6 -- RAH175/176/191/195. Contrairement au Bloc 9 (contraintes
    sur le TICKET sélectionné), la gouvernance porte sur le CHAMP ENTIER
    (tous les partants, pas seulement les 8 retenus)."""
    report = []

    # RAH-175/176 -- GAMMA activé à poids réel (pas placeholder) ET cap +8
    # respecté. Le cap est structurellement garanti par gamma_signals.py
    # (clamp avant retour, pas une vérification a posteriori) -- donc
    # vérifiable ici en relisant simplement la valeur finale, sans
    # dupliquer la logique de calcul.
    depassements = [h.cheval.numero for h in horses if h.breakdown and h.breakdown.gamma_pch > GAMMA_CAP + 1e-6]
    report.append({
        "rule": "RAH-175/176", "label": "GAMMA à poids réel, cap +8 PCH respecté",
        "status": "FAIL" if depassements else "PASS",
        "detail": (f"Dépassements détectés (ne devrait jamais arriver, cap déjà appliqué "
                   f"dans gamma_signals.py) : {depassements}" if depassements
                   else f"Aucun dépassement sur {len(horses)} chevaux (cap={GAMMA_CAP} appliqué en amont)."),
    })

    # RAH-191/195 -- portent sur le PROCESSUS DE CALIBRATION du protocole
    # entre versions (rétrogradation de signal non documentée, correction
    # de paramètre >0,2pp sans RCA) -- pas sur l'exécution d'une course
    # individuelle. Marqué explicitement non applicable plutôt que simulé.
    for rule, label in [("RAH-191", "Aucune rétrogradation de signal ignorée"),
                         ("RAH-195", "Correction de paramètre <=0,2pp sans RCA documentée")]:
        report.append({
            "rule": rule, "label": label, "status": "NON_APPLICABLE",
            "detail": "Concerne le processus de calibration du protocole ENTRE versions "
                      "(revue humaine des changements de paramètres), pas l'exécution d'une "
                      "course individuelle -- rien à vérifier ici par construction.",
        })
    return report


def check_hard_constraints(
    race: RaceContext,
    horses: List[HorseScore],
    selection: List[int],
    roles_report=None,  # Optional[dict] roles soft report from GMO
) -> List[Dict]:
    report = []
    sel = [horses[i] for i in selection]

    # RAH-90 -- plafond ICP>=6 : max 2, ou max 3 si TOUS sont dans le top-3 cotes
    def _cote_h(h):
        c = h.cheval.cote_avant_course if h.cheval.cote_avant_course is not None else h.cheval.cote_matin
        return float(c) if c is not None and c > 0 else 999.0
    ranked_mkt = sorted(horses, key=_cote_h)
    top3_nums_mkt = {h.cheval.numero for h in ranked_mkt[:3]}
    favs_icp = [h for h in sel if (h.cheval.icp_global or 0) >= 6]
    nb_favoris_icp = len(favs_icp)
    all_in_top_mkt = nb_favoris_icp > 0 and all(h.cheval.numero in top3_nums_mkt for h in favs_icp)
    if nb_favoris_icp <= 2:
        st90, d90 = "PASS", f"{nb_favoris_icp} favori(s) ICP>=6 dans les 8 (plafond 2)"
    elif nb_favoris_icp <= 3 and all_in_top_mkt:
        st90, d90 = "PASS", (
            f"{nb_favoris_icp} favori(s) ICP>=6 TOUS top-3 marché — "
            f"plafond assoupli à 3 (hiérarchie noyau/marché > RAH-90)"
        )
    else:
        st90, d90 = "WARN", (
            f"{nb_favoris_icp} favori(s) ICP>=6 dans les 8 — "
            f"plafond 2 non tenable sans casser le noyau protégé (voir CORE_PROTECT)"
        )
    report.append({"rule": "RAH-90", "label": "Plafond favoris (ICP>=6, max 2 sur 8, ≤3 si top-marché)",
                    "status": st90, "detail": d90})

    # RAH-07/168 -- diversité stylistique : SUPPRIMÉE (21/09/2026)
    # Remplacée par couverture favoris de marché (cotes les plus courtes).
    report.append({
        "rule": "RAH-07/168",
        "label": "Diversité stylistique",
        "status": "NON_APPLICABLE",
        "detail": "Levier retiré 21/09/2026 — remplacé par couverture favoris marché "
                  "(≥2 des 3 cotes les plus courtes dans le ticket 8).",
    })

    # NOUVEAU — Couverture favoris de marché (cote)
    def _cote(h):
        c = h.cheval.cote_avant_course if h.cheval.cote_avant_course is not None else h.cheval.cote_matin
        return float(c) if c is not None and c > 0 else 999.0

    ranked = sorted(horses, key=_cote)
    top3_market = ranked[:3]
    top3_nums = {h.cheval.numero for h in top3_market}
    sel_nums = {h.cheval.numero for h in sel}
    n_market_in = len(top3_nums & sel_nums)
    market_detail = (
        f"top3_cotes=["
        + ", ".join(f"#{h.cheval.numero}@{_cote(h):.1f}" for h in top3_market)
        + f"] dans_ticket={n_market_in}/3 (cible ≥2)"
    )
    report.append({
        "rule": "RAH-MARCHE-01",
        "label": "Couverture favoris marché (≥2/3 cotes courtes, souple)",
        # v1.29.19 (port Grok, Golden 22/09) : WARN non bloquant, pas FAIL --
        # "éviter d'être guidé principalement par le marché". Le mécanisme
        # actif dans gmo_v.py ne force plus que ≥1/3 ; ce ≥2/3 reste un
        # repère de transparence, jamais prioritaire sur le noyau interne.
        "status": "PASS" if n_market_in >= 2 else "WARN",
        "detail": market_detail + ("" if n_market_in >= 2 else " -- non bloquant (hiérarchie interne > marché)"),
    })

    # RAH-178/259 -- quotas T1-T4
    # v1.29.18 (22/09/2026, Golden) : quota assoupli -- T1+T2 ET T3+T4
    # chacun dans [3,5] (au lieu du 4+4 rigide du 20/09). L'ancien palier
    # WARN "3+5 toléré" devient la cible normale (PASS), pas un repli.
    tranches: Dict[str, int] = {}
    for h in sel:
        t = h.synthesis.tranche.value if h.synthesis.tranche else "HORS_TRANCHE"
        tranches[t] = tranches.get(t, 0) + 1
    n_t12 = tranches.get("T1", 0) + tranches.get("T2", 0)
    n_t34 = tranches.get("T3", 0) + tranches.get("T4a", 0) + tranches.get("T4b", 0)
    # Fallback cote / ordre_final si tranche absente (anti HORS_TRANCHE)
    for h in sel:
        if h.synthesis.tranche is None:
            c = h.cheval.cote_avant_course if h.cheval.cote_avant_course is not None else h.cheval.cote_matin
            if c is not None and c > 0:
                if c < 15:
                    n_t12 += 1
                else:
                    n_t34 += 1
            else:
                # dernier recours : hors-cote → compter en T3/T4 (outsider)
                n_t34 += 1
    quota_ok = 3 <= n_t12 <= 5 and 3 <= n_t34 <= 5
    detail = f"répartition={tranches} → T1/T2={n_t12} T3/T4={n_t34} (cible [3,5]/[3,5], ticket=8)"
    if quota_ok:
        st_q = "PASS"
        detail += " | sous-mix libre (qualité intra-tranche)"
    else:
        # WARN si 2+6 ou 6+2 (hors plage stricte)
        if (n_t12 >= 2 and n_t34 >= 2):
            st_q = "WARN"
            detail += " -- QUOTA_HORS_PLAGE (cible stricte [3,5]/[3,5] sur ticket 8)"
        else:
            st_q = "FAIL"
            detail += " -- QUOTA_PLAGE_35_NON_RESPECTEE"
    report.append({"rule": "RAH-178/259", "label": "Quotas T1-T4 (plage [3,5]/[3,5])",
                    "status": st_q,
                    "detail": detail})

    # Mix interne T1/T2/T3/T4 (01/10/2026) — INFO / WARN, non FAIL
    n_t1 = tranches.get("T1", 0)
    n_t2 = tranches.get("T2", 0)
    n_t3 = tranches.get("T3", 0)
    n_t4 = tranches.get("T4a", 0) + tranches.get("T4b", 0)
    from app.engine.gmo_v import discipline_internal_mix
    try:
        _mix = discipline_internal_mix(race.discipline if race is not None else None)
    except Exception:
        _mix = {"t1_max": 3, "t2_min": 1, "t4_min": 1}
    mix_warns = []
    if n_t1 > _mix.get("t1_max", 3):
        mix_warns.append(f"T1={n_t1}>{_mix.get('t1_max')}")
    if n_t2 < _mix.get("t2_min", 1):
        mix_warns.append(f"T2={n_t2}<{_mix.get('t2_min')}")
    if n_t4 < _mix.get("t4_min", 1):
        mix_warns.append(f"T4={n_t4}<{_mix.get('t4_min')}")
    report.append({
        "rule": "RAH-MIX-INTERNE",
        "label": "Mix interne T1/T2/T3/T4",
        "status": "WARN" if mix_warns else "PASS",
        "detail": f"T1={n_t1} T2={n_t2} T3={n_t3} T4={n_t4} targets={_mix}"
                  + ((" | " + ",".join(mix_warns)) if mix_warns else ""),
    })


    # v1.29.29 — rôles abandonnés
    report.append({
        "rule": "RAH-ROLES-01",
        "label": "Rôles ticket (abandonnés)",
        "status": "NON_APPLICABLE",
        "detail": "PIVOT/SEMI/VALUE/SAUVAGE désactivés — sélection = p_boost + quotas [3,5]/[3,5]",
    })

    # RAH-266 -- éligibilité T3/T4 (v1.29.19, étendu port Grok) : tocard OU
    # forme régulière/forte OU signaux actifs. Golden (22/09) a demandé
    # explicitement "les T3/T4" -- étendu au-delà du seul T4 (v1.29.17-18).
    # L'enforcement réel est fait AU MOMENT DE LA SÉLECTION (gmo_v.py,
    # _tocard_ok + gate final section 5) -- ce FAIL ne devrait donc quasi
    # plus jamais se déclencher en pratique, sauf pool T3/T4 éligible trop
    # petit (log RAH266_TICKET_ECHEC_* dans ce cas, honnête plutôt que
    # silencieux).
    TOCARD_MIN_T3 = 0.22
    TOCARD_MIN_T4 = 0.25
    try:
        from app.engine.musique_features import profil_forme_recente
    except ImportError:
        def profil_forme_recente(m):  # type: ignore
            return "MORTE"
    t34_sous_seuil = []
    for h in sel:
        t = h.synthesis.tranche
        ts = h.breakdown.tocard_score if h.breakdown else 0.0
        has_signaux = bool(h.breakdown and h.breakdown.signaux_actifs)
        try:
            from app.engine.musique_features import profil_forme_recente_disc
            forme_ok = profil_forme_recente_disc(
                getattr(h.cheval, "musique", None), getattr(race, "discipline", None)
            ) in ("FORTE", "REGULIERE")
        except Exception:
            forme_ok = profil_forme_recente(getattr(h.cheval, "musique", None)) in ("FORTE", "REGULIERE")
        if t == Tranche.T3:
            if ts < TOCARD_MIN_T3 and not has_signaux and not forme_ok:
                t34_sous_seuil.append(h.cheval.numero)
        elif t in (Tranche.T4A, Tranche.T4B):
            if ts < TOCARD_MIN_T4 and not has_signaux and not forme_ok:
                t34_sous_seuil.append(h.cheval.numero)
    report.append({
        "rule": "RAH-266",
        "label": "Éligibilité T3/T4 (tocard | forme régulière | signaux)",
        "status": "FAIL" if t34_sous_seuil else "PASS",
        "detail": (
            f"chevaux T3/T4 sans tocard/forme/signaux: {t34_sous_seuil}"
            if t34_sous_seuil else "OK"
        ),
    })

    # RAH-FORME-T1 (v1.29.19, port Grok) -- INFO non bloquant : un T1 du
    # ticket dont la forme récente est "MORTE" (0 Top5/Top8 sur 3 courses)
    # est un vrai favori de cote mais une évaluation interne peu
    # engageante -- exactement le profil que Golden (22/09) veut voir
    # surveillé plutôt que verrouillé aveuglément.
    t1_forme_morte = [
        h.cheval.numero for h in sel
        if h.synthesis.tranche == Tranche.T1
        and profil_forme_recente(getattr(h.cheval, "musique", None)) == "MORTE"
    ]
    report.append({
        "rule": "RAH-FORME-T1",
        "label": "T1 forme morte (INFO, non bloquant)",
        "status": "INFO" if t1_forme_morte else "PASS",
        "detail": (
            f"T1 avec musique morte dans le ticket: {t1_forme_morte}"
            if t1_forme_morte else "Aucun T1 forme morte"
        ),
    })

    # RAH-267 -- FAVORI_UNANIME, cote>20/1 obligatoire, VALEUR_MORTE
    favori_unanime_hors_ticket = any(
        h.cheval.favori_unanime and h.cheval.numero not in [s.cheval.numero for s in sel]
        for h in horses)
    cote_elevee_present = any((h.cheval.cote_matin or 0) > 20 for h in sel)
    valeur_morte_present = any(
        (h.cheval.cote_matin or 0) > 25 and not h.breakdown.signaux_actifs and h.breakdown.tocard_score < 0.20
        for h in sel)
    n_out15 = sum(
        1 for h in sel
        if (h.cheval.cote_avant_course or h.cheval.cote_matin or 0) >= 15
    )
    detail_267 = (
        f"favori_unanime_absent={favori_unanime_hors_ticket}, "
        f"nb_cote>=15={n_out15}, >20/1={cote_elevee_present}, "
        f"VALEUR_MORTE={valeur_morte_present}"
    )
    st267 = "FAIL" if favori_unanime_hors_ticket else "PASS"
    report.append({
        "rule": "RAH-267",
        "label": "FAVORI_UNANIME (bloquant) / couverture outsiders (info)",
        "status": st267,
        "detail": detail_267,
    })

    # RAH-302/303/304 -- bornes documentées des postes patch (sanity check)
    hors_bornes = [h.cheval.numero for h in sel if abs(h.breakdown.forme_lineaire_pch) > 20]
    report.append({"rule": "RAH-303", "label": "FORME_LINEAIRE (cap +/-20)",
                    "status": "FAIL" if hors_bornes else "PASS",
                    "detail": f"hors bornes: {hors_bornes}" if hors_bornes else "OK"})
    report.append({"rule": "RAH-302", "label": "D46-D22", "status": "NON_APPLICABLE",
                    "detail": "D46-D22 n'est pas implémenté dans le moteur 100% Python actuel "
                              "(toujours à 0, flag D46_D22_NON_EVALUE) -- il n'y a rien à valider. "
                              "Corrigé le 05/08/2026 : l'ancien statut 'PASS (Couche LLM)' était un "
                              "reliquat de l'architecture pré-pivot Python, la Couche LLM ne tournant "
                              "plus dans cette version, ce statut était devenu trompeur."})
    report.append({"rule": "RAH-304", "label": "M48-B42", "status": "NON_APPLICABLE",
                    "detail": "M48-B42 n'est pas implémenté dans le moteur 100% Python actuel "
                              "(toujours à 0, flag M48_B42_NON_EVALUE) -- il n'y a rien à valider. "
                              "Même correctif que RAH-302 (05/08/2026)."})

    # RAH-308 -- atténuation malus T3/T4 (RAH-310 dans master.md) : vérifie la présence du flag
    # sur au moins un cheval T3/T4 avec malus actif, si applicable
    report.append({"rule": "RAH-308", "label": "Atténuation malus outsiders T3/T4",
                    "status": "INFO",
                    "detail": "Mécanisme dans engine/tranches.py (outsider_penalty_mult) — "
                              "non re-vérifié cheval par cheval dans cette checklist"})

    # RAH-309 -- repli SOV_v2 documenté
    sov_repli = [h.cheval.numero for h in sel if "SOV_V2_REPLI" in h.synthesis.flags]
    report.append({"rule": "RAH-309", "label": "SOV_v2 repli documenté", "status": "PASS",
                    "detail": f"chevaux en repli: {sov_repli}" if sov_repli else "Aucun repli nécessaire"})

    # RAH-212 -- neutralisation presse (drift neutralisé si incident concurrent documenté)
    report.append({"rule": "RAH-212", "label": "Neutralisation presse / drift",
                    "status": "INFO",
                    "detail": "Mécanisme Module O (OVERBET) — flags DRIFT_NEUTRE_* si applicable"})

    return report
