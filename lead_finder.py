#!/usr/bin/env python3
"""
Busca empresas no Google Places e exporta leads para CSV.

Use somente para prospeccao responsavel: revise os leads manualmente, respeite
opt-out, nao automatize disparos em massa e siga LGPD/CAN-SPAM/regras locais.
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


# Endpoint oficial da Places API (New) para buscar empresas por texto.
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Lista de campos que queremos receber do Google. Quanto menos campos, menor o
# custo/volume da resposta e mais simples fica o CSV.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.businessStatus",
        "places.rating",
        "places.userRatingCount",
        "places.primaryType",
        "places.types",
        "nextPageToken",
    ]
)

# Colunas finais do arquivo CSV. O whatsapp_review.py usa phone/whatsapp_link.
CSV_FIELDS = [
    "searched_query",
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


@dataclass
class Lead:
    """Representa um lead ja normalizado para exportar no CSV."""

    searched_query: str
    name: str
    phone: str
    website: str
    address: str
    maps_url: str
    business_status: str
    rating: str
    review_count: int
    primary_type: str
    opportunity_score: int
    prospect_reason: str
    whatsapp_link: str
    place_id: str

    def as_row(self) -> dict[str, Any]:
        """Converte o lead para o formato aceito pelo csv.DictWriter."""
        return {
            "searched_query": self.searched_query,
            "name": self.name,
            "phone": self.phone,
            "website": self.website,
            "address": self.address,
            "maps_url": self.maps_url,
            "business_status": self.business_status,
            "rating": self.rating,
            "review_count": self.review_count,
            "primary_type": self.primary_type,
            "opportunity_score": self.opportunity_score,
            "prospect_reason": self.prospect_reason,
            "whatsapp_link": self.whatsapp_link,
            "place_id": self.place_id,
        }


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carrega variaveis simples do arquivo .env sem depender de biblioteca."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        # Ignora linhas vazias, comentarios e linhas que nao parecem KEY=VALUE.
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def post_json(url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Envia um POST JSON para a API do Google e devolve a resposta como dict."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Mostra o corpo do erro porque o Google costuma explicar campo/API/chave.
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro HTTP {exc.code} da API: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexao com a API: {exc}") from exc


def search_text(
    api_key: str,
    query: str,
    max_results: int,
    language_code: str,
    region_code: str,
    delay_seconds: float,
) -> list[dict[str, Any]]:
    """Executa a busca de texto e segue paginas ate bater o limite pedido."""
    places: list[dict[str, Any]] = []
    page_token: str | None = None

    while len(places) < max_results:
        # A API limita a pagina; aqui pedimos so o que falta ate max_results.
        payload: dict[str, Any] = {
            "textQuery": query,
            "pageSize": min(20, max_results - len(places)),
            "languageCode": language_code,
            "regionCode": region_code,
        }
        if page_token:
            payload["pageToken"] = page_token

        data = post_json(TEXT_SEARCH_URL, api_key, payload)
        batch = data.get("places", [])
        places.extend(batch)

        page_token = data.get("nextPageToken")
        if not page_token or not batch:
            break

        # Evita chamadas grudadas entre paginas.
        time.sleep(delay_seconds)

    return places[:max_results]


def normalize_phone(phone: str) -> str:
    """Deixa o telefone somente com numeros e tenta preparar para WhatsApp."""
    digits = re.sub(r"\D+", "", phone)
    if not digits:
        return ""

    if digits.startswith(("0800", "0300")):
        return ""

    # Telefones brasileiros as vezes chegam sem DDI.
    if len(digits) in {10, 11}:
        digits = "55" + digits

    return digits


def build_whatsapp_link(phone: str, message: str) -> str:
    """Monta link wa.me com telefone e mensagem ja preenchida."""
    digits = normalize_phone(phone)
    if not digits:
        return ""

    encoded = urllib.parse.quote(message)
    return f"https://wa.me/{digits}?text={encoded}"


def score_place(place: dict[str, Any]) -> tuple[int, str]:
    """Calcula uma pontuacao simples para priorizar leads mais promissores."""
    website = place.get("websiteUri") or ""
    phone = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""
    review_count = int(place.get("userRatingCount") or 0)
    rating = float(place.get("rating") or 0)

    score = 0
    reasons: list[str] = []

    # Sem site e o principal sinal de oportunidade para vender criacao de site.
    if not website:
        score += 60
        reasons.append("nao tem site no Google Maps")
    else:
        reasons.append("ja tem site")

    if phone:
        score += 20
        reasons.append("tem telefone para contato")

    if review_count >= 20:
        score += 10
        reasons.append("tem volume de avaliacoes")

    if rating >= 4.0:
        score += 10
        reasons.append("boa reputacao")

    return min(score, 100), "; ".join(reasons)


def place_to_lead(place: dict[str, Any], query: str, whatsapp_message: str) -> Lead:
    """Transforma o JSON bruto do Google em um objeto Lead padronizado."""
    display_name = place.get("displayName") or {}
    phone = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""
    score, reason = score_place(place)

    return Lead(
        searched_query=query,
        name=display_name.get("text") or "",
        phone=phone,
        website=place.get("websiteUri") or "",
        address=place.get("formattedAddress") or "",
        maps_url=place.get("googleMapsUri") or "",
        business_status=place.get("businessStatus") or "",
        rating=str(place.get("rating") or ""),
        review_count=int(place.get("userRatingCount") or 0),
        primary_type=place.get("primaryType") or "",
        opportunity_score=score,
        prospect_reason=reason,
        whatsapp_link=build_whatsapp_link(phone, whatsapp_message),
        place_id=place.get("id") or "",
    )


def read_queries(args: argparse.Namespace) -> list[str]:
    """Junta buscas vindas do terminal e/ou de arquivo .txt."""
    queries: list[str] = []

    if args.query:
        queries.extend(args.query)

    if args.queries_file:
        path = Path(args.queries_file)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo de buscas nao encontrado: {path}")
        queries.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            # Permite comentar linhas no arquivo de buscas com #.
            if line.strip() and not line.strip().startswith("#")
        )

    # Remove duplicadas mantendo a ordem original.
    return list(dict.fromkeys(queries))


def export_csv(path: Path, leads: list[Lead]) -> None:
    """Salva a lista de leads em CSV compativel com Excel/Sheets."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.as_row())


