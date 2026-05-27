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

warnings.filterwarnings("ignore")

# ==========================================
# 0. PROTOCOLO DE ESTADO Y CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Alpha V6 Quant Dashboard", layout="wide")

if "config" not in st.session_state:
    st.session_state["config"] = {
        "symbol": "BNBUSDT", "tf": "15m", "dias": 1, "angulo": 15, "sl_mult": 1.5,
        "alertas": {"regimen": True, "cruce_mb": True, "cruce_ms": True}
    }
elif "alertas" not in st.session_state["config"]:
    st.session_state["config"]["alertas"] = {"regimen": True, "cruce_mb": True, "cruce_ms": True}

if "errores" not in st.session_state:
    st.session_state["errores"] = []

if "historial_alertas" not in st.session_state:
    st.session_state["historial_alertas"] = {"time": None, "reg": False, "mb": False, "ms": False}

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
# 1. UI: BARRA LATERAL (CONFIGURACIÓN EN VIVO)
# ==========================================
st.sidebar.header("⚙️ Parámetros de Auditoría")

top_20_cryptos = {
    "Bitcoin (BTC)": "BTCUSDT", "Ethereum (ETH)": "ETHUSDT", "Binance Coin (BNB)": "BNBUSDT",
    "Solana (SOL)": "SOLUSDT", "Ripple (XRP)": "XRPUSDT", "Cardano (ADA)": "ADAUSDT",
    "Avalanche (AVAX)": "AVAXUSDT", "Polkadot (DOT)": "DOTUSDT", "Chainlink (LINK)": "LINKUSDT",
    "Polygon (MATIC)": "MATICUSDT", "Litecoin (LTC)": "LTCUSDT", "Bitcoin Cash (BCH)": "BCHUSDT",
    "Cosmos (ATOM)": "ATOMUSDT", "Uniswap (UNI)": "UNIUSDT", "Stellar (XLM)": "XLMUSDT",
    "Ethereum Classic (ETC)": "ETCUSDT", "Near Protocol (NEAR)": "NEARUSDT", 
    "Aptos (APT)": "APTUSDT", "Sui (SUI)": "SUIUSDT", "Internet Computer (ICP)": "ICPUSDT"
}

crypto_seleccionada = st.sidebar.selectbox("Seleccionar Criptomoneda", list(top_20_cryptos.keys()), index=list(top_20_cryptos.values()).index(st.session_state["config"]["symbol"]))

if st.session_state["config"]["symbol"] != top_20_cryptos[crypto_seleccionada]:
    st.session_state["historial_alertas"] = {"time": None, "reg": False, "mb": False, "ms": False}
st.session_state["config"]["symbol"] = top_20_cryptos[crypto_seleccionada]

opciones_tf = {"15 Minutos": "15m", "1 Hora": "1h", "4 Horas": "4h", "1 Día": "1d"}
tf_seleccionado = st.sidebar.selectbox("Temporalidad del Gráfico", list(opciones_tf.keys()), index=list(opciones_tf.values()).index(st.session_state["config"]["tf"]))
st.session_state["config"]["tf"] = opciones_tf[tf_seleccionado]

opciones_dias = {"1 Día": 1, "2 Días": 2, "3 Días": 3, "1 Semana": 7, "1 Mes (30d)": 30, "2 Meses (60d)": 60, "3 Meses (90d)": 90}
dias_seleccionados = st.sidebar.selectbox("Rango de Historial (Visualización)", list(opciones_dias.keys()), index=list(opciones_dias.values()).index(st.session_state["config"]["dias"]))
st.session_state["config"]["dias"] = opciones_dias[dias_seleccionados]

st.session_state["config"]["sl_mult"] = st.sidebar.slider("Multiplicador ATR (Stop Loss)", min_value=0.5, max_value=3.0, value=st.session_state["config"]["sl_mult"], step=0.1)

