"""
execution_report_render.py -- Formate un ExecutionReport en document
markdown lisible et téléchargeable. Distinct du rapport d'audit
walk-forward (post_race_audit.py) : celui-ci répond à "le pipeline a-t-il
tourné correctement ?", l'audit répond à "la stratégie a-t-elle bien
prédit ?" une fois la course courue.
"""
from __future__ import annotations
import json
from app.models import ExecutionReport, StageStatus

_ICONES = {
    StageStatus.EN_COURS: "⏳",
    StageStatus.OK: "✅",
    StageStatus.WARNING: "⚠️",
    StageStatus.ERROR: "❌",
    StageStatus.SKIPPED: "⏭️",
}


def render_execution_report_md(report: ExecutionReport) -> str:
    lignes = []
    lignes.append(f"# Rapport d'exécution -- course {report.race_id}")
    lignes.append("")
    lignes.append(f"*Moteur {report.version_moteur} -- {report.mode}*")
    lignes.append("")
    lignes.append(f"**Statut global : {report.statut_global}**")
    lignes.append(f"- Démarré : {report.demarre_le}")
    lignes.append(f"- Terminé : {report.termine_le or '(en cours ou interrompu)'}")
    if report.demarre_le and report.termine_le:
        try:
            from datetime import datetime
            d0 = datetime.fromisoformat(report.demarre_le)
            d1 = datetime.fromisoformat(report.termine_le)
            lignes.append(f"- Durée totale : {round((d1 - d0).total_seconds(), 1)}s")
        except Exception:
            pass
    lignes.append("")

    if report.regle_20_respectee is not None:
        icone = "✅" if report.regle_20_respectee else "❌"
        lignes.append(f"**RÈGLE 20 (aucun résultat officiel consulté avant construction du ticket) : "
                       f"{icone} {'respectée' if report.regle_20_respectee else 'NON respectée'}**")
        if report.regle_20_note:
            lignes.append(f"> {report.regle_20_note}")
        lignes.append("")

    # --- Liens exacts des sources (collecte + enrichissement) ---
    sl = getattr(report, "sources_liens", None) or {}
    if sl:
        lignes.append("---")
        lignes.append("")
        lignes.append("## Liens sources utilisés pour cette course")
        lignes.append("")
        col = sl.get("collecte") or {}
        if col:
            lignes.append("### Collecte (sources principales)")
            lignes.append("")
            if col.get("url_primaire"):
                lignes.append(f"- **URL primaire** : {col['url_primaire']}")
            for u in (col.get("urls_fournies") or col.get("urls_complementaires") or []):
                tag = " (primaire)" if u == col.get("url_primaire") else " (complémentaire)"
                lignes.append(f"- {u}{tag}")
            lignes.append("")
        enr = sl.get("enrichissement") or {}
        if enr:
            lignes.append("### Enrichissement (sources complémentaires)")
            lignes.append("")
            for nom, info in enr.items():
                if not isinstance(info, dict):
                    lignes.append(f"- **{nom}** : {info}")
                    continue
                url = info.get("url")
                urls = info.get("urls")
                urls_t = info.get("urls_tentees")
                status = info.get("status", "")
                lignes.append(f"- **{nom}**" + (f" [{status}]" if status else ""))
                if url:
                    lignes.append(f"  - lien : {url}")
                if isinstance(urls, dict):
                    for k, v in urls.items():
                        if v:
                            lignes.append(f"  - {k} : {v}")
                if isinstance(urls_t, dict):
                    for k, v in urls_t.items():
                        if isinstance(v, list) and v:
                            lignes.append(f"  - tentées ({k}) :")
                            for uu in v[:8]:
                                lignes.append(f"    - {uu}")
                if info.get("exemples_urls"):
                    lignes.append(f"  - exemples fiches ({info.get('nb', '?')} au total) :")
                    for uu in info["exemples_urls"][:8]:
                        lignes.append(f"    - {uu}")
                if info.get("note"):
                    lignes.append(f"  - note : {info['note']}")
            lignes.append("")
        if sl.get("note"):
            lignes.append(f"> {sl['note']}")
            lignes.append("")

    lignes.append("---")
    lignes.append("")
    lignes.append("## Étapes du pipeline")
    lignes.append("")

    for etape in report.etapes:
        icone = _ICONES.get(etape.status, "•")
        duree = f" ({etape.duree_sec}s)" if etape.duree_sec is not None else ""
        opt = " *(optionnelle)*" if etape.optionnelle else ""
        lignes.append(f"### {icone} {etape.nom}{duree}{opt}")
        lignes.append("")
        if etape.message:
            lignes.append(f"> {etape.message}")
            lignes.append("")
        if etape.details:
            for k, v in etape.details.items():
                if isinstance(v, (list, dict)) and len(json.dumps(v, ensure_ascii=False)) > 300:
                    lignes.append(f"- **{k}** :")
                    lignes.append("```json")
                    lignes.append(json.dumps(v, ensure_ascii=False, indent=2)[:2000])
                    lignes.append("```")
                else:
                    lignes.append(f"- **{k}** : {v}")
            lignes.append("")

    if report.erreur_fatale:
        lignes.append("---")
        lignes.append("")
        lignes.append("## ❌ Erreur fatale")
        lignes.append("")
        lignes.append(f"```\n{report.erreur_fatale}\n```")
        lignes.append("")
        if report.traceback_complet:
            lignes.append("<details><summary>Traceback complet</summary>")
            lignes.append("")
            lignes.append(f"```\n{report.traceback_complet}\n```")
            lignes.append("")
            lignes.append("</details>")
            lignes.append("")

    lignes.append("---")
    lignes.append("")
    lignes.append("## Correspondance avec les blocs du protocole (Guide d'exécution)")
    lignes.append("")
    lignes.append("*Le protocole source définit 12 blocs (+ 7bis) exécutés séquentiellement. "
                   "Le moteur en regroupe certains par nécessité technique (dépendances circulaires) "
                   "ou par absence de code séparable -- jamais par omission silencieuse : chaque bloc "
                   "listé ci-dessous est couvert par une étape ci-dessus, ou explicitement marqué "
                   "absent avec sa raison.*")
    lignes.append("")
    lignes.append("| Bloc protocole | Couvert par |")
    lignes.append("|---|---|")
    for bloc, etape in [
        ("1. Accusé de réception", "Étape 1 (fusionné, pas de code séparable)"),
        ("2. Extraction brute", "Étape 1 (fusionné, pas de code séparable)"),
        ("3. Collecte web obligatoire", "Étapes 1-2-3 (7/11 sources automatisées, cf. CARTOGRAPHIE_DONNEES.md)"),
        ("4. Rapport de complétude", "Étape 4bis (reporting seul, sans dégradation -- décision assumée)"),
        ("5. Calcul PCH_FINAL", "Étape 5 (fusionné avec Bloc 7, dépendance circulaire)"),
        ("6. Gouvernance", "Étape 6"),
        ("7. Pool Borda + CSF + Composite", "Étape 5 (fusionné avec Bloc 5, dépendance circulaire)"),
        ("7bis. SUPRA (7 phases)", "Étape 4 (heuristique simplifiée, PAS les 7 phases complètes)"),
        ("8. GMOV", "Étape 7"),
        ("9. Contraintes dures", "Étape 8"),
        ("10. Journalisation GAMMA", "Étape 10"),
        ("11. Réorganisation P1->R2", "Étape 9"),
        ("12. Présentation finale", "Étape 10"),
    ]:
        lignes.append(f"| {bloc} | {etape} |")
    lignes.append("")

    nb_ok = sum(1 for e in report.etapes if e.status == StageStatus.OK)
    nb_warn = sum(1 for e in report.etapes if e.status == StageStatus.WARNING)
    nb_err = sum(1 for e in report.etapes if e.status == StageStatus.ERROR)
    nb_skip = sum(1 for e in report.etapes if e.status == StageStatus.SKIPPED)
    lignes.append("---")
    lignes.append("")
    lignes.append(f"**Récapitulatif : {nb_ok} OK · {nb_warn} avertissement(s) · {nb_err} erreur(s) · {nb_skip} ignorée(s)** "
                   f"sur {len(report.etapes)} étape(s).")
    lignes.append("")
    lignes.append("*Pour comparer le ticket aux résultats officiels une fois la course courue, "
                   "voir le rapport d'audit walk-forward (`/api/races/{id}/audit`) -- distinct de celui-ci.*")

    return "\n".join(lignes)
