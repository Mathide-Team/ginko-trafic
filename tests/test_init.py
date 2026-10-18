"""Tests de l'installation : perturbations et temps d'attente."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ginko_trafic.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
CLE = "CLE-TEST-123"
LIGNE_TRAM = "901"
LIGNE_BUS = "902"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _reponse(nom: str) -> web.Response:
    return web.json_response(json.loads(_lire(nom)))


def _build_app() -> web.Application:
    """Serveur factice reproduisant les routes Ginko."""

    async def get_lignes(request: web.Request) -> web.Response:
        return _reponse("lignes.json")

    async def get_details_variante(request: web.Request) -> web.Response:
        return _reponse("details_variante.json")

    async def get_liste_temps(request: web.Request) -> web.Response:
        noms = request.query.get("listeNoms", "")
        if "Panne" in noms:
            return web.Response(status=500)
        if "Vide" in noms:
            return _reponse("reponse_vide.json")
        if "Zero" in noms:
            return _reponse("liste_temps_zero.json")
        return _reponse("liste_temps.json")

    async def get_etat_lignes(request: web.Request) -> web.Response:
        return _reponse("etat_lignes.json")

    async def get_messages(request: web.Request) -> web.Response:
        return _reponse("messages.json")

    app = web.Application()
    app.router.add_get("/DR/getLignes.do", get_lignes)
    app.router.add_get("/DR/getDetailsVariante.do", get_details_variante)
    app.router.add_get("/TR/getListeTemps.do", get_liste_temps)
    app.router.add_get("/TR/getEtatLignes.do", get_etat_lignes)
    app.router.add_get("/TR/getMessages.do", get_messages)
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


async def _demarrer(hass: HomeAssistant, client: TestClient, options: dict) -> MockConfigEntry:
    """Charge l'intégration en pointant Ginko vers le serveur factice."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "custom_components.ginko_trafic.api.BASE_URL",
            str(client.make_url("/")),
        )
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"cle_api": CLE},
            options=options,
            unique_id="reseau-ginko",
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry


def _etat(hass: HomeAssistant, cle: str):
    """Cherche une entité par la fin de son entity_id."""
    for plateforme in ("sensor", "binary_sensor"):
        for entity_id in hass.states.async_entity_ids(plateforme):
            if entity_id.endswith(cle):
                return hass.states.get(entity_id)
    return None


async def test_perturbations(hass: HomeAssistant, client: TestClient) -> None:
    """État par ligne : perturbation en cours vs fonctionnement normal."""
    hass.config.language = "fr"
    await _demarrer(hass, client, {"lignes": [LIGNE_TRAM, LIGNE_BUS]})
    ids = [e for e in hass.states.async_entity_ids("binary_sensor") if e.endswith("_perturbation")]
    assert len(ids) == 2
    tram_on = [hass.states.get(e) for e in ids if e.startswith("binary_sensor.ligne_t9")]
    bus_off = [hass.states.get(e) for e in ids if e.startswith("binary_sensor.ligne_42")]
    assert tram_on[0].state == "on"  # etat 5 : perturbation en cours
    assert tram_on[0].attributes["etat"] == "perturbation en cours"
    assert "Travaux voie tram" in tram_on[0].attributes["messages"]
    assert bus_off[0].state == "off"  # etat 1 : normale
    assert bus_off[0].attributes["etat"] == "normale"


async def test_prochain_passage(hass: HomeAssistant, client: TestClient) -> None:
    """Minutes d'attente du prochain passage, avec attributs."""
    hass.config.language = "fr"
    await _demarrer(
        hass,
        client,
        {
            "lignes": [LIGNE_TRAM],
            "abonnements": [{"arret": "Exemple Mairie", "id_ligne": LIGNE_TRAM, "sens_aller": True}],
        },
    )
    capteur = _etat(hass, "_passage_exemple_mairie_aller")
    assert capteur is not None
    assert capteur.state == "3"  # 180 secondes
    assert capteur.attributes["destination"] == "Exemple Sud"
    assert capteur.attributes["temps_reel"] is True
    assert capteur.attributes["horaire_affiche"] == "3 min"
    assert "8 min" in capteur.attributes["prochains_passages"]


