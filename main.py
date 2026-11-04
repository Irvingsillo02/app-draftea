"""Panel Estadístico Draftea Pro v3 — versión football-data.org (un solo archivo).

Requisitos (requirements.txt): fastapi, uvicorn[standard], httpx
Variable de entorno en Render: FOOTBALL_DATA_KEY
Start command en Render:       uvicorn main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import logging
import os
import re
import time
import unicodedata
from collections import defaultdict, deque
from difflib import SequenceMatcher
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from math import exp, factorial
from typing import Annotated, Any, Awaitable, Callable

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)

# =====================================================================
# 1. CONFIGURACIÓN
# =====================================================================
API_KEY = next(
    (os.getenv(k) for k in ("FOOTBALL_DATA_KEY", "FOOTBALL_DATA_API_KEY", "API_KEY") if os.getenv(k)),
    None,
)
API_BASE = os.getenv("API_BASE", "https://api.football-data.org/v4")
RATE_POR_MIN = int(os.getenv("RATE_POR_MIN", "9"))  # el plan gratuito permite 10/min
MAX_ESPERA_SEG = 25

# The Odds API (cuotas). Variable de entorno en Render: ODDS_API_KEY
ODDS_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")
TTL_CUOTAS = 43200  # 12 h: cuida los créditos del plan gratuito (500 al mes)
UMBRAL_EV = 0.05    # valor esperado mínimo para marcar "posible valor"
UMBRAL_DIF = 0.03   # y al menos 3 puntos porcentuales sobre el mercado

SPORT_KEYS = {
    "PL": "soccer_epl",
    "PD": "soccer_spain_la_liga",
    "BL1": "soccer_germany_bundesliga",
    "CL": "soccer_uefa_champs_league",
    "SA": "soccer_italy_serie_a",
}
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

TTL_CARTELERA = 1800     # 30 min
TTL_EQUIPOS = 86400      # 24 h
TTL_PARTIDOS = 3600      # 1 h
TTL_H2H = 21600          # 6 h

# Competiciones incluidas en el plan gratuito de football-data.org
LIGAS: dict[str, str] = {
    "PL": "Premier League (Inglaterra)",
    "PD": "La Liga (España)",
    "SA": "Serie A (Italia)",
    "BL1": "Bundesliga (Alemania)",
    "FL1": "Ligue 1 (Francia)",
    "CL": "Champions League",
    "PPL": "Primeira Liga (Portugal)",
    "DED": "Eredivisie (Países Bajos)",
    "BSA": "Brasileirão (Brasil)",
    "ELC": "Championship (Inglaterra)",
    "EC": "Eurocopa",
    "WC": "Mundial (FIFA)",
}


# =====================================================================
# 3. MODELOS DE RESPUESTA
# =====================================================================
class EquipoRef(BaseModel):
    id: int
    nombre: str
    logo: str | None = None


class Equipo(EquipoRef):
    tiene_dfs: bool = False


class Partido(BaseModel):
    fixture_id: int
    fecha: str
    ronda: str | None = None
    estadio: str | None = None
    local: Equipo
    visita: Equipo


class Forma(BaseModel):
    partidos: int = 0
    ganados: int = 0
    empatados: int = 0
    perdidos: int = 0
    gf_prom: float | None = None
    gc_prom: float | None = None
    goles_totales_prom: float | None = None
    btts_pct: float | None = None
    over15_pct: float | None = None
    over25_pct: float | None = None
    porteria_cero_pct: float | None = None  # % de partidos sin recibir gol
    sin_anotar_pct: float | None = None     # % de partidos sin marcar
    over25_ult5: int = 0                    # de sus últimos 5, cuántos pasaron de 2.5
    btts_ult5: int = 0
    racha: str = ""  # más reciente primero


class Marcador(BaseModel):
    marcador: str
    prob: float


class Probabilidades(BaseModel):
    local: float
    empate: float
    visita: float
    over15: float
    over25: float
    over35: float
    btts: float
    goles_esperados_local: float
    goles_esperados_visita: float
    marcadores_probables: list[Marcador]


class Dfs(BaseModel):
    figura: str
    puntos_esperados: float | None = None
    xg: float | None = None
    xa: float | None = None
    tiros: float | None = None
    tiros_arco: float | None = None
    fuente: str = "manual"


class Carga(BaseModel):
    dias_descanso: float | None = None  # días desde su último partido hasta hoy
    partidos_14d: int = 0
    partidos_30d: int = 0


class Analisis(BaseModel):
    local: EquipoRef
    visita: EquipoRef
    h2h: Forma
    forma_local: Forma
    forma_visita: Forma
    forma_local_casa: Forma
    forma_visita_fuera: Forma
    carga_local: Carga
    carga_visita: Carga
    probabilidades: Probabilidades | None = None
    dfs_local: Dfs | None = None
    dfs_visita: Dfs | None = None
    advertencias: list[str] = []



class Seleccion(BaseModel):
    mercado: str
    seleccion: str
    prob_modelo: float
    prob_mercado: float   # consenso de las casas, sin margen
    diferencia: float     # prob_modelo - prob_mercado
    mejor_cuota: float
    casa: str | None = None
    ev: float             # valor esperado con la mejor cuota: prob_modelo * cuota - 1
    casas: int = 0
    posible_valor: bool = False


class Valor(BaseModel):
    disponible: bool
    evento: str | None = None
    comienza: str | None = None
    selecciones: list[Seleccion] = []
    creditos_restantes: int | None = None
    advertencias: list[str] = []

# =====================================================================
# 2. PROYECCIONES DFS (manuales). Cada equipo una sola vez.
# =====================================================================
#    (nombre, query, figura, pts, xG, tiros, tiros al arco, xA)
_DFS_RAW = [
    # Liga MX
    ("Club América", "Club America", "Henry Martín (DEL)", "18.5", "0.65", "3.4", "1.8", "0.30"),
    ("Cruz Azul", "Cruz Azul", "Ángel Sepúlveda (DEL)", "16.4", "0.58", "3.1", "1.5", "0.22"),
    ("Monterrey (Rayados)", "Monterrey", "Sergio Canales (MED)", "17.9", "0.42", "3.2", "1.4", "0.45"),
    ("Tigres UANL", "Tigres UANL", "A-P. Gignac (DEL)", "17.2", "0.62", "3.6", "1.7", "0.20"),
    ("Toluca", "Toluca", "Paulinho (DEL)", "18.1", "0.68", "3.5", "1.8", "0.22"),
    ("Pumas UNAM", "Pumas UNAM", "César Huerta (DEL)", "16.9", "0.45", "3.3", "1.4", "0.35"),
    ("Guadalajara (Chivas)", "Guadalajara Chivas", "Roberto Alvarado (MED)", "15.8", "0.35", "2.8", "1.2", "0.42"),
    ("Pachuca", "Pachuca", "Salomón Rondón (DEL)", "16.7", "0.60", "3.5", "1.6", "0.18"),
    # Premier League
    ("Arsenal", "Arsenal", "Bukayo Saka (DEL)", "19.2", "0.52", "3.2", "1.5", "0.48"),
    ("Chelsea", "Chelsea", "Cole Palmer (MED)", "21.0", "0.65", "3.6", "1.8", "0.50"),
    ("Liverpool", "Liverpool", "Mohamed Salah (DEL)", "20.4", "0.70", "3.8", "1.9", "0.42"),
    ("Manchester City", "Manchester City", "Erling Haaland (DEL)", "22.5", "0.95", "4.2", "2.4", "0.12"),
    ("Manchester United", "Manchester United", "Bruno Fernandes (MED)", "16.8", "0.35", "2.8", "1.1", "0.45"),
    ("Tottenham", "Tottenham", "Son Heung-Min (DEL)", "18.5", "0.48", "3.1", "1.5", "0.35"),
    # La Liga
    ("Real Madrid", "Real Madrid", "Vinicius Jr (DEL)", "20.8", "0.68", "3.7", "1.8", "0.44"),
    ("FC Barcelona", "Barcelona", "Lamine Yamal (DEL)", "19.5", "0.48", "3.3", "1.4", "0.52"),
    ("Atlético de Madrid", "Atletico Madrid", "Antoine Griezmann (DEL)", "17.2", "0.45", "2.8", "1.2", "0.38"),
    ("Athletic Club", "Athletic Club", "Iñaki Williams (DEL)", "14.5", "0.38", "2.5", "1.0", "0.22"),
    ("Real Sociedad", "Real Sociedad", "Takefusa Kubo (MED)", "13.8", "0.30", "2.2", "0.9", "0.28"),
    # Serie A
    ("Inter de Milán", "Inter", "Lautaro Martínez (DEL)", "18.2", "0.60", "3.5", "1.6", "0.15"),
    ("Juventus", "Juventus", "Dusan Vlahovic (DEL)", "16.5", "0.55", "3.1", "1.4", "0.10"),
    ("AC Milan", "AC Milan", "Christian Pulisic (MED)", "17.0", "0.45", "2.9", "1.2", "0.35"),
    ("Napoli", "Napoli", "Khvicha Kvaratskhelia (DEL)", "18.8", "0.50", "3.3", "1.5", "0.40"),
    ("AS Roma", "Roma", "Paulo Dybala (DEL)", "15.8", "0.42", "2.6", "1.1", "0.32"),
    # Bundesliga
    ("Bayern Munich", "Bayern Munich", "Harry Kane (DEL)", "22.5", "0.85", "4.1", "2.2", "0.25"),
    ("Bayer Leverkusen", "Bayer Leverkusen", "Florian Wirtz (MED)", "19.0", "0.40", "2.5", "1.1", "0.55"),
    ("Borussia Dortmund", "Borussia Dortmund", "Julian Brandt (MED)", "15.5", "0.25", "1.8", "0.8", "0.45"),
    ("RB Leipzig", "RB Leipzig", "Xavi Simons (MED)", "16.2", "0.32", "2.4", "1.0", "0.42"),
    # Ligue 1
    ("PSG", "Paris Saint Germain", "Bradley Barcola (DEL)", "19.5", "0.55", "3.2", "1.5", "0.30"),
    ("Mónaco", "Monaco", "Aleksandr Golovin (MED)", "14.8", "0.20", "1.9", "0.7", "0.40"),
    ("Marsella", "Marseille", "Mason Greenwood (DEL)", "17.2", "0.48", "2.8", "1.3", "0.25"),
    # MLS
    ("Inter Miami", "Inter Miami", "Lionel Messi (DEL)", "24.5", "0.75", "4.0", "2.0", "0.65"),
    ("LAFC", "Los Angeles FC", "Denis Bouanga (DEL)", "20.1", "0.68", "3.8", "1.7", "0.25"),
    ("LA Galaxy", "Los Angeles Galaxy", "Riqui Puig (MED)", "17.5", "0.30", "2.5", "1.0", "0.50"),
    ("Columbus Crew", "Columbus Crew", "Cucho Hernández (DEL)", "19.0", "0.62", "3.5", "1.6", "0.30"),
    # Brasil
    ("Flamengo", "Flamengo", "Pedro (DEL)", "17.8", "0.60", "3.2", "1.5", "0.15"),
    ("Palmeiras", "Palmeiras", "Raphael Veiga (MED)", "16.5", "0.35", "2.4", "1.0", "0.40"),
    ("Botafogo", "Botafogo", "Tiquinho Soares (DEL)", "15.2", "0.45", "2.7", "1.2", "0.20"),
    ("Fluminense", "Fluminense", "Germán Cano (DEL)", "17.5", "0.65", "3.4", "1.5", "0.10"),
    # Argentina
    ("River Plate", "River Plate", "Miguel Borja (DEL)", "18.0", "0.62", "3.3", "1.6", "0.10"),
    ("Boca Juniors", "Boca Juniors", "Edinson Cavani (DEL)", "16.5", "0.50", "2.9", "1.3", "0.15"),
    ("Racing Club", "Racing Club", "Adrián Martínez (DEL)", "15.8", "0.48", "2.8", "1.2", "0.12"),
    # Portugal
    ("Benfica", "Benfica", "Ángel Di María (MED)", "16.5", "0.35", "2.5", "1.0", "0.45"),
    ("FC Porto", "FC Porto", "Evanilson (DEL)", "15.8", "0.50", "2.8", "1.2", "0.15"),
    ("Sporting CP", "Sporting CP", "Viktor Gyökeres (DEL)", "21.0", "0.75", "4.0", "2.0", "0.25"),
    # Países Bajos
    ("PSV Eindhoven", "PSV Eindhoven", "Luuk de Jong (DEL)", "18.5", "0.65", "3.5", "1.5", "0.20"),
    ("Feyenoord", "Feyenoord", "Santiago Giménez (DEL)", "17.0", "0.58", "3.2", "1.4", "0.15"),
    ("Ajax", "Ajax", "Brian Brobbey (DEL)", "15.5", "0.50", "2.9", "1.3", "0.18"),
    # Selecciones
    ("Argentina", "Argentina", "Lionel Messi (DEL)", "22.0", "0.65", "3.5", "1.8", "0.55"),
    ("Francia", "France", "Kylian Mbappé (DEL)", "23.5", "0.85", "4.2", "2.1", "0.30"),
    ("Brasil", "Brazil", "Vinicius Jr (DEL)", "19.5", "0.60", "3.2", "1.5", "0.40"),
    ("Inglaterra", "England", "Harry Kane (DEL)", "20.0", "0.75", "3.6", "1.7", "0.20"),
    ("Uruguay", "Uruguay", "Darwin Núñez (DEL)", "18.5", "0.70", "3.8", "1.6", "0.15"),
    ("Colombia", "Colombia", "Luis Díaz (DEL)", "17.0", "0.45", "2.8", "1.2", "0.25"),
    ("España", "Spain", "Lamine Yamal (DEL)", "18.0", "0.40", "2.5", "1.1", "0.45"),
    ("Alemania", "Germany", "Jamal Musiala (MED)", "18.8", "0.45", "2.7", "1.2", "0.40"),
]

# Nombres de football-data.org que no coinciden con tus llaves (ya normalizados con clave())
_ALIAS_API = {
    "bayern munchen": "Bayern Munich",
    "04 bayer leverkusen": "Bayer Leverkusen",
    "internazionale milano": "Inter",
    "psv": "PSV Eindhoven",
}
_STOP = {"fc", "cf", "cd", "club", "de"}


def clave(texto: str) -> str:
    """Normaliza un nombre: sin acentos, sin puntos, sin 'FC/Club/de', orden de palabras irrelevante."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[.'’]", "", t)
    tokens = [x for x in re.sub(r"[^a-z0-9]+", " ", t).split() if x not in _STOP]
    return " ".join(sorted(tokens))


