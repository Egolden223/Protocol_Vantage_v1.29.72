"""tasks.py -- Tâches IA du protocole (v1.29.44).

1. repair_fields      : l'IA relit le TEXTE des pages et comble / vérifie les champs manquants ou suspects ;
2. (presse)           : voir qualitative.compute_press_signals ;
3. detect_anomalies   : contrôle de cohérence des données avant scoring (déterministe, sans IA : plus fiable) ;
4. analyze_misses     : hypothèses testables à partir de 30-50 audits ;
5. build_race_summary : résumé de course en langage clair (gabarit déterministe + reformulation IA contrôlée).

Principe commun : l'IA ne produit JAMAIS un chiffre sans PREUVE. Toute valeur doit être accompagnée d'une
phrase copiée du texte source ; le code vérifie que cette phrase existe, que le cheval y est cité et que la valeur
y figure. Sans preuve valide -> rejet. L'IA n'écrase jamais une donnée existante, sauf si elle est signalée
anormale par detect_anomalies ET que la nouvelle valeur est plausible et prouvée.
"""
from __future__ import annotations
import logging
import re
import statistics
import time
from typing import Any, Dict, List, Optional

from app.scraping.identity import norm_nom

logger = logging.getLogger("vantage.llm.tasks")

# ----------------------------------------------------------------------------------------- pages
_PAGES_CACHE: Dict[tuple, tuple] = {}


def get_pages(urls) -> List[tuple]:
    """Texte des pages de la course (cache 10 min ; Geny exclu sauf s'il est la seule source : crédits ScraperAPI)."""
    cibles = [u for u in urls if u and str(u).startswith("http")]
    sans_geny = [u for u in cibles if "geny.com" not in u]
    key = tuple(sorted(sans_geny or cibles))
    hit = _PAGES_CACHE.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    from app.llm.collection import pages_to_texts
    pages = pages_to_texts(list(key)) if key else []
    if len(_PAGES_CACHE) > 8:
        _PAGES_CACHE.clear()
    _PAGES_CACHE[key] = (time.time(), pages)
    return pages


