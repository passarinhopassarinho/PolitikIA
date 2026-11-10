# PotikIA — Consultas públicas do Senado

Site estático, gratuito e sem coleta de dados pessoais. Mostra os projetos em tramitação no Senado, leva a pessoa para opinar no e-Cidadania e ajuda a escrever para a relatoria.

## O que tem aqui

| Arquivo | Para que serve |
|---|---|
| `index.html` | O site. |
| `privacidade.html` | Política de privacidade (modelo; preencher os campos entre colchetes). |
| `data/senado.json` | Dados que o site exibe. Vem com **dados fictícios de demonstração**; é substituído na primeira atualização. |
| `data/compromissos.json` | Compromissos públicos de senadores, curados à mão (fase 3). |
| `coletor/coletor.py` | Busca os dados públicos do Senado e gera `data/senado.json`. Só usa Python padrão. |
| `.github/workflows/atualizar.yml` | Roda o coletor todo dia e publica o site. |

## Como publicar (uns 15 minutos, sem programar)

1. **Crie uma conta no GitHub** (github.com) e, de preferência, uma organização gratuita chamada, por exemplo, `potikia`.
2. **Crie um repositório público** chamado `potikia` (ou outro nome). Marque "Add a README" para ele não nascer vazio.
3. **Envie os arquivos:** no repositório, clique em *Add file → Upload files* e arraste **todo o conteúdo desta pasta** (inclusive a pasta `.github`). Clique em *Commit changes*.
   - Se o upload pelo navegador ignorar a pasta `.github` (pastas que começam com ponto às vezes ficam ocultas), crie o arquivo manualmente: *Add file → Create new file*, digite o nome `.github/workflows/atualizar.yml` e cole o conteúdo.
4. **Ative o site:** *Settings → Pages → Build and deployment → Source: GitHub Actions*.
5. **Rode a primeira atualização:** aba *Actions → Atualizar dados e publicar site → Run workflow*. Em alguns minutos o site estará em `https://<sua-conta>.github.io/potikia/`.
6. Depois disso, a atualização roda sozinha todo dia às 6h17 (horário de Brasília).

## Conferir na primeira execução

O coletor foi testado com respostas simuladas, porque a API do Senado não estava acessível do ambiente onde foi escrito. Na primeira rodada, confira:

- **Aba Actions → log do passo "Coletar dados do Senado"**: deve listar quantos registros vieram por tipo (PL, PEC…). Se tudo vier com 0, a API mudou o formato da pesquisa — me mande o log.
- **Relatoria:** o coletor tenta `/processo/relatoria` e, se falhar, `/materia/relatorias/{código}`. Se nenhum projeto aparecer com "Acionar relatoria", um desses endereços mudou.
- **Links:** clique em "Opinar no e-Cidadania" e "Tramitação" de dois projetos e veja se abrem a página certa. O site assume que o código da matéria na API é o mesmo usado no e-Cidadania.

## Compromissos públicos (fase 3)

Edite `data/compromissos.json` no próprio GitHub (ícone de lápis). Cada item:

```json
{
  "senador": "código do senador na API (ex.: 5012)",
  "temas": ["Tecnologia e dados"],
  "texto": "Resumo fiel e neutro do compromisso.",
  "fonte": "https://link-para-a-fonte-original",
  "fonte_desc": "Entrevista ao veículo X",
  "data": "2026-09-12",
  "curadoria": "iniciais de quem verificou"
}
```

Regras sugeridas: só entra com link público verificável; mesmo critério para todos os partidos; resumo sem adjetivos; canal para o gabinete pedir correção. **Apague o item de exemplo** antes de publicar (itens com `"exemplo": true` não aparecem quando os dados são reais).

## Privacidade, em uma frase

Nada sai do aparelho da pessoa: favoritos, temas e filtros ficam no navegador; a posição dela nunca é salva; mensagens saem do e-mail dela. O único registro técnico é o log de acesso do provedor de hospedagem (IP), tratado na política de privacidade.

## Ajustes simples

- **Temas:** edite o dicionário `TEMAS` em `coletor/coletor.py` (palavras-chave na ementa).
- **Tipos de proposição:** lista `SIGLAS` no mesmo arquivo.
- **Horário da atualização:** linha `cron` no `atualizar.yml` (horário em UTC).
