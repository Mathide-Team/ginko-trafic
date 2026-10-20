# Ginko trafic

Intégration Home Assistant pour le réseau **Ginko** (Besançon et Grand
Besançon Métropole) : perturbations par ligne et temps d'attente aux
arrêts, via l'[API open data Ginko](https://api.ginko.voyage/).

## Fonctionnalités

- **Perturbation par ligne** (binary sensor) : état info-trafic de chaque
  ligne suivie — normale, information, perturbation prévue, perturbation
  en cours ou circulation interrompue — avec les messages associés
  (titre, lien vers ginko.voyage).
- **Prochain passage** (capteur) par abonnement arrêt + ligne + sens :
  minutes d'attente du prochain passage mesuré (délai ou horaire
  lointain), destination, fiabilité — temps réel localisé ou
  estimation théorique —, horaire affiché, affluence prévue et liste
  des passages suivants en attributs. L'arrêt et le sens font partie
  du nom du capteur.
- **Alerte avant le passage** : créez une automation sur le nombre de
  minutes restantes, par exemple :

  ```yaml
  automation:
    - alias: "Bus dans moins de 10 minutes"
      trigger:
        - platform: numeric_state
          entity_id: sensor.ligne_42_exempleville_exemple_ouest_passage_exemple_mairie_aller
          below: 10
      condition:
        # Ne pas alerter sur une estimation théorique (véhicule non localisé).
        - condition: template
          value_template: >-
            {{ is_state_attr('sensor.ligne_42_exempleville_exemple_ouest_passage_exemple_mairie_aller',
            'temps_reel', true) }}
      action:
        - service: notify.mobile_app
          data:
            message: "Le bus 42 arrive à Exemple Mairie dans moins de 10 minutes"
  ```

  Adaptez l'identifiant d'entité (visible dans les outils de
  développement) et le service de notification à votre installation.

  Sans la condition, un horaire théorique (« estimation », `temps_reel`
  à `false`) peut aussi déclencher l'alerte.

- Les deux flux sont indépendants : une panne des temps d'attente ne
  fait pas perdre les infos trafic, et inversement.
- Une seule entrée pour le réseau ; lignes suivies et abonnements se
  gèrent dans les options (ajout en trois étapes : ligne, sens, arrêt ;
  suppression par désélection).

## Tableau de bord

Une vue prête à l'emploi est fournie dans
[`exemples/tableau-de-bord.yaml`](exemples/tableau-de-bord.yaml) :

- **bandeau d'alerte**, affiché seulement quand une ligne suivie est
  perturbée, avec les messages d'info-trafic ;
- **prochains passages** : tableau ligne, arrêt, direction, attente (en
  gras, « théorique » si le véhicule n'est pas localisé) et passages
  suivants ;
- **info trafic** : état de chaque ligne suivie.

Seules des cartes intégrées à Home Assistant sont utilisées. Les cartes
parcourent toutes les entités de l'intégration
(`integration_entities('ginko_trafic')`) : rien à adapter, les nouveaux
abonnements apparaissent d'eux-mêmes.

Installation : Paramètres → Tableaux de bord → ouvrir un tableau de bord
→ ⋮ → Modifier → ⋮ → Éditeur de configuration, puis coller le contenu
du fichier comme nouvel élément de `views:`.

## Prérequis : clé API

L'API Ginko exige une **clé gratuite** : demandez-la par courriel à
[ginko.support-ssi@keolis.com](mailto:ginko.support-ssi@keolis.com)
(objet « Demande de clé API »). La clé est saisie à la configuration et
validée immédiatement.

## Installation

### HACS

Ajoutez ce dépôt dans HACS (« Dépôts personnalisés », catégorie
« Intégration »), puis recherchez « Ginko trafic ». Sans release
publiée, [HACS installe la branche par défaut](https://www.hacs.xyz/docs/publish/integration/)
(les releases, une fois
publiées, offrent un choix de versions).

### Manuel

Copiez le dossier `custom_components/ginko_trafic` dans le dossier
`custom_components` de votre installation, puis redémarrez Home
Assistant.

## Configuration

1. Ajoutez l'intégration « Ginko trafic » et collez votre clé API.
2. Choisissez les lignes à suivre (perturbations).
3. Dans les options, ajoutez des abonnements de temps d'attente :
   ligne → sens (destination) → arrêt. Un même arrêt peut être suivi
   pour plusieurs lignes, et une même ligne dans les deux sens.

Les deux flux sont rafraîchis toutes les minutes : les temps
d'attente Ginko sont recalculés toutes les 10 s (tram) à 30 s (bus),
et la documentation de l'API demande de ne pas conserver les messages
d'info-trafic plus d'une minute.

## Limites connues (v0.1)

- Le capteur « prochain passage » affiche des minutes dès qu'une
  durée numérique est disponible (délai « 3 min » ou horaire lointain
  « 17h05 » converti) ; un texte de remplacement (« Travaux ») ou
  l'absence de mesure laisse le capteur sans valeur, le détail restant
  en attributs. Une estimation théorique (véhicule non localisé) est
  signalée par l'attribut `temps_reel` à `false`.
- Les messages d'info-trafic ne sont filtrés que par ligne en v0.1 ;
  le filtrage par arrêt (paramètre `idArrets` de l'API) reste à faire.
- L'intégration n'a pas encore été validée avec une clé API réelle :
  les tests s'appuient sur un serveur factice construit depuis la
  [spécification officielle de l'API](https://api.ginko.voyage/APIDoc/APIGinko.yaml).
- Les lignes scolaires et services à la demande ne sont pas ouvertes en
  open data par Ginko.
- Données sous [licence ODbL](https://opendatacommons.org/licenses/odbl/1-0/)
  (Keolis Besançon Mobilités / Grand Besançon Métropole) : mentionnez la
  provenance si vous rediffusez.

## Développement

Socle qualité Mathilde-Team : CI (ruff, yamllint, pytest, hassfest, HACS),
branches protégées `dev` → `main`.

```bash
uv run -p 3.13 --only-group test pytest -q   # tests
uv run --only-group lint ruff check .        # lint
```
