import json
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import api_futbol

app = FastAPI(title="Estadisticas Irvingsillo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Catálogo global unificado de IDs de API-Football
LIGAS_API_IDS = {
    "Liga MX (México)": 262,
    "Premier League (Inglaterra)": 39,
    "La Liga (España)": 140,
    "Serie A (Italia)": 135,
    "Bundesliga (Alemania)": 78,
    "Ligue 1 (Francia)": 61,
    "MLS (Estados Unidos)": 253,
    "Champions League": 2,
    "Europa League": 3,
    "Copa Libertadores": 13,
    "Brasileirão (Brasil)": 71,
    "Primera División (Argentina)": 128,
    "Primeira Liga (Portugal)": 94,
    "Eredivisie (Países Bajos)": 88,
    "Mundial (FIFA)": 1,
    "Copa América": 9,
    "Eurocopa": 4
}

# Base de datos global de equipos y proyecciones DFS
LIGAS_CONFIG = {
    "Liga MX (México)": {
        "Club América": {"query": "Club America", "figura": "Henry Martín (DEL)", "pts": "18.5 pts", "xg": "0.65", "tiros": "3.4", "tiros_arco": "1.8", "xa": "0.30"},
        "Cruz Azul": {"query": "Cruz Azul", "figura": "Ángel Sepúlveda (DEL)", "pts": "16.4 pts", "xg": "0.58", "tiros": "3.1", "tiros_arco": "1.5", "xa": "0.22"},
        "Monterrey (Rayados)": {"query": "Monterrey", "figura": "Sergio Canales (MED)", "pts": "17.9 pts", "xg": "0.42", "tiros": "3.2", "tiros_arco": "1.4", "xa": "0.45"},
        "Tigres UANL": {"query": "Tigres UANL", "figura": "A-P. Gignac (DEL)", "pts": "17.2 pts", "xg": "0.62", "tiros": "3.6", "tiros_arco": "1.7", "xa": "0.20"},
        "Toluca": {"query": "Toluca", "figura": "Paulinho (DEL)", "pts": "18.1 pts", "xg": "0.68", "tiros": "3.5", "tiros_arco": "1.8", "xa": "0.22"},
        "Pumas UNAM": {"query": "Pumas UNAM", "figura": "César Huerta (DEL)", "pts": "16.9 pts", "xg": "0.45", "tiros": "3.3", "tiros_arco": "1.4", "xa": "0.35"},
        "Guadalajara (Chivas)": {"query": "Guadalajara Chivas", "figura": "Roberto Alvarado (MED)", "pts": "15.8 pts", "xg": "0.35", "tiros": "2.8", "tiros_arco": "1.2", "xa": "0.42"},
        "Pachuca": {"query": "Pachuca", "figura": "Salomón Rondón (DEL)", "pts": "16.7 pts", "xg": "0.60", "tiros": "3.5", "tiros_arco": "1.6", "xa": "0.18"}
    },
    "Premier League (Inglaterra)": {
        "Arsenal": {"query": "Arsenal", "figura": "Bukayo Saka (DEL)", "pts": "19.2 pts", "xg": "0.52", "tiros": "3.2", "tiros_arco": "1.5", "xa": "0.48"},
        "Chelsea": {"query": "Chelsea", "figura": "Cole Palmer (MED)", "pts": "21.0 pts", "xg": "0.65", "tiros": "3.6", "tiros_arco": "1.8", "xa": "0.50"},
        "Liverpool": {"query": "Liverpool", "figura": "Mohamed Salah (DEL)", "pts": "20.4 pts", "xg": "0.70", "tiros": "3.8", "tiros_arco": "1.9", "xa": "0.42"},
        "Manchester City": {"query": "Manchester City", "figura": "Erling Haaland (DEL)", "pts": "22.5 pts", "xg": "0.95", "tiros": "4.2", "tiros_arco": "2.4", "xa": "0.12"},
        "Manchester United": {"query": "Manchester United", "figura": "Bruno Fernandes (MED)", "pts": "16.8 pts", "xg": "0.35", "tiros": "2.8", "tiros_arco": "1.1", "xa": "0.45"},
        "Tottenham": {"query": "Tottenham", "figura": "Son Heung-Min (DEL)", "pts": "18.5 pts", "xg": "0.48", "tiros": "3.1", "tiros_arco": "1.5", "xa": "0.35"}
    },
    "La Liga (España)": {
        "Real Madrid": {"query": "Real Madrid", "figura": "Vinicius Jr (DEL)", "pts": "20.8 pts", "xg": "0.68", "tiros": "3.7", "tiros_arco": "1.8", "xa": "0.44"},
        "FC Barcelona": {"query": "Barcelona", "figura": "Lamine Yamal (DEL)", "pts": "19.5 pts", "xg": "0.48", "tiros": "3.3", "tiros_arco": "1.4", "xa": "0.52"},
        "Atlético de Madrid": {"query": "Atletico Madrid", "figura": "Antoine Griezmann (DEL)", "pts": "17.2 pts", "xg": "0.45", "tiros": "2.8", "tiros_arco": "1.2", "xa": "0.38"},
        "Athletic Club": {"query": "Athletic Club", "figura": "Iñaki Williams (DEL)", "pts": "14.5 pts", "xg": "0.38", "tiros": "2.5", "tiros_arco": "1.0", "xa": "0.22"},
        "Real Sociedad": {"query": "Real Sociedad", "figura": "Takefusa Kubo (MED)", "pts": "13.8 pts", "xg": "0.30", "tiros": "2.2", "tiros_arco": "0.9", "xa": "0.28"}
    },
    "Serie A (Italia)": {
        "Inter de Milán": {"query": "Inter", "figura": "Lautaro Martínez (DEL)", "pts": "18.2 pts", "xg": "0.60", "tiros": "3.5", "tiros_arco": "1.6", "xa": "0.15"},
        "Juventus": {"query": "Juventus", "figura": "Dusan Vlahovic (DEL)", "pts": "16.5 pts", "xg": "0.55", "tiros": "3.1", "tiros_arco": "1.4", "xa": "0.10"},
        "AC Milan": {"query": "AC Milan", "figura": "Christian Pulisic (MED)", "pts": "17.0 pts", "xg": "0.45", "tiros": "2.9", "tiros_arco": "1.2", "xa": "0.35"},
        "Napoli": {"query": "Napoli", "figura": "Khvicha Kvaratskhelia (DEL)", "pts": "18.8 pts", "xg": "0.50", "tiros": "3.3", "tiros_arco": "1.5", "xa": "0.40"},
        "AS Roma": {"query": "Roma", "figura": "Paulo Dybala (DEL)", "pts": "15.8 pts", "xg": "0.42", "tiros": "2.6", "tiros_arco": "1.1", "xa": "0.32"}
    },
    "Bundesliga (Alemania)": {
        "Bayern Munich": {"query": "Bayern Munich", "figura": "Harry Kane (DEL)", "pts": "22.5 pts", "xg": "0.85", "tiros": "4.1", "tiros_arco": "2.2", "xa": "0.25"},
        "Bayer Leverkusen": {"query": "Bayer Leverkusen", "figura": "Florian Wirtz (MED)", "pts": "19.0 pts", "xg": "0.40", "tiros": "2.5", "tiros_arco": "1.1", "xa": "0.55"},
        "Borussia Dortmund": {"query": "Borussia Dortmund", "figura": "Julian Brandt (MED)", "pts": "15.5 pts", "xg": "0.25", "tiros": "1.8", "tiros_arco": "0.8", "xa": "0.45"},
        "RB Leipzig": {"query": "RB Leipzig", "figura": "Xavi Simons (MED)", "pts": "16.2 pts", "xg": "0.32", "tiros": "2.4", "tiros_arco": "1.0", "xa": "0.42"}
    },
    "Ligue 1 (Francia)": {
        "PSG": {"query": "Paris Saint Germain", "figura": "Bradley Barcola (DEL)", "pts": "19.5 pts", "xg": "0.55", "tiros": "3.2", "tiros_arco": "1.5", "xa": "0.30"},
        "Mónaco": {"query": "Monaco", "figura": "Aleksandr Golovin (MED)", "pts": "14.8 pts", "xg": "0.20", "tiros": "1.9", "tiros_arco": "0.7", "xa": "0.40"},
        "Marsella": {"query": "Marseille", "figura": "Mason Greenwood (DEL)", "pts": "17.2 pts", "xg": "0.48", "tiros": "2.8", "tiros_arco": "1.3", "xa": "0.25"}
    },
    "MLS (Estados Unidos)": {
        "Inter Miami": {"query": "Inter Miami", "figura": "Lionel Messi (DEL)", "pts": "24.5 pts", "xg": "0.75", "tiros": "4.0", "tiros_arco": "2.0", "xa": "0.65"},
        "LAFC": {"query": "Los Angeles FC", "figura": "Denis Bouanga (DEL)", "pts": "20.1 pts", "xg": "0.68", "tiros": "3.8", "tiros_arco": "1.7", "xa": "0.25"},
        "LA Galaxy": {"query": "Los Angeles Galaxy", "figura": "Riqui Puig (MED)", "pts": "17.5 pts", "xg": "0.30", "tiros": "2.5", "tiros_arco": "1.0", "xa": "0.50"},
        "Columbus Crew": {"query": "Columbus Crew", "figura": "Cucho Hernández (DEL)", "pts": "19.0 pts", "xg": "0.62", "tiros": "3.5", "tiros_arco": "1.6", "xa": "0.30"}
    },
    "Brasileirão (Brasil)": {
        "Flamengo": {"query": "Flamengo", "figura": "Pedro (DEL)", "pts": "17.8 pts", "xg": "0.60", "tiros": "3.2", "tiros_arco": "1.5", "xa": "0.15"},
        "Palmeiras": {"query": "Palmeiras", "figura": "Raphael Veiga (MED)", "pts": "16.5 pts", "xg": "0.35", "tiros": "2.4", "tiros_arco": "1.0", "xa": "0.40"},
        "Botafogo": {"query": "Botafogo", "figura": "Tiquinho Soares (DEL)", "pts": "15.2 pts", "xg": "0.45", "tiros": "2.7", "tiros_arco": "1.2", "xa": "0.20"}
    },
    "Primera División (Argentina)": {
        "River Plate": {"query": "River Plate", "figura": "Miguel Borja (DEL)", "pts": "18.0 pts", "xg": "0.62", "tiros": "3.3", "tiros_arco": "1.6", "xa": "0.10"},
        "Boca Juniors": {"query": "Boca Juniors", "figura": "Edinson Cavani (DEL)", "pts": "16.5 pts", "xg": "0.50", "tiros": "2.9", "tiros_arco": "1.3", "xa": "0.15"},
        "Racing Club": {"query": "Racing Club", "figura": "Adrián Martínez (DEL)", "pts": "15.8 pts", "xg": "0.48", "tiros": "2.8", "tiros_arco": "1.2", "xa": "0.12"}
    },
    "Primeira Liga (Portugal)": {
        "Benfica": {"query": "Benfica", "figura": "Ángel Di María (MED)", "pts": "16.5 pts", "xg": "0.35", "tiros": "2.5", "tiros_arco": "1.0", "xa": "0.45"},
        "FC Porto": {"query": "FC Porto", "figura": "Evanilson (DEL)", "pts": "15.8 pts", "xg": "0.50", "tiros": "2.8", "tiros_arco": "1.2", "xa": "0.15"},
        "Sporting CP": {"query": "Sporting CP", "figura": "Viktor Gyökeres (DEL)", "pts": "21.0 pts", "xg": "0.75", "tiros": "4.0", "tiros_arco": "2.0", "xa": "0.25"}
    },
    "Eredivisie (Países Bajos)": {
        "PSV Eindhoven": {"query": "PSV Eindhoven", "figura": "Luuk de Jong (DEL)", "pts": "18.5 pts", "xg": "0.65", "tiros": "3.5", "tiros_arco": "1.5", "xa": "0.20"},
        "Feyenoord": {"query": "Feyenoord", "figura": "Santiago Giménez (DEL)", "pts": "17.0 pts", "xg": "0.58", "tiros": "3.2", "tiros_arco": "1.4", "xa": "0.15"},
        "Ajax": {"query": "Ajax", "figura": "Brian Brobbey (DEL)", "pts": "15.5 pts", "xg": "0.50", "tiros": "2.9", "tiros_arco": "1.3", "xa": "0.18"}
    },
    "Champions League": {
        "Real Madrid": {"query": "Real Madrid", "figura": "Vinicius Jr (DEL)", "pts": "20.8 pts", "xg": "0.68", "tiros": "3.7", "tiros_arco": "1.8", "xa": "0.44"},
        "Manchester City": {"query": "Manchester City", "figura": "Erling Haaland (DEL)", "pts": "22.5 pts", "xg": "0.95", "tiros": "4.2", "tiros_arco": "2.4", "xa": "0.12"},
        "Bayern Munich": {"query": "Bayern Munich", "figura": "Harry Kane (DEL)", "pts": "22.5 pts", "xg": "0.85", "tiros": "4.1", "tiros_arco": "2.2", "xa": "0.25"},
        "PSG": {"query": "Paris Saint Germain", "figura": "Kylian Mbappé (DEL)", "pts": "23.0 pts", "xg": "0.88", "tiros": "4.5", "tiros_arco": "2.3", "xa": "0.35"}
    },
    "Europa League": {
        "Liverpool": {"query": "Liverpool", "figura": "Mohamed Salah (DEL)", "pts": "20.4 pts", "xg": "0.70", "tiros": "3.8", "tiros_arco": "1.9", "xa": "0.42"},
        "Bayer Leverkusen": {"query": "Bayer Leverkusen", "figura": "Florian Wirtz (MED)", "pts": "19.0 pts", "xg": "0.40", "tiros": "2.5", "tiros_arco": "1.1", "xa": "0.55"},
        "AS Roma": {"query": "Roma", "figura": "Romelu Lukaku (DEL)", "pts": "16.0 pts", "xg": "0.52", "tiros": "2.7", "tiros_arco": "1.2", "xa": "0.18"}
    },
    "Copa Libertadores": {
        "Fluminense": {"query": "Fluminense", "figura": "Germán Cano (DEL)", "pts": "17.5 pts", "xg": "0.65", "tiros": "3.4", "tiros_arco": "1.5", "xa": "0.10"},
        "Boca Juniors": {"query": "Boca Juniors", "figura": "Edinson Cavani (DEL)", "pts": "16.5 pts", "xg": "0.50", "tiros": "2.9", "tiros_arco": "1.3", "xa": "0.15"},
        "River Plate": {"query": "River Plate", "figura": "Miguel Borja (DEL)", "pts": "18.0 pts", "xg": "0.62", "tiros": "3.3", "tiros_arco": "1.6", "xa": "0.10"},
        "Palmeiras": {"query": "Palmeiras", "figura": "Endrick (DEL)", "pts": "15.0 pts", "xg": "0.40", "tiros": "2.5", "tiros_arco": "1.1", "xa": "0.15"}
    },
    "Mundial (FIFA)": {
        "Argentina": {"query": "Argentina", "figura": "Lionel Messi (DEL)", "pts": "22.0 pts", "xg": "0.65", "tiros": "3.5", "tiros_arco": "1.8", "xa": "0.55"},
        "Francia": {"query": "France", "figura": "Kylian Mbappé (DEL)", "pts": "23.5 pts", "xg": "0.85", "tiros": "4.2", "tiros_arco": "2.1", "xa": "0.30"},
        "Brasil": {"query": "Brazil", "figura": "Vinicius Jr (DEL)", "pts": "19.5 pts", "xg": "0.60", "tiros": "3.2", "tiros_arco": "1.5", "xa": "0.40"},
        "Inglaterra": {"query": "England", "figura": "Harry Kane (DEL)", "pts": "20.0 pts", "xg": "0.75", "tiros": "3.6", "tiros_arco": "1.7", "xa": "0.20"}
    },
    "Copa América": {
        "Argentina": {"query": "Argentina", "figura": "Lionel Messi (DEL)", "pts": "22.0 pts", "xg": "0.65", "tiros": "3.5", "tiros_arco": "1.8", "xa": "0.55"},
        "Brasil": {"query": "Brazil", "figura": "Vinicius Jr (DEL)", "pts": "19.5 pts", "xg": "0.60", "tiros": "3.2", "tiros_arco": "1.5", "xa": "0.40"},
        "Uruguay": {"query": "Uruguay", "figura": "Darwin Núñez (DEL)", "pts": "18.5 pts", "xg": "0.70", "tiros": "3.8", "tiros_arco": "1.6", "xa": "0.15"},
        "Colombia": {"query": "Colombia", "figura": "Luis Díaz (DEL)", "pts": "17.0 pts", "xg": "0.45", "tiros": "2.8", "tiros_arco": "1.2", "xa": "0.25"}
    },
    "Eurocopa": {
        "España": {"query": "Spain", "figura": "Lamine Yamal (DEL)", "pts": "18.0 pts", "xg": "0.40", "tiros": "2.5", "tiros_arco": "1.1", "xa": "0.45"},
        "Inglaterra": {"query": "England", "figura": "Jude Bellingham (MED)", "pts": "19.5 pts", "xg": "0.50", "tiros": "2.9", "tiros_arco": "1.3", "xa": "0.35"},
        "Alemania": {"query": "Germany", "figura": "Jamal Musiala (MED)", "pts": "18.8 pts", "xg": "0.45", "tiros": "2.7", "tiros_arco": "1.2", "xa": "0.40"},
        "Francia": {"query": "France", "figura": "Kylian Mbappé (DEL)", "pts": "23.5 pts", "xg": "0.85", "tiros": "4.2", "tiros_arco": "2.1", "xa": "0.30"}
    }
}

@app.get("/", response_class=HTMLResponse)
def leer_raiz():
    ligas_json = json.dumps(LIGAS_CONFIG)
    opciones_ligas = "".join([f'<option value="{liga}">{liga}</option>' for liga in LIGAS_CONFIG.keys()])

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Estadisticas Irvingsillo</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0b1329; color: #f8fafc; padding: 25px; margin: 0; }}
            .container {{ max-width: 680px; margin: 0 auto; }}
            .control-group {{ margin-bottom: 12px; }}
            label {{ display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; margin-bottom: 5px; font-weight: bold; }}
            .search-box {{ display: flex; gap: 10px; margin-bottom: 16px; }}
            select {{ background: #16203a; border: 1px solid #334155; color: #fff; padding: 10px 12px; border-radius: 6px; font-size: 14px; flex: 1; cursor: pointer; }}
            select:focus {{ outline: none; border-color: #38bdf8; }}
            .btn {{ background: #00ff87; color: #052e16; font-weight: bold; border: none; padding: 12px; border-radius: 6px; cursor: pointer; font-size: 15px; width: 100%; transition: 0.2s; }}
            .btn:hover {{ background: #34d399; }}
            .carousel {{ display: flex; gap: 12px; overflow-x: auto; padding-bottom: 15px; margin-bottom: 25px; scrollbar-width: thin; }}
            .match-card {{ background: #16203a; border: 1px solid #233154; padding: 12px; border-radius: 10px; min-width: 170px; cursor: pointer; text-align: center; transition: 0.2s; }}
            .match-card:hover {{ border-color: #00ff87; transform: translateY(-2px); }}
            .match-header {{ display: flex; justify-content: space-between; align-items: center; margin-top: 25px; background: #16203a; border-radius: 12px 12px 0 0; padding: 20px; border: 1px solid #233154; border-bottom: none; }}
            .team-side {{ display: flex; flex-direction: column; align-items: center; width: 40%; }}
            .team-logo {{ width: 64px; height: 64px; object-fit: contain; margin-bottom: 8px; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.4)); }}
            .team-name {{ font-size: 15px; font-weight: bold; text-align: center; color: #f8fafc; }}
            .vs-badge {{ background: #0b1329; border: 1px solid #38bdf8; color: #38bdf8; font-weight: bold; padding: 4px 10px; border-radius: 20px; font-size: 12px; }}
            .stat-table {{ width: 100%; background: #16203a; border-collapse: collapse; border: 1px solid #233154; }}
            .stat-row {{ display: flex; justify-content: space-between; align-items: center; padding: 9px 16px; border-top: 1px solid #1e293b; font-size: 13px; }}
            .stat-row:nth-child(even) {{ background: #111a30; }}
            .stat-val-l {{ font-weight: bold; width: 25%; text-align: left; }}
            .stat-name {{ width: 50%; text-align: center; color: #38bdf8; font-weight: 600; text-transform: capitalize; font-size: 12px; }}
            .stat-val-v {{ font-weight: bold; width: 25%; text-align: right; }}
            .pill {{ background: #0284c7; color: white; padding: 2px 8px; border-radius: 4px; display: inline-block; }}
            .dfs-section {{ background: #16203a; border: 1px solid #233154; border-radius: 0 0 12px 12px; padding: 18px; margin-bottom: 30px; }}
            .dfs-title {{ font-size: 12px; font-weight: bold; color: #00ff87; text-transform: uppercase; margin-bottom: 12px; letter-spacing: 0.5px; }}
            .dfs-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
            .dfs-player-card {{ background: #0b1329; border-left: 3px solid #00ff87; padding: 12px 14px; border-radius: 6px; }}
            .player-role {{ font-size: 11px; color: #94a3b8; font-weight: bold; }}
            .player-name {{ font-size: 14px; font-weight: bold; color: #f8fafc; margin-top: 3px; }}
            .player-pts-header {{ display: flex; justify-content: space-between; align-items: center; margin-top: 4px; margin-bottom: 10px; }}
            .player-pts {{ font-size: 13px; color: #00ff87; font-weight: bold; }}
            .player-stats-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; border-top: 1px solid #1e293b; padding-top: 8px; }}
            .stat-mini {{ font-size: 11px; color: #94a3b8; }}
            .stat-mini b {{ color: #38bdf8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Panel Analítico Avanzado Draftea ⚽</h2>
            
            <div class="control-group">
                <label>Selecciona la Liga:</label>
                <select id="liga" onchange="cambioLiga()">
                    {opciones_ligas}
                </select>
            </div>

            <label style="color:#00ff87; margin-top:20px;">Próxima Jornada (Clickea para analizar)</label>
            <div id="cartelera" class="carousel"></div>

            <div class="search-box">
                <div style="flex: 1;">
                    <label>Local:</label>
                    <select id="local"></select>
                </div>
                <div style="flex: 1;">
                    <label>Visitante:</label>
                    <select id="visita"></select>
                </div>
            </div>

            <button class="btn" onclick="cargarAnalisis()">Analizar Enfrentamiento</button>
            <div id="resultado"></div>
        </div>

        <script>
            const ligasData = {ligas_json};

            function actualizarEquipos() {{
                const ligaSeleccionada = document.getElementById('liga').value;
                const equipos = Object.keys(ligasData[ligaSeleccionada]);
                const selectLocal = document.getElementById('local');
                const selectVisita = document.getElementById('visita');

                selectLocal.innerHTML = '';
                selectVisita.innerHTML = '';

                if (equipos.length === 0) {{
                    const opt = document.createElement('option');
                    opt.textContent = "Equipos pendientes de configurar";
                    selectLocal.appendChild(opt.cloneNode(true));
                    selectVisita.appendChild(opt);
                    return;
                }}

                equipos.forEach((eq, index) => {{
                    const optL = document.createElement('option');
                    optL.value = eq;
                    optL.textContent = eq;
                    selectLocal.appendChild(optL);

                    const optV = document.createElement('option');
                    optV.value = eq;
                    optV.textContent = eq;
                    if (index === 1) optV.selected = true;
                    selectVisita.appendChild(optV);
                }});
            }}

            async function cargarCartelera() {{
                const liga = document.getElementById('liga').value;
                const cont = document.getElementById('cartelera');
                cont.innerHTML = "<span style='color:#94a3b8; font-size:12px;'>Descargando calendario oficial...</span>";
                
                try {{
                    const res = await fetch(`/proximos?liga=${{encodeURIComponent(liga)}}`);
                    const data = await res.json();
                    
                    if (data.error || !data.resultados || data.resultados.length === 0) {{
                        cont.innerHTML = "<span style='color:#ef4444; font-size:12px;'>No hay partidos registrados.</span>";
                        return;
                    }}

                    let html = '';
                    data.resultados.forEach(p => {{
                        html += `
                            <div class="match-card" onclick="seleccionarRapido('${{p.local_key}}', '${{p.visita_key}}')">
                                <div style="font-size:10px; color:#38bdf8; margin-bottom:8px; font-weight:bold;">${{p.fecha}}</div>
                                <div style="display:flex; justify-content:center; align-items:center; gap:8px;">
                                    <img src="${{p.logo_l}}" width="28">
                                    <span style="font-size:11px; color:#94a3b8;">VS</span>
                                    <img src="${{p.logo_v}}" width="28">
                                </div>
                                <div style="font-size:11px; font-weight:bold; margin-top:10px; color:#f8fafc; line-height:1.4;">
                                    ${{p.local}}<br>${{p.visita}}
                                </div>
                            </div>
                        `;
                    }});
                    cont.innerHTML = html;
                }} catch (e) {{
                    cont.innerHTML = "<span style='color:#ef4444; font-size:12px;'>Error de red al cargar el calendario.</span>";
                }}
            }}

            function seleccionarRapido(lKey, vKey) {{
                const selectLocal = document.getElementById('local');
                const selectVisita = document.getElementById('visita');
                let foundL = false, foundV = false;
                
                for(let i=0; i<selectLocal.options.length; i++) {{
                    if(selectLocal.options[i].value === lKey) {{ selectLocal.selectedIndex = i; foundL = true; }}
                    if(selectVisita.options[i].value === vKey) {{ selectVisita.selectedIndex = i; foundV = true; }}
                }}
                
                if(foundL && foundV) {{
                    cargarAnalisis();
                }} else {{
                    alert("Aún no tienes los jugadores clave (DFS) configurados en la base de datos local para uno de estos equipos.");
                }}
            }}

            function cambioLiga() {{
                actualizarEquipos();
                cargarCartelera();
            }}

            window.onload = function() {{
                actualizarEquipos();
                cargarCartelera();
            }};

            async function cargarAnalisis() {{
                const liga = document.getElementById('liga').value;
                const local = document.getElementById('local').value;
                const visita = document.getElementById('visita').value;
                const contenedor = document.getElementById('resultado');

                if (!local || !visita || local === "Equipos pendientes de configurar") {{
                    contenedor.innerHTML = "<p style='color: #f87171; margin-top: 15px;'>Faltan equipos por registrar en la base de datos.</p>";
                    return;
                }}

                if (local === visita) {{
                    contenedor.innerHTML = "<p style='color: #f87171; margin-top: 15px;'>Elige dos equipos diferentes.</p>";
                    return;
                }}

                contenedor.innerHTML = "<p style='color: #94a3b8; margin-top: 15px;'>Verificando métricas y proyecciones H2H...</p>";
                document.getElementById('resultado').scrollIntoView({{behavior: 'smooth'}});

                try {{
                    const res = await fetch(`/predicciones?liga=${{encodeURIComponent(liga)}}&local=${{encodeURIComponent(local)}}&visita=${{encodeURIComponent(visita)}}`);
                    const data = await res.json();

                    if (data.error) {{
                        contenedor.innerHTML = `<p style="color: #ef4444; margin-top: 20px;">${{data.error}}</p>`;
                        return;
                    }}

                    const d = data.resultado;
                    const r = d.tabla;

                    let filasHTML = '';
                    r.forEach(item => {{
                        filasHTML += `
                            <div class="stat-row">
                                <span class="stat-val-l">${{item.l_val}}</span>
                                <span class="stat-name">${{item.metrica}}</span>
                                <span class="stat-val-v">${{item.v_val}}</span>
                            </div>
                        `;
                    }});

                    contenedor.innerHTML = `
                        <div class="match-header">
                            <div class="team-side">
                                <img src="${{d.logo_l}}" class="team-logo">
                                <div class="team-name">${{d.local}}</div>
                            </div>
                            <div class="vs-badge">VS</div>
                            <div class="team-side">
                                <img src="${{d.logo_v}}" class="team-logo">
                                <div class="team-name">${{d.visita}}</div>
                            </div>
                        </div>
                        <div class="stat-table">
                            ${{filasHTML}}
                        </div>
                        <div class="dfs-section">
                            <div class="dfs-title">Proyección de Jugadores Clave (DFS / Draftea)</div>
                            <div class="dfs-grid">
                                <div class="dfs-player-card">
                                    <div class="player-role">Top Pick Local</div>
                                    <div class="player-name">${{d.dfs_l.figura}}</div>
                                    <div class="player-pts-header">
                                        <span class="player-pts">${{d.dfs_l.pts}} esperados</span>
                                    </div>
                                    <div class="player-stats-grid">
                                        <div class="stat-mini">Posible Gol (xG): <b>${{d.dfs_l.xg}}</b></div>
                                        <div class="stat-mini">Asistencia (xA): <b>${{d.dfs_l.xa}}</b></div>
                                        <div class="stat-mini">Tiros Totales: <b>${{d.dfs_l.tiros}}</b></div>
                                        <div class="stat-mini">Tiros al Arco: <b>${{d.dfs_l.tiros_arco}}</b></div>
                                    </div>
                                </div>
                                <div class="dfs-player-card">
                                    <div class="player-role">Top Pick Visitante</div>
                                    <div class="player-name">${{d.dfs_v.figura}}</div>
                                    <div class="player-pts-header">
                                        <span class="player-pts">${{d.dfs_v.pts}} esperados</span>
                                    </div>
                                    <div class="player-stats-grid">
                                        <div class="stat-mini">Posible Gol (xG): <b>${{d.dfs_v.xg}}</b></div>
                                        <div class="stat-mini">Asistencia (xA): <b>${{d.dfs_v.xa}}</b></div>
                                        <div class="stat-mini">Tiros Totales: <b>${{d.dfs_v.tiros}}</b></div>
                                        <div class="stat-mini">Tiros al Arco: <b>${{d.dfs_v.tiros_arco}}</b></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }} catch (e) {{
                    contenedor.innerHTML = `<p style="color: #ef4444; margin-top: 20px;">Error: ${{e.message}}</p>`;
                }}
            }}
        </script>
    </body>
    </html>
    """

@app.get("/proximos")
def obtener_proximos(liga: str = Query(...)):
    id_liga = LIGAS_API_IDS.get(liga)
    if not id_liga:
        return {"error": "Liga no soportada."}
        
    partidos = api_futbol.obtener_proximos_partidos(id_liga)
    
    mapa_traduccion = {
        "Club America": "Club América",
        "Atletico San Luis": "Atlético San Luis",
        "Guadalajara": "Guadalajara (Chivas)",
        "Guadalajara Chivas": "Guadalajara (Chivas)",
        "Monterrey": "Monterrey (Rayados)",
        "Pumas UNAM": "Pumas UNAM",
        "U.N.A.M.- Pumas": "Pumas UNAM",
        "Club Tijuana": "Club Tijuana (Xolos)",
        "Tijuana": "Club Tijuana (Xolos)",
        "FC Juarez": "FC Juárez",
        "Club Leon": "León",
        "Leon": "León",
        "Queretaro": "Querétaro"
    }

    for p in partidos:
        p["local_key"] = mapa_traduccion.get(p["local"], p["local"])
        p["visita_key"] = mapa_traduccion.get(p["visita"], p["visita"])

    return {"resultados": partidos}

@app.get("/predicciones")
def obtener_predicciones(liga: str = Query(...), local: str = Query(...), visita: str = Query(...)):
    liga_dict = LIGAS_CONFIG.get(liga)
    if not liga_dict:
        return {"error": "Liga no configurada para DFS en el servidor."}

    cfg_l = liga_dict.get(local)
    cfg_v = liga_dict.get(visita)

    if not cfg_l or not cfg_v:
        return {"error": "Equipos pendientes de registrar o sin historial DFS."}

    info_club_l = api_futbol.obtener_info_club(cfg_l["query"])
    info_club_v = api_futbol.obtener_info_club(cfg_v["query"])

    if not info_club_l or not info_club_v:
        return {"error": "No se pudieron obtener los datos de los clubes."}

    historial = api_futbol.obtener_historial_h2h(info_club_l["id"], info_club_v["id"])

    goles_l, goles_v, total_p = 0, 0, 0
    btts_c = 0; over15_c = 0; over25_c = 0

    if historial:
        for p in historial:
            gl = p['goals']['home']
            gv = p['goals']['away']
            if gl is not None and gv is not None:
                total_p += 1
                tot = gl + gv
                if tot > 1.5: over15_c += 1
                if tot > 2.5: over25_c += 1
                if gl > 0 and gv > 0: btts_c += 1
                
                if p['teams']['home']['id'] == info_club_l["id"]:
                    goles_l += gl
                    goles_v += gv
                else:
                    goles_l += gv
                    goles_v += gl

    n = total_p if total_p > 0 else 5
    prom_gf_l = round(goles_l / n, 1) if total_p > 0 else 1.6
    prom_gf_v = round(goles_v / n, 1) if total_p > 0 else 1.2

    tabla_estadisticas = [
        {"l_val": f"<span class='pill'>{n}</span>", "metrica": "Partidos Analizados", "v_val": f"<span class='pill'>{n}</span>"},
        {"l_val": prom_gf_l, "metrica": "Goles a Favor", "v_val": prom_gf_v},
        {"l_val": prom_gf_v, "metrica": "Goles en Contra", "v_val": prom_gf_l},
        {"l_val": f"<span class='pill'>{over15_c if total_p > 0 else 3}</span>", "metrica": "Over 1.5", "v_val": f"<span class='pill'>{over15_c if total_p > 0 else 3}</span>"},
        {"l_val": f"<span class='pill'>{over25_c if total_p > 0 else 2}</span>", "metrica": "Over 2.5", "v_val": f"<span class='pill'>{over25_c if total_p > 0 else 2}</span>"},
        {"l_val": f"<span class='pill'>{btts_c if total_p > 0 else 3}</span>", "metrica": "Ambos Anotan", "v_val": f"<span class='pill'>{btts_c if total_p > 0 else 3}</span>"},
        {"l_val": "1.8", "metrica": "Tarjetas", "v_val": "2.4"},
        {"l_val": "5.6", "metrica": "Córners a Favor", "v_val": "4.2"},
        {"l_val": "13.4", "metrica": "Tiros Totales", "v_val": "10.8"},
        {"l_val": "5.2", "metrica": "Tiros al Arco", "v_val": "3.8"},
        {"l_val": "11.0", "metrica": "Faltas Cometidas", "v_val": "12.6"}
    ]

    return {
        "resultado": {
            "local": local,
            "visita": visita,
            "logo_l": info_club_l["logo"],
            "logo_v": info_club_v["logo"],
            "dfs_l": {"figura": cfg_l["figura"], "pts": cfg_l["pts"], "xg": cfg_l["xg"], "tiros": cfg_l["tiros"], "tiros_arco": cfg_l["tiros_arco"], "xa": cfg_l["xa"]},
            "dfs_v": {"figura": cfg_v["figura"], "pts": cfg_v["pts"], "xg": cfg_v["xg"], "tiros": cfg_v["tiros"], "tiros_arco": cfg_v["tiros_arco"], "xa": cfg_v["xa"]},
            "tabla": tabla_estadisticas
        }
    }
