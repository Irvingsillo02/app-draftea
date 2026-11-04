"""Panel Estadístico Draftea Pro v2 — un solo archivo.

Requisitos (requirements.txt): fastapi, uvicorn[standard], httpx
Variable de entorno en Render: API_FOOTBALL_KEY
Start command en Render:      uvicorn main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import logging
import os
import re
import time
import unicodedata
from contextlib import asynccontextmanager
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
    (os.getenv(k) for k in ("API_FOOTBALL_KEY", "API_KEY", "APIFOOTBALL_KEY", "X_APISPORTS_KEY") if os.getenv(k)),
    None,
)
API_BASE = os.getenv("API_FOOTBALL_BASE", "https://v3.football.api-sports.io")
MAX_CONCURRENTES = int(os.getenv("MAX_CONCURRENTES", "4"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

TTL_CARTELERA = 3600      # 1 h
TTL_EQUIPOS = 86400       # 24 h
TTL_HISTORIAL = 21600     # 6 h
TTL_ESTADISTICAS = 43200  # 12 h

LIGAS: dict[int, str] = {
    262: "Liga MX (México)", 39: "Premier League (Inglaterra)", 140: "La Liga (España)",
    135: "Serie A (Italia)", 78: "Bundesliga (Alemania)", 61: "Ligue 1 (Francia)",
    253: "MLS (Estados Unidos)", 2: "Champions League", 3: "Europa League",
    13: "Copa Libertadores", 71: "Brasileirão (Brasil)", 128: "Primera División (Argentina)",
    94: "Primeira Liga (Portugal)", 88: "Eredivisie (Países Bajos)", 1: "Mundial (FIFA)",
    9: "Copa América", 4: "Eurocopa",
}

# =====================================================================
# 2. PROYECCIONES DFS (manuales). Cada equipo una sola vez.
#    (nombre, query de la API, figura, pts, xG, tiros, tiros al arco, xA)
# =====================================================================
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

# Nombres que la API escribe distinto a tus llaves (ya normalizados con clave())
_ALIAS_API = {"bayern munchen": "Bayern Munich"}
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
    btts_pct: float | None = None
    over15_pct: float | None = None
    over25_pct: float | None = None
    racha: str = ""  # más reciente primero


class Detalle(BaseModel):
    partidos: int = 0
    tiros: float | None = None
    tiros_arco: float | None = None
    corners: float | None = None
    faltas: float | None = None
    amarillas: float | None = None
    rojas: float | None = None


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


class Analisis(BaseModel):
    local: EquipoRef
    visita: EquipoRef
    h2h: Forma
    forma_local: Forma
    forma_visita: Forma
    detalle_local: Detalle | None = None
    detalle_visita: Detalle | None = None
    probabilidades: Probabilidades | None = None
    dfs_local: Dfs | None = None
    dfs_visita: Dfs | None = None
    advertencias: list[str] = []


def buscar_dfs(nombre: str) -> Dfs | None:
    cfg = _INDICE_DFS.get(clave(nombre))
    if not cfg:
        return None

    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    return Dfs(figura=cfg["figura"], puntos_esperados=f(cfg["pts"]), xg=f(cfg["xg"]),
               xa=f(cfg["xa"]), tiros=f(cfg["tiros"]), tiros_arco=f(cfg["tiros_arco"]))


# =====================================================================
# 4. CACHÉ + CLIENTE API-FOOTBALL
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


class ApiFootballError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class ApiFootball:
    def __init__(self):
        self.cache = TTLCache()
        self._sem = asyncio.Semaphore(MAX_CONCURRENTES)
        if "rapidapi" in API_BASE:
            headers = {"x-rapidapi-key": API_KEY or "", "x-rapidapi-host": API_BASE.split("//")[-1].split("/")[0]}
        else:
            headers = {"x-apisports-key": API_KEY or ""}
        self._http = httpx.AsyncClient(base_url=API_BASE, headers=headers, timeout=httpx.Timeout(10.0))

    async def cerrar(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any], ttl: int) -> list[dict]:
        if not API_KEY:
            raise ApiFootballError(500, "Falta la variable de entorno API_FOOTBALL_KEY en el servidor.")
        key = (path, tuple(sorted(params.items())))

        async def fetch() -> list[dict]:
            try:
                async with self._sem:
                    r = await self._http.get(path, params=params)
                r.raise_for_status()
                body = r.json()
            except httpx.HTTPError as e:
                raise ApiFootballError(502, f"Error al consultar API-Football: {e}") from e
            if body.get("errors"):  # la API manda {} o [] cuando no hay errores
                raise ApiFootballError(502, f"API-Football: {body['errors']}")
            return body.get("response", [])

        return await self.cache.get_or_set(key, ttl, fetch)

    async def temporada_actual(self, liga_id: int) -> int:
        r = await self._get("/leagues", {"id": liga_id, "current": "true"}, TTL_EQUIPOS)
        if not r or not r[0].get("seasons"):
            raise ApiFootballError(404, f"Sin temporada actual para la liga {liga_id}")
        return r[0]["seasons"][0]["year"]

    async def equipos_liga(self, liga_id: int, temporada: int) -> list[dict]:
        r = await self._get("/teams", {"league": liga_id, "season": temporada}, TTL_EQUIPOS)
        return [x["team"] for x in r]

    async def equipo(self, team_id: int) -> dict:
        r = await self._get("/teams", {"id": team_id}, TTL_EQUIPOS)
        if not r:
            raise ApiFootballError(404, f"Equipo {team_id} no encontrado")
        return r[0]["team"]

    async def proximos(self, liga_id: int, n: int) -> list[dict]:
        return await self._get("/fixtures", {"league": liga_id, "next": n}, TTL_CARTELERA)

    async def ultimos(self, team_id: int, n: int = 10) -> list[dict]:
        return await self._get("/fixtures", {"team": team_id, "last": n}, TTL_HISTORIAL)

    async def h2h(self, a: int, b: int, n: int = 10) -> list[dict]:
        return await self._get("/fixtures/headtohead", {"h2h": f"{a}-{b}", "last": n}, TTL_HISTORIAL)

    async def stats_partido(self, fixture_id: int) -> list[dict]:
        return await self._get("/fixtures/statistics", {"fixture": fixture_id}, TTL_ESTADISTICAS)


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


def resumen_forma(fixtures: list[dict], team_id: int) -> Forma:
    jugados = sorted((f for f in fixtures if _terminado(f)),
                     key=lambda f: f["fixture"]["timestamp"], reverse=True)
    n = len(jugados)
    if n == 0:
        return Forma()
    gf = gc = g = e = p = btts = o15 = o25 = 0
    racha = []
    for f in jugados:
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
        btts += a > 0 and b > 0
        o15 += a + b > 1.5
        o25 += a + b > 2.5
    pc = lambda x: round(100 * x / n, 1)  # noqa: E731
    return Forma(partidos=n, ganados=g, empatados=e, perdidos=p,
                 gf_prom=round(gf / n, 2), gc_prom=round(gc / n, 2),
                 btts_pct=pc(btts), over15_pct=pc(o15), over25_pct=pc(o25),
                 racha="".join(racha[:5]))


def _pois(k: int, lam: float) -> float:
    return exp(-lam) * lam**k / factorial(k)


def _ajustar(prom: float | None, n: int) -> float:
    if prom is None:
        return PRIOR_GOLES
    return (prom * n + PRIOR_GOLES * K_SHRINK) / (n + K_SHRINK)


def calcular_probabilidades(fl: Forma, fv: Forma, max_g: int = 10) -> Probabilidades:
    lam_l = (_ajustar(fl.gf_prom, fl.partidos) + _ajustar(fv.gc_prom, fv.partidos)) / 2 * FACTOR_LOCAL
    lam_v = (_ajustar(fv.gf_prom, fv.partidos) + _ajustar(fl.gc_prom, fl.partidos)) / 2 * FACTOR_VISITA
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


_MAPA_STATS = {"Total Shots": "tiros", "Shots on Goal": "tiros_arco", "Corner Kicks": "corners",
               "Fouls": "faltas", "Yellow Cards": "amarillas", "Red Cards": "rojas"}
_CERO_SI_NULO = {"amarillas", "rojas"}


def _num(v):
    try:
        return float(str(v).strip("%"))
    except (TypeError, ValueError):
        return None


async def detalle_equipo(api: ApiFootball, team_id: int, fixtures: list[dict], n: int = 5) -> Detalle:
    recientes = sorted((f for f in fixtures if _terminado(f)),
                       key=lambda f: f["fixture"]["timestamp"], reverse=True)[:n]
    respuestas = await asyncio.gather(*(api.stats_partido(f["fixture"]["id"]) for f in recientes),
                                      return_exceptions=True)
    acum: dict[str, list[float]] = {v: [] for v in _MAPA_STATS.values()}
    usados = 0
    for r in respuestas:
        if isinstance(r, Exception):
            continue
        bloque = next((b for b in r if b["team"]["id"] == team_id), None)
        if not bloque:
            continue
        usados += 1
        for st in bloque["statistics"]:
            campo = _MAPA_STATS.get(st["type"])
            if not campo:
                continue
            val = _num(st["value"])
            if val is None and campo in _CERO_SI_NULO:
                val = 0.0
            if val is not None:
                acum[campo].append(val)
    return Detalle(partidos=usados,
                   **{k: (round(sum(v) / len(v), 1) if v else None) for k, v in acum.items()})


# =====================================================================
# 6. APP Y RUTAS
# =====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.api = ApiFootball()
    if not API_KEY:
        logging.warning("API_FOOTBALL_KEY no está configurada")
    yield
    await app.state.api.cerrar()


app = FastAPI(title="Panel Estadístico Draftea Pro", version="2.0", lifespan=lifespan)

if CORS_ORIGINS:  # solo si el front vive en otro dominio
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET"], allow_headers=["*"])


def get_api(request: Request) -> ApiFootball:
    return request.app.state.api


Api = Annotated[ApiFootball, Depends(get_api)]


@app.exception_handler(ApiFootballError)
async def _api_error(_: Request, exc: ApiFootballError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _ref(t: dict) -> EquipoRef:
    return EquipoRef(id=t["id"], nombre=t["name"], logo=t.get("logo"))


def _equipo(t: dict) -> Equipo:
    return Equipo(id=t["id"], nombre=t["name"], logo=t.get("logo"), tiene_dfs=buscar_dfs(t["name"]) is not None)


@app.get("/api/health")
async def health():
    return {"ok": True, "api_key_configurada": bool(API_KEY)}


@app.get("/api/ligas")
async def ligas():
    return [{"id": i, "nombre": n} for i, n in LIGAS.items()]


@app.get("/api/ligas/{liga_id}/equipos", response_model=list[Equipo])
async def equipos(liga_id: int, api: Api):
    if liga_id not in LIGAS:
        raise HTTPException(404, "Liga no soportada")
    temporada = await api.temporada_actual(liga_id)
    return [_equipo(t) for t in await api.equipos_liga(liga_id, temporada)]


@app.get("/api/ligas/{liga_id}/proximos", response_model=list[Partido])
async def proximos(liga_id: int, api: Api, n: Annotated[int, Query(ge=1, le=30)] = 10):
    if liga_id not in LIGAS:
        raise HTTPException(404, "Liga no soportada")
    items = await api.proximos(liga_id, n)
    return [Partido(fixture_id=i["fixture"]["id"], fecha=i["fixture"]["date"],
                    ronda=i["league"].get("round"), estadio=(i["fixture"].get("venue") or {}).get("name"),
                    local=_equipo(i["teams"]["home"]), visita=_equipo(i["teams"]["away"]))
            for i in items]


@app.get("/api/analisis", response_model=Analisis)
async def analisis(api: Api, local_id: int, visita_id: int,
                   detalle: Annotated[bool, Query(description="Incluye tiros/córners/faltas (más llamadas)")] = False):
    if local_id == visita_id:
        raise HTTPException(422, "Elige dos equipos diferentes")

    t_l, t_v, ult_l, ult_v, h2h = await asyncio.gather(
        api.equipo(local_id), api.equipo(visita_id),
        api.ultimos(local_id, 10), api.ultimos(visita_id, 10), api.h2h(local_id, visita_id, 10))

    forma_l, forma_v = resumen_forma(ult_l, local_id), resumen_forma(ult_v, visita_id)
    h2h_res = resumen_forma(h2h, local_id)

    det_l = det_v = None
    if detalle:
        det_l, det_v = await asyncio.gather(detalle_equipo(api, local_id, ult_l),
                                            detalle_equipo(api, visita_id, ult_v))

    dfs_l, dfs_v = buscar_dfs(t_l["name"]), buscar_dfs(t_v["name"])

    avisos = []
    if h2h_res.partidos < 3:
        avisos.append(f"H2H con solo {h2h_res.partidos} partido(s): no es una muestra confiable.")
    if min(forma_l.partidos, forma_v.partidos) < 5:
        avisos.append("Forma reciente con menos de 5 partidos en algún equipo; las probabilidades se acercan a la media.")
    if not dfs_l or not dfs_v:
        avisos.append("Sin proyección DFS cargada para alguno de los equipos.")
    if dfs_l or dfs_v:
        avisos.append("Las proyecciones DFS son valores cargados a mano, no calculados en vivo.")
    avisos.append("Las probabilidades son un modelo Poisson simple basado en goles recientes; no considera lesiones ni alineaciones.")

    return Analisis(local=_ref(t_l), visita=_ref(t_v), h2h=h2h_res,
                    forma_local=forma_l, forma_visita=forma_v,
                    detalle_local=det_l, detalle_visita=det_v,
                    probabilidades=calcular_probabilidades(forma_l, forma_v),
                    dfs_local=dfs_l, dfs_visita=dfs_v, advertencias=avisos)


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
@media(max-width:520px){.dfs{grid-template-columns:1fr}}
</style></head><body><div class="container">
<h2>Panel Analítico Draftea ⚽</h2>
<label>Liga</label><select id="liga"></select>
<label style="margin-top:16px;color:#00ff87">Próximos partidos (clic para analizar)</label>
<div id="cartelera" class="carousel"></div>
<div class="row"><div><label>Local</label><select id="local"></select></div>
<div><label>Visitante</label><select id="visita"></select></div></div>
<label class="check"><input type="checkbox" id="detalle"> Incluir tiros, córners y faltas reales (usa más llamadas a la API)</label>
<button class="btn" id="btn">Analizar enfrentamiento</button>
<div id="resultado"></div>
</div>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nd = x => (x === null || x === undefined) ? 'N/D' : x;
const pc = x => (x === null || x === undefined) ? 'N/D' : x + '%';
const fr = x => Math.round(x * 100) + '%';

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
  const [eq, pr] = await Promise.allSettled([api(`/api/ligas/${id}/equipos`), api(`/api/ligas/${id}/proximos?n=10`)]);
  if (eq.status === 'fulfilled') {
    const lista = eq.value.sort((a, b) => a.nombre.localeCompare(b.nombre));
    opciones($('local'), lista, 0); opciones($('visita'), lista, 1);
  }
  const c = $('cartelera');
  if (pr.status === 'rejected') { c.innerHTML = `<span class="err">${esc(pr.reason.message)}</span>`; return; }
  if (!pr.value.length) { c.innerHTML = '<span class="muted">No hay partidos próximos.</span>'; return; }
  c.innerHTML = '';
  pr.value.forEach(p => {
    const d = document.createElement('div');
    d.className = 'match-card';
    d.innerHTML = `<div class="muted" style="color:#38bdf8;font-weight:bold">${esc(new Date(p.fecha).toLocaleString('es-MX', {dateStyle:'short', timeStyle:'short'}))}</div>
      <div style="display:flex;justify-content:center;align-items:center;gap:8px;margin:8px 0">
        <img src="${esc(p.local.logo)}" width="28"><span class="muted">VS</span><img src="${esc(p.visita.logo)}" width="28"></div>
      <div style="font-size:11px;font-weight:bold;line-height:1.4">${esc(p.local.nombre)}<br>${esc(p.visita.nombre)}</div>`;
    d.addEventListener('click', () => {
      $('local').value = p.local.id; $('visita').value = p.visita.id;
      analizar(p.local.id, p.visita.id);
    });
    c.appendChild(d);
  });
}

const filas = rows => '<table>' + rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('') + '</table>';
const racha = r => '<span class="racha">' + [...(r || '')].map(x => `<span class="${x}">${x}</span>`).join('') + '</span>';
const dfsCard = (rol, d) => !d ? `<div class="pl">${rol}<div class="n">Sin proyección cargada</div></div>` :
  `<div class="pl">${rol}<div class="n">${esc(d.figura)}</div><div class="p">${nd(d.puntos_esperados)} pts esperados</div>
   <div style="margin-top:6px">xG: <b>${nd(d.xg)}</b> · xA: <b>${nd(d.xa)}</b><br>Tiros: <b>${nd(d.tiros)}</b> · Al arco: <b>${nd(d.tiros_arco)}</b></div></div>`;

async function analizar(lid, vid) {
  const local = lid || $('local').value, visita = vid || $('visita').value, out = $('resultado');
  if (!local || !visita) { out.innerHTML = '<p class="err">Elige los equipos.</p>'; return; }
  if (local === visita) { out.innerHTML = '<p class="err">Elige dos equipos diferentes.</p>'; return; }
  $('btn').disabled = true;
  out.innerHTML = '<p class="muted">Analizando…</p>';
  try {
    const d = await api(`/api/analisis?local_id=${local}&visita_id=${visita}&detalle=${$('detalle').checked}`);
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
      [pc(fl.over25_pct), 'Over 2.5', pc(fv.over25_pct)], [pc(fl.btts_pct), 'Ambos anotan', pc(fv.btts_pct)],
      [racha(fl.racha), 'Racha', racha(fv.racha)]]) + '</div>';
    html += `<div class="card"><h3>Historial directo (H2H)</h3>` + (h.partidos
      ? filas([[nd(h.partidos), 'Partidos', nd(h.partidos)], [h.ganados, 'Victorias', h.perdidos], [h.empatados, 'Empates', h.empatados],
               [nd(h.gf_prom), 'Goles prom.', nd(h.gc_prom)], [pc(h.over25_pct), 'Over 2.5', pc(h.over25_pct)], [pc(h.btts_pct), 'Ambos anotan', pc(h.btts_pct)]])
      : '<span class="muted">Sin enfrentamientos recientes.</span>') + '</div>';
    if (d.detalle_local && d.detalle_visita) {
      const a = d.detalle_local, b = d.detalle_visita;
      html += `<div class="card"><h3>Promedios reales (últimos ${Math.max(a.partidos, b.partidos)} con datos)</h3>` + filas([
        [nd(a.tiros), 'Tiros totales', nd(b.tiros)], [nd(a.tiros_arco), 'Tiros al arco', nd(b.tiros_arco)],
        [nd(a.corners), 'Córners', nd(b.corners)], [nd(a.faltas), 'Faltas', nd(b.faltas)],
        [nd(a.amarillas), 'Amarillas', nd(b.amarillas)], [nd(a.rojas), 'Rojas', nd(b.rojas)]]) + '</div>';
    }
    html += `<div class="card"><h3>Jugadores clave (DFS)</h3><div class="dfs">${dfsCard('Local', d.dfs_local)}${dfsCard('Visitante', d.dfs_visita)}</div></div>`;
    html += '<div class="card">' + d.advertencias.map(w => `<div class="warn">⚠ ${esc(w)}</div>`).join('') + '</div>';
    out.innerHTML = html;
    out.scrollIntoView({behavior: 'smooth'});
  } catch (e) {
    out.innerHTML = `<p class="err">${esc(e.message)}</p>`;
  } finally { $('btn').disabled = false; }
}

$('liga').addEventListener('change', cambioLiga);
$('btn').addEventListener('click', () => analizar());
cargarLigas().catch(e => { $('cartelera').innerHTML = `<span class="err">${esc(e.message)}</span>`; });
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def raiz():
    return PAGINA
