from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim

SOURCE_URL = "https://precodahora.ba.gov.br/"


def geocode_location(address: str) -> tuple[float, float, str] | None:
    """Obtém coordenadas online para um endereço no Brasil.

    Usa o Nominatim/OpenStreetMap com identificação explícita do aplicativo.
    Retorna latitude, longitude e nome formatado; em caso de falha retorna None.
    """
    query = address.strip()
    if not query:
        return None
    if "brasil" not in query.lower() and "bahia" not in query.lower():
        query = f"{query}, Bahia, Brasil"
    try:
        geolocator = Nominatim(user_agent="cesta-bahia-streamlit/0.1")
        location = geolocator.geocode(query, exactly_one=True, timeout=10)
        if not location:
            return None
        return float(location.latitude), float(location.longitude), location.address
    except Exception:
        return None


@dataclass
class SearchConfig:
    latitude: float
    longitude: float
    radius_km: float
    max_age_hours: int
    query: str
    volume: float | None = None
    unidade: str | None = None


def demo_prices() -> pd.DataFrame:
    """Dataset pequeno para o MVP funcionar sem dependência externa."""
    now = datetime.now()
    rows = [
        ("Arroz tipo 1 5 kg", "789100000001", "Mercado Aurora", "Rua das Flores, 120", -12.9718, -38.5011, 27.90, 2.1, 3),
        ("Arroz tipo 1 5 kg", "789100000001", "Supermercado Bahia", "Av. Oceânica, 850", -12.9650, -38.5102, 29.49, 4.0, 7),
        ("Feijão carioca 1 kg", "789100000002", "Mercado Aurora", "Rua das Flores, 120", -12.9718, -38.5011, 7.49, 2.1, 3),
        ("Feijão carioca 1 kg", "789100000002", "Supermercado Bahia", "Av. Oceânica, 850", -12.9650, -38.5102, 6.99, 4.0, 7),
        ("Café em pó 500 g", "789100000003", "Mercado Aurora", "Rua das Flores, 120", -12.9718, -38.5011, 17.90, 2.1, 3),
        ("Café em pó 500 g", "789100000003", "Atacadão Central", "Rua do Comércio, 42", -12.9780, -38.4880, 15.90, 3.8, 12),
        ("Leite integral 1 L", "789100000004", "Mercado Aurora", "Rua das Flores, 120", -12.9718, -38.5011, 5.29, 2.1, 3),
        ("Leite integral 1 L", "789100000004", "Supermercado Bahia", "Av. Oceânica, 850", -12.9650, -38.5102, 4.99, 4.0, 7),
        ("Óleo de soja 900 ml", "789100000005", "Atacadão Central", "Rua do Comércio, 42", -12.9780, -38.4880, 6.49, 3.8, 12),
        ("Óleo de soja 900 ml", "789100000005", "Mercado Aurora", "Rua das Flores, 120", -12.9718, -38.5011, 6.89, 2.1, 3),
        ("Macarrão espaguete 500 g", "789100000006", "Supermercado Bahia", "Av. Oceânica, 850", -12.9650, -38.5102, 3.79, 4.0, 7),
        ("Macarrão espaguete 500 g", "789100000006", "Mercado Aurora", "Rua das Flores, 120", -12.9718, -38.5011, 4.19, 2.1, 3),
    ]
    df = pd.DataFrame(rows, columns=["produto", "gtin", "estabelecimento", "endereco", "latitude", "longitude", "preco", "distancia_km", "idade_horas"])
    df["coletado_em"] = now
    df["data_nf"] = now - df["idade_horas"].map(timedelta)
    df["fonte"] = "Demonstração"
    return df


