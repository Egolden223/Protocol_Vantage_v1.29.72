import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_WEB_SEARCHES = int(os.environ.get("MAX_WEB_SEARCHES", "20"))
MAX_WEB_FETCHES = int(os.environ.get("MAX_WEB_FETCHES", "10"))
DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "vantage.db"))
PROTOCOL_ASSETS_DIR = Path(__file__).resolve().parent / "protocol_assets"

# Sources autorisées pour web_search / web_fetch (Bloc P, Partie 2bis) --
# laissé ouvert (None) par défaut pour ne pas bloquer un hippodrome/source
# non listé ; peut être restreint via la variable d'environnement si souhaité.
ALLOWED_SEARCH_DOMAINS = os.environ.get("ALLOWED_SEARCH_DOMAINS", "").split(",") if os.environ.get("ALLOWED_SEARCH_DOMAINS") else None

# --- Supervision IA optionnelle (v1.29.13) ---
# Priorité: GROQ_API_KEY > GEMINI_API_KEY > ANTHROPIC_API_KEY
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
AI_SUPERVISOR = os.environ.get("AI_SUPERVISOR", "1")
AI_APPLY_BOUNDED_REPAIRS = os.environ.get("AI_APPLY_BOUNDED_REPAIRS", "0")

# --- Web search étape 2.7 (Google + repli DDG) ---
# Google Custom Search (recommandé) :
#   GOOGLE_CSE_API_KEY  ou GOOGLE_API_KEY
#   GOOGLE_CSE_CX       (Search Engine ID, console.cloud.google.com/apis)
# SerpAPI (optionnel) : SERPAPI_KEY
# Sans clé → DuckDuckGo HTML uniquement.

# --- Modules IA Claude (v1.29.43) -- nécessitent ANTHROPIC_API_KEY ---
# Collecte IA de secours : utilisée UNIQUEMENT si toutes les sources Python échouent (défaut : active).
AI_COLLECTION_FALLBACK = os.environ.get("AI_COLLECTION_FALLBACK", "1")
# Couche qualitative IA (commentaires + pronostics/presse) : AJOUTE des signaux bornés (+/- 6 PCH par cheval).
# Active par défaut ; AI_QUALITATIVE_LLM=0 pour la couper.
AI_QUALITATIVE_LLM = os.environ.get("AI_QUALITATIVE_LLM", "1")   # activée (12/10/2026), sans effet sans clé IA
AI_QUALITATIVE_CAP_PCH = float(os.environ.get("AI_QUALITATIVE_CAP_PCH", "6"))   # plafond +/- par cheval
# Autres tâches IA (v1.29.44) : réparation des champs manquants, résumé de course (analyse des ratés : à la demande)
AI_REPAIR = os.environ.get("AI_REPAIR", "1")
AI_SUMMARY = os.environ.get("AI_SUMMARY", "1")
AI_POSTRACE = os.environ.get("AI_POSTRACE", "1")   # analyse IA post-course (explications à preuve vérifiée)

# --- Sauvegarde Hugging Face (v1.29.46) : chaque course (+ son audit) est envoyée dans un dataset HF privé,
# car le disque Render est perdu à chaque redéploiement / mise en veille (plan sans disque persistant).
HF_TOKEN = os.environ.get("HF_TOKEN", "")                  # jeton HF avec droit d'ÉCRITURE (secret Render)
HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "")    # ex. "monpseudo/vantage-historique"
HF_AUTOSAVE = os.environ.get("HF_AUTOSAVE", "1")           # 0 = désactivé
HF_RESTORE_ON_START = os.environ.get("HF_RESTORE_ON_START", "1")   # recharger l'historique au démarrage
HF_RESTORE_LIMIT = int(os.environ.get("HF_RESTORE_LIMIT", "300"))
# En REJEU (course déjà courue) les pages web contiennent résultats et comptes rendus : toute IA qui LIT ces pages pour
# influencer le ticket (qualitatif, réparation) est coupée par défaut -> pas de fuite d'information dans les calibrations.
AI_REJEU_INFLUENCE = os.environ.get("AI_REJEU_INFLUENCE", "0")