_INDICE_DFS: dict[str, dict] = {}
for _n, _q, _fig, _pts, _xg, _ti, _ta, _xa in _DFS_RAW:
    _cfg = {"figura": _fig, "pts": _pts, "xg": _xg, "tiros": _ti, "tiros_arco": _ta, "xa": _xa}
    for _alias in (_n, _q):
        _INDICE_DFS.setdefault(clave(_alias), _cfg)
for _k, _v in _ALIAS_API.items():
    if clave(_v) in _INDICE_DFS:
        _INDICE_DFS.setdefault(_k, _INDICE_DFS[clave(_v)])


def buscar_dfs(*nombres: str | None) -> Dfs | None:
    """Busca por nombre completo, nombre corto, etc. (el primero que coincida)."""
    for n in nombres:
        cfg = _INDICE_DFS.get(clave(n)) if n else None
        if cfg:
            def f(x):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return None
            return Dfs(figura=cfg["figura"], puntos_esperados=f(cfg["pts"]), xg=f(cfg["xg"]),
                       xa=f(cfg["xa"]), tiros=f(cfg["tiros"]), tiros_arco=f(cfg["tiros_arco"]))
    return None


# =====================================================================
# 4. CACHÉ + CLIENTE football-data.org
# =====================================================================
class TTLCache:
    """Caché en memoria con TTL; junta llamadas simultáneas idénticas en una sola."""

    def __init__(self, max_items: int = 2000):
        self._data: dict[Any, tuple[float, Any]] = {}
        self._locks: dict[Any, asyncio.Lock] = {}
        self._max = max_items

    def _podar(self) -> None:
        ahora = time.monotonic()
        for k in [k for k, (exp_, _) in self._data.items() if exp_ <= ahora]:
            self._data.pop(k, None)
            self._locks.pop(k, None)
        while len(self._data) > self._max:
            k = next(iter(self._data))
            self._data.pop(k, None)
            self._locks.pop(k, None)

    async def get_or_set(self, key: Any, ttl: int, factory: Callable[[], Awaitable[Any]]) -> Any:
        hit = self._data.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._data.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            valor = await factory()  # si falla, no se guarda nada
            self._data[key] = (time.monotonic() + ttl, valor)
            if len(self._data) > self._max:
                self._podar()
            return valor



class ApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class _Limitador:
    """Ventana deslizante de 60 s para respetar el límite del plan gratuito."""

    def __init__(self, max_por_min: int):
        self.max = max_por_min
        self.marcas: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def esperar(self) -> None:
        async with self.lock:
            while True:
                ahora = time.monotonic()
                while self.marcas and ahora - self.marcas[0] >= 60:
                    self.marcas.popleft()
                if len(self.marcas) < self.max:
                    self.marcas.append(ahora)
                    return
                espera = 60 - (ahora - self.marcas[0])
                if espera > MAX_ESPERA_SEG:
                    raise ApiError(429, "Límite de peticiones por minuto del plan gratuito. Intenta de nuevo en unos segundos.")
                await asyncio.sleep(espera + 0.1)


class FootballData:
    def __init__(self):
        self.cache = TTLCache()
        self._lim = _Limitador(RATE_POR_MIN)
        self._http = httpx.AsyncClient(base_url=API_BASE, headers={"X-Auth-Token": API_KEY or ""},
                                       timeout=httpx.Timeout(15.0))

    async def cerrar(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any], ttl: int) -> dict:
        if not API_KEY:
            raise ApiError(500, "Falta la variable de entorno FOOTBALL_DATA_KEY en el servidor.")
        key = (path, tuple(sorted(params.items())))

        async def fetch() -> dict:
            await self._lim.esperar()
            try:
                r = await self._http.get(path, params=params)
            except httpx.HTTPError as e:
                raise ApiError(502, f"No se pudo conectar con football-data.org: {e}") from e
            if r.status_code >= 400:
                try:
                    msg = r.json().get("message", "")
                except Exception:
                    msg = ""
                if r.status_code == 429:
                    raise ApiError(429, "Límite de peticiones por minuto de football-data.org. Intenta de nuevo en unos segundos.")
                if r.status_code in (401, 403):
                    raise ApiError(r.status_code, f"football-data.org: {msg or 'acceso denegado (revisa la key o tu plan)'}")
                if r.status_code == 404:
                    raise ApiError(404, f"football-data.org: {msg or 'no encontrado'}")
                raise ApiError(502, f"football-data.org respondió {r.status_code}: {msg}")
            return r.json()

        return await self.cache.get_or_set(key, ttl, fetch)

    async def equipos_liga(self, codigo: str) -> list[dict]:
        return (await self._get(f"/competitions/{codigo}/teams", {}, TTL_EQUIPOS)).get("teams", [])

    async def proximos(self, codigo: str, dias: int = 9) -> list[dict]:
        hoy = date.today()
        params = {"dateFrom": hoy.isoformat(), "dateTo": (hoy + timedelta(days=dias)).isoformat()}
        return (await self._get(f"/competitions/{codigo}/matches", params, TTL_CARTELERA)).get("matches", [])

    async def partidos_equipo(self, team_id: int) -> list[dict]:
        return (await self._get(f"/teams/{team_id}/matches", {"status": "FINISHED"}, TTL_PARTIDOS)).get("matches", [])

    async def equipo(self, team_id: int) -> dict:
        return await self._get(f"/teams/{team_id}", {}, TTL_EQUIPOS)

    async def h2h(self, partido_id: int) -> list[dict]:
        return (await self._get(f"/matches/{partido_id}/head2head", {"limit": 10}, TTL_H2H)).get("matches", [])


class OddsApi:
    """Cliente de The Odds API. Todo con caché de 12 h para cuidar los créditos."""

    def __init__(self):
        self.cache = TTLCache()
        self.creditos: int | None = None
        self._http = httpx.AsyncClient(base_url=ODDS_BASE, timeout=httpx.Timeout(15.0))

    async def cerrar(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any], ttl: int) -> Any:
        if not ODDS_KEY:
            raise ApiError(500, "Falta la variable de entorno ODDS_API_KEY en el servidor.")
        key = (path, tuple(sorted(params.items())))

        async def fetch() -> Any:
            try:
                r = await self._http.get(path, params={**params, "apiKey": ODDS_KEY})
            except httpx.HTTPError as e:
                raise ApiError(502, f"No se pudo conectar con The Odds API: {e}") from e
            restantes = r.headers.get("x-requests-remaining")
            if restantes is not None:
                try:
                    self.creditos = int(float(restantes))
                except ValueError:
                    pass
            if r.status_code >= 400:
                try:
                    msg = r.json().get("message", "")
                except Exception:
                    msg = ""
                if r.status_code == 401:
                    raise ApiError(401, f"The Odds API: key inválida o créditos agotados. {msg}")
                if r.status_code == 429:
                    raise ApiError(429, "The Odds API: demasiadas peticiones. Intenta en unos segundos.")
                if r.status_code in (404, 422):
                    raise ApiError(404, f"The Odds API: no se encontró el recurso. {msg}")
                raise ApiError(502, f"The Odds API respondió {r.status_code}: {msg}")
            return r.json()

        return await self.cache.get_or_set(key, ttl, fetch)

    async def eventos_liga(self, sport_key: str) -> list[dict]:
        params = {"regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal", "dateFormat": "iso"}
        return await self._get(f"/sports/{sport_key}/odds", params, TTL_CUOTAS)

    async def btts_evento(self, sport_key: str, evento_id: str) -> dict:
        params = {"regions": "eu", "markets": "btts", "oddsFormat": "decimal", "dateFormat": "iso"}
        return await self._get(f"/sports/{sport_key}/events/{evento_id}/odds", params, TTL_CUOTAS)


# Nombres que las casas escriben distinto a football-data.org (ya normalizados con clave())
_ALIAS_CUOTAS = {
    clave("Athletic Bilbao"): clave("Athletic Club"),
    clave("Sporting Lisbon"): clave("Sporting Clube de Portugal"),
}


def _mismo_equipo(a: str, b: str) -> bool:
    ca, cb = clave(a), clave(b)
    ca, cb = _ALIAS_CUOTAS.get(ca, ca), _ALIAS_CUOTAS.get(cb, cb)
    if ca == cb:
        return True
    ta, tb = ca.split(), cb.split()
    corto, largo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # "Inter Milan" ~ "Internazionale Milano": cada palabra corta es prefijo de una larga
    if corto and all(any(x.startswith(c) for x in largo) for c in corto):
        return True
    return SequenceMatcher(None, ca, cb).ratio() >= 0.85


