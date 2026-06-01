import streamlit as st
import urllib.request
import json
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
from datetime import datetime, timedelta
import os
from streamlit_autorefresh import st_autorefresh

warnings.filterwarnings("ignore")

# ==========================================
# 0. PROTOCOLO DE ESTADO Y CONFIGURACIÓN MULTI-ACTIVO
# ==========================================
st.set_page_config(page_title="Alpha V6 Quant Dashboard", layout="wide")
st_autorefresh(interval=60000, key="motor_vigilancia_activa")

def generar_estructura_base_activo():
    return {
        "tf": "15m", "dias": 1, "angulo": 15, "sl_mult": 0.5, # Ajustado a 0.5 por defecto para la nube
        "alertas": {"regimen": True, "cruce_mb": True, "cruce_ms": True}
    }

def cargar_settings_globales():
    if os.path.exists("settings.json"):
        try:
            with open("settings.json", "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"activo_seleccionado": "ETHUSDT", "data_activos": {}}

def guardar_settings_globales():
    try:
        with open("settings.json", "w") as f:
            json.dump(st.session_state["db_master"], f)
    except Exception as e:
        registrar_error("PERSISTENCIA", f"Error I/O: {str(e)}")

if "db_master" not in st.session_state:
    st.session_state["db_master"] = cargar_settings_globales()

if "errores" not in st.session_state:
    st.session_state["errores"] = []

if "historial_multi_activo" not in st.session_state:
    st.session_state["historial_multi_activo"] = {}

def registrar_error(tipo, detalle):
    st.session_state["errores"].append({"tipo": tipo, "detalle": detalle, "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")})

def verificar_error(tipo):
    return any(e["tipo"] == tipo for e in st.session_state["errores"])

def reproducir_alerta_local(nombre_archivo):
    if os.path.exists(nombre_archivo):
        try:
            with open(nombre_archivo, "rb") as f:
                audio_bytes = f.read()
            with st.sidebar:
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)
        except Exception:
            pass 

# ==========================================
# 1. UI: BARRA LATERAL (MODO PRO)
# ==========================================
st.sidebar.header("🚀 Modo Pro: Auditoría")

top_20_cryptos = {
    "Bitcoin (BTC)": "BTCUSDT", "Ethereum (ETH)": "ETHUSDT", "Binance Coin (BNB)": "BNBUSDT",
    "Solana (SOL)": "SOLUSDT", "Ripple (XRP)": "XRPUSDT", "Cardano (ADA)": "ADAUSDT",
    "Avalanche (AVAX)": "AVAXUSDT", "Polkadot (DOT)": "DOTUSDT", "Chainlink (LINK)": "LINKUSDT",
    "Polygon (MATIC)": "MATICUSDT", "Litecoin (LTC)": "LTCUSDT", "Bitcoin Cash (BCH)": "BCHUSDT",
    "Cosmos (ATOM)": "ATOMUSDT", "Uniswap (UNI)": "UNIUSDT", "Stellar (XLM)": "XLMUSDT"
}

crypto_seleccionada = st.sidebar.selectbox("Criptomoneda Objetivo", list(top_20_cryptos.keys()), index=list(top_20_cryptos.values()).index(st.session_state["db_master"].get("activo_seleccionado", "ETHUSDT")))
symbol_actual = top_20_cryptos[crypto_seleccionada]

if st.session_state["db_master"]["activo_seleccionado"] != symbol_actual:
    st.session_state["db_master"]["activo_seleccionado"] = symbol_actual
    guardar_settings_globales()

if symbol_actual not in st.session_state["db_master"]["data_activos"]:
    st.session_state["db_master"]["data_activos"][symbol_actual] = generar_estructura_base_activo()
    guardar_settings_globales()

cfg_activo = st.session_state["db_master"]["data_activos"][symbol_actual]

if symbol_actual not in st.session_state["historial_multi_activo"]:
    st.session_state["historial_multi_activo"][symbol_actual] = {"time": None, "reg": False, "mb": False, "ms": False}

