#!/usr/bin/env python3
"""
Busca leads no OpenStreetMap sem chave de API.

Fonte dos dados: OpenStreetMap via Nominatim e Overpass API. Os dados podem ter
menos telefones/sites que o Google Maps, mas nao exigem Google Cloud.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lead_finder import build_whatsapp_link


# Nominatim acha a cidade/regiao e devolve a area aproximada dela.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Overpass consulta empresas/pontos dentro da area encontrada pelo Nominatim.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# O OpenStreetMap pede User-Agent identificando o app. Pode sobrescrever no .env.
USER_AGENT = os.getenv(
    "OSM_USER_AGENT",
    "LeadFinderSites/1.0 (prospecting tool; configure OSM_USER_AGENT in .env)",
)

# Colunas geradas no CSV. Mantive o formato parecido com lead_finder.py.
CSV_FIELDS = [
    "searched_query",
    "source",
    "name",
    "phone",
    "website",
    "address",
    "maps_url",
    "business_status",
    "rating",
    "review_count",
    "primary_type",
    "opportunity_score",
    "prospect_reason",
    "whatsapp_link",
    "place_id",
]

# Traduz nomes amigaveis para tags usadas no OpenStreetMap.
# Exemplo: "lojas" vira shop=*, que pega qualquer tipo de loja.
CATEGORY_TAGS: dict[str, list[tuple[str, str]]] = {
    "academias": [("leisure", "fitness_centre"), ("sport", "fitness")],
    "barbearias": [("shop", "hairdresser")],
    "cabeleireiros": [("shop", "hairdresser")],
    "cafes": [("amenity", "cafe")],
    "clinicas": [("amenity", "clinic"), ("healthcare", "clinic")],
    "clinicas de estetica": [("shop", "beauty"), ("amenity", "beauty")],
    "dentistas": [("amenity", "dentist"), ("healthcare", "dentist")],
    "escolas": [("amenity", "school")],
    "estetica": [("shop", "beauty"), ("amenity", "beauty")],
    "farmacias": [("amenity", "pharmacy")],
    "floriculturas": [("shop", "florist")],
    "imobiliarias": [("office", "estate_agent")],
    "comercio": [("shop", "*")],
    "comercios": [("shop", "*")],
    "lojas": [("shop", "*")],
    "lojas em geral": [("shop", "*")],
    "lojas de moveis": [("shop", "furniture")],
    "oficinas": [("shop", "car_repair")],
    "oficinas mecanicas": [("shop", "car_repair")],
    "oticas": [("shop", "optician")],
    "padarias": [("shop", "bakery")],
    "pet shops": [("shop", "pet")],
    "pizzarias": [("amenity", "restaurant"), ("cuisine", "pizza")],
    "restaurantes": [("amenity", "restaurant")],
    "saloes": [("shop", "hairdresser"), ("shop", "beauty")],
    "supermercados": [("shop", "supermarket")],
}


@dataclass
class OsmLead:
    """Representa um lead vindo do OpenStreetMap ja pronto para CSV."""

    searched_query: str
    name: str
    phone: str
    website: str
    address: str
    maps_url: str
    primary_type: str
    opportunity_score: int
    prospect_reason: str
    whatsapp_link: str
    place_id: str

    def as_row(self) -> dict[str, Any]:
        """Converte o lead para uma linha do CSV."""
        return {
            "searched_query": self.searched_query,
            "source": "openstreetmap",
            "name": self.name,
            "phone": self.phone,
            "website": self.website,
            "address": self.address,
            "maps_url": self.maps_url,
            "business_status": "",
            "rating": "",
            "review_count": "",
            "primary_type": self.primary_type,
            "opportunity_score": self.opportunity_score,
            "prospect_reason": self.prospect_reason,
            "whatsapp_link": self.whatsapp_link,
            "place_id": self.place_id,
        }


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carrega variaveis do .env, como OSM_USER_AGENT se voce quiser definir."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        # Aceita somente linhas simples KEY=VALUE e ignora comentarios.
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request_json(url: str, params: dict[str, str], timeout: int = 40) -> Any:
    """Faz uma requisicao GET e devolve o JSON decodificado."""
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexao: {exc}") from exc


def post_overpass(query: str, timeout: int = 90) -> dict[str, Any]:
    """Envia uma consulta Overpass QL e devolve o resultado JSON."""
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        OVERPASS_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro HTTP {exc.code} no Overpass: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexao com Overpass: {exc}") from exc


def geocode(where: str) -> tuple[float, float, float, float]:
    """Transforma 'Campinas SP' em uma caixa geografica para buscar dentro."""
    data = request_json(
        NOMINATIM_URL,
        {
            "q": where,
            "format": "jsonv2",
            "limit": "1",
            "addressdetails": "0",
        },
    )
    if not data:
        raise RuntimeError(f"Nao encontrei a cidade/regiao: {where}")

    south, north, west, east = [float(value) for value in data[0]["boundingbox"]]
    return south, west, north, east


def normalize_text(value: str) -> str:
    """Padroniza texto para comparar categorias sem se preocupar com espacos."""
    return re.sub(r"\s+", " ", value.strip().lower())


def parse_query(query: str) -> tuple[str, str]:
    """Separa uma busca no formato 'categoria em cidade'."""
    match = re.search(r"\s+em\s+", query, flags=re.IGNORECASE)
    if not match:
        raise ValueError(
            'Use --what e --where, ou uma busca no formato "barbearias em Campinas SP".'
        )
    return query[: match.start()].strip(), query[match.end() :].strip()


def tags_for(what: str, custom_tags: list[str]) -> list[tuple[str, str]]:
    """Escolhe quais tags OSM usar para a categoria solicitada."""
    tags: list[tuple[str, str]] = []

    # --tag permite forcar uma tag OSM manual, por exemplo shop=clothes.
    for custom_tag in custom_tags:
        if "=" not in custom_tag:
            raise ValueError(f"Tag invalida: {custom_tag}. Use formato chave=valor.")
        key, value = custom_tag.split("=", 1)
        tags.append((key.strip(), value.strip()))

    if tags:
        return tags

    normalized = normalize_text(what)
    # Primeiro tenta bater a categoria exata cadastrada no dicionario.
    if normalized in CATEGORY_TAGS:
        return CATEGORY_TAGS[normalized]

    # Depois tenta uma categoria contida no texto, tipo "lojas pequenas".
    partial_matches = [
        tag
        for category, category_tags in CATEGORY_TAGS.items()
        if category in normalized
        for tag in category_tags
    ]
    if partial_matches:
        return partial_matches

    # Ultimo recurso: busca pelo nome/texto como tag name.
    return [("name", what)]


def overpass_filter(key: str, value: str, bbox: tuple[float, float, float, float]) -> str:
    """Monta o trecho da consulta para nodes/ways/relations dentro da area."""
    south, west, north, east = bbox
    bbox_text = f"({south},{west},{north},{east})"
    if value == "*":
        # shop=* significa qualquer elemento que tenha a tag shop.
        tag_filter = f'["{key}"]'
    else:
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        tag_filter = f'["{key}"="{escaped_value}"]'

    return "\n".join(
        [
            f"node{tag_filter}{bbox_text};",
            f"way{tag_filter}{bbox_text};",
            f"relation{tag_filter}{bbox_text};",
        ]
    )


def build_overpass_query(tags: list[tuple[str, str]], bbox: tuple[float, float, float, float]) -> str:
    """Monta a consulta completa usada pelo Overpass API."""
    filters = "\n".join(overpass_filter(key, value, bbox) for key, value in tags)
    return f"""
