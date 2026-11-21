"""
GRU Signals — CatalogSignal G-series + numéro bias + ticket policy
==================================================================
Applique le catalogue GRU (gru_catalog.py) aux partants :
  - Gxx signaux de contexte hippodrome (spécialiste, distance, surface…)
  - apply_numero_bias (AS attelé / corde plat selon hippo)
  - ticket_policy (densifier | elargir | mixte) exposée au pipeline

RÈGLE 2 : jamais inventer. Si hippodrome hors catalogue → flag GRU_INCONNU
sans bonus/malus inventé.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional, Tuple

from app.models import Cheval, RaceContext, CatalogSignal, Discipline
from app.engine.gru_catalog import (
    get_gru_entry, resolve_distance_bin, normalize_hippo_key, GRU_CATALOG,
    effective_cote_max_utile, get_opa_observed,
)

# poids unitaires des effets numéro (plafonnés par entry)
_POIDS_VALEUR = {
    "bonus": 1.5,
    "bonus_place": 1.0,
    "bonus_leger": 0.8,
    "malus": -1.5,
    "malus_leger": -0.8,
    "neutre": 0.0,
}


def _disc_slug(d: Discipline) -> str:
    m = {
        Discipline.TROT_ATTELE: "attele",
        Discipline.TROT_MONTE: "monte",
        Discipline.PLAT: "plat",
        Discipline.HAIES: "haies",
        Discipline.STEEPLE: "steeple",
    }
    return m.get(d, "plat")


def _is_autostart(race: RaceContext) -> bool:
    dep = getattr(race, "depart", None)
    if dep is None:
        return False
    val = dep.value if hasattr(dep, "value") else str(dep)
    return "AUTO" in val.upper() or "AS" in val.upper()


def _numero_partant(cheval: Cheval) -> Optional[int]:
    n = cheval.numero_autostart if cheval.numero_autostart is not None else cheval.numero
    try:
        return int(n) if n is not None else None
    except (TypeError, ValueError):
        return None


def apply_numero_bias(
    cheval: Cheval,
    race: RaceContext,
    entry: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Optional[str], List[str]]:
    """
    Returns (delta_points, zone_label, flags).
    delta_points is raw signal value (will be capped by plafond).
    """
    if entry is None:
        entry = get_gru_entry(race.hippodrome)
    if not entry:
        return 0.0, None, []

    bias = entry.get("numero_bias") or {}
    if not bias.get("applicable"):
        return 0.0, None, []

    disc = _disc_slug(race.discipline)
    is_as = _is_autostart(race)
    dist_bin = resolve_distance_bin(entry, race.distance_m, disc) or ""
    condition = (bias.get("condition") or "").lower()

    # evaluate condition loosely
    ok = True
    if "attele" in condition and disc not in ("attele", "monte"):
        ok = False
    if "autostart" in condition and not is_as:
        ok = False
    if "plat" in condition and disc != "plat":
        ok = False
    if "distance_bin" in condition:
        # e.g. distance_bin in [sprint, mile]
        allowed = []
        if "[" in condition:
            inside = condition.split("[", 1)[1].split("]", 1)[0]
            allowed = [x.strip().strip("'\"") for x in inside.split(",")]
        if allowed and dist_bin not in allowed:
            ok = False
    if not ok:
        return 0.0, None, []

    num = _numero_partant(cheval)
    if num is None:
        return 0.0, None, []

    zones = bias.get("zones") or {}
    delta = 0.0
    zone_hit = None
    flags: List[str] = []
    for zname, zdef in zones.items():
        nums = zdef.get("numeros") or []
        if num in nums:
            effet = zdef.get("effet", "neutre")
            poids = float(zdef.get("poids", 1))
            unit = _POIDS_VALEUR.get(effet, 0.0)
            delta = unit * poids
            zone_hit = zname
            flags.append(f"GRU_NUMERO_{zname.upper()}")
            break

    plafond = float(bias.get("plafond_total_numero") or 4)
    if delta > plafond:
        delta = plafond
    elif delta < -plafond:
        delta = -plafond

    return delta, zone_hit, flags



# ======================= v1.29.64 (base v1.29.63) : renforcements GRU à POIDS MAÎTRISÉ =======================
# Les renforcements proposés pour la v1.29.64 sont portés par un PROFIL « renforcé » à poids INTERMÉDIAIRES (≈ la moitié de l'écart proposé),
# bornés et déterministes. Par défaut tout le pipeline reste au profil « neutre » (= comportement v1.29.63 : tickets A et C inchangés) ;
# le profil renforcé n'alimente que le ticket B (cf. renforcer_horses) ou, si on le décide, tout le pipeline (VANTAGE_GRU_RENFORCE=1).
# Une variable d'environnement explicite sur un paramètre l'emporte sur les deux profils (ablation d'un renforcement à la fois).
#   paramètre                         neutre   proposé   renforcé (maîtrisé)
#   VANTAGE_GRU_G10_MULT              1.00     1.25      1.12   spécialiste local
#   VANTAGE_GRU_G56_SCALE             1.00     ≈1.28     1.14   boosts outsider (sweet-spot et zone haute)
#   VANTAGE_GRU_G30_SLOPE / _CAP      1.2/.10  2.0/.15   1.6/.125 multiplicateur de numéro sur ordre_final
#   VANTAGE_GRU_PIEGE_MULT_MIN        1.00     0.88      0.94   rétrogradation favoris/seconds à piège
#   VANTAGE_GRU_POOL_PEPITE_TH        8.0      5.5/6.5   8.0    seuil d'entrée de pool (pépite) ; _POOL_MAX_ENTRIES : 0 → 2 par course
#   VANTAGE_GRU_PIEGE_SKIP_MF         99 (off) 5.0       6.0    pas d'injection « market-force » d'un favori à piège (sauf favori n°1)
#   VANTAGE_GRU_G58_65_SCALE          0 (off)  1.0       0.5    signaux G58/G59/G60/G61/G63/G64 (plafonds +2,5 / −2,0)
#   VANTAGE_GRU_G62_SCALE             0 (off)  1.0       1.0    évolution de cote (seul signal confirmé : rejeu 55 courses)
import contextvars

_PROFIL_NEUTRE = {"VANTAGE_GRU_G10_MULT": 1.0, "VANTAGE_GRU_G56_SCALE": 1.0, "VANTAGE_GRU_G30_SLOPE": 1.2, "VANTAGE_GRU_G30_CAP": 0.10,
                  "VANTAGE_GRU_PIEGE_MULT_MIN": 1.0, "VANTAGE_GRU_POOL_PEPITE_TH": 8.0, "VANTAGE_GRU_POOL_MAX_ENTRIES": 0.0,
                  "VANTAGE_GRU_PIEGE_SKIP_MF": 99.0, "VANTAGE_GRU_G58_65_SCALE": 0.0, "VANTAGE_GRU_G62_SCALE": 0.0}
_PROFIL_RENFORCE = {"VANTAGE_GRU_G10_MULT": 1.12, "VANTAGE_GRU_G56_SCALE": 1.14, "VANTAGE_GRU_G30_SLOPE": 1.6, "VANTAGE_GRU_G30_CAP": 0.125,
                    "VANTAGE_GRU_PIEGE_MULT_MIN": 0.94, "VANTAGE_GRU_POOL_PEPITE_TH": 8.0, "VANTAGE_GRU_POOL_MAX_ENTRIES": 2.0,
                    "VANTAGE_GRU_PIEGE_SKIP_MF": 6.0, "VANTAGE_GRU_G58_65_SCALE": 0.5, "VANTAGE_GRU_G62_SCALE": 1.0}
_PROFIL_COURANT: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("gru_profil", default=None)


class gru_profil:
    """Contexte : `with gru_profil("renforce"): ...` force le profil ("neutre" | "renforce") pour les appels internes."""
    def __init__(self, nom: str):
        self.nom, self._tok = nom, None
    def __enter__(self):
        self._tok = _PROFIL_COURANT.set(self.nom)
        return self
    def __exit__(self, *a):
        _PROFIL_COURANT.reset(self._tok)


def _gp(nom: str, defaut: float = 0.0) -> float:
    """Valeur d'un paramètre GRU : variable d'environnement explicite > profil du contexte > profil global (VANTAGE_GRU_RENFORCE) > défaut."""
    v = os.environ.get(nom)
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    prof = _PROFIL_COURANT.get()
    if prof is None:
        prof = "renforce" if os.environ.get("VANTAGE_GRU_RENFORCE", "0").strip().lower() in ("1", "true", "oui", "on") else "neutre"
    table = _PROFIL_RENFORCE if prof == "renforce" else _PROFIL_NEUTRE
    return float(table.get(nom, defaut))


def _specialiste_score(cheval: Cheval, hippo_key: str) -> Tuple[float, str]:
    """Heuristique spécialiste local via historique_hippodrome (si dispo)."""
    hist = cheval.historique_hippodrome or []
    if len(hist) < 2:
        return 0.0, ""
    top5 = sum(1 for h in hist if h.rang is not None and h.rang <= 5)
    wins = sum(1 for h in hist if h.rang == 1)
    n = len(hist)
    taux = top5 / n
    if taux >= 0.60 and n >= 3:
        return 7.0, f"specialiste_{hippo_key} ({top5}/{n} top5)"
    if taux >= 0.40 and n >= 2:
        return 4.0, f"bon_parcours_{hippo_key} ({top5}/{n} top5)"
    if wins >= 1 and n >= 2:
        return 2.5, f"deja_gagne_{hippo_key}"
    if n >= 2 and top5 == 0:
        return -3.0, f"faible_parcours_{hippo_key}"
    return 0.0, ""


def _distance_fit(cheval: Cheval, race: RaceContext) -> Tuple[float, str]:
    hist = getattr(cheval, "historique_distance", None) or []
    if not hist:
        return 0.0, ""
    dm = race.distance_m
    close = [h for h in hist if h.distance_m and abs(h.distance_m - dm) <= 200]
    if not close:
        far = [h for h in hist if h.distance_m and abs(h.distance_m - dm) > 400]
        if far and len(far) >= 2:
            return -2.5, "decalage_distance"
        return 0.0, ""
    top5 = sum(1 for h in close if h.rang is not None and h.rang <= 5)
    if top5 >= 2:
        return 4.0, f"specialiste_distance ({top5} top5 ±200m)"
    if top5 == 1:
        return 2.0, "apte_distance"
    return 0.0, ""


def compute_gru_signals(
    cheval: Cheval,
    race: RaceContext,
    champ: Optional[List[Cheval]] = None,
) -> List[CatalogSignal]:
    """Génère les CatalogSignal famille G pour un partant."""
    signaux: List[CatalogSignal] = []
    entry = get_gru_entry(race.hippodrome)
    hippo_key = normalize_hippo_key(race.hippodrome) or "unknown"

    def add(id_: str, valeur: float, conf: str, justif: str):
        if abs(valeur) < 0.05:
            return
        signaux.append(CatalogSignal(
            id=id_, valeur_brute=valeur, catalog="G",
            confiance=conf, justification=justif,
        ))

    def _extras():
        try:
            for id_, v, conf, why in compute_gru_extra_signals(cheval, race, entry, champ):
                add(id_, v, conf, why)
        except Exception:   # noqa: BLE001 -- un défaut des extras ne doit jamais faire échouer G01-G57
            pass

    if entry is None:
        add("G00", -1.0, "MINIMAL", f"GRU_INCONNU hippodrome={race.hippodrome}")
        _extras()               # G59 / G62 / G63 ne dépendent pas du catalogue
        return signaux

    # G01 — contexte hippodrome présent
    add("G01", 1.0, "STRICT", f"GRU actif: {hippo_key}")

    # G10 — spécialiste local
    sp_val, sp_just = _specialiste_score(cheval, hippo_key)
    if sp_val:
        sp_val = sp_val * _gp("VANTAGE_GRU_G10_MULT", 1.12)       # v1.29.64 maîtrisé (proposé 1.25)
        conf = "STRICT" if abs(sp_val) >= 6 else "DEGRADE"
        add("G10", sp_val, conf, sp_just)

    # G20 — adéquation distance
    d_val, d_just = _distance_fit(cheval, race)
    if d_val:
        add("G20", d_val, "DEGRADE", d_just)

    # G30 — numéro bias
    delta, zone, flags = apply_numero_bias(cheval, race, entry)
    if delta != 0.0 and zone:
        conf = "STRICT" if abs(delta) >= 3 else "DEGRADE"
        add("G30", delta, conf, f"numero_bias:{zone} n={_numero_partant(cheval)}")

    # G40 — ticket policy (mode densifier / mixte / elargir) + rapport_profile
    policy = entry.get("ticket_policy") or {}
    rapport = entry.get("rapport_profile") or {}
    conseil = policy.get("conseil") or policy.get("mode") or policy.get("attele") or policy.get("plat")
    width = rapport.get("ticket_width_bias") or "mixte"
    if conseil in ("densifier", "densifier_leger") or width == "serre":
        if cheval.cote_matin is not None and cheval.cote_matin <= 6.0:
            add("G40", 1.5 if conseil == "densifier" else 1.0, "MINIMAL",
                f"ticket densifier/serre + cote basse")
    if conseil in ("elargir", "mixte") or width in ("elargi", "large"):
        if cheval.cote_matin is not None and 12.0 <= cheval.cote_matin <= 35.0:
            add("G40", 1.2 if conseil == "elargir" or width == "elargi" else 0.8, "MINIMAL",
                f"ticket {conseil or width} + outsider cohérent")

    # --- selection_levers (G50–G55) ---
    levers = entry.get("selection_levers") or {}
    style = levers.get("style_dominant") or "mixte"

    # G50 — style de course vs profil cheval (heuristique musique/historique)
    musique = (getattr(cheval, "musique", None) or "").lower()
    # placement_precoce: valorise chevaux souvent devant (1,2,3 dans musique récente)
    if style == "placement_precoce":
        if any(c in musique[:6] for c in ("1", "2", "3")):
            add("G50", 2.0, "DEGRADE", "style piste=placement_precoce + musique avant")
        elif any(c in musique[:6] for c in ("0", "d", "a")):
            add("G50", -1.5, "MINIMAL", "style piste=placement_precoce + musique arrière/incident")
    elif style == "finisseur":
        if any(c in musique[:8] for c in ("1", "2", "3", "4", "5")):
            add("G50", 1.5, "DEGRADE", "style piste=finisseur + musique top5")
        # léger malus si toujours en tête pure sans finir (signal faible)

    # G51 — surface_key : spécialiste surface (PSF/gazon) si flag dispo
    if levers.get("surface_key"):
        flags_ch = getattr(cheval, "flags", None) or []
        if any("psf" in str(f).lower() or "surface" in str(f).lower() for f in flags_ch):
            add("G51", 2.5, "DEGRADE", "surface_key piste + flag spécialiste surface")
        # sinon pas de malus : donnée souvent absente

    # G52 — terrain_sensible : rappel informatif (poids nul si pas de penetro)
    if levers.get("terrain_sensible"):
        add("G52", 0.5, "MINIMAL", "terrain_sensible: vérifier pénétro/état gazon")

    # G53 — rendre_distance_ok : ne pas sur-pénaliser un cheval qui rend
    if levers.get("rendre_distance_ok"):
        recul = getattr(cheval, "recul_m", None) or getattr(cheval, "distance_handicap", None)
        if recul and float(recul) >= 25:
            add("G53", 2.0, "DEGRADE", f"rendre_distance_ok + recul {recul}m")

    # G54 — avantage_local : driver/entraîneur régional (heuristique nom/hippo)
    if levers.get("avantage_local"):
        # si le cheval a déjà top5 ici → déjà G10; sinon petit boost si driver local flag
        flags_ch = getattr(cheval, "flags", None) or []
        if any("local" in str(f).lower() or "regional" in str(f).lower() for f in flags_ch):
            add("G54", 2.0, "MINIMAL", "avantage_local + flag local")

    # G55 — autostart_critical sans numéro favorable
    if levers.get("autostart_critical") and _is_autostart(race):
        delta_as, zone_as, _ = apply_numero_bias(cheval, race, entry)
        if zone_as is None and _numero_partant(cheval) is not None:
            add("G55", -0.8, "MINIMAL", "AS critique hors zone privilégiée")


    # G57 — gaucher / droitier vs corde de la piste
    gd = levers.get("gaucher_droitier")
    if gd in ("gaucher", "droitier"):
        flags_ch = [str(f).lower() for f in (getattr(cheval, "flags", None) or [])]
        # flags possibles: gaucher, droitier, corde_gauche, corde_droite
        match = any(gd in f or (gd == "gaucher" and "gauche" in f) or (gd == "droitier" and "droite" in f) for f in flags_ch)
        mismatch = any(
            (gd == "gaucher" and ("droitier" in f or "droite" in f)) or
            (gd == "droitier" and ("gaucher" in f or "gauche" in f))
            for f in flags_ch
        )
        if match:
            add("G57", 1.5, "MINIMAL", f"corde piste={gd} + flag cheval aligné")
        elif mismatch:
            add("G57", -1.0, "MINIMAL", f"corde piste={gd} vs flag cheval opposé")

    # G56 — outsider / longshot / extreme longshot
    # Evidence resultat-quinte Vincennes (2091 Q+):
    #   1er max 44 | 3e max 72 | 4e max 108 | 5e max 68
    #   Examples: 17/09/26 4e@108 5e@35; 24/08 3e@72; 19/06 5e@68
    # iturf: 30+ still 12-14% in Quinté → NEVER hard-malus pure high cote
    op = entry.get("outsider_profile") or {}
    cote = cheval.cote_matin
    if cote is not None and op:
        sweet = op.get("cote_sweet_spot") or [12, 22]
        hippo_k = normalize_hippo_key(race.hippodrome) or ""
        cmax = effective_cote_max_utile(entry, hippo_k)
        weight = op.get("outsider_weight") or "medium"
        extreme_ok = op.get("extreme_longshot_ok", True)
        lo, hi = float(sweet[0]), float(sweet[1])
        if lo <= cote <= hi:
            boost = {"high": 2.5, "medium": 1.8, "low": 1.0}.get(weight, 1.2) * _gp("VANTAGE_GRU_G56_SCALE", 1.14)
            add("G56", round(boost, 2), "DEGRADE",
                f"outsider sweet-spot cote={cote:.1f} [{lo}-{hi}] weight={weight}")
        elif hi < cote <= 35:
            boost = {"high": 1.5, "medium": 1.0, "low": 0.5}.get(weight, 0.8) * _gp("VANTAGE_GRU_G56_SCALE", 1.14)
            add("G56", round(boost, 2), "MINIMAL",
                f"outsider haut cote={cote:.1f} (souvent 4e/5e)")
        elif 35 < cote <= cmax and extreme_ok:
            # Extreme longshot: observed in top5 (4e/5e). Scale by hippo openness + disc.
            base = {"high": 1.2, "medium": 0.6, "low": 0.2}.get(weight, 0.4)
            be = float(op.get("boost_extreme") or 1.0)
            # multiplicateur discipline (dict) + ouverture hippo
            disc_map = op.get("discipline_bias") if isinstance(op.get("discipline_bias"), dict) else {}
            disc_key = None
            try:
                dval = getattr(race.discipline, "value", None) or str(race.discipline or "")
                dval = dval.lower().replace("é", "e")
                for k, v in disc_map.items():
                    if k in dval or dval in k:
                        disc_key = k
                        break
                disc_mult = float(disc_map.get(disc_key, 1.0)) if disc_key else 1.0
            except Exception:
                disc_mult = 1.0
            open_mult = {"tres_ouvert": 1.25, "ouvert": 1.1, "serre": 0.9, "moyen": 1.0}.get(
                op.get("hippo_openness") or "moyen", 1.0)
            boost = round(base * be * disc_mult * open_mult, 2)
            add("G56", boost, "MINIMAL",
                f"extreme longshot cote={cote:.1f} ≤{cmax} open={op.get('hippo_openness')} disc={disc_key or '-'}")
        elif cote > cmax:
            # Beyond observed useful range: neutral (0), not hard malus
            add("G56", 0.0, "MINIMAL",
                f"tocard extrême cote={cote:.1f} >{cmax} (neutre, pas malus)")

    _extras()                   # v1.29.64 : G58-G64 à poids maîtrisé
    return signaux


def gru_ticket_policy(race: RaceContext) -> Dict[str, Any]:
    """Expose la politique ticket + leviers sélection pour l'orchestrateur / GMO-V."""
    entry = get_gru_entry(race.hippodrome)
    if not entry:
        return {"conseil": "neutre", "gru_key": None, "favori_taux_gagne": None}
    disc = _disc_slug(race.discipline)
    policy = dict(entry.get("ticket_policy") or {})
    if disc in policy:
        policy["conseil"] = policy[disc]
    dist_bin = resolve_distance_bin(entry, race.distance_m, disc)
    stats = entry.get("stats_corpus") or {}
    levers = entry.get("selection_levers") or {}
    rapport = entry.get("rapport_profile") or {}
    outsider = entry.get("outsider_profile") or {}
    # harmonise ticket_width avec conseil
    width = rapport.get("ticket_width_bias") or "normal"
    conseil = policy.get("conseil", "neutre")
    if width == "large" and conseil in ("densifier", "densifier_leger"):
        conseil = "mixte"  # large override densifier
    elif width == "serre" and conseil == "elargir":
        conseil = "mixte"
    return {
        "conseil": conseil,
        "profil_rapport": policy.get("profil_rapport") or rapport.get("median_desordre"),
        "ticket_width_bias": width,
        "favori_fiable": rapport.get("favori_fiable"),
        "median_desordre": rapport.get("median_desordre"),
        "hippodrome_key": normalize_hippo_key(race.hippodrome),
        "distance_bin": dist_bin,
        "favori_taux_gagne": stats.get("favori_taux_gagne"),
        "favori_taux_place": stats.get("favori_taux_place"),
        "nb_favoris_corpus": stats.get("nb_favoris_corpus"),
        "corde": entry.get("corde"),
        "numero_bias_applicable": bool((entry.get("numero_bias") or {}).get("applicable")),
        "style_dominant": levers.get("style_dominant"),
        "surface_key": levers.get("surface_key"),
        "terrain_sensible": levers.get("terrain_sensible"),
        "rendre_distance_ok": levers.get("rendre_distance_ok"),
        "avantage_local": levers.get("avantage_local"),
        "autostart_critical": levers.get("autostart_critical"),
        "gaucher_droitier": levers.get("gaucher_droitier"),
        "notes_selection": levers.get("notes"),
        "outsider_weight": outsider.get("outsider_weight"),
        "longshot_viable": outsider.get("longshot_viable"),
        "cote_sweet_spot": outsider.get("cote_sweet_spot"),
        "cote_max_utile": outsider.get("cote_max_utile"),
        "extreme_longshot_ok": outsider.get("extreme_longshot_ok"),
        "extreme_range": outsider.get("extreme_range"),
        "hippo_openness": outsider.get("hippo_openness"),
        "discipline_bias": outsider.get("discipline_bias"),
        "boost_extreme": outsider.get("boost_extreme"),
        "by_discipline": outsider.get("by_discipline"),
        "notes_outsider": outsider.get("notes"),
    }


