"""
execution_tracer.py -- Construit un ExecutionReport pendant que
run_pipeline tourne, une étape à la fois, et le persiste en base APRÈS
CHAQUE étape (pas seulement à la fin) : si le pipeline plante à l'étape 5,
les étapes 1-4 restent consultables dans le rapport, avec l'étape 5
marquée ERROR et le message d'exception exact -- c'est précisément ce qui
permet de localiser un bug sans avoir à relire tout le log serveur.

Usage dans orchestrator.py :

    tracer = ExecutionTracer(race_id)
    with tracer.stage("Collecte multi-sources") as st:
        race, chevaux, warnings, url = scrape_race_with_fallback(urls)
        st.details = {"url_utilisee": url, "nb_chevaux": len(chevaux)}
        if warnings:
            st.status = StageStatus.WARNING

    with tracer.stage("Enrichissement Frequence-Turf", optionnelle=True) as st:
        ...  # une exception ici est capturée et n'interrompt PAS le pipeline

    tracer.finish("TERMINE")
"""
from __future__ import annotations
import logging
import traceback as tb_module
from datetime import datetime, timezone
from typing import Optional

from app import db
from app.models import ExecutionReport, StageTrace, StageStatus
from app.version import VERSION_BUILD

logger = logging.getLogger("vantage.execution_tracer")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _StageContext:
    def __init__(self, tracer: "ExecutionTracer", nom: str, optionnelle: bool):
        self.tracer = tracer
        self.trace = StageTrace(nom=nom, optionnelle=optionnelle)

    def __enter__(self) -> StageTrace:
        self.trace.debut = _now_iso()
        self.trace.status = StageStatus.EN_COURS
        self.tracer.report.etape_courante = self.trace.nom
        self.tracer.report.statut_global = "EN_COURS"
        # Persiste immédiatement pour que l'UI voie l'étape active
        self.tracer._persist()
        return self.trace

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.trace.fin = _now_iso()
        try:
            d0 = datetime.fromisoformat(self.trace.debut)
            d1 = datetime.fromisoformat(self.trace.fin)
            self.trace.duree_sec = round((d1 - d0).total_seconds(), 3)
        except Exception:
            pass

        suppress = False
        if exc_type is not None:
            self.trace.status = StageStatus.ERROR
            self.trace.message = f"{exc_type.__name__}: {exc_val}"
            full_tb = "".join(tb_module.format_exception(exc_type, exc_val, exc_tb))
            self.tracer.report.traceback_complet = full_tb[-4000:]
            self.tracer.report.erreur_fatale = f"[{self.trace.nom}] {self.trace.message}"
            if self.trace.optionnelle:
                logger.warning("Étape optionnelle '%s' en échec (pipeline poursuivi) : %s", self.trace.nom, self.trace.message)
                suppress = True  # on avale l'exception, le pipeline continue
            else:
                logger.error("Étape '%s' en échec (pipeline interrompu) : %s", self.trace.nom, self.trace.message)

        if self.trace.status == StageStatus.EN_COURS:
            self.trace.status = StageStatus.OK
        self.tracer.report.etapes.append(self.trace)
        self.tracer.report.etape_courante = None
        self.tracer._persist()
        return suppress


class ExecutionTracer:
    def __init__(self, race_id: str):
        self.race_id = race_id
        # version_moteur : corrigé le 20/09/2026 (Golden) -- le champ avait
        # une valeur par défaut figée à "v1.28.2" dans models.py depuis sa
        # création, jamais mise à jour depuis (repéré via un vrai rapport
        # d'audit du 20/09/2026 affichant "v1.28.2" alors que l'étape
        # "0. Identification", ajoutée en v1.29.1, était bien présente --
        # incohérence qui aurait pu faire perdre du temps à quelqu'un qui
        # se fie à ce numéro pour diagnostiquer). Prend maintenant la
        # version réelle du code en cours d'exécution.
        self.report = ExecutionReport(race_id=race_id, demarre_le=_now_iso(), version_moteur=VERSION_BUILD)
        self._persist()

    def stage(self, nom: str, optionnelle: bool = False) -> _StageContext:
        return _StageContext(self, nom, optionnelle)

    def set_regle_20(self, respectee: bool, note: str) -> None:
        self.report.regle_20_respectee = respectee
        self.report.regle_20_note = note
        self._persist()

    def finish(self, statut: Optional[str] = None) -> None:
        self.report.termine_le = _now_iso()
        if statut:
            self.report.statut_global = statut
        else:
            has_error = any(e.status == StageStatus.ERROR for e in self.report.etapes)
            has_warning = any(e.status == StageStatus.WARNING for e in self.report.etapes)
            self.report.statut_global = "ECHEC" if has_error else ("TERMINE_AVEC_AVERTISSEMENTS" if has_warning else "TERMINE")
        self._persist()

    def _persist(self) -> None:
        try:
            db.save_execution_report(self.race_id, self.report.model_dump(mode="json"))
        except Exception:
            logger.exception("Échec de sauvegarde du rapport d'exécution pour %s (non bloquant)", self.race_id)
