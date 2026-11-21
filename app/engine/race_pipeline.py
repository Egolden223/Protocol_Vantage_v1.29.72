"""
race_pipeline.py -- Orchestration Étapes 4 à 9 pour l'ensemble du champ.

Séquence (résolution pragmatique de l'anti-circularité SOV/Harville/OVERBET,
cf. commentaires en tête de fonction) :
  1. PCH_FINAL pass 1 (sans OVERBET) pour chaque cheval -- pch_final.py
  2. COMPOSITE v1 (Module Q)
  3. ORDRE_SCORE_initial = COMPOSITE_v1 x PRODUIT_MULT_v1 (Harville_mult=1.0)
  4. OVERBET (Module O) sur la base d'ORDRE_SCORE_initial -> ajuste PCH/tocard
  5. COMPOSITE v2 (avec PCH/tocard ajustés)
  6. Classement provisoire (par ORDRE_SCORE_initial) -> position_attendue
  7. harville_fiable_course (niveau course) + Harville_mult (niveau cheval)
  8. PRODUIT_MULT_v2 (avec Harville_mult) -> ORDRE_BASE final -> ORDRE_FINAL
  9. IFT par cheval
"""
from __future__ import annotations
from typing import List
from statistics import mean

from app.models import (Cheval, RaceContext, HorseScore, ModuleBreakdown, SynthesisResult,
                         QualitativeSignals, Signature, Discipline, Tranche)
from app.engine.discipline_detect import ensure_race_discipline
from app.engine.pch_final import (compute_module_breakdown, apply_overbet_second_pass,
                                  apply_rah163_ferrure_sov_guard, apply_t2_value_scores)
from app.engine.p5p6 import compute_p5p6_score
from app.engine.supra import compute_supra_synthese
from app.engine import synthesis as S
from app.engine.tranches import classify_tranche
from app.engine.common import clamp, disc_bucket, derive_style_mpa
from app.engine import modules_ap as M


def _derive_activite(chevaux, race) -> None:
    from datetime import date as _d
    from statistics import median
    try:
        ref = _d.fromisoformat(str(race.date_course)[:10])
    except (TypeError, ValueError):
        ref = None
    for c in chevaux:
        hist = c.historique_recent or []
        if ref is not None and hist and (c.nb_courses_30j is None or c.nb_courses_12m in (None, 0)):
            dates = []
            for h in hist:
                try:
                    d = _d.fromisoformat(str(h.date)[:10])
                except (TypeError, ValueError):
                    continue
                if d < ref:
                    dates.append(d)
            if dates:
                if c.nb_courses_30j is None:
                    c.nb_courses_30j = sum(1 for d in dates if (ref - d).days <= 30)
                oldest = min(dates)
                # 12 mois : valable seulement si l'historique remonte assez loin (sinon sous-estimé)
                if not c.nb_courses_12m and (ref - oldest).days >= 365:
                    c.nb_courses_12m = sum(1 for d in dates if (ref - d).days <= 365)
        if c.distance_habituelle_m is None and c.historique_distance:
            vals = [h.valeur for h in c.historique_distance if h.valeur and 800 <= h.valeur <= 8000]
            if len(vals) >= 3:
                c.distance_habituelle_m = int(median(vals))


def _market_implied_probs(chevaux: List[Cheval]) -> List[float]:
    """Probabilités implicites normalisées (1/cote), overround retiré.
    Cotes matin prioritaires ; repli cote_avant_course. Retourne [] si <2 cotes.
    """
    raw: List[float] = []
    for c in chevaux:
        cote = c.cote_matin if c.cote_matin and c.cote_matin > 1.01 else None
        if cote is None and c.cote_avant_course and c.cote_avant_course > 1.01:
            cote = c.cote_avant_course
        if cote is not None:
            raw.append(1.0 / float(cote))
    if len(raw) < 2:
        return []
    s = sum(raw)
    if s <= 0:
        return []
    return [p / s for p in raw]