def ordre_final_gru_numero(
    ordre_base: float,
    race: RaceContext,
    cheval: Cheval,
) -> float:
    """
    Remplace / généralise ordre_final_malus_enghien.
    Applique un multiplicateur borné selon le delta G30.
    """
    delta, zone, _ = apply_numero_bias(cheval, race)
    if delta == 0.0:
        return ordre_base
    # delta typique ±2..6 → mult ±3%..8%
    mult = 1.0 + (delta / 100.0) * _gp("VANTAGE_GRU_G30_SLOPE", 1.6)           # v1.29.64 maîtrisé (avant 1.2 ; proposé 2.0)
    cap = _gp("VANTAGE_GRU_G30_CAP", 0.125)                                     # avant 0.10 ; proposé 0.15
    mult = max(1.0 - cap, min(1.0 + cap, mult))
    return ordre_base * mult


def sum_gru_bonus(signaux: List[CatalogSignal]) -> float:
    """Somme plafonnée des signaux G pour injection PCH / composite."""
    total = sum(s.valeur_brute for s in signaux if s.catalog == "G")
    return max(-12.0, min(12.0, total))


def compute_gru_pepite(cheval: Cheval, race: RaceContext, entry: dict | None = None) -> tuple[float, list]:
    """Priorité 5 — activation pépite GRU assouplie (outsider viable hippo).

    Avant : souvent 0 (seuils trop durs / data absente).
    Maintenant : score 0–8 PCH si plusieurs critères soft sont réunis.
    """
    flags: list = []
    cote = cheval.cote_avant_course if cheval.cote_avant_course is not None else cheval.cote_matin
    try:
        cote_f = float(cote) if cote is not None else None
    except (TypeError, ValueError):
        cote_f = None
    if cote_f is None or cote_f < 12.0:
        return 0.0, ["GRU_PEPITE_SKIP_COTE"]

    score = 0.0
    # Forme récente (musique)
    try:
        from app.scraping.musique import parse_musique
        perfs = parse_musique(cheval.musique or "")[:5]
        tops = sum(1 for p in perfs if getattr(p, "rang", None) and p.rang <= 5)
        if tops >= 2:
            score += 3.0
            flags.append("GRU_PEPITE_FORME_2TOP5")
        elif tops >= 1:
            score += 1.5
            flags.append("GRU_PEPITE_FORME_1TOP5")
    except Exception:
        pass

    # Catalogue outsider_profile (clés string high|medium|low — pas un float)
    if entry:
        op = entry.get("outsider_profile") or entry.get("outsider") or {}
        if not isinstance(op, dict):
            op = {}
        ow = op.get("outsider_weight") or entry.get("outsider_weight")
        lv = op.get("longshot_viable")
        if lv is None:
            lv = entry.get("longshot_viable")
        # weight → points
        _OW_PTS = {"high": 2.5, "medium": 1.5, "low": 0.5}
        if isinstance(ow, str) and ow.lower() in _OW_PTS:
            score += _OW_PTS[ow.lower()]
            flags.append(f"GRU_PEPITE_OUTSIDER_WEIGHT_{ow.upper()}")
        else:
            try:
                if ow is not None and float(ow) >= 0.55:
                    score += 2.0
                    flags.append("GRU_PEPITE_OUTSIDER_WEIGHT")
            except (TypeError, ValueError):
                pass
        if lv:
            score += 1.5
            flags.append("GRU_PEPITE_LONGSHOT_VIABLE")
        # Sweet spot catalogue (prioritaire sur bornes génériques)
        sweet = op.get("cote_sweet_spot") or entry.get("cote_sweet_spot")
        if isinstance(sweet, (list, tuple)) and len(sweet) >= 2:
            try:
                lo, hi = float(sweet[0]), float(sweet[1])
                if lo <= cote_f <= hi:
                    score += 1.5
                    flags.append(f"GRU_PEPITE_SWEET_CATALOG_{lo:.0f}_{hi:.0f}")
                elif hi < cote_f <= hi * 1.5:
                    score += 0.75
                    flags.append("GRU_PEPITE_SWEET_HAUT")
            except (TypeError, ValueError):
                pass
        elif 15.0 <= cote_f <= 40.0:
            score += 1.0
            flags.append("GRU_PEPITE_COTE_SWEET")
        elif cote_f > 40.0:
            score += 0.5
    else:
        if 15.0 <= cote_f <= 40.0:
            score += 1.0
            flags.append("GRU_PEPITE_COTE_SWEET")
        elif cote_f > 40.0:
            score += 0.5

    # Affinity hippo (historique)
    hip = (race.hippodrome or "").upper()
    hist = getattr(cheval, "historique_hippodrome", None) or []
    if hist and hip:
        local = sum(1 for h in hist if getattr(h, "rang", None) and h.rang <= 5)
        if local >= 1:
            score += 2.0
            flags.append("GRU_PEPITE_HIPPO_TOP5")

    score = max(0.0, min(8.0, score))
    if score >= 4.0:
        flags.append("GRU_PEPITE_ACTIF")
    elif score >= 2.5:
        flags.append("GRU_PEPITE_FAIBLE")
    else:
        score = 0.0
        flags.append("GRU_PEPITE_SOUS_SEUIL")
    # v1.29.63 : plafond configurable. Rejeu 55 courses : 74 % des outsiders (cote ≥ 12) atteignent 6-9 points → la pépite ne discrimine plus
    # (arrivée 23,6 % contre 21 % pour l'ensemble des outsiders). Plafond 3 : +0,07 de capture (3 courses meilleures / 0 pire) ; retirer
    # la pépite : +0,09 (6 / 2). CANDIDAT : VANTAGE_PEPITE_PLAFOND (défaut 8 = inchangé).
    try:
        plafond = float(os.environ.get("VANTAGE_PEPITE_PLAFOND", "8"))
    except ValueError:
        plafond = 8.0
    if plafond < 8.0:
        score = min(score, max(0.0, plafond))
    return score, flags


