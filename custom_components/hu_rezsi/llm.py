"""LLM-eszköz az Assist-ügynöknek (pl. Gemini): a befizetendő számlák lekérdezése (HA 2026.x `llm` platform).

Régebbi HA-n ez a fájl nem töltődik be; ott az Assist API a regisztrált szándékot (intent) magától adja az ügynöknek.
"""

from __future__ import annotations

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent
from homeassistant.helpers.llm import LLM_API_ASSIST, IntentTool, LLMContext

from .const import DOMAIN
from .hatarido_ertesites import BefizetendoIntent


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    if api_id != LLM_API_ASSIST:
        return None
    kezelo = next((h for h in intent.async_get(hass) if isinstance(h, BefizetendoIntent)), None)
    if kezelo is None:
        return None
    return LLMTools(tools=[IntentTool(f"{DOMAIN}__befizetendo_szamlak", kezelo, integration=DOMAIN,
                                      title="Befizetendő számlák")])
