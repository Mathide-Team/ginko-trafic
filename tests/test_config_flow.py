"""Tests des flux de configuration et d'options."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ginko_trafic.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
CLE = "CLE-TEST-123"
MAUVAISE_CLE = "MAUVAISE"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _reponse(nom: str) -> web.Response:
    return web.json_response(json.loads(_lire(nom)))


def _build_app() -> web.Application:
    """Serveur factice reproduisant les routes Ginko."""

    async def get_lignes(request: web.Request) -> web.Response:
        if request.query.get("apiKey") == MAUVAISE_CLE:
            return _reponse("erreur_cle.json")
        return _reponse("lignes.json")

    async def get_details_variante(request: web.Request) -> web.Response:
        return _reponse("details_variante.json")

    app = web.Application()
    app.router.add_get("/DR/getLignes.do", get_lignes)
    app.router.add_get("/DR/getDetailsVariante.do", get_details_variante)
    return app


@pytest.fixture(autouse=True)
def _socket_autorise(socket_enabled):
    """Autorise le serveur HTTP local des tests."""
    yield


@pytest.fixture
async def client():
    server = TestServer(_build_app())
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


@pytest.fixture
def api_locale(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Pointe le client Ginko vers le serveur factice pendant tout le test."""
    monkeypatch.setattr(
        "custom_components.ginko_trafic.api.BASE_URL",
        str(client.make_url("/")),
    )
    return client


async def test_flux_configuration(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Clé validée puis choix des lignes : l'entrée est créée."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["step_id"] == "user"
    # Clé refusée : le formulaire revient avec l'erreur.
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {"cle_api": MAUVAISE_CLE})
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"cle_api": "cle_invalide"}
    # Clé valide : étape des lignes.
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {"cle_api": CLE})
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["step_id"] == "lignes"
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {"lignes": ["901", "902"]})
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert resultat["data"] == {"cle_api": CLE}
    assert resultat["options"]["lignes"] == ["901", "902"]
    assert resultat["options"]["abonnements"] == []


async def test_deja_configure(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Le réseau Ginko ne se configure qu'une fois."""
    existante = MockConfigEntry(
        domain=DOMAIN,
        data={"cle_api": CLE},
        options={"lignes": [], "abonnements": []},
        unique_id="reseau-ginko",
    )
    existante.add_to_hass(hass)
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {"cle_api": CLE})
    assert resultat["type"] is FlowResultType.ABORT
    assert resultat["reason"] == "already_configured"


async def _options_init(hass: HomeAssistant, entry) -> object:
    return await hass.config_entries.options.async_init(entry.entry_id)


async def test_options_retrait_abonnement(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Désélectionner un abonnement le supprime."""
    hass.config.language = "fr"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"cle_api": CLE},
        options={
            "lignes": ["901"],
            "abonnements": [{"arret": "Exemple Mairie", "id_ligne": "901", "sens_aller": True}],
        },
        unique_id="reseau-ginko",
    )
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["step_id"] == "init"
    # Soumission sans sélection d'abonnement : il est retiré.
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"lignes": ["901"], "abonnements": [], "ajouter": False},
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["abonnements"] == []
    assert entry.options["lignes"] == ["901"]


async def test_options_ajout_abonnement(hass: HomeAssistant, api_locale: TestClient) -> None:
    """L'ajout traverse ligne, sens puis arrêt, sans dupliquer."""
    hass.config.language = "fr"
    abonnement_existant = {
        "arret": "Exemple Mairie",
        "id_ligne": "901",
        "sens_aller": True,
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"cle_api": CLE},
        options={"lignes": ["901"], "abonnements": [abonnement_existant]},
        unique_id="reseau-ginko",
    )
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {
            "lignes": ["901"],
            "abonnements": [json.dumps(abonnement_existant, sort_keys=True)],
            "ajouter": True,
        },
    )
    # Étape 1/3 : la ligne.
    assert resultat["step_id"] == "abonnement_ligne"
    resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"ligne": "902"})
    # Étape 2/3 : le sens (variante aller de la ligne 902).
    assert resultat["step_id"] == "abonnement_sens"
    resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"sens": "902-0"})
    # Étape 3/3 : l'arrêt.
    assert resultat["step_id"] == "abonnement_arret"
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"arret": "Exemple Mairie"}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    abonnements = entry.options["abonnements"]
    assert len(abonnements) == 2
    assert {
        "arret": "Exemple Mairie",
        "id_ligne": "902",
        "sens_aller": True,
    } in abonnements

    # Un abonnement identique n'est pas dupliqué.
    resultat = await _options_init(hass, entry)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {
            "lignes": ["901"],
            "abonnements": [json.dumps(a, sort_keys=True) for a in abonnements],
            "ajouter": True,
        },
    )
    resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"ligne": "901"})
    resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"sens": "901-0"})
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"arret": "Exemple Mairie"}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    # L'abonnement 901 aller à Exemple Mairie existait déjà : pas de doublon.
    assert len(entry.options["abonnements"]) == 2