def compute_gru_piege(cheval: Cheval, race: RaceContext, entry: dict | None = None) -> tuple[float, list]:
    """Score piège GRU (négatif) — zones numero_bias malus + AS critique hors zone.

    Retourne un score ≤ 0 (typiquement −0 à −8) pour injection PCH.
    """
    flags: list = []
    if entry is None:
        try:
            entry = get_gru_entry(getattr(race, "hippodrome", None) or "")
        except Exception:
            entry = None
    if not entry:
        return 0.0, ["GRU_PIEGE_NO_ENTRY"]

    score = 0.0  # accumule négatif
    # Bias numéro (zones malus du catalogue)
    try:
        delta, zone, _ = apply_numero_bias(cheval, race, entry)
        if delta < 0:
            # delta typique −1..−6 → piège PCH
            score += max(-6.0, float(delta) * 1.2)
            flags.append(f"GRU_PIEGE_NUMERO_{zone or 'zone'}")
    except Exception:
        pass

    # Autostart critique hors zone privilégiée
    levers = entry.get("selection_levers") or {}
    if levers.get("autostart_critical") and _is_autostart(race):
        try:
            delta_as, zone_as, _ = apply_numero_bias(cheval, race, entry)
            if zone_as is None and _numero_partant(cheval) is not None:
                score -= 2.0
                flags.append("GRU_PIEGE_AS_CRITIQUE")
        except Exception:
            pass

    # Favori fiable = piège de sous-élargir (signal course, pas cheval) — skip par cheval

    # Rapport: hippo favori_fiable False + cheval ultra-favori cote → léger
    # (évite de sur-jouer le favori sur hippo ouvert)
    try:
        rp = entry.get("rapport_profile") or {}
        cote = cheval.cote_avant_course if cheval.cote_avant_course is not None else cheval.cote_matin
        if rp.get("favori_fiable") is False and cote is not None and float(cote) < 4.0:
            score -= 1.0
            flags.append("GRU_PIEGE_FAVORI_HIPPO_OUVERT")
    except (TypeError, ValueError):
        pass

    score = max(-8.0, min(0.0, score))
    if score <= -3.0:
        flags.append("GRU_PIEGE_ACTIF")
    elif score < -0.05:
        flags.append("GRU_PIEGE_LEGER")
    else:
        flags.append("GRU_PIEGE_NEUTRE")
        score = 0.0
    return score, flags


