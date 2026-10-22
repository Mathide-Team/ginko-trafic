"""Tests du client Ginko (fixtures entièrement fictives)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from custom_components.ginko_trafic.api import (
    GinkoApiError,
    GinkoClient,
    GinkoReponseError,
)

FIXTURES = Path(__file__).parent / "fixtures"
CLE = "CLE-TEST-123"
MAUVAISE_CLE = "MAUVAISE"

# Paramètres reçus par le serveur factice (pour vérifier l'encodage).
RECU: dict[str, dict] = {}


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _reponse(nom: str) -> web.Response:
    return web.json_response(json.loads(_lire(nom)))


def _build_app() -> web.Application:
    """Serveur factice reproduisant les routes Ginko."""

    async def get_lignes(request: web.Request) -> web.Response:
        RECU["lignes"] = dict(request.query)
        if request.query.get("apiKey") == MAUVAISE_CLE:
            return _reponse("erreur_cle.json")
        return _reponse("lignes.json")

    async def get_arrets(request: web.Request) -> web.Response:
        return _reponse("arrets.json")

    async def get_details_variante(request: web.Request) -> web.Response:
        return _reponse("details_variante.json")

    async def get_liste_temps(request: web.Request) -> web.Response:
        RECU["temps"] = dict(request.query)
        noms = request.query.get("listeNoms", "")
        if "Panne" in noms:
            return web.Response(status=500)
        if "Zero" in noms:
            return _reponse("liste_temps_zero.json")
        if "Vide" in noms:
            return _reponse("reponse_vide.json")
        return _reponse("liste_temps.json")

    async def get_etat_lignes(request: web.Request) -> web.Response:
        return _reponse("etat_lignes.json")

    async def get_messages(request: web.Request) -> web.Response:
        RECU["messages"] = dict(request.query)
        return _reponse("messages.json")

    async def mauvais_json(request: web.Request) -> web.Response:
        return web.Response(text="pas du tout du json", content_type="text/plain")

    app = web.Application()
    app.router.add_get("/DR/getLignes.do", get_lignes)
    app.router.add_get("/DR/getArrets.do", get_arrets)
    app.router.add_get("/DR/getDetailsVariante.do", get_details_variante)
    app.router.add_get("/TR/getListeTemps.do", get_liste_temps)
    app.router.add_get("/TR/getEtatLignes.do", get_etat_lignes)
    app.router.add_get("/TR/getMessages.do", get_messages)
    app.router.add_get("/mauvais.do", mauvais_json)
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


def _ginko(client: TestClient, cle: str = CLE) -> GinkoClient:
    return GinkoClient(client.session, cle, base_url=str(client.make_url("/")))


async def test_lignes(client: TestClient) -> None:
    """Les lignes et leurs variantes (sens) sont lues."""
    lignes = await _ginko(client).async_get_lignes()
    assert len(lignes) == 2
    premiere = lignes[0]
    assert premiere.id == "901"
    assert premiere.num_public == "T9"
    assert premiere.typologie == 10
    assert len(premiere.variantes) == 2
    variante_aller = premiere.variantes[0]
    assert variante_aller.sens_aller is True
    assert variante_aller.destination == "Exemple Sud"


async def test_cle_invalide(client: TestClient) -> None:
    """Une clé refusée lève GinkoReponseError, distinct du réseau."""
    with pytest.raises(GinkoReponseError, match="clé API invalide"):
        await _ginko(client, MAUVAISE_CLE).async_get_lignes()


async def test_erreur_http(client: TestClient) -> None:
    """Une erreur HTTP sur la vraie route devient GinkoApiError."""

    async def etat_panne(request: web.Request) -> web.Response:
        RECU["panne"] = True
        return web.Response(status=500)

    app = web.Application()
    app.router.add_get("/TR/getEtatLignes.do", etat_panne)
    serveur = TestClient(TestServer(app))
    await serveur.start_server()
    try:
        ginko = GinkoClient(serveur.session, CLE, base_url=str(serveur.make_url("/")))
        with pytest.raises(GinkoApiError):
            await ginko.async_get_etat_lignes()
    finally:
        await serveur.close()
    assert RECU["panne"]  # la route a bien été atteinte


async def test_json_invalide(client: TestClient) -> None:
    """Un corps JSON mal formé devient GinkoApiError."""

    async def etat_illisible(request: web.Request) -> web.Response:
        RECU["illisible"] = True
        return web.Response(text="{pas du tout du json", content_type="application/json")

    app = web.Application()
    app.router.add_get("/TR/getEtatLignes.do", etat_illisible)
    serveur = TestClient(TestServer(app))
    await serveur.start_server()
    try:
        ginko = GinkoClient(serveur.session, CLE, base_url=str(serveur.make_url("/")))
        with pytest.raises(GinkoApiError):
            await ginko.async_get_etat_lignes()
    finally:
        await serveur.close()
    assert RECU["illisible"]  # la route a bien été atteinte


async def test_erreur_reseau(client: TestClient) -> None:
    """Un serveur injoignable devient GinkoApiError."""
    ginko = GinkoClient(client.session, CLE, base_url="http://127.0.0.1:1")
    with pytest.raises(GinkoApiError):
        await ginko.async_get_lignes()


async def test_temps_attente_encodage(client: TestClient) -> None:
    """Les tableaux parallèles sont encodés en chaînes tilde-séparées."""
    abonnements = [
        ("Exemple Mairie", "901", True),
        ("Exemple Nord Terminus", "901", False),
    ]
    lieux = await _ginko(client).async_get_temps(abonnements)
    assert RECU["temps"]["listeNoms"] == "Exemple Mairie~Exemple Nord Terminus"
    assert RECU["temps"]["listeIdLignes"] == "901~901"
    assert RECU["temps"]["listeSensAller"] == "1~0"
    assert len(lieux) == 2
    mairie = lieux[0]
    assert mairie.nom_exact == "Exemple Mairie"
    assert len(mairie.liste_temps) == 3
    premier = mairie.liste_temps[0]
    assert premier.temps_en_seconde == 180
    assert premier.fiable is True
    assert premier.destination == "Exemple Sud"


async def test_temps_attente_cas_particuliers(client: TestClient) -> None:
    """Horaire lointain, texte de remplacement et zéro sont conservés."""
    lieux = await _ginko(client).async_get_temps([("Exemple Mairie", "902", True)])
    horaire = [t for t in lieux[0].liste_temps if t.type_de_temps == 1]
    assert horaire[0].temps == "17h05"
    assert horaire[0].temps_en_seconde == 3900
    lieux = await _ginko(client).async_get_temps([("Exemple Nord Terminus", "901", False)])
    terminus = next(lieu for lieu in lieux if lieu.nom_exact == "Exemple Nord Terminus")
    texte = terminus.liste_temps[0]
    assert texte.type_de_temps == 2
    assert texte.temps == "Travaux"
    assert texte.temps_en_seconde is None
    # Zéro : le véhicule est à l'arrêt, c'est une mesure valable.
    lieux = await _ginko(client).async_get_temps([("Exemple Zero", "901", True)])
    zero = next(t for t in lieux[0].liste_temps if t.temps_en_seconde == 0)
    assert zero.fiable is True
    # L'API ne garantit pas l'ordre : les deux mesures sont présentes.
    assert len(lieux[0].liste_temps) == 2


async def test_temps_sans_abonnement(client: TestClient) -> None:
    """Sans abonnement, aucune requête n'est émise."""
    assert await _ginko(client).async_get_temps([]) == []


