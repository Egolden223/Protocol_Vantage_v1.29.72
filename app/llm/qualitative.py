"""
qualitative.py -- Couche LLM pour tout ce qui exige une lecture de texte
libre / jugement qualitatif plutôt qu'une formule numérique :
  - Catalogues B01-B56 / M01-M43 (Partie 4.1/4.2) + décote/tranche gérée
    ensuite par engine/tranches.py
  - GRU PÉPITE/PIÈGE spécifiques à l'hippodrome (Partie 5)
  - SSFO (32 signaux, RAH-271), GAMMA (RAH-179-209, cap +8)
  - FORME_LINEAIRE (B58/RAH-309), D46-D22, D02-B59, M48-B42, D45, RAH-186,
    M33, RAH-200 (Bloc 5 items 17-29)
  - SUPRA (7 phases, Bloc 7bis) et Longshot Hunter (Partie 17.4)
  - CSF (SF-01 à SF-24) et composantes du tocard_score (Bloc 7)

Une seule requête par course (tous les partants ensemble) pour permettre
les comparaisons inter-chevaux (H2H, convergence, omission SUPRA) et
limiter le nombre d'appels API.
"""
from __future__ import annotations
from typing import List, Dict
import logging

from app.models import CatalogSignal, Cheval, RaceContext, QualitativeSignals
from app import config

logger = logging.getLogger("vantage.llm.qualitative")