[out:json][timeout:60];
(
{filters}
);
out center tags;
"""


def first_tag(tags: dict[str, str], names: list[str]) -> str:
    """Retorna o primeiro valor encontrado entre varias tags possiveis."""
    for name in names:
        value = tags.get(name)
        if value:
            return value
    return ""


def address_from_tags(tags: dict[str, str]) -> str:
    """Monta um endereco legivel usando as tags de endereco disponiveis."""
    street = first_tag(tags, ["addr:street"])
    number = first_tag(tags, ["addr:housenumber"])
    suburb = first_tag(tags, ["addr:suburb", "addr:neighbourhood"])
    city = first_tag(tags, ["addr:city", "addr:town", "addr:municipality"])
    state = first_tag(tags, ["addr:state"])

    parts = []
    if street and number:
        parts.append(f"{street}, {number}")
    elif street:
        parts.append(street)
    for value in [suburb, city, state]:
        if value and value not in parts:
            parts.append(value)
    return " - ".join(parts)


def element_url(element: dict[str, Any]) -> str:
    """Cria um link do OpenStreetMap apontando para o elemento encontrado."""
    element_type = element.get("type", "node")
    element_id = element.get("id", "")
    lat = element.get("lat") or element.get("center", {}).get("lat")
    lon = element.get("lon") or element.get("center", {}).get("lon")

    if lat and lon:
        return f"https://www.openstreetmap.org/{element_type}/{element_id}#map=19/{lat}/{lon}"
    return f"https://www.openstreetmap.org/{element_type}/{element_id}"


def primary_type(tags: dict[str, str]) -> str:
    """Mostra a categoria principal do lead, como shop=bakery."""
    for key in ["shop", "amenity", "office", "craft", "leisure", "tourism"]:
        if tags.get(key):
            return f"{key}={tags[key]}"
    return ""


def score(tags: dict[str, str]) -> tuple[int, str]:
    """Da prioridade para quem nao tem site e tem telefone para contato."""
    website = first_tag(tags, ["website", "contact:website", "url"])
    phone = first_tag(tags, ["phone", "contact:phone", "mobile", "contact:mobile"])

    value = 40
    reasons: list[str] = []

    # Sem site aumenta a chance de ser um bom prospect para criacao de site.
    if not website:
        value += 35
        reasons.append("sem site no OpenStreetMap")
    else:
        reasons.append("tem site cadastrado")

    if phone:
        value += 25
        reasons.append("tem telefone para contato")
    else:
        reasons.append("sem telefone cadastrado")

    return min(value, 100), "; ".join(reasons)


def element_to_lead(
    element: dict[str, Any], searched_query: str, message: str
) -> OsmLead | None:
    """Converte um elemento bruto do OSM em lead; ignora itens sem nome."""
    tags = element.get("tags") or {}
    name = first_tag(tags, ["name", "brand", "operator"])
    if not name:
        return None

    phone = first_tag(tags, ["phone", "contact:phone", "mobile", "contact:mobile"])
    website = first_tag(tags, ["website", "contact:website", "url"])
    lead_score, reason = score(tags)
    place_id = f"osm:{element.get('type')}:{element.get('id')}"

    return OsmLead(
        searched_query=searched_query,
        name=name,
        phone=phone,
        website=website,
        address=address_from_tags(tags),
        maps_url=element_url(element),
        primary_type=primary_type(tags),
        opportunity_score=lead_score,
        prospect_reason=reason,
        whatsapp_link=build_whatsapp_link(phone, message),
        place_id=place_id,
    )


def export_csv(path: Path, leads: list[OsmLead]) -> None:
    """Grava o CSV final em UTF-8 com BOM, bom para abrir no Excel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.as_row())


