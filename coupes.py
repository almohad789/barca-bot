"""Coupe du Roi et Supercopa d'Espagne, absentes de l'offre gratuite football-data.

Deux sources, utilisées ensemble :

1. ESPN, en tentative. Son API est souvent bloquée depuis les serveurs de
   GitHub Actions (c'était le cas pour le bot des Rams). Si elle répond, les
   matchs de coupe arrivent tout seuls, scores compris. Sinon, le bot l'écrit
   dans les journaux et continue sans planter.

2. MATCHS_MANUELS, juste en dessous. Une ligne par match de coupe, à ajouter
   dès que le tirage ou l'horaire est connu. C'est la solution qui marche à
   coup sûr. Pour ces matchs, le bot publie l'annonce, le rappel et
   l'événement Discord, mais pas de rapport de fin de match (il ne connaît pas
   le score). Si ESPN fournit le même match, la ligne manuelle est ignorée.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp

from modeles import Equipe, Match

log = logging.getLogger("coupes")

PARIS = ZoneInfo("Europe/Paris")

# Identifiant ESPN du FC Barcelone masculin (différent de celui de football-data).
ESPN_BARCA = "83"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{ligue}/scoreboard"
LIGUES_ESPN = {"esp.copa_del_rey": "CDR", "esp.super_cup": "SC"}

# ---------------------------------------------------------------------------
# À remplir à la main. Heure de Paris. Exemple :
#
#     {
#         "date": "2027-01-07 20:00",
#         "competition": "SC",                 # CDR = Coupe du Roi, SC = Supercopa
#         "tour": "Demi-finale",
#         "adversaire": "Athletic Club",
#         "domicile": False,                   # True si le Barça reçoit
#         "stade": "King Abdullah Sports City",
#         "ville": "Djeddah",
#     },
# ---------------------------------------------------------------------------
MATCHS_MANUELS: list[dict] = [
]


def _manuel_vers_match(ligne: dict, team_id: str, nom_equipe: str) -> Match | None:
    try:
        debut = datetime.strptime(ligne["date"], "%Y-%m-%d %H:%M").replace(tzinfo=PARIS)
    except (KeyError, ValueError):
        log.warning("ligne manuelle ignorée, date illisible : %s", ligne)
        return None
    nous = Equipe(id=team_id, nom=nom_equipe)
    eux = Equipe(id="adv", nom=ligne.get("adversaire", "?"))
    dom, ext = (nous, eux) if ligne.get("domicile", True) else (eux, nous)
    jour = debut.astimezone(timezone.utc).strftime("%Y%m%d")
    return Match(
        id=f"man_{jour}_{ligne.get('competition', 'X')}",
        coup_envoi=debut.astimezone(timezone.utc),
        competition=ligne.get("competition", "CDR"),
        domicile=dom,
        exterieur=ext,
        etape=ligne.get("tour", ""),
        statut="TIMED",
        stade=ligne.get("stade", ""),
        ville=ligne.get("ville", ""),
        source="saisie manuelle",
    )


def _espn_vers_match(evenement: dict, code: str, team_id: str, nom_equipe: str) -> Match | None:
    competition = (evenement.get("competitions") or [{}])[0]
    concurrents = competition.get("competitors") or []
    if not any(str((c.get("team") or {}).get("id")) == ESPN_BARCA for c in concurrents):
        return None

    def equipe(c: dict) -> Equipe:
        t = c.get("team") or {}
        barca = str(t.get("id")) == ESPN_BARCA
        try:
            buts = int(c.get("score")) if c.get("score") not in (None, "") else None
        except (TypeError, ValueError):
            buts = None
        return Equipe(
            id=team_id if barca else f"espn{t.get('id')}",
            nom=nom_equipe if barca else (t.get("shortDisplayName") or t.get("displayName") or "?"),
            logo="" if barca else (t.get("logo") or ""),
            buts=buts,
        )

    dom = next((c for c in concurrents if c.get("homeAway") == "home"), concurrents[0])
    ext = next((c for c in concurrents if c is not dom), concurrents[-1])
    domicile, exterieur = equipe(dom), equipe(ext)

    etat = ((evenement.get("status") or {}).get("type") or {})
    fini = bool(etat.get("completed"))
    vainqueur = ""
    if fini:
        if dom.get("winner"):
            vainqueur = "HOME_TEAM"
        elif ext.get("winner"):
            vainqueur = "AWAY_TEAM"
        else:
            vainqueur = "DRAW"

    try:
        debut = datetime.fromisoformat(evenement["date"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        debut = None

    lieu = competition.get("venue") or {}
    tour = ""
    for note in competition.get("notes") or []:
        tour = note.get("headline") or tour

    return Match(
        id=f"espn_{evenement.get('id')}",
        coup_envoi=debut,
        competition=code,
        domicile=domicile,
        exterieur=exterieur,
        etape=tour,
        statut="FINISHED" if fini else ("IN_PLAY" if etat.get("state") == "in" else "TIMED"),
        stade=lieu.get("fullName") or "",
        ville=(lieu.get("address") or {}).get("city") or "",
        vainqueur=vainqueur,
        source="ESPN",
    )


async def matchs_coupes(
    session: aiohttp.ClientSession, team_id: str, nom_equipe: str, annee: int
) -> list[Match]:
    trouves: list[Match] = []
    for ligue, code in LIGUES_ESPN.items():
        try:
            async with session.get(
                ESPN.format(ligue=ligue),
                params={"dates": f"{annee}0701-{annee + 1}0630", "limit": 300},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                donnees = await resp.json(content_type=None)
            for ev in donnees.get("events") or []:
                m = _espn_vers_match(ev, code, team_id, nom_equipe)
                if m:
                    trouves.append(m)
        except Exception as exc:
            log.warning("ESPN injoignable pour %s (%s), seule la saisie manuelle compte", ligue, exc)

    # Les lignes manuelles comblent ce qu'ESPN n'a pas donné.
    jours_espn = {
        (m.competition, m.coup_envoi.date()) for m in trouves if m.coup_envoi
    }
    for ligne in MATCHS_MANUELS:
        m = _manuel_vers_match(ligne, team_id, nom_equipe)
        if m and (m.competition, m.coup_envoi.date()) not in jours_espn:
            trouves.append(m)
    log.info("coupes : %d matchs", len(trouves))
    return trouves