def _context_openness(race: RaceContext) -> dict:
    """Prior de contexte 0–1 (plus haut = plus ouvert) pour IIC-v2.

    δ_disc / δ_dist / δ_hippo calibrés sur stats Quinté+ (MediaPronos,
    Turf BZH D5, Hippigold 2025-2026) et corpus Vantage 54 courses.
    """
    disc = race.discipline
    dist = int(race.distance_m or 0)
    hippo = (race.hippodrome or "").strip().upper()
    hippo_norm = (
        hippo.replace("É", "E").replace("È", "E").replace("-", " ").replace("'", " ")
    )

    # Base 0.5 + deltas bornés
    delta = 0.0
    # Discipline
    if disc in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE):
        delta -= 0.06
    elif disc == Discipline.PLAT:
        delta += 0.04
    elif disc == Discipline.STEEPLE:
        delta += 0.03
    elif disc == Discipline.HAIES:
        delta += 0.00
    # Distance
    if disc == Discipline.PLAT and dist and dist <= 1400:
        delta += 0.03
    if disc in (Discipline.HAIES, Discipline.STEEPLE) and dist and dist >= 3600:
        delta += 0.04
    if disc in (Discipline.TROT_ATTELE, Discipline.TROT_MONTE) and dist and dist >= 2850:
        delta -= 0.02
    # Hippodromes (ouverture relative)
    if any(h in hippo_norm for h in ("CHANTILLY", "SAINT CLOUD", "DEAUVILLE", "LONGCHAMP")):
        delta += 0.03
    if "VINCENNES" in hippo_norm:
        delta -= 0.04
    if "AUTEUIL" in hippo_norm:
        delta += 0.02

    ctx = max(0.0, min(1.0, 0.50 + delta))
    return {"context_open": round(ctx, 3), "delta_context": round(delta, 3)}


def compute_race_market_metrics(chevaux: List[Cheval], race: RaceContext | None = None) -> dict:
    """Métriques marché + IIC-v2 hybride (sans meneurs).

    IIC-v2 = 70 % marché + 30 % contexte (discipline / distance / hippo).

    Marché (pondérations) :
      - HHI sur proba implicites 30 %
      - Part du favori             25 %
      - Densité cotes 6–15         20 %
      - Écart fav–2e               15 %
      - Taille de champ            10 %

    Réf. : HHI racing, Racing Post competitiveness, Turf BZH D5,
    MediaPronos Quinté+, corpus Vantage (structure top5 + corrélations).
    """
    cotes = sorted(
        [
            float(c.cote_matin if c.cote_matin and c.cote_matin > 1.01
                  else (c.cote_avant_course if c.cote_avant_course and c.cote_avant_course > 1.01
                        else 0))
            for c in chevaux
        ]
    )
    cotes = [x for x in cotes if x > 1.01]
    probs = _market_implied_probs(chevaux)
    n = len(cotes)
    if n < 2 or not probs:
        return {
            "hhi": None, "fav_share": None, "ecart_fav": None,
            "densite_semi": None, "n_cotes": n, "iic": None,
            "iic_market": None, "context_open": None,
        }
    hhi = sum(p * p for p in probs)  # 1/n .. 1
    fav_share = max(probs)  # part normalisée du favori
    ecart_fav = cotes[1] - cotes[0]
    n_semi = sum(1 for c in cotes if 6.0 <= c <= 15.0)
    densite_semi = n_semi / n
    # Composantes « ouverture » 0–1 (plus haut = plus instable)
    hhi_open = max(0.0, min(1.0, (0.28 - hhi) / 0.20))
    fav_open = max(0.0, min(1.0, (0.40 - fav_share) / 0.28))
    gap_open = max(0.0, min(1.0, (4.0 - ecart_fav) / 4.0))
    semi_open = max(0.0, min(1.0, densite_semi / 0.45))
    field_open = max(0.0, min(1.0, (n - 8) / 10.0))
    iic_market = (
        0.30 * hhi_open
        + 0.25 * fav_open
        + 0.20 * semi_open
        + 0.15 * gap_open
        + 0.10 * field_open
    )
    ctx_open = 0.50
    delta_ctx = 0.0
    if race is not None:
        ctx = _context_openness(race)
        ctx_open = ctx["context_open"]
        delta_ctx = ctx["delta_context"]
    # IIC-v2 hybride
    iic = 100.0 * (0.70 * iic_market + 0.30 * ctx_open)
    return {
        "hhi": round(hhi, 4),
        "fav_share": round(fav_share, 4),
        "ecart_fav": round(ecart_fav, 3),
        "densite_semi": round(densite_semi, 3),
        "n_cotes": n,
        "iic_market": round(100.0 * iic_market, 2),
        "context_open": round(ctx_open, 3),
        "delta_context": round(delta_ctx, 3),
        "iic": round(iic, 2),
    }


