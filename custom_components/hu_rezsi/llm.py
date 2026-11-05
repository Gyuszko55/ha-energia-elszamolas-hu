"""LLM-eszközök az Assist-ügynöknek (pl. Gemini): a Rezsikövető hangutasításai (HA 2026.x `llm` platform).

Régebbi HA-n ez a fájl nem töltődik be; ott az Assist API a regisztrált szándékokat (intent) magától adja az ügynöknek.
"""

from __future__ import annotations

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent
from homeassistant.helpers.llm import LLM_API_ASSIST, IntentTool, LLMContext

from .const import DOMAIN
from .hang import RezsiIntent


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    if api_id != LLM_API_ASSIST:
        return None
    kezelok = [h for h in intent.async_get(hass) if isinstance(h, RezsiIntent)]
    if not kezelok:
        return None
    return LLMTools(tools=[IntentTool(f"{DOMAIN}__{h.eszkoz_nev}", h, integration=DOMAIN, title=h.eszkoz_cim)
                           for h in kezelok])