def collect_public_page(config: SearchConfig, timeout: int = 12) -> tuple[pd.DataFrame, str]:
    """Consulta os endpoints públicos usados pela página e normaliza os resultados reais."""
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; CestaBahia/0.1)", "Accept": "application/json, text/plain, */*"})
        response = session.get(SOURCE_URL, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        token_node = soup.select_one("#validate")
        if not token_node:
            return pd.DataFrame(), "Não foi possível iniciar a sessão da fonte."
        headers = {"X-CSRFToken": token_node.get("data-id", ""), "Referer": SOURCE_URL, "X-Requested-With": "XMLHttpRequest"}
        suggestion = session.post(SOURCE_URL.rstrip("/") + "/sugestao/", data={"item": config.query}, headers=headers, timeout=timeout)
        if suggestion.status_code in (403, 429) or "captcha" in suggestion.text.lower():
            return pd.DataFrame(), "A fonte solicitou verificação humana."
        suggestions = suggestion.json().get("resultado", [])
        if not suggestions:
            return pd.DataFrame(), "Nenhum produto correspondente foi sugerido."
        query_tokens = set(re.findall(r"[a-z0-9]+", normalize_term(config.query)))
        def suggestion_score(item: dict) -> int:
            description_tokens = set(re.findall(r"[a-z0-9]+", normalize_term(str(item.get("descricao", "")))))
            return len(query_tokens & description_tokens)
        ranked = sorted(suggestions, key=suggestion_score, reverse=True)
        selected = ranked[0]
        gtin = str(selected.get("gtin", ""))
        params = {"gtin": gtin, "horas": str(config.max_age_hours), "latitude": str(config.latitude), "longitude": str(config.longitude), "raio": str(config.radius_km), "precomax": "0", "precomin": "0", "ordenar": "preco.asc", "pagina": "1", "processo": "carregar", "totalRegistros": "0", "totalPaginas": "0", "pageview": "lista"}
        prices = session.post(SOURCE_URL.rstrip("/") + "/produtos/", data=params, headers=headers, timeout=timeout)
        if prices.status_code in (403, 429) or "captcha" in prices.text.lower():
            return pd.DataFrame(), "A fonte solicitou verificação humana."
        payload = prices.json()
        rows = []
        for record in payload.get("resultado", []):
            product = record.get("produto", {})
            shop = record.get("estabelecimento", {})
            description = product.get("descricao", config.query)
            product_volume = re.search(r"(\d+(?:[.,]\d+)?)\s*(KG|G|L|ML)\b", str(description).upper())
            same_pack = True
            if config.volume is not None and product_volume:
                found_volume = float(product_volume.group(1).replace(",", "."))
                found_unit = product_volume.group(2).lower()
                same_pack = found_unit == (config.unidade or "").lower() and abs(found_volume - config.volume) < 0.01
            rows.append({"produto": description, "gtin": str(product.get("gtin", gtin)), "estabelecimento": shop.get("nomeEstabelecimento", "Não informado"), "endereco": f"{shop.get('endLogradouro', '')}, {shop.get('endNumero', '')}".strip(", "), "latitude": shop.get("latitude"), "longitude": shop.get("longitude"), "preco": float(product.get("precoLiquido") or product.get("precoUnitario") or 0), "distancia_km": float(shop.get("distancia") or 0), "idade_horas": max(0, int(product.get("timeSpan", 0) / 3600)), "coletado_em": datetime.now(), "data_nf": product.get("data"), "fonte": "Preço da Hora Bahia", "embalagem_compativel": same_pack})
        return pd.DataFrame(rows), f"{len(rows)} preços reais coletados para {selected.get('descricao', config.query)}."
    except requests.RequestException as exc:
        return pd.DataFrame(), f"Fonte indisponível: {exc.__class__.__name__}."
    except (ValueError, KeyError) as exc:
        return pd.DataFrame(), f"Resposta inesperada da fonte: {exc.__class__.__name__}."


def normalize_term(term: str) -> str:
    term = unicodedata.normalize("NFKD", term.lower()).encode("ascii", "ignore").decode()
    term = term.strip()
    term = re.sub(r"\b(kg|quilo|quilos|g|gramas|l|litro|ml)\b", "", term)
    return re.sub(r"\s+", " ", term).strip()


def clean_product_name(name: str) -> str:
    """Remove embalagem e conectivos, preservando o nome pesquisável do produto."""
    value = name.lower().strip()
    value = re.sub(r"\b(latas?|garrafas?|garrafão|pacotes?|caixas?|bandejas?|unidades?|und|litro|litros|quilo|quilos)\b", " ", value)
    value = re.sub(r"\b\d+(?:[.,]\d+)?\s*(kg|quilo|quilos|g|gramas|l|litro|litros|ml|un|unid)\b", " ", value)
    value = re.sub(r"\b(de|do|da|dos|das|com|cada)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip(" ,.-")


def parse_quantity_and_specs(raw: str) -> dict:
    """Extrai quantidade e embalagem sem destruir o texto usado na busca."""
    text = raw.strip().lower()
    qty_match = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*(?:x|unidades?|unid\.?|un\.?|latas?|garrafas?|pacotes?|caixas?)?\s*(.*)", text)
    quantity = float(qty_match.group(1).replace(",", ".")) if qty_match else 1.0
    remainder = qty_match.group(2).strip() if qty_match else text
    spec = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml|un|unid)", remainder)
    volume = float(spec.group(1).replace(",", ".")) if spec else None
    unit = spec.group(2) if spec else None
    if spec is None:
        spelled = re.search(r"(\d+(?:[.,]\d+)?)?\s*(litro|litros|quilo|quilos)", remainder)
        if spelled:
            volume = float((spelled.group(1) or "1").replace(",", "."))
            unit = "l" if spelled.group(2).startswith("litro") else "kg"
    search_name = clean_product_name(remainder)
    return {"nome": search_name, "busca": search_name, "quantidade": quantity, "volume": volume, "unidade": unit, "texto_original": raw.strip()}


def parse_cart(text: str) -> list[dict]:
    """Interpretação determinística para o MVP; aceita separação por vírgula ou linha."""
    cleaned = re.sub(r"\s+", " ", text.replace(";", ",")).strip()
    parts = [p.strip(" .") for p in re.split(r",|\n|\be\b", cleaned, flags=re.I) if p.strip()]
    items = []
    for part in parts:
        item = parse_quantity_and_specs(part)
        if len(item["nome"]) >= 2:
            if item["quantidade"].is_integer():
                item["quantidade"] = int(item["quantidade"])
            items.append(item)
    return items


def resolve_cart_message(text: str, previous_user_message: str | None = None) -> tuple[str, list[dict]]:
    """Resolve referências conversacionais simples antes de consultar a fonte."""
    normalized = text.lower().strip()
    references_previous = any(token in normalized for token in ("cada acima", "os itens acima", "a lista acima", "tudo acima"))
    if references_previous and previous_user_message:
        return previous_user_message, parse_cart(previous_user_message)
    return text, parse_cart(text)


def match_prices(df: pd.DataFrame, items: Iterable[dict], radius_km: float, max_age_hours: int) -> pd.DataFrame:
    if df.empty:
        return df
    names = [normalize_term(i["nome"]) for i in items]
    mask = df["distancia_km"].le(radius_km) & df["idade_horas"].le(max_age_hours)
    product_mask = pd.Series(False, index=df.index)
    for name in names:
        tokens = [t for t in name.split() if len(t) > 2]
        item_mask = df["produto"].str.lower().apply(lambda x: sum(t in x for t in tokens) >= max(1, min(2, len(tokens))))
        product_mask |= item_mask
    return df[mask & product_mask].copy()


def optimize_cart(df: pd.DataFrame, items: list[dict], strategy: str) -> dict:
    if df.empty:
        return {"linhas": pd.DataFrame(), "total": 0.0, "lojas": [], "cobertura": 0, "mensagem": "Nenhum preço encontrado."}
    qty = {normalize_term(i["nome"]): i["quantidade"] for i in items}
    work = df.copy()
    work["chave"] = work["produto"].map(normalize_term)
    # Para cada produto da demonstração, usamos o primeiro candidato correspondente.
    candidates = []
    for item in items:
        key = normalize_term(item["nome"])
        tokens = [t for t in key.split() if len(t) > 2]
        found = work[work["produto"].str.lower().apply(lambda x: sum(t in x for t in tokens) >= max(1, min(2, len(tokens))))]
        if found.empty:
            continue
        found = found.sort_values(["embalagem_compativel", "preco"], ascending=[False, True])
        candidates.append(found.iloc[0].to_dict())
    result = pd.DataFrame(candidates)
    if result.empty:
        return {"linhas": result, "total": 0.0, "lojas": [], "cobertura": 0, "mensagem": "Não foi possível associar os itens."}
    result["quantidade"] = [next((i["quantidade"] for i in items if normalize_term(i["nome"]) in normalize_term(r["produto"])), 1) for r in candidates]
    result["subtotal"] = result["preco"] * result["quantidade"]
    if strategy == "Uma única loja":
        store_totals = result.groupby("estabelecimento")["subtotal"].sum().sort_values()
        store = store_totals.index[0]
        result = result[result["estabelecimento"] == store].copy()
    return {"linhas": result, "total": float(result["subtotal"].sum()), "lojas": result["estabelecimento"].unique().tolist(), "cobertura": len(result), "mensagem": ""}
