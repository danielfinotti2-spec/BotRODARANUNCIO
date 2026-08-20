# Bot de Prospeccao para Sites

Bot em Python para encontrar possiveis clientes locais, gerar uma lista em CSV e abrir conversas no WhatsApp Desktop ou WhatsApp Web com uma mensagem pronta.

O projeto foi feito para prospeccao manual e responsavel. Ele nao aperta "enviar" sozinho.

## Aviso Importante

Use com moderacao. Se voce buscar muitos dados em pouco tempo ou abrir muitas conversas no WhatsApp, pode receber restricao, bloqueio temporario ou ate bloqueio da conta.

Riscos principais:

- WhatsApp pode limitar ou bloquear contas que enviam muitas mensagens parecidas.
- OpenStreetMap/Nominatim/Overpass podem limitar seu IP se houver muitas consultas repetidas.
- Google Maps/Places pode gerar custos e tambem aplicar limites de uso.
- Contatos frios em massa podem ser considerados spam.

Boas praticas:

- Revise os leads antes de abordar.
- Personalize a mensagem quando possivel.
- Faca poucos contatos por vez.
- Respeite quem pedir para nao receber novas mensagens.
- Nao use disparo automatico em massa.
- Use intervalos grandes quando ativar repeticao automatica.
- Nunca suba `.env` ou arquivos CSV com contatos para repositorio publico.

## Recursos

- Busca leads sem Google Cloud usando OpenStreetMap.
- Opcionalmente busca pelo Google Places API, se voce tiver chave.
- Filtra empresas sem site cadastrado.
- Filtra empresas com telefone valido para WhatsApp.
- Gera CSV compativel com Excel/Google Sheets.
- Abre WhatsApp Desktop por padrao.
- Permite marcar lead como enviado, pulado ou sem telefone.

## Requisitos

- Python 3.10 ou superior.
- WhatsApp Desktop instalado, se quiser abrir pelo aplicativo.
- Nenhuma biblioteca externa obrigatoria.

## Arquivos

- `osm_lead_finder.py`: busca leads sem Google Cloud usando OpenStreetMap.
- `lead_finder.py`: busca leads usando Google Places API.
- `whatsapp_review.py`: abre os leads no WhatsApp para revisao manual.
- `queries_exemplo.txt`: exemplos de buscas.
- `.env.example`: exemplo de configuracao.
- `requirements.txt`: informacao sobre dependencias.

## Uso Rapido sem Google Cloud

Buscar lojas em uma cidade e gerar `leads.csv`:

```powershell
python osm_lead_finder.py --what "lojas" --where "Campinas SP" --with-phone-only --without-website-only --out leads.csv
```

Abrir os contatos no WhatsApp Desktop:

```powershell
python whatsapp_review.py leads.csv
```

Durante a revisao:

- `e`: marcar como enviado
- `p`: pular lead
- `q`: sair

## Buscar Todo Tipo de Loja

Para lojas em geral:

```powershell
python osm_lead_finder.py --what "lojas" --where "Campinas SP" --out leads.csv
```

Somente lojas com telefone:

```powershell
python osm_lead_finder.py --what "lojas" --where "Campinas SP" --with-phone-only --out leads.csv
```

Somente lojas sem site e com telefone:

```powershell
python osm_lead_finder.py --what "lojas" --where "Campinas SP" --with-phone-only --without-website-only --out leads.csv
```

Outras cidades:

```powershell
python osm_lead_finder.py --what "lojas" --where "Sorocaba SP" --with-phone-only --out leads.csv
python osm_lead_finder.py --what "comercios" --where "Osasco SP" --with-phone-only --out leads.csv
python osm_lead_finder.py --what "lojas em geral" --where "Santo Andre SP" --with-phone-only --out leads.csv
```

## Repetir Ate Encontrar Telefone

Se nao encontrar nenhum lead com telefone, o bot pode tentar de novo automaticamente:

```powershell
python osm_lead_finder.py --what "lojas" --where "Campinas SP" --without-website-only --repeat-until-found --out leads.csv
```