async def test_reponse_vide(client: TestClient) -> None:
    """Une réponse sans objet est une liste vide, pas une erreur."""
    lieux = await _ginko(client).async_get_temps([("Exemple Vide", "901", True)])
    assert lieux == []


async def test_etat_lignes(client: TestClient) -> None:
    """L'état info-trafic de chaque ligne est lu."""
    etats = await _ginko(client).async_get_etat_lignes()
    assert {e.id_ligne: e.etat for e in etats} == {"901": 5, "902": 1}


async def test_messages_filtres(client: TestClient) -> None:
    """Les messages sont filtrés par identifiants de lignes côté serveur."""
    messages = await _ginko(client).async_get_messages(["901"])
    assert RECU["messages"]["idLignes"] == "901"
    assert len(messages) == 2
    premier = messages[0]
    assert premier.etat == 5
    assert premier.lignes == ("T9",)
    assert premier.url == "https://exemple.invalid/info/71"


async def _client_sur_route(chemin: str, reponse: web.Response) -> TestClient:
    """Serveur factice d'une seule route renvoyant *reponse*."""

    async def route(request: web.Request) -> web.Response:
        RECU[chemin] = dict(request.query)
        return reponse

    app = web.Application()
    app.router.add_get(chemin, route)
    serveur = TestClient(TestServer(app))
    await serveur.start_server()
    return serveur


async def test_arrets(client: TestClient) -> None:
    """La liste des arrêts (DR/getArrets) est lue avec identifiant et nom."""
    arrets = await _ginko(client).async_get_arrets()
    assert [(a.id, a.nom) for a in arrets] == [
        ("A1", "Exemple Mairie"),
        ("A2", "Exemple Marche"),
        ("A3", "Exemple Nord Terminus"),
    ]


@pytest.mark.parametrize(
    "corps",
    [
        pytest.param([1, 2], id="liste"),
        pytest.param({"objets": []}, id="sans-ok"),
    ],
)
async def test_enveloppe_inattendue(corps: object) -> None:
    """Un JSON valide sans enveloppe ``{"ok": …}`` devient GinkoApiError."""
    serveur = await _client_sur_route("/TR/getEtatLignes.do", web.json_response(corps))
    try:
        ginko = GinkoClient(serveur.session, CLE, base_url=str(serveur.make_url("/")))
        with pytest.raises(GinkoApiError, match=r"Enveloppe inattendue de Ginko \(TR/getEtatLignes.do\)"):
            await ginko.async_get_etat_lignes()
    finally:
        await serveur.close()
    assert "/TR/getEtatLignes.do" in RECU  # la route a bien été atteinte


async def test_refus_sans_message() -> None:
    """Un refus sans ``msg`` garde un libellé explicite, pas une chaîne vide."""
    serveur = await _client_sur_route("/DR/getLignes.do", web.json_response({"ok": False}))
    try:
        ginko = GinkoClient(serveur.session, CLE, base_url=str(serveur.make_url("/")))
        with pytest.raises(GinkoReponseError, match=r"^requête refusée par Ginko$"):
            await ginko.async_get_lignes()
    finally:
        await serveur.close()


async def test_messages_sans_filtre(client: TestClient) -> None:
    """Sans lignes, aucun filtre ``idLignes`` n'est envoyé (tous les messages)."""
    messages = await _ginko(client).async_get_messages()
    assert "idLignes" not in RECU["messages"]
    assert len(messages) == 2
    messages = await _ginko(client).async_get_messages([])
    assert "idLignes" not in RECU["messages"]