def _squash(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


# ------------------------------------------------------------------------- 3. anomalies de données
def detect_anomalies(race, chevaux) -> List[Dict[str, Any]]:
    """Liste de {numero, champ, code, severite (INFO|ALERTE|ERREUR), detail}. Aucune modification des données."""
    out: List[Dict[str, Any]] = []

    def add(num, champ, code, sev, detail):
        out.append({"numero": num, "champ": champ, "code": code, "severite": sev, "detail": detail})

    nums = [c.numero for c in chevaux]
    for n in sorted({x for x in nums if nums.count(x) > 1}):
        add(n, "numero", "NUMERO_EN_DOUBLE", "ERREUR", f"Le numéro {n} apparaît plusieurs fois.")
    noms = [norm_nom(c.nom) for c in chevaux]
    for c in chevaux:
        if noms.count(norm_nom(c.nom)) > 1:
            add(c.numero, "nom", "NOM_EN_DOUBLE", "ALERTE", f"Nom en double : {c.nom}")
    if race.partants_confirmes and abs(len(chevaux) - race.partants_confirmes) > 2:
        add(None, "partants", "EFFECTIF_INCOHERENT", "ALERTE",
            f"{len(chevaux)} chevaux lus pour {race.partants_confirmes} partants annoncés.")

    inv = []
    for c in chevaux:
        cm, ca = c.cote_matin, c.cote_avant_course
        for champ, v in (("cote_matin", cm), ("cote_avant_course", ca)):
            if v is not None and (v < 1.05 or v > 999):
                add(c.numero, champ, "COTE_HORS_BORNES", "ERREUR", f"{champ}={v}")
        if cm and ca and (ca / cm > 6 or ca / cm < 1 / 6):
            add(c.numero, "cote_avant_course", "COTE_VARIATION_EXTREME", "ALERTE", f"matin {cm} -> avant course {ca}")
        ref = ca or cm
        if ref and ref >= 1.05:
            inv.append(1.0 / ref)
        if c.age is not None and not (2 <= c.age <= 15):
            add(c.numero, "age", "AGE_INVRAISEMBLABLE", "ERREUR", f"age={c.age}")
        if c.gains_totaux_eur is not None and c.gains_totaux_eur < 0:
            add(c.numero, "gains_totaux_eur", "GAINS_NEGATIFS", "ERREUR", f"{c.gains_totaux_eur}")
        if c.poids_actuel_kg is not None and not (40 <= c.poids_actuel_kg <= 75):
            add(c.numero, "poids_actuel_kg", "POIDS_HORS_BORNES", "ERREUR", f"{c.poids_actuel_kg} kg")
        if c.musique and not re.fullmatch(r"[0-9A-Za-z()\s.\-/]{2,80}", c.musique):
            add(c.numero, "musique", "MUSIQUE_FORMAT_INVALIDE", "ALERTE", f"{c.musique!r}")
    if len(inv) >= 8 and not (0.85 <= sum(inv) <= 1.9):
        add(None, "cotes", "SURROND_INVRAISEMBLABLE", "ALERTE",
            f"Somme des 1/cote = {sum(inv):.2f} (attendu 0.9-1.6) : cotes mélangées, partants manquants ou source erronée.")
    poids = [c.poids_actuel_kg for c in chevaux if c.poids_actuel_kg]
    if len(poids) >= 6:
        med = statistics.median(poids)
        for c in chevaux:
            if c.poids_actuel_kg and abs(c.poids_actuel_kg - med) > 15:
                add(c.numero, "poids_actuel_kg", "POIDS_ECART_CHAMP", "ALERTE", f"{c.poids_actuel_kg} kg vs médiane {med:.1f}")
    # discipline vs musique (lettres de discipline : a/m = trot, p = plat, h/s/c = obstacle)
    disc = race.discipline.value
    for c in chevaux:
        lettres = re.findall(r"\d[a-z]|[DATRdatr][a-z]", c.musique or "")
        low = [x[-1] for x in lettres]
        if len(low) >= 4:
            trot = sum(1 for x in low if x in "am"); plat = sum(1 for x in low if x == "p")
            if disc.startswith("TROT") and plat / len(low) > 0.7:
                add(c.numero, "musique", "MUSIQUE_DISCIPLINE_INCOHERENTE", "ALERTE", "musique de plat sur une course de trot")
            if disc == "PLAT" and trot / len(low) > 0.7:
                add(c.numero, "musique", "MUSIQUE_DISCIPLINE_INCOHERENTE", "ALERTE", "musique de trot sur une course de plat")
    return out


# ------------------------------------------------------------------- 1. réparation des champs (IA)
_CHAMPS: Dict[str, Any] = {
    "cote_matin": ("float", 1.05, 999), "cote_avant_course": ("float", 1.05, 999),
    "age": ("int", 2, 15), "poids_actuel_kg": ("float", 40, 75), "gains_totaux_eur": ("float", 0, 2e8),
    "nb_courses": ("int", 0, 500), "valeur_pmu": ("float", 0, 150),
    "musique": ("str_musique",), "driver_jockey": ("str", 3, 45), "entraineur": ("str", 3, 45),
}


def _valider(champ: str, val: Any):
    spec = _CHAMPS.get(champ)
    if spec is None or val in (None, ""):
        return None
    try:
        if spec[0] in ("float", "int"):
            v = float(str(val).replace(",", ".").replace(" ", ""))
            if not (spec[1] <= v <= spec[2]):
                return None
            return int(v) if spec[0] == "int" else v
        s = str(val).strip()
        if spec[0] == "str_musique":
            return s if re.fullmatch(r"[0-9A-Za-z()\s.\-/]{3,80}", s) else None
        return s if spec[1] <= len(s) <= spec[2] else None
    except (TypeError, ValueError):
        return None


def _valeur_dans_preuve(champ: str, v: Any, preuve: str) -> bool:
    p = _squash(preuve).replace(",", ".")
    if isinstance(v, (int, float)):
        cands = {str(v), f"{v:g}"}
        if isinstance(v, float):
            cands.add(f"{v:.1f}")
        return any(x in p for x in cands)
    return _squash(str(v)) in _squash(preuve)


def _vide(v) -> bool:
    return v is None or v == "" or v == 0


def repair_fields(race, chevaux, urls, client=None, anomalies=None, max_cells: int = 120) -> Dict[str, Any]:
    """Comble les champs manquants et revérifie les champs suspects à partir du TEXTE des pages. Modifie `chevaux`."""
    rep: Dict[str, Any] = {"appele": False, "remplis": [], "corriges": [], "rejetes": 0, "cellules_demandees": 0}
    suspects = {(a["numero"], a["champ"]) for a in (anomalies or []) if a.get("numero") is not None and a["champ"] in _CHAMPS}
    demandes: Dict[int, Dict[str, str]] = {}
    for c in chevaux:
        for champ in _CHAMPS:
            cur = getattr(c, champ, None)
            if champ == "cote_avant_course" and getattr(c, "cote_matin", None):
                continue                                    # une seule cote manquante n'est pas bloquante
            if (champ in ("age", "nb_courses", "valeur_pmu", "poids_actuel_kg", "gains_totaux_eur") and _vide(cur)
                    and champ not in ("age", "gains_totaux_eur", "nb_courses")):
                continue                                    # champs légitimement absents (ex. poids en trot)
            if cur in (None, "") or (c.numero, champ) in suspects:
                demandes.setdefault(c.numero, {})[champ] = "VERIFIER" if (c.numero, champ) in suspects else "MANQUANT"
    cells = sum(len(v) for v in demandes.values())
    rep["cellules_demandees"] = cells
    if cells == 0:
        return rep
    pages = get_pages(urls)
    if not pages:
        rep["raison"] = "aucune page téléchargeable"
        return rep
    if client is None:
        from app.llm.client import LLMClient
        client = LLMClient(timeout=90)
    par_num = {c.numero: c for c in chevaux}
    lignes = []
    for num, champs in list(demandes.items())[:30]:
        lignes.append(f"#{num} {par_num[num].nom} : " + ", ".join(f"{k} ({v})" for k, v in champs.items()))
    system = """Tu relis le TEXTE de pages hippiques (programme / partants / pronostics) pour compléter des champs.
Pour chaque cheval et chaque champ demandé, donne la valeur ET une preuve : une phrase/ligne COPIÉE telle quelle du
texte (max 160 caractères) qui contient le NOM du cheval (ou son numéro) et la valeur. Si le texte ne la donne pas :
null. N'invente rien, ne calcule rien. Cotes en décimal européen (5.2). Champs : cote_matin, cote_avant_course, age,
poids_actuel_kg, gains_totaux_eur, nb_courses, valeur_pmu, musique, driver_jockey, entraineur.
SORTIE JSON : {"1": {"cote_matin": {"valeur": 5.2, "preuve": "ligne copiée"}, "age": null}}"""
    user = "CHAMPS À TROUVER :\n" + "\n".join(lignes) + "\n\n" + "\n\n".join(f"=== {u} ===\n{t}" for u, t in pages)
    try:
        data = client.run_json(system, user, max_tokens=6000, web_search=False, web_fetch=False)
    except Exception as e:  # noqa: BLE001
        rep["erreur"] = str(e)[:200]
        return rep
    rep["appele"] = True
    rep["fournisseur"] = getattr(client, "last_provider", None)
    texte = "\n".join(t for _, t in pages)
    full = _squash(texte)
    for num, champs in demandes.items():
        brut = data.get(str(num)) or {}
        c = par_num[num]
        for champ, mode in champs.items():
            item = brut.get(champ)
            if not isinstance(item, dict):
                continue
            v = _valider(champ, item.get("valeur"))
            preuve = str(item.get("preuve") or "")
            frag = _squash(preuve)[:60]
            ok = v is not None and len(frag) >= 10 and frag in full
            if ok:
                i = full.find(frag)
                fen = full[max(0, i - 250): i + len(frag) + 250]
                ok = (norm_nom(c.nom) in norm_nom(fen)) and _valeur_dans_preuve(champ, v, preuve)
            if not ok:
                rep["rejetes"] += 1
                continue
            cur = getattr(c, champ, None)
            if cur in (None, ""):
                setattr(c, champ, v); rep["remplis"].append(f"#{num}.{champ}={v}")
                c.flags.append(f"IA_REPARE:{champ}")
            elif mode == "VERIFIER" and cur != v:
                setattr(c, champ, v); rep["corriges"].append(f"#{num}.{champ}: {cur} -> {v}")
                c.flags.append(f"IA_CORRIGE:{champ}")
    return rep


# ----------------------------------------------------------------- 4. analyse des ratés (hypothèses)
def analyze_misses(audits: List[Dict[str, Any]], client=None, min_audits: int = 10) -> Dict[str, Any]:
    """Statistiques déterministes + hypothèses testables proposées par l'IA (jamais de valeurs de paramètres)."""
    audits = [a for a in audits if isinstance(a, dict)]
    if len(audits) < min_audits:
        return {"statut": "INSUFFISANT", "message": f"{len(audits)} audit(s) < {min_audits} : trop peu pour chercher des motifs."}
    manques, caps = [], []
    for a in audits:
        caps.append(a.get("nb_captures"))
        for m in a.get("chevaux_manques") or []:
            manques.append({"rang": m.get("rang_reel"), "cote": m.get("cote_pre_course"), "tranche": m.get("notre_tranche"),
                            "causes": (m.get("causes") or m.get("diagnostic") or [])[:3] if isinstance(m.get("causes") or m.get("diagnostic") or [], list) else []})
    caps = [x for x in caps if isinstance(x, (int, float))]
    par_tranche: Dict[str, int] = {}
    for m in manques:
        par_tranche[str(m["tranche"])] = par_tranche.get(str(m["tranche"]), 0) + 1
    cotes = [m["cote"] for m in manques if isinstance(m.get("cote"), (int, float))]
    stats = {
        "nb_courses": len(audits), "captures_moyennes_sur_5": round(sum(caps) / len(caps), 2) if caps else None,
        "nb_chevaux_manques": len(manques), "manques_par_tranche": par_tranche,
        "cote_mediane_des_manques": round(statistics.median(cotes), 1) if cotes else None,
    }
    comp = [(a.get("baselines_contrefactuelles") or {}) for a in audits]
    t = [b["ticket"] - b["marche_top8"] for b in comp if "ticket" in b and "marche_top8" in b]
    if t:
        stats["ticket_moins_marche_moyen"] = round(sum(t) / len(t), 3)
    res: Dict[str, Any] = {"statut": "OK", "statistiques": stats, "hypotheses": []}
    try:
        if client is None:
            from app.llm.client import LLMClient
            client = LLMClient(timeout=90)
        system = """Tu analyses des statistiques d'audit d'un système de pronostic hippique (ticket de 8 chevaux pour capter le
Top 5). Propose AU PLUS 5 hypothèses sur les motifs de manqués. Règles : chaque hypothèse DOIT s'appuyer sur un chiffre
des statistiques fournies (cite-le) ; N'INVENTE aucun chiffre ; NE PROPOSE AUCUNE valeur de paramètre ni de poids ; donne
le TEST à faire (quelle statistique comparer, sur quel sous-ensemble de courses) et ce qui la réfuterait.
SORTIE JSON : {"hypotheses": [{"hypothese": "...", "chiffre_cite": "...", "test": "...", "refutation": "..."}]}"""
        data = client.run_json(system, "STATISTIQUES :\n" + str(stats), max_tokens=2500, web_search=False, web_fetch=False)
        blob = str(stats)
        for h in (data.get("hypotheses") or [])[:5]:
            if isinstance(h, dict) and h.get("hypothese") and h.get("test") and str(h.get("chiffre_cite", ""))[:20] and \
                    any(tok in blob for tok in re.findall(r"\d+(?:\.\d+)?", str(h.get("chiffre_cite")))):
                res["hypotheses"].append({k: str(h.get(k, ""))[:400] for k in ("hypothese", "chiffre_cite", "test", "refutation")})
        res["fournisseur"] = getattr(client, "last_provider", None)
    except Exception as e:  # noqa: BLE001
        res["ia_indisponible"] = str(e)[:200]
    return res


# ------------------------------------------------------------------- 5. résumé en langage clair
def _fmt_cote(h) -> str:
    c = h.cheval.cote_avant_course or h.cheval.cote_matin
    return f"{c:g}" if c else "?"


def build_race_summary(result, anomalies=None, reparation=None, ia_qual=None, client=None) -> Dict[str, Any]:
    """Résumé en français : gabarit déterministe (toujours disponible) + reformulation IA contrôlée."""
    by_num = {h.cheval.numero: h for h in result.horses}

    def desc(slot):
        h = by_num.get(slot.numero)
        if not h:
            return f"n°{slot.numero}"
        tr = h.synthesis.tranche.value if h.synthesis and h.synthesis.tranche else "?"
        return f"n°{h.cheval.numero} {h.cheval.nom} (cote {_fmt_cote(h)}, {tr})"

    a = [desc(t) for t in result.ticket]
    set_a = {t.numero for t in result.ticket}
    lignes = [f"Ticket A (protocole) : {', '.join(a)}."]
    if getattr(result, "ticket_quotas", None):
        set_b = {t.numero for t in result.ticket_quotas}
        plus = [desc(t) for t in result.ticket_quotas if t.numero not in set_a]
        moins = [desc(t) for t in result.ticket if t.numero not in set_b]
        qi = result.quotas_info or {}
        if plus or moins:
            lignes.append(f"Ticket B (quotas par tranche) diffère par : + {', '.join(plus) or 'aucun'} ; − {', '.join(moins) or 'aucun'}. "
                          f"Répartition T1+T2 = {qi.get('t1_t2', '?')}, T3+T4 = {qi.get('t3_t4', '?')}.")
        else:
            lignes.append("Ticket B (quotas par tranche) : mêmes 8 chevaux que le ticket A.")
    nb_err = sum(1 for x in (anomalies or []) if x["severite"] == "ERREUR")
    nb_al = sum(1 for x in (anomalies or []) if x["severite"] == "ALERTE")
    q = []
    if anomalies is not None:
        q.append(f"{nb_err} erreur(s) et {nb_al} alerte(s) de cohérence détectée(s)")
    if reparation and reparation.get("appele"):
        q.append(f"{len(reparation['remplis'])} champ(s) comblé(s) et {len(reparation['corriges'])} corrigé(s) par IA")
    if ia_qual and ia_qual.get("active"):
        q.append(f"{ia_qual.get('signaux_ajoutes', 0)} signal(aux) IA (commentaires/presse) ajouté(s), plafonnés")
    if q:
        lignes.append("Qualité des données : " + " ; ".join(q) + ".")
    pc = result.p_top5_in_ticket
    if pc is not None:
        lignes.append(f"Probabilité modèle d'avoir les 5 premiers dans le ticket A : {pc:.1%} (indicatif).")
    base = " ".join(lignes)
    out = {"texte": base, "source": "gabarit"}
    try:
        from app.llm.client import ai_available, LLMClient
        from app import config
        if config.AI_SUMMARY != "0" and ai_available():
            cl = client or LLMClient(timeout=45)
            data = cl.run_json("Tu rédiges en français clair (6 à 8 phrases, ton posé, sans jargon) un résumé de course à partir de FAITS. "
                               "N'ajoute AUCUN chiffre, nom ou fait absent des faits. Pas de conseil de mise. "
                               'SORTIE JSON : {"resume": "..."}', "FAITS :\n" + base,
                               max_tokens=900, web_search=False, web_fetch=False)
            txt = str(data.get("resume", "")).strip()
            nombres = re.findall(r"\d+(?:[.,]\d+)?", txt)
            if txt and all(n.replace(",", ".") in base.replace(",", ".") or float(n.replace(",", ".")) <= 20 for n in nombres):
                out = {"texte": txt, "source": f"ia:{getattr(cl, 'last_provider', '?')}", "gabarit": base}
    except Exception as e:  # noqa: BLE001
        logger.info("Résumé IA indisponible : %s", e)
    return out


# ------------------------------------------------------------------ 6. audit post-course assisté par IA
CAUSES_POST_COURSE = ("INCIDENT_COURSE", "PARCOURS_PLACEMENT", "RYTHME_TACTIQUE", "TERRAIN", "DISTANCE",
                      "FORME_CONDITION", "MATERIEL_JOCKEY", "SUPERIORITE_ADVERSAIRES")


def _cibles_post_course(audit: Dict[str, Any], resultats: Optional[Dict[int, dict]]) -> Dict[int, Dict[str, Any]]:
    cibles: Dict[int, Dict[str, Any]] = {}
    for m in audit.get("chevaux_manques") or []:
        cibles[m["numero"]] = {"role": "MANQUE_DU_TOP5", "nom": m.get("nom"), "rang_reel": m.get("rang_reel"),
                               "cote": m.get("cote_pre_course"),
                               "signaux": [x.split(" = ")[0] for x in (m.get("signaux_sous_evalues") or [])]}
    ticket_cands = (list(audit.get("ticket_hors_top5") or []) + list((audit.get("audit_ticket_B") or {}).get("ticket_hors_top5") or [])
                    + list((audit.get("audit_ticket_C") or {}).get("ticket_hors_top5") or []))
    for h in ticket_cands:
        if h["numero"] in cibles:
            continue
        rr = h.get("resultat_reel") or (resultats or {}).get(h["numero"]) or {}
        cibles[h["numero"]] = {"role": "SUR_EVALUE_DANS_NOTRE_TICKET", "nom": h.get("nom"), "rang_reel": rr.get("rang"),
                               "cote": h.get("cote_pre_course"),
                               "signaux": [x.split(" = ")[0] for x in (h.get("signaux_surevalues") or [])]}
    return cibles


def analyze_post_race(audit: Dict[str, Any], resultats: Optional[Dict[int, dict]] = None, urls=None,
                      client=None) -> Dict[str, Any]:
    """Explique pourquoi chaque cheval concerné (manqué du Top 5 / sur-évalué dans nos tickets) a eu ce résultat.
    Sources de texte : commentaires officiels PMU + pages de la course (comptes rendus). RÈGLES :
      * un incident officiel (tombé, arrêté...) classe le cheval INCIDENT_COURSE sans IA ;
      * toute autre explication de l'IA doit citer une phrase RÉELLEMENT présente dans ces textes, qui nomme
        le cheval ; sinon elle est rejetée (le cheval reste « non documenté ») ;
      * l'IA ne peut incriminer qu'un module parmi ceux qui ont réellement pesé sur ce cheval."""
    from app.llm.qualitative import _preuve_valide
    cibles = _cibles_post_course(audit, resultats)
    res: Dict[str, Any] = {"disponible": False, "explications": {}, "rejetees": 0}
    if not cibles:
        res["raison"] = "Aucun cheval à expliquer."
        return res
    explications: Dict[str, Dict[str, Any]] = {}
    # 1) incidents officiels : cause certaine, sans IA
    for num, c in cibles.items():
        rr = (resultats or {}).get(num) or {}
        inc = (rr.get("incident") or "").upper()
        if inc and any(k in inc for k in ("TOMB", "ARRET", "DISQ", "DISTANC", "POTEAU", "REFUS", "ALLURE", "DEROB")):
            explications[str(num)] = {"cause": "INCIDENT_COURSE", "source": "PMU officiel",
                                      "explication": f"Incident officiel : {rr.get('incident')}", "preuve": f"incident PMU = {rr.get('incident')}",
                                      "module_en_cause": None}
    # 2) textes d'après-course
    textes = []
    for num, c in cibles.items():
        com = ((resultats or {}).get(num) or {}).get("commentaire")
        if com:
            textes.append(f"[Commentaire PMU #{num} {c['nom']}] {com}")
    pages = []
    try:
        pages = get_pages(urls or [])
    except Exception as e:  # noqa: BLE001
        logger.info("Pages d'après-course indisponibles : %s", e)
    texte_total = "\n".join(textes) + "\n" + "\n".join(t for _, t in pages)
    a_expliquer = {n: c for n, c in cibles.items() if str(n) not in explications}
    if a_expliquer and len(texte_total.strip()) > 200:
        try:
            if client is None:
                from app.llm.client import LLMClient
                client = LLMClient(timeout=90)
            lignes = "\n".join(
                f"#{n} {c['nom']} ({c['role']}, rang réel {c['rang_reel']}, cote {c['cote']}; modules en cause possibles: "
                f"{', '.join(c['signaux']) or 'aucun'})" for n, c in a_expliquer.items())
            system = f"""Tu analyses une course hippique APRÈS son arrivée. Pour chaque cheval listé, explique pourquoi son résultat
diffère de notre prévision, à partir UNIQUEMENT des textes fournis (comptes rendus / commentaires). Pour chaque cheval :
- "cause" parmi {list(CAUSES_POST_COURSE)} ;
- "explication" : une phrase ;
- "preuve" : phrase EXACTE copiée du texte, qui NOMME ce cheval (max 160 caractères) ;
- "module_en_cause" : UN module parmi ceux listés pour ce cheval si l'explication le met en cause, sinon null.
Si le texte n'explique rien sur ce cheval : null pour ce cheval. N'invente rien.
SORTIE JSON : {{"3": {{"cause": "DISTANCE", "explication": "...", "preuve": "phrase copiée", "module_en_cause": "MODULE_DIST_ADAPT"}}, "7": null}}"""
            user = "CHEVAUX :\n" + lignes + "\n\nTEXTES :\n" + texte_total[:60000]
            data = client.run_json(system, user, max_tokens=4000, web_search=False, web_fetch=False)
            res["fournisseur"] = getattr(client, "last_provider", None)
            for n, c in a_expliquer.items():
                item = data.get(str(n))
                if not isinstance(item, dict):
                    continue
                cause = str(item.get("cause", "")).upper()
                preuve = str(item.get("preuve", ""))
                if cause not in CAUSES_POST_COURSE or not _preuve_valide(preuve, c["nom"] or "", texte_total):
                    res["rejetees"] += 1
                    continue
                mod = item.get("module_en_cause")
                mod = mod if mod in c["signaux"] else None
                explications[str(n)] = {"cause": cause, "source": "IA (preuve vérifiée)", "explication": str(item.get("explication", ""))[:300],
                                        "preuve": preuve[:160], "module_en_cause": mod}
        except Exception as e:  # noqa: BLE001
            res["ia_indisponible"] = str(e)[:200]
    elif a_expliquer:
        res["raison_partielle"] = "Aucun texte d'après-course exploitable (ni commentaire PMU ni compte rendu) pour expliquer les autres chevaux."
    res["explications"] = explications
    res["disponible"] = bool(explications)
    par_cause: Dict[str, int] = {}
    par_module: Dict[str, int] = {}
    for e in explications.values():
        par_cause[e["cause"]] = par_cause.get(e["cause"], 0) + 1
        if e.get("module_en_cause"):
            par_module[e["module_en_cause"]] = par_module.get(e["module_en_cause"], 0) + 1
    res["synthese"] = {"par_cause": par_cause, "modules_en_cause": par_module,
                       "chevaux_analyses": len(cibles), "chevaux_expliques": len(explications),
                       "non_documentes": [n for n in cibles if str(n) not in explications]}
    return res


def appliquer_analyse_post_course(audit: Dict[str, Any], analyse: Dict[str, Any]) -> None:
    """Attache l'explication à chaque fiche cheval (audit A et audit B) et remplace l'ancien encart « non disponible »."""
    expl = analyse.get("explications") or {}

    def _tag(a: Dict[str, Any]):
        for k in ("chevaux_manques", "ticket_hors_top5"):
            for card in a.get(k) or []:
                e = expl.get(str(card.get("numero")))
                if e:
                    card["explication_post_course"] = e
        a["analyse_presse_post_course"] = {
            "disponible": analyse.get("disponible", False), "fournisseur": analyse.get("fournisseur"),
            "synthese": analyse.get("synthese"), "rejetees": analyse.get("rejetees"),
            "raison": analyse.get("raison") or analyse.get("raison_partielle") or analyse.get("ia_indisponible"),
        }
    _tag(audit)
    for cle in ("audit_ticket_B", "audit_ticket_C"):
        if isinstance(audit.get(cle), dict) and not audit[cle].get("erreur"):
            _tag(audit[cle])