opciones_tf = {"15 Minutos": "15m", "1 Hora": "1h", "4 Horas": "4h", "1 Día": "1d"}
tf_seleccionado = st.sidebar.selectbox("Temporalidad", list(opciones_tf.keys()), index=list(opciones_tf.values()).index(cfg_activo["tf"]))
if cfg_activo["tf"] != opciones_tf[tf_seleccionado]:
    cfg_activo["tf"] = opciones_tf[tf_seleccionado]
    guardar_settings_globales()

opciones_dias = {"1 Día": 1, "2 Días": 2, "3 Días": 3, "1 Semana": 7, "1 Mes (30d)": 30, "2 Meses (60d)": 60, "3 Meses (90d)": 90}
dias_seleccionados = st.sidebar.selectbox("Rango de Historial", list(opciones_dias.keys()), index=list(opciones_dias.values()).index(cfg_activo["dias"]))
if cfg_activo["dias"] != opciones_dias[dias_seleccionados]:
    cfg_activo["dias"] = opciones_dias[dias_seleccionados]
    guardar_settings_globales()

# Este slider ahora controla qué tan "gruesa" es la nube verde
sl_val = st.sidebar.slider("Grosor Nube Verde (Filtro ATR)", 0.1, 2.0, cfg_activo["sl_mult"], 0.1)
if cfg_activo["sl_mult"] != sl_val:
    cfg_activo["sl_mult"] = sl_val
    guardar_settings_globales()

with st.sidebar.expander(f"🔔 Alertas: {crypto_seleccionada}", expanded=True):
    r_val = st.checkbox("Cambio Régimen", value=cfg_activo["alertas"]["regimen"])
    mb_val = st.checkbox("Cruce MediaBuy", value=cfg_activo["alertas"]["cruce_mb"])
    ms_val = st.checkbox("Cruce MediaSell", value=cfg_activo["alertas"]["cruce_ms"])
    
    if cfg_activo["alertas"]["regimen"] != r_val or cfg_activo["alertas"]["cruce_mb"] != mb_val or cfg_activo["alertas"]["cruce_ms"] != ms_val:
        cfg_activo["alertas"]["regimen"] = r_val
        cfg_activo["alertas"]["cruce_mb"] = mb_val
        cfg_activo["alertas"]["cruce_ms"] = ms_val
        guardar_settings_globales()

ticker_activo = symbol_actual.replace("USDT", "")

# ==========================================
# 2. INGESTA DE SEÑAL
# ==========================================
@st.cache_data(ttl=50, show_spinner=False)
def get_market_data(symbol, interval, dias_visuales):
    if verificar_error("BLOQUEO_CATASTROFICO"): return pd.DataFrame()

    buffer_dias = {"15m": 3, "1h": 10, "4h": 40, "1d": 250}.get(interval, 5)
    dias_totales = dias_visuales + buffer_dias
    now = datetime.utcnow()
    start_date = now - timedelta(days=dias_totales)
    current_start = int(start_date.timestamp() * 1000)
    end_time_ms = int(now.timestamp() * 1000)
    motores = [
        ("BINANCE_VISION", "data-api.binance.vision"), 
        ("BINANCE_GLOBAL", "api.binance.com"),
        ("MEXC_OFFSHORE", "api.mexc.com")
    ]
    df_list = []
    
    for nombre_motor, dominio in motores:
        df_list_temp, temp_start, exito_motor = [], current_start, True
        while temp_start < end_time_ms:
            url = f"https://{dominio}/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000&startTime={temp_start}"
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 QuantAlpha'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                if not data: break
                df_temp = pd.DataFrame(data, columns=['Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_time', 'Quote_asset_volume', 'Trades', 'Taker_buy_base', 'Taker_buy_quote', 'Ignore'])
                df_list_temp.append(df_temp[['Open_time', 'Open', 'High', 'Low', 'Close', 'Volume']])
                temp_start = int(df_temp['Close_time'].iloc[-1]) + 1
            except Exception:
                exito_motor = False; break
                
        if exito_motor and df_list_temp:
            df_list = df_list_temp
            break
            
    if not df_list: 
        registrar_error("BLOQUEO_CATASTROFICO", "Conexión rechazada.")
        st.cache_data.clear()
        return pd.DataFrame()
    
    df = pd.concat(df_list, ignore_index=True)
    df.drop_duplicates(subset=['Open_time'], inplace=True)
    df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric)
    df['Date'] = pd.to_datetime(df['Open_time'], unit='ms') - pd.Timedelta(hours=5)
    df.set_index('Date', inplace=True)
    return df

