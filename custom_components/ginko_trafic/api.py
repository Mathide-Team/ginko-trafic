"""Client de l'API open data Ginko (contrat Swagger v1.2 vérifié).

Contrat établi depuis la spécification officielle
(https://api.ginko.voyage/APIDoc/APIGinko.yaml) :

- toute requête exige une clé API (gratuite, demandée par courriel) ;
- la réponse est encapsulée : ``{"ok": true, "objets": ...}`` en cas de
  succès, ``{"ok": false, "msg": ...}`` en cas d'échec ;
- les paramètres tableaux sont fournis en une seule chaîne avec les
  valeurs séparées par le caractère tilde ``~`` ;
- les booléens valent ``1`` (vrai) ou ``0`` (faux).

Méthodes utilisées :

- ``DR/getLignes`` : lignes et variantes (sens) qui circulent ;
- ``DR/getDetailsVariante`` : arrêts desservis par une variante ;
- ``DR/getArrets`` : liste des arrêts ;
- ``TR/getListeTemps`` : temps d'attente par lieu + ligne + sens
  (tableaux parallèles, réponse groupée par lieu) ;
- ``TR/getEtatLignes`` : état info-trafic de chaque ligne (0 à 6) ;
- ``TR/getMessages`` : messages d'info-trafic, filtrables par lignes.

La méthode ``TR/getInfosTrafic`` est dépréciée (v1.2) : elle est
remplacée par ``TR/getMessages``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import LOGGER

BASE_URL = "https://api.ginko.voyage"


class GinkoError(Exception):
    """Erreur de base de l'intégration."""


class GinkoApiError(GinkoError):
    """L'API Ginko est injoignable ou a renvoyé une réponse invalide."""


class GinkoReponseError(GinkoError):
    """L'API Ginko a refusé la requête (clé invalide, paramètre refusé…)."""


@dataclass(frozen=True)
class Variante:
    """Sens de circulation d'une ligne."""

    id: str
    sens_aller: bool
    destination: str
    precision_destination: str


@dataclass(frozen=True)
class Ligne:
    """Ligne du réseau (FormLigne)."""

    id: str
    num_public: str
    libelle: str
    mode: int  # 0 bus, 1 tramway
    typologie: int  # 10 tramway, 20 LIANES, 30 urbaines, 40 complémentaires…
    couleur_fond: str
    couleur_texte: str
    variantes: tuple[Variante, ...]


@dataclass(frozen=True)
class Arret:
    """Arrêt de bus ou station de tram (FormArret)."""

    id: str
    nom: str
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class TempsAttente:
    """Un temps d'attente temps réel (FormTempsAttente)."""

    id_arret: str
    id_ligne: str
    num_ligne_public: str
    sens_aller: bool
    destination: str
    precision_destination: str
    temps: str  # texte affichable : « 3 min », « 17h05 » ou « Travaux »
    temps_en_seconde: int | None
    type_de_temps: int  # 0 délai, 1 horaire d'arrivée, 2 texte
    fiable: bool  # temps réel localisé vs estimation théorique
    num_vehicule: str
    affluence: int
    id_info_trafic: int
    quai: str


@dataclass(frozen=True)
class LieuTemps:
    """Réponse d'un lieu interrogé par TR/getListeTemps."""

    nom_exact: str
    liste_temps: tuple[TempsAttente, ...]
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class EtatLigne:
    """État info-trafic d'une ligne (FormInfoLigne)."""

    id_ligne: str
    num_ligne_public: str
    etat: int  # 0 à 6


@dataclass(frozen=True)
class Message:
    """Message d'info-trafic (FormMessage)."""

    id: int
    titre: str
    texte: str
    url: str
    etat: int  # 1 à 6
    id_evenement: int
    lignes: tuple[str, ...]  # numéros publics des lignes concernées
    arrets: tuple[str, ...]


def _variante(enregistrement: dict[str, Any]) -> Variante:
    return Variante(
        id=str(enregistrement["id"]),
        sens_aller=bool(enregistrement["sensAller"]),
        destination=enregistrement.get("destination") or "",
        precision_destination=enregistrement.get("precisionDestination") or "",
    )


