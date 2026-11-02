import os
import json
import requests

API_KEY = "76bd38beda57b762e2c2595376ece2ab"
BASE_URL = "https://v3.football.api-sports.io/"
HEADERS = {"x-apisports-key": API_KEY}
CACHE_FILE = "equipos_cache.json"

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        CACHE_EQUIPOS = json.load(f)
else:
    CACHE_EQUIPOS = {}

def guardar_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(CACHE_EQUIPOS, f, ensure_ascii=False, indent=2)

def obtener_info_club(nombre_busqueda):
    if nombre_busqueda in CACHE_EQUIPOS:
        return CACHE_EQUIPOS[nombre_busqueda]

    url = f"{BASE_URL}teams"
    respuesta = requests.get(url, headers=HEADERS, params={"search": nombre_busqueda})
    
    if respuesta.status_code == 200 and respuesta.json().get('results', 0) > 0:
        team_data = respuesta.json()['response'][0]['team']
        info = {
            "id": team_data['id'],
            "nombre": team_data['name'],
            "logo": team_data['logo']
        }
        CACHE_EQUIPOS[nombre_busqueda] = info
        guardar_cache()
        return info
    return None

def obtener_historial_h2h(id_local, id_visitante):
    url = f"{BASE_URL}fixtures/headtohead"
    parametros = {"h2h": f"{id_local}-{id_visitante}"}
    respuesta = requests.get(url, headers=HEADERS, params=parametros)
    if respuesta.status_code == 200:
        return respuesta.json().get('response', [])[:5]
    return []

def obtener_proximos_partidos(id_liga):
    cache_key = f"proximos_liga_{id_liga}"
    if cache_key in CACHE_EQUIPOS:
        return CACHE_EQUIPOS[cache_key]

    url = f"{BASE_URL}fixtures"
    parametros = {"league": id_liga, "next": 5}
    respuesta = requests.get(url, headers=HEADERS, params=parametros)
    
    if respuesta.status_code == 200:
        datos = respuesta.json().get('response', [])
        partidos = []
        for p in datos:
            partidos.append({
                "fecha": p["fixture"]["date"][:10],
                "local": p["teams"]["home"]["name"],
                "logo_l": p["teams"]["home"]["logo"],
                "visita": p["teams"]["away"]["name"],
                "logo_v": p["teams"]["away"]["logo"]
            })
        CACHE_EQUIPOS[cache_key] = partidos
        guardar_cache()
        return partidos
    return []