def parse_args() -> argparse.Namespace:
    """Define os comandos e filtros aceitos pelo script."""
    parser = argparse.ArgumentParser(
        description="Busca leads no OpenStreetMap sem Google Cloud."
    )
    parser.add_argument(
        "-q",
        "--query",
        action="append",
        help='Busca no formato "barbearias em Campinas SP".',
    )
    parser.add_argument("--what", help='Categoria. Ex: "barbearias"')
    parser.add_argument("--where", help='Cidade/regiao. Ex: "Campinas SP"')
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help='Tag OSM manual. Ex: --tag "shop=hairdresser"',
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=80,
        help="Maximo de leads por busca. Padrao: 80.",
    )
    parser.add_argument(
        "--out",
        default=f"osm_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        help="Arquivo CSV de saida.",
    )
    parser.add_argument(
        "--without-website-only",
        action="store_true",
        help="Exporta apenas empresas sem site cadastrado no OpenStreetMap.",
    )
    parser.add_argument(
        "--with-phone-only",
        action="store_true",
        help="Exporta apenas empresas com telefone cadastrado.",
    )
    parser.add_argument(
        "--repeat-until-found",
        action="store_true",
        help="Repete a busca ate encontrar ao menos um lead com telefone.",
    )
    parser.add_argument(
        "--repeat-delay",
        type=int,
        default=300,
        help="Pausa em segundos entre repeticoes. Padrao: 300.",
    )
    parser.add_argument(
        "--message",
        default=(
            "Ola, tudo bem? Trabalho com criacao de sites profissionais para "
            "empresas locais. Encontrei sua empresa e acredito que um site "
            "simples, rapido e bem apresentado pode ajudar a fortalecer sua "
            "presenca online e gerar mais contatos. Posso te enviar uma "
            "sugestao sem compromisso?"
        ),
        help="Mensagem inicial usada no link do WhatsApp.",
    )
    return parser.parse_args()


