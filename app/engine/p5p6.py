"""
p5p6.py -- P5P6_SCORE (Étape 11.11bis, Partie 17.10 pour la définition
qui fait foi). Absent du moteur jusqu'au 08/08/2026.

IMPORTANT -- redéfini par le patch "Objectif Désordre" (17.10a) : sous ce
paradigme, P5P6 ne remplace plus directement P5/P6 dans un ticket
séquentiel BORDA (l'Étape D du texte source, "Remplacement", est donc
volontairement NON implémentée ici -- elle appartient à l'ancien
paradigme séquentiel). P5P6_SCORE sert uniquement de :
  1. Critère d'entrée au Pool Élargi (P5P6_SCORE >= 0,30, Étape 11.a) --
     c'était le 5e critère manquant identifié le 07/08/2026.
  2. Valeur informative journalisée (p5_p5p6_score et détail C1-C5),
     pour audit et pour un usage futur éventuel dans GMO-V.

Sous-composantes, état au 12/09/2026 (repli explicite, jamais deviné) :
  - C1 : enrichi (B04 + tocard_score + proxy ≥2 Ghost D STRICT ou SSFO
    actif). Les sous-critères D02/D43/B51/B55/B38/D22/D50/D51 et
    RAH-114 coeff_temps restent non trackés individuellement.
  - C3 : PENTE_SCORE (B47bis) branché le 02/09/2026 -- utilise
    cheval.pente_score quand disponible (>=3 courses datées avec partants
    connus dans l'historique), repli PENTE_INSUFFISANT (0.4) sinon.
  - C5 : allocations_last3 rarement peuplé -- toujours 1.0 (repli "aucune
    montée détectée" par défaut protocole, pas une valeur mesurée).
  - LS_FINAL utilisé pour C2 = max(ls_final_par_famille.values()) --
    approximation Longshot Hunter déjà documentée ailleurs comme telle.
  - Kill-List (M25) approximé par STAB_DQ_SERIE_CRITIQUE (le catalogue
    M25 lui-même n'est pas implémenté).
"""
from __future__ import annotations
from typing import List, Tuple, Dict
from app.models import Cheval, RaceContext, CatalogSignal, Signature


def _c1_signal_fort_unique(cheval: Cheval, signaux: List[CatalogSignal], tocard_score: float,
                            breakdown_flags: List[str] = None) -> float:
    """C1 enrichi le 12/09/2026 : en plus de B04 / tocard_score, on
    reconnaît un signal fort unique via :
      - présence d'au moins 2 Ghost D STRICT (convergence D)
      - ou SSFO_ACTIFS avec bonus implicite (flag présent)
    Ces proxies n'inventent aucune donnée (RÈGLE 2) : ils ne font que
    lire des signaux déjà calculés en amont."""
    b04 = next((s for s in signaux if s.id == "B04" and s.confiance == "STRICT"), None)
    if b04 is not None:
        return 0.9  # RAH-114 coeff_temps>=0,75 non tracké -- approximé sans ce sous-critère
    if tocard_score >= 0.35:
        return 0.7
    if 0.25 <= tocard_score < 0.35:
        return 0.5
    # T2 Value (semi-favoris) — tocard désactivé sur T1/T2
    flags = breakdown_flags or []
    if any(f.startswith("T2_VALUE_FORT") for f in flags):
        return 0.65
    if any(f.startswith("T2_VALUE_UTILE") for f in flags):
        return 0.45
    t2_sig = next((s for s in signaux if getattr(s, "id", None) == "T2_VALUE"), None)
    if t2_sig is not None and float(getattr(t2_sig, "valeur_brute", 0) or 0) >= 0.55:
        return 0.65
    if t2_sig is not None and float(getattr(t2_sig, "valeur_brute", 0) or 0) >= 0.40:
        return 0.45

    flags = breakdown_flags or []
    # Ghost D catalogue (rare) + Ghost D flags (source principale, cf. ghost_d.py)
    nb_ghost_strict = sum(1 for s in signaux
                          if str(s.id).startswith("D") and s.confiance == "STRICT")
    nb_ghost_flags = sum(
        1 for f in flags
        if (f.startswith("D") and not f.startswith("D46")
            and "STRICT" in f)
        or f in ("D41", "D22_STRICT", "D01_STRICT", "D43_STRICT", "D36_STRICT")
    )
    if nb_ghost_strict >= 2 or nb_ghost_flags >= 2:
        return 0.55
    if any(f.startswith("SSFO_ACTIFS_") for f in flags):
        return 0.45
    return 0.0