def _ligne(enregistrement: dict[str, Any]) -> Ligne:
    return Ligne(
        id=str(enregistrement["id"]),
        num_public=enregistrement.get("numLignePublic") or "",
        libelle=enregistrement.get("libellePublic") or "",
        mode=enregistrement.get("modeTransport") or 0,
        typologie=enregistrement.get("typologie") or 80,
        couleur_fond=enregistrement.get("couleurFond") or "",
        couleur_texte=enregistrement.get("couleurTexte") or "",
        variantes=tuple(_variante(v) for v in enregistrement.get("variantes") or []),
    )


def _arret(enregistrement: dict[str, Any]) -> Arret:
    return Arret(
        id=str(enregistrement["id"]),
        nom=enregistrement.get("nom") or "",
        latitude=enregistrement.get("latitude") or None,
        longitude=enregistrement.get("longitude") or None,
    )


def _temps_attente(enregistrement: dict[str, Any]) -> TempsAttente:
    return TempsAttente(
        id_arret=str(enregistrement.get("idArret") or ""),
        id_ligne=str(enregistrement.get("idLigne") or ""),
        num_ligne_public=enregistrement.get("numLignePublic") or "",
        sens_aller=bool(enregistrement.get("sensAller")),
        destination=enregistrement.get("destination") or "",
        precision_destination=enregistrement.get("precisionDestination") or "",
        temps=enregistrement.get("temps") or "",
        temps_en_seconde=enregistrement.get("tempsEnSeconde"),
        type_de_temps=enregistrement.get("typeDeTemps") or 0,
        fiable=bool(enregistrement.get("fiable")),
        num_vehicule=enregistrement.get("numVehicule") or "",
        affluence=enregistrement.get("affluence", -1),
        id_info_trafic=enregistrement.get("idInfoTrafic") or 0,
        quai=enregistrement.get("quai") or "",
    )


def _message(enregistrement: dict[str, Any]) -> Message:
    return Message(
        id=enregistrement.get("id") or 0,
        titre=enregistrement.get("titre") or "",
        texte=enregistrement.get("texte") or "",
        url=enregistrement.get("url") or "",
        etat=enregistrement.get("etat") or 1,
        id_evenement=enregistrement.get("idEvenement") or 0,
        lignes=tuple(enregistrement.get("lignes") or ()),
        arrets=tuple(enregistrement.get("arrets") or ()),
    )