def parse_args() -> argparse.Namespace:
    """Define todos os parametros aceitos pela linha de comando."""
    parser = argparse.ArgumentParser(
        description="Busca leads no Google Maps/Places e exporta CSV."
    )
    parser.add_argument(
        "-q",
        "--query",
        action="append",
        help='Busca no formato livre. Ex: -q "dentistas em Campinas"',
    )
    parser.add_argument(
        "--queries-file",
        help="Arquivo .txt com uma busca por linha.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=40,
        help="Maximo de resultados por busca. Padrao: 40.",
    )
    parser.add_argument(
        "--out",
        default=f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        help="Arquivo CSV de saida.",
    )
    parser.add_argument(
        "--without-website-only",
        action="store_true",
        help="Exporta apenas empresas que nao tem site cadastrado no Maps.",
    )
    parser.add_argument(
        "--language-code",
        default="pt-BR",
        help="Idioma dos resultados. Padrao: pt-BR.",
    )
    parser.add_argument(
        "--region-code",
        default="BR",
        help="Regiao dos resultados. Padrao: BR.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=2.0,
        help="Pausa entre paginas da API. Padrao: 2.",
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


def main() -> int:
    """Fluxo principal: le configuracao, busca empresas, filtra e exporta."""
    load_dotenv()
    args = parse_args()
    queries = read_queries(args)

    if not queries:
        print('Informe ao menos uma busca. Ex: python lead_finder.py -q "barbearias em Sorocaba"')
        return 2

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Defina GOOGLE_MAPS_API_KEY no arquivo .env ou nas variaveis de ambiente.")
        return 2

    all_leads: list[Lead] = []
    seen_place_ids: set[str] = set()

    for query in queries:
        print(f"Buscando: {query}")
        places = search_text(
            api_key=api_key,
            query=query,
            max_results=args.max_results,
            language_code=args.language_code,
            region_code=args.region_code,
            delay_seconds=args.delay_seconds,
        )

        for place in places:
            place_id = place.get("id") or ""
            # Evita repetir a mesma empresa quando varias buscas retornam o mesmo lugar.
            if place_id in seen_place_ids:
                continue

            lead = place_to_lead(place, query, args.message)
            # Quando o foco e vender site, este filtro deixa so quem nao tem site.
            if args.without_website_only and lead.website:
                continue

            seen_place_ids.add(place_id)
            all_leads.append(lead)

    # Melhores oportunidades aparecem primeiro no CSV.
    all_leads.sort(key=lambda lead: lead.opportunity_score, reverse=True)
    export_csv(Path(args.out), all_leads)

    print(f"Pronto: {len(all_leads)} leads exportados em {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
