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

