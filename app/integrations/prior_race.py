"""prior_race.py — Anti-doublon : détecte si une course a déjà été traitée (local + HF).

v1.29.65.1 — extrait volontairement hors de hf_export.py pour un patch minimal.
v1.29.66.2 — identité stricte : date+hippo SEUL ne suffit plus.
  Match uniquement si :
  - R+C fournis et égaux à ceux de l'historique, OU
  - (distance ±25 m ET discipline) fournis et égaux.
  Si l'historique n'a pas de R+C alors que la requête en a, pas de match
  (évite les faux positifs entre C1/C2/C3 le même jour au même hippodrome).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vantage.prior_race")


def _capture_from_audit(audit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extrait les taux de capture top5 (et top4 si présent) depuis un audit post-course."""
    out: Dict[str, Any] = {
        "nb_captures_A": None,
        "taux_capture_A": None,
        "nb_captures_B": None,
        "taux_capture_B": None,
        "nb_captures_C": None,
        "taux_capture_C": None,
        "nb_captures_top4": None,
        "taux_capture_top4": None,
        "label_court": "capture non disponible",
    }
    if not isinstance(audit, dict) or not audit:
        return out

    def _pair(src: Dict[str, Any]):
        nb = src.get("nb_captures")
        tx = src.get("taux_capture_desordre")
        if tx is None and nb is not None:
            try:
                tx = float(nb) / 5.0
            except (TypeError, ValueError):
                tx = None
        return nb, tx

    nb_a, tx_a = _pair(audit)
    out["nb_captures_A"], out["taux_capture_A"] = nb_a, tx_a

    b = audit.get("audit_ticket_B") or {}
    if isinstance(b, dict):
        out["nb_captures_B"], out["taux_capture_B"] = _pair(b)
    c = audit.get("audit_ticket_C") or {}
    if isinstance(c, dict):
        out["nb_captures_C"], out["taux_capture_C"] = _pair(c)

    if audit.get("nb_captures_top4") is not None:
        out["nb_captures_top4"] = audit.get("nb_captures_top4")
    if audit.get("taux_capture_top4") is not None:
        out["taux_capture_top4"] = audit.get("taux_capture_top4")
    elif out["nb_captures_top4"] is not None:
        try:
            out["taux_capture_top4"] = float(out["nb_captures_top4"]) / 4.0
        except (TypeError, ValueError):
            pass

    parts = []
    if out["nb_captures_A"] is not None:
        pct = f"{out['taux_capture_A']*100:.0f}%" if out["taux_capture_A"] is not None else "?"
        parts.append(f"A {out['nb_captures_A']}/5 ({pct})")
    if out["nb_captures_B"] is not None:
        pct = f"{out['taux_capture_B']*100:.0f}%" if out["taux_capture_B"] is not None else "?"
        parts.append(f"B {out['nb_captures_B']}/5 ({pct})")
    if out["nb_captures_C"] is not None:
        pct = f"{out['taux_capture_C']*100:.0f}%" if out["taux_capture_C"] is not None else "?"
        parts.append(f"C {out['nb_captures_C']}/5 ({pct})")
    if out["nb_captures_top4"] is not None:
        pct = f"{out['taux_capture_top4']*100:.0f}%" if out["taux_capture_top4"] is not None else "?"
        parts.append(f"top4 {out['nb_captures_top4']}/4 ({pct})")
    if parts:
        out["label_court"] = " · ".join(parts)
    elif not audit.get("arrivee") and not audit.get("top5"):
        out["label_court"] = "audit sans arrivée (capture N/A)"
    return out