with st.sidebar.expander("🔔 Panel de Alertas In Situ", expanded=True):
    st.session_state["config"]["alertas"]["regimen"] = st.checkbox("Cambio de Régimen (0/1/2)", value=st.session_state["config"]["alertas"]["regimen"])
    st.session_state["config"]["alertas"]["cruce_mb"] = st.checkbox("Cruce Alcista (Rompe MediaBuy)", value=st.session_state["config"]["alertas"]["cruce_mb"])
    st.session_state["config"]["alertas"]["cruce_ms"] = st.checkbox("Cruce Bajista (Rompe MediaSell)", value=st.session_state["config"]["alertas"]["cruce_ms"])

ticker_activo = st.session_state["config"]["symbol"].replace("USDT", "")

# ==========================================
# 2. INGESTA DE SEÑAL (ENRUTADOR MULTI-EXCHANGE CLOUD)
# ==========================================
@st.cache_data(ttl=300, show_spinner=False) 
def get_market_data(symbol, interval, dias_visuales):
    if verificar_error("BLOQUEO_CATASTROFICO"): return pd.DataFrame()

    buffer_dias = {"15m": 3, "1h": 10, "4h": 40, "1d": 250}.get(interval, 5)
    dias_totales = dias_visuales + buffer_dias
    now = datetime.utcnow()
    start_date = now - timedelta(days=dias_totales)
    current_start = int(start_date.timestamp() * 1000)
    end_time_ms = int(now.timestamp() * 1000)
    
    motores = [
        ("BINANCE_GLOBAL", "api.binance.com"),
        ("BINANCE_US", "api.binance.us"), 
        ("MEXC_OFFSHORE", "api.mexc.com") 
    ]
    
    df_list = []
    
    for nombre_motor, dominio in motores:
        df_list_temp = []
        temp_start = current_start
        exito_motor = True
        
        while temp_start < end_time_ms:
            url = f"https://{dominio}/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000&startTime={temp_start}"
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 QuantAlpha/7.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                
                if not data: break
                
                df_temp = pd.DataFrame(data, columns=['Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_time', 'Quote_asset_volume', 'Trades', 'Taker_buy_base', 'Taker_buy_quote', 'Ignore'])
                df_list_temp.append(df_temp[['Open_time', 'Open', 'High', 'Low', 'Close', 'Volume']])
                temp_start = int(df_temp['Close_time'].iloc[-1]) + 1
            except Exception as e:
                exito_motor = False
                break
                
        if exito_motor and df_list_temp:
            df_list = df_list_temp
            if nombre_motor != "BINANCE_GLOBAL":
                registrar_error("INFO_FAILOVER", f"Conectado a través de {nombre_motor} (evasión de IP exitosa)")
            break
            
    if not df_list: 
        registrar_error("BLOQUEO_CATASTROFICO", "Todos los motores de liquidez rechazaron la conexión IP.")
        st.cache_data.clear()
        return pd.DataFrame()
    
    df = pd.concat(df_list, ignore_index=True)
    df.drop_duplicates(subset=['Open_time'], inplace=True)
    df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric)
    df['Date'] = pd.to_datetime(df['Open_time'], unit='ms') - pd.Timedelta(hours=5)
    df.set_index('Date', inplace=True)
    return df