def determine_signature(chevaux: List[Cheval], race: RaceContext) -> Signature:
    """Étape 2 -- signature LOCK/STANDARD/CHAOS/MIXTE_LOCK (IIC-v2).

    Règle meneurs SUPPRIMÉE (dégénérait en CHAOS permanent sur le corpus).

    IIC-v2 hybride :
      1) 70 % marché (HHI, fav_share, densité 6–15, écart, field size)
      2) 30 % contexte (discipline / distance / hippodrome)
      3) Garde-fous durs sur part favori / écart (anti faux CHAOS / faux LOCK)

    Seuils : LOCK < 30 | MIXTE_LOCK 30–48 | STANDARD 48–68 | CHAOS ≥ 68
    + garde-fous LOCK / MIXTE prioritaires.
    """
    m = compute_race_market_metrics(chevaux, race)
    iic = m.get("iic")
    fav_share = m.get("fav_share")
    ecart_fav = m.get("ecart_fav")

    # Stash métriques sur le contexte pour audit / ticket B
    try:
        race.iic_v2 = m.get("iic")  # type: ignore[attr-defined]
        race.iic_market = m.get("iic_market")  # type: ignore[attr-defined]
        race.market_metrics = m  # type: ignore[attr-defined]
    except Exception:
        pass

    if iic is None:
        return Signature.STANDARD

    # Garde-fous durs (prioritaires sur IIC)
    if fav_share is not None and fav_share >= 0.42 and (ecart_fav or 0) >= 3.0:
        return Signature.LOCK
    if fav_share is not None and fav_share >= 0.32 and (ecart_fav or 0) >= 2.0 and iic < 55:
        return Signature.MIXTE_LOCK

    # Mapping IIC-v2
    if iic >= 68:
        return Signature.CHAOS
    if iic >= 48:
        return Signature.STANDARD
    if iic >= 30:
        return Signature.MIXTE_LOCK
    return Signature.LOCK