def _c2_plage_cote(cheval: Cheval, signaux: List[CatalogSignal], ls_final: float,
                    signature: Signature) -> float:
    cote = cheval.cote_matin
    if cote is None:
        return 0.5  # aucune donnée -- valeur neutre, pas de repli documenté dans le texte source
    nb_strict = sum(1 for s in signaux if s.confiance == "STRICT" and s.valeur_brute > 0)
    if cote < 6:
        return 0.4 if (nb_strict >= 3 or ls_final >= 0.50) else 0.1
    if cote < 10:
        return 0.65 if nb_strict >= 2 else 0.5
    if cote <= 30:
        return 1.0
    if cote <= 60:
        if signature == Signature.CHAOS:
            return 1.0  # RAH-90/Étape D : ne jamais superposer un 2e assouplissement
        return 0.9 if ls_final >= 0.60 else 0.8
    # cote > 60
    if signature == Signature.CHAOS:
        return 1.0
    return 0.6 if ls_final >= 0.60 else 0.3


def _c3_trajectoire(cheval: Cheval, signaux: List[CatalogSignal]) -> Tuple[float, bool]:
    """PENTE_SCORE (B47bis, historique_signals.py) exposé en champ propre
    depuis le 02/09/2026 -- auparavant toujours en repli PENTE_INSUFFISANT
    (0.4) faute d'accès à la valeur brute. Seuils identiques à
    historique_signals.py (mêmes 8 courses triées) : PS_FORT>=0.15,
    PS_MODERE>=0.07, PS_STABLE>=-0.05, PS_DECLIN>=-0.12, sinon PS_CHUTE.
    RAH-152 : plafonné à 0.6 si redondance avec un bonus PCH déjà plein
    (B47bis valeur_brute==12.0, cas PS_FORT non atténué par garde-jeune)."""
    pente = cheval.pente_score
    if pente is None:
        return 0.4, False  # PENTE_INSUFFISANT -- moins de 3 courses datées avec partants connus
    if pente >= 0.15:
        c3 = 1.0
    elif pente >= 0.07:
        c3 = 0.7
    elif pente >= -0.05:
        c3 = 0.5
    elif pente >= -0.12:
        c3 = 0.2
    else:
        c3 = 0.0
    b47bis_plein = any(s.id == "B47bis" and s.valeur_brute >= 12.0 for s in signaux)
    if c3 == 1.0 and b47bis_plein:
        return 0.6, True  # C3_PLAFONNE_REDONDANCE
    return c3, False


def _c4_securite(breakdown_flags: List[str], signaux: List[CatalogSignal]) -> float:
    if "STAB_DQ_SERIE_CRITIQUE" in breakdown_flags:  # proxy Kill-List (M25 non implémenté)
        return 0.0
    m30 = next((s for s in signaux if s.id == "M30" and s.confiance == "STRICT"), None)
    if m30 is not None:
        return 0.3
    if "FEU_ROUGE" in breakdown_flags:
        return 0.2
    if "FEU_ORANGE" in breakdown_flags:
        return 0.6
    return 1.0


def _c5_montee_categorie() -> float:
    # allocations_last3 jamais peuplé -- repli protocole "aucune montée détectée"
    return 1.0


def compute_p5p6_score(cheval: Cheval, race: RaceContext, signaux: List[CatalogSignal],
                        breakdown_flags: List[str], tocard_score: float,
                        ls_final_par_famille: Dict[str, float]) -> Tuple[float, Dict[str, float], List[str]]:
    ls_final = max(ls_final_par_famille.values()) if ls_final_par_famille else 0.0
    signature = race.signature or Signature.STANDARD

    c1 = _c1_signal_fort_unique(cheval, signaux, tocard_score, breakdown_flags)
    c2 = _c2_plage_cote(cheval, signaux, ls_final, signature)
    c3, c3_plafonne = _c3_trajectoire(cheval, signaux)
    c4 = _c4_securite(breakdown_flags, signaux)
    c5 = _c5_montee_categorie()

    score = 0.35 * c1 + 0.20 * c2 + 0.18 * c3 + 0.12 * c4 + 0.15 * c5
    detail = {"c1": round(c1, 3), "c2": round(c2, 3), "c3": round(c3, 3),
              "c4": round(c4, 3), "c5": round(c5, 3)}
    # C3 utilise PENTE_SCORE réel (02/09/2026) ; C1 enrichi le 12/09/2026
    # avec proxies Ghost D / SSFO ; C5 reste en repli (allocations_last3
    # rarement peuplé).
    flags = ["P5P6_C5_APPROXIME"]
    if cheval.pente_score is None:
        flags.append("P5P6_C3_REPLI_PENTE_INDISPONIBLE")
    if c3_plafonne:
        flags.append("C3_PLAFONNE_REDONDANCE")
    if c1 >= 0.45 and tocard_score < 0.25:
        flags.append("P5P6_C1_PROXY_GHOST_OU_SSFO")
    return round(score, 3), detail, flags
