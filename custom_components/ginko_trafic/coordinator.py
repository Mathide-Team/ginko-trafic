"""Coordinateurs : infos trafic et temps d'attente, indépendants."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EtatLigne, GinkoApiError, GinkoError, LieuTemps, Message
from .const import (
    ABO_ARRET,
    ABO_ID_LIGNE,
    ABO_SENS_ALLER,
    INTERVALLE_PASSAGES_S,
    INTERVALLE_TRAFIC_S,
    LOGGER,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import GinkoClient


class TraficCoordinator(DataUpdateCoordinator[dict[str, object]]):
    """Interroge l'état des lignes et les messages (toutes les minutes).

    Les deux requêtes sont indépendantes des temps d'attente : une
    panne des passages ne doit pas faire perdre les perturbations.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GinkoClient,
    ) -> None:
        LOGGER.debug("TraficCoordinator.__init__() appelé")
        super().__init__(
            hass,
            LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=INTERVALLE_TRAFIC_S),
        )
        self._client = client
        self._id_lignes = list(entry.options.get("lignes") or [])
        LOGGER.debug("TraficCoordinator.__init__() retourne | %s ligne(s)", len(self._id_lignes))

    async def _async_update_data(self) -> dict[str, object]:
        """État par ligne + messages des lignes suivies."""
        LOGGER.debug("_async_update_data() (trafic) appelé | %s ligne(s)", len(self._id_lignes))
        try:
            etats: list[EtatLigne] = await self._client.async_get_etat_lignes()
            messages: list[Message] = await self._client.async_get_messages(self._id_lignes or None)
        except GinkoApiError as erreur:
            LOGGER.debug("mise à jour du trafic impossible : %s", erreur)
            msg = f"Mise à jour du trafic impossible : {erreur}"
            raise UpdateFailed(msg) from erreur
        except GinkoError as erreur:
            LOGGER.debug("requête trafic refusée : %s", erreur)
            msg = f"Requête trafic refusée : {erreur}"
            raise UpdateFailed(msg) from erreur
        LOGGER.debug("_async_update_data() (trafic) retourne %s état(s)", len(etats))
        return {"etats": etats, "messages": messages}


class PassagesCoordinator(DataUpdateCoordinator[list[LieuTemps]]):
    """Interroge les temps d'attente des abonnements (toutes les minutes).

    Une seule requête groupée pour tous les abonnements (tableaux
    parallèles de l'API). Une panne de cette requête ne doit pas faire
    perdre les infos trafic.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GinkoClient,
    ) -> None:
        LOGGER.debug("PassagesCoordinator.__init__() appelé")
        super().__init__(
            hass,
            LOGGER,
            name=f"{entry.title} passages",
            update_interval=timedelta(seconds=INTERVALLE_PASSAGES_S),
        )
        self._client = client
        self._abonnements = list(entry.options.get("abonnements") or [])
        LOGGER.debug("PassagesCoordinator.__init__() retourne | %s abonnement(s)", len(self._abonnements))

    def _triplets(self) -> list[tuple[str, str, bool]]:
        """Abonnements convertis en triplets (arrêt, ligne, sens)."""
        LOGGER.debug("_triplets() appelé | %s abonnement(s)", len(self._abonnements))
        resultat = [
            (abo[ABO_ARRET], str(abo[ABO_ID_LIGNE]), bool(abo[ABO_SENS_ALLER]))
            for abo in self._abonnements
            if ABO_ARRET in abo and ABO_ID_LIGNE in abo
        ]
        LOGGER.debug("_triplets() retourne %s triplet(s)", len(resultat))
        return resultat

    async def _async_update_data(self) -> list[LieuTemps]:
        """Temps d'attente groupés de tous les abonnements."""
        LOGGER.debug("_async_update_data() (passages) appelé")
        try:
            lieux = await self._client.async_get_temps(self._triplets())
        except GinkoApiError as erreur:
            LOGGER.debug("mise à jour des passages impossible : %s", erreur)
            msg = f"Mise à jour des passages impossible : {erreur}"
            raise UpdateFailed(msg) from erreur
        except GinkoError as erreur:
            LOGGER.debug("requête passages refusée : %s", erreur)
            msg = f"Requête passages refusée : {erreur}"
            raise UpdateFailed(msg) from erreur
        LOGGER.debug("_async_update_data() (passages) retourne %s lieu(x)", len(lieux))
        return lieux