# ----------------------------------------------------------------------------------------------------------------------
# v1.29.64 (base v1.29.63) : signaux G58–G64 à poids maîtrisé, rétrogradation des pièges, aides pour le pool GMO-V
# ----------------------------------------------------------------------------------------------------------------------
_G_EXTRA_CAP_BONUS = 2.5        # somme des bonus G58-G64 par cheval
_G_EXTRA_CAP_MALUS = -2.0       # somme des malus G58-G64 par cheval


def _disc_str(race: RaceContext) -> str:
    d = getattr(race, "discipline", None)
    return (getattr(d, "value", None) or str(d or "")).upper()


def _norm_nom(x: Optional[str]) -> str:
    return " ".join(sorted(str(x or "").upper().replace(".", " ").replace("-", " ").split()))


def compute_gru_extra_signals(cheval: Cheval, race: RaceContext, entry: Optional[Dict[str, Any]] = None,
                              champ: Optional[List[Cheval]] = None) -> List[Tuple[str, float, str, str]]:
    """G58 ferrure (trot), G59 récence, G60 driver, G61 synergie piste+distance, G62 évolution de cote, G63 poids relatif, G64 âge/sexe.
    Retourne [(id, valeur, confiance, justification)] déjà pondérée (poids maîtrisé) et plafonnée (+2,5 / −2,0). G65 (avis entraîneur) :
    donnée non collectée → absent. Données manquantes → aucun signal (jamais de valeur inventée)."""
    sc = _gp("VANTAGE_GRU_G58_65_SCALE", 0.5)
    sc62 = _gp("VANTAGE_GRU_G62_SCALE", 1.0)
    out: List[Tuple[str, float, str, str]] = []
    disc = _disc_str(race)
    trot = "TROT" in disc
    obstacle = any(k in disc for k in ("HAIES", "STEEPLE", "CROSS"))
    cote = cheval.cote_avant_course if cheval.cote_avant_course is not None else cheval.cote_matin
    fav = cote is not None and cote < 6.0
    longshot = cote is not None and cote > 80.0

    def push(id_: str, v: float, conf: str, why: str, poids: float = None, famille_bonus: bool = False):
        w = sc if poids is None else poids
        v = v * w
        if famille_bonus and v > 0:
            if fav:
                v *= 0.60                       # favori : bonus réduits de 40 % (déjà fort)
            elif longshot:
                v *= 1.30                       # extreme longshot : détection de pépites
        if abs(v) >= 0.05:
            out.append((id_, round(v, 2), conf, why))

    # G58 — ferrure (trot) : D4 actuel (la 1re D4 / la perte de D4 exigent l'historique de ferrure, non collecté)
    if trot and cote is not None:
        ft = str(getattr(cheval, "deferre", None) or getattr(cheval, "ferrure_type", None) or "").upper()
        if ft.startswith("D4"):
            v = 0.6 if cote >= 12.0 else (0.3 if cote >= 8.0 else 0.0)
            if v:
                push("G58", min(v, 1.2), "MINIMAL", f"D4 actuel (cote {cote:.0f})", famille_bonus=True)

    # G59 — récence / intervalle
    d = getattr(cheval, "delai_j", None)
    if d is not None:
        lo, hi, court = ((8, 28, 7) if trot else (14, 35, 10) if obstacle else (7, 21, 5))
        if lo <= d <= hi:
            tops = sum(1 for c in (getattr(cheval, "musique", None) or "")[:10] if c in "12345")
            push("G59", 0.9 if tops >= 3 else 0.5, "MINIMAL", f"récence idéale {d} j (fenêtre {lo}-{hi})")
        elif d < court:
            push("G59", -0.8 if fav else -0.4, "MINIMAL", f"intervalle trop court {d} j (< {court})")

    # G60 — driver : changement vers un driver en forme / duo habituel
    dj, dp = _norm_nom(getattr(cheval, "driver_jockey", None)), _norm_nom(getattr(cheval, "driver_precedent", None))
    changement = bool(dj and dp and dj != dp)
    ds = getattr(cheval, "driver_stats", None)
    taux30 = None
    if ds is not None:
        for w_ in (getattr(ds, "fenetres", None) or []):
            if getattr(w_, "jours", None) == 30 and (w_.courses or 0) >= 8:
                taux30 = w_.victoires / w_.courses
    if changement and taux30 is not None:
        if taux30 >= 0.15:
            push("G60", 0.8, "MINIMAL", f"changement de driver vers forme 30 j {taux30:.0%}", famille_bonus=True)
        elif taux30 < 0.05:
            push("G60", -0.6, "MINIMAL", f"changement de driver vers forme 30 j {taux30:.0%}")
    tdc = getattr(cheval, "tandem_driver_cheval", None)
    if tdc is not None and not changement and (getattr(tdc, "courses_ensemble", 0) or 0) >= 10:
        push("G60", 0.6, "MINIMAL", f"duo habituel ({tdc.courses_ensemble} courses ensemble)", famille_bonus=True)

    # G61 — synergie piste + distance (spécialiste local ET adéquation distance) : poids réduit, pour limiter le double comptage avec G10 / G20
    try:
        hippo_key = normalize_hippo_key(race.hippodrome) or ""
        sp, _ = _specialiste_score(cheval, hippo_key)
        dv, _ = _distance_fit(cheval, race)
        if sp >= 4.0 and dv > 0:
            push("G61", 0.8, "MINIMAL", "spécialiste local + distance adaptée", poids=sc * 0.6, famille_bonus=True)
    except Exception:
        pass

    # G62 — évolution de cote matin → départ : seule règle confirmée hors échantillon (rejeu 55 courses : hausse ≥ 30 % = 13 % d'arrivée)
    cm, cd = cheval.cote_matin, cheval.cote_avant_course
    if cm and cd and cm > 0 and cd > 0:
        r = cd / cm
        if r <= 0.75:
            push("G62", 0.5, "MINIMAL", f"cote en baisse {r - 1:+.0%}", poids=sc62)
        elif r >= 1.30:
            push("G62", -0.6 if fav else -0.4, "MINIMAL", f"cote en hausse {r - 1:+.0%} (manque de soutien)", poids=sc62)

    # G63 — poids relatif (handicap, plat / obstacle)
    pw = getattr(cheval, "poids_actuel_kg", None)
    handicap = getattr(getattr(race, "type_course", None), "value", "") == "HANDICAP"
    if pw is not None and handicap and not trot and champ:
        poids = [c.poids_actuel_kg for c in champ if getattr(c, "poids_actuel_kg", None) is not None]
        if len(poids) >= 5:
            moy, mx = sum(poids) / len(poids), max(poids)
            if pw <= moy - 2.0:
                push("G63", 0.4, "MINIMAL", f"poids {pw:.1f} kg bien placé (moy {moy:.1f})")
            elif fav and pw >= mx and mx - moy >= 3.0:
                push("G63", -0.4, "MINIMAL", f"favori au poids maximal {pw:.1f} kg")

    # G64 — âge × sexe × distance
    sx, ag, dm = str(getattr(cheval, "sexe", None) or "").upper()[:1], getattr(cheval, "age", None), race.distance_m
    hk = normalize_hippo_key(race.hippodrome) or ""
    if trot and sx == "F" and ag is not None and 5 <= ag <= 7 and 2100 <= dm <= 2700 and hk in ("vincennes", "enghien"):
        push("G64", 0.3, "MINIMAL", "jument 5-7 ans, distance moyenne Vincennes/Enghien")
    elif sx == "H" and ag is not None and ag > 9 and dm >= (2700 if trot else 2400):
        push("G64", -0.3, "MINIMAL", f"hongre {ag} ans sur longue distance")

    # plafonds de somme (G62 exclu du plafond : déjà borné à ±0,6)
    pos = sum(v for i, v, _, _ in out if v > 0 and i != "G62")
    neg = sum(v for i, v, _, _ in out if v < 0 and i != "G62")
    kp = min(1.0, _G_EXTRA_CAP_BONUS / pos) if pos > 0 else 1.0
    kn = min(1.0, abs(_G_EXTRA_CAP_MALUS) / abs(neg)) if neg < 0 else 1.0
    return [(i, round(v * (kp if v > 0 else kn), 2) if i != "G62" else v, c, w) for i, v, c, w in out]


