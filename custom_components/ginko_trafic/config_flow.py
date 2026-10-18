"""Configuration : clé API, lignes suivies, abonnements arrêt/ligne/sens."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GinkoApiError, GinkoClient, GinkoError, GinkoReponseError, Ligne
from .const import (
    ABO_ARRET,
    ABO_ID_LIGNE,
    ABO_SENS_ALLER,
    CONF_ABONNEMENTS,
    CONF_CLE_API,
    CONF_LIGNES,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_CLE_API): str})


def _cle_abonnement(abonnement: dict) -> str:
    """Clé stable d'un abonnement pour les listes de sélection."""
    return json.dumps(abonnement, sort_keys=True, ensure_ascii=False)


def _libelle_abonnement(abonnement: dict, num_ligne: str | None) -> str:
    """Libellé lisible d'un abonnement."""
    num = num_ligne or str(abonnement.get(ABO_ID_LIGNE, "?"))
    sens = "aller" if abonnement.get(ABO_SENS_ALLER) else "retour"
    return f"{num} — {abonnement.get(ABO_ARRET, '?')} ({sens})"


class GinkoTraficConfigFlow(ConfigFlow, domain=DOMAIN):
    """Étapes de configuration : une entrée pour le réseau Ginko."""

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> GinkoTraficOptionsFlow:
        """Options d'une entrée existante."""
        return GinkoTraficOptionsFlow()

    def __init__(self) -> None:
        self._cle: str = ""
        self._lignes: list[Ligne] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Demande la clé API et la valide."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id("reseau-ginko")
            self._abort_if_unique_id_configured()
            cle = user_input[CONF_CLE_API].strip()
            try:
                client = GinkoClient(async_get_clientsession(self.hass), cle)
                lignes = await client.async_get_lignes()
            except GinkoReponseError:
                erreurs[CONF_CLE_API] = "cle_invalide"
            except GinkoApiError:
                erreurs["base"] = "cannot_connect"
            else:
                self._cle = cle
                self._lignes = lignes
                return await self.async_step_lignes()
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=erreurs,
        )

    async def async_step_lignes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix des lignes suivies pour les perturbations."""
        if user_input is not None:
            return self.async_create_entry(
                title="Ginko",
                data={CONF_CLE_API: self._cle},
                options={
                    CONF_LIGNES: user_input.get(CONF_LIGNES) or [],
                    CONF_ABONNEMENTS: [],
                },
            )
        return self.async_show_form(
            step_id="lignes",
            data_schema=vol.Schema(
                {vol.Optional(CONF_LIGNES, default=[]): cv.multi_select(self._selection_lignes())}
            ),
        )

    def _selection_lignes(self) -> dict[str, str]:
        """Lignes proposées, triées par typologie puis numéro public."""
        lignes = sorted(self._lignes, key=lambda ligne: (ligne.typologie, ligne.num_public))
        return {ligne.id: f"{ligne.num_public} — {ligne.libelle}" for ligne in lignes}


class GinkoTraficOptionsFlow(OptionsFlow):
    """Options : lignes suivies, abonnements, ajout d'un abonnement."""

    def __init__(self) -> None:
        self._partiel: dict[str, Any] = {}
        self._nouvel_abonnement: dict | None = None
        self._ligne_choisie: Ligne | None = None
        self._variante_choisie_id: str = ""

    @callback
    def _options_actuelles(self) -> dict[str, Any]:
        return {
            CONF_LIGNES: list(self.config_entry.options.get(CONF_LIGNES) or []),
            CONF_ABONNEMENTS: list(self.config_entry.options.get(CONF_ABONNEMENTS) or []),
        }

    async def _async_lignes(self) -> list[Ligne]:
        """Lignes du réseau ; liste vide si l'API est indisponible."""
        client = GinkoClient(
            async_get_clientsession(self.hass),
            self.config_entry.data[CONF_CLE_API],
        )
        try:
            return await client.async_get_lignes()
        except GinkoError:
            return []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Lignes suivies, retrait d'abonnements, ajout facultatif."""
        erreurs: dict[str, str] = {}
        lignes = await self._async_lignes()
        if user_input is not None:
            abonnements = [json.loads(cle) for cle in user_input.get(CONF_ABONNEMENTS) or []]
            self._partiel = {
                CONF_LIGNES: user_input.get(CONF_LIGNES) or [],
                CONF_ABONNEMENTS: abonnements,
            }
            if user_input.get("ajouter"):
                return await self.async_step_abonnement_ligne()
            return self.async_create_entry(title="", data=self._partiel)
        options = self._options_actuelles()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    # Union des lignes disponibles aujourd'hui et des lignes
                    # déjà suivies : une ligne absente du service du jour
                    # reste sélectionnable (et conservée si on ne la touche pas).
                    vol.Optional(CONF_LIGNES, default=options[CONF_LIGNES]): cv.multi_select(
                        {
                            **{i: i for i in options[CONF_LIGNES]},
                            **{ligne.id: f"{ligne.num_public} — {ligne.libelle}" for ligne in lignes},
                        }
                    ),
                    vol.Optional(
                        CONF_ABONNEMENTS,
                        default=[_cle_abonnement(a) for a in options[CONF_ABONNEMENTS]],
                    ): cv.multi_select(
                        {_cle_abonnement(a): _libelle_abonnement(a, None) for a in options[CONF_ABONNEMENTS]}
                    ),
                    vol.Optional("ajouter", default=False): bool,
                }
            ),
            errors=erreurs,
        )

    async def async_step_abonnement_ligne(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix de la ligne du nouvel abonnement."""
        if user_input is not None:
            lignes = await self._async_lignes()
            self._ligne_choisie = next((ligne for ligne in lignes if ligne.id == user_input["ligne"]), None)
            if self._ligne_choisie is None or not self._ligne_choisie.variantes:
                return self.async_show_form(
                    step_id="abonnement_ligne",
                    data_schema=vol.Schema({vol.Required("ligne"): str}),
                    errors={"ligne": "lignes_indisponibles"},
                )
            return await self.async_step_abonnement_sens()
        lignes = await self._async_lignes()
        return self.async_show_form(
            step_id="abonnement_ligne",
            data_schema=vol.Schema(
                {
                    vol.Required("ligne"): vol.In(
                        {ligne.id: f"{ligne.num_public} — {ligne.libelle}" for ligne in lignes}
                    )
                }
            ),
        )

    async def async_step_abonnement_sens(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix du sens (variante) du nouvel abonnement."""
        ligne = self._ligne_choisie
        assert ligne is not None
        if user_input is not None:
            self._variante_choisie_id = user_input["sens"]
            return await self.async_step_abonnement_arret()
        return self.async_show_form(
            step_id="abonnement_sens",
            data_schema=vol.Schema(
                {
                    vol.Required("sens"): vol.In(
                        {
                            v.id: (f"{v.destination} ({'aller' if v.sens_aller else 'retour'})")
                            for v in ligne.variantes
                        }
                    )
                }
            ),
        )

    async def async_step_abonnement_arret(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix de l'arrêt du nouvel abonnement, puis enregistrement."""
        ligne = self._ligne_choisie
        assert ligne is not None
        client = GinkoClient(
            async_get_clientsession(self.hass),
            self.config_entry.data[CONF_CLE_API],
        )
        if user_input is not None:
            variante = next(
                (v for v in ligne.variantes if v.id == self._variante_choisie_id),
                None,
            )
            assert variante is not None
            abonnement = {
                ABO_ARRET: user_input["arret"],
                ABO_ID_LIGNE: ligne.id,
                ABO_SENS_ALLER: variante.sens_aller,
            }
            abonnements = list(self._partiel.get(CONF_ABONNEMENTS) or [])
            deja_present = any(
                a[ABO_ARRET] == abonnement[ABO_ARRET]
                and str(a[ABO_ID_LIGNE]) == abonnement[ABO_ID_LIGNE]
                and bool(a.get(ABO_SENS_ALLER)) == abonnement[ABO_SENS_ALLER]
                for a in abonnements
            )
            if not deja_present:
                abonnements.append(abonnement)
            return self.async_create_entry(title="", data={**self._partiel, CONF_ABONNEMENTS: abonnements})
        try:
            arrets = await client.async_get_details_variante(ligne.id, self._variante_choisie_id)
        except GinkoError:
            # Pas de saisie libre : l'erreur est conservée et le choix du
            # sens est re-proposé — le réenvoyer relance la récupération.
            return self.async_show_form(
                step_id="abonnement_sens",
                data_schema=vol.Schema(
                    {
                        vol.Required("sens"): vol.In(
                            {
                                v.id: (f"{v.destination} ({'aller' if v.sens_aller else 'retour'})")
                                for v in ligne.variantes
                            }
                        )
                    }
                ),
                errors={"base": "cannot_connect"},
            )
        return self.async_show_form(
            step_id="abonnement_arret",
            data_schema=vol.Schema({vol.Required("arret"): vol.In({a.nom: a.nom for a in arrets})}),
        )
