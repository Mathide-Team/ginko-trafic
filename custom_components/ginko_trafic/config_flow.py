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
    LOGGER,
)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_CLE_API): str})


def _cle_abonnement(abonnement: dict) -> str:
    """Clé stable d'un abonnement pour les listes de sélection."""
    return json.dumps(abonnement, sort_keys=True, ensure_ascii=False)


def _libelle_abonnement(abonnement: dict, num_ligne: str | None) -> str:
    """Libellé lisible d'un abonnement."""
    LOGGER.debug("_libelle_abonnement() appelé | ligne=%s", abonnement.get(ABO_ID_LIGNE))
    num = num_ligne or str(abonnement.get(ABO_ID_LIGNE, "?"))
    sens = "aller" if abonnement.get(ABO_SENS_ALLER) else "retour"
    LOGGER.debug("_libelle_abonnement() retourne le libellé")
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
        LOGGER.debug("GinkoTraficConfigFlow.__init__() appelé")
        self._cle: str = ""
        self._lignes: list[Ligne] = []
        LOGGER.debug("GinkoTraficConfigFlow.__init__() retourne")

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Demande la clé API et la valide."""
        LOGGER.debug("async_step_user() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id("reseau-ginko")
            self._abort_if_unique_id_configured()
            cle = user_input[CONF_CLE_API].strip()
            try:
                client = GinkoClient(async_get_clientsession(self.hass), cle)
                lignes = await client.async_get_lignes()
            except GinkoReponseError as erreur:
                LOGGER.debug("clé refusée par Ginko : %s", erreur)
                erreurs[CONF_CLE_API] = "cle_invalide"
            except GinkoApiError as erreur:
                LOGGER.debug("API Ginko injoignable : %s", erreur)
                erreurs["base"] = "cannot_connect"
            else:
                self._cle = cle
                self._lignes = lignes
                LOGGER.debug("async_step_user() passe au choix des lignes (%s)", len(lignes))
                return await self.async_step_lignes()
        LOGGER.debug("async_step_user() affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=erreurs,
        )

    async def async_step_lignes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix des lignes suivies pour les perturbations."""
        LOGGER.debug("async_step_lignes() appelé | saisie=%s", user_input is not None)
        if user_input is not None:
            LOGGER.debug("async_step_lignes() crée l'entrée")
            return self.async_create_entry(
                title="Ginko",
                data={CONF_CLE_API: self._cle},
                options={
                    CONF_LIGNES: user_input.get(CONF_LIGNES) or [],
                    CONF_ABONNEMENTS: [],
                },
            )
        LOGGER.debug("async_step_lignes() affiche le formulaire")
        return self.async_show_form(
            step_id="lignes",
            data_schema=vol.Schema(
                {vol.Optional(CONF_LIGNES, default=[]): cv.multi_select(self._selection_lignes())}
            ),
        )

    def _selection_lignes(self) -> dict[str, str]:
        """Lignes proposées, triées par typologie puis numéro public."""
        LOGGER.debug("_selection_lignes() appelé | %s ligne(s)", len(self._lignes))
        lignes = sorted(self._lignes, key=lambda ligne: (ligne.typologie, ligne.num_public))
        LOGGER.debug("_selection_lignes() retourne la sélection")
        return {ligne.id: f"{ligne.num_public} — {ligne.libelle}" for ligne in lignes}