def apply_gru_piege_mult(ordre_final: float, gru_piege_score: float, cote: Optional[float]) -> float:
    """Rétrograde (jamais de boost) les favoris (cote < 6) et seconds (6-10) à piège GRU ≥ 3. Multiplicateur dans [VANTAGE_GRU_PIEGE_MULT_MIN, 1]
    (défaut 0,94 ; proposé 0,88). Proportionnel : la pénalité maximale proposée (12 %) est ramenée à (1 − MIN)."""
    mn = _gp("VANTAGE_GRU_PIEGE_MULT_MIN", 0.94)
    piege = abs(float(gru_piege_score or 0.0))
    if mn >= 1.0 or piege < 3.0 or cote is None or cote >= 10.0:
        return ordre_final
    pen = min(0.12, 0.02 + (piege - 3.0) * 0.012) * ((1.0 - mn) / 0.12)
    if cote >= 6.0:
        pen *= 0.6
    return ordre_final * max(mn, 1.0 - pen)


def gru_pepite_score_of(h: Any) -> float:
    """Pépite GRU (≥ 0) d'un HorseScore, lue dans le breakdown (déjà calculée par pch_final)."""
    try:
        return max(0.0, float(getattr(h.breakdown, "gru_pepite_piege_pch", 0.0) or 0.0))
    except Exception:
        return 0.0


