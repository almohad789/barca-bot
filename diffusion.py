"""Où regarder le Barça en France, saison 2026/2027.

Contrairement à la NFL, les droits du foot sont attribués par compétition, ce
qui rend la réponse bien plus fiable :

  * Liga : DAZN et Disney+, tous les matchs, diffusés en simultané sur les
    deux plateformes, de 2026/2027 à 2028/2029 (fin de 14 saisons de beIN).
  * Ligue des champions : groupe CANAL+, seul détenteur pour 2026/2027. La
    chaîne exacte (CANAL+, CANAL+ FOOT, CANAL+ SPORT ou un canal CANAL+ LIVE)
    n'est fixée qu'en cours de semaine.
  * Coupe du Roi : DAZN, jusqu'en 2029.
  * Supercopa d'Espagne : La Chaîne L'Équipe, en clair, demi-finales et
    finale, jusqu'en 2028.

Dès que la chaîne exacte d'un match est connue, la figer dans OVERRIDES avec
l'identifiant du match tel qu'il apparaît dans state.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OVERRIDES: dict[str, list[str]] = {
    # "fd_544321": ["CANAL+"],
}

PAR_COMPETITION: dict[str, list[tuple[str, str, str]]] = {
    "PD": [
        ("DAZN", "confirmé", "tous les matchs de Liga"),
        ("Disney+", "confirmé", "même match, en simultané"),
    ],
    "CL": [
        ("Groupe CANAL+", "confirmé", "détenteur exclusif de la Ligue des champions"),
    ],
    "CDR": [
        ("DAZN", "confirmé", "droits de la Coupe du Roi jusqu'en 2029"),
    ],
    "SC": [
        ("La Chaîne L'Équipe", "confirmé", "en clair, demi-finales et finale"),
    ],
}

NOTES = {
    "CL": "La chaîne précise (CANAL+, CANAL+ FOOT, CANAL+ SPORT ou CANAL+ LIVE) "
          "est annoncée en cours de semaine. À vérifier dans le programme CANAL+ la veille.",
    "CDR": "Pour les premiers tours, vérifier que l'affiche est bien retenue par DAZN.",
}


@dataclass
class Chaine:
    nom: str
    confiance: str      # "confirmé", "probable", "possible"
    pourquoi: str = ""

    ICONES = {"confirmé": "✅", "probable": "🟡", "possible": "⚪"}

    def rendu(self) -> str:
        icone = self.ICONES.get(self.confiance, "⚪")
        suite = f" ({self.pourquoi})" if self.pourquoi else ""
        return f"{icone} **{self.nom}**{suite}"


@dataclass
class Diffusion:
    france: list[Chaine] = field(default_factory=list)
    note: str = ""

    def texte(self) -> str:
        if not self.france:
            return "⚪ diffuseur pas encore identifié pour cette compétition"
        return "\n".join(c.rendu() for c in self.france)

    def court(self) -> str:
        """Pour le champ « lieu » des événements Discord."""
        return " ou ".join(c.nom for c in self.france[:2]) or "diffuseur à confirmer"


def diffusion_france(match) -> Diffusion:
    if match.id in OVERRIDES:
        return Diffusion([Chaine(n, "confirmé", "chaîne confirmée") for n in OVERRIDES[match.id]])
    lignes = PAR_COMPETITION.get(match.competition, [])
    return Diffusion(
        [Chaine(*l) for l in lignes],
        NOTES.get(match.competition, ""),
    )
