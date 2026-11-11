#!/usr/bin/env python3
"""
PotikIA — explicações em linguagem simples, geradas por IA.

Roda no GitHub Actions depois do coletor. Usa o GitHub Models (gratuito, com
limite diário) autenticado pelo GITHUB_TOKEN da própria automação: não precisa
de chave nem de cartão. Envia à IA SOMENTE textos públicos do Senado (ementa e
indexação). Nenhum dado de usuário passa por aqui.

Cada projeto é explicado uma única vez e guardado em data/explicacoes.json.
Se o limite gratuito acabar, para e continua no dia seguinte.
"""
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, "data", "senado.json")
SAIDA = os.path.join(RAIZ, "data", "explicacoes.json")
ENDPOINT = "https://models.github.ai/inference/chat/completions"
MODELO = os.environ.get("MODELO_IA", "openai/gpt-4.1-mini")
MAX_POR_DIA = int(os.environ.get("MAX_EXPLICACOES", "120"))
PAUSA = float(os.environ.get("PAUSA_IA", "4.5"))  # respeita ~15 pedidos/minuto
VERSAO_PROMPT = "v1"

SISTEMA = """Você explica proposições legislativas do Senado Federal brasileiro para cidadãos comuns.
Regras obrigatórias:
- Use português do Brasil simples, frases curtas, sem juridiquês. Se precisar de um termo técnico, explique-o.
- Baseie-se APENAS no texto fornecido (ementa e indexação). Não invente números, prazos, valores ou efeitos que não estejam no texto.
- Se o texto não permitir saber algo, diga que isso depende do texto completo do projeto.
- Seja estritamente neutro e apartidário: não opine, não diga se a proposta é boa ou ruim, não use adjetivos valorativos, não cite partidos nem pessoas.
- Não diga ao leitor como votar ou se posicionar.
Responda somente com um JSON no formato:
{"resumo": "2 a 3 frases dizendo o que a proposta faz", "pontos": ["até 3 itens curtos sobre o que muda na prática"], "quem": "1 frase sobre quem pode ser afetado, ou string vazia se o texto não indicar"}"""

# ---------- critérios de prioridade (públicos e iguais para todos) ----------
# Como a IA gratuita tem limite diário, os projetos de maior impacto são explicados primeiro.
# Os critérios olham só o TIPO e o TEXTO da ementa, nunca o autor ou o partido.
PESO_TIPO = {"PEC": 5, "MPV": 4, "PLP": 3, "PL": 1, "PDL": 0}
CRITERIOS = [
    # (pontos, nome do critério, palavras-chave na ementa)
    (3, "orçamento e finanças públicas", ["orçament", "tribut", "imposto", "contribuiç", "fiscal", "receita pública", "despesa", "crédito extraordinário", "crédito especial", "diretrizes orçamentárias", "plano plurianual", "fundo ", "dívida pública", "renúncia de receita", "benefício fiscal"]),
    (3, "direitos fundamentais", ["direitos fundamentais", "direitos humanos", "liberdade", "igualdade", "discrimina", "dados pessoais", "privacidade", "criança", "adolescente", "pessoa com deficiência", "idoso", "mulher", "indígena", "quilombola", "saúde", "sus", "educação", "previdência", "aposentadoria", "assistência social", "moradia", "trabalhador", "salário", "segurança alimentar", "código penal", "processo penal", "prisão", "pena ", "consumidor", "meio ambiente"]),
    (1, "alcance nacional", ["constituição federal", "código ", "estatuto", "política nacional", "sistema nacional", "todo o território nacional"]),
]
SIMBOLICOS = ["denomina ", "institui o dia", "institui a semana", "institui o mês", "inscreve o nome", "livro dos heróis", "declara patrono", "patrona", "confere o título", "capital nacional", "radiodifusão", "outorga", "renova a concessão", "renova a permissão", "honorífic"]

def prioridade(m, hoje=None):
    from datetime import date
    e = (m.get("ementa") or "").lower()
    pts = PESO_TIPO.get(m.get("sigla"), 0)
    motivos = []
    for peso, nome, kws in CRITERIOS:
        if any(k in e for k in kws):
            pts += peso; motivos.append(nome)
    if m.get("relatores"):
        pts += 2; motivos.append("em análise com relatoria")
    try:
        dias = ((hoje or date.today()) - date.fromisoformat(m.get("apresentacao", "")[:10])).days
        if dias <= 90: pts += 1; motivos.append("recente")
    except Exception:
        pass
    if any(k in e for k in SIMBOLICOS):
        pts -= 6; motivos.append("homenagem/outorga (baixa prioridade)")
    return pts, motivos