def buscar_evento(eventos: list[dict], local: str, visita: str) -> dict | None:
    for ev in eventos:
        if _mismo_equipo(ev.get("home_team", ""), local) and _mismo_equipo(ev.get("away_team", ""), visita):
            return ev
    return None


def _consenso(bookmakers: list[dict], mercado: str, etiquetas: dict[str, str],
              punto: float | None = None) -> dict[str, dict]:
    """Probabilidad de mercado sin margen (promedio entre casas) y mejor cuota por selección."""
    acum: dict[str, list[float]] = defaultdict(list)
    mejores: dict[str, tuple[float, str | None]] = {}
    for b in bookmakers:
        for mk in b.get("markets", []):
            if mk.get("key") != mercado:
                continue
            outs = [o for o in mk.get("outcomes", [])
                    if o.get("name") in etiquetas and o.get("price")
                    and (punto is None or o.get("point") == punto)]
            if len(outs) != len(etiquetas):
                continue
            total = sum(1 / o["price"] for o in outs)  # quita el margen de la casa
            for o in outs:
                k = etiquetas[o["name"]]
                acum[k].append((1 / o["price"]) / total)
                if k not in mejores or o["price"] > mejores[k][0]:
                    mejores[k] = (o["price"], b.get("title"))
    return {k: {"prob_mercado": sum(v) / len(v), "mejor_cuota": mejores[k][0],
                "casa": mejores[k][1], "casas": len(v)} for k, v in acum.items()}


def _armar(mercado: str, modelo: dict[str, tuple[str, float]], consenso: dict[str, dict]) -> list[Seleccion]:
    res = []
    for k, (nombre, prob) in modelo.items():
        c = consenso.get(k)
        if not c:
            continue
        ev = prob * c["mejor_cuota"] - 1
        dif = prob - c["prob_mercado"]
        res.append(Seleccion(mercado=mercado, seleccion=nombre, prob_modelo=round(prob, 3),
                             prob_mercado=round(c["prob_mercado"], 3), diferencia=round(dif, 3),
                             mejor_cuota=c["mejor_cuota"], casa=c["casa"], ev=round(ev, 3), casas=c["casas"],
                             posible_valor=ev >= UMBRAL_EV and dif >= UMBRAL_DIF))
    return res


def _norm(m: dict) -> dict:
    """Convierte un partido de football-data.org al formato interno que usan las estadísticas."""
    ft = (m.get("score") or {}).get("fullTime") or {}
    try:
        ts = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        ts = 0.0
    estado = "FT" if m.get("status") == "FINISHED" else m.get("status", "")
    return {
        "fixture": {"id": m["id"], "timestamp": ts, "status": {"short": estado}},
        "teams": {"home": {"id": m["homeTeam"]["id"]}, "away": {"id": m["awayTeam"]["id"]}},
        "goals": {"home": ft.get("home"), "away": ft.get("away")},
    }


def _equipo_en(partidos: list[dict], team_id: int) -> dict | None:
    for m in partidos:
        for lado in ("homeTeam", "awayTeam"):
            if m.get(lado, {}).get("id") == team_id:
                return m[lado]
    return None


# =====================================================================
# 5. ESTADÍSTICAS Y MODELO
# =====================================================================
TERMINADOS = {"FT", "AET", "PEN"}
PRIOR_GOLES = 1.35
K_SHRINK = 5
FACTOR_LOCAL, FACTOR_VISITA = 1.10, 0.92


def _terminado(f: dict) -> bool:
    return (f["fixture"]["status"]["short"] in TERMINADOS
            and f["goals"]["home"] is not None and f["goals"]["away"] is not None)


def resumen_forma(fixtures: list[dict], team_id: int, n_max: int = 10) -> Forma:
    jugados = sorted((f for f in fixtures if _terminado(f)),
                     key=lambda f: f["fixture"]["timestamp"], reverse=True)[:n_max]
    n = len(jugados)
    if n == 0:
        return Forma()
    gf = gc = g = e = p = btts = o15 = o25 = cs = fts = o25_5 = btts_5 = 0
    racha = []
    for idx, f in enumerate(jugados):
        es_local = f["teams"]["home"]["id"] == team_id
        a = f["goals"]["home" if es_local else "away"]
        b = f["goals"]["away" if es_local else "home"]
        gf += a
        gc += b
        if a > b:
            g += 1
            racha.append("G")
        elif a == b:
            e += 1
            racha.append("E")
        else:
            p += 1
            racha.append("P")
        ambos = a > 0 and b > 0
        btts += ambos
        o15 += a + b > 1.5
        o25 += a + b > 2.5
        cs += b == 0
        fts += a == 0
        if idx < 5:  # los 5 más recientes
            o25_5 += a + b > 2.5
            btts_5 += ambos
    pc = lambda x: round(100 * x / n, 1)  # noqa: E731
    return Forma(partidos=n, ganados=g, empatados=e, perdidos=p,
                 gf_prom=round(gf / n, 2), gc_prom=round(gc / n, 2),
                 goles_totales_prom=round((gf + gc) / n, 2),
                 btts_pct=pc(btts), over15_pct=pc(o15), over25_pct=pc(o25),
                 porteria_cero_pct=pc(cs), sin_anotar_pct=pc(fts),
                 over25_ult5=o25_5, btts_ult5=btts_5, racha="".join(racha[:5]))


def calcular_carga(fixtures: list[dict], ahora: float | None = None) -> Carga:
    """Días de descanso y partidos jugados en 14/30 días (solo competiciones del plan)."""
    ahora = ahora or time.time()
    ts = sorted((f["fixture"]["timestamp"] for f in fixtures
                 if _terminado(f) and 0 < f["fixture"]["timestamp"] <= ahora), reverse=True)
    if not ts:
        return Carga()
    dia = 86400
    return Carga(dias_descanso=round((ahora - ts[0]) / dia, 1),
                 partidos_14d=sum(1 for t in ts if ahora - t <= 14 * dia),
                 partidos_30d=sum(1 for t in ts if ahora - t <= 30 * dia))


def _pois(k: int, lam: float) -> float:
    return exp(-lam) * lam**k / factorial(k)


def _ajustar(prom: float | None, n: int) -> float:
    if prom is None:
        return PRIOR_GOLES
    return (prom * n + PRIOR_GOLES * K_SHRINK) / (n + K_SHRINK)


MIN_PARTIDOS_SEDE = 4  # mínimo de partidos en casa/de visita para usar ese rendimiento


def _ataque_defensa(general: Forma, sede: Forma | None) -> tuple[float, float, bool]:
    """Goles a favor/en contra esperados; mezcla 50/50 con el rendimiento por sede si hay muestra."""
    gf = _ajustar(general.gf_prom, general.partidos)
    gc = _ajustar(general.gc_prom, general.partidos)
    usa_sede = sede is not None and sede.partidos >= MIN_PARTIDOS_SEDE
    if usa_sede:
        gf = 0.5 * gf + 0.5 * _ajustar(sede.gf_prom, sede.partidos)
        gc = 0.5 * gc + 0.5 * _ajustar(sede.gc_prom, sede.partidos)
    return gf, gc, usa_sede


