#!/usr/bin/env python3
"""
Abre leads no WhatsApp Desktop ou Web com mensagem pronta para revisao manual.

Este script nao aperta "enviar" sozinho. Isso reduz risco de spam, bloqueio de
conta e contato indevido com empresas que nao querem receber abordagem.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

from lead_finder import build_whatsapp_link, normalize_phone


# Campos de controle adicionados ao CSV depois que voce revisa cada lead.
STATUS_FIELD = "contact_status"
CONTACTED_AT_FIELD = "contacted_at"

# Mensagem usada quando o CSV nao tem whatsapp_link ou quando voce nao passa --message.
DEFAULT_MESSAGE = (
    "Ola, tudo bem? Trabalho com criacao de sites profissionais para empresas "
    "locais. Encontrei sua empresa e acredito que um site simples, rapido e bem "
    "apresentado pode ajudar a fortalecer sua presenca online e gerar mais "
    "contatos. Posso te enviar uma sugestao sem compromisso?"
)


def parse_args() -> argparse.Namespace:
    """Define as opcoes do terminal para abrir/revisar leads."""
    parser = argparse.ArgumentParser(
        description="Abre contatos do CSV no WhatsApp Desktop ou Web, um por vez."
    )
    parser.add_argument("csv_file", help="CSV gerado pelo lead_finder.py")
    parser.add_argument(
        "--message",
        help="Mensagem para usar no lugar da mensagem/link salvo no CSV.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Linha de lead para comecar, contando a partir de 1. Padrao: 1.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Quantidade maxima de leads para abrir nesta rodada.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Pausa em segundos depois de abrir cada conversa. Padrao: 1.5.",
    )
    parser.add_argument(
        "--out",
        help="CSV de saida com status. Padrao: sobrescreve o arquivo original.",
    )
    parser.add_argument(
        "--target",
        choices=["desktop", "web"],
        default="desktop",
        help="Onde abrir a conversa. Padrao: desktop.",
    )
    return parser.parse_args()


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Le o CSV e garante que existem colunas para status de contato."""
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]

    for field in [STATUS_FIELD, CONTACTED_AT_FIELD]:
        # Se o CSV veio sem controle de contato, adiciona as colunas.
        if field not in fieldnames:
            fieldnames.append(field)

    return fieldnames, rows


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    """Regrava o CSV com status atualizado depois de cada lead."""
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def message_from_row(row: dict[str, str], custom_message: str | None) -> str:
    """Escolhe a mensagem: --message, texto salvo no link ou padrao."""
    if custom_message:
        return custom_message

    existing_link = row.get("whatsapp_link", "")
    if existing_link:
        # Reaproveita o texto que ja estava dentro do link wa.me do CSV.
        parsed = urllib.parse.urlparse(existing_link)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("text"):
            return query["text"][0]

    return DEFAULT_MESSAGE


def build_desktop_whatsapp_link(phone: str, message: str) -> str:
    """Monta link whatsapp:// para abrir no aplicativo desktop."""
    digits = normalize_phone(phone)
    if not digits:
        return ""

    encoded_message = urllib.parse.quote(message)
    return f"whatsapp://send?phone={digits}&text={encoded_message}"


def whatsapp_url(row: dict[str, str], custom_message: str | None, target: str) -> str:
    """Monta o link certo para Desktop ou Web a partir da linha do CSV."""
    message = message_from_row(row, custom_message)
    phone = row.get("phone", "")

    if target == "desktop":
        return build_desktop_whatsapp_link(phone, message)

    return build_whatsapp_link(phone, message)


def open_whatsapp(url: str) -> None:
    """Abre o link no app do Windows quando possivel; senao usa navegador."""
    if url.startswith("whatsapp://") and hasattr(os, "startfile"):
        os.startfile(url)  # type: ignore[attr-defined]
        return

    webbrowser.open(url)


def main() -> int:
    """Percorre leads, abre conversa e registra status automaticamente."""
    args = parse_args()
    input_path = Path(args.csv_file)
    output_path = Path(args.out) if args.out else input_path

    if not input_path.exists():
        print(f"CSV nao encontrado: {input_path}")
        return 2

    fieldnames, rows = read_rows(input_path)
    if not rows:
        print("CSV sem leads.")
        return 0

    start_index = max(args.start - 1, 0)
    opened = 0

    while True:
        for index, row in enumerate(rows[start_index:], start=start_index):
            if args.limit is not None and opened >= args.limit:
                break

            if row.get(STATUS_FIELD) == "sent":
                continue

            url = whatsapp_url(row, args.message, args.target)
            if not url:
                row[STATUS_FIELD] = "no_phone"
                continue

            name = row.get("name") or "sem nome"
            phone = row.get("phone") or "sem telefone"
            print(f"\nLead {index + 1}/{len(rows)}: {name} - {phone}")
            print(f"Abrindo WhatsApp {args.target}...")
            open_whatsapp(url)
            opened += 1
            time.sleep(args.delay)

            # Marca automaticamente como enviado
            row[STATUS_FIELD] = "sent"
            row[CONTACTED_AT_FIELD] = datetime.now().isoformat(timespec="seconds")

            # Salva a cada lead
            write_rows(output_path, fieldnames, rows)

        print("\nFim das tentativas. Reiniciando em 30 segundos...")
        time.sleep(30)  # Intervalo fixo entre tentativas

    return 0


if __name__ == "__main__":
    raise SystemExit(main())