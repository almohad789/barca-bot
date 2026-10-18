"""Vérification hors ligne : simule football-data, ESPN et Discord, puis rejoue
plusieurs passages du bot à des instants différents.

    python test_local.py

Aucun message n'est envoyé, rien n'est écrit dans le vrai state.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

MAINTENANT = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def equipe(i, nom):
    return {"id": i, "name": nom, "shortName": nom, "tla": nom[:3].upper(),
            "crest": f"https://crests.football-data.org/{i}.png"}


BARCA = equipe(81, "Barça")
MATCHS = [
    {   # joué la semaine dernière, ne doit PAS être rapporté au premier lancement
        "id": 1, "utcDate": iso(MAINTENANT - timedelta(days=8)), "status": "FINISHED",
        "matchday": 8, "stage": "REGULAR_SEASON", "competition": {"code": "PD"},
        "homeTeam": BARCA, "awayTeam": equipe(559, "Sevilla"),
        "score": {"winner": "HOME_TEAM", "duration": "REGULAR",
                  "fullTime": {"home": 3, "away": 1}, "halfTime": {"home": 1, "away": 0}},
    },
    {   # dans 30 h : annonce attendue
        "id": 2, "utcDate": iso(MAINTENANT + timedelta(hours=30)), "status": "TIMED",
        "matchday": 3, "stage": "LEAGUE_STAGE", "competition": {"code": "CL"},
        "homeTeam": equipe(5, "Bayern"), "awayTeam": BARCA,
        "score": {"fullTime": {"home": None, "away": None}},
    },
    {   # heure pas encore fixée : pas d'événement Discord
        "id": 3, "utcDate": iso(MAINTENANT + timedelta(days=12)), "status": "SCHEDULED",
        "matchday": 10, "stage": "REGULAR_SEASON", "competition": {"code": "PD"},
        "homeTeam": BARCA, "awayTeam": equipe(86, "Real Madrid"),
        "score": {"fullTime": {"home": None, "away": None}},
    },
]
H2H = {"matches": [
    {"id": 90, "utcDate": "2025-04-16T19:00:00Z", "status": "FINISHED", "competition": {"code": "CL"},
     "homeTeam": BARCA, "awayTeam": equipe(5, "Bayern"),
     "score": {"winner": "HOME_TEAM", "fullTime": {"home": 4, "away": 1}}},
    {"id": 91, "utcDate": "2024-10-23T19:00:00Z", "status": "FINISHED", "competition": {"code": "CL"},
     "homeTeam": BARCA, "awayTeam": equipe(5, "Bayern"),
     "score": {"winner": "HOME_TEAM", "fullTime": {"home": 4, "away": 1}}},
    {"id": 92, "utcDate": "2020-08-14T19:00:00Z", "status": "FINISHED", "competition": {"code": "CL"},
     "homeTeam": BARCA, "awayTeam": equipe(5, "Bayern"),
     "score": {"winner": "AWAY_TEAM", "fullTime": {"home": 2, "away": 8}}},
]}
CLASSEMENT = {"standings": [{"type": "TOTAL", "table": [
    {"position": 1, "team": {"id": 81}, "points": 21, "playedGames": 8},
    {"position": 2, "team": {"id": 86}, "points": 19, "playedGames": 8},
]}]}
ESPN_COUPE = {"events": [{
    "id": "700", "date": iso(MAINTENANT + timedelta(days=60)),
    "status": {"type": {"state": "pre", "completed": False}},
    "competitions": [{
        "venue": {"fullName": "Estadio Pedro Escartín", "address": {"city": "Guadalajara"}},
        "notes": [{"headline": "Seizième de finale"}],
        "competitors": [
            {"homeAway": "home", "team": {"id": "5000", "shortDisplayName": "Guadalajara"}},
            {"homeAway": "away", "team": {"id": "83", "shortDisplayName": "Barcelona"}},
        ],
    }],
}]}


class Reponse:
    def __init__(self, statut=200, donnees=None, entetes=None):
        self.status, self._d, self.headers = statut, donnees or {}, entetes or {}

    async def json(self, content_type=None):
        return self._d

    async def text(self):
        return json.dumps(self._d)

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FausseSession:
    def __init__(self, *a, **k):
        self.messages, self.evenements = [], []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, params=None, headers=None, timeout=None):
        if "head2head" in url:
            return Reponse(200, H2H)
        if "/standings" in url:
            return Reponse(200, CLASSEMENT)
        if "/teams/81/matches" in url:
            return Reponse(200, {"matches": MATCHS})
        if "esp.copa_del_rey" in url:
            return Reponse(200, ESPN_COUPE)
        return Reponse(403)          # Supercopa : on simule le blocage ESPN

    def post(self, url, json=None):
        SESSIONS[-1].messages.append(json)
        return Reponse(204)

    def request(self, methode, url, json=None, headers=None):
        SESSIONS[-1].evenements.append((methode, url, json))
        return Reponse(200, {"id": f"ev{len(SESSIONS[-1].evenements)}"})


SESSIONS: list[FausseSession] = []


def nouvelle_session(*a, **k):
    s = FausseSession()
    SESSIONS.append(s)
    return s


async def passage(runner, instant):
    with mock.patch("runner.aiohttp.ClientSession", nouvelle_session), \
         mock.patch("runner.datetime") as dt, \
         mock.patch("evenements.asyncio.sleep", mock.AsyncMock()):
        dt.now.return_value = instant
        dt.max = datetime.max
        await runner.executer()
    return SESSIONS[-1]


def resume(session):
    for m in session.messages:
        e = m["embeds"][0]
        print(f"  📨 {m['content'][:90]!r}")
        print(f"     {e['title']} | {e.get('description', '').splitlines()[0]}")
        for f in e.get("fields", []):
            print(f"       {f['name']}: {f['value'].splitlines()[0][:90]}")
    for methode, url, charge in session.evenements:
        print(f"  📅 {methode} {charge['name'] if charge and 'name' in charge else url.split('/')[-1]}"
              + (f" @ {charge['entity_metadata']['location']}" if charge and "entity_metadata" in charge else ""))


async def main():
    dossier = Path(tempfile.mkdtemp())
    os.chdir(dossier)
    Path("state.json").write_text('{"matchs": {}, "evenements": {}}')
    os.environ.update(DISCORD_WEBHOOK_URL="https://x", FOOTBALL_DATA_TOKEN="t",
                      DISCORD_BOT_TOKEN="b", DISCORD_GUILD_ID="g",
                      EVENEMENTS_JOURS="365")

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import runner

    print("Passage 1 : premier lancement, Bayern dans 30 h")
    s = await passage(runner, MAINTENANT)
    resume(s)
    assert len(s.messages) == 1, "une seule annonce attendue (Bayern), pas de rapport Séville"
    noms = [c["name"] for _, _, c in s.evenements]
    assert any("Bayern" in n for n in noms) and any("Guadalajara" in n for n in noms)
    assert not any("Real" in n for n in noms), "pas d'événement si l'heure n'est pas fixée"

    print("\nPassage 2 : 15 minutes plus tard, rien de neuf")
    s = await passage(runner, MAINTENANT + timedelta(minutes=15))
    resume(s)
    assert not s.messages and not s.evenements

    print("\nPassage 3 : 1 h avant le match")
    s = await passage(runner, MAINTENANT + timedelta(hours=29))
    resume(s)
    assert len(s.messages) == 1 and "bientôt" in s.messages[0]["content"]

    print("\nPassage 4 : le Clásico reçoit son heure, puis le Bayern est terminé (2:2, buteurs)")
    MATCHS[2]["status"] = "TIMED"
    MATCHS[1].update(status="FINISHED", score={
        "winner": "DRAW", "duration": "REGULAR",
        "fullTime": {"home": 2, "away": 2}, "halfTime": {"home": 1, "away": 1}})
    MATCHS[1]["goals"] = [
        {"minute": 12, "team": {"id": 5}, "scorer": {"name": "H. Kane"}, "type": "PENALTY"},
        {"minute": 40, "team": {"id": 81}, "scorer": {"name": "Lamine Yamal"}},
        {"minute": 77, "team": {"id": 81}, "scorer": {"name": "R. Lewandowski"}},
        {"minute": 90, "injuryTime": 3, "team": {"id": 5}, "scorer": {"name": "M. Olise"}},
    ]
    s = await passage(runner, MAINTENANT + timedelta(hours=33))
    resume(s)
    assert any("nul" in m["embeds"][0]["title"] for m in s.messages)
    assert any("Real" in (c or {}).get("name", "") for _, _, c in s.evenements)

    print("\nPassage 5 : la Liga décale le Clásico de 2 heures")
    MATCHS[2]["utcDate"] = iso(MAINTENANT + timedelta(days=12, hours=2))
    s = await passage(runner, MAINTENANT + timedelta(hours=34))
    resume(s)
    assert [m for m, _, _ in s.evenements] == ["PATCH"]

    print("\nÉtat final :")
    print(Path("state.json").read_text())
    print("\n✅ Tous les contrôles passent.")


if __name__ == "__main__":
    asyncio.run(main())