def calcular_probabilidades(fl: Forma, fv: Forma, fl_casa: Forma | None = None,
                            fv_fuera: Forma | None = None, max_g: int = 10) -> Probabilidades:
    gf_l, gc_l, sede_l = _ataque_defensa(fl, fl_casa)
    gf_v, gc_v, sede_v = _ataque_defensa(fv, fv_fuera)
    # si ya se usó el rendimiento por sede, la ventaja de localía va incluida; si no, factor fijo
    lam_l = (gf_l + gc_v) / 2 * (1.0 if sede_l else FACTOR_LOCAL)
    lam_v = (gf_v + gc_l) / 2 * (1.0 if sede_v else FACTOR_VISITA)
    celdas = [(i, j, _pois(i, lam_l) * _pois(j, lam_v)) for i in range(max_g) for j in range(max_g)]
    total = sum(c[2] for c in celdas)

    def s(cond) -> float:
        return round(sum(p for i, j, p in celdas if cond(i, j)) / total, 3)

    top = sorted(celdas, key=lambda c: c[2], reverse=True)[:3]
    return Probabilidades(
        local=s(lambda i, j: i > j), empate=s(lambda i, j: i == j), visita=s(lambda i, j: i < j),
        over15=s(lambda i, j: i + j > 1), over25=s(lambda i, j: i + j > 2),
        over35=s(lambda i, j: i + j > 3), btts=s(lambda i, j: i > 0 and j > 0),
        goles_esperados_local=round(lam_l, 2), goles_esperados_visita=round(lam_v, 2),
        marcadores_probables=[Marcador(marcador=f"{i}-{j}", prob=round(p / total, 3)) for i, j, p in top],
    )



# =====================================================================
# 6. APP Y RUTAS
# =====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.api = FootballData()
    app.state.odds = OddsApi()
    if not API_KEY:
        logging.warning("FOOTBALL_DATA_KEY no está configurada")
    yield
    await app.state.api.cerrar()
    await app.state.odds.cerrar()


app = FastAPI(title="Panel Estadístico Draftea Pro", version="3.0", lifespan=lifespan)

if CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET"], allow_headers=["*"])


def get_api(request: Request) -> FootballData:
    return request.app.state.api


Api = Annotated[FootballData, Depends(get_api)]


def get_odds(request: Request) -> OddsApi:
    return request.app.state.odds


Odds = Annotated[OddsApi, Depends(get_odds)]


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _equipo(t: dict) -> Equipo:
    nombre = t.get("name") or t.get("shortName") or "?"
    return Equipo(id=t["id"], nombre=nombre, logo=t.get("crest"),
                  tiene_dfs=buscar_dfs(t.get("name"), t.get("shortName")) is not None)


@app.get("/api/health")
async def health():
    return {"ok": True, "api_key_configurada": bool(API_KEY), "odds_key_configurada": bool(ODDS_KEY)}


@app.get("/api/ligas")
async def ligas():
    return [{"id": c, "nombre": n} for c, n in LIGAS.items()]


@app.get("/api/ligas/{liga}/equipos", response_model=list[Equipo])
async def equipos(liga: str, api: Api):
    if liga not in LIGAS:
        raise HTTPException(404, "Liga no soportada")
    return [_equipo(t) for t in await api.equipos_liga(liga)]


@app.get("/api/ligas/{liga}/proximos", response_model=list[Partido])
async def proximos(liga: str, api: Api, n: Annotated[int, Query(ge=1, le=30)] = 10):
    if liga not in LIGAS:
        raise HTTPException(404, "Liga no soportada")
    pendientes = [m for m in await api.proximos(liga) if m.get("status") in ("SCHEDULED", "TIMED")]
    pendientes.sort(key=lambda m: m["utcDate"])
    return [Partido(fixture_id=m["id"], fecha=m["utcDate"],
                    ronda=f"Jornada {m['matchday']}" if m.get("matchday") else None,
                    local=_equipo(m["homeTeam"]), visita=_equipo(m["awayTeam"]))
            for m in pendientes[:n]]


async def construir_analisis(api: FootballData, local_id: int, visita_id: int, partido_id: int | None) -> Analisis:
    if local_id == visita_id:
        raise HTTPException(422, "Elige dos equipos diferentes")

    ms_l, ms_v = await asyncio.gather(api.partidos_equipo(local_id), api.partidos_equipo(visita_id))
    t_l = _equipo_en(ms_l, local_id)
    if t_l is None:
        t_l = await api.equipo(local_id)
    t_v = _equipo_en(ms_v, visita_id)
    if t_v is None:
        t_v = await api.equipo(visita_id)

    ult_l, ult_v = [_norm(m) for m in ms_l], [_norm(m) for m in ms_v]
    forma_l, forma_v = resumen_forma(ult_l, local_id), resumen_forma(ult_v, visita_id)
    casa_l = resumen_forma([p for p in ult_l if p["teams"]["home"]["id"] == local_id], local_id)
    fuera_v = resumen_forma([p for p in ult_v if p["teams"]["away"]["id"] == visita_id], visita_id)
    carga_l, carga_v = calcular_carga(ult_l), calcular_carga(ult_v)

    avisos: list[str] = []
    if partido_id:
        try:
            h2h_partidos = [_norm(m) for m in await api.h2h(partido_id)]
        except ApiError as e:
            h2h_partidos = []
            avisos.append(f"No se pudo obtener el H2H: {e.detail}")
    else:
        h2h_partidos = [p for p in ult_l if {p["teams"]["home"]["id"], p["teams"]["away"]["id"]} == {local_id, visita_id}]
        avisos.append("H2H completo solo disponible al elegir un partido de la cartelera; aquí se usa solo la temporada actual.")
    h2h_res = resumen_forma(h2h_partidos, local_id)

    dfs_l = buscar_dfs(t_l.get("name"), t_l.get("shortName"))
    dfs_v = buscar_dfs(t_v.get("name"), t_v.get("shortName"))

    if h2h_res.partidos < 3:
        avisos.append(f"H2H con solo {h2h_res.partidos} partido(s): no es una muestra confiable.")
    if min(forma_l.partidos, forma_v.partidos) < 5:
        avisos.append("Forma reciente con menos de 5 partidos en algún equipo; las probabilidades se acercan a la media.")
    if not dfs_l or not dfs_v:
        avisos.append("Sin proyección DFS cargada para alguno de los equipos.")
    if dfs_l or dfs_v:
        avisos.append("Las proyecciones DFS son valores cargados a mano, no calculados en vivo.")
    avisos.append("Este proveedor no incluye tiros, córners ni faltas. Las probabilidades son un modelo Poisson simple (goles recientes), sin lesiones ni alineaciones.")

    nom = lambda t: t.get("name") or t.get("shortName") or "?"  # noqa: E731
    for nombre, c in ((nom(t_l), carga_l), (nom(t_v), carga_v)):
        if c.dias_descanso is not None and c.dias_descanso <= 3:
            avisos.append(f"{nombre} jugó hace {c.dias_descanso} días: poca recuperación, posible rotación.")
        if c.partidos_14d >= 4:
            avisos.append(f"{nombre} acumula {c.partidos_14d} partidos en 14 días.")
    avisos.append("Descanso y carga cuentan solo partidos de competiciones incluidas en el plan (no copas nacionales ni amistosos) y se miden a hoy.")
    return Analisis(
        local=EquipoRef(id=local_id, nombre=nom(t_l), logo=t_l.get("crest")),
        visita=EquipoRef(id=visita_id, nombre=nom(t_v), logo=t_v.get("crest")),
        h2h=h2h_res, forma_local=forma_l, forma_visita=forma_v,
        forma_local_casa=casa_l, forma_visita_fuera=fuera_v,
        carga_local=carga_l, carga_visita=carga_v,
        probabilidades=calcular_probabilidades(forma_l, forma_v, casa_l, fuera_v),
        dfs_local=dfs_l, dfs_visita=dfs_v, advertencias=avisos)


@app.get("/api/analisis", response_model=Analisis)
async def analisis(api: Api, local_id: int, visita_id: int,
                   partido_id: Annotated[int | None, Query(description="ID de un partido de la cartelera (habilita el H2H)")] = None):
    return await construir_analisis(api, local_id, visita_id, partido_id)