Por seguranca, o script usa pausa minima de 60 segundos. O padrao e 300 segundos.

Exemplo com intervalo de 10 minutos:

```powershell
python osm_lead_finder.py --what "lojas" --where "Campinas SP" --repeat-until-found --repeat-delay 600 --out leads.csv
```

Evite `while true` sem pausa. Isso pode gerar restricao no seu IP ou bloquear o acesso temporariamente.

## Categorias Prontas

```text
academias, barbearias, cabeleireiros, cafes, clinicas, clinicas de estetica,
comercio, comercios, dentistas, escolas, estetica, farmacias, floriculturas,
imobiliarias, lojas, lojas em geral, lojas de moveis, oficinas,
oficinas mecanicas, oticas, padarias, pet shops, pizzarias, restaurantes,
saloes, supermercados
```

Tambem da para usar uma tag manual do OpenStreetMap:

```powershell
python osm_lead_finder.py --what "qualquer nome" --where "Campinas SP" --tag "shop=hairdresser" --out leads.csv
```

## WhatsApp Desktop ou Web

Desktop, padrao:

```powershell
python whatsapp_review.py leads.csv
```

Navegador/WhatsApp Web:

```powershell
python whatsapp_review.py leads.csv --target web
```

Limitar uma rodada:

```powershell
python whatsapp_review.py leads.csv --limit 10
```

Usar outra mensagem:

```powershell
python whatsapp_review.py leads.csv --message "Ola, tudo bem? Trabalho com criacao de sites profissionais. Posso te enviar uma sugestao sem compromisso?"
```

## Mensagem Padrao

```text
Ola, tudo bem? Trabalho com criacao de sites profissionais para empresas locais. Encontrei sua empresa e acredito que um site simples, rapido e bem apresentado pode ajudar a fortalecer sua presenca online e gerar mais contatos. Posso te enviar uma sugestao sem compromisso?
```

## Opcao com Google Maps/Places

Esta opcao costuma trazer dados mais completos, mas precisa de Google Cloud.

1. Crie uma chave no Google Cloud com a Places API ativada.
2. Copie `.env.example` para `.env`.
3. Coloque sua chave no `.env`:

```env
GOOGLE_MAPS_API_KEY=sua_chave
```

Buscar com Google:

```powershell
python lead_finder.py -q "lojas em Campinas SP" --without-website-only --out leads.csv
```

Varias buscas:

```powershell
python lead_finder.py --queries-file queries_exemplo.txt --max-results 40 --without-website-only --out leads.csv
```

## CSV Gerado

O CSV pode conter:

- nome da empresa
- telefone
- site, se houver
- endereco
- link do mapa
- categoria
- pontuacao de oportunidade
- motivo da pontuacao
- link do WhatsApp com mensagem pronta
- status de contato, depois da revisao

## Prospeccao Responsavel

Este projeto deve ser usado para organizar prospeccao manual. Ele nao deve ser usado para spam.

Recomendacoes:

- Aborde poucos contatos por vez.
- Use uma mensagem educada e clara.
- Identifique quem voce e e o que oferece.
- Nao insista com quem nao respondeu ou recusou.
- Nao envie mensagens repetidas em massa.
- Confira as regras de privacidade e comunicacao comercial aplicaveis.

Para envio totalmente automatico, o caminho correto e a API oficial do WhatsApp Business/Cloud API, com contatos que aceitaram receber mensagens e templates aprovados quando necessario.

## Antes de Publicar no GitHub

Confira se estes arquivos nao serao enviados:

- `.env`
- `leads.csv`
- qualquer `*.csv` com contatos reais
- `__pycache__/`

O `.gitignore` deste projeto ja bloqueia esses arquivos, mas confira antes de publicar.

## Fontes

- OpenStreetMap: https://www.openstreetmap.org
- Nominatim Usage Policy: https://operations.osmfoundation.org/policies/nominatim/
- Overpass API: https://wiki.openstreetmap.org/wiki/Overpass_API
- Google Places API: https://developers.google.com/maps/documentation/places/web-service
- WhatsApp Business Platform: https://developers.facebook.com/docs/whatsapp
