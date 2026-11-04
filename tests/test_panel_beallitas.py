"""A panel integráció szintű beállításai (hu_rezsi/panel_beallitas): az automatikus bezárás ideje – olvasni
mindenki, írni csak rendszergazda; ellenőrzött érték (0–600 mp, 0 = soha)."""

from types import SimpleNamespace

import pytest

import tests.conftest  # noqa: F401
from tests.test_email_felderites import _ws

from custom_components.hu_rezsi import panel, panel_beallitas


def test_panel_beallitas_olvasas_mindenkinek_iras_adminnak(monkeypatch):
    tarolt = {}

    class Tar:
        def __init__(self, hass, ver, kulcs):
            pass

        async def async_load(self):
            return tarolt.get("x")

        async def async_save(self, adat):
            tarolt["x"] = dict(adat)

    monkeypatch.setattr(panel_beallitas, "Store", Tar)
    hass = SimpleNamespace(data={})
    k = _ws(panel.ws_panel_beallitas, hass, {"type": "hu_rezsi/panel_beallitas"}, admin=False)
    assert k.eredmeny == {"auto_bezaras_mp": 10}
    k = _ws(panel.ws_panel_beallitas, hass, {"beallitas": {"auto_bezaras_mp": 30}}, admin=False)
    assert k.hiba[0] == "unauthorized" and tarolt == {}
    k = _ws(panel.ws_panel_beallitas, hass, {"beallitas": {"auto_bezaras_mp": 30}})
    assert k.eredmeny == {"auto_bezaras_mp": 30} and tarolt["x"] == {"auto_bezaras_mp": 30}
    assert panel_beallitas.aktualis(hass) == {"auto_bezaras_mp": 30}
    k = _ws(panel.ws_panel_beallitas, hass, {"beallitas": {"auto_bezaras_mp": 9999}})
    assert k.hiba[0] == "hibas_ertek"
    assert _ws(panel.ws_panel_beallitas, hass, {"beallitas": {"auto_bezaras_mp": "0"}}).eredmeny == {"auto_bezaras_mp": 0}
    with pytest.raises(ValueError):
        panel_beallitas.ervenyes({"auto_bezaras_mp": "sok"})