def requested_searches(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    """Normaliza buscas vindas de --what/--where ou de -q."""
    searches: list[tuple[str, str, str]] = []

    if args.what and args.where:
        searches.append((args.what, args.where, f"{args.what} em {args.where}"))

    for query in args.query or []:
        what, where = parse_query(query)
        searches.append((what, where, query))

    return searches


def collect_leads(
    args: argparse.Namespace,
    searches: list[tuple[str, str, str]],
    bboxes: dict[str, tuple[float, float, float, float]],
) -> list[OsmLead]:
    """Busca, filtra, remove duplicados e ordena os leads de uma rodada."""
    leads: list[OsmLead] = []
    seen_ids: set[str] = set()

    for what, where, searched_query in searches:
        if where not in bboxes:
            # Cache da cidade: em repeticoes, nao precisa geocodificar de novo.
            print(f"Geocodificando: {where}")
            bboxes[where] = geocode(where)
            time.sleep(1.1)

        tags = tags_for(what, args.tag)
        print(f"Buscando: {searched_query}")
        data = post_overpass(build_overpass_query(tags, bboxes[where]))

        count_for_search = 0
        for element in data.get("elements", []):
            lead = element_to_lead(element, searched_query, args.message)
            if not lead or lead.place_id in seen_ids:
                continue
            # Filtro principal para achar empresas que podem precisar de site.
            if args.without_website_only and lead.website:
                continue
            # Com telefone somente se tambem gerou link valido de WhatsApp.
            if args.with_phone_only and not lead.whatsapp_link:
                continue

            leads.append(lead)
            seen_ids.add(lead.place_id)
            count_for_search += 1
            if count_for_search >= args.max_results:
                break

    # Ordena para deixar as melhores oportunidades no topo do CSV.
    leads.sort(key=lambda lead: lead.opportunity_score, reverse=True)
    return leads


def main() -> int:
    """Fluxo principal do buscador sem Google Cloud."""
    load_dotenv()
    args = parse_args()
    searches = requested_searches(args)

    if not searches:
        print('Use: python osm_lead_finder.py --what "lojas" --where "Campinas SP"')
        return 2

    if args.repeat_until_found:
        args.with_phone_only = True
        # Evita loop agressivo contra API publica gratuita.
        if args.repeat_delay < 60:
            print("repeat-delay muito baixo para servico gratuito; usando 60 segundos.")
            args.repeat_delay = 60

    bboxes: dict[str, tuple[float, float, float, float]] = {}
    attempt = 1

    while True:
        if args.repeat_until_found:
            print(f"Tentativa {attempt}")

        leads = collect_leads(args, searches, bboxes)
        export_csv(Path(args.out), leads)

        if leads or not args.repeat_until_found:
            print(f"Pronto: {len(leads)} leads exportados em {args.out}")
            return 0

        # Se nao achou telefone, espera e tenta de novo conforme pedido.
        print(
            "Nenhum lead com telefone encontrado. "
            f"Rodando de novo em {args.repeat_delay} segundos..."
        )
        attempt += 1
        time.sleep(args.repeat_delay)


if __name__ == "__main__":
    raise SystemExit(main())
