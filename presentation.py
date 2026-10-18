"""Construction des messages Discord : dates en français et embeds."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from diffusion import Diffusion
from modeles import Confrontations, Match

PARIS = ZoneInfo("Europe/Paris")

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

COULEUR_BARCA = 0xA50044          # grenat
COULEUR_VICTOIRE = 0x2ECC71
COULEUR_DEFAITE = 0xE74C3C
COULEUR_NULLE = 0x95A5A6

ICONES = {"PD": "🇪🇸", "CL": "⭐", "CDR": "🏆", "SC": "🏆", "CWC": "🌍"}


def fr_datetime(dt: datetime | None, avec_annee: bool = False) -> str:
    if dt is None:
        return "horaire non communiqué"
    local = dt.astimezone(PARIS)
    annee = f" {local.year}" if avec_annee else ""
    return f"{JOURS[local.weekday()]} {local.day} {MOIS[local.month - 1]}{annee} à {local:%Hh%M}"


def fr_date(dt: datetime | None) -> str:
    if dt is None:
        return "date non communiquée"
    local = dt.astimezone(PARIS)
    return f"{JOURS[local.weekday()]} {local.day} {MOIS[local.month - 1]} {local.year}"


def horaire(match: Match, avec_annee: bool = False) -> str:
    if match.horaire_confirme:
        return fr_datetime(match.coup_envoi, avec_annee)
    return fr_date(match.coup_envoi) + ", heure pas encore fixée"


def timestamp_discord(dt: datetime | None) -> str:
    """Horodatage natif Discord : chacun le voit dans son fuseau."""
    if dt is None:
        return ""
    t = int(dt.timestamp())
    return f"<t:{t}:F> (<t:{t}:R>)"


def titre_match(match: Match) -> str:
    return f"{match.domicile.nom} 🆚 {match.exterieur.nom}"


def lieu(match: Match, team_id: str, stade_domicile: str) -> str:
    cote = "à domicile" if match.est_domicile(team_id) else "à l'extérieur"
    stade = match.stade or (stade_domicile if match.est_domicile(team_id) else "")
    if match.ville and match.ville.lower() not in stade.lower():
        stade = f"{stade}, {match.ville}" if stade else match.ville
    return f"{cote} · {stade}" if stade else cote


def embed_annonce(
    match: Match,
    team_id: str,
    nom_equipe: str,
    h2h: Confrontations,
    forme: list[str],
    classement: dict,
    diff: Diffusion,
    stade_domicile: str,
    titre: str | None = None,
) -> discord.Embed:
    eux = match.eux(team_id)
    icone = ICONES.get(match.competition, "⚽")

    embed = discord.Embed(
        title=titre or f"{icone} Prochain match du {nom_equipe}",
        description=f"**{titre_match(match)}**\n{match.libelle}",
        color=COULEUR_BARCA,
    )
    if eux.logo:
        embed.set_thumbnail(url=eux.logo)

    quand = horaire(match, avec_annee=True)
    if match.horaire_confirme:
        quand += "\n" + timestamp_discord(match.coup_envoi)
    embed.add_field(name="🗓️ Coup d'envoi (heure de Paris)", value=quand, inline=False)
    embed.add_field(name="📍 Où", value=lieu(match, team_id, stade_domicile), inline=False)

    # Classement de Liga, seulement si les deux équipes y figurent
    if match.competition == "PD" and classement:
        lignes = []
        for equipe in (match.nous(team_id), eux):
            pos = classement.get(equipe.id)
            if pos:
                nom = nom_equipe if equipe.id == team_id else equipe.nom
                lignes.append(f"{nom} : {pos[0]}e, {pos[1]} pts en {pos[2]} matchs")
        if lignes:
            embed.add_field(name="📋 Classement de Liga", value="\n".join(lignes), inline=False)

    # Bilan face à l'adversaire
    lignes = [f"**{h2h.resume}**" + (f" sur les {h2h.joues} derniers matchs" if h2h.joues else "")]
    if h2h.joues:
        lignes.append(
            f"Buts : {h2h.buts_pour} marqués, {h2h.buts_contre} encaissés "
            f"({h2h.buts_pour / h2h.joues:.1f} et {h2h.buts_contre / h2h.joues:.1f} par match)"
        )
    if h2h.derniers:
        lignes.append("Dernières confrontations : " + " · ".join(h2h.derniers))
    embed.add_field(name=f"📊 Face à {eux.nom}", value="\n".join(lignes), inline=False)

    if forme:
        embed.add_field(
            name="📈 Forme du moment",
            value=" ".join(forme) + "\n_5 derniers matchs, toutes compétitions, du plus ancien au plus récent_",
            inline=False,
        )

    embed.add_field(name="🇫🇷 Diffusion en France", value=diff.texte(), inline=False)
    if diff.note:
        embed.add_field(name="ℹ️ À savoir", value=diff.note, inline=False)

    embed.set_footer(text=f"Données {match.source} · droits TV saison 2026/2027")
    return embed


def embed_rappel(match: Match, team_id: str, diff: Diffusion) -> discord.Embed:
    eux = match.eux(team_id)
    embed = discord.Embed(
        title="⏰ Coup d'envoi dans une heure",
        description=f"**{titre_match(match)}**\n{match.libelle}\n"
                    f"{fr_datetime(match.coup_envoi)} heure de Paris",
        color=COULEUR_BARCA,
    )
    if eux.logo:
        embed.set_thumbnail(url=eux.logo)
    embed.add_field(name="🇫🇷 Où regarder", value=diff.texte(), inline=False)
    return embed


def _score(match: Match) -> str:
    d, e = match.domicile.buts, match.exterieur.buts
    texte = f"{match.domicile.nom} {d if d is not None else '?'} : {e if e is not None else '?'} {match.exterieur.nom}"
    if None not in match.tab:
        texte += f" ({match.tab[0]} : {match.tab[1]} aux tirs au but)"
    elif match.prolongation:
        texte += " (après prolongation)"
    return texte


def _commentaire(match: Match, team_id: str) -> str:
    nous, eux = match.nous(team_id).buts or 0, match.eux(team_id).buts or 0
    ecart = abs(nous - eux)
    if None not in match.tab:
        return "Tout s'est joué aux tirs au but."
    if ecart == 0:
        return "Les deux équipes se quittent dos à dos." if nous else "Aucun but de part et d'autre."
    if ecart == 1:
        return "Un seul but d'écart, jusqu'au bout."
    if ecart == 2:
        return "Match maîtrisé sans être tranquille."
    return "Écart net au tableau d'affichage."


def embed_rapport(
    match: Match,
    team_id: str,
    nom_equipe: str,
    bilan_saison: str,
    classement: dict,
) -> discord.Embed:
    res = match.resultat(team_id)
    couleur, entete = {
        "V": (COULEUR_VICTOIRE, f"✅ Victoire du {nom_equipe}"),
        "D": (COULEUR_DEFAITE, f"❌ Défaite du {nom_equipe}"),
    }.get(res, (COULEUR_NULLE, "🤝 Match nul"))
    if None not in match.tab and res == "V":
        entete = f"✅ Le {nom_equipe} passe aux tirs au but"
    elif None not in match.tab and res == "D":
        entete = f"❌ Le {nom_equipe} sort aux tirs au but"

    eux = match.eux(team_id)
    embed = discord.Embed(
        title=entete,
        description=f"**{_score(match)}**\n{match.libelle} · {_commentaire(match, team_id)}",
        color=couleur,
    )
    if eux.logo:
        embed.set_thumbnail(url=eux.logo)

    if None not in match.mi_temps:
        embed.add_field(
            name="🕐 Mi-temps",
            value=f"{match.domicile.nom} {match.mi_temps[0]} : {match.mi_temps[1]} {match.exterieur.nom}",
            inline=False,
        )

    if match.buts_detail:
        for equipe in (match.domicile, match.exterieur):
            lignes = []
            for b in match.buts_detail:
                if b.equipe_id != equipe.id:
                    continue
                marque = {"PENALTY": " (pén.)", "OWN": " (c.s.c.)"}.get(b.type, "")
                lignes.append(f"{b.minute}' {b.buteur}{marque}")
            if lignes:
                nom = nom_equipe if equipe.id == team_id else equipe.nom
                embed.add_field(name=f"⚽ {nom}", value="\n".join(lignes), inline=True)

    contexte = []
    if bilan_saison:
        contexte.append(f"Bilan de la saison, toutes compétitions : **{bilan_saison}**")
    if match.competition == "PD":
        pos = classement.get(team_id)
        if pos:
            contexte.append(f"Classement de Liga : **{pos[0]}e** avec {pos[1]} points")
    if contexte:
        embed.add_field(name=f"📈 Où en est le {nom_equipe}", value="\n".join(contexte), inline=False)

    pied = f"{match.stade} · " if match.stade else ""
    embed.set_footer(text=f"{pied}Données {match.source}")
    return embed
