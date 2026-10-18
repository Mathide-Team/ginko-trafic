"""Capteurs de temps d'attente par abonnement arrêt + ligne + sens."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TempsAttente
from .const import (
    ABO_ARRET,
    ABO_ID_LIGNE,
    ABO_SENS_ALLER,
    DOMAIN,
)
from .coordinator import PassagesCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

AFFLUENCES = {-1: "indisponible", 0: "faible", 1: "modérée", 2: "forte"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée un capteur par abonnement de passage."""
    donnees = hass.data[DOMAIN][entry.entry_id]
    lignes: dict[str, object] = donnees["lignes"]
    passages: PassagesCoordinator = donnees["passages"]
    abonnements = list(entry.options.get("abonnements") or [])
    async_add_entities(
        [
            GinkoProchainPassageEntity(passages, lignes, abonnement)
            for abonnement in abonnements
            if ABO_ARRET in abonnement and ABO_ID_LIGNE in abonnement
        ]
    )


class GinkoProchainPassageEntity(CoordinatorEntity[PassagesCoordinator], SensorEntity):
    """Prochain passage à un arrêt pour une ligne et un sens.

    L'état est le nombre de minutes d'attente du prochain passage
    mesuré (délai ou horaire lointain) ; les cas sans durée numérique
    (texte de remplacement, aucune mesure) laissent le capteur sans
    valeur, avec le détail en attributs.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: PassagesCoordinator,
        lignes: dict[str, object],
        abonnement: dict,
    ) -> None:
        super().__init__(coordinator)
        self._abonnement = abonnement
        self._ligne = lignes.get(str(abonnement[ABO_ID_LIGNE]))
        arret_slug = str(abonnement[ABO_ARRET]).strip().lower().replace(" ", "_")
        sens = "aller" if abonnement[ABO_SENS_ALLER] else "retour"
        # L'arrêt et le sens font partie du nom : deux abonnements de
        # la même ligne restent distinguables dans l'interface.
        self._attr_name = f"passage {abonnement[ABO_ARRET]} ({sens})"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{abonnement[ABO_ID_LIGNE]}_{sens}_{arret_slug}"
        )
        self._attr_device_info = self._informations_ligne()

    def _informations_ligne(self) -> DeviceInfo:
        """Appareil portant le nom réel de la ligne."""
        num = getattr(self._ligne, "num_public", None) or str(self._abonnement[ABO_ID_LIGNE])
        libelle = getattr(self._ligne, "libelle", "") or ""
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._abonnement[ABO_ID_LIGNE]))},
            name=f"Ligne {num}" + (f" {libelle}" if libelle else ""),
            manufacturer="Ginko (Keolis Besançon Mobilités)",
            model="Ligne de bus/tram",
        )

    def _temps_de_l_abonnement(self) -> list[TempsAttente]:
        """Temps d'attente de l'abonnement, triés par attente croissante.

        Un zéro (véhicule à l'arrêt) est une mesure valable et doit
        rester en tête : None et 0 sont distingués explicitement.
        """
        resultat: list[TempsAttente] = []
        arret = str(self._abonnement[ABO_ARRET]).strip().casefold()
        for lieu in self.coordinator.data or []:
            if lieu.nom_exact.strip().casefold() != arret:
                continue
            for temps in lieu.liste_temps:
                if temps.id_ligne == str(self._abonnement[ABO_ID_LIGNE]) and temps.sens_aller == bool(
                    self._abonnement[ABO_SENS_ALLER]
                ):
                    resultat.append(temps)
        resultat.sort(
            key=lambda t: (
                t.temps_en_seconde is None,
                t.temps_en_seconde if t.temps_en_seconde is not None else 10**9,
            )
        )
        return resultat

    def _premier_mesure(self) -> TempsAttente | None:
        """Premier passage avec durée numérique (délai ou horaire)."""
        for temps in self._temps_de_l_abonnement():
            if temps.type_de_temps == 2:  # texte : « Travaux », « Déviation »…
                continue
            if temps.temps_en_seconde is None:
                continue
            return temps
        return None

    @property
    def native_value(self) -> int | None:
        """Minutes d'attente du prochain passage mesuré, sinon None."""
        premier = self._premier_mesure()
        if premier is None:
            return None
        return max(0, round(premier.temps_en_seconde / 60))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Destination, fiabilité, horaires et affluence du prochain passage.

        L'état et ces attributs décrivent le même enregistrement : celui
        du premier passage mesuré, même si un texte de remplacement
        arrive avant dans la liste.
        """
        liste = self._temps_de_l_abonnement()
        if not liste:
            return {"arret": self._abonnement[ABO_ARRET]}
        premier = self._premier_mesure() or liste[0]
        return {
            "arret": self._abonnement[ABO_ARRET],
            "destination": premier.destination,
            "precision_destination": premier.precision_destination or None,
            "horaire_affiche": premier.temps,
            "type_de_temps": premier.type_de_temps,
            "temps_reel": premier.fiable,
            "affluence": AFFLUENCES.get(premier.affluence, "inconnue"),
            "quai": premier.quai or None,
            "prochains_passages": [t.temps for t in liste[:5]],
        }
