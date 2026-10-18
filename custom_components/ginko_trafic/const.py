"""Constantes de l'intégration Ginko trafic."""

from __future__ import annotations

import logging

DOMAIN = "ginko_trafic"
LOGGER = logging.getLogger(__name__)

# Options (une entrée par réseau Ginko).
CONF_CLE_API = "cle_api"
CONF_LIGNES = "lignes"
CONF_ABONNEMENTS = "abonnements"

# Rafraîchissements : les temps d'attente sont recalculés toutes les
# 10 s (tram) à 30 s (bus) par Ginko ; les messages d'info-trafic ne
# doivent pas être conservés plus d'une minute (documentation Ginko).
INTERVALLE_PASSAGES_S = 60
INTERVALLE_TRAFIC_S = 60

# Champs d'un abonnement stocké dans les options.
ABO_ARRET = "arret"
ABO_ID_LIGNE = "id_ligne"
ABO_SENS_ALLER = "sens_aller"

# États d'une ligne (TR/getEtatLignes, champ etat).
ETAT_NORMAL = 1
ETATS_PERTURBATION = {4, 5, 6}  # prévue, en cours, circulation interrompue
LIBELLES_ETAT = {
    0: "inconnu",
    1: "normale",
    2: "information",
    3: "hors période de service",
    4: "perturbation prévue",
    5: "perturbation en cours",
    6: "circulation interrompue",
}
