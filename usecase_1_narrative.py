from llm_engine import ask_llama
from prompt_builder import timeseries_row_to_context

SYSTEM_PROMPT = """
Tu es un expert réseau télécom.
Tu réponds uniquement en français.

Tu dois produire exactement 3 sections :
1. Résumé exécutif
2. Explication technique
3. Recommandation immédiate

Règles strictes :
- Ne pas inventer d'informations absentes
- Être clair, professionnel et factuel
- Si le throughput est nul, mentionner qu'il peut s'agir d'une absence de transfert actif
  ou d'un incident de connectivité selon le contexte
- Ne pas conclure à une congestion si bandwidth_util_pct est très faible ou nulle
- Chaque section doit être complète
"""


def generate_narrative(row: dict) -> str:
    context = timeseries_row_to_context(row)

    user_prompt = f"""
Voici une mesure réseau :

{context}

Rédige :
1. Un résumé exécutif pour un manager
2. Une explication technique pour un ingénieur
3. Une recommandation d'action immédiate
"""
    return ask_llama(SYSTEM_PROMPT, user_prompt)