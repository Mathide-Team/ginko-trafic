"""Intégration « Ginko trafic » : perturbations et temps d'attente."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GinkoClient, GinkoError
from .const import LOGGER
from .coordinator import PassagesCoordinator, TraficCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type GinkoTraficConfigEntry = ConfigEntry[None]


async def async_setup_entry(hass: HomeAssistant, entry: GinkoTraficConfigEntry) -> bool:
    """Prépare les deux coordinateurs et les entités.

    Un échec de la première mise à jour laisse Home Assistant retenter
    plus tard : l'entrée reste en « configuration non terminée ».
    """
    client = GinkoClient(
        async_get_clientsession(hass),
        entry.data["cle_api"],
    )
    try:
        lignes = {ligne.id: ligne for ligne in await client.async_get_lignes()}
    except GinkoError as erreur:
        raise ConfigEntryNotReady(str(erreur)) from erreur
    trafic = TraficCoordinator(hass, entry, client)
    passages = PassagesCoordinator(hass, entry, client)
    trafic_pret = True
    passages_prets = True
    try:
        await trafic.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        trafic_pret = False
    try:
        await passages.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        passages_prets = False
    if not trafic_pret and not passages_prets:
        # Aucun flux n'a réussi : Home Assistant retentera plus tard.
        raise ConfigEntryNotReady
    if not trafic_pret:
        LOGGER.warning("Infos trafic indisponibles au démarrage")
    if not passages_prets:
        LOGGER.warning("Temps d'attente indisponibles au démarrage")
    hass.data.setdefault(entry.domain, {})[entry.entry_id] = {
        "client": client,
        "lignes": lignes,
        "trafic": trafic,
        "passages": passages,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_mise_a_jour))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GinkoTraficConfigEntry) -> bool:
    """Décharge les entités de l'entrée."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[entry.domain].pop(entry.entry_id)
    return unload_ok


async def _async_mise_a_jour(hass: HomeAssistant, entry: GinkoTraficConfigEntry) -> None:
    """Recharge l'entrée quand les options (abonnements) changent."""
    await hass.config_entries.async_reload(entry.entry_id)