# ==========================================
# 3. MOTOR CUANTITATIVO: MODO PRO (REVERSIÓN A LA MEDIA)
# ==========================================
def calcular_estrategia(df, angulo_requerido, grosor_nube_atr):
    weights = np.array([(1 + (i**2) / (2 * 8.0 * 8**2)) ** (-8.0) for i in range(25)])[::-1]
    weights /= np.sum(weights)
    df['yhat1'] = df['Close'].rolling(25).apply(lambda x: np.dot(x, weights), raw=True)
    df['ATR'] = df['High'].rolling(14).max() - df['Low'].rolling(14).min()
    df['Angle'] = np.degrees(np.arctan((df['yhat1'].diff(1) / df['ATR']) * 10))

    df['Trailing_Top'] = df['High'].rolling(200).max()
    df['Trailing_Bottom'] = df['Low'].rolling(200).min()
    rango = df['Trailing_Top'] - df['Trailing_Bottom']
    df['Discount_Limit'] = df['Trailing_Bottom'] + rango * 0.35
    df['Premium_Limit'] = df['Trailing_Top'] - rango * 0.35

    long_mem, short_mem, media_buy, media_sell = [], [], [], []
    for i in range(len(df)):
        c, o = df['Close'].iloc[i], df['Open'].iloc[i]
        dl, pl = df['Discount_Limit'].iloc[i], df['Premium_Limit'].iloc[i]
        if c <= dl and c < o and pd.notna(dl):
            long_mem.append(c)
            if len(long_mem) > 10: long_mem.pop(0)
        if c >= pl and c > o and pd.notna(pl):
            short_mem.append(c)
            if len(short_mem) > 10: short_mem.pop(0)
        media_buy.append(np.mean(long_mem) if long_mem else np.nan)
        media_sell.append(np.mean(short_mem) if short_mem else np.nan)
        
    df['MediaBuy'], df['MediaSell'] = media_buy, media_sell

    # Clustering de Regímenes
    df['Returns'] = np.log(df['Close'] / df['Close'].shift(1))
    df['Vol'] = df['Returns'].rolling(96).std()
    df['Mom'] = df['Close'].pct_change(96)
    
    df_temp = df.dropna().copy()
    if len(df_temp) < 10:
        df['Regime'] = 0; kmeans = None
    else:
        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        df.loc[df_temp.index, 'Regime'] = kmeans.fit_predict(df_temp[['Vol', 'Returns', 'Mom']].values)
        df['Regime'] = df['Regime'].ffill().bfill().fillna(0).astype(int)

    df['Regime_Start'] = df['Regime'] != df['Regime'].shift(1)
    df['Regime_End'] = df['Regime'] != df['Regime'].shift(-1)
    
    # ---------------------------------------------------------
    # LÓGICA MODO PRO: Nube Verde y Reversión a la Media
    # ---------------------------------------------------------
    # El grosor de la nube es dictado por el slider de la UI
    df['MediaBuy_Tolerancia'] = df['MediaBuy'] + (df['ATR'] * grosor_nube_atr)
    
    # ENTRADA: Cruce hacia arriba de la MediaBuy (de abajo hacia arriba)
    df['Cruce_MB_Up'] = (df['Close'] > df['MediaBuy']) & (df['Close'].shift(1) <= df['MediaBuy'].shift(1))
    vela_verde = df['Close'] > df['Open']
    
    # Validamos el cruce con el ángulo cinético
    df['Buy_Trigger'] = df['Cruce_MB_Up'] & vela_verde & (df['Angle'] >= angulo_requerido)
    df['Signal'] = np.where(df['Buy_Trigger'], 1, -1)
    
    trades = []
    in_trade = False
    escapo_nube = False
    
    for i in range(1, len(df)):
        if not in_trade and df['Signal'].iloc[i] == 1:
            in_trade = True
            entry_p = df['Close'].iloc[i]
            entry_t = df.index[i]
            escapo_nube = False # Reseteamos el estado de escape
            
        elif in_trade:
            # 1. Monitoreo de Zona de Expansión (El precio sale de la nube por arriba)
            if df['Low'].iloc[i] > df['MediaBuy_Tolerancia'].iloc[i]:
                escapo_nube = True
                
            # 2. STOP LOSS ESTRICTO: Cruce de la MediaBuy hacia abajo
            if df['Close'].iloc[i] < df['MediaBuy'].iloc[i]:
                exit_p = df['Close'].iloc[i]
                tipo_salida = 'TP' if exit_p > entry_p else 'SL'
                trades.append({'Entry_Time': entry_t, 'Entry_Price': entry_p, 'Exit_Time': df.index[i], 'Exit_Price': exit_p, 'Type': tipo_salida})
                in_trade = False
                
            # 3. TAKE PROFIT (Reversión): Toca la nube verde tras haber escapado
            elif escapo_nube and (df['Low'].iloc[i] <= df['MediaBuy_Tolerancia'].iloc[i]):
                exit_p = df['MediaBuy_Tolerancia'].iloc[i] # Ejecuta venta al tocar la frontera de la nube
                trades.append({'Entry_Time': entry_t, 'Entry_Price': entry_p, 'Exit_Time': df.index[i], 'Exit_Price': exit_p, 'Type': 'TP'})
                in_trade = False

    return df, pd.DataFrame(trades), kmeans

