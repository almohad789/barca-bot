"""Événements planifiés Discord pour les matchs du Barça.

Un webhook ne sait que poster des messages. Les événements planifiés passent par
l'API des serveurs, qui exige un jeton d'application bot et la permission
« Gérer les événements ».

Différence avec le bot des Rams : en Liga, l'heure exacte n'est fixée que deux
à quatre semaines avant le match, et elle change parfois. Le bot :
  * ne crée un événement que lorsque l'heure est confirmée ;
  * retient l'identifiant Discord et l'heure dans state.json ;
  * corrige l'événement si l'heure ou le titre bouge, et le supprime si le match est reporté.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp

from diffusion import diffusion_france
from presentation import horaire, lieu

log = logging.getLogger("evenements")

API = "https://discord.com/api/v10"

DUREE_NORMALE = timedelta(hours=2)
DUREE_COUPE = timedelta(hours=2, minutes=30)     # prolongation et tirs au but possibles

PRIVACY_GUILD_ONLY = 2
ENTITY_EXTERNAL = 3


def _nom(match, team_id: str, nom_equipe: str) -> str:
    eux = match.eux(team_id)
    return f"⚽ {nom_equipe} vs {eux.nom}"[:100]


def _lieu(match, team_id: str, stade_domicile: str) -> str:
    texte = diffusion_france(match).court()
    stade = match.stade or (stade_domicile if match.est_domicile(team_id) else match.ville)
    if stade:
        texte += f" · {stade}"
    return texte[:100]


def _description(match, team_id: str, stade_domicile: str, h2h=None) -> str:
    diff = diffusion_france(match)
    lignes = [f"{match.libelle}.", lieu(match, team_id, stade_domicile).capitalize() + "."]
    if h2h is not None and h2h.joues:
        lignes.append(f"Face à {match.eux(team_id).nom} : {h2h.resume} sur les {h2h.joues} derniers matchs.")
    lignes += ["", "En France :"]
    for c in diff.france:
        lignes.append(f"{_icone(c)} {c.nom}" + (f" ({c.pourquoi})" if c.pourquoi else ""))
    if diff.note:
        lignes += ["", diff.note]
    return "\n".join(lignes)[:1000]


def _icone(c) -> str:
    return {"confirmé": "✅", "probable": "🟡", "possible": "⚪"}.get(c.confiance, "⚪")


def _charge(match, team_id, nom_equipe, stade_domicile, h2h=None) -> dict:
    duree = DUREE_NORMALE if match.competition == "PD" else DUREE_COUPE
    return {
        "name": _nom(match, team_id, nom_equipe),
        "privacy_level": PRIVACY_GUILD_ONLY,
        "scheduled_start_time": match.coup_envoi.isoformat(),
        "scheduled_end_time": (match.coup_envoi + duree).isoformat(),
        "entity_type": ENTITY_EXTERNAL,
        "entity_metadata": {"location": _lieu(match, team_id, stade_domicile)},
        "description": _description(match, team_id, stade_domicile, h2h),
    }


async def _appel(session, methode: str, url: str, token: str, charge: dict | None = None):
    entetes = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    async with session.request(methode, url, json=charge, headers=entetes) as resp:
        corps = await resp.text()
        if resp.status in (200, 201, 204):
            return resp.status, corps
        if resp.status == 429:
            log.warning("limite de débit Discord atteinte, suite au prochain passage")
        elif resp.status == 403:
            log.error("permission refusée : le bot doit avoir « Gérer les événements » sur le serveur")
        elif resp.status == 401:
            log.error("jeton de bot invalide : vérifie le secret DISCORD_BOT_TOKEN")
        elif resp.status != 404:
            log.error("Discord a refusé (%s) : %s", resp.status, corps[:300])
        return resp.status, corps


async def synchroniser(
    session: aiohttp.ClientSession,
    token: str,
    guild_id: str,
    matchs: list,
    team_id: str,
    nom_equipe: str,
    stade_domicile: str,
    evenements: dict,
    maintenant,
    horizon_jours: int = 45,
    maximum_par_passage: int = 5,
    enrichir=None,
) -> bool:
    """Crée, corrige ou supprime les événements. Renvoie True si l'état a changé.

    `evenements` est la partie de state.json qui associe un identifiant de
    match à {"id": identifiant Discord, "debut": heure ISO}.
    """
    if not token or not guild_id:
        return False

    import json

    base = f"{API}/guilds/{guild_id}/scheduled-events"
    modifie = False
    actions = 0
    limite = maintenant + timedelta(days=horizon_jours)

    for match in matchs:
        if actions >= maximum_par_passage:
            log.info("quota d'actions atteint pour ce passage, suite au prochain")
            break
        connu = evenements.get(match.id)

        # Match reporté ou annulé : on retire l'événement.
        if match.annule and connu:
            statut, _ = await _appel(session, "DELETE", f"{base}/{connu['id']}", token)
            if statut in (204, 404):
                evenements.pop(match.id)
                modifie = True
                actions += 1
                log.info("événement supprimé, match reporté : %s", match.id)
            continue

        if not match.coup_envoi or match.termine or match.annule or not match.horaire_confirme:
            continue
        if not (maintenant < match.coup_envoi <= limite):
            continue

        debut = match.coup_envoi.isoformat()
        nom = _nom(match, team_id, nom_equipe)
        if connu and connu.get("debut") == debut and connu.get("nom") == nom:
            continue

        h2h = None
        if enrichir is not None and not connu:
            try:
                h2h = await enrichir(match)
            except Exception as exc:
                log.warning("enrichissement impossible pour %s : %s", match.id, exc)

        charge = _charge(match, team_id, nom_equipe, stade_domicile, h2h)

        if connu:
            # L'heure ou le titre a changé : on corrige seulement ce qui diffère.
            correctif = {}
            if connu.get("debut") != debut:
                correctif.update({k: charge[k] for k in ("scheduled_start_time", "scheduled_end_time")})
            if connu.get("nom") != nom:
                correctif["name"] = nom
            statut, _ = await _appel(session, "PATCH", f"{base}/{connu['id']}", token, correctif)
            if statut == 200:
                if "name" in correctif:
                    log.info("titre corrigé pour %s : %s", match.id, nom)
                if "scheduled_start_time" in correctif:
                    log.info("horaire corrigé pour %s : %s", match.id, horaire(match))
                connu["debut"] = debut
                connu["nom"] = nom
            elif statut == 404:
                evenements.pop(match.id)          # supprimé à la main, on le recréera
            else:
                break
        else:
            statut, corps = await _appel(session, "POST", base, token, charge)
            if statut not in (200, 201):
                break                              # inutile d'insister si ça échoue
            evenements[match.id] = {"id": json.loads(corps).get("id"), "debut": debut, "nom": nom}
            log.info("événement créé pour %s", match.id)

        modifie = True
        actions += 1
        await asyncio.sleep(1)                     # on reste courtois avec l'API

    return modifie