@app.get("/api/valor", response_model=Valor)
async def valor(api: Api, odds: Odds, liga: str, local_id: int, visita_id: int,
                partido_id: int | None = None):
    sport = SPORT_KEYS.get(liga)
    if not sport:
        raise HTTPException(422, "Cuotas disponibles solo para PL, PD, BL1, CL y SA")
    an = await construir_analisis(api, local_id, visita_id, partido_id)  # sale de caché si ya se analizó
    p = an.probabilidades
    eventos = await odds.eventos_liga(sport)
    ev = buscar_evento(eventos, an.local.nombre, an.visita.nombre)
    if not ev or not p:
        return Valor(disponible=False, creditos_restantes=odds.creditos,
                     advertencias=["No hay cuotas publicadas para este partido (aún no abren o los nombres no coinciden)."])

    avisos = ["El modelo es simple y el mercado suele ser más preciso: una diferencia grande suele indicar un error del modelo, no una apuesta segura. Úsalo como filtro, no como señal."]
    sels = _armar("Resultado 1X2",
                  {"local": (an.local.nombre, p.local), "empate": ("Empate", p.empate), "visita": (an.visita.nombre, p.visita)},
                  _consenso(ev.get("bookmakers", []), "h2h",
                            {ev["home_team"]: "local", ev["away_team"]: "visita", "Draw": "empate"}))
    sels += _armar("Total de goles 2.5",
                   {"over25": ("Más de 2.5", p.over25), "under25": ("Menos de 2.5", 1 - p.over25)},
                   _consenso(ev.get("bookmakers", []), "totals", {"Over": "over25", "Under": "under25"}, punto=2.5))
    try:
        btts = await odds.btts_evento(sport, ev["id"])
        sels += _armar("Ambos anotan",
                       {"btts_si": ("Sí", p.btts), "btts_no": ("No", 1 - p.btts)},
                       _consenso(btts.get("bookmakers", []), "btts", {"Yes": "btts_si", "No": "btts_no"}))
    except ApiError as e:
        avisos.append(f"No se pudo obtener 'ambos anotan': {e.detail}")
    avisos.append("Mejor cuota = la más alta entre las casas consultadas (región EU); la probabilidad de mercado es el promedio sin margen.")

    return Valor(disponible=True, evento=f"{ev['home_team']} vs {ev['away_team']}", comienza=ev.get("commence_time"),
                 selecciones=sels, creditos_restantes=odds.creditos, advertencias=avisos)


