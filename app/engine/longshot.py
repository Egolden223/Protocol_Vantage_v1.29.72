"""
longshot.py -- Module Chasseur de Longshots (Partie 17.4, 8 familles).
Registre formel : LONGSHOT_F_CATALOG (F1–F8), 29/09/2026.
Éligibilité : cote>30/1 (avant_course ou matin) ET score famille dans LS_FINAL.
F6 = journalisation seule (exclue de LS_FINAL, protocole).

Couverture réelle des sous-termes, honnêtement :
  - F1 Revenant : calculable (delai_j, gains relatifs au champ en repli de
    "Plafond" qui n'est pas un concept structuré ailleurs, classement_
    national si Frequence-Turf a tourné -- sinon Driver_Elite=0).
  - F2 Régulier déclassé : NON calculable -- dépend d'IRP_ajusté (B47),
    non implémenté (formule propre à part entière). Toujours 0, flag
    F2_NON_EVALUE.
  - F3 Talent brut : calculable via record_chrono_sec (Zone-Turf) --
    "meilleur tiers du champ" au lieu du ratio RK_ref/RK_cheval exact
    (RK non disponible), approximation documentée.
  - F4 Configuration favorable : calculable (style_mpa, maintenant
    réellement peuplé) pour Alignement_Style ; Antecedent_Parcours et
    Commentaire_Tactique non disponibles (pas de hippodrome dans
    PerfHistorique, pas de commentaire collecté) -- ces 2 termes à 0.
  - F5 Oublié du marché : calculable si Frequence-Turf a tourné (ICP,
    jours Quinté seulement) sinon 0.
  - F7 Retard de gains : calculable (gains relatifs, taux Top5 via
    historique_terrain/distance).
  - F8 Spécialiste du parcours exact : approximé par distance seule
    (±100m) -- PerfHistorique ne stocke pas l'hippodrome par entrée,
    donc pas de vraie correspondance "hippodrome+distance".
  - F6 Opportuniste tactique : n'entre JAMAIS dans LS_FINAL (exclue par
    construction du protocole) -- journalisation seule (flag
    f6_candidat_observe), implémentée à titre informatif uniquement.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from app.models import Cheval, RaceContext, StyleMPA, Signature


# ---------------------------------------------------------------------------
# REGISTRE FORMEL des familles Longshots F1–F8 (Partie 17.4)
# Formalisé 29/09/2026 — même logique de gouvernance que GHOST_D_CATALOG.
# F6 est journalisée mais EXCLUE de LS_FINAL (protocole).
# ---------------------------------------------------------------------------
LONGSHOT_F_CATALOG: dict = {
    "F1": {
        "label": "Revenant",
        "description": "Longue absence + gains relatifs bas + driver élite + top3 12 mois",
        "in_ls_final": True,
        "status": "ACTIVE",
        "data": ["delai_j", "gains_totaux_eur", "driver_stats.classement_national", "historique_*"],
    },
    "F2": {
        "label": "Régulier déclassé",
        "description": "IRP/B47 élevé + top3 récent + progression B47bis (proxy IRP par palier)",
        "in_ls_final": True,
        "status": "ACTIVE_DEGRADED",  # IRP approximé via B47 si présent, sinon 0
        "data": ["signaux B47/B47bis", "historique_*"],
    },
    "F3": {
        "label": "Talent brut",
        "description": "Record chrono dans le meilleur tiers du champ",
        "in_ls_final": True,
        "status": "ACTIVE_APPROX",
        "data": ["record_chrono_sec"],
    },
    "F4": {
        "label": "Configuration favorable",
        "description": "Alignement style MPA ; antécédent parcours / commentaire tactique souvent 0",
        "in_ls_final": True,
        "status": "ACTIVE_PARTIAL",
        "data": ["style_mpa", "rythme_projete"],
    },
    "F5": {
        "label": "Oublié du marché",
        "description": "ICP presse faible + cote longue (Quinté)",
        "in_ls_final": True,
        "status": "ACTIVE",
        "data": ["icp_global", "icp_pondere"],
    },
    "F6": {
        "label": "Opportuniste tactique",
        "description": "Attentiste + signature chaos + distance longue — journalisation seule",
        "in_ls_final": False,  # exclu par construction du protocole
        "status": "LOG_ONLY",
        "data": ["style_mpa", "signature", "distance_m"],
    },
    "F7": {
        "label": "Retard de gains",
        "description": "Gains relatifs bas + taux Top5 récent",
        "in_ls_final": True,
        "status": "ACTIVE",
        "data": ["gains_totaux_eur", "historique_*"],
    },
    "F8": {
        "label": "Spécialiste du parcours",
        "description": "Top3 sur même distance (±100m) — hippodrome non joint",
        "in_ls_final": True,
        "status": "ACTIVE_APPROX",
        "data": ["historique_distance", "distance_m"],
    },
}
LONGSHOT_F_ACTIVE_IN_LS = tuple(
    k for k, v in LONGSHOT_F_CATALOG.items() if v.get("in_ls_final")
)
LONGSHOT_F_ALL_IDS = tuple(sorted(LONGSHOT_F_CATALOG.keys(), key=lambda x: int(x[1:])))
assert len(LONGSHOT_F_CATALOG) == 8
assert set(LONGSHOT_F_ACTIVE_IN_LS) == {"F1", "F2", "F3", "F4", "F5", "F7", "F8"}
# Portée cote : T3 (≥15) + T4A/T4B — pas de redondance intentionnelle avec
# Ghost D (D18 drift, D35 presse, D08 retour) : F* = score composite famille ;
# Ghost D = signaux atomiques tocard. Décote si F5 seule (ICP déjà en D).


# Seuil aligné T3 (Partie 17.9 : T3 = 15–35, T4A = 35–100, T4B ≥ 100)
# Recherche turf 2026 : outsiders Top5 souvent ~12–20/1 ; tocards >30/1 plus rares.
_SEUIL_ELIGIBILITE_COTE = 15.0
_SEUIL_T3_MAX = 35.0
_SEUIL_T4A_MAX = 100.0

# Activation famille + multiplicateur LS_FINAL par bande (évite de noyer T3
# avec le même barème que T4B, et exige plus de signal pour les extrêmes).
_BAND_PARAMS = {
    "T3":  {"seuil_actif": 0.25, "ls_mult": 0.85, "ls_cap": 0.85},
    "T4A": {"seuil_actif": 0.30, "ls_mult": 1.00, "ls_cap": 1.00},
    "T4B": {"seuil_actif": 0.40, "ls_mult": 1.00, "ls_cap": 1.00},
}


def _cote_ref(cheval: Cheval) -> Optional[float]:
    c = cheval.cote_avant_course if cheval.cote_avant_course is not None else cheval.cote_matin
    try:
        return float(c) if c is not None else None
    except (TypeError, ValueError):
        return None


def _band_from_cote(cote: float) -> str:
    if cote < _SEUIL_T3_MAX:
        return "T3"
    if cote < _SEUIL_T4A_MAX:
        return "T4A"
    return "T4B"



def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _gains_ratio_plafond(cheval: Cheval, champ: List[Cheval]) -> float:
    """"Plafond" n'est pas un concept structuré ailleurs dans le moteur
    (dépendrait d'un parsing des conditions de course, non fait) --
    approximé par le maximum de gains_totaux_eur observé dans le champ.
    Renvoie Gains/Plafond (PAS 1-Gains/Plafond -- au variable de faire
    l'inversion selon la formule appelante)."""
    gains_champ = [c.gains_totaux_eur for c in champ if c.gains_totaux_eur is not None]
    plafond = max(gains_champ) if gains_champ else None
    if plafond is None or plafond <= 0 or cheval.gains_totaux_eur is None:
        return 0.5  # aucune donnée -- valeur neutre, pas un repli documenté par le protocole
    return _clamp01(cheval.gains_totaux_eur / plafond)


def _top_n_recent(historique, n_rang: int, jours_max: int, date_ref: str) -> Tuple[int, int]:
    """Retourne (nb_top_n, nb_courses_valides) parmi les performances avec
    une date exploitable, dans la fenêtre jours_max."""
    if not historique or not date_ref:
        return 0, 0
    try:
        d_ref = datetime.fromisoformat(date_ref[:10]).date()
    except ValueError:
        return 0, 0
    nb_top, nb_valides = 0, 0
    for p in historique:
        if not p.date:
            continue
        try:
            d = datetime.fromisoformat(p.date[:10]).date()
        except ValueError:
            continue
        if (d_ref - d).days > jours_max or (d_ref - d).days < 0:
            continue
        nb_valides += 1
        if p.rang and p.rang <= n_rang:
            nb_top += 1
    return nb_top, nb_valides


def compute_longshot_families(cheval: Cheval, race: RaceContext, champ: List[Cheval],
                               signaux: List = None) -> Dict[str, object]:
    flags: List[str] = []
    cote_ref_f = _cote_ref(cheval)
    if cote_ref_f is None or cote_ref_f < _SEUIL_ELIGIBILITE_COTE:
        return {
            "eligible": False,
            "ls_final": 0.0,
            "ls_base": 0.0,
            "familles_actives": [],
            "familles_scores": {k: 0.0 for k in LONGSHOT_F_ACTIVE_IN_LS},
            "flags": ["LS_COTE_SOUS_SEUIL_OU_ABSENTE"],
            "famille_dominante": None,
            "palier": "N/A",
            "band": None,
            "catalog_version": "F1-F8@T3T4-v1.29.34",
        }
    band = _band_from_cote(cote_ref_f)
    band_p = _BAND_PARAMS[band]
    flags.append(f"LS_BAND_{band}")

    historique = (cheval.historique_distance or []) + (cheval.historique_terrain or [])
    date_ref = race.date_course or ""

    # --- F1 Revenant ---
    absence = cheval.delai_j if cheval.delai_j is not None else 0
    top3_12m, _ = _top_n_recent(historique, 3, 365, date_ref)
    driver_elite = 1.0 if (cheval.driver_stats and cheval.driver_stats.classement_national
                            and cheval.driver_stats.classement_national <= 20) else 0.0
    if not (cheval.driver_stats and cheval.driver_stats.classement_national):
        flags.append("F1_DRIVER_ELITE_NON_EVALUE")
    f1 = (0.25 * min(1.0, absence / 90) + 0.25 * (1 - _gains_ratio_plafond(cheval, champ))
          + 0.25 * driver_elite + 0.25 * (1.0 if top3_12m >= 1 else 0.0))

    # --- F2 Régulier déclassé -- débloqué le 09/08/2026 (B47/IRP existe désormais) ---
    signaux = signaux or []
    b47 = next((s for s in signaux if s.id == "B47"), None)
    b47bis = next((s for s in signaux if s.id == "B47bis"), None)
    if b47 is not None:
        # IRP brut non exposé en champ dédié (seul le palier PCH l'est) --
        # approximation par palier, documentée. STRICT~0.65, DÉGRADÉ~0.475,
        # MINIMAL/DERNIER_RECOURS~0.30.
        irp_est = {"STRICT": 0.65, "DEGRADE": 0.475, "MINIMAL": 0.30}.get(b47.confiance, 0.475)
        terme_irp = min(1.0, irp_est / 0.70)
        top3_5d, nb5 = _top_n_recent(historique, 3, 150, date_ref)
        terme_top3 = 1.0 if nb5 >= 5 and top3_5d >= 1 else 0.0
        terme_progression = 1.0 if (b47bis and b47bis.valeur_brute > 0) else 0.0
        flags.append("F2_CHANGEMENT_ENTRAINEUR_NON_EVALUE")  # pas de tracking "entraîneur précédent"
        f2 = 0.35 * terme_irp + 0.25 * terme_top3 + 0.25 * terme_progression + 0.15 * 0.0
        flags.append("F2_IRP_APPROXIME_PAR_PALIER_B47")
    else:
        f2 = 0.0
        flags.append("F2_NON_EVALUE_B47_ABSENT")

    # --- F3 Talent brut ---
    records_champ = [c.record_chrono_sec for c in champ if c.record_chrono_sec is not None]
    if cheval.record_chrono_sec is not None and len(records_champ) >= 3:
        records_champ.sort()
        seuil_tiers = records_champ[max(0, len(records_champ) // 3 - 1)]
        record_top_tiers = 1.0 if cheval.record_chrono_sec <= seuil_tiers else 0.0
    else:
        record_top_tiers = 0.0
        flags.append("F3_RECORD_NON_EVALUE")
    top4c, nb4 = _top_n_recent(historique, 9999, 240, date_ref)  # "place" = classé, pas nécessairement top3
    place_4d = 1.0 if nb4 >= 4 and top4c >= 1 else 0.0
    dq_12m = sum(1 for p in historique if p.incident)
    f3 = (0.30 * record_top_tiers + 0.30 * driver_elite + 0.20 * place_4d
          + 0.20 * (1 - min(1.0, dq_12m / 5)))

    # --- F4 Configuration favorable ---
    alignement_style = 0.0
    if cheval.style_mpa == StyleMPA.MENEUR_MODERE and (race.rythme_projete or "") in ("LENT", "CONTROLE"):
        alignement_style = 1.0
    elif cheval.style_mpa == StyleMPA.ATTENTISTE and (race.rythme_projete or "") in ("RAPIDE", "TRES_RAPIDE"):
        alignement_style = 1.0
    elif cheval.style_mpa == StyleMPA.POLYVALENT:
        alignement_style = 0.5
    if not cheval.style_mpa:
        flags.append("F4_STYLE_NON_EVALUE")
    flags.append("F4_ANTECEDENT_PARCOURS_ET_COMMENTAIRE_NON_EVALUES")  # pas de hippodrome par entrée, pas de commentaire collecté
    f4 = 0.40 * alignement_style  # + 0.30*Antecedent_Parcours (0) + 0.30*Commentaire_Tactique (0)

    # --- F5 Oublié du marché ---
    if cheval.icp_pondere is not None:
        icp_norm = min(1.0, cheval.icp_pondere / 50.0)  # normalisation grossière, pas de barème protocole précisé
        top3_3d, nb3 = _top_n_recent(historique, 3, 90, date_ref)
        top3_recent = 1.0 if nb3 >= 3 and top3_3d >= 1 else 0.0
        f5 = 0.35 * (1 - icp_norm) + 0.35 * top3_recent + 0.30 * 0.5  # SOV_v2_positif non isolable ici -> neutre
    else:
        f5 = 0.0
        flags.append("F5_NON_EVALUE_ICP_ABSENT")

    # --- F7 Retard de gains ---
    top5_5d, nb5 = _top_n_recent(historique, 5, 150, date_ref)
    taux_top5 = (top5_5d / nb5) if nb5 else 0.0
    f7 = 0.5 * (1 - _gains_ratio_plafond(cheval, champ)) + 0.5 * taux_top5

    # --- F8 Spécialiste du parcours exact (approximé, distance seule) ---
    if race.distance_m and cheval.historique_distance:
        memes_distance = [p for p in cheval.historique_distance if abs(p.valeur - race.distance_m) <= 100]
        if memes_distance:
            victoires_top3 = sum(1 for p in memes_distance if p.rang <= 3)
            f8 = _clamp01(victoires_top3 / len(memes_distance))
            flags.append("F8_APPROXIME_DISTANCE_SEULE_SANS_HIPPODROME")
        else:
            f8 = 0.0
    else:
        f8 = 0.0
        flags.append("F8_NON_EVALUE")

    # --- F6 Opportuniste tactique -- jamais dans LS_BASE, journalisation seule ---
    f6_candidat = (cheval.style_mpa == StyleMPA.ATTENTISTE and
                   (race.signature == Signature.CHAOS) and
                   race.distance_m and race.distance_m >= 2600)
    if f6_candidat:
        flags.append("f6_candidat_observe")

    scores = {"F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5, "F7": f7, "F8": f8}
    ls_base = max(scores.values())
    famille_max = max(scores, key=scores.get)

    # Seuils d'activation par bande T3/T4 (anti-bruit T4B, ouverture T3)
    seuil_actif = float(band_p["seuil_actif"])
    familles_actives = [k for k, v in scores.items() if v >= seuil_actif]
    bonus = 1.20 if len(familles_actives) >= 3 else (1.10 if len(familles_actives) == 2 else 1.0)
    # Anti-redondance légère F5 (ICP) : déjà couvert par Ghost D35/D22 —
    # si F5 est la seule famille active, décote 15 % (signal isolé presse).
    if familles_actives == ["F5"]:
        ls_base = ls_base * 0.85
        flags.append("LS_F5_SEULE_DECOTE_ANTI_REDONDANCE_GHOST")
    ls_raw = ls_base * bonus * float(band_p["ls_mult"])
    ls_final = min(float(band_p["ls_cap"]), ls_raw)
    # T3 : exiger au moins 1 famille active sinon pas d'éligibilité « utile »
    if band == "T3" and not familles_actives:
        flags.append("LS_T3_SANS_FAMILLE_ACTIVE")
        return {
            "eligible": False,
            "ls_final": 0.0,
            "ls_base": round(ls_base, 3),
            "familles_actives": [],
            "familles_scores": {k: round(v, 3) for k, v in scores.items()},
            "flags": flags,
            "famille_dominante": famille_max,
            "palier": "N/A",
            "band": band,
            "catalog_version": "F1-F8@T3T4-v1.29.34",
        }

    # Scores F6 exclus de LS (protocole) mais exposés pour audit
    scores_audit = dict(scores)
    scores_audit["F6"] = 1.0 if f6_candidat else 0.0

    return {
        "eligible": True,
        "ls_final": round(ls_final, 3),
        "ls_base": round(ls_base, 3),
        "famille_dominante": famille_max,
        "familles_actives": familles_actives,
        "familles_scores": {k: round(v, 3) for k, v in scores.items()},
        "familles_scores_audit": {k: round(v, 3) for k, v in scores_audit.items()},
        "flags": flags,
        # Gouvernance 17.4 : familles LS au palier BETA tant qu'un cycle
        # multi-courses de promotion ALPHA n'est pas en place.
        "palier": "BETA",
        "catalog_version": "F1-F8@T3T4-v1.29.34",
        "band": band,
        "catalog_ids": list(LONGSHOT_F_ALL_IDS),
        "in_ls_final_ids": list(LONGSHOT_F_ACTIVE_IN_LS),
        "f6_log_only": bool(f6_candidat),
    }