async def test_passage_zero_prioritaire(hass: HomeAssistant, client: TestClient) -> None:
    """Un véhicule à l'arrêt (0 s) passe avant un délai de 8 minutes.

    L'état et les attributs décrivent le même enregistrement : celui
    du véhicule à l'arrêt.
    """
    hass.config.language = "fr"
    await _demarrer(
        hass,
        client,
        {
            "lignes": [LIGNE_TRAM],
            "abonnements": [{"arret": "Exemple Zero", "id_ligne": LIGNE_TRAM, "sens_aller": True}],
        },
    )
    capteur = _etat(hass, "_passage_exemple_zero_aller")
    assert capteur is not None
    assert capteur.state == "0"
    assert capteur.attributes["destination"] == "Exemple Sud"
    assert capteur.attributes["horaire_affiche"] == "à l'arrêt"
    assert capteur.attributes["temps_reel"] is True


async def test_deux_arrets_meme_ligne(hass: HomeAssistant, client: TestClient) -> None:
    """Deux abonnements de la même ligne ont des entités distinctes."""
    hass.config.language = "fr"
    await _demarrer(
        hass,
        client,
        {
            "lignes": [LIGNE_TRAM],
            "abonnements": [
                {"arret": "Exemple Mairie", "id_ligne": LIGNE_TRAM, "sens_aller": True},
                {
                    "arret": "Exemple Nord Terminus",
                    "id_ligne": LIGNE_TRAM,
                    "sens_aller": False,
                },
            ],
        },
    )
    mairie = _etat(hass, "_passage_exemple_mairie_aller")
    terminus = _etat(hass, "_passage_exemple_nord_terminus_retour")
    assert mairie is not None
    assert terminus is not None
    assert mairie.entity_id != terminus.entity_id
    # Identifiant complet documenté dans le README : périphérique ligne
    # + nom « passage {arrêt} ({sens}) ».
    assert mairie.entity_id == "sensor.ligne_t9_exemple_nord_exemple_sud_passage_exemple_mairie_aller"
    assert mairie.state == "3"
    assert terminus.state == "unknown"  # texte « Travaux » sans valeur


async def test_passage_texte_et_horaire(hass: HomeAssistant, client: TestClient) -> None:
    """Texte de remplacement et horaire lointain laissent le détail."""
    hass.config.language = "fr"
    await _demarrer(
        hass,
        client,
        {
            "lignes": [LIGNE_TRAM, LIGNE_BUS],
            "abonnements": [
                # Sens retour : le temps est remplacé par « Travaux ».
                {
                    "arret": "Exemple Nord Terminus",
                    "id_ligne": LIGNE_TRAM,
                    "sens_aller": False,
                },
                # Ligne 42 à Exemple Mairie : horaire « 17h05 » (type 1).
                {"arret": "Exemple Mairie", "id_ligne": LIGNE_BUS, "sens_aller": True},
            ],
        },
    )
    ids = [e for e in hass.states.async_entity_ids("sensor") if "_passage_" in e]
    par_arret = {hass.states.get(e).attributes["arret"]: hass.states.get(e) for e in ids}
    travaux = par_arret["Exemple Nord Terminus"]
    assert travaux.state == "unknown"  # type 2 : pas de valeur numérique
    assert travaux.attributes["horaire_affiche"] == "Travaux"
    horaire = par_arret["Exemple Mairie"]
    assert horaire.state == "65"  # 3900 secondes
    assert horaire.attributes["temps_reel"] is False  # estimation théorique


async def test_aucun_passage(hass: HomeAssistant, client: TestClient) -> None:
    """Un abonnement sans réponse reste sans valeur, pas en erreur."""
    hass.config.language = "fr"
    await _demarrer(
        hass,
        client,
        {
            "lignes": [LIGNE_TRAM],
            "abonnements": [{"arret": "Exemple Vide", "id_ligne": LIGNE_TRAM, "sens_aller": True}],
        },
    )
    capteur = _etat(hass, "_passage_exemple_vide_aller")
    assert capteur is not None
    assert capteur.state == "unknown"


