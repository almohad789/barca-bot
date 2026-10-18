# 🔵🔴 Bot Discord FC Barcelone

Prévient automatiquement quand le Barça masculin joue, **toutes compétitions
confondues** : Liga, Ligue des champions, Coupe du Roi et Supercopa. Horaire de
Paris, adversaire, bilan face à cette équipe, forme du moment, classement de
Liga, chaîne française, puis rapport de fin de match avec les buteurs. Il crée
aussi les **événements planifiés** du serveur Discord.

Même fonctionnement que le bot des Rams : **GitHub Actions**, sans serveur,
sans machine allumée.

---

## ⚙️ Comment il tourne

`runner.py` est exécuté **toutes les 15 minutes** par le workflow
`.github/workflows/barca.yml`. À chaque passage il télécharge le calendrier,
regarde ce qui est dû, poste ce qui manque, puis s'arrête.

`state.json` mémorise ce qui a déjà été publié (`annonce`, `rappel`,
`rapport`) et les événements Discord créés. Le workflow le recommite dès qu'il
change, ce qui garantit zéro doublon d'une exécution à l'autre.

Au **premier lancement**, les matchs déjà joués depuis le début de la saison
sont marqués comme traités sans rien poster : pas de rafale de rapports.

---

## 📡 D'où viennent les données

| Compétition          | Source | Automatique ? |
| -------------------- | ------ | ------------- |
| Liga                 | football-data.org | ✅ oui |
| Ligue des champions  | football-data.org | ✅ oui |
| Coupe du Roi         | ESPN, sinon saisie manuelle | 🟡 si ESPN répond |
| Supercopa d'Espagne  | ESPN, sinon saisie manuelle | 🟡 si ESPN répond |

**football-data.org** remplace nflverse : gratuit avec une clé, joignable depuis
GitHub Actions. Son offre gratuite ne contient pas les deux coupes espagnoles.

Pour celles ci, le bot tente **ESPN**. Comme pour les Rams, ESPN bloque souvent
les serveurs de GitHub : si c'est le cas, le journal affiche
`ESPN injoignable` et le bot continue normalement. Il suffit alors d'ajouter
les matchs de coupe à la main dans `MATCHS_MANUELS`, en haut de `coupes.py`,
dès que le tirage est connu :

```python
MATCHS_MANUELS = [
    {
        "date": "2027-01-07 20:00",          # heure de Paris
        "competition": "SC",                 # CDR = Coupe du Roi, SC = Supercopa
        "tour": "Demi-finale",
        "adversaire": "Athletic Club",
        "domicile": False,
        "stade": "King Abdullah Sports City",
        "ville": "Djeddah",
    },
]
```

Pour un match saisi à la main, le bot publie l'annonce, le rappel et
l'événement, mais pas le rapport de fin de match (il ne connaît pas le score).

---

## 📣 Ce que le bot publie tout seul

| Quand            | Contenu |
| ---------------- | ------- |
| **48 h avant**   | Adversaire, compétition et tour, date et heure de Paris, lieu, classement de Liga des deux équipes, bilan des 10 dernières confrontations, forme sur 5 matchs, chaîne française |
| **75 min avant** | Rappel court avec la chaîne |
| **Fin du match** | Score, mi-temps, buteurs, prolongation ou tirs au but, bilan de la saison toutes compétitions, place en Liga |
| **En continu**   | Un événement planifié Discord par match dont l'heure est fixée |

### Pas de pourcentage de victoire

Le bot des Rams calculait une probabilité à partir des cotes nflverse.
football-data ne fournit pas de cotes dans son offre gratuite : la section
**Pronostic** est remplacée par la **forme du moment** (🟩 victoire,
⬜ nul, 🟥 défaite) et le classement.

---

## 📅 Événements planifiés et horaires de Liga

En Liga, l'heure exacte n'est fixée que deux à quatre semaines avant le match,
et elle bouge parfois. Le bot en tient compte :

* tant que l'heure n'est pas fixée, **aucun événement** n'est créé, et
  l'annonce affiche « heure pas encore fixée » ;
* dès qu'elle l'est, l'événement est créé ;
* si elle change ensuite, l'événement est **corrigé** automatiquement ;
* si le match est reporté, l'événement est **supprimé**.

Comme pour les Rams, il faut une application bot :