class GinkoClient:
    """Client en lecture seule de l'API Ginko (URL injectable pour les tests)."""

    def __init__(
        self,
        session: ClientSession,
        cle_api: str,
        base_url: str | None = None,
    ) -> None:
        LOGGER.debug("GinkoClient.__init__() appelé | url=%s", base_url or BASE_URL)
        self._session = session
        self._cle = cle_api
        # Lue à l'instanciation : les tests peuvent surcharger api.BASE_URL.
        self._base_url = (base_url or BASE_URL).rstrip("/")
        LOGGER.debug("GinkoClient.__init__() retourne")

    async def _async_appel(self, chemin: str, params: dict[str, str]) -> Any:
        """Appel protégé : réseau, HTTP, JSON et enveloppe validés."""
        LOGGER.debug("_async_appel() appelé | chemin=%s", chemin)
        url = f"{self._base_url}/{chemin}"
        parametres = {"apiKey": self._cle, **params}
        try:
            async with self._session.get(url, params=parametres) as response:
                response.raise_for_status()
                donnees = await response.json()
        except ClientResponseError as erreur:
            msg = f"Ginko a répondu {erreur.status} pour {chemin}"
            LOGGER.debug("Ginko a répondu %s pour %s", erreur.status, chemin)
            raise GinkoApiError(msg) from erreur
        except (ClientError, TimeoutError) as erreur:
            msg = f"Ginko est injoignable ({chemin})"
            LOGGER.debug("Ginko injoignable (%s) : %s", chemin, erreur)
            raise GinkoApiError(msg) from erreur
        except ValueError as erreur:
            msg = f"Réponse illisible de Ginko ({chemin})"
            LOGGER.debug("réponse illisible de Ginko (%s) : %s", chemin, erreur)
            raise GinkoApiError(msg) from erreur
        if not isinstance(donnees, dict) or "ok" not in donnees:
            msg = f"Enveloppe inattendue de Ginko ({chemin})"
            LOGGER.debug("enveloppe inattendue de Ginko (%s)", chemin)
            raise GinkoApiError(msg)
        if not donnees["ok"]:
            msg = str(donnees.get("msg") or "requête refusée par Ginko")
            LOGGER.debug("requête refusée par Ginko (%s) : %s", chemin, donnees.get("msg"))
            raise GinkoReponseError(msg)
        LOGGER.debug("_async_appel() retourne les objets (%s)", chemin)
        return donnees.get("objets")

    async def async_get_lignes(self) -> list[Ligne]:
        """Lignes et variantes circulant aujourd'hui (DR/getLignes)."""
        LOGGER.debug("async_get_lignes() appelé")
        objets = await self._async_appel("DR/getLignes.do", {})
        lignes = [_ligne(enr) for enr in objets or []]
        LOGGER.debug("async_get_lignes() retourne %s ligne(s)", len(lignes))
        return lignes

    async def async_get_arrets(self) -> list[Arret]:
        """Liste de tous les arrêts (DR/getArrets)."""
        LOGGER.debug("async_get_arrets() appelé")
        objets = await self._async_appel("DR/getArrets.do", {})
        arrets = [_arret(enr) for enr in objets or []]
        LOGGER.debug("async_get_arrets() retourne %s arrêt(s)", len(arrets))
        return arrets

    async def async_get_details_variante(self, id_ligne: str, id_variante: str) -> list[Arret]:
        """Arrêts desservis par une variante (DR/getDetailsVariante)."""
        LOGGER.debug("async_get_details_variante() appelé | ligne=%s variante=%s", id_ligne, id_variante)
        objets = await self._async_appel(
            "DR/getDetailsVariante.do",
            {"idLigne": id_ligne, "idVariante": id_variante},
        )
        arrets = [_arret(enr) for enr in objets or []]
        LOGGER.debug("async_get_details_variante() retourne %s arrêt(s)", len(arrets))
        return arrets

    async def async_get_temps(self, abonnements: list[tuple[str, str, bool]]) -> list[LieuTemps]:
        """Temps d'attente pour des abonnements (TR/getListeTemps).

        Chaque abonnement est un triplet (nom d'arrêt, id de ligne,
        sens aller). Les trois paramètres tableaux sont parallèles : ils
        sont envoyés en chaînes tilde-séparées, comme l'exige l'API bas
        niveau.
        """
        LOGGER.debug("async_get_temps() appelé | %s abonnement(s)", len(abonnements or []))
        if not abonnements:
            LOGGER.debug("async_get_temps() retourne [] (aucun abonnement)")
            return []
        noms = "~".join(a[0] for a in abonnements)
        lignes = "~".join(a[1] for a in abonnements)
        sens = "~".join("1" if a[2] else "0" for a in abonnements)
        objets = await self._async_appel(
            "TR/getListeTemps.do",
            {"listeNoms": noms, "listeIdLignes": lignes, "listeSensAller": sens},
        )
        lieux: list[LieuTemps] = []
        for lieu in objets or []:
            lieux.append(
                LieuTemps(
                    nom_exact=lieu.get("nomExact") or "",
                    liste_temps=tuple(_temps_attente(enr) for enr in lieu.get("listeTemps") or []),
                    latitude=lieu.get("latitude") or None,
                    longitude=lieu.get("longitude") or None,
                )
            )
        LOGGER.debug("async_get_temps() retourne %s lieu(x)", len(lieux))
        return lieux

    async def async_get_etat_lignes(self) -> list[EtatLigne]:
        """État info-trafic de chaque ligne (TR/getEtatLignes)."""
        LOGGER.debug("async_get_etat_lignes() appelé")
        objets = await self._async_appel("TR/getEtatLignes.do", {})
        etats = [
            EtatLigne(
                id_ligne=str(enr.get("idLigne") or ""),
                num_ligne_public=enr.get("numLignePublic") or "",
                etat=enr.get("etat") or 0,
            )
            for enr in objets or []
        ]
        LOGGER.debug("async_get_etat_lignes() retourne %s ligne(s)", len(etats))
        return etats

    async def async_get_messages(self, id_lignes: list[str] | None = None) -> list[Message]:
        """Messages d'info-trafic (TR/getMessages), filtrés par lignes."""
        LOGGER.debug("async_get_messages() appelé | %s ligne(s)", len(id_lignes or []))
        params: dict[str, str] = {}
        if id_lignes:
            params["idLignes"] = "~".join(id_lignes)
        objets = await self._async_appel("TR/getMessages.do", params)
        messages = [_message(enr) for enr in objets or []]
        LOGGER.debug("async_get_messages() retourne %s message(s)", len(messages))
        return messages