async def test_panne_passages_sans_perte_trafic(hass: HomeAssistant, client: TestClient) -> None:
    """Une panne des temps d'attente ne fait pas perdre les perturbations."""
    hass.config.language = "fr"
    await _demarrer(
        hass,
        client,
        {
            "lignes": [LIGNE_TRAM, LIGNE_BUS],
            "abonnements": [{"arret": "Exemple Panne", "id_ligne": LIGNE_TRAM, "sens_aller": True}],
        },
    )
    perturbations = [
        hass.states.get(e)
        for e in hass.states.async_entity_ids("binary_sensor")
        if e.endswith("_perturbation")
    ]
    tram = next(p for p in perturbations if "t9" in p.entity_id)
    assert tram.state == "on"  # les infos trafic restent disponibles
    capteur = _etat(hass, "_passage_exemple_panne_aller")
    assert capteur is not None
    # Le coordinateur passages n'a jamais réussi : indisponible, pas d'erreur.
    assert capteur.state == "unavailable"


async def test_panne_trafic_sans_perte_passages(hass: HomeAssistant, client: TestClient) -> None:
    """Une panne des infos trafic n'empêche pas les temps d'attente.

    Après un premier échec, la mise à jour suivante rétablit les
    perturbations sans intervention.
    """
    hass.config.language = "fr"
    # Une seule panne suffit : la mise à jour du trafic interroge l'état
    # des lignes puis les messages, et échoue dès qu'une route échoue.
    echecs = {"restants": 1}

    async def _reponse_ou_panne(nom: str) -> web.Response:
        if echecs["restants"] > 0:
            echecs["restants"] -= 1
            return web.Response(status=500)
        return _reponse(nom)

    async def get_etat_lignes(request: web.Request) -> web.Response:
        return await _reponse_ou_panne("etat_lignes.json")

    async def get_messages(request: web.Request) -> web.Response:
        return await _reponse_ou_panne("messages.json")

    async def get_lignes(request: web.Request) -> web.Response:
        return _reponse("lignes.json")

    async def get_liste_temps(request: web.Request) -> web.Response:
        return _reponse("liste_temps.json")

    app = web.Application()
    app.router.add_get("/DR/getLignes.do", get_lignes)
    app.router.add_get("/TR/getEtatLignes.do", get_etat_lignes)
    app.router.add_get("/TR/getMessages.do", get_messages)
    app.router.add_get("/TR/getListeTemps.do", get_liste_temps)
    serveur = TestClient(TestServer(app))
    await serveur.start_server()

    def _tram():
        return next(
            p
            for p in (
                hass.states.get(e)
                for e in hass.states.async_entity_ids("binary_sensor")
                if e.endswith("_perturbation")
            )
            if "t9" in p.entity_id
        )

    # Le patch de BASE_URL doit rester actif pour le rafraîchissement de
    # récupération : il englobe donc toute la suite du test.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "custom_components.ginko_trafic.api.BASE_URL",
            str(serveur.make_url("/")),
        )
        try:
            entry = await _demarrer(
                hass,
                serveur,
                {
                    "lignes": [LIGNE_TRAM],
                    "abonnements": [
                        {
                            "arret": "Exemple Mairie",
                            "id_ligne": LIGNE_TRAM,
                            "sens_aller": True,
                        }
                    ],
                },
            )
            capteur = _etat(hass, "_passage_exemple_mairie_aller")
            assert capteur is not None
            assert capteur.state == "3"  # les passages restent disponibles
            # Premier rafraîchissement trafic en échec : les entités se
            # chargent malgré l'absence de données, en indisponible.
            assert _tram().state == "unavailable"
            # La mise à jour suivante rétablit les perturbations (serveur
            # encore actif : le rafraîchissement doit pouvoir joindre l'API).
            trafic = hass.data[DOMAIN][entry.entry_id]["trafic"]
            await trafic.async_refresh()
            await hass.async_block_till_done()
            assert _tram().state == "on"
            assert _tram().attributes["etat"] == "perturbation en cours"
        finally:
            await serveur.close()