1. `DISCORD_BOT_TOKEN` : jeton de l'application (onglet **Bot** →
   **Reset Token** sur [le portail développeur](https://discord.com/developers/applications)).
   Tu peux réutiliser celui du bot des Rams.
2. `DISCORD_GUILD_ID` : identifiant du serveur.
3. Permission **Gérer les événements** sur le serveur.

Durée des événements : 2 h en Liga, 2 h 30 en coupe (prolongation possible).
Au maximum **5 créations ou corrections par passage**.

---

## 🔧 Mise en route

1. Crée une clé gratuite sur [football-data.org](https://www.football-data.org/client/register).
   Elle arrive par mail.
2. Crée un nouveau dépôt GitHub `barca-bot` et envoie y ces fichiers.
3. Dans *Settings → Secrets and variables → Actions*, ajoute les secrets.
4. Onglet **Actions** → **Bot Barça** → **Run workflow** → cocher
   *Poster un message de test tout de suite*.

**Secrets**

| Nom                   | Obligatoire | Rôle |
| --------------------- | ----------- | ---- |
| `DISCORD_WEBHOOK_URL` | oui         | webhook du salon où le bot poste |
| `FOOTBALL_DATA_TOKEN` | oui         | clé football-data.org |
| `DISCORD_BOT_TOKEN`   | non         | uniquement pour les événements planifiés |
| `DISCORD_GUILD_ID`    | non         | idem |

**Variables**

| Nom       | Défaut | Rôle |
| --------- | ------ | ---- |
| `ROLE_ID` | vide   | rôle à mentionner dans les annonces et rappels |

**Réglages dans le workflow** (`env:` du job, dans `barca.yml`)

| Nom                | Défaut              | Rôle |
| ------------------ | ------------------- | ---- |
| `TEAM_ID`          | `81`                | identifiant football-data du Barça masculin |
| `NOM_EQUIPE`       | `Barça`             | nom affiché dans les messages |
| `STADE_DOMICILE`   | `Spotify Camp Nou`  | stade affiché quand la source n'en donne pas |
| `EVENEMENTS_JOURS` | `45` (365 dans le workflow) | horizon des événements |
| `ANNONCE_HEURES`   | `48`                | délai de l'annonce |
| `RAPPEL_MINUTES`   | `75`                | délai du rappel |
| `RAPPORT_JOURS`    | `3`                 | au delà, un match terminé n'a plus de rapport |

---

## 🇫🇷 Diffusion en France, saison 2026/2027

Contrairement à la NFL, les droits sont attribués **par compétition**, donc la
chaîne est presque toujours certaine :

| Compétition         | Chaîne | Confiance |
| ------------------- | ------ | --------- |
| Liga                | **DAZN** et **Disney+**, en simultané, jusqu'en 2029 | ✅ |
| Ligue des champions | **Groupe CANAL+**, seul diffuseur | ✅ chaîne exacte annoncée en semaine |
| Coupe du Roi        | **DAZN**, jusqu'en 2029 | ✅ |
| Supercopa           | **La Chaîne L'Équipe**, en clair, jusqu'en 2028 | ✅ |

Pour la Ligue des champions, CANAL+ répartit les matchs entre CANAL+,
CANAL+ FOOT, CANAL+ SPORT et les canaux CANAL+ LIVE. Dès que tu connais la
chaîne exacte, fige la dans `OVERRIDES` en haut de `diffusion.py`. La clé est
l'identifiant du match visible dans `state.json` :

```python
OVERRIDES = {
    "fd_544321": ["CANAL+"],
}
```

---

## 🧪 Tester en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python test_local.py
```

`test_local.py` simule football-data, ESPN et Discord et rejoue cinq passages
(premier lancement, annonce, rappel, rapport avec buteurs, horaire décalé).
Rien n'est envoyé.

Test réel avec ton webhook :

```bash
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
FOOTBALL_DATA_TOKEN="ta_cle" python runner.py --test
```

---

## 📁 Structure du dépôt

```
barca-bot/
├── runner.py          # point d'entrée GitHub Actions, exécution unique
├── footballdata.py    # client football-data.org : calendrier, confrontations, classement
├── coupes.py          # Coupe du Roi et Supercopa : ESPN + MATCHS_MANUELS
├── modeles.py         # structures Match, Equipe, Confrontations
├── presentation.py    # embeds Discord et dates en français
├── diffusion.py       # chaînes françaises par compétition, OVERRIDES
├── evenements.py      # événements planifiés : création, correction, suppression
├── test_local.py      # test hors ligne de bout en bout
├── state.json         # ce qui a déjà été publié (auto, à garder avec le code)
└── .github/workflows/
    └── barca.yml      # exécution toutes les 15 minutes
```

Par rapport au bot des Rams, il n'y a pas de `bot.py` ni de `espn.py` : pas de
version historique à conserver.