# =====================================================================
# 7. FRONT (HTML plano, sin f-string)
# =====================================================================
PAGINA = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel Estadístico Draftea Pro</title>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0b1329;color:#f8fafc;margin:0;padding:20px}
.container{max-width:720px;margin:0 auto}
label{display:block;font-size:11px;color:#94a3b8;text-transform:uppercase;margin-bottom:5px;font-weight:bold}
select{background:#16203a;border:1px solid #334155;color:#fff;padding:10px 12px;border-radius:6px;font-size:14px;width:100%}
.row{display:flex;gap:10px;margin:12px 0}.row>div{flex:1;min-width:0}
.btn{background:#00ff87;color:#052e16;font-weight:bold;border:none;padding:12px;border-radius:6px;cursor:pointer;font-size:15px;width:100%}
.btn:hover{background:#34d399}.btn:disabled{opacity:.6;cursor:wait}
.check{display:flex;align-items:center;gap:8px;font-size:12px;color:#94a3b8;margin:8px 0 12px}
.carousel{display:flex;gap:12px;overflow-x:auto;padding-bottom:12px;margin-bottom:16px}
.match-card{background:#16203a;border:1px solid #233154;padding:12px;border-radius:10px;min-width:170px;cursor:pointer;text-align:center}
.match-card:hover{border-color:#00ff87}
.muted{color:#94a3b8;font-size:12px}.err{color:#ef4444;font-size:13px}
.card{background:#16203a;border:1px solid #233154;border-radius:12px;padding:16px;margin-top:16px}
.head{display:flex;justify-content:space-between;align-items:center}
.side{display:flex;flex-direction:column;align-items:center;width:40%;text-align:center;font-weight:bold;font-size:15px}
.side img{width:60px;height:60px;object-fit:contain;margin-bottom:6px}
.vs{border:1px solid #38bdf8;color:#38bdf8;font-weight:bold;padding:4px 10px;border-radius:20px;font-size:12px}
h3{font-size:12px;color:#00ff87;text-transform:uppercase;letter-spacing:.5px;margin:0 0 10px}
.bar{display:flex;height:26px;border-radius:6px;overflow:hidden;font-size:12px;font-weight:bold}
.bar div{display:flex;align-items:center;justify-content:center;min-width:34px}
.b1{background:#0284c7}.b2{background:#64748b}.b3{background:#e11d48}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:7px 4px;border-top:1px solid #1e293b}td:first-child{text-align:left;font-weight:bold;width:25%}
td:last-child{text-align:right;font-weight:bold;width:25%}td:nth-child(2){text-align:center;color:#38bdf8;font-size:12px}
.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{background:#0b1329;border:1px solid #233154;border-radius:20px;padding:4px 10px;font-size:12px}
.chip b{color:#38bdf8}
.dfs{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.pl{background:#0b1329;border-left:3px solid #00ff87;padding:10px 12px;border-radius:6px;font-size:12px;color:#94a3b8}
.pl .n{font-size:14px;font-weight:bold;color:#f8fafc;margin:3px 0}.pl .p{color:#00ff87;font-weight:bold;font-size:13px}
.pl b{color:#38bdf8}
.warn{font-size:12px;color:#fbbf24;margin:4px 0}
.racha span{display:inline-block;width:20px;height:20px;line-height:20px;text-align:center;border-radius:4px;font-size:11px;margin-right:3px}
.G{background:#16a34a}.E{background:#ca8a04}.P{background:#dc2626}
.cuotas{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.cuotas input{width:100%;background:#0b1329;border:1px solid #334155;color:#fff;padding:8px;border-radius:6px;font-size:14px}
.tv{margin-top:6px}.tv th{font-size:11px;color:#94a3b8;text-align:right;padding:4px}.tv th:first-child{text-align:left}
.tv td{padding:6px 4px;border-top:1px solid #1e293b;text-align:right;font-weight:normal;width:auto;color:#f8fafc}
.tv td:first-child{text-align:left;font-weight:bold;width:auto}.tv td:nth-child(2){color:#f8fafc;font-size:13px}.tv td:last-child{width:auto;font-weight:bold}
.tv tr.val td{color:#00ff87;background:#0b1f1a}
@media(max-width:520px){.dfs{grid-template-columns:1fr}}
</style></head><body><div class="container">
<h2>Panel Analítico Draftea ⚽</h2>
<label>Liga</label><select id="liga"></select>
<label style="margin-top:16px;color:#00ff87">Próximos partidos (clic para analizar)</label>
<div id="cartelera" class="carousel"></div>
<div class="row"><div><label>Local</label><select id="local"></select></div>
<div><label>Visitante</label><select id="visita"></select></div></div>
<button class="btn" id="btn">Analizar enfrentamiento</button>
<div id="resultado"></div>
</div>
<script>
const $ = id => document.getElementById(id);
let partidos = [];
let oddsOk = false;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nd = x => (x === null || x === undefined) ? 'N/D' : x;
const pc = x => (x === null || x === undefined) ? 'N/D' : x + '%';
const fr = x => Math.round(x * 100) + '%';
function aDecimal(txt) {
  const t = String(txt || '').trim().replace(',', '.');
  if (!t) return null;
  const n = parseFloat(t);
  if (isNaN(n)) return null;
  if (/^[+-]/.test(t) && Math.abs(n) >= 100) return n > 0 ? 1 + n / 100 : 1 + 100 / Math.abs(n); // americano
  return n > 1 ? n : null;
}
function valorManual(d, c) {
  const p = d.probabilidades;
  const mercados = [
    ['Resultado 1X2', [[d.local.nombre, p.local, c.l], ['Empate', p.empate, c.e], [d.visita.nombre, p.visita, c.v]]],
    ['Total de goles 2.5', [['Más de 2.5', p.over25, c.o], ['Menos de 2.5', 1 - p.over25, c.u]]],
    ['Ambos anotan', [['Sí', p.btts, c.bs], ['No', 1 - p.btts, c.bn]]],
  ];
  let h = '', hay = false;
  for (const [nombre, sels] of mercados) {
    const filas = sels.filter(s => s[2]);
    if (!filas.length) continue;
    hay = true;
    const completo = filas.length === sels.length;
    const total = completo ? sels.reduce((a, s) => a + 1 / s[2], 0) : 1; // con todas las cuotas se quita el margen
    h += `<table class="tv"><tr><th>${esc(nombre)}${completo ? '' : ' (con margen)'}</th><th>Modelo</th><th>Mercado</th><th>Cuota</th><th>EV</th></tr>` +
      filas.map(([n, prob, cuota]) => {
        const pm = (1 / cuota) / total, ev = prob * cuota - 1, val = ev >= 0.05 && prob - pm >= 0.03;
        return `<tr class="${val ? 'val' : ''}"><td>${esc(n)}</td><td>${fr(prob)}</td><td>${fr(pm)}</td><td>${cuota.toFixed(2)}</td><td>${(ev * 100).toFixed(1)}%</td></tr>`;
      }).join('') + '</table><br>';
  }
  if (!hay) return '<p class="muted">Escribe al menos una cuota.</p>';
  return h + '<div class="warn">⚠ El modelo es simple (sin lesiones ni alineaciones) y el mercado suele ser más preciso: un EV alto suele indicar error del modelo. Úsalo como filtro.</div>';
}
function pintarValor(v) {
  if (!v.disponible) return `<p class="muted">${esc(v.advertencias.join(' '))}</p>`;
  const grupos = {};
  v.selecciones.forEach(s => (grupos[s.mercado] = grupos[s.mercado] || []).push(s));
  let h = `<div class="muted" style="margin:8px 0">${esc(v.evento)} · créditos restantes: ${nd(v.creditos_restantes)}</div>`;
  for (const [m, filas] of Object.entries(grupos)) {
    h += `<table class="tv"><tr><th>${esc(m)}</th><th>Modelo</th><th>Mercado</th><th>Mejor cuota</th><th>EV</th></tr>` +
      filas.map(s => `<tr class="${s.posible_valor ? 'val' : ''}"><td>${esc(s.seleccion)}</td><td>${fr(s.prob_modelo)}</td><td>${fr(s.prob_mercado)}</td>
        <td>${s.mejor_cuota.toFixed(2)}<br><span class="muted">${esc(s.casa)}</span></td><td>${(s.ev * 100).toFixed(1)}%</td></tr>`).join('') + '</table><br>';
  }
  return h + v.advertencias.map(w => `<div class="warn">⚠ ${esc(w)}</div>`).join('');
}
const dias = x => (x === null || x === undefined) ? 'N/D' : x + ' d';
const de5 = f => f.partidos ? `${f.over25_ult5}/${Math.min(5, f.partidos)}` : 'N/D';

async function api(url) {
  const r = await fetch(url);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ('Error ' + r.status));
  return d;
}
function opciones(sel, lista, idx) {
  sel.innerHTML = lista.map(e => `<option value="${esc(e.id)}">${esc(e.nombre)}</option>`).join('');
  if (idx !== undefined && sel.options[idx]) sel.selectedIndex = idx;
}

async function cargarLigas() {
  const ligas = await api('/api/ligas');
  $('liga').innerHTML = ligas.map(l => `<option value="${l.id}">${esc(l.nombre)}</option>`).join('');
  await cambioLiga();
}
async function cambioLiga() {
  const id = $('liga').value;
  $('cartelera').innerHTML = '<span class="muted">Cargando…</span>';
  $('local').innerHTML = $('visita').innerHTML = '';
  partidos = [];
  const [eq, pr] = await Promise.allSettled([api(`/api/ligas/${id}/equipos`), api(`/api/ligas/${id}/proximos?n=10`)]);
  if (eq.status === 'fulfilled') {
    const lista = eq.value.sort((a, b) => a.nombre.localeCompare(b.nombre));
    opciones($('local'), lista, 0); opciones($('visita'), lista, 1);
  }
  const c = $('cartelera');
  if (pr.status === 'rejected') { c.innerHTML = `<span class="err">${esc(pr.reason.message)}</span>`; return; }
  if (!pr.value.length) { c.innerHTML = '<span class="muted">No hay partidos próximos.</span>'; return; }
  c.innerHTML = '';
  partidos = pr.value;
  pr.value.forEach(p => {
    const d = document.createElement('div');
    d.className = 'match-card';
    d.innerHTML = `<div class="muted" style="color:#38bdf8;font-weight:bold">${esc(new Date(p.fecha).toLocaleString('es-MX', {dateStyle:'short', timeStyle:'short'}))}</div>
      <div style="display:flex;justify-content:center;align-items:center;gap:8px;margin:8px 0">
        <img src="${esc(p.local.logo)}" width="28"><span class="muted">VS</span><img src="${esc(p.visita.logo)}" width="28"></div>
      <div style="font-size:11px;font-weight:bold;line-height:1.4">${esc(p.local.nombre)}<br>${esc(p.visita.nombre)}</div>`;
    d.addEventListener('click', () => {
      $('local').value = p.local.id; $('visita').value = p.visita.id;
      analizar(p.local.id, p.visita.id, p.fixture_id);
    });
    c.appendChild(d);
  });
}

const filas = rows => '<table>' + rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('') + '</table>';
const racha = r => '<span class="racha">' + [...(r || '')].map(x => `<span class="${x}">${x}</span>`).join('') + '</span>';
const dfsCard = (rol, d) => !d ? `<div class="pl">${rol}<div class="n">Sin proyección cargada</div></div>` :
  `<div class="pl">${rol}<div class="n">${esc(d.figura)}</div><div class="p">${nd(d.puntos_esperados)} pts esperados</div>
   <div style="margin-top:6px">xG: <b>${nd(d.xg)}</b> · xA: <b>${nd(d.xa)}</b><br>Tiros: <b>${nd(d.tiros)}</b> · Al arco: <b>${nd(d.tiros_arco)}</b></div></div>`;

async function analizar(lid, vid, mid) {
  const local = lid || $('local').value, visita = vid || $('visita').value, out = $('resultado');
  const pm = partidos.find(p => String(p.local.id) === String(local) && String(p.visita.id) === String(visita));
  const partidoId = mid || (pm ? pm.fixture_id : '');
  if (!local || !visita) { out.innerHTML = '<p class="err">Elige los equipos.</p>'; return; }
  if (local === visita) { out.innerHTML = '<p class="err">Elige dos equipos diferentes.</p>'; return; }
  $('btn').disabled = true;
  out.innerHTML = '<p class="muted">Analizando…</p>';
  try {
    const d = await api(`/api/analisis?local_id=${local}&visita_id=${visita}` + (partidoId ? `&partido_id=${partidoId}` : ''));
    const p = d.probabilidades, fl = d.forma_local, fv = d.forma_visita, h = d.h2h;
    let html = `<div class="card"><div class="head">
      <div class="side"><img src="${esc(d.local.logo)}">${esc(d.local.nombre)}</div><div class="vs">VS</div>
      <div class="side"><img src="${esc(d.visita.logo)}">${esc(d.visita.nombre)}</div></div></div>`;
    if (p) {
      html += `<div class="card"><h3>Probabilidades (modelo Poisson)</h3>
        <div class="bar"><div class="b1" style="flex:${p.local}">${fr(p.local)}</div><div class="b2" style="flex:${p.empate}">${fr(p.empate)}</div><div class="b3" style="flex:${p.visita}">${fr(p.visita)}</div></div>
        <div class="muted" style="display:flex;justify-content:space-between;margin:4px 0 12px"><span>Local</span><span>Empate</span><span>Visitante</span></div>
        <div class="chips"><span class="chip">Over 1.5 <b>${fr(p.over15)}</b></span><span class="chip">Over 2.5 <b>${fr(p.over25)}</b></span>
        <span class="chip">Over 3.5 <b>${fr(p.over35)}</b></span><span class="chip">Ambos anotan <b>${fr(p.btts)}</b></span>
        <span class="chip">Goles esp. <b>${p.goles_esperados_local} – ${p.goles_esperados_visita}</b></span></div>
        <div class="muted" style="margin-top:10px">Marcadores probables: ${p.marcadores_probables.map(m => `<b style="color:#38bdf8">${esc(m.marcador)}</b> (${fr(m.prob)})`).join(' · ')}</div></div>`;
    }
    html += `<div class="card"><h3>Forma reciente (últimos ${Math.max(fl.partidos, fv.partidos)})</h3>` + filas([
      [nd(fl.partidos), 'Partidos', nd(fv.partidos)],
      [`${fl.ganados}-${fl.empatados}-${fl.perdidos}`, 'G-E-P', `${fv.ganados}-${fv.empatados}-${fv.perdidos}`],
      [nd(fl.gf_prom), 'Goles a favor', nd(fv.gf_prom)], [nd(fl.gc_prom), 'Goles en contra', nd(fv.gc_prom)],
      [nd(fl.goles_totales_prom), 'Goles totales por partido', nd(fv.goles_totales_prom)],
      [pc(fl.over25_pct), 'Over 2.5', pc(fv.over25_pct)], [de5(fl), 'Over 2.5 (últimos 5)', de5(fv)],
      [pc(fl.btts_pct), 'Ambos anotan', pc(fv.btts_pct)],
      [pc(fl.porteria_cero_pct), 'Portería en cero', pc(fv.porteria_cero_pct)],
      [pc(fl.sin_anotar_pct), 'Sin anotar', pc(fv.sin_anotar_pct)],
      [racha(fl.racha), 'Racha', racha(fv.racha)]]) + '</div>';
    const cs = d.forma_local_casa, fs = d.forma_visita_fuera, cl = d.carga_local, cv = d.carga_visita;
    html += `<div class="card"><h3>Local en casa vs. visitante de visita</h3>` + ((cs.partidos || fs.partidos)
      ? filas([[nd(cs.partidos), 'Partidos', nd(fs.partidos)],
               [`${cs.ganados}-${cs.empatados}-${cs.perdidos}`, 'G-E-P', `${fs.ganados}-${fs.empatados}-${fs.perdidos}`],
               [nd(cs.gf_prom), 'Goles a favor', nd(fs.gf_prom)], [nd(cs.gc_prom), 'Goles en contra', nd(fs.gc_prom)],
               [pc(cs.over25_pct), 'Over 2.5', pc(fs.over25_pct)], [pc(cs.btts_pct), 'Ambos anotan', pc(fs.btts_pct)],
               [pc(cs.porteria_cero_pct), 'Portería en cero', pc(fs.porteria_cero_pct)]])
      : '<span class="muted">Sin partidos suficientes por sede.</span>') + '</div>';
    html += `<div class="card"><h3>Descanso y carga de partidos</h3>` + filas([
      [dias(cl.dias_descanso), 'Desde su último partido', dias(cv.dias_descanso)],
      [nd(cl.partidos_14d), 'Partidos en 14 días', nd(cv.partidos_14d)],
      [nd(cl.partidos_30d), 'Partidos en 30 días', nd(cv.partidos_30d)]]) + '</div>';
    html += `<div class="card"><h3>Historial directo (H2H)</h3>` + (h.partidos
      ? filas([[nd(h.partidos), 'Partidos', nd(h.partidos)], [h.ganados, 'Victorias', h.perdidos], [h.empatados, 'Empates', h.empatados],
               [nd(h.gf_prom), 'Goles prom.', nd(h.gc_prom)], [pc(h.over25_pct), 'Over 2.5', pc(h.over25_pct)], [pc(h.btts_pct), 'Ambos anotan', pc(h.btts_pct)]])
      : '<span class="muted">Sin enfrentamientos recientes.</span>') + '</div>';
    html += `<div class="card"><h3>Jugadores clave (DFS)</h3><div class="dfs">${dfsCard('Local', d.dfs_local)}${dfsCard('Visitante', d.dfs_visita)}</div></div>`;
    html += '<div class="card">' + d.advertencias.map(w => `<div class="warn">⚠ ${esc(w)}</div>`).join('') + '</div>';
    out.innerHTML = html;
    const lig = $('liga').value;
    const box = document.createElement('div');
    box.className = 'card';
    const conApi = oddsOk && ['PL', 'PD', 'BL1', 'CL', 'SA'].includes(lig);
    const campo = (id, et) => `<div><label>${et}</label><input id="q_${id}" inputmode="decimal" placeholder="2.10 o +110"></div>`;
    box.innerHTML = `<h3>Valor frente al mercado</h3>
      <div class="muted" style="margin-bottom:8px">Escribe las cuotas de tu casa (decimal 2.10 o americano +110 / -120). Deja vacío lo que no uses.</div>
      <div class="cuotas">${campo('l', 'Local')}${campo('e', 'Empate')}${campo('v', 'Visitante')}
        ${campo('o', 'Más de 2.5')}${campo('u', 'Menos de 2.5')}<div></div>${campo('bs', 'Ambos anotan: Sí')}${campo('bn', 'Ambos anotan: No')}</div>
      <button class="btn" id="btnManual" style="margin-top:10px">Calcular valor</button><div id="valorManual"></div>` +
      (conApi ? `<hr style="border:0;border-top:1px solid #233154;margin:16px 0"><button class="btn" id="btnValor">O traer cuotas automáticas (The Odds API)</button>
        <div class="muted" style="margin-top:6px">Consume créditos (unos 2–3 la primera vez; se guardan 12 h).</div><div id="valorOut"></div>` : '');
    out.appendChild(box);
    $('btnManual').addEventListener('click', () => {
      const c = {};
      ['l', 'e', 'v', 'o', 'u', 'bs', 'bn'].forEach(k => { c[k] = aDecimal($('q_' + k).value); });
      $('valorManual').innerHTML = valorManual(d, c);
    });
    if (conApi) {
      $('btnValor').addEventListener('click', async () => {
        const b = $('btnValor'), vo = $('valorOut');
        b.disabled = true;
        vo.innerHTML = '<p class="muted">Consultando cuotas…</p>';
        try {
          const v = await api(`/api/valor?liga=${lig}&local_id=${local}&visita_id=${visita}` + (partidoId ? `&partido_id=${partidoId}` : ''));
          vo.innerHTML = pintarValor(v);
        } catch (e) { vo.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
        finally { b.disabled = false; }
      });
    }
    out.scrollIntoView({behavior: 'smooth'});
  } catch (e) {
    out.innerHTML = `<p class="err">${esc(e.message)}</p>`;
  } finally { $('btn').disabled = false; }
}

fetch('/api/health').then(r => r.json()).then(h => { oddsOk = !!h.odds_key_configurada; }).catch(() => {});
$('liga').addEventListener('change', cambioLiga);
$('btn').addEventListener('click', () => analizar());
cargarLigas().catch(e => { $('cartelera').innerHTML = `<span class="err">${esc(e.message)}</span>`; });
</script></body></html>"""



@app.get("/", response_class=HTMLResponse)
async def raiz():
    return PAGINA