def _read(name: str, limit: int = None) -> str:
    try:
        txt = (config.PROTOCOL_ASSETS_DIR / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return txt[:limit] if limit else txt


def protocol_assets_available() -> bool:
    return bool(_read("partie4_catalogues.txt", 50))


# --- Mode « texte libre » (sans les textes du protocole) ------------------------------------
# Le LLM ne choisit PAS de valeur : il indique seulement quels signaux sont activés par le texte
# (commentaire de la dernière course, presse) avec la phrase qui le justifie ; les points sont fixés
# ici, en code (bornés). Aucun ID du catalogue B/M n'est inventé : espace dédié « AI01..AI06 ».
SIGNAUX_IA_TEXTE = {
    "AI01": ("EXCUSE_DERNIERE_COURSE", +4.0, "Dernière course expliquée par un incident de parcours (gêné, barré, mal placé, malchance)."),
    "AI02": ("PROGRESSION_ANNONCEE", +3.0, "Le texte annonce une amélioration (retour de forme, matériel changé, rentrée attendue)."),
    "AI03": ("FINISH_FORT", +3.0, "A bien fini / terminé en trombe / manque de piste ou de distance."),
    "AI04": ("SIGNE_DE_FAIBLESSE", -4.0, "Signe physique ou de condition négatif (s'est éteint, boiterie, arrêté, souffle)."),
    "AI05": ("COMPORTEMENT_RISQUE", -3.0, "Comportement à risque (indocile, refus, a pris le mors, faute d'allure répétée)."),
    "AI06": ("CONTRE_PERF_EXPLIQUEE", +3.0, "Contre-performance attribuée au terrain ou à la distance, non reproductible ici."),
}


def build_system_prompt_texte_libre(race: RaceContext) -> str:
    regles = "\n".join(f"- {k} ({v[0]}) : {v[2]}" for k, v in SIGNAUX_IA_TEXTE.items())
    return f"""Tu lis des commentaires de courses hippiques (course {race.hippodrome}, {race.discipline.value}, {race.distance_m} m).
Pour CHAQUE cheval, indique quels signaux ci-dessous sont ACTIVÉS par son texte (commentaire de sa dernière
course). N'active un signal que si le texte le dit explicitement ; sinon liste vide. Ne devine rien, n'utilise
aucune autre information que le texte fourni. Cite la phrase du texte qui justifie chaque signal (max 120 car.).

SIGNAUX AUTORISÉS (aucun autre) :
{regles}

SORTIE (JSON strict, clé = numéro du cheval en chaîne) :
{{"1": {{"signaux": [{{"id": "AI01", "preuve": "…phrase du texte…"}}], "flags": []}}, "2": {{"signaux": []}}}}
Ne retourne QUE ce JSON."""


def _extract_gru_fiche(hippodrome: str) -> str:
    full = _read("partie5_gru.txt")
    lines = full.splitlines()
    name_upper = hippodrome.upper()
    hits = [i for i, l in enumerate(lines) if name_upper in l.upper()]
    if len(hits) < 3:
        # fiche non trouvée précisément -> renvoyer un extrait des règles
        # transversales (début du document) + signaler l'absence
        return "\n".join(lines[:400]) + f"\n\n[NOTE: aucune fiche spécifique trouvée pour '{hippodrome}' -- " \
                                          f"traiter comme GRU_INCONNU, appliquer uniquement les règles transversales]"
    start = max(0, min(hits) - 30)
    end = min(len(lines), max(hits) + 150)
    return "\n".join(lines[start:end])


def build_system_prompt(race: RaceContext) -> str:
    catalogues = _read("partie4_catalogues.txt")
    supra_longshot = _read("partie17_supra_longshot_gmo.txt")
    gru_fiche = _extract_gru_fiche(race.hippodrome)
    rah = _read("partie7_rah.txt", limit=20000)

    return f"""Tu exécutes les modules QUALITATIFS de PROTOCOL VANTAGE v1.22.2-test
pour la course {race.hippodrome} ({race.discipline.value}, {race.distance_m}m,
{race.type_course.value}). Tu disposes ci-dessous du texte ORIGINAL et FAISANT
FOI du protocole pour ces modules -- applique-le à la lettre, ne réinvente
aucune règle, cite l'ID du signal (ex "B04", "M17", "RAH-186") pour chaque
activation.

=== PARTIE 4 -- CATALOGUES B01-B56 / M01-M43 (signaux faibles SF, Ghost D) ===
{catalogues}

=== PARTIE 17 -- SUPRA, LONGSHOT HUNTER, GMO-V, GAMMA (RAH-179-209), SSFO ===
{supra_longshot}

=== PARTIE 7 -- REGISTRE RAH (référence) ===
{rah}

=== PARTIE 5 -- FICHE GRU HIPPODROME ({race.hippodrome}) ===
{gru_fiche}

MISSION : pour CHAQUE cheval du champ fourni (identité, cotes, musique,
commentaire de dernière course, stats driver/entraîneur, historique), détermine :

1. `signaux_catalogue` : la liste des signaux B01-B56/M01-M43/GRU PÉPITE-PIÈGE/
   SSFO/RAH-179-209(GAMMA) ACTIFS, chacun avec : id, valeur_brute (valeur PCH de
   référence AVANT décote de famille et AVANT BONUS_TRANCHE_MULT/MALUS_TRANCHE_MULT
   -- ces deux étapes sont appliquées ensuite par le moteur Python, ne les
   applique PAS toi-même), catalog ("B" ou "M"), famille (C|L|F|M|P selon
   Partie 1.5, ou null), is_gamma (true si RAH-179 à RAH-209), confiance
   (STRICT|DEGRADE|MINIMAL), justification (1 phrase, citant les faits qui
   déclenchent le signal).
2. Les postes patch calculés directement (déjà finaux, cap respecté) :
   forme_lineaire_pch (cap +/-20), d46_d22_pch, d02_b59_pch, m48_b42_pch,
   d45_pch (cap +/-10), rah186_pch, m33_pch, rah200_pch,
   discipline_specifique_pch (TROT-01..04 / PLAT-01..04 / OBS-01..05 selon
   discipline, somme déjà finale).
3. `csf_signaux` : signaux faibles SF-01 à SF-24 actifs (id, valeur, famille).
4. Composantes tocard_score : tocard_somme_d (Σ des signaux Ghost D convertis
   en points 0-1), tocard_pdq, tocard_sdr, tocard_overbet_souscote (bool).
5. `supra_verdict`, `supra_score_sim` (Phase 2, 0-1), `supra_omission_candidate`
   (bool, Phase 6), `supra_phases` (résumé libre des 7 phases).
6. `ls_final_par_famille` : score LS_FINAL (0-1) par famille Longshot Hunter
   active (Partie 17.4, 8 familles) si le cheval est un outsider (cote>15/1).
7. `bonus_ssfo` : total RAH-271 (0-32 signaux SSFO), avant cap.

Chevaux sans aucune donnée qualitative exploitable -> toutes les listes vides,
valeurs à 0, sans les inventer.

SORTIE ATTENDUE (JSON strict, un seul objet, clé = numéro du cheval en string) :
{{
  "1": {{
    "signaux_catalogue": [{{"id": "B01", "valeur_brute": 15, "catalog": "B",
                             "famille": "F", "is_gamma": false,
                             "confiance": "STRICT", "justification": "..."}}],
    "forme_lineaire_pch": 0, "d46_d22_pch": 0, "d02_b59_pch": 0, "m48_b42_pch": 0,
    "d45_pch": 0, "rah186_pch": 0, "m33_pch": 0, "rah200_pch": 0,
    "discipline_specifique_pch": 0,
    "csf_signaux": [{{"id": "SF-01", "valeur": 4, "famille": "F"}}],
    "tocard_somme_d": 0.0, "tocard_pdq": 0.0, "tocard_sdr": 0.0, "tocard_overbet_souscote": false,
    "supra_verdict": "...", "supra_score_sim": 0.3, "supra_omission_candidate": false,
    "supra_phases": {{}}, "ls_final_par_famille": {{}}, "bonus_ssfo": 0,
    "flags": [], "justifications": {{}}
  }},
  "2": {{ ... }}
}}
Ne retourne QUE ce JSON, sans texte d'accompagnement."""


def build_user_prompt(chevaux: List[Cheval]) -> str:
    lines = ["Champ de la course (données pré-course collectées) :\n"]
    for c in chevaux:
        lines.append(
            f"#{c.numero} {c.nom} -- cote_matin={c.cote_matin}, valeur_pmu={c.valeur_pmu}, "
            f"musique={c.musique}, style={c.style_mpa}, entraineur={c.entraineur}, "
            f"driver={c.driver_jockey}, commentaire_derniere_course=\"{c.commentaire_derniere_course}\", "
            f"delai_j={c.delai_j}, icp_global={c.icp_global}, dq_12m={c.dq_12m}, "
            f"gains_totaux_eur={c.gains_totaux_eur}, nb_courses={c.nb_courses}"
        )
    return "\n".join(lines)


def _user_prompt_texte(chevaux: List[Cheval]) -> str:
    out = ["Commentaires de dernière course (un cheval par bloc) :\n"]
    for c in chevaux:
        txt = (c.commentaire_derniere_course or "").strip()
        if txt:
            out.append(f"#{c.numero} {c.nom} : \"{txt[:600]}\"")
    return "\n".join(out)


def compute_qualitative_signals(race: RaceContext, chevaux: List[Cheval],
                                 client) -> List[QualitativeSignals]:
    """Signaux qualitatifs par IA. Deux modes :
      * textes du protocole présents (app/protocol_assets/) -> mode complet d'origine (catalogues B/M, SUPRA...) ;
      * sinon (cas du dépôt actuel) -> mode « texte libre » : signaux AI01..AI06, points fixés en code."""
    if protocol_assets_available():
        system = build_system_prompt(race)
        user = build_user_prompt(chevaux)
        data = client.run_json(system, user, max_tokens=16000, web_search=False, web_fetch=False)
        results = []
        for c in chevaux:
            raw = data.get(str(c.numero), {})
            try:
                results.append(QualitativeSignals.model_validate(raw))
            except Exception as e:
                logger.warning("Signaux qualitatifs invalides pour #%s (%s) : %s -- valeurs neutres appliquées", c.numero, c.nom, e)
                results.append(QualitativeSignals())
        return results

    avec_texte = [c for c in chevaux if (c.commentaire_derniere_course or "").strip()]
    if not avec_texte:
        return [QualitativeSignals(flags=["IA_QUALITATIVE_SANS_TEXTE"]) for _ in chevaux]
    data = client.run_json(build_system_prompt_texte_libre(race), _user_prompt_texte(avec_texte),
                           max_tokens=6000, web_search=False, web_fetch=False)
    results = []
    for c in chevaux:
        sigs = []
        raw = data.get(str(c.numero)) or {}
        for item in (raw.get("signaux") or []):
            sid = str(item.get("id", "")).strip().upper()
            if sid not in SIGNAUX_IA_TEXTE:
                continue                                   # ID inventé par l'IA : ignoré
            preuve = str(item.get("preuve", "")).strip()[:160]
            texte = (c.commentaire_derniere_course or "").lower()
            # garde anti-hallucination : la « preuve » doit venir du texte réellement fourni
            frag = preuve.lower()[:40]
            if not preuve or (len(frag) >= 8 and frag not in texte):
                continue
            nom, pts, _ = SIGNAUX_IA_TEXTE[sid]
            sigs.append(CatalogSignal(id=sid, valeur_brute=pts, catalog="B" if pts > 0 else "M", famille="F",
                                      justification=f"[IA {nom}] {preuve}", confiance="DEGRADE"))
        results.append(QualitativeSignals(signaux_catalogue=sigs, flags=[f"IA_TEXTE:{x.id}" for x in sigs]))
    return results


def merge_ai_qualitative(python_signals: List[QualitativeSignals], ai_signals: List[QualitativeSignals],
                         cap_pch: float | None = None) -> List[str]:
    """Fusion ADDITIVE et BORNÉE dans les signaux Python (modifiés sur place) :
      * seuls les signaux dont l'ID n'existe pas déjà sont ajoutés (Python reste prioritaire) ;
      * confiance forcée à DEGRADE, is_gamma=False ;
      * total ajouté par cheval plafonné à +/- cap_pch (défaut config.AI_QUALITATIVE_CAP_PCH = 6) ;
      * champs SUPRA remplis seulement s'ils sont vides côté Python ; aucun poste PCH du moteur n'est écrasé.
    Retourne les flags de traçabilité."""
    cap = config.AI_QUALITATIVE_CAP_PCH if cap_pch is None else cap_pch
    flags: List[str] = []
    for py, ai in zip(python_signals, ai_signals):
        deja = {s.id for s in py.signaux_catalogue}
        total = 0.0
        for s in ai.signaux_catalogue:
            if s.id in deja:
                continue
            v = max(-cap, min(cap, float(s.valeur_brute)))
            if abs(total + v) > cap:                       # plafond cumulé par cheval
                v = max(-cap, min(cap, total + v)) - total
            if abs(v) < 1e-9:
                continue
            total += v
            py.signaux_catalogue.append(CatalogSignal(
                id=s.id, valeur_brute=v, catalog="B" if v > 0 else "M", famille=s.famille or "F",
                is_gamma=False, justification=s.justification, confiance="DEGRADE"))
        if total:
            py.flags.append(f"IA_QUALITATIVE:{total:+.1f}")
        if py.supra_verdict is None and ai.supra_verdict:
            py.supra_verdict = ai.supra_verdict
        if py.supra_score_sim is None and ai.supra_score_sim is not None:
            py.supra_score_sim = max(0.0, min(1.0, float(ai.supra_score_sim)))
        for f in ai.flags:
            if f.startswith("IA_QUALITATIVE_SANS_TEXTE"):
                flags.append(f)
    # v1.29.49 : un seul message récapitulatif (avant : 16 lignes identiques dans le rapport)
    n_sans = sum(1 for f in flags if f.startswith("IA_QUALITATIVE_SANS_TEXTE"))
    flags = [f for f in flags if not f.startswith("IA_QUALITATIVE_SANS_TEXTE")]
    if n_sans:
        flags.append(f"IA_QUALITATIVE_SANS_TEXTE ({n_sans} chevaux sans commentaire de dernière course)")
    return flags


# --- Lecture des pronostics / presse (v1.29.44) ----------------------------------------------
# Les consensus de favoris sont déjà couverts par l'ICP (CanalTurf) : on ne retient donc que ce que
# l'ICP ne voit pas -- un OUTSIDER mis en avant par un expert, ou un cheval explicitement DÉCONSEILLÉ.
SIGNAUX_IA_PRESSE = {
    "AI07": ("OUTSIDER_SIGNALE_PAR_PRESSE", +3.0, "Outsider (cote >= 12) cité comme une chance / un coup / une base-tocard par un expert."),
    "AI08": ("DECONSEILLE_PAR_PRESSE", -2.0, "Cheval explicitement déconseillé / à écarter / jugé sans chance dans le texte."),
}


def _squash(t: str) -> str:
    import re
    return re.sub(r"\s+", " ", t or "").strip().lower()


def _preuve_valide(preuve: str, nom: str, texte_pages: str) -> bool:
    """La phrase-preuve existe VRAIMENT dans le texte des pages et le cheval est cité à proximité."""
    from app.scraping.identity import norm_nom
    frag = _squash(preuve)[:60]
    if len(frag) < 12:
        return False
    full = _squash(texte_pages)
    i = full.find(frag)
    if i < 0:
        return False
    fen = full[max(0, i - 250): i + len(frag) + 250]
    return norm_nom(nom) in norm_nom(fen)


def compute_press_signals(race: RaceContext, chevaux: List[Cheval], pages, client) -> List[QualitativeSignals]:
    """pages = [(url, texte)] (voir collection.pages_to_texts). Retourne un QualitativeSignals par cheval."""
    vide = [QualitativeSignals() for _ in chevaux]
    if not pages:
        return vide
    texte = "\n".join(t for _, t in pages)
    regles = "\n".join(f"- {k} ({v[0]}) : {v[2]}" for k, v in SIGNAUX_IA_PRESSE.items())
    noms = "\n".join(f"#{c.numero} {c.nom} (cote {c.cote_avant_course or c.cote_matin})" for c in chevaux)
    system = f"""Tu lis des pronostics et commentaires de presse hippique (course {race.hippodrome}, {race.discipline.value}).
Pour chaque cheval de la liste, indique si le texte active un des signaux ci-dessous. Active-le SEULEMENT si le
texte le dit explicitement ; cite la phrase EXACTE copiée du texte (max 160 car.) qui cite le cheval. Sinon rien.
SIGNAUX AUTORISÉS :
{regles}
SORTIE JSON : {{"1": {{"signaux": [{{"id": "AI07", "preuve": "phrase exacte"}}]}}, "2": {{"signaux": []}}}}"""
    user = f"CHEVAUX :\n{noms}\n\n" + "\n\n".join(f"=== {u} ===\n{t}" for u, t in pages)
    data = client.run_json(system, user, max_tokens=5000, web_search=False, web_fetch=False)
    out = []
    for c in chevaux:
        sigs = []
        for item in ((data.get(str(c.numero)) or {}).get("signaux") or []):
            sid = str(item.get("id", "")).strip().upper()
            if sid not in SIGNAUX_IA_PRESSE or not _preuve_valide(str(item.get("preuve", "")), c.nom, texte):
                continue
            cote = c.cote_avant_course or c.cote_matin or 0
            if sid == "AI07" and cote < 12:
                continue                                   # favoris : déjà couverts par l'ICP
            nom, pts, _ = SIGNAUX_IA_PRESSE[sid]
            sigs.append(CatalogSignal(id=sid, valeur_brute=pts, catalog="B" if pts > 0 else "M", famille="F",
                                      justification=f"[IA {nom}] {str(item.get('preuve'))[:160]}", confiance="DEGRADE"))
        out.append(QualitativeSignals(signaux_catalogue=sigs, flags=[f"IA_PRESSE:{x.id}" for x in sigs]))
    return out
