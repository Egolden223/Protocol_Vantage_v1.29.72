"""supervisor.py — Couche IA optionnelle (garde + post-audit).

Providers free-tier supportés (ordre de préférence si plusieurs clés) :
  - GROQ_API_KEY      → https://api.groq.com (Llama)
  - GEMINI_API_KEY    → Google Generative Language API
  - ANTHROPIC_API_KEY → Claude (si déjà configuré)

Sans aucune clé : no-op, le moteur reste 100 % déterministe.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vantage.ai_supervisor")

AI_ENABLED = os.environ.get("AI_SUPERVISOR", "1").strip() not in ("0", "false", "False")
AI_APPLY_BOUNDED_REPAIRS = os.environ.get("AI_APPLY_BOUNDED_REPAIRS", "0").strip() in (
    "1",
    "true",
    "True",
)
AI_TIMEOUT_SEC = int(os.environ.get("AI_TIMEOUT_SEC", "20"))

# RAH-270 (v1.29.14) : signal qualitatif de rythme/allure, distinct de
# AI_SUPERVISOR -- celui-ci ne fait que conseiller/auditer (n'influence
# jamais le ticket). AI_QUALITATIVE_SIGNAL active un vrai poste PCH
# (postes 17-32, borné +/-3, cf. app/engine/ai_rhythm.py). Désactivé par
# défaut : activer AI_SUPERVISOR seul ne suffit pas à influencer le
# scoring -- décision délibérée, pas un oubli.
AI_QUALITATIVE_SIGNAL = os.environ.get("AI_QUALITATIVE_SIGNAL", "0").strip() in (
    "1",
    "true",
    "True",
)
RAH270_CAP = 3.0


def is_qualitative_ai_enabled() -> bool:
    return AI_ENABLED and AI_QUALITATIVE_SIGNAL and _provider_available() is not None
def _env_key(*names: str) -> Optional[str]:
    """Lit une clé API en stripant espaces/quotes (erreurs fréquentes Render)."""
    for n in names:
        v = os.environ.get(n)
        if v is None:
            continue
        v = v.strip().strip('"').strip("'")
        if v:
            return v
    return None


# Modèles par défaut + chaîne de repli (sept. 2026)
# Groq : llama-3.1-8b-instant (gratuit / taux élevé) en premier ;
#         llama-3.3-70b-versatile ; openai/gpt-oss-20b (production).
# Gemini : gemini-2.0-flash est ÉTEINT → 404 ; utiliser 2.5 / 3.x Flash.
# v1.29.52 -- modèles par défaut VALIDÉS EN RÉEL (« tester l'IA » du 17/10/2026) : sur ce compte Groq seuls les modèles
# openai/gpt-oss-* sont accessibles (llama-3.1-8b-instant et llama-3.3-70b-versatile renvoient 404) ; côté Gemini,
# gemini-2.5-flash(-lite) et 1.5-* sont « no longer available to new users » alors que gemini-3.5-flash répond.
# Les noms vieillissent vite : le dernier modèle qui a fonctionné est mémorisé et réessayé en premier, et les modèles
# réellement disponibles sont découverts dynamiquement (ListModels) quand la liste est épuisée.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_MODEL_FALLBACKS = [
    m.strip() for m in os.environ.get(
        "GROQ_MODEL_FALLBACKS",
        "openai/gpt-oss-120b,llama-3.3-70b-versatile,llama-3.1-8b-instant",
    ).split(",") if m.strip()
]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_MODEL_FALLBACKS = [
    m.strip() for m in os.environ.get(
        "GEMINI_MODEL_FALLBACKS",
        "gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-2.5-flash,gemini-2.5-flash-lite",
    ).split(",") if m.strip()
]
_LAST_OK: Dict[str, str] = {}          # dernier modèle ayant répondu, par fournisseur (réessayé en premier)


def _ordered_models(provider: str, base: str, fallbacks: List[str]) -> List[str]:
    out: List[str] = []
    for m in [_LAST_OK.get(provider), base] + fallbacks:
        if m and m not in out:
            out.append(m)
    return out


def _provider_available() -> Optional[str]:
    if _env_key("GROQ_API_KEY"):
        return "groq"
    if _env_key("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        return "gemini"
    if _env_key("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def is_ai_available() -> bool:
    return AI_ENABLED and _provider_available() is not None


_UA = "protocol-vantage/1.0 (+https://github.com/; python)"


def _http_json(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    # v1.29.50 : en-tête User-Agent explicite. Sans lui, urllib envoie « Python-urllib/3.x », bloqué par la protection
    # Cloudflare de Groq (HTTP 403 « error code: 1010 ») -> tous les appels Groq échouaient.
    headers = {"User-Agent": _UA, **headers}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or AI_TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_err = ""
        try:
            body_err = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {body_err}") from e



def _groq_list_models(key: str) -> List[str]:
    """Liste les modèles actifs côté Groq (pour recovery 404)."""
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}", "User-Agent": _UA},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=min(AI_TIMEOUT_SEC, 10)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        # Préférer chat/instruct textuels
        prefer = [i for i in ids if any(x in i for x in (
            "llama-3.1-8b", "llama-3.3-70b", "gpt-oss-20b", "gpt-oss-120b", "instant", "versatile"
        ))]
        return prefer or ids
    except Exception as e:
        logger.warning("groq list models: %s", e)
        return []


def _call_groq(system: str, user: str, max_tokens: int = 2500, json_mode: bool = False,
               timeout: Optional[int] = None) -> str:
    key = _env_key("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY absent")
    models = _ordered_models("groq", GROQ_MODEL, GROQ_MODEL_FALLBACKS)
    last_err: Optional[Exception] = None
    saw_auth = False
    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        if "gpt-oss" in model:
            # modèles « raisonnants » : le raisonnement consomme des tokens de sortie -> effort bas + marge,
            # sinon `content` peut revenir vide (réponse tronquée pendant la réflexion).
            payload["reasoning_effort"] = "low"
            payload["max_tokens"] = max_tokens + 800
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            try:
                out = _http_json(
                    "https://api.groq.com/openai/v1/chat/completions",
                    {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    payload, timeout,
                )
            except RuntimeError as e400:
                if "400" in str(e400) and ("reasoning" in str(e400).lower() or "response_format" in str(e400).lower()):
                    payload.pop("reasoning_effort", None)
                    payload.pop("response_format", None)           # option non supportée par ce modèle : on réessaie sans
                    out = _http_json("https://api.groq.com/openai/v1/chat/completions",
                                     {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload, timeout)
                else:
                    raise
            content = out["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise RuntimeError(f"réponse vide du modèle {model} (raisonnement sans sortie ?)")
            _LAST_OK["groq"] = model
            return content
        except Exception as e:
            last_err = e
            msg = str(e)
            logger.warning("Groq model %s failed: %s", model, e)
            if "401" in msg or "Invalid API Key" in msg or "invalid_api_key" in msg.lower():
                saw_auth = True
                break  # clé invalide → inutile de tenter d'autres modèles
            if "403" in msg and ("rate" in msg.lower() or "quota" in msg.lower() or "limit" in msg.lower()):
                # rate limit : essayer un modèle plus petit si dispo
                continue
            if "403" in msg and "Forbidden" in msg:
                # souvent clé refusée ou modèle non autorisé — on continue les modèles
                continue
            continue
    # Recovery : modèles listés dynamiquement si 404 massif
    if last_err and "404" in str(last_err) and not saw_auth:
        for model in _groq_list_models(key)[:6]:
            if model in models:
                continue
            try:
                out = _http_json(
                    "https://api.groq.com/openai/v1/chat/completions",
                    {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 2500,
                    },
                )
                return out["choices"][0]["message"]["content"]
            except Exception as e:
                last_err = e
                continue
    if saw_auth:
        raise RuntimeError(
            f"Groq 401/403 auth — vérifier GROQ_API_KEY sur Render (clé invalide ou révoquée). Détail: {last_err}"
        )
    raise RuntimeError(f"Groq all models failed: {last_err}")


_GEMINI_BAD = ("preview", "exp", "thinking", "tts", "image", "live", "audio", "embedding", "vision", "learnlm",
               "gemma", "aqa", "robotics", "computer", "deep-research", "veo", "imagen", "omni")


def _gemini_list_models(key: str) -> List[str]:
    """Modèles réellement disponibles pour CETTE clé (ListModels) : texte, generateContent, stables d'abord.
    Évite de dépendre d'une liste de noms qui vieillit (les gemini-1.5-* et 2.0-* sont retirés)."""
    try:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={urllib.parse.quote(key)}",
            headers={"User-Agent": _UA}, method="GET")
        with urllib.request.urlopen(req, timeout=min(AI_TIMEOUT_SEC, 15)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("Gemini ListModels indisponible : %s", e)
        return []
    out: List[str] = []
    for m in data.get("models") or []:
        name = str(m.get("name", "")).replace("models/", "")
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if not name.startswith("gemini") or any(b in name for b in _GEMINI_BAD):
            continue
        out.append(name)

    def _score(n: str):
        ver = re.search(r"(\d+(?:\.\d+)?)", n)
        v = float(ver.group(1)) if ver else 0.0
        famille = 2 if ("flash" in n and "lite" not in n) else (1 if "flash" in n else 0)   # flash > flash-lite > autres (pro)
        return (famille, v)                          # versions récentes d'abord
    return sorted(set(out), key=_score, reverse=True)


def _call_gemini(system: str, user: str, max_tokens: int = 2500, json_mode: bool = False,
                 timeout: Optional[int] = None) -> str:
    """Gemini generateContent — modèles post-2.0 (2.0-flash shutdown → 404)."""
    key = _env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY absent")
    models: List[str] = []
    for m in [_LAST_OK.get("gemini"), GEMINI_MODEL] + GEMINI_MODEL_FALLBACKS:
        if m and m not in models:
            # normalise "models/xxx" → "xxx"
            m = m.replace("models/", "")
            models.append(m)
    last_err: Optional[Exception] = None
    saw_auth = False
    text_payload = {
        "contents": [{"role": "user", "parts": [{"text": f"{system}\n\n---\n\n{user}"}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }
    if json_mode:
        text_payload["generationConfig"]["responseMimeType"] = "application/json"
    tentes: Dict[str, str] = {}                      # modèle -> dernière erreur (diagnostic lisible)
    decouverts = False
    queue = list(models)
    while queue:
        model = queue.pop(0)
        # Essayer v1beta puis v1
        for api_ver in ("v1beta", "v1"):
            url = (
                f"https://generativelanguage.googleapis.com/{api_ver}/models/"
                f"{model}:generateContent?key={urllib.parse.quote(key)}"
            )
            try:
                out = _http_json(url, {"Content-Type": "application/json"}, text_payload, timeout)
                cands = out.get("candidates") or []
                if not cands:
                    # prompt bloqué / vide
                    pf = out.get("promptFeedback") or {}
                    last_err = RuntimeError(f"Gemini empty candidates feedback={pf}")
                    continue
                parts = (cands[0].get("content") or {}).get("parts") or []
                texts = [p.get("text", "") for p in parts if p.get("text")]
                if texts:
                    _LAST_OK["gemini"] = model
                    return "\n".join(texts)
                last_err = RuntimeError("Gemini parts sans texte")
            except Exception as e:
                last_err = e
                msg = str(e)
                tentes[model] = msg[:90].replace("\n", " ")
                logger.warning("Gemini %s/%s failed: %s", api_ver, model, e)
                if "401" in msg or "API_KEY_INVALID" in msg or "API key not valid" in msg:
                    saw_auth = True
                    break
                continue
        if saw_auth:
            break
        # v1.29.50 : liste statique épuisée -> on interroge les modèles réellement disponibles pour cette clé
        if not queue and not decouverts and not saw_auth:
            decouverts = True
            dispo = _gemini_list_models(key)
            tentes["(ListModels)"] = (f"{len(dispo)} modèle(s) texte disponible(s) : " + ", ".join(dispo[:8])) if dispo else "aucun modèle listé (clé sans accès ?)"
            queue = [m for m in dispo if m not in tentes][:4]
    if saw_auth:
        raise RuntimeError(
            f"Gemini clé invalide — vérifier GEMINI_API_KEY / GOOGLE_API_KEY. Détail: {last_err}"
        )
    info = tentes.pop("(ListModels)", None)
    detail = ((f"(ListModels) {info} ; ") if info else "") + " ; ".join(f"{m}: {e[:60]}" for m, e in list(tentes.items())[:6])
    raise RuntimeError(f"Gemini all models failed ({len(tentes)} essayés) -- {detail}")


def _call_anthropic(system: str, user: str, max_tokens: int = 2500, json_mode: bool = False,
                    timeout: Optional[int] = None) -> str:
    key = _env_key("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY absent")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    out = _http_json(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        payload, timeout,
    )
    texts = [b.get("text", "") for b in out.get("content", []) if b.get("type") == "text"]
    return "\n".join(texts)


def _llm(system: str, user: str) -> Dict[str, Any]:
    if not AI_ENABLED:
        return {"status": "DISABLED", "provider": None, "text": None}

    # v1.29.16 (port Grok, walk-forward) — chaîne de repli au lieu d'un
    # seul provider : un Groq 403 (rate limit atteint en test réel) ne
    # doit pas faire échouer tout l'appel si Gemini/Anthropic sont
    # disponibles en secours.
    order = []
    if _env_key("GROQ_API_KEY"):
        order.append("groq")
    if _env_key("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        order.append("gemini")
    if _env_key("ANTHROPIC_API_KEY"):
        order.append("anthropic")
    if not order:
        return {
            "status": "SKIPPED_NO_KEY",
            "provider": None,
            "text": None,
            "note": "Définir GROQ_API_KEY et/ou GEMINI_API_KEY (ou ANTHROPIC_API_KEY) sur Render. Modèles: llama-3.1-8b-instant / gemini-2.5-flash (2.0-flash est éteint).",
        }

    errors = []
    for prov in order:
        try:
            if prov == "groq":
                text = _call_groq(system, user)
            elif prov == "gemini":
                text = _call_gemini(system, user)
            else:
                text = _call_anthropic(system, user)
            return {"status": "OK", "provider": prov, "text": text}
        except Exception as e:
            logger.warning("AI supervisor call failed (%s): %s", prov, e)
            errors.append(f"{prov}: {str(e)[:120]}")
    return {
        "status": "ERROR",
        "provider": order[0],
        "text": None,
        "error": " | ".join(errors)[:300],
    }


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else None
    if not raw:
        m2 = re.search(r"(\{[^{}]*\"actions\".*\})", text, re.S)
        raw = m2.group(1) if m2 else None
    if not raw:
        # try whole text
        t = text.strip()
        if t.startswith("{") and t.endswith("}"):
            raw = t
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# 1) Garde / conseiller pré-ticket
# ---------------------------------------------------------------------------

_SYSTEM_GUARD = """Tu es le superviseur de conformité du protocole turf Quinté "Protocol Vantage".
Tu reçois un rapport de conformité DÉTERMINISTE déjà calculé (checks PASS/WARN/FAIL),
des flags GMO-V et un résumé du ticket.
Règles strictes:
- Ne invente aucun cheval, cote, ni résultat de course.
- Ne propose PAS d'annuler le quota flexible 3-5 ni le noyau marché validé. Les rôles PIVOT/SEMI/VALUE/SAUVAGE sont déterministes — ne les invente pas.
- Actions autorisées uniquement: NONE, LOG_ONLY, SUGGEST_REFETCH_SOURCE, SUGGEST_SWAP_HORS_NOYAU.
- Réponds en français.
- Termine par un bloc JSON strict:
```json
{"synthese":"...","actions":[{"type":"LOG_ONLY","detail":"..."}],"risques_protocole":[],"confiance":0.0}
```
"""


def supervise_pre_ticket(
    compliance: Dict[str, Any],
    gmo_flags: List[str],
    ticket_summary: List[Dict[str, Any]],
    race_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Interprète la conformité + propose actions bornées (appliquées seulement si env)."""
    base = {
        "compliance_verdict": compliance.get("verdict"),
        "ai": {"status": "SKIPPED"},
        "actions_proposees": [],
        "actions_appliquees": [],
        "synthese": None,
    }
    payload = {
        "course": race_summary,
        "compliance": compliance,
        "gmo_flags": gmo_flags[:40],
        "ticket": ticket_summary,
    }
    user = (
        "Analyse ce dossier d'exécution pré-ticket et vérifie le respect du protocole.\n"
        + json.dumps(payload, ensure_ascii=False, default=str)[:12000]
    )
    ai = _llm(_SYSTEM_GUARD, user)
    base["ai"] = {k: ai.get(k) for k in ("status", "provider", "error", "note") if k in ai or True}
    base["ai"]["status"] = ai.get("status")
    base["ai"]["provider"] = ai.get("provider")
    if ai.get("error"):
        base["ai"]["error"] = ai["error"]
    if ai.get("note"):
        base["ai"]["note"] = ai["note"]

    if ai.get("status") != "OK" or not ai.get("text"):
        base["synthese"] = (
            f"Supervision IA indisponible ({ai.get('status')}). "
            f"Verdict déterministe: {compliance.get('verdict')} "
            f"({compliance.get('nb_fail')} FAIL, {compliance.get('nb_warn')} WARN)."
        )
        return base

    text = ai["text"]
    base["synthese_brute"] = text[:4000]
    parsed = _extract_json_block(text)
    if parsed:
        base["synthese"] = parsed.get("synthese") or text[:800]
        actions = parsed.get("actions") or []
        # filtre liste blanche
        allowed = {"NONE", "LOG_ONLY", "SUGGEST_REFETCH_SOURCE", "SUGGEST_SWAP_HORS_NOYAU"}
        cleaned = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            t = str(a.get("type", "LOG_ONLY"))
            if t not in allowed:
                t = "LOG_ONLY"
            cleaned.append({"type": t, "detail": str(a.get("detail", ""))[:500]})
        base["actions_proposees"] = cleaned
        base["risques_protocole"] = parsed.get("risques_protocole") or []
        base["confiance"] = parsed.get("confiance")
    else:
        base["synthese"] = text[:1500]
        base["actions_proposees"] = [{"type": "LOG_ONLY", "detail": "Réponse IA non JSON — log only"}]

    # Réparations bornées : par défaut on N'APPLIQUE PAS de swap ticket
    if AI_APPLY_BOUNDED_REPAIRS:
        for a in base["actions_proposees"]:
            if a["type"] in ("LOG_ONLY", "NONE", "SUGGEST_REFETCH_SOURCE", "SUGGEST_SWAP_HORS_NOYAU"):
                base["actions_appliquees"].append(
                    {
                        **a,
                        "applied": False,
                        "reason": "Suggestions journalisées — swap ticket non auto-appliqué (sécurité protocole).",
                    }
                )
    else:
        base["actions_appliquees"] = [
            {
                "type": "NONE",
                "detail": "AI_APPLY_BOUNDED_REPAIRS=0 — suggestions seulement",
                "applied": False,
            }
        ]
    return base


# ---------------------------------------------------------------------------
# 2) Audit post-course enrichi
# ---------------------------------------------------------------------------

_SYSTEM_POST = """Tu es l'analyste post-course structurel du protocole Quinté Protocol Vantage.
Tu reçois l'audit déterministe (capture, manqués, hors top5, modules, rôles, flags).

Objectifs (dans cet ordre):
1) Expliquer chaque manqué (cause probable: scoring, quota, marché, rôle, lacune donnée).
2) Qualifier les hors-top5 du ticket (couverture utile vs bruit) et la répartition des rôles PIVOT/SEMI/VALUE/SAUVAGE.
3) Dire si le protocole a été respecté (Règle 20, contraintes, déterminisme).
4) Diagnostic STRUCTUREL: modules/catalogues/contraintes qui ont écarté un arrivant ou surévalué un hors-Top5; conflits de règles éventuels.
5) Proposer 1 à 3 HYPOTHÈSES de levier structurel testables en walk-forward (bornes, poids, seuils) — JAMAIS "ajouter le n°X".
   Chaque hypothèse: levier, plage autorisée, métrique de succès (ex: capture moyenne, taux ≥4/5), discipline concernée.

Interdits: inventer l'arrivée, modifier les chiffres fournis, conseiller une mise financière, proposer un cheval précis.

Réponds en français, markdown court, puis JSON strict:
```json
{
  "capture_commentaire":"...",
  "manques":[{"numero":0,"cause":"..."}],
  "roles_commentaire":"...",
  "lecons_protocole":["..."],
  "diagnostic_structurel":["..."],
  "hypotheses":[{"levier":"...","plage":"...","metrique":"...","discipline":"toutes|trot|plat|obstacle"}],
  "priorite":"haute|moyenne|basse"
}
```
"""


def enrich_post_race_audit(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Ajoute section supervision_ia à l'audit post-course."""
    slim = {
        "recap": audit.get("recap_technique"),
        "taux_capture_desordre": audit.get("taux_capture_desordre"),
        "nb_captures": audit.get("nb_captures"),
        "captures": audit.get("chevaux_captures"),
        "manques": audit.get("chevaux_manques"),
        "hors_top5": audit.get("ticket_hors_top5"),
        "arrivee": audit.get("arrivee_officielle_top5"),
        # v1.29.22 — contexte structurel pour diagnostic / hypothèses
        "roles_ticket": (audit.get("rapport_execution") or {}).get("roles_ticket")
            or audit.get("roles_ticket"),
        "gmo_flags_sample": ((audit.get("rapport_execution") or {}).get("gmo_flags") or [])[:25],
    }
    user = "Audit post-course à interpréter:\n" + json.dumps(slim, ensure_ascii=False, default=str)[:14000]
    ai = _llm(_SYSTEM_POST, user)
    section: Dict[str, Any] = {
        "status": ai.get("status"),
        "provider": ai.get("provider"),
    }
    if ai.get("error"):
        section["error"] = ai["error"]
    if ai.get("note"):
        section["note"] = ai["note"]
    if ai.get("status") != "OK" or not ai.get("text"):
        section["commentaire"] = (
            "IA post-audit indisponible — se référer aux champs déterministes "
            "(chevaux_manques.signaux_sous_evalues, ticket_hors_top5)."
        )
        return section

    text = ai["text"]
    section["commentaire_markdown"] = text[:5000]
    parsed = _extract_json_block(text)
    if parsed:
        section["structure"] = {
            "capture_commentaire": parsed.get("capture_commentaire"),
            "manques": parsed.get("manques"),
            "roles_commentaire": parsed.get("roles_commentaire"),
            "lecons_protocole": parsed.get("lecons_protocole"),
            "diagnostic_structurel": parsed.get("diagnostic_structurel") or [],
            "hypotheses": parsed.get("hypotheses") or [],
            "priorite": parsed.get("priorite"),
        }
        # Journal d'hypothèses structurelles (jamais de n° de cheval)
        hyps = []
        for h in (parsed.get("hypotheses") or []):
            if not isinstance(h, dict):
                continue
            lev = str(h.get("levier") or "")[:200]
            if not lev or any(x in lev.lower() for x in ("n°", "numero ", "numéro ")):
                continue
            hyps.append({
                "levier": lev,
                "plage": str(h.get("plage") or "")[:120],
                "metrique": str(h.get("metrique") or "capture_top5_moyenne")[:80],
                "discipline": str(h.get("discipline") or "toutes")[:40],
            })
        section["journal_hypotheses"] = hyps[:5]
    return section


# ---------------------------------------------------------------------------
# 3) RAH-270 -- signal qualitatif de rythme/allure (v1.29.14, optionnel)
# ---------------------------------------------------------------------------

_SYSTEM_RYTHME = """Tu es analyste hippique. Pour CHAQUE cheval listé, lis son
commentaire de dernière course (texte libre, en français, style presse
hippique) et estime un signal de RYTHME/ALLURE : la course a-t-elle été
gênée/mal négociée (signal négatif, ex: "manque de rythme", "enfermé",
"a manqué son départ", "s'est déplacé") ou au contraire bien négociée avec
une marge de progression réelle (signal positif, ex: "n'a rien pu faire
mais fort en fin de parcours", "réclame plus long", "s'est bien comporté
malgré un parcours compliqué") ?
Règles strictes:
- N'invente RIEN : si le commentaire est vide, générique ou ne permet
  aucune lecture fiable du rythme, mets signal=0 et rationale="indéterminé".
- Chaque signal est un nombre entre -3 et +3 (jamais au-delà).
- Ne tiens compte QUE du commentaire fourni, pas de cotes ni de résultats.
- Réponds en français.
- Termine par un bloc JSON strict, un objet par cheval, TOUS les numéros
  fournis doivent apparaître (même à 0) :
```json
{"signaux":[{"numero":1,"signal":0.0,"rationale":"..."}]}
```
"""


def classify_race_rhythm(chevaux: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Un seul appel LLM pour toute la course (pas un par cheval).

    chevaux: [{"numero": int, "nom": str, "commentaire": str}, ...] --
    seuls les chevaux avec un commentaire non trivial (>=10 caractères)
    devraient être inclus par l'appelant, mais cette fonction reste
    défensive de toute façon.
    Retour: {"status": "OK"|"SKIPPED_NO_KEY"|"DISABLED"|"ERROR",
             "provider": str|None, "par_numero": {numero: {"signal": float, "rationale": str}}}
    """
    result: Dict[str, Any] = {"status": "SKIPPED", "provider": None, "par_numero": {}}
    if not chevaux:
        result["status"] = "SKIPPED_VIDE"
        return result

    user = (
        "Chevaux à analyser (numero/nom/commentaire) :\n"
        + json.dumps(chevaux, ensure_ascii=False, default=str)[:12000]
    )
    ai = _llm(_SYSTEM_RYTHME, user)
    result["status"] = ai.get("status")
    result["provider"] = ai.get("provider")
    if ai.get("error"):
        result["error"] = ai["error"]
    if ai.get("note"):
        result["note"] = ai["note"]
    if ai.get("status") != "OK" or not ai.get("text"):
        return result

    parsed = _extract_json_block(ai["text"])
    if not parsed or not isinstance(parsed.get("signaux"), list):
        result["status"] = "ERROR"
        result["error"] = "Réponse IA sans bloc JSON 'signaux' exploitable"
        return result

    par_numero: Dict[int, Dict[str, Any]] = {}
    for item in parsed["signaux"]:
        if not isinstance(item, dict):
            continue
        try:
            numero = int(item.get("numero"))
        except (TypeError, ValueError):
            continue
        try:
            signal = float(item.get("signal", 0.0))
        except (TypeError, ValueError):
            signal = 0.0
        # Clamp défensif -- même si le prompt le demande déjà, on ne fait
        # jamais confiance à une sortie LLM sans borne appliquée côté code.
        signal = max(-RAH270_CAP, min(RAH270_CAP, signal))
        par_numero[numero] = {
            "signal": signal,
            "rationale": str(item.get("rationale", ""))[:300],
        }
    result["par_numero"] = par_numero
    return result


# ---------------------------------------------------------------------------
# 4) Détection d'anomalies d'exécution (déterministe + synthèse IA optionnelle)
# ---------------------------------------------------------------------------

def diagnose_execution_anomalies(
    gmo_flags: Optional[List[str]] = None,
    coverage: Optional[Dict[str, Any]] = None,
    roles_report: Optional[Dict[str, Any]] = None,
    sources_warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Anomalies opérationnelles — purement déterministe, pas d'appel LLM.

    Sert de garde-fou avant/après ticket: sources, rôles, couverture.
    """
    alerts: List[str] = []
    gmo_flags = gmo_flags or []
    sources_warnings = sources_warnings or []
    roles_report = roles_report or {}
    coverage = coverage or {}

    for w in sources_warnings[:20]:
        ws = str(w).upper()
        if any(k in ws for k in ("403", "404", "TIMEOUT", "EMPTY", "LACUNE_CRITIQUE")):
            alerts.append(f"SOURCE:{w}"[:160])

    for fl in gmo_flags:
        if any(k in fl for k in (
            "QUOTA_REPAIR_FAIL", "MARCHE_COUVERTURE_BLOCAGE",
            "ROLE_WARN_NO_PIVOT", "ROLE_WARN_NO_VALUE",
        )):
            alerts.append(f"GMO:{fl}"[:160])

    for w in (roles_report.get("warns") or []):
        alerts.append(f"ROLE:{w}")

    ratio_val = coverage.get("ratio_valeur")
    if ratio_val is not None and float(ratio_val) > 0.30:
        alerts.append(f"LACUNE:valeur_pmu_ratio={ratio_val}")

    severity = "OK"
    if any(a.startswith("SOURCE:") or a.startswith("LACUNE:") for a in alerts):
        severity = "WARN"
    if any("FAIL" in a for a in alerts):
        severity = "HIGH"

    return {
        "status": severity,
        "nb_alerts": len(alerts),
        "alerts": alerts[:30],
        "note": "Déterministe — pas d'appel LLM. Utiliser supervision_ia pour l'interprétation.",
    }


def propose_structural_experiments(
    audits_summary: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Propose des expériences A/B structurelles à partir d'un batch d'audits.

    audits_summary: liste légère [{discipline, capture, manques_flags, roles_counts}, ...]
    Sans clé API: retour SKIPPED. Ne propose jamais un numéro de cheval.
    """
    base: Dict[str, Any] = {"status": "SKIPPED", "experiences": []}
    if not audits_summary:
        base["status"] = "SKIPPED_VIDE"
        return base
    if not is_ai_available():
        base["status"] = "SKIPPED_NO_KEY"
        base["note"] = "Clé API absente — pas d'expériences proposées."
        return base

    system = (
        "Tu es le comité d'expérimentation du protocole Vantage. "
        "À partir d'un batch d'audits walk-forward, propose 1 à 3 expériences "
        "STRUCTURELLES (bornes, poids, seuils par discipline). "
        "Interdit: nommer un cheval ou un numéro. "
        "JSON final: "
        '{"experiences":[{"nom":"...","levier":"...","plage":"...","discipline":"...","metrique":"capture_moyenne"}]}'
    )
    user = "Batch audits:\n" + json.dumps(audits_summary, ensure_ascii=False, default=str)[:12000]
    ai = _llm(system, user)
    base["status"] = ai.get("status")
    base["provider"] = ai.get("provider")
    if ai.get("error"):
        base["error"] = ai["error"]
    if ai.get("status") != "OK" or not ai.get("text"):
        return base
    parsed = _extract_json_block(ai["text"])
    if not parsed:
        return base
    exps = []
    for e in (parsed.get("experiences") or [])[:3]:
        if not isinstance(e, dict):
            continue
        lev = str(e.get("levier") or "")
        if any(x in lev.lower() for x in ("n°", "numero", "numéro")):
            continue
        exps.append({
            "nom": str(e.get("nom") or "")[:80],
            "levier": lev[:160],
            "plage": str(e.get("plage") or "")[:80],
            "discipline": str(e.get("discipline") or "toutes")[:40],
            "metrique": str(e.get("metrique") or "capture_moyenne")[:80],
        })
    base["experiences"] = exps
    return base


def guide_enrichment(
    race: Any,
    lacunes: List[str],
    resume_couverture: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Guide IA étape 2.7 — priorités + requêtes web (chaîne _llm)."""
    if not is_ai_available():
        return {
            "status": "SKIPPED",
            "reason": "AI_UNAVAILABLE",
            "queries": [],
            "priorites": [],
        }

    hippo = getattr(race, "hippodrome", "") or ""
    date_s = (getattr(race, "date_course", None) or "")[:10]
    disc = str(getattr(race, "discipline", "") or "")
    system = (
        "Tu es expert courses hippiques PMU (trot/plat). "
        "On enrichit des donnees manquantes AVANT scoring. "
        "Reponds UNIQUEMENT en JSON valide avec cles: "
        "priorites (liste), queries (liste), conseils (liste), sources_suggerees (liste). "
        "Max 6 queries, max 5 priorites. Requetes en francais date+hippodrome. "
        "Trot GNT: privilegier Dist/recul, ferrure, gains_moyenne."
    )
    user = (
        "Course: {hippo} {date} discipline={disc}\n"
        "Lacunes: {lac}\n"
        "Couverture: {cov}\n"
        "Propose un plan d'enrichissement web minimal et operationnel."
    ).format(
        hippo=hippo,
        date=date_s,
        disc=disc,
        lac=str(lacunes[:25]),
        cov=str(resume_couverture)[:500] if resume_couverture else "n/a",
    )
    ai = _llm(system, user)
    if ai.get("status") != "OK" or not ai.get("text"):
        return {
            "status": ai.get("status") or "ERROR",
            "error": ai.get("error") or ai.get("note") or "no text",
            "provider": ai.get("provider"),
            "queries": [],
            "priorites": [],
        }
    raw = ai["text"]
    try:
        mjson = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(mjson.group(0) if mjson else raw)
        return {
            "status": "OK",
            "provider": ai.get("provider"),
            "priorites": data.get("priorites") or [],
            "queries": data.get("queries") or [],
            "conseils": data.get("conseils") or [],
            "sources_suggerees": data.get("sources_suggerees") or [],
            "raw_preview": raw[:300],
        }
    except Exception as e:
        logger.warning("guide_enrichment parse: %s", e)
        return {
            "status": "OK_PARTIAL",
            "provider": ai.get("provider"),
            "priorites": list(lacunes)[:5],
            "queries": [
                f"{hippo} {date_s} partants",
                f"site:turfomania.fr {hippo} {date_s}",
                f"site:letrot.com {hippo} {date_s}",
            ],
            "conseils": ["parse JSON echoue — queries heuristiques"],
            "raw_preview": raw[:300],
            "error": str(e)[:120],
        }




def ai_runtime_status() -> Dict[str, Any]:
    """Statut opérationnel IA pour rapports / health."""
    return {
        "ai_enabled": AI_ENABLED,
        "provider_preferred": _provider_available(),
        "providers_configured": {
            "groq": bool(_env_key("GROQ_API_KEY")),
            "gemini": bool(_env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")),
            "anthropic": bool(_env_key("ANTHROPIC_API_KEY")),
        },
        "models": {
            "groq_primary": GROQ_MODEL,
            "groq_fallbacks": GROQ_MODEL_FALLBACKS,
            "gemini_primary": GEMINI_MODEL,
            "gemini_fallbacks": GEMINI_MODEL_FALLBACKS,
        },
        "qualitative_signal": AI_QUALITATIVE_SIGNAL,
        "timeout_sec": AI_TIMEOUT_SEC,
        # v1.29.43 -- modules IA Claude (collection.py / qualitative.py)
        "modules_ia": {
            "cle_ia_presente": _provider_available() is not None,
            "fournisseurs": {"groq": bool(_env_key("GROQ_API_KEY")), "gemini": bool(_env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")),
                             "anthropic": bool(_env_key("ANTHROPIC_API_KEY"))},
            "ordre_taches_textuelles": os.environ.get("AI_PROVIDER_ORDER", "gemini,groq,anthropic"),
            "collecte_ia_mode": ("navigation web (Anthropic)" if _env_key("ANTHROPIC_API_KEY") else "extraction du texte des pages (Gemini/Groq)"),
            "collecte_ia_de_secours": os.environ.get("AI_COLLECTION_FALLBACK", "1") != "0",
            "qualitative_llm_active": os.environ.get("AI_QUALITATIVE_LLM", "1") == "1",
            "qualitative_plafond_pch": float(os.environ.get("AI_QUALITATIVE_CAP_PCH", "6")),
            "operationnels": AI_ENABLED and _provider_available() is not None,
        },
    }


def _ping_model(provider: str, key: str, model: str) -> Dict[str, Any]:
    """Une requête minimale sur UN modèle : résultat lisible (ok/erreur) pour le diagnostic."""
    import time as _t
    t0 = _t.time()
    try:
        if provider == "groq":
            out = _http_json("https://api.groq.com/openai/v1/chat/completions",
                             {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                             {"model": model, "messages": [{"role": "user", "content": "Réponds OK"}], "max_tokens": 16}, 20)
            txt = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        else:
            out = _http_json(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={urllib.parse.quote(key)}",
                             {"Content-Type": "application/json"},
                             {"contents": [{"role": "user", "parts": [{"text": "Réponds OK"}]}], "generationConfig": {"maxOutputTokens": 16}}, 20)
            parts = (((out.get("candidates") or [{}])[0]).get("content") or {}).get("parts") or []
            txt = "".join(p.get("text", "") for p in parts)
        return {"modele": model, "ok": True, "reponse": txt.strip()[:30] or "(vide)", "duree_s": round(_t.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        return {"modele": model, "ok": False, "erreur": f"{type(e).__name__}: {str(e)[:160]}", "duree_s": round(_t.time() - t0, 1)}


def test_providers() -> Dict[str, Any]:
    """Diagnostic complet depuis le téléphone : pour Groq et Gemini, liste les modèles RÉELLEMENT disponibles pour la clé
    et teste chaque candidat (jusqu'au premier qui répond) ; Anthropic : un ping."""
    out: Dict[str, Any] = {}
    gkey = _env_key("GROQ_API_KEY")
    if not gkey:
        out["groq"] = {"configure": False}
    else:
        dispo = _groq_list_models(gkey)
        cands = list(dict.fromkeys([GROQ_MODEL] + GROQ_MODEL_FALLBACKS + dispo[:6]))[:8]
        essais = []
        for m in cands:
            r = _ping_model("groq", gkey, m)
            essais.append(r)
            if r["ok"]:
                break
        out["groq"] = {"configure": True, "ok": any(r["ok"] for r in essais), "modeles_disponibles": dispo[:15], "essais": essais}
    mkey = _env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not mkey:
        out["gemini"] = {"configure": False}
    else:
        dispo = _gemini_list_models(mkey)
        cands = list(dict.fromkeys([GEMINI_MODEL] + GEMINI_MODEL_FALLBACKS + dispo[:4]))[:9]
        essais = []
        for m in cands:
            r = _ping_model("gemini", mkey, m)
            essais.append(r)
            if r["ok"]:
                break
        out["gemini"] = {"configure": True, "ok": any(r["ok"] for r in essais),
                         "modeles_disponibles": dispo[:15] or "ListModels vide ou refusé (clé sans accès à l'API Generative Language ?)",
                         "essais": essais}
    if not _env_key("ANTHROPIC_API_KEY"):
        out["anthropic"] = {"configure": False}
    else:
        r = _ping_model_anthropic()
        out["anthropic"] = {"configure": True, **r}
    out["au_moins_un_ok"] = any(isinstance(v, dict) and v.get("ok") for v in out.values())
    return out


def _ping_model_anthropic() -> Dict[str, Any]:
    import time as _t
    t0 = _t.time()
    try:
        txt = _call_anthropic("Réponds uniquement par le mot OK.", "ping", max_tokens=20, timeout=20)
        return {"ok": bool(txt.strip()), "reponse": txt.strip()[:30], "duree_s": round(_t.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:200]}", "duree_s": round(_t.time() - t0, 1)}