def compute_race_scores(race: RaceContext, chevaux: List[Cheval],
                         qualitatifs: List[QualitativeSignals]) -> List[HorseScore]:
    try:
        ensure_race_discipline(race)
    except Exception:
        pass

    # Harmonise cotes : matin manquante ← avant_course (évite HORS_TRANCHE)
    for c in chevaux:
        if (c.cote_matin is None or c.cote_matin <= 0) and c.cote_avant_course and c.cote_avant_course > 0:
            c.cote_matin = c.cote_avant_course
            # flag via commentaire libre non dispo; log silencieux
        if (c.cote_avant_course is None or c.cote_avant_course <= 0) and c.cote_matin and c.cote_matin > 0:
            c.cote_avant_course = c.cote_matin
    assert len(chevaux) == len(qualitatifs)

    # v1.29.41 : poids du champ. poids_{moyen,min,max}_champ_kg n'étaient JAMAIS
    # renseignés : le terme « poids relatif » des modules tactiques (plat/obstacle)
    # et le critère SSFO « <= moyenne-2 » restaient morts sur toutes les courses.
    poids = [float(c.poids_actuel_kg) for c in chevaux if c.poids_actuel_kg]
    if len(poids) >= max(4, int(0.7 * len(chevaux))):
        race.poids_champ_kg = poids
        moy, pmin, pmax = sum(poids) / len(poids), min(poids), max(poids)
        for c in chevaux:
            if c.poids_moyen_champ_kg is None:
                c.poids_moyen_champ_kg, c.poids_min_champ_kg, c.poids_max_champ_kg = moy, pmin, pmax

    # Corrigé le 07/08/2026 : derive_style_mpa() existait depuis longtemps
    # (repli musique via _style_from_musique, common.py) mais n'était
    # JAMAIS appelée nulle part dans le pipeline -- cheval.style_mpa
    # restait à None pour 100% des chevaux, sur 100% des courses testées.
    # Impact double : RAH-07/168 (diversité stylistique) voyait TOUJOURS
    # "INCONNU" pour tout le monde (contrainte impossible à respecter,
    # forçant GMO-V en relaxation maximale -- cf. les 2 derniers rapports
    # d'exécution) ET race.rythme_projete ci-dessous (nb_meneurs toujours
    # 0, en amont de determine_signature) était donc faux sur toutes les
    # courses. Ne dépend PAS de Bloc C -- juste du musique, déjà collecté.
    for cheval in chevaux:
        if cheval.style_mpa is None:
            style, conf, p_avant, st_flags = derive_style_mpa(cheval)
            cheval.style_mpa = style
            if cheval.p_avant is None:
                cheval.p_avant = p_avant

    if race.signature is None:
        race.signature = determine_signature(chevaux, race)
    if race.rythme_projete is None:
        nb_meneurs = sum(1 for c in chevaux if c.style_mpa and c.style_mpa.value.startswith("MENEUR"))
        race.nb_meneurs_champ = nb_meneurs
        race.rythme_projete = M.rythme_projete(nb_meneurs)

    # --- Enrichissements optionnels via open-pmu-api (pmu_corpus_analyse.py,
    # ajouté le 06/09/2026) -- no-op silencieux si ACTIVER_SUPRA_PHASE2_REEL
    # est False (par défaut) ou en cas d'échec réseau. Doivent tourner AVANT
    # la passe 1 : confrontations_directes est lu par module_n_h2h à
    # l'intérieur de compute_module_breakdown, et bonus_corde_empirique
    # doit être sur qual avant que pch_final.py ne l'additionne.
    from app.engine.pmu_corpus_analyse import (
        compute_biais_corde, bonus_corde_empirique, populate_confrontations_directes)
    biais_corde = compute_biais_corde(race)
    for cheval, qual in zip(chevaux, qualitatifs):
        qual.flags.extend(populate_confrontations_directes(cheval, chevaux, race))
        if biais_corde:
            bonus, corde_flags = bonus_corde_empirique(cheval, race, biais_corde)
            qual.bonus_corde_empirique = bonus
            qual.flags.extend(corde_flags)

    # --- Probabilité de marché sans marge bookmaker (probabilites_marche.py,
    # ajouté le 06/09/2026) -- informationnel, ne modifie aucun calcul PCH/tocard.
    from app.engine.pl_inclusion import compute_probabilites_marche
    probas_marche, overround = compute_probabilites_marche(chevaux)
    if probas_marche:
        for cheval, qual in zip(chevaux, qualitatifs):
            qual.probabilite_marche_vraie = probas_marche.get(cheval.numero)
            qual.overround_marche = overround

    # v1.29.41 : champs d'activité jamais renseignés (modules IFF/surmenage, Ghost D, CSF distance
    # habituelle restaient neutres). Dérivés de l'historique daté, STRICTEMENT avant la course.
    _derive_activite(chevaux, race)

    # --- Pass 1 : PCH_FINAL (sans OVERBET) ---
    breakdowns: List[ModuleBreakdown] = []
    for cheval, qual in zip(chevaux, qualitatifs):
        bd = compute_module_breakdown(cheval, race, chevaux, qual)
        bd.corde_empirique_pch = qual.bonus_corde_empirique
        bd.pch_final = clamp(0, 220, bd.pch_final + bd.corde_empirique_pch)
        bd.pch_norm = bd.pch_final / 220.0
        breakdowns.append(bd)

    # T2 Value est comparé au PCH de l’ensemble du champ après la passe 1;
    # le calcul n’utilise ainsi ni score absolu proxy ni résultat futur.
    apply_t2_value_scores(chevaux, race, breakdowns, qualitatifs)

    # --- SSFO, garde-fou PCH_FINAL>=160 (RAH-271) -- appliqué ici car
    # pch_final n'est connu qu'après compute_module_breakdown, alors que
    # bonus_ssfo est calculé en amont dans qualitative_engine.py.
    for bd, qual in zip(breakdowns, qualitatifs):
        if bd.pch_final >= 160 and qual.bonus_ssfo:
            qual.bonus_ssfo = 0.0
            if "SSFO_ZERO_PCH_PLAFOND" not in qual.flags:
                qual.flags.append("SSFO_ZERO_PCH_PLAFOND")

    tranches = [classify_tranche(c.cote_matin, getattr(c, "cote_avant_course", None) or c.cote_matin) for c in chevaux]

    # --- COMPOSITE v1 + ORDRE_SCORE_initial (Harville_mult=1.0) ---
    sov_results = [S.compute_sov_v2(c, t) for c, t in zip(chevaux, tranches)]
    iql_results = [S.compute_iql_v2(c) for c in chevaux]

    # --- RAH-163 (porté 11/09/2026) -- garde-fou anti-double-comptage
    # ferrure x SOV_v2. Doit s'exécuter ici : après SOV_v2 (connu seulement
    # à cette étape) mais AVANT composite_v1/stab_mults, qui consomment
    # bd.stab_pch. Contrairement à OVERBET, ce n'est pas une "2e passe"
    # post-ORDRE_SCORE -- la correction doit être visible dès COMPOSITE.
    for cheval, bd, (sov_v, _) in zip(chevaux, breakdowns, sov_results):
        apply_rah163_ferrure_sov_guard(cheval, bd, sov_v)

    composite_v1 = [S.compute_composite(bd, race.discipline, race.signature, t) for bd, t in zip(breakdowns, tranches)]

    tact_mults = [M.tact_mult(bd.tact_score) for bd in breakdowns]
    stab_mults = [S.stab_mult(bd.stab_pch) for bd in breakdowns]
    all_mults = [S.all_mult(c.all_score) for c in chevaux]

    ordre_initial = []
    for i in range(len(chevaux)):
        sov_v, _ = sov_results[i]
        iql_v, _ = iql_results[i]
        produit_brut = (1 + sov_v) * iql_v * tact_mults[i] * stab_mults[i] * all_mults[i] * 1.0
        produit_corrige = clamp(0.65, 1.45, produit_brut)
        ordre_initial.append(composite_v1[i] * produit_corrige)

    # --- OVERBET (Module O), 2e passe sur PCH/tocard ---
    overbet_flags_per_horse: List[List[str]] = []
    for i, (cheval, bd) in enumerate(zip(chevaux, breakdowns)):
        before = len(bd.flags)
        apply_overbet_second_pass(cheval, bd, ordre_initial[i], len(chevaux), race.allocation_eur)
        overbet_flags_per_horse.append(bd.flags[before:])

    # --- P5P6_SCORE (Étape 11.11bis, Partie 17.10), ajouté le 08/08/2026 ---
    # tocard_score doit être la valeur FINALE (post-OVERBET) puisque
    # P5P6_SCORE sert de critère d'entrée au Pool Élargi (Étape 11.a),
    # lui-même évalué après cette passe.
    for i, (cheval, bd, qual) in enumerate(zip(chevaux, breakdowns, qualitatifs)):
        score, detail, p5p6_flags = compute_p5p6_score(
            cheval, race, qual.signaux_catalogue, bd.flags, bd.tocard_score, qual.ls_final_par_famille)
        bd.p5p6_score = score
        bd.p5p6_detail = detail
        for f in p5p6_flags:
            if f not in bd.flags:
                bd.flags.append(f)

    composite_v2 = [S.compute_composite(bd, race.discipline, race.signature, t) for bd, t in zip(breakdowns, tranches)]

    # --- classement provisoire -> position_attendue ---
    ordre_ranking = sorted(range(len(chevaux)), key=lambda i: ordre_initial[i], reverse=True)
    position_attendue = {idx: rank + 1 for rank, idx in enumerate(ordre_ranking)}

    # --- harville_fiable (niveau course) ---
    ift_prelim = []
    for i, (cheval, bd) in enumerate(zip(chevaux, breakdowns)):
        sov_flags = sov_results[i][1]
        ift_v, _ = S.compute_ift(cheval, bd, race, sov_flags, iql_results[i][1], position_attendue[i])
        ift_prelim.append(ift_v)

    nb_valeur_morte = sum(1 for i, c in enumerate(chevaux)
                          if (c.cote_matin or 0) > 25 and not breakdowns[i].signaux_actifs
                          and breakdowns[i].tocard_score < 0.20)
    nb_overbet_media = sum(1 for fl in overbet_flags_per_horse if "OVERBET_MEDIA" in fl)
    nb_killlist = sum(1 for bd in breakdowns if "STAB_DQ_SERIE_CRITIQUE" in bd.flags)

    harville_fiable = S.harville_fiable_course(ift_prelim, nb_valeur_morte, nb_overbet_media,
                                                nb_killlist, len(chevaux))

    # --- Harville_mult par cheval + PRODUIT_MULT_v2 + ORDRE_FINAL ---
    synths: List[SynthesisResult] = []
    for i, (cheval, bd) in enumerate(zip(chevaux, breakdowns)):
        harville_mult = 1.0
        if harville_fiable:
            pos = position_attendue[i]
            cote_ref = cheval.cote_avant_course or cheval.cote_matin
            if cote_ref is not None and cote_ref > 8 and pos in (2, 3, 4, 5):
                bonus = S.harville_bonus_for(cote_ref, pos)
                overbet_flags = overbet_flags_per_horse[i]
                if "OVERBET_SURCOTE" in overbet_flags and pos in (2, 3):
                    bonus = 0.0
                    bd.flags.append("HARVILLE_INDIVIDUEL_OFF")
                harville_mult = 1.0 + bonus
        else:
            bd.flags.append("HARVILLE_DESACTIVE")

        sov_v, sov_flags = sov_results[i]
        iql_v, iql_source = iql_results[i]
        produit_brut = (1 + sov_v) * iql_v * tact_mults[i] * stab_mults[i] * all_mults[i] * harville_mult
        produit_corrige = clamp(0.65, 1.45, produit_brut)
        if produit_corrige != produit_brut:
            bd.flags.append("MULT_PLAFONNE_BAS" if produit_brut < 0.65 else "MULT_PLAFONNE_HAUT")

        ordre_base = composite_v2[i] * produit_corrige
        # GRU multi-hippodrome (remplace / généralise malus Enghien seul)
        ordre_final = S.ordre_final_with_gru(ordre_base, race, cheval)
        # v1.29.64 (poids maîtrisé) : rétrogradation des favoris / seconds à piège GRU (multiplicateur ≥ VANTAGE_GRU_PIEGE_MULT_MIN, jamais de boost)
        try:
            from app.engine.gru_signals import apply_gru_piege_mult
            _of_pm = apply_gru_piege_mult(ordre_final, max(0.0, -float(getattr(bd, "gru_pepite_piege_pch", 0.0) or 0.0)),
                                          cheval.cote_avant_course if cheval.cote_avant_course is not None else cheval.cote_matin)
            if _of_pm != ordre_final:
                bd.flags.append("GRU_PIEGE_MULT")
                ordre_final = _of_pm
        except Exception:   # noqa: BLE001
            pass

        ift_v, ift_label = S.compute_ift(cheval, bd, race, sov_flags, iql_source, position_attendue[i])

        synths.append(SynthesisResult(
            composite=composite_v2[i], sov_v2=sov_v, iql_v2=iql_v, harville_mult=harville_mult,
            tact_mult=tact_mults[i], stab_mult=stab_mults[i], all_mult=all_mults[i],
            produit_mult_brut=produit_brut, produit_mult_corrige=produit_corrige,
            ordre_base=ordre_base, ordre_final=ordre_final, ift=ift_v, ift_label=ift_label,
            tranche=tranches[i], flags=sov_flags + list(overbet_flags_per_horse[i]),
        ))

    horses = [HorseScore(cheval=c, breakdown=bd, synthesis=s) for c, bd, s in zip(chevaux, breakdowns, synths)]

    # --- Calibration 13/09/2026 : blend marché dans ORDRE_FINAL (grands champs) ---
    # Correctif double marché 14/09/2026 : alpha=0.35 (était 0.45) — réduit le sur-poids favori
    # moyen du gagnant de ~8.8 à ~5.6 et relève rang1/hits, sans toucher COMPOSITE.
    # Inutile sous 14 partants (ORDRE déjà correct ~5e).
    n_partants = len(horses)
    # Correctif 14/09/2026 : alpha 0.35 (était 0.45) pour limiter le
    # triple comptage marché (ORDRE + GMO market_blend + op model).
    if n_partants >= 14:
        alpha = 0.35
        market = []
        for h in horses:
            cote = h.cheval.cote_avant_course or h.cheval.cote_matin
            market.append(1.0 / cote if cote is not None and cote > 1.01 else 0.0)
        m_total = sum(market)
        if m_total > 1e-12:
            m_norm = [m / m_total for m in market]
            o_vals = [max(0.0, h.synthesis.ordre_final) for h in horses]
            o_total = sum(o_vals) or 1.0
            o_norm = [o / o_total for o in o_vals]
            for h, o, m in zip(horses, o_norm, m_norm):
                blended = (1.0 - alpha) * o + alpha * m
                h.synthesis.ordre_final = blended
                if "ORDRE_MARKET_BLEND_035" not in h.breakdown.flags:
                    h.breakdown.flags.append("ORDRE_MARKET_BLEND_035")

    # --- Synthèse SUPRA (Phases 1/3/4/5 réelles + verrou de convergence +
    # plafond 3 modifications/course, 17.6) -- ajoutée le 09/08/2026.
    # Nécessite ordre_final connu pour tout le champ (rang interne, Phase 4).
    sov_flags_par_cheval = {chevaux[i].numero: sov_results[i][1] for i in range(len(chevaux))}
    supra_synth = compute_supra_synthese(race, horses, sov_flags_par_cheval)
    by_numero = {h.cheval.numero: h for h in horses}
    for mod in supra_synth["modifications_retenues"]:
        h = by_numero.get(mod["numero"])
        if h is None:
            continue
        delta = supra_synth["amplitude_pch_par_modification"] * (1 if mod["sens"] == "+" else -1)
        h.breakdown.supra_pch_delta = delta
        h.breakdown.pch_final = clamp(0, 220, h.breakdown.pch_final + delta)
        h.breakdown.pch_norm = h.breakdown.pch_final / 220.0
        h.breakdown.flags.append(f"SUPRA_MODIFICATION_{mod['sens']}_{mod['nb_phases']}PHASES_CONVERGENTES")
    race._supra_synthese = supra_synth  # attaché de façon informelle, journalisé dans le JSON final

    _fill_missing_tranches(horses)
    return horses



def _fill_missing_tranches(horses: List[HorseScore]) -> None:
    """Assigne une tranche provisoire si cote absente (évite HORS_TRANCHE massif).
    Proxy : rang par ordre_final dans le champ → T1..T4b.
    """
    missing = [h for h in horses if h.synthesis and h.synthesis.tranche is None]
    if not missing:
        return
    ranked = sorted(horses, key=lambda h: (h.synthesis.ordre_final if h.synthesis else 0.0), reverse=True)
    n = max(len(ranked), 1)
    for rank, h in enumerate(ranked):
        if not h.synthesis or h.synthesis.tranche is not None:
            continue
        pct = rank / n
        if pct < 0.15:
            h.synthesis.tranche = Tranche.T1
        elif pct < 0.30:
            h.synthesis.tranche = Tranche.T2
        elif pct < 0.55:
            h.synthesis.tranche = Tranche.T3
        elif pct < 0.80:
            h.synthesis.tranche = Tranche.T4A
        else:
            h.synthesis.tranche = Tranche.T4B
        if "TRANCHE_PROXY_RANK" not in h.synthesis.flags:
            h.synthesis.flags.append("TRANCHE_PROXY_RANK")