def gru_piege_score_of(h: Any) -> float:
    """Piège GRU (≥ 0, magnitude) d'un HorseScore."""
    try:
        return max(0.0, -float(getattr(h.breakdown, "gru_pepite_piege_pch", 0.0) or 0.0))
    except Exception:
        return 0.0


def delta_pch_gru_renforce(h: Any, race: RaceContext, champ: List[Cheval]) -> float:
    """Variation de PCH apportée par le profil GRU « renforcé » par rapport au profil « neutre » (= pipeline v1.29.63), pour UN cheval.
    Les signaux G ne portent pas de famille (pas de décote) : la variation est la différence des sommes bonus/malus finales par tranche
    (bonus × multiplicateur de tranche, malus atténués en T3/T4, plafond de malus). Bornée à ±6 points de PCH."""
    from app.engine.tranches import sommer_bonus_malus
    tr = getattr(getattr(h, "synthesis", None), "tranche", None)
    with gru_profil("neutre"):
        g0 = compute_gru_signals(h.cheval, race, champ)
    with gru_profil("renforce"):
        g1 = compute_gru_signals(h.cheval, race, champ)

    def tot(g):
        r = sommer_bonus_malus(g, tr)
        return r["bonus_final"] + r["malus_final"]
    return max(-6.0, min(6.0, tot(g1) - tot(g0)))


