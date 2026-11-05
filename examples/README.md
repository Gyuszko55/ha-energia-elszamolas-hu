# Rezsikövető – példák

## Hangparancs: „van befizetendő számlám?”

A Rezsikövető (2.4.0-tól) elmondja, milyen számlákat kell még befizetned, mennyit, és hány nap múlva
esedékesek – a lejártakat külön („2 napja lejárt”). A csoportos beszedéses és az állandó átutalásos számlák
kimaradnak (ott nincs teendő).

- **LLM-es Assist-ügynöknél** (Google Gemini, OpenAI, Anthropic, Ollama…) nincs teendő: az ügynök beállításaiban
  legyen bekapcsolva az **Assist** – a Rezsikövető ott eszközként (`hu_rezsi__befizetendo_szamlak`) adja.
- **A helyi (beépített) Assisthoz** a magyar mondatok kellenek: másold a
  [custom_sentences/hu/hu_rezsi.yaml](custom_sentences/hu/hu_rezsi.yaml) fájlt a Home Assistant
  `config/custom_sentences/hu/` mappájába, majd töltsd újra a beszélgetést (vagy indítsd újra a HA-t).

Példamondatok: „Van befizetendő számlám?”, „Milyen számlát kell befizetnem?”, „Van lejárt számlám?”, „Mikor
esedékes a következő számla?”.

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
