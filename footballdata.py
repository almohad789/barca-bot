"""Source principale : l'API football-data.org (version 4).

Pourquoi elle : gratuite avec une clé, stable, et joignable depuis GitHub Actions,
contrairement à ESPN qui filtre les adresses IP des datacenters.

L'offre gratuite couvre la Liga (PD) et la Ligue des champions (CL), ce qui
représente l'essentiel de la saison du Barça. La Coupe du Roi et la Supercopa
n'y sont pas : coupes.py s'en charge.

Limite de l'offre gratuite : 10 requêtes par minute. Le client fait une pause
tout seul quand football-data répond 429.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import aiohttp

from modeles import But, Confrontations, Equipe, Match

log = logging.getLogger("footballdata")

API = "https://api.football-data.org/v4"


def _date(brut: str | None) -> datetime | None:
    if not brut:
        return None
    try:
        return datetime.fromisoformat(brut.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _logo(url: str | None) -> str:
    # Discord n'affiche pas les SVG en vignette.
    if not url or url.lower().endswith(".svg"):
        return ""
    return url


def _equipe(brut: dict) -> Equipe:
    brut = brut or {}
    return Equipe(
        id=str(brut.get("id", "")),
        nom=brut.get("shortName") or brut.get("name") or "?",
        logo=_logo(brut.get("crest")),
        classement=brut.get("leagueRank"),
    )


def _paire(bloc: dict | None) -> tuple[int | None, int | None]:
    bloc = bloc or {}
    return bloc.get("home"), bloc.get("away")


def vers_match(brut: dict) -> Match:
    score = brut.get("score") or {}
    duree = score.get("duration", "REGULAR")
    dom, ext = _paire(score.get("fullTime"))
    tab = _paire(score.get("penalties"))

    # En cas de tirs au but, fullTime inclut les tirs réussis. On garde le score
    # du jeu (temps réglementaire + prolongation) et on affiche les tirs à part.
    if duree == "PENALTY_SHOOTOUT":
        reg_d, reg_e = _paire(score.get("regularTime"))
        pro_d, pro_e = _paire(score.get("extraTime"))
        if reg_d is not None and reg_e is not None:
            dom, ext = reg_d + (pro_d or 0), reg_e + (pro_e or 0)
        elif None not in (dom, ext) and None not in tab:
            dom, ext = dom - tab[0], ext - tab[1]

    domicile, exterieur = _equipe(brut.get("homeTeam")), _equipe(brut.get("awayTeam"))
    domicile.buts, exterieur.buts = dom, ext

    buts = []
    for b in brut.get("goals") or []:
        minute = str(b.get("minute") or "?")
        if b.get("injuryTime"):
            minute += f"+{b['injuryTime']}"
        buts.append(But(
            minute=minute,
            buteur=(b.get("scorer") or {}).get("name") or "?",
            equipe_id=str((b.get("team") or {}).get("id", "")),
            type=b.get("type") or "",
        ))

    return Match(
        id=f"fd_{brut.get('id')}",
        coup_envoi=_date(brut.get("utcDate")),
        competition=(brut.get("competition") or {}).get("code", ""),
        domicile=domicile,
        exterieur=exterieur,
        etape=brut.get("stage") or "",
        journee=brut.get("matchday"),
        statut=brut.get("status") or "SCHEDULED",
        stade=brut.get("venue") or "",
        vainqueur=score.get("winner") or "",
        mi_temps=_paire(score.get("halfTime")),
        tab=tab,
        prolongation=duree in ("EXTRA_TIME", "PENALTY_SHOOTOUT"),
        buts_detail=buts,
        source="football-data.org",
    )


class FootballDataClient:
    def __init__(self, session: aiohttp.ClientSession, jeton: str):
        self._session = session
        self._entetes = {"X-Auth-Token": jeton}
        self._cache: dict[str, dict] = {}

    async def _get(self, chemin: str, params: dict | None = None) -> dict:
        cle = chemin + repr(sorted((params or {}).items()))
        if cle in self._cache:
            return self._cache[cle]

        for tentative in range(3):
            async with self._session.get(
                f"{API}{chemin}", params=params, headers=self._entetes,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    attente = int(resp.headers.get("X-RequestCounter-Reset", "60") or 60) + 1
                    log.info("limite football-data atteinte, pause de %d s", attente)
                    await asyncio.sleep(min(attente, 65))
                    continue
                if resp.status == 403:
                    raise RuntimeError(
                        f"football-data refuse l'accès à {chemin} : compétition hors de l'offre gratuite ?"
                    )
                if resp.status == 400 and tentative == 0 and params and "dateFrom" in params:
                    raise ValueError("plage de dates refusée")
                resp.raise_for_status()
                donnees = await resp.json()
                self._cache[cle] = donnees
                return donnees
        raise RuntimeError("football-data reste saturé, on réessaiera au prochain passage")

    async def saison(self, team_id: str, annee: int) -> list[Match]:
        """Tous les matchs de l'équipe sur la saison, toutes compétitions de l'offre."""
        try:
            donnees = await self._get(
                f"/teams/{team_id}/matches",
                {"dateFrom": f"{annee}-07-01", "dateTo": f"{annee + 1}-06-30", "limit": 100},
            )
        except ValueError:
            donnees = await self._get(f"/teams/{team_id}/matches", {"season": annee, "limit": 100})
        matchs = [vers_match(m) for m in donnees.get("matches") or []]
        log.info("football-data : %d matchs pour la saison %d", len(matchs), annee)
        return matchs

    async def confrontations(self, match: Match, team_id: str, limite: int = 10) -> Confrontations:
        """Bilan des dernières rencontres face à l'adversaire du match."""
        identifiant = match.id.removeprefix("fd_")
        h2h = Confrontations()
        if not match.id.startswith("fd_"):
            return h2h
        donnees = await self._get(f"/matches/{identifiant}/head2head", {"limit": limite})
        anciens = sorted(
            (vers_match(m) for m in donnees.get("matches") or []),
            key=lambda m: m.coup_envoi or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        for m in anciens:
            if not m.termine or m.id == match.id:
                continue
            nous, eux = m.nous(team_id).buts, m.eux(team_id).buts
            if nous is None or eux is None:
                continue
            h2h.buts_pour += nous
            h2h.buts_contre += eux
            res = m.resultat(team_id)
            if res == "V":
                h2h.victoires += 1
            elif res == "D":
                h2h.defaites += 1
            else:
                h2h.nuls += 1
            if len(h2h.derniers) < 5:
                annee = m.coup_envoi.year if m.coup_envoi else "?"
                lieu = "dom." if m.est_domicile(team_id) else "ext."
                h2h.derniers.append(f"{res} {nous}:{eux} ({lieu}, {annee})")
        return h2h

    async def classement_liga(self) -> dict[str, tuple[int, int, int]]:
        """id équipe -> (position, points, matchs joués) au classement de Liga."""
        donnees = await self._get("/competitions/PD/standings")
        for bloc in donnees.get("standings") or []:
            if bloc.get("type") == "TOTAL":
                return {
                    str((ligne.get("team") or {}).get("id")): (
                        ligne.get("position"), ligne.get("points"), ligne.get("playedGames"),
                    )
                    for ligne in bloc.get("table") or []
                }
        return {}


def saison_foot(jour: date | None = None) -> int:
    """La saison 2026 court de juillet 2026 à juin 2027."""
    jour = jour or datetime.now(timezone.utc).date()
    return jour.year if jour.month >= 7 else jour.year - 1
