"""Binary sensors de perturbation par ligne suivie."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ETATS_PERTURBATION, LIBELLES_ETAT
from .coordinator import TraficCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée un binary sensor par ligne suivie."""
    donnees = hass.data[DOMAIN][entry.entry_id]
    lignes: dict[str, object] = donnees["lignes"]
    trafic: TraficCoordinator = donnees["trafic"]
    ids_lignes = list(entry.options.get("lignes") or [])
    async_add_entities([GinkoPerturbationEntity(trafic, lignes, str(id_ligne)) for id_ligne in ids_lignes])


class GinkoPerturbationEntity(CoordinatorEntity[TraficCoordinator], BinarySensorEntity):
    """Perturbation en cours ou prévue sur une ligne.

    L'état vient de ``TR/getEtatLignes`` (4 : perturbation prévue,
    5 : en cours, 6 : circulation interrompue). Les états 1 et 2
    (fonctionnement normal, simple information) ne déclenchent pas le
    capteur ; l'état 3 (hors période de service) est exposé en attribut.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "perturbation"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: TraficCoordinator,
        lignes: dict[str, object],
        id_ligne: str,
    ) -> None:
        super().__init__(coordinator)
        self._id_ligne = id_ligne
        self._ligne = lignes.get(id_ligne)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{id_ligne}_perturbation"
        num = getattr(self._ligne, "num_public", None) or id_ligne
        libelle = getattr(self._ligne, "libelle", "") or ""
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, id_ligne)},
            name=f"Ligne {num}" + (f" {libelle}" if libelle else ""),
            manufacturer="Ginko (Keolis Besançon Mobilités)",
            model="Ligne de bus/tram",
        )

    def _etat_ligne(self) -> int | None:
        """État info-trafic de la ligne, None si absente de la réponse."""
        # data peut être None si le premier rafraîchissement a échoué.
        for etat in (self.coordinator.data or {}).get("etats") or []:
            if etat.id_ligne == self._id_ligne:
                return etat.etat
        return None

    def _messages_ligne(self) -> list[dict[str, object]]:
        """Messages d'info-trafic concernant la ligne (numéro public)."""
        num = getattr(self._ligne, "num_public", None)
        if not num:
            return []
        messages = (self.coordinator.data or {}).get("messages") or []
        return [
            {
                "titre": m.titre,
                "etat": LIBELLES_ETAT.get(m.etat, str(m.etat)),
                "url": m.url or None,
            }
            for m in messages
            if num in m.lignes
        ]

    @property
    def is_on(self) -> bool | None:
        """Vrai si une perturbation concerne la ligne (prévue ou en cours)."""
        etat = self._etat_ligne()
        if etat is None:
            return None
        return etat in ETATS_PERTURBATION

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """État détaillé et messages de la ligne."""
        etat = self._etat_ligne()
        messages = self._messages_ligne()
        return {
            "etat": LIBELLES_ETAT.get(etat, "inconnu") if etat is not None else None,
            "code_etat": etat,
            "messages": [m["titre"] for m in messages],
            "detail_messages": messages,
        }