def log(*a):
    print("[explicar]", *a, file=sys.stderr)

USAR_JSON_MODE = True

def chamar(token, corpo):
    req = urllib.request.Request(ENDPOINT, data=json.dumps(corpo).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def extrair_json(texto):
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except Exception:
        m = re.search(r"\{.*\}", texto, re.S)
        if not m:
            raise ValueError("resposta sem JSON")
        return json.loads(m.group(0))

def pedir(token, materia):
    global USAR_JSON_MODE
    usuario = (f"Tipo e número: {materia['sigla']} {materia['numero']}/{materia['ano']}\n"
               f"Ementa oficial: {materia['ementa']}")
    if materia.get("indexacao"):
        usuario += f"\nIndexação: {materia['indexacao']}"
    corpo = {
        "model": MODELO,
        "temperature": 0.2,
        "max_tokens": 450,
        "messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}],
    }
    if USAR_JSON_MODE:
        corpo["response_format"] = {"type": "json_object"}
    try:
        resp = chamar(token, corpo)
    except urllib.error.HTTPError as e:
        if e.code in (400, 422) and USAR_JSON_MODE:
            log("modelo não aceitou o modo JSON; tentando sem ele")
            USAR_JSON_MODE = False
            corpo.pop("response_format", None)
            resp = chamar(token, corpo)
        else:
            raise
    texto = resp["choices"][0]["message"]["content"]
    j = extrair_json(texto)
    resumo = str(j.get("resumo", "")).strip()
    pontos = [str(p).strip() for p in (j.get("pontos") or []) if str(p).strip()][:3]
    quem = str(j.get("quem", "")).strip()
    if len(resumo) < 20:
        raise ValueError("resposta vazia")
    return {"resumo": resumo[:700], "pontos": [p[:240] for p in pontos], "quem": quem[:240]}

def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        log("sem GITHUB_TOKEN; nada a fazer"); return
    dados = json.load(open(DADOS, encoding="utf-8"))
    if dados.get("demo"):
        log("dados de demonstração; pulando"); return
    exp = {}
    if os.path.exists(SAIDA):
        try: exp = json.load(open(SAIDA, encoding="utf-8"))
        except Exception: exp = {}

    # só explica de novo se a ementa mudou; prioriza com relatoria e mais recentes
    def precisa(m):
        e = exp.get(m["id"])
        return m.get("ementa") and (not e or e.get("ementa") != m["ementa"] or e.get("prompt") != VERSAO_PROMPT)
    fila = [m for m in dados["materias"] if precisa(m)]
    fila.sort(key=lambda m: (prioridade(m)[0], m.get("apresentacao", "")), reverse=True)
    log(f"modelo: {MODELO}; pendentes: {len(fila)}; limite desta rodada: {MAX_POR_DIA}")

    feitas, erros = 0, 0
    for m in fila[:MAX_POR_DIA]:
        try:
            r = pedir(token, m)
        except urllib.error.HTTPError as e:
            try: detalhe = e.read().decode()[:400]
            except Exception: detalhe = ""
            log(f"{m['id']}: HTTP {e.code} {detalhe}")
            if e.code == 429:
                log("limite gratuito atingido; continua amanhã"); break
            if e.code in (401, 403):
                log(f"sem permissão ({e.code}). Confira 'models: read' no workflow."); break
            erros += 1; continue
        except Exception as e:
            erros += 1; log(f"{m['id']}: {e}"); continue
        r.update({"prioridade": prioridade(m)[1], "ementa": m["ementa"], "modelo": MODELO, "prompt": VERSAO_PROMPT,
                  "gerado_em": datetime.now(timezone.utc).date().isoformat()})
        exp[m["id"]] = r; feitas += 1
        if feitas % 10 == 0:
            salvar(exp)
        time.sleep(PAUSA)
        if erros >= 10:
            log("muitos erros seguidos; parando"); break

    ids = {m["id"] for m in dados["materias"]}
    exp = {k: v for k, v in exp.items() if k in ids}  # remove projetos que saíram da lista
    salvar(exp)
    log(f"ok: {feitas} novas, {erros} erros, {len(exp)} no total")

def salvar(exp):
    tmp = SAIDA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(exp, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, SAIDA)

if __name__ == "__main__":
    main()