# ==========================================
# 3. MOTOR CUANTITATIVO 
# ==========================================
def calcular_estrategia(df, angulo_requerido, sl_mult):
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

    df['VolumenPromedio'] = df['Volume'].rolling(20).mean()
    df['VolumenFuerte'] = df['Volume'] > df['VolumenPromedio']
    df['CruceDetectado'] = (df['Close'] < df['MediaSell']) & (df['Close'].shift(1) >= df['MediaSell'].shift(1))
    df['SellCondition'] = df['yhat1'] < df['yhat1'].shift(1)
    
    vela_verde = df['Close'] > df['Open']
    toque_zona = (df['Low'] <= df['MediaBuy']) | (df['Low'].shift(1) <= df['MediaBuy'].shift(1))
    df['Buy_Trigger'] = toque_zona & vela_verde & (df['Close'] > df['MediaBuy']) & (df['yhat1'] > df['yhat1'].shift(1)) & (df['Angle'] >= angulo_requerido)
    df['Cruce_MB_Alcista'] = (df['Close'].shift(1) <= df['MediaBuy'].shift(1)) & (df['Close'] > df['MediaBuy'])
    df['Cruce_MS_Bajista'] = (df['Close'].shift(1) >= df['MediaSell'].shift(1)) & (df['Close'] < df['MediaSell'])
    df['Signal'] = np.where(df['Buy_Trigger'], 1, -1)
    
    trades = []
    in_trade, entry_p, sl_price, cruce_latch = False, 0, 0, False 
    
    for i in range(1, len(df)):
        if df['CruceDetectado'].iloc[i]: cruce_latch = True

        if not in_trade and df['Signal'].iloc[i] == 1:
            in_trade, entry_p, sl_price, cruce_latch = True, df['Close'].iloc[i], df['Close'].iloc[i] - (df['ATR'].iloc[i] * sl_mult), False 
            entry_t = df.index[i]
        elif in_trade:
            umbral_premium = df['MediaBuy'].iloc[i] + ((df['MediaSell'].iloc[i] - df['MediaBuy'].iloc[i]) * 0.7)
            confirmacion_sell = (df['SellCondition'].iloc[i] and pd.notna(df['MediaSell'].iloc[i]) and 
                                 (df['Close'].iloc[i] > umbral_premium) and (cruce_latch or (df['Close'].iloc[i] < df['MediaSell'].iloc[i])) and df['VolumenFuerte'].iloc[i])
            hit_tp_azul = ((df['Regime'].iloc[i] == 1) and (df['High'].iloc[i] >= df['MediaSell'].iloc[i]) and (df['Close'].iloc[i] < df['Close'].iloc[i-1]))
            
            if df['Low'].iloc[i] <= sl_price:
                trades.append({'Entry_Time': entry_t, 'Entry_Price': entry_p, 'Exit_Time': df.index[i], 'Exit_Price': sl_price, 'Type': 'SL'}); in_trade = False
            elif confirmacion_sell:
                trades.append({'Entry_Time': entry_t, 'Entry_Price': entry_p, 'Exit_Time': df.index[i], 'Exit_Price': df['Close'].iloc[i], 'Type': 'Sell_Logic'}); in_trade = False
            elif hit_tp_azul:
                trades.append({'Entry_Time': entry_t, 'Entry_Price': entry_p, 'Exit_Time': df.index[i], 'Exit_Price': min(df['Close'].iloc[i], df['MediaSell'].iloc[i]), 'Type': 'TP'}); in_trade = False

    return df, pd.DataFrame(trades), kmeans

# ==========================================
# 4. RENDERIZADO VISUAL Y MÉTRICAS
# ==========================================
df_raw = get_market_data(st.session_state["config"]["symbol"], st.session_state["config"]["tf"], st.session_state["config"]["dias"])