def _extract_rc(row: dict, ctx: dict) -> tuple[Optional[int], Optional[int]]:
    """Retourne (reunion_num, course_num) depuis label / contexte, ou (None, None)."""
    label = str(row.get("reunion_course_label") or ctx.get("reunion_course_label") or "")
    m = re.search(r"R\s*(\d{1,2})\s*C\s*(\d{1,2})", label, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    rn, cn = ctx.get("reunion_num"), ctx.get("course_num")
    try:
        rn_i = int(rn) if rn is not None else None
    except (TypeError, ValueError):
        rn_i = None
    try:
        cn_i = int(cn) if cn is not None else None
    except (TypeError, ValueError):
        cn_i = None
    if rn_i is None or cn_i is None:
        try:
            rctx = (row.get("result") or {}).get("context") or {}
            if rn_i is None and rctx.get("reunion_num") is not None:
                rn_i = int(rctx["reunion_num"])
            if cn_i is None and rctx.get("course_num") is not None:
                cn_i = int(rctx["course_num"])
        except (TypeError, ValueError, AttributeError):
            pass
    return rn_i, cn_i


def _identity_match(
    *,
    query_rn: Optional[int],
    query_cn: Optional[int],
    query_dist: Optional[int],
    query_disc_slug: Optional[str],
    prior_rn: Optional[int],
    prior_cn: Optional[int],
    prior_dist: Optional[int],
    prior_disc_slug: Optional[str],
) -> bool:
    """True seulement si l'identité course est suffisamment précise.

    Règles (v1.29.66.2) :
    1) Si la requête fournit R ET C : match ssi le prior a le même R+C.
       Si le prior n'a pas de R+C → pas de match (évite faux positifs).
    2) Sinon, si la requête fournit distance ET discipline : match ssi
       distance ±25 m et même discipline (slugs).
    3) Sinon → pas de match (date+hippodrome seuls insuffisants).
    """
    has_query_rc = query_rn is not None and query_cn is not None
    if has_query_rc:
        if prior_rn is None or prior_cn is None:
            return False
        return int(prior_rn) == int(query_rn) and int(prior_cn) == int(query_cn)

    has_query_dd = query_dist is not None and bool(query_disc_slug)
    if has_query_dd:
        if prior_dist is None or not prior_disc_slug:
            return False
        try:
            if abs(int(prior_dist) - int(query_dist)) > 25:
                return False
        except (TypeError, ValueError):
            return False
        return prior_disc_slug == query_disc_slug

    return False


def lookup_prior_race(
    date_course: str,
    hippodrome: str | None = None,
    distance_m: int | None = None,
    discipline: str | None = None,
    reunion_num: int | None = None,
    course_num: int | None = None,
) -> list[dict]:
    """Cherche une course déjà traitée (SQLite local + dataset Hugging Face).

    Identité stricte (v1.29.66.2) : ne matche PAS sur date+hippodrome seuls.
    """
    from app import db
    from app.integrations import hf_export as hf

    hits: list[dict] = []

    date_iso = (date_course or "").strip()[:10]
    if len(date_iso) == 10 and date_iso[2] == "-" and date_iso[5] == "-":
        try:
            d, m, y = date_iso.split("-")
            if len(y) == 2:
                date_iso = f"20{y}-{m}-{d}"
        except Exception:
            pass

    hippo_slug = hf._slugify(hippodrome) if hippodrome else None
    disc_slug = None
    if discipline:
        disc_slug = hf._DISCIPLINE_LABELS.get(str(discipline).upper(), hf._slugify(discipline))

    q_rn = int(reunion_num) if reunion_num is not None else None
    q_cn = int(course_num) if course_num is not None else None

    if not ((q_rn is not None and q_cn is not None) or (distance_m is not None and disc_slug)):
        logger.info(
            "lookup_prior: critères insuffisants (besoin R+C ou distance+discipline) — aucun match"
        )
        return []

    try:
        rows = db.list_races(limit=300) or []
    except Exception as e:
        logger.warning("lookup_prior local: %s", e)
        rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        ctx = hf._context(row) or {}
        rdate = str(ctx.get("date_course") or row.get("created_at") or "")[:10]
        if rdate != date_iso:
            continue
        rhip = str(row.get("hippodrome") or ctx.get("hippodrome") or "")
        if hippo_slug:
            rhip_s = hf._slugify(rhip)
            if rhip_s != hippo_slug and hippo_slug not in rhip_s and rhip_s not in hippo_slug:
                continue

        prior_rn, prior_cn = _extract_rc(row, ctx)
        try:
            prior_dist = int(ctx.get("distance_m")) if ctx.get("distance_m") is not None else None
        except (TypeError, ValueError):
            prior_dist = None
        rdisc = str(ctx.get("discipline") or "")
        prior_disc = hf._DISCIPLINE_LABELS.get(rdisc, hf._slugify(rdisc)) if rdisc else None

        if not _identity_match(
            query_rn=q_rn,
            query_cn=q_cn,
            query_dist=distance_m,
            query_disc_slug=disc_slug,
            prior_rn=prior_rn,
            prior_cn=prior_cn,
            prior_dist=prior_dist,
            prior_disc_slug=prior_disc,
        ):
            continue

        audit = row.get("audit") if isinstance(row.get("audit"), dict) else None
        cap = _capture_from_audit(audit)
        ver = None
        try:
            ver = (row.get("result") or {}).get("version_moteur") or (row.get("meta") or {}).get("version_moteur")
        except Exception:
            ver = None
        if not ver:
            try:
                ver = (row.get("result") or {}).get("context", {}).get("version_moteur")
            except Exception:
                pass

        hits.append({
            "source": "local",
            "race_id": row.get("id"),
            "date_course": rdate or date_iso,
            "hippodrome": rhip or hippodrome,
            "discipline": ctx.get("discipline"),
            "distance_m": ctx.get("distance_m"),
            "reunion_num": prior_rn,
            "course_num": prior_cn,
            "reunion_course_label": row.get("reunion_course_label") or (
                f"R{prior_rn}C{prior_cn}" if prior_rn is not None and prior_cn is not None else None
            ),
            "status": row.get("status"),
            "a_un_audit": bool(audit),
            "version_moteur": ver,
            "folder_hf": None,
            "updated_at": row.get("updated_at"),
            "capture": cap,
            "nb_captures_A": cap.get("nb_captures_A"),
            "taux_capture_A": cap.get("taux_capture_A"),
            "nb_captures_B": cap.get("nb_captures_B"),
            "taux_capture_B": cap.get("taux_capture_B"),
            "nb_captures_C": cap.get("nb_captures_C"),
            "taux_capture_C": cap.get("taux_capture_C"),
            "capture_label": cap.get("label_court"),
        })

    if hf.hf_export_enabled() and hf._repo():
        try:
            folders = hf._list_folders()
        except Exception as e:
            logger.warning("lookup_prior HF list: %s", e)
            folders = []

        try:
            from datetime import datetime
            jjmmaa = datetime.fromisoformat(date_iso).strftime("%d-%m-%y")
        except Exception:
            jjmmaa = None

        for folder in folders:
            parts = folder.split("-")
            if len(parts) < 6:
                continue
            f_date = "-".join(parts[0:3])
            if jjmmaa and f_date != jjmmaa:
                continue
            f_disc = parts[3]
            f_dist = parts[-1]
            f_hippo = "-".join(parts[4:-1])
            if hippo_slug and hippo_slug not in f_hippo and f_hippo not in (hippo_slug or ""):
                continue
            try:
                dm = int(re.sub(r"[^0-9]", "", f_dist) or "0") or None
            except (TypeError, ValueError):
                dm = None

            meta: Dict[str, Any] = {}
            try:
                meta = hf._get_json(folder, "meta.json") or {}
            except Exception:
                meta = {}

            prior_rn = prior_cn = None
            label = str(meta.get("reunion_course_label") or "")
            m = re.search(r"R\s*(\d{1,2})\s*C\s*(\d{1,2})", label, re.I)
            if m:
                prior_rn, prior_cn = int(m.group(1)), int(m.group(2))
            else:
                try:
                    if meta.get("reunion_num") is not None:
                        prior_rn = int(meta["reunion_num"])
                    if meta.get("course_num") is not None:
                        prior_cn = int(meta["course_num"])
                except (TypeError, ValueError):
                    pass

            prior_disc = f_disc
            if meta.get("discipline"):
                prior_disc = hf._DISCIPLINE_LABELS.get(
                    str(meta["discipline"]).upper(), hf._slugify(str(meta["discipline"]))
                )

            if not _identity_match(
                query_rn=q_rn,
                query_cn=q_cn,
                query_dist=distance_m,
                query_disc_slug=disc_slug,
                prior_rn=prior_rn,
                prior_cn=prior_cn,
                prior_dist=dm,
                prior_disc_slug=prior_disc,
            ):
                continue

            if any(h.get("folder_hf") == folder for h in hits):
                continue

            audit_hf: Dict[str, Any] = {}
            try:
                audit_hf = hf._get_json(folder, "audit_postcourse.json") or {}
            except Exception:
                audit_hf = {}
            cap = _capture_from_audit(audit_hf if isinstance(audit_hf, dict) else None)
            hits.append({
                "source": "huggingface",
                "race_id": meta.get("race_id"),
                "date_course": meta.get("date_course") or date_iso,
                "hippodrome": meta.get("hippodrome") or f_hippo,
                "discipline": f_disc,
                "distance_m": dm,
                "reunion_num": prior_rn,
                "course_num": prior_cn,
                "reunion_course_label": meta.get("reunion_course_label") or (
                    f"R{prior_rn}C{prior_cn}" if prior_rn is not None and prior_cn is not None else None
                ),
                "status": meta.get("status"),
                "a_un_audit": bool(meta.get("a_un_audit")) or bool(audit_hf),
                "version_moteur": meta.get("version_moteur"),
                "folder_hf": folder,
                "updated_at": meta.get("updated_at"),
                "capture": cap,
                "nb_captures_A": cap.get("nb_captures_A"),
                "taux_capture_A": cap.get("taux_capture_A"),
                "nb_captures_B": cap.get("nb_captures_B"),
                "taux_capture_B": cap.get("taux_capture_B"),
                "nb_captures_C": cap.get("nb_captures_C"),
                "taux_capture_C": cap.get("taux_capture_C"),
                "capture_label": cap.get("label_court"),
            })

    seen = set()
    uniq = []
    for h in hits:
        key = h.get("race_id") or h.get("folder_hf") or id(h)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return uniq
