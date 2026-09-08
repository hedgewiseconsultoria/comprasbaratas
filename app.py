from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from precodahora import SearchConfig, collect_public_page, demo_prices, geocode_location, match_prices, optimize_cart, parse_cart

st.set_page_config(page_title="Cesta Bahia", page_icon="🛒", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@600;700&display=swap');
:root { --ink:#18251f; --muted:#68756e; --green:#147a58; --mint:#e7f4ec; --cream:#fbfaf6; --line:#e0e8e1; }
.stApp { background:var(--cream); color:var(--ink); font-family:'DM Sans',sans-serif; }
.block-container { max-width:1220px; padding:1.6rem 2rem 4rem; }
[data-testid="stSidebar"] { background:#143b2c; }
[data-testid="stSidebar"] * { color:#f4fbf6 !important; }
.brand { display:flex; align-items:center; gap:12px; margin-bottom:24px; }
.logo { width:42px;height:42px;border-radius:14px;background:#f3c969;color:#143b2c;display:flex;align-items:center;justify-content:center;font-size:22px; }
.brand-title { font-size:21px;font-weight:700;line-height:1; }
.brand-sub { color:#b9d6c6;font-size:11px;margin-top:4px; }
.hero { background:linear-gradient(120deg,#143b2c 0%,#1d684c 70%,#2e8d64 100%); border-radius:25px;padding:35px 40px;color:#fff;position:relative;overflow:hidden;margin-bottom:24px; }
.hero:after { content:'✦'; position:absolute;right:55px;top:18px;font-size:160px;color:rgba(255,255,255,.05); }
.kicker { color:#b8e5c7;text-transform:uppercase;letter-spacing:2px;font-size:11px;font-weight:700; }
.hero h1 { font-family:'Playfair Display',serif;font-size:42px;line-height:1.05;margin:12px 0 10px;max-width:650px; }
.hero p { color:#d5eee0;max-width:650px;font-size:16px;margin:0; }
.card { background:#fff;border:1px solid var(--line);border-radius:18px;padding:20px 22px;box-shadow:0 8px 25px rgba(26,64,43,.05); }
.card h3 { margin:0 0 8px;font-size:18px; }
.eyebrow { color:var(--muted);text-transform:uppercase;letter-spacing:1.4px;font-size:10px;font-weight:700; }
.metric { font-size:28px;font-weight:700;color:var(--green);margin-top:4px; }
.chatbox { background:#fff;border:1px solid var(--line);border-radius:20px;padding:18px; }
.bubble-user { background:#e7f4ec;border-radius:17px 17px 3px 17px;padding:13px 16px;margin:8px 0 8px 16%; }
.bubble-bot { background:#f3f6f2;border-radius:17px 17px 17px 3px;padding:13px 16px;margin:8px 16% 8px 0; }
.pill { display:inline-block;background:#edf7f0;color:#176b4c;border-radius:99px;padding:5px 10px;margin:3px;font-size:12px;font-weight:600; }
.small-note { color:var(--muted);font-size:12px; }
div[data-testid="stMetric"] { background:#fff;border:1px solid var(--line);border-radius:15px;padding:12px 16px; }
.stButton>button { border-radius:12px;border:0;background:#147a58;color:#fff;font-weight:600; }
.stButton>button:hover { background:#0d6045;color:#fff; }
</style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role":"assistant", "content":"Olá! Eu monto sua cesta comparando preço, distância e número de paradas. O que você precisa comprar?"}]
if "last_result" not in st.session_state:
    st.session_state.last_result = None

with st.sidebar:
    st.markdown('<div class="brand"><div class="logo">🛒</div><div><div class="brand-title">Cesta Bahia</div><div class="brand-sub">compras inteligentes</div></div></div>', unsafe_allow_html=True)
    st.markdown("### Preferências")
    radius = st.slider("Raio de busca (km)", 1, 30, 8)
    max_age = st.slider("Preço emitido há até (horas)", 1, 72, 24)
    strategy = st.selectbox("Como você quer comprar?", ["Equilibrada", "Menor preço por item", "Uma única loja"])
    st.divider()
    st.markdown("**Local de referência**")
    address = st.text_input("Endereço ou CEP", "Pituba, Salvador - BA", help="A localização é pesquisada online no OpenStreetMap/Nominatim.")
    if st.button("Buscar localização online", use_container_width=True):
        with st.spinner("Localizando endereço..."):
            found = geocode_location(address)
        if found:
            st.session_state.location = found
            st.success(f"Local encontrado: {found[2]}")
        else:
            st.error("Não encontrei esse endereço. Tente informar rua, bairro, cidade e estado.")
    default_location = st.session_state.get("location", (-12.9714, -38.5014, "Salvador - BA"))
    lat, lon = default_location[0], default_location[1]
    st.caption(f"Coordenadas usadas: {lat:.5f}, {lon:.5f}")
    st.divider()
    st.markdown("<span class='small-note'>Fonte: Preço da Hora Bahia · modo de demonstração disponível</span>", unsafe_allow_html=True)

st.markdown('<div class="hero"><div class="kicker">assistente de compras da Bahia</div><h1>Sua lista. O melhor caminho para economizar.</h1><p>Escreva sua cesta como falaria com uma pessoa. Nós organizamos os itens e comparamos as melhores combinações por perto.</p></div>', unsafe_allow_html=True)

left, right = st.columns([1.35, 1], gap="large")
with left:
    st.markdown('<div class="card"><div class="eyebrow">Converse com seu assistente</div><h3>O que vai na sua cesta?</h3>', unsafe_allow_html=True)
    for msg in st.session_state.messages[-6:]:
        css = "bubble-user" if msg["role"] == "user" else "bubble-bot"
        label = "Você" if msg["role"] == "user" else "Cesta Bahia"
        st.markdown(f'<div class="{css}"><b>{label}</b><br>{html.escape(msg["content"])}</div>', unsafe_allow_html=True)
    prompt = st.chat_input("Ex.: arroz 5 kg, feijão, café e leite para a semana")
    st.markdown('</div>', unsafe_allow_html=True)
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        items = parse_cart(prompt)
        if not items:
            reply = "Não consegui identificar produtos. Tente separar os itens por vírgulas, por exemplo: arroz 5 kg, feijão 1 kg e café 500 g."
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()
        with st.spinner("Consultando preços e montando combinações..."):
            live_parts = []
            source_messages = []
            for item in items:
                config = SearchConfig(lat, lon, radius, max_age, item["nome"])
                live_item, source_message = collect_public_page(config)
                source_messages.append(source_message)
                if not live_item.empty:
                    live_parts.append(live_item)
            live = pd.concat(live_parts, ignore_index=True) if live_parts else pd.DataFrame()
            using_demo = live.empty
            prices = demo_prices() if using_demo else live
            filtered = match_prices(prices, items, radius, max_age)
            result_strategy = "Menor preço por item" if strategy == "Menor preço por item" else strategy
            result = optimize_cart(filtered, items, result_strategy)
            result["items"] = items
            result["using_demo"] = using_demo
            result["source_message"] = " ".join(source_messages)
            st.session_state.last_result = result
        names = ", ".join(i["nome"] for i in items)
        mode = "dados de demonstração" if using_demo else "dados coletados"
        reply = f"Encontrei {len(items)} itens ({names}). Preparei uma recomendação usando {mode}, em até {radius} km, priorizando {strategy.lower()}."
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

with right:
    st.markdown('<div class="card"><div class="eyebrow">Comece em segundos</div><h3>Experimente uma cesta</h3><p class="small-note">Clique em uma sugestão para preencher o chat.</p>', unsafe_allow_html=True)
    suggestions = ["Arroz 5 kg, feijão 1 kg, café 500 g", "Leite, pão, ovos e queijo", "Macarrão, óleo, arroz e feijão"]
    for suggestion in suggestions:
        if st.button(suggestion, use_container_width=True, key=suggestion):
            st.session_state.messages.append({"role": "user", "content": suggestion})
            st.rerun()
    st.markdown('<hr><div class="eyebrow">Como funciona</div><p class="small-note">1. Você escreve a lista<br>2. O motor identifica os produtos<br>3. A busca compara preços próximos<br>4. A recomendação mostra o melhor equilíbrio</p></div>', unsafe_allow_html=True)

result = st.session_state.last_result
if result:
    st.markdown("## Sua recomendação")
    if result["using_demo"]:
        st.info("A fonte pública usa uma consulta dinâmica. Este resultado está no modo demonstração para o app funcionar no Streamlit Cloud; o adaptador de coleta está preparado em `precodahora.py`.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total estimado", f"R$ {result['total']:.2f}".replace('.', ','))
    m2.metric("Itens encontrados", f"{result['cobertura']}/{len(result['items'])}")
    m3.metric("Estabelecimentos", len(result["lojas"]))
    m4.metric("Raio aplicado", f"{radius} km")
    tab1, tab2 = st.tabs(["Detalhamento", "Mapa de opções"])
    with tab1:
        lines = result["linhas"]
        if not lines.empty:
            display = lines[["produto", "quantidade", "preco", "subtotal", "estabelecimento", "distancia_km", "idade_horas"]].copy()
            display.columns = ["Produto", "Qtd.", "Preço unit.", "Subtotal", "Estabelecimento", "Distância (km)", "Idade do preço (h)"]
            st.dataframe(display.style.format({"Preço unit.": "R$ {:.2f}", "Subtotal": "R$ {:.2f}", "Distância (km)": "{:.1f}"}), use_container_width=True, hide_index=True)
            st.caption(f"Coleta realizada em {datetime.now().strftime('%d/%m/%Y às %H:%M')}. Valores são estimativas baseadas nos registros disponíveis.")
        else:
            st.warning(result["mensagem"])
    with tab2:
        lines = result["linhas"]
        if not lines.empty:
            st.map(lines.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]], zoom=12)
            st.dataframe(lines[["estabelecimento", "endereco", "distancia_km"]].drop_duplicates().rename(columns={"estabelecimento":"Estabelecimento", "endereco":"Endereço", "distancia_km":"Distância (km)"}).style.format({"Distância (km)": "{:.1f}"}), use_container_width=True, hide_index=True)
        else:
            st.caption("O mapa aparecerá quando houver resultados.")

st.markdown('<div style="text-align:center;color:#87968d;font-size:12px;margin-top:42px">Cesta Bahia · protótipo Streamlit · preços sujeitos a atualização e disponibilidade no estabelecimento</div>', unsafe_allow_html=True)