class GinkoTraficOptionsFlow(OptionsFlow):
    """Options : lignes suivies, abonnements, ajout d'un abonnement."""

    def __init__(self) -> None:
        LOGGER.debug("GinkoTraficOptionsFlow.__init__() appelé")
        self._partiel: dict[str, Any] = {}
        self._nouvel_abonnement: dict | None = None
        self._ligne_choisie: Ligne | None = None
        self._variante_choisie_id: str = ""
        LOGGER.debug("GinkoTraficOptionsFlow.__init__() retourne")

    @callback
    def _options_actuelles(self) -> dict[str, Any]:
        return {
            CONF_LIGNES: list(self.config_entry.options.get(CONF_LIGNES) or []),
            CONF_ABONNEMENTS: list(self.config_entry.options.get(CONF_ABONNEMENTS) or []),
        }

    async def _async_lignes(self) -> list[Ligne]:
        """Lignes du réseau ; liste vide si l'API est indisponible."""
        LOGGER.debug("_async_lignes() appelé")
        client = GinkoClient(
            async_get_clientsession(self.hass),
            self.config_entry.data[CONF_CLE_API],
        )
        try:
            lignes = await client.async_get_lignes()
        except GinkoError as erreur:
            LOGGER.debug("lignes indisponibles : %s", erreur)
            LOGGER.debug("_async_lignes() retourne [] (API indisponible)")
            return []
        LOGGER.debug("_async_lignes() retourne %s ligne(s)", len(lignes))
        return lignes

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Lignes suivies, retrait d'abonnements, ajout facultatif."""
        LOGGER.debug("async_step_init() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        lignes = await self._async_lignes()
        if user_input is not None:
            abonnements = [json.loads(cle) for cle in user_input.get(CONF_ABONNEMENTS) or []]
            self._partiel = {
                CONF_LIGNES: user_input.get(CONF_LIGNES) or [],
                CONF_ABONNEMENTS: abonnements,
            }
            if user_input.get("ajouter"):
                LOGGER.debug("async_step_init() bascule vers l'ajout d'abonnement")
                return await self.async_step_abonnement_ligne()
            LOGGER.debug("async_step_init() enregistre les options")
            return self.async_create_entry(title="", data=self._partiel)
        options = self._options_actuelles()
        LOGGER.debug("async_step_init() affiche le formulaire")
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
        LOGGER.debug("async_step_abonnement_ligne() appelé | saisie=%s", user_input is not None)
        if user_input is not None:
            lignes = await self._async_lignes()
            self._ligne_choisie = next((ligne for ligne in lignes if ligne.id == user_input["ligne"]), None)
            if self._ligne_choisie is None or not self._ligne_choisie.variantes:
                LOGGER.debug("async_step_abonnement_ligne() : ligne indisponible")
                return self.async_show_form(
                    step_id="abonnement_ligne",
                    data_schema=vol.Schema({vol.Required("ligne"): str}),
                    errors={"ligne": "lignes_indisponibles"},
                )
            LOGGER.debug("async_step_abonnement_ligne() passe au choix du sens")
            return await self.async_step_abonnement_sens()
        lignes = await self._async_lignes()
        LOGGER.debug("async_step_abonnement_ligne() affiche le formulaire")
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
        LOGGER.debug("async_step_abonnement_sens() appelé | saisie=%s", user_input is not None)
        ligne = self._ligne_choisie
        assert ligne is not None
        if user_input is not None:
            self._variante_choisie_id = user_input["sens"]
            LOGGER.debug("async_step_abonnement_sens() passe au choix de l'arrêt")
            return await self.async_step_abonnement_arret()
        LOGGER.debug("async_step_abonnement_sens() affiche le formulaire")
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
        LOGGER.debug("async_step_abonnement_arret() appelé | saisie=%s", user_input is not None)
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
            LOGGER.debug("async_step_abonnement_arret() enregistre l'abonnement")
            return self.async_create_entry(title="", data={**self._partiel, CONF_ABONNEMENTS: abonnements})
        try:
            arrets = await client.async_get_details_variante(ligne.id, self._variante_choisie_id)
        except GinkoError as erreur:
            # Pas de saisie libre : l'erreur est conservée et le choix du
            # sens est re-proposé — le réenvoyer relance la récupération.
            LOGGER.debug("arrêts de la variante indisponibles : %s", erreur)
            LOGGER.debug("async_step_abonnement_arret() re-propose le choix du sens")
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
        LOGGER.debug("async_step_abonnement_arret() affiche le formulaire des arrêts")
        return self.async_show_form(
            step_id="abonnement_arret",
            data_schema=vol.Schema({vol.Required("arret"): vol.In({a.nom: a.nom for a in arrets})}),
        )
