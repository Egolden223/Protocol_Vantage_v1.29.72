"""
client.py -- Client Claude en HTTP direct (v1.29.43) : AUCUN package à installer.

Avant : dépendait du SDK `anthropic`, absent de requirements.txt -> ImportError dès qu'un module
(collection.py / qualitative.py) était chargé : ces modules ne pouvaient jamais fonctionner.
Maintenant : urllib (stdlib), même interface (ClaudeClient.run / run_json) + :
  * web_search / web_fetch côté serveur Anthropic (outils optionnels) ;
  * reprise automatique des tours « pause_turn » (recherches longues) ;
  * repli progressif : sans web_fetch, puis sans aucun outil, si l'API refuse la requête ;
  * erreurs explicites (clé absente, quota, réseau) -> ClaudeUnavailable, jamais de plantage opaque.
"""
from __future__ import annotations
import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from app import config

logger = logging.getLogger("vantage.llm")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class ClaudeUnavailable(RuntimeError):
    """Clé absente, quota dépassé ou réseau indisponible : l'appelant dégrade proprement."""


def _api_key() -> str:
    return (os.environ.get("ANTHROPIC_API_KEY") or config.ANTHROPIC_API_KEY or "").strip().strip('"').strip("'")


def claude_available() -> bool:
    return bool(_api_key())


class ClaudeClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: int = 120):
        self.key = (api_key or _api_key()).strip()
        if not self.key:
            raise ClaudeUnavailable("ANTHROPIC_API_KEY manquant (variable d'environnement Render).")
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or config.ANTHROPIC_MODEL
        self.timeout = timeout

    # --- outils serveur ---
    def _tools(self, web_search: bool, web_fetch: bool, allowed_domains: Optional[List[str]]) -> List[Dict]:
        tools: List[Dict] = []
        if web_search:
            t: Dict[str, Any] = {"type": "web_search_20250305", "name": "web_search", "max_uses": config.MAX_WEB_SEARCHES}
            if allowed_domains:
                t["allowed_domains"] = allowed_domains
            tools.append(t)
        if web_fetch:
            t = {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": config.MAX_WEB_FETCHES}
            if allowed_domains:
                t["allowed_domains"] = allowed_domains
            tools.append(t)
        return tools

    def _post(self, payload: Dict[str, Any], beta: bool) -> Dict[str, Any]:
        headers = {"x-api-key": self.key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        if beta:
            headers["anthropic-beta"] = "web-fetch-2025-09-10"
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            raise _HttpError(e.code, body) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ClaudeUnavailable(f"Réseau/API Anthropic indisponible : {e}") from None

    def run(self, system: str, user: str, *, max_tokens: int = 8000, web_search: bool = True,
            web_fetch: bool = True, allowed_domains: Optional[List[str]] = None) -> str:
        plans = []
        if web_search or web_fetch:
            plans.append((web_search, web_fetch))
            if web_fetch:
                plans.append((web_search, False))      # repli : sans web_fetch (bêta)
            plans.append((False, False))               # repli : sans outil
        else:
            plans.append((False, False))
        last: Optional[Exception] = None
        for ws, wf in plans:
            tools = self._tools(ws, wf, allowed_domains)
            try:
                return self._run_once(system, user, max_tokens, tools, beta=wf)
            except _HttpError as e:
                last = e
                if e.code in (401, 403):
                    raise ClaudeUnavailable(f"Clé Anthropic refusée (HTTP {e.code}).") from None
                if e.code == 429:
                    raise ClaudeUnavailable("Quota/limite Anthropic atteint (HTTP 429).") from None
                logger.warning("Anthropic HTTP %s avec outils (ws=%s wf=%s) : %s -- repli", e.code, ws, wf, e.body[:160])
        raise ClaudeUnavailable(f"Requête Anthropic refusée : {last}")

    def _run_once(self, system: str, user: str, max_tokens: int, tools: List[Dict], beta: bool) -> str:
        messages: List[Dict[str, Any]] = [{"role": "user", "content": user}]
        texts: List[str] = []
        for _ in range(5):                              # reprises pause_turn
            payload: Dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "system": system, "messages": messages}
            if tools:
                payload["tools"] = tools
            out = self._post(payload, beta)
            content = out.get("content", [])
            texts = [b.get("text", "") for b in content if b.get("type") == "text"]
            if out.get("stop_reason") == "pause_turn":
                messages = [messages[0], {"role": "assistant", "content": content}]
                continue
            break
        return "\n".join(texts)

    def run_json(self, system: str, user: str, *, schema_hint: str = "", **kwargs) -> Dict[str, Any]:
        full_system = (system.rstrip() + "\n\nCONSIGNE DE FORMAT (impérative) : ta réponse finale doit être "
                       "UNIQUEMENT un objet JSON valide, sans texte avant ni après, sans balises markdown. " + schema_hint)
        return parse_json_loose(self.run(full_system, user, **kwargs))


class _HttpError(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f"HTTP {code}: {body[:120]}")
        self.code, self.body = code, body


def parse_json_loose(raw: str) -> Dict[str, Any]:
    """Tolère un léger bruit autour du JSON (code fences, phrase d'intro)."""
    txt = raw.strip()
    txt = re.sub(r"^```(json)?", "", txt.strip())
    txt = re.sub(r"```$", "", txt.strip())
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    start, end = txt.find("{"), txt.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(txt[start:end + 1])
        except json.JSONDecodeError as e:
            logger.error("Échec de parsing JSON depuis la réponse LLM : %s\n---\n%s", e, raw[:2000])
            raise
    raise ValueError(f"Aucun JSON trouvé dans la réponse LLM :\n{raw[:2000]}")


# =====================================================================================
# LLMClient (v1.29.43) -- multi-fournisseurs : Groq / Gemini (clés GRATUITES) / Anthropic
# =====================================================================================
def _provider_keys() -> Dict[str, bool]:
    from app.llm import supervisor as S
    return {
        "groq": bool(S._env_key("GROQ_API_KEY")),
        "gemini": bool(S._env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")),
        "anthropic": bool(S._env_key("ANTHROPIC_API_KEY")),
    }


def ai_available() -> bool:
    """Au moins UNE clé IA (Groq, Gemini ou Anthropic) et AI_SUPERVISOR non désactivé."""
    from app.llm import supervisor as S
    return S.AI_ENABLED and any(_provider_keys().values())


class LLMClient:
    """Même interface que ClaudeClient (run_json), mais route vers le premier fournisseur disponible.

    * Anthropic : seul à pouvoir naviguer sur le web (web_search/web_fetch) -> utilisé en priorité
      quand la navigation est demandée ET qu'une clé Anthropic existe.
    * Gemini / Groq (gratuits) : pas de navigation -> on leur fournit le TEXTE des pages (voir
      collection.py) ; sortie JSON forcée. Ordre par défaut pour les tâches textuelles :
      AI_PROVIDER_ORDER (défaut « gemini,groq,anthropic » : grand contexte d'abord).
    Un fournisseur qui échoue (quota, clé, JSON tronqué) -> on passe au suivant.
    """

    def __init__(self, timeout: int = 90, order: Optional[List[str]] = None):
        if not ai_available():
            raise ClaudeUnavailable("Aucune clé IA : définir GEMINI_API_KEY et/ou GROQ_API_KEY (gratuites) "
                                    "ou ANTHROPIC_API_KEY.")
        self.timeout = timeout
        self.order = order or [p.strip() for p in os.environ.get("AI_PROVIDER_ORDER", "gemini,groq,anthropic").split(",") if p.strip()]
        self.last_provider: Optional[str] = None

    def can_browse(self) -> bool:
        return _provider_keys()["anthropic"]

    def run_json(self, system: str, user: str, *, schema_hint: str = "", max_tokens: int = 8000,
                 web_search: bool = False, web_fetch: bool = False,
                 allowed_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        from app.llm import supervisor as S
        keys = _provider_keys()
        full_system = (system.rstrip() + "\n\nCONSIGNE DE FORMAT (impérative) : réponds UNIQUEMENT par un objet "
                       "JSON valide, sans texte autour, sans balises markdown. " + schema_hint)
        errors: List[str] = []
        # Navigation demandée + clé Anthropic -> Claude avec outils web en premier
        if (web_search or web_fetch) and keys["anthropic"]:
            try:
                out = ClaudeClient(timeout=max(self.timeout, 120)).run_json(
                    system, user, schema_hint=schema_hint, max_tokens=max_tokens, web_search=web_search,
                    web_fetch=web_fetch, allowed_domains=allowed_domains)
                self.last_provider = "anthropic+web"
                return out
            except Exception as e:  # noqa: BLE001
                errors.append(f"anthropic+web: {str(e)[:120]}")
        for prov in self.order:
            if not keys.get(prov):
                continue
            try:
                fn = {"groq": S._call_groq, "gemini": S._call_gemini, "anthropic": S._call_anthropic}[prov]
                text = fn(full_system, user, max_tokens=max_tokens, json_mode=(prov != "anthropic"), timeout=self.timeout)
                data = parse_json_loose(text or "")
                self.last_provider = prov
                return data
            except Exception as e:  # noqa: BLE001
                errors.append(f"{prov}: {str(e)[:120]}")
                logger.warning("LLMClient %s a échoué : %s", prov, e)
        raise ClaudeUnavailable("Aucun fournisseur IA n'a répondu : " + " | ".join(errors)[:400])