# ==========================================
# 4. RENDERIZADO VISUAL Y MÉTRICAS
# ==========================================
df_raw = get_market_data(symbol_actual, cfg_activo["tf"], cfg_activo["dias"])

if not df_raw.empty:
    df_full, trades_df_full, kmeans_model = calcular_estrategia(df_raw.copy(), cfg_activo["angulo"], cfg_activo["sl_mult"])
    
    ultimo_tiempo_vela = df_full.index[-1]
    hist = st.session_state["historial_multi_activo"][symbol_actual]

    if hist["time"] != ultimo_tiempo_vela:
        hist["time"] = ultimo_tiempo_vela
        hist["reg"], hist["mb"], hist["ms"] = False, False, False

    if cfg_activo["alertas"]["regimen"] and df_full['Regime_Start'].iloc[-1] and not hist["reg"]:
        st.toast(f"**{ticker_activo}**: Cambio a Régimen {df_full['Regime'].iloc[-1]}", icon="🔄")
        reproducir_alerta_local("alerta_regimen.mp3"); hist["reg"] = True
        
    # Cruce alcista actualizado a la nueva lógica
    if cfg_activo["alertas"]["cruce_mb"] and df_full['Cruce_MB_Up'].iloc[-1] and not hist["mb"]:
        st.toast(f"**{ticker_activo}**: Cruce ALCISTA", icon="🟢")
        reproducir_alerta_local("alerta_alcista.mp3"); hist["mb"] = True

    fecha_corte = (datetime.utcnow() - pd.Timedelta(hours=5)) - timedelta(days=cfg_activo["dias"])
    df = df_full[df_full.index >= fecha_corte].copy()
    trades_df = trades_df_full[trades_df_full['Entry_Time'] >= fecha_corte].copy() if not trades_df_full.empty else pd.DataFrame()

    last_time, last_price, last_mb, last_ms = df.index[-1], df['Close'].iloc[-1], df['MediaBuy'].iloc[-1], df['MediaSell'].iloc[-1]

    st.subheader(f"Dashboard Modo Pro - {crypto_seleccionada}")
    
    if len(st.session_state["errores"]) > 0:
        with st.expander("🔍 Auditoría de Red", expanded=False):
            for err in st.session_state["errores"]: st.warning(f"[{err['timestamp']}] {err['tipo']} -> {err['detalle']}")
            if st.button("Limpiar Logs"): st.session_state["errores"] = []; st.rerun()

    fig = make_subplots(rows=1, cols=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name=ticker_activo, line=dict(color='gray', width=1)))
    
    # Nube Verde:
    fig.add_trace(go.Scatter(x=df.index, y=df['MediaBuy_Tolerancia'], name='Frontera Nube', line=dict(color='rgba(0,230,118,0.2)', width=0), showlegend=False))
    fig.add_trace(go.Scatter(x=df.index, y=df['MediaBuy'], name='MediaBuy', fill='tonexty', fillcolor='rgba(0,230,118,0.1)', line=dict(color='#00e676', width=2)))
    
    # MediaSell Mantenida por contexto visual
    fig.add_trace(go.Scatter(x=df.index, y=df['MediaSell'], name='MediaSell', line=dict(color='#ff5252', width=2)))
    
    fig.add_annotation(x=last_time, y=last_price, text=f"<b>{last_price:.2f}</b>", showarrow=True, arrowhead=0, ax=40, ay=0, bgcolor="gray", font=dict(color="white", size=11), xanchor="left")

    colores_regimen = ['#00e676', '#2196f3', '#ff9800'] 
    for i in range(3):
        mask_regimen = df['Regime'] == i
        mask_extremos = mask_regimen & (df['Regime_Start'] | df['Regime_End'])
        y_line_transparente = df['Close'].where(mask_regimen, np.nan)
        fig.add_trace(go.Scatter(x=df.index, y=y_line_transparente, mode='lines', name=f'Reg {i} (Path)', line=dict(color=colores_regimen[i], width=2.5), opacity=0.3, showlegend=False))
        fig.add_trace(go.Scatter(x=df.index[mask_extremos], y=df['Close'][mask_extremos], mode='markers', name=f'Reg {i}', marker=dict(color=colores_regimen[i], size=7, line=dict(width=1, color='white'))))

    if not trades_df.empty:
        tp_df, sl_df = trades_df[trades_df['Type'] == 'TP'], trades_df[trades_df['Type'] == 'SL']
        fig.add_trace(go.Scatter(x=trades_df['Entry_Time'], y=trades_df['Entry_Price'] * 0.995, mode='markers', name='Entrada (Cruce Arriba)', marker=dict(symbol='triangle-up', color='#00ff00', size=14)))
        fig.add_trace(go.Scatter(x=tp_df['Exit_Time'] if not tp_df.empty else [None], y=tp_df['Exit_Price'] if not tp_df.empty else [None], mode='markers', name='Take Profit (Retorno a Nube)', marker=dict(symbol='star', color='orange', size=10)))
        fig.add_trace(go.Scatter(x=sl_df['Exit_Time'] if not sl_df.empty else [None], y=sl_df['Exit_Price'] if not sl_df.empty else [None], mode='markers', name='Stop Loss (Cruce Abajo)', marker=dict(symbol='x', color='red', size=10)))

    fig.update_layout(template='plotly_dark', height=500, margin=dict(r=60), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, width='stretch')

    c1, c2, c3 = st.columns(3)
    nuevo_angulo = st.slider("Escudo Cinético (Ángulo de Confirmación)", 0, 85, cfg_activo["angulo"], 5)
    if nuevo_angulo != cfg_activo["angulo"]:
        cfg_activo["angulo"] = nuevo_angulo
        guardar_settings_globales()
        st.rerun()
else:
    st.error("🚨 Ejecución detenida por protección algorítmica.")