if not df_raw.empty:
    df_full, trades_df_full, kmeans_model = calcular_estrategia(df_raw.copy(), st.session_state["config"]["angulo"], st.session_state["config"]["sl_mult"])
    
    ultimo_tiempo_vela = df_full.index[-1]
    cfg_alertas = st.session_state["config"]["alertas"]
    hist = st.session_state["historial_alertas"]

    if hist["time"] != ultimo_tiempo_vela:
        hist["time"] = ultimo_tiempo_vela; hist["reg"] = False; hist["mb"] = False; hist["ms"] = False

    if cfg_alertas["regimen"] and df_full['Regime_Start'].iloc[-1] and not hist["reg"]:
        st.toast(f"**{ticker_activo}**: Cambio a Régimen {df_full['Regime'].iloc[-1]}", icon="🔄")
        reproducir_alerta_local("alerta_regimen.mp3"); hist["reg"] = True
        
    if cfg_alertas["cruce_mb"] and df_full['Cruce_MB_Alcista'].iloc[-1] and not hist["mb"]:
        st.toast(f"**{ticker_activo}**: Cruce ALCISTA sobre MediaBuy", icon="🟢")
        reproducir_alerta_local("alerta_alcista.mp3"); hist["mb"] = True
        
    if cfg_alertas["cruce_ms"] and df_full['Cruce_MS_Bajista'].iloc[-1] and not hist["ms"]:
        st.toast(f"**{ticker_activo}**: Cruce BAJISTA bajo MediaSell", icon="🔴")
        reproducir_alerta_local("alerta_bajista.mp3"); hist["ms"] = True

    fecha_corte = (datetime.utcnow() - pd.Timedelta(hours=5)) - timedelta(days=st.session_state["config"]["dias"])
    df = df_full[df_full.index >= fecha_corte].copy()
    trades_df = trades_df_full[trades_df_full['Entry_Time'] >= fecha_corte].copy() if not trades_df_full.empty else pd.DataFrame()

    last_time, last_price, last_mb, last_ms = df.index[-1], df['Close'].iloc[-1], df['MediaBuy'].iloc[-1], df['MediaSell'].iloc[-1]

    st.subheader(f"Simulador Alpha V6 - {crypto_seleccionada} ({tf_seleccionado})")
    
    if len(st.session_state["errores"]) > 0:
        with st.expander("🔍 Registro de Ruteo de Conexión (Logs)", expanded=False):
            for err in st.session_state["errores"]:
                st.info(f"[{err['timestamp']}] {err['tipo']} -> {err['detalle']}")
            if st.button("Limpiar Logs"):
                st.session_state["errores"] = []; st.rerun()

    fig = make_subplots(rows=1, cols=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name=ticker_activo, line=dict(color='gray', width=1)))
    fig.add_trace(go.Scatter(x=df.index, y=df['MediaBuy'], name='MediaBuy', line=dict(color='#00e676', width=2)))
    fig.add_trace(go.Scatter(x=df.index, y=df['MediaSell'], name='MediaSell', line=dict(color='#ff5252', width=2)))

    fig.add_annotation(x=last_time, y=last_price, text=f"<b>{last_price:.2f}</b>", showarrow=True, arrowhead=0, ax=40, ay=0, bgcolor="gray", font=dict(color="white", size=11), xanchor="left")
    if pd.notna(last_mb): fig.add_annotation(x=last_time, y=last_mb, text=f"<b>{last_mb:.2f}</b>", showarrow=True, arrowhead=0, ax=40, ay=0, bgcolor="#00e676", font=dict(color="black", size=11), xanchor="left")
    if pd.notna(last_ms): fig.add_annotation(x=last_time, y=last_ms, text=f"<b>{last_ms:.2f}</b>", showarrow=True, arrowhead=0, ax=40, ay=0, bgcolor="#ff5252", font=dict(color="white", size=11), xanchor="left")

    colores_regimen = ['#00e676', '#2196f3', '#ff9800'] 
    for i in range(3):
        mask_regimen = df['Regime'] == i
        mask_extremos = mask_regimen & (df['Regime_Start'] | df['Regime_End'])
        y_line_transparente = df['Close'].where(mask_regimen, np.nan)
        fig.add_trace(go.Scatter(x=df.index, y=y_line_transparente, mode='lines', name=f'Reg {i} (Path)', line=dict(color=colores_regimen[i], width=2.5), opacity=0.3, showlegend=False))
        fig.add_trace(go.Scatter(x=df.index[mask_extremos], y=df['Close'][mask_extremos], mode='markers', name=f'Reg {i}', marker=dict(color=colores_regimen[i], size=7, line=dict(width=1, color='white'))))

    if not trades_df.empty:
        tp_df, sl_df, sell_logic_df = trades_df[trades_df['Type'] == 'TP'], trades_df[trades_df['Type'] == 'SL'], trades_df[trades_df['Type'] == 'Sell_Logic']
        fig.add_trace(go.Scatter(x=trades_df['Entry_Time'], y=trades_df['Entry_Price'] * 0.995, mode='markers', name='Entrada A+', marker=dict(symbol='triangle-up', color='#00ff00', size=14)))
        fig.add_trace(go.Scatter(x=tp_df['Exit_Time'] if not tp_df.empty else [None], y=tp_df['Exit_Price'] if not tp_df.empty else [None], mode='markers', name='Take Profit', marker=dict(symbol='star', color='orange', size=10)))
        fig.add_trace(go.Scatter(x=sell_logic_df['Exit_Time'] if not sell_logic_df.empty else [None], y=sell_logic_df['Exit_Price'] if not sell_logic_df.empty else [None], mode='markers', name='Salida (Vol+Cruce)', marker=dict(symbol='diamond', color='#9c27b0', size=12, line=dict(width=1, color='white'))))
        fig.add_trace(go.Scatter(x=sl_df['Exit_Time'] if not sl_df.empty else [None], y=sl_df['Exit_Price'] if not sl_df.empty else [None], mode='markers', name='Stop Loss Dinámico', marker=dict(symbol='x', color='red', size=10)))

    fig.update_layout(template='plotly_dark', height=500, margin=dict(r=60), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, width='stretch')

    st.markdown("---")
    col_pie, col_macro = st.columns([1, 2])
    
    with col_pie:
        st.markdown("<h4 style='text-align: center;'>Régimen de Mercado</h4>", unsafe_allow_html=True)
        regime_counts = df['Regime'].value_counts().sort_index()
        fig_pie = go.Figure(data=[go.Pie(labels=[f'Reg {i}' for i in regime_counts.index], values=regime_counts.values, hole=0.4, marker=dict(colors=colores_regimen))])
        fig_pie.update_layout(template='plotly_dark', height=350, margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig_pie, width='stretch')

    with col_macro:
        st.markdown("<h4 style='text-align: center; background-color: #d3d3d3; color: #333; border-radius: 5px; padding: 5px;'>Distribución de Variables Macro</h4>", unsafe_allow_html=True)
        if kmeans_model is not None:
            centers = kmeans_model.cluster_centers_
            z_normalized = np.interp(centers, (centers.min(), centers.max()), (0.1, 0.9))
            fig_hm = go.Figure(data=go.Heatmap(z=z_normalized, x=['Vol', 'Ret', 'Mom'], y=['R0', 'R1', 'R2'], colorscale='Turbo', showscale=False))
            fig_hm.update_layout(template='plotly_white', height=250, margin=dict(t=10, b=30, l=50, r=10))
            st.plotly_chart(fig_hm, width='stretch')
        else:
            st.info("Datos insuficientes para K-Means.")

        estado_actual = "Entrada Confirmada" if df['Buy_Trigger'].iloc[-1] else "Esperando Gatillo"
        c1, c2, c3 = st.columns(3)
        precision = ".4f" if last_price < 5 else ".2f"
        
        c1.metric(f"{ticker_activo}/USDT (Actual)", f"${last_price:{precision}}")
        c2.metric("MediaBuy (Soporte)", f"${last_mb:{precision}}" if pd.notna(last_mb) else "N/A")
        c3.metric("Estado de Señal", estado_actual)

        st.markdown("<br>", unsafe_allow_html=True)
        nuevo_angulo = st.slider("Sensibilidad del Escudo Cinético (Ángulo)", min_value=0, max_value=85, value=st.session_state["config"]["angulo"], step=5, key="slider_inferior")
        if nuevo_angulo != st.session_state["config"]["angulo"]:
            st.session_state["config"]["angulo"] = nuevo_angulo
            st.rerun()

else:
    st.error("🚨 Error crítico: Conexión rechazada por los 3 motores (Binance, Binance US y MEXC).")
    if st.button("🔄 Reintentar Conexión"):
        st.session_state["errores"] = []
        get_market_data.clear() 
        st.rerun()
