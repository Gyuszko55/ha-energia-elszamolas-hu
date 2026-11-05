# Rezsikövető – példák

## Hangparancsok

A Rezsikövető (2.4.0-tól) hangon is válaszol – mindegyik kérdéshez odamondható a közmű (villany/áram, gáz, víz,
távhő/fűtés, szemét, internet, közös költség):

| Példa | Válasz |
|---|---|
| „Van befizetendő számlám?”, „Van befizetendő gázszámlám?” | a még be nem fizetett számlák összeggel, hány nap múlva esedékes / hány napja lejárt |
| „Mikor jön a következő számla?”, „Mennyi lesz a következő vízszámla?” | a várható következő számla összege és ideje |
| „Mennyi a rezsi eddig?”, „Mennyi a villany eddig?” | a folyó időszak költsége eddig és várhatóan |
| „Hol tartok a keretben?”, „Hol tartok a gázkeretben?” | a kedvezményes keretből hátralévő, és mikor lépi túl |
| „Mennyi volt az utolsó villanyszámla?” | a legutóbbi számla összege és kelte |

- **LLM-es Assist-ügynöknél** (Google Gemini, OpenAI, Anthropic, Ollama…) nincs teendő: az ügynök beállításaiban
  legyen bekapcsolva az **Assist** – a Rezsikövető ott eszközként adja őket.
- **A helyi (beépített) Assisthoz** a magyar mondatok kellenek: másold a
  [custom_sentences/hu/hu_rezsi.yaml](custom_sentences/hu/hu_rezsi.yaml) fájlt a Home Assistant
  `config/custom_sentences/hu/` mappájába, majd töltsd újra a beszélgetést (vagy indítsd újra a HA-t).

Automatizálásból is hívható (pl. reggeli összefoglaló):

```yaml
- action: conversation.process
  data:
    language: hu
    text: "van befizetendő számlám"
  response_variable: valasz
- action: notify.mobile_app_telefonom
  data:
    message: "{{ valasz.response.speech.plain.speech }}"
```
