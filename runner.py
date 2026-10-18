"""Bot Barça, exécution unique, pour GitHub Actions.

Même principe que le bot des Rams : le workflow lance ce script toutes les
15 minutes, il regarde ce qui est dû, poste ce qui manque, puis s'arrête.

Usage :
    python runner.py            exécution normale
    python runner.py --test     poste l'annonce du prochain match tout de suite
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import discord

from coupes import matchs_coupes
from diffusion import diffusion_france
from evenements import synchroniser
from footballdata import FootballDataClient, saison_foot
from modeles import Confrontations, Match
from presentation import embed_annonce, embed_rappel, embed_rapport, horaire

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("runner")

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
JETON_FD = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
TEAM_ID = os.getenv("TEAM_ID", "81").strip()            # FC Barcelone sur football-data.org
NOM_EQUIPE = os.getenv("NOM_EQUIPE", "Barça").strip()
STADE = os.getenv("STADE_DOMICILE", "Spotify Camp Nou").strip()
ROLE_ID = os.getenv("ROLE_ID", "").strip()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()
EVENEMENTS_JOURS = int(os.getenv("EVENEMENTS_JOURS", "45"))

ANNONCE_HEURES = float(os.getenv("ANNONCE_HEURES", "48"))
RAPPEL_MINUTES = float(os.getenv("RAPPEL_MINUTES", "75"))
# Au-delà, un match terminé n'a plus droit à son rapport (évite un déluge au premier lancement).
RAPPORT_JOURS = float(os.getenv("RAPPORT_JOURS", "3"))

ETAT = Path("state.json")


# --------------------------------------------------------------------- état
def charger_etat() -> dict:
    """state.json contient deux parties : ce qui a été posté, et les événements Discord."""
    if ETAT.exists():
        try:
            brut = json.loads(ETAT.read_text(encoding="utf-8"))
            brut.setdefault("matchs", {})
            brut.setdefault("evenements", {})
            return brut
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("état illisible (%s), on repart de zéro", exc)
    return {"matchs": {}, "evenements": {}}


def signaler_changement() -> None:
    sortie = os.getenv("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write("changed=true\n")


def mention() -> str:
    return f"<@&{ROLE_ID}> " if ROLE_ID else ""


async def poster(session: aiohttp.ClientSession, contenu: str, embed: discord.Embed) -> None:
    charge = {
        "content": contenu[:1900],
        "embeds": [embed.to_dict()],
        "allowed_mentions": {"parse": ["roles"] if ROLE_ID else []},
    }
    async with session.post(WEBHOOK, json=charge) as resp:
        if resp.status >= 400:
            corps = await resp.text()
            raise RuntimeError(f"Discord a refusé le message ({resp.status}) : {corps[:300]}")


# --------------------------------------------------------------- données
async def calendrier(session, client: FootballDataClient, annee: int) -> list[Match]:
    """Liga et Ligue des champions par football-data, coupes par coupes.py, fusionnés."""
    matchs = await client.saison(TEAM_ID, annee)
    jours = {(m.competition, m.coup_envoi.date()) for m in matchs if m.coup_envoi}
    for m in await matchs_coupes(session, TEAM_ID, NOM_EQUIPE, annee):
        # Si un jour l'offre football-data inclut les coupes, pas de doublon.
        if m.coup_envoi and (m.competition, m.coup_envoi.date()) not in jours:
            matchs.append(m)
    fin = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(matchs, key=lambda m: m.coup_envoi or fin)


def forme(matchs: list[Match], avant: datetime) -> list[str]:
    """Les 5 derniers résultats, du plus ancien au plus récent, en pastilles."""
    passes = [m for m in matchs if m.termine and m.coup_envoi and m.coup_envoi < avant]
    pastilles = {"V": "🟩", "N": "⬜", "D": "🟥"}
    return [pastilles.get(m.resultat(TEAM_ID), "▫️") for m in passes[-5:]]


def bilan_saison(matchs: list[Match]) -> str:
    v = n = d = 0
    for m in matchs:
        if not m.termine:
            continue
        r = m.resultat(TEAM_ID)
        v, n, d = v + (r == "V"), n + (r == "N"), d + (r == "D")
    return f"{v} V, {n} N, {d} D" if v + n + d else ""


async def dossier(client: FootballDataClient, matchs: list[Match], match: Match):
    try:
        h2h = await client.confrontations(match, TEAM_ID)
    except Exception as exc:
        log.warning("confrontations indisponibles : %s", exc)
        h2h = Confrontations()
    classement = {}
    if match.competition == "PD":
        try:
            classement = await client.classement_liga()
        except Exception as exc:
            log.warning("classement indisponible : %s", exc)
    return h2h, forme(matchs, match.coup_envoi), classement, diffusion_france(match)


# --------------------------------------------------------------- exécution
async def executer(mode_test: bool = False) -> None:
    if not WEBHOOK:
        raise SystemExit("DISCORD_WEBHOOK_URL absent : ajoute-le dans les secrets du dépôt.")
    if not JETON_FD:
        raise SystemExit("FOOTBALL_DATA_TOKEN absent : crée une clé gratuite sur football-data.org.")

    etat = charger_etat()
    postes: dict[str, list[str]] = etat["matchs"]
    modifie = False
    premier_lancement = not postes and not etat.get("initialise")

    async with aiohttp.ClientSession(headers={"User-Agent": "barca-bot/1.0"}) as session:
        client = FootballDataClient(session, JETON_FD)
        annee = saison_foot()

        try:
            matchs = await calendrier(session, client, annee)
        except Exception as exc:
            log.error("calendrier indisponible : %s", exc)
            if mode_test:
                await poster(session, "", discord.Embed(
                    title=f"🧪 Test du bot {NOM_EQUIPE}",
                    description="Le webhook fonctionne, mais le calendrier football-data "
                                f"n'a pas pu être téléchargé.\n`{type(exc).__name__}: {str(exc)[:200]}`",
                    color=0xE67E22,
                ))
            return

        log.info("%d matchs pour la saison %d/%d", len(matchs), annee, annee + 1)
        maintenant = datetime.now(timezone.utc)

        # ---------------------------------------------------------- mode test
        if mode_test:
            futurs = [m for m in matchs if m.coup_envoi and m.coup_envoi > maintenant
                      and not m.termine and not m.annule]
            if not futurs:
                await poster(session, "", discord.Embed(
                    title=f"🧪 Test du bot {NOM_EQUIPE}",
                    description=f"Tout fonctionne, mais aucun match à venir pour la saison {annee}/{annee + 1}.",
                    color=0xE67E22,
                ))
                return
            match = futurs[0]
            h2h, frm, cls, diff = await dossier(client, matchs, match)
            await poster(
                session, "🧪 Message de test. Le bot est opérationnel.",
                embed_annonce(match, TEAM_ID, NOM_EQUIPE, h2h, frm, cls, diff, STADE),
            )
            log.info("message de test envoyé")
            return

        # ------------------------------------------- premier lancement
        if premier_lancement:
            for m in matchs:
                if m.termine:
                    postes.setdefault(m.id, []).append("rapport")
            etat["initialise"] = True
            modifie = True
            log.info("premier lancement : les matchs déjà joués sont marqués sans être postés")

        # ------------------------------------------- événements planifiés
        async def enrichir(match):
            return await client.confrontations(match, TEAM_ID)

        try:
            if await synchroniser(
                session, BOT_TOKEN, GUILD_ID, matchs, TEAM_ID, NOM_EQUIPE, STADE,
                etat["evenements"], maintenant, horizon_jours=EVENEMENTS_JOURS, enrichir=enrichir,
            ):
                modifie = True
        except Exception as exc:
            log.warning("synchronisation des événements impossible : %s", exc)

        # -------------------------------------------------------- mode normal
        for match in matchs:
            if not match.coup_envoi or match.annule:
                continue
            deja = postes.get(match.id, [])
            delta = match.coup_envoi - maintenant
            eux = match.eux(TEAM_ID).nom

            if (
                not match.termine
                and timedelta(0) < delta <= timedelta(hours=ANNONCE_HEURES)
                and "annonce" not in deja
            ):
                h2h, frm, cls, diff = await dossier(client, matchs, match)
                await poster(
                    session,
                    f"{mention()}🔵🔴 Le {NOM_EQUIPE} joue {horaire(match)} contre **{eux}** "
                    f"({match.nom_competition}).",
                    embed_annonce(match, TEAM_ID, NOM_EQUIPE, h2h, frm, cls, diff, STADE),
                )
                postes.setdefault(match.id, []).append("annonce")
                modifie = True
                log.info("annonce postée : %s", match.id)

            if (
                not match.termine
                and match.horaire_confirme
                and timedelta(0) < delta <= timedelta(minutes=RAPPEL_MINUTES)
                and "rappel" not in deja
            ):
                await poster(session, f"{mention()}⏰ Ça commence bientôt.",
                             embed_rappel(match, TEAM_ID, diffusion_france(match)))
                postes.setdefault(match.id, []).append("rappel")
                modifie = True
                log.info("rappel posté : %s", match.id)

            if (
                match.termine
                and "rapport" not in deja
                and -delta <= timedelta(days=RAPPORT_JOURS)
            ):
                classement = {}
                if match.competition == "PD":
                    try:
                        classement = await client.classement_liga()
                    except Exception as exc:
                        log.warning("classement indisponible : %s", exc)
                await poster(session, "", embed_rapport(
                    match, TEAM_ID, NOM_EQUIPE, bilan_saison(matchs), classement,
                ))
                postes.setdefault(match.id, []).append("rapport")
                modifie = True
                log.info("rapport posté : %s", match.id)

    if modifie:
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
        signaler_changement()
        log.info("état mis à jour")
    else:
        log.info("rien à publier cette fois")


if __name__ == "__main__":
    asyncio.run(executer(mode_test="--test" in sys.argv))