async def test_options_ligne_absente_du_jour(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une ligne suivie absente du service du jour reste conservable.

    Le sélecteur propose l'union des lignes du jour et des lignes
    suivies ; réenregistrer sans modification ne perd rien.
    """
    hass.config.language = "fr"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"cle_api": CLE},
        options={"lignes": ["901", "999"], "abonnements": []},
        unique_id="reseau-ginko",
    )
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    assert resultat["type"] is FlowResultType.FORM
    # 999 (non retournée par l'API) et 901 sont toutes deux proposées.
    cle = next(k for k in resultat["data_schema"].schema if str(k).endswith("lignes"))
    selection = resultat["data_schema"].schema[cle].options
    assert "999" in selection
    assert "901" in selection
    # Soumission inchangée : les deux lignes restent suivies.
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"lignes": ["901", "999"], "abonnements": [], "ajouter": False},
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["lignes"] == ["901", "999"]


async def test_options_ajout_panne_arret(
    hass: HomeAssistant, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un échec de récupération des arrêts propose un réessai, pas une saisie libre."""
    hass.config.language = "fr"
    echecs = {"restants": 1}

    async def get_details_variante(request: web.Request) -> web.Response:
        if echecs["restants"] > 0:
            echecs["restants"] -= 1
            return web.Response(status=500)
        return _reponse("details_variante.json")

    app = web.Application()
    app.router.add_get("/DR/getLignes.do", lambda r: _reponse("lignes.json"))
    app.router.add_get("/DR/getDetailsVariante.do", get_details_variante)
    app.router.add_get("/TR/getListeTemps.do", lambda r: _reponse("reponse_vide.json"))
    app.router.add_get("/TR/getEtatLignes.do", lambda r: _reponse("etat_lignes.json"))
    app.router.add_get("/TR/getMessages.do", lambda r: _reponse("messages.json"))
    serveur = TestClient(TestServer(app))
    await serveur.start_server()
    monkeypatch.setattr(
        "custom_components.ginko_trafic.api.BASE_URL",
        str(serveur.make_url("/")),
    )
    try:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"cle_api": CLE},
            options={"lignes": ["901"], "abonnements": []},
            unique_id="reseau-ginko",
        )
        entry.add_to_hass(hass)
        resultat = await _options_init(hass, entry)
        resultat = await hass.config_entries.options.async_configure(
            resultat["flow_id"],
            {"lignes": ["901"], "abonnements": [], "ajouter": True},
        )
        resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"ligne": "902"})
        resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"sens": "902-0"})
        # La récupération des arrêts échoue : retour au choix du sens avec
        # l'erreur, jamais un champ de saisie libre d'arrêt.
        assert resultat["step_id"] == "abonnement_sens"
        assert resultat["errors"] == {"base": "cannot_connect"}
        assert "arret" not in str(resultat["data_schema"].schema)
        # Le réenvoi du sens relance la récupération, qui réussit.
        resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"sens": "902-0"})
        assert resultat["step_id"] == "abonnement_arret"
        resultat = await hass.config_entries.options.async_configure(
            resultat["flow_id"], {"arret": "Exemple Mairie"}
        )
        await hass.async_block_till_done()
        assert resultat["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options["abonnements"] == [
            {"arret": "Exemple Mairie", "id_ligne": "902", "sens_aller": True}
        ]
    finally:
        await serveur.close()


async def test_flux_configuration_reseau_injoignable(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ginko injoignable à la saisie de la clé : erreur générale, pas « clé invalide »."""
    monkeypatch.setattr("custom_components.ginko_trafic.api.BASE_URL", "http://127.0.0.1:1/")
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {"cle_api": CLE})
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["step_id"] == "user"
    assert resultat["errors"] == {"base": "cannot_connect"}


async def test_options_api_indisponible(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """API indisponible : seules les lignes déjà suivies sont proposées, et restent conservées."""
    hass.config.language = "fr"
    monkeypatch.setattr("custom_components.ginko_trafic.api.BASE_URL", "http://127.0.0.1:1/")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"cle_api": CLE},
        options={"lignes": ["901"], "abonnements": []},
        unique_id="reseau-ginko",
    )
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    assert resultat["type"] is FlowResultType.FORM
    cle = next(k for k in resultat["data_schema"].schema if str(k).endswith("lignes"))
    assert resultat["data_schema"].schema[cle].options == {"901": "901"}
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"lignes": ["901"], "abonnements": [], "ajouter": False}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"lignes": ["901"], "abonnements": []}


async def test_options_ajout_ligne_sans_variante(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une ligne du jour sans aucune variante (sens) ne peut pas être abonnée."""
    hass.config.language = "fr"
    lignes = json.loads(_lire("lignes.json"))
    sans_variante = dict(lignes["objets"][1], id="903", numLignePublic="99", variantes=[])
    lignes["objets"].append(sans_variante)
    app = web.Application()
    app.router.add_get("/DR/getLignes.do", lambda r: web.json_response(lignes))
    serveur = TestClient(TestServer(app))
    await serveur.start_server()
    monkeypatch.setattr("custom_components.ginko_trafic.api.BASE_URL", str(serveur.make_url("/")))
    try:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"cle_api": CLE},
            options={"lignes": ["901"], "abonnements": []},
            unique_id="reseau-ginko",
        )
        entry.add_to_hass(hass)
        resultat = await _options_init(hass, entry)
        resultat = await hass.config_entries.options.async_configure(
            resultat["flow_id"], {"lignes": ["901"], "abonnements": [], "ajouter": True}
        )
        assert resultat["step_id"] == "abonnement_ligne"
        resultat = await hass.config_entries.options.async_configure(resultat["flow_id"], {"ligne": "903"})
        assert resultat["type"] is FlowResultType.FORM
        assert resultat["step_id"] == "abonnement_ligne"
        assert resultat["errors"] == {"ligne": "lignes_indisponibles"}
        assert entry.options == {"lignes": ["901"], "abonnements": []}  # rien n'a changé
    finally:
        await serveur.close()
