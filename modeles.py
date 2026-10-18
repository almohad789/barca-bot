"""Structures de données partagées par toutes les sources (football-data, ESPN, saisie manuelle)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Code compétition -> nom affiché. Les codes PD et CL sont ceux de football-data.org,
# CDR et SC sont attribués par coupes.py.
COMPETITIONS = {
    "PD": "Liga",
    "CL": "Ligue des champions",
    "CDR": "Coupe du Roi",
    "SC": "Supercopa d'Espagne",
    "CWC": "Coupe du monde des clubs",
    "EL": "Ligue Europa",
}

ETAPES = {
    "REGULAR_SEASON": "",
    "LEAGUE_STAGE": "Phase de ligue",
    "GROUP_STAGE": "Phase de groupes",
    "PLAYOFFS": "Barrages",
    "LAST_64": "Trente-deuxième de finale",
    "LAST_32": "Seizième de finale",
    "LAST_16": "Huitième de finale",
    "QUARTER_FINALS": "Quart de finale",
    "SEMI_FINALS": "Demi-finale",
    "THIRD_PLACE": "Match pour la troisième place",
    "FINAL": "Finale",
    "ROUND_1": "Premier tour",
    "ROUND_2": "Deuxième tour",
    "ROUND_3": "Troisième tour",
}


@dataclass
class Equipe:
    id: str = ""
    nom: str = ""
    logo: str = ""
    buts: int | None = None
    classement: int | None = None


@dataclass
class But:
    minute: str
    buteur: str
    equipe_id: str
    type: str = ""            # "PENALTY", "OWN", ...


@dataclass
class Match:
    id: str                    # préfixé par la source : fd_, espn_, man_
    coup_envoi: datetime | None
    competition: str           # code, voir COMPETITIONS
    domicile: Equipe
    exterieur: Equipe
    etape: str = ""            # code d'étape football-data ou libellé libre
    journee: int | None = None
    statut: str = "SCHEDULED"  # SCHEDULED, TIMED, IN_PLAY, FINISHED, POSTPONED...
    stade: str = ""
    ville: str = ""
    vainqueur: str = ""        # HOME_TEAM, AWAY_TEAM, DRAW
    mi_temps: tuple[int | None, int | None] = (None, None)
    tab: tuple[int | None, int | None] = (None, None)   # tirs au but
    prolongation: bool = False
    buts_detail: list[But] = field(default_factory=list)
    source: str = ""

    # ------------------------------------------------------------ côtés
    def est_domicile(self, team_id: str) -> bool:
        return self.domicile.id == team_id

    def nous(self, team_id: str) -> Equipe:
        return self.domicile if self.est_domicile(team_id) else self.exterieur

    def eux(self, team_id: str) -> Equipe:
        return self.exterieur if self.est_domicile(team_id) else self.domicile

    # ------------------------------------------------------------ état
    @property
    def termine(self) -> bool:
        return self.statut in ("FINISHED", "AWARDED")

    @property
    def annule(self) -> bool:
        return self.statut in ("POSTPONED", "CANCELLED", "SUSPENDED")

    @property
    def horaire_confirme(self) -> bool:
        """football-data met SCHEDULED tant que l'heure n'est pas fixée par la ligue."""
        return self.statut != "SCHEDULED"

    def resultat(self, team_id: str) -> str:
        """V, N ou D du point de vue de l'équipe suivie. Les tirs au but départagent."""
        gagnant_dom = self.vainqueur == "HOME_TEAM"
        gagnant_ext = self.vainqueur == "AWAY_TEAM"
        if not (gagnant_dom or gagnant_ext):
            nous, eux = self.nous(team_id).buts, self.eux(team_id).buts
            if nous is None or eux is None:
                return "?"
            if nous == eux:
                return "N"
            return "V" if nous > eux else "D"
        return "V" if gagnant_dom == self.est_domicile(team_id) else "D"

    # ------------------------------------------------------------ libellés
    @property
    def nom_competition(self) -> str:
        return COMPETITIONS.get(self.competition, self.competition)

    @property
    def libelle(self) -> str:
        """Par exemple « Liga, 9e journée » ou « Ligue des champions, Quart de finale »."""
        etape = ETAPES.get(self.etape, self.etape)
        if self.competition == "PD" and self.journee:
            return f"{self.nom_competition}, {self.journee}e journée"
        if self.etape == "LEAGUE_STAGE" and self.journee:
            return f"{self.nom_competition}, phase de ligue, {self.journee}e journée"
        return f"{self.nom_competition}, {etape}" if etape else self.nom_competition


@dataclass
class Confrontations:
    victoires: int = 0
    nuls: int = 0
    defaites: int = 0
    buts_pour: int = 0
    buts_contre: int = 0
    derniers: list[str] = field(default_factory=list)

    @property
    def joues(self) -> int:
        return self.victoires + self.nuls + self.defaites

    @property
    def resume(self) -> str:
        if not self.joues:
            return "aucune confrontation récente dans les données"
        return f"{self.victoires} V, {self.nuls} N, {self.defaites} D"
