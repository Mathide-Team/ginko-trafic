"""Le tableau de bord d'exemple (exemples/tableau-de-bord.yaml) se rend sans erreur (issue #4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from tests.test_init import LIGNE_BUS, LIGNE_TRAM, _build_app, _demarrer

VUE = yaml.safe_load((Path(__file__).parents[1] / "exemples" / "tableau-de-bord.yaml").read_text())


@pytest.fixture(autouse=True)
def _socket_autorise(socket_enabled):
    """Autorise le serveur HTTP local des tests."""
    yield


@pytest.fixture
async def client():
    test_client = TestClient(TestServer(_build_app()))
    await test_client.start_server()
    yield test_client
    await test_client.close()


def _cartes_markdown(cartes: list[dict]) -> list[dict]:
    resultat = []
    for carte in cartes:
        if carte.get("type") == "conditional":
            resultat.extend(_cartes_markdown([carte["card"]]))
        elif carte.get("type") == "markdown":
            resultat.append(carte)
    return resultat


def _rendre(hass: HomeAssistant, gabarit: str) -> str:
    return Template(gabarit, hass).async_render(parse_result=False)


async def test_rendu_avec_abonnement(hass: HomeAssistant, client: TestClient) -> None:
    hass.config.language = "fr"
    await _demarrer(
        hass,
        client,
        {
            "lignes": [LIGNE_TRAM, LIGNE_BUS],
            "abonnements": [{"arret": "Exemple Mairie", "id_ligne": LIGNE_TRAM, "sens_aller": True}],
        },
    )
    cartes = {c.get("title", ""): c for c in _cartes_markdown(VUE["cards"])}
    passages = _rendre(hass, cartes["Prochains passages"]["content"])
    assert "Exemple Mairie" in passages
    assert "**3 min**" in passages
    assert "Exemple Sud" in passages
    lignes = [ligne for ligne in passages.splitlines() if ligne.startswith("|")]
    # En-tête, séparateur, une ligne par abonnement : tableau Markdown valide.
    assert len(lignes) == 3
    assert all(ligne.count("|") == 6 for ligne in lignes)
    trafic = _rendre(hass, cartes["Info trafic"]["content"])
    assert "perturbation en cours" in trafic
    assert "normale" in trafic
    # Bandeau : condition vraie (tram perturbé) et message affiché.
    conditionnelle = next(c for c in VUE["cards"] if c["type"] == "conditional")
    assert _rendre(hass, conditionnelle["conditions"][0]["value_template"]) == "True"
    bandeau = _rendre(hass, conditionnelle["card"]["content"])
    assert "1 ligne perturbée" in bandeau
    assert "Travaux voie tram" in bandeau
    # Chaque message sur sa propre ligne de liste.
    assert any(ligne.startswith("- ") and "Travaux voie tram" in ligne for ligne in bandeau.splitlines())
    # Une ligne par ligne de transport dans l'info trafic.
    assert len([ligne for ligne in trafic.splitlines() if "mdi:" in ligne]) == 2


async def test_rendu_sans_abonnement(hass: HomeAssistant, client: TestClient) -> None:
    hass.config.language = "fr"
    await _demarrer(hass, client, {"lignes": [LIGNE_BUS]})
    cartes = {c.get("title", ""): c for c in _cartes_markdown(VUE["cards"])}
    assert "Aucun abonnement" in _rendre(hass, cartes["Prochains passages"]["content"])
    conditionnelle = next(c for c in VUE["cards"] if c["type"] == "conditional")
    assert _rendre(hass, conditionnelle["conditions"][0]["value_template"]) == "False"