def _envf(nom: str, defaut: float) -> float:
    try:
        return float(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return float(defaut)


def renforcer_horses(horses: List[Any], race: RaceContext, biais_corde: Optional[Dict[int, float]] = None,
                     reglages: Optional[Dict[str, Any]] = None) -> Tuple[List[Any], Dict[str, Any]]:
    """Univers du TICKET B : copies légères des HorseScore portant `ajust_rang` (en rangs ; positif = mieux classé), somme bornée ±6 de six
    composantes, chacune convertie en rangs par un poids réglable. Les HorseScore d'origine et les tickets A et C ne sont JAMAIS modifiés.
      gru          Δ de PCH du profil GRU « renforcé » (G10, G56, G58-G64…)                       × VANTAGE_B_GRU_RANGS         (2,0 rang / point)
      classements  points B11 + B12 déjà calculés par le pipeline (plafond 8), poids supplémentaire × VANTAGE_B_CLASSEMENTS_RANGS (0,5)
      pepite       −(pépite − plafond 3) : la pépite est saturée (74 % des outsiders à 6-9)         × VANTAGE_B_PEPITE_RANGS      (0,3)
      piege        −(1 − multiplicateur de piège renforcé)                                          × VANTAGE_B_PIEGE_RANGS       (50)
      g30          écart renforcé − neutre du multiplicateur de numéro (ordre_final)                × VANTAGE_B_G30_RANGS         (10)
      corde        bonus de corde empirique V2 (si le corpus donne un biais)                        × VANTAGE_B_CORDE_RANGS       (1,0)
    Retourne (proxys, statistiques). Poids validés au rejeu 55 courses pour gru / pepite / piege (capture 4,02-4,04, non dégradée)."""
    import types
    from app.engine.ticket_quotas import _cote_ref
    if reglages is None:                # réglages par portée (famille > distance > hippodrome) ; env explicite prioritaire
        from app.engine.gru_catalog import reglages_b_pour
        reglages = reglages_b_pour(race)["valeurs"]
    r_gru, r_cl = float(reglages["rangs_gru"]), float(reglages["rangs_classements"])
    r_pep, cap_pep = float(reglages["rangs_pepite"]), float(reglages["plafond_pepite"])
    r_pie, r_g30, r_cor = float(reglages["rangs_piege"]), float(reglages["rangs_g30"]), float(reglages["rangs_corde"])
    champ = [h.cheval for h in horses]
    proxys: List[Any] = []
    cnt = {k: 0 for k in ("gru", "classements", "pepite", "piege", "g30", "corde")}
    par_cheval: Dict[int, Dict[str, float]] = {}
    delta_max = 0.0
    for h in horses:
        comp: Dict[str, float] = {}
        net = float(getattr(h.breakdown, "gru_pepite_piege_pch", 0.0) or 0.0)
        cote = _cote_ref(h)
        try:
            d = delta_pch_gru_renforce(h, race, champ)
            delta_max = max(delta_max, abs(d))
            comp["gru"] = d * r_gru
        except Exception:                                                   # noqa: BLE001
            pass
        try:
            pts = sum(max(0.0, float(s.get("valeur_brute", 0.0))) for s in (getattr(h.breakdown, "signaux_actifs", None) or [])
                      if isinstance(s, dict) and s.get("id") in ("B11", "B12"))
            comp["classements"] = min(pts, 8.0) * r_cl
        except Exception:                                                   # noqa: BLE001
            pass
        comp["pepite"] = -max(0.0, net - cap_pep) * r_pep if net > 0 else 0.0
        try:
            with gru_profil("renforce"):
                m = apply_gru_piege_mult(1.0, max(0.0, -net), cote)
            comp["piege"] = -(1.0 - m) * r_pie
        except Exception:                                                   # noqa: BLE001
            pass
        try:
            with gru_profil("renforce"):
                mr = ordre_final_gru_numero(1.0, race, h.cheval)
            with gru_profil("neutre"):
                mn = ordre_final_gru_numero(1.0, race, h.cheval)
            comp["g30"] = (mr - mn) * r_g30
        except Exception:                                                   # noqa: BLE001
            pass
        if biais_corde:
            try:
                from app.engine.pmu_corpus_analyse import bonus_corde_empirique
                comp["corde"] = bonus_corde_empirique(h.cheval, race, biais_corde)[0] * r_cor
            except Exception:                                               # noqa: BLE001
                pass
        for k, v in comp.items():
            if abs(v) >= 0.05:
                cnt[k] += 1
        total = max(-6.0, min(6.0, sum(comp.values())))
        pch = float(getattr(h.breakdown, "pch_final", 0.0) or 0.0)
        proxys.append(types.SimpleNamespace(cheval=h.cheval, synthesis=h.synthesis, breakdown=types.SimpleNamespace(pch_final=pch),
                                            ajust_rang=total, pepite=max(0.0, net), lab={k: round(v, 2) for k, v in comp.items() if abs(v) >= 0.05}))
        if abs(total) >= 0.05:
            par_cheval[int(h.cheval.numero)] = {k: round(v, 2) for k, v in comp.items() if abs(v) >= 0.05}
    aj = [abs(p.ajust_rang) for p in proxys]
    return proxys, {"rangs_par_point": r_gru, "chevaux_modifies": sum(1 for a in aj if a >= 0.05), "delta_max_abs": round(delta_max, 2),
                    "ajust_moyen_abs": round(sum(aj) / max(1, len(aj)), 3), "ajust_max_abs": round(max(aj, default=0.0), 2),
                    "composantes_chevaux_touches": cnt, "par_cheval": par_cheval}
