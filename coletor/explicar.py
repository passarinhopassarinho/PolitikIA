#!/usr/bin/env python3
"""
PotikIA — explicações em linguagem simples, geradas por IA.

Roda no GitHub Actions depois do coletor. Envia à IA SOMENTE a ementa oficial
(texto público). Nenhum dado de usuário passa por aqui.

Provedor padrão: um modelo ABERTO rodando dentro da própria automação, via Ollama
(PROVEDOR_IA=ollama). Grátis, sem cadastro, sem chave e sem enviar nada a empresas de IA.
Opcionais, se um dia houver chave (Settings > Secrets and variables > Actions):
- ANTHROPIC_API_KEY -> Anthropic Claude (pago, por uso)
- GEMINI_API_KEY    -> Google Gemini (termos exigem uso profissional e público maior de 18 anos)
(O GitHub Models foi desativado pelo GitHub em 30/07/2026 e não funciona mais.)

Cada projeto é explicado uma única vez e guardado em data/explicacoes.json.
Se o limite acabar, para e continua no dia seguinte.
"""
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, "data", "senado.json")
SAIDA = os.path.join(RAIZ, "data", "explicacoes.json")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
PROVEDOR = os.environ.get("PROVEDOR_IA", "").strip().lower() or ("anthropic" if ANTHROPIC_KEY else "gemini" if GEMINI_KEY else "")
MODELO = os.environ.get("MODELO_IA", "").strip() or {"ollama": "qwen3:4b", "gemini": "gemini-flash-latest", "anthropic": "claude-haiku-5-5"}.get(PROVEDOR, "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
TEMPO_MAX_MIN = float(os.environ.get("TEMPO_MAX_MIN", "0"))  # 0 = sem limite de tempo
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

def post_json(url, corpo, headers):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "potikia-explicar", **headers})
    with urllib.request.urlopen(req, timeout=90) as r:
        bruto = r.read(); tipo = r.headers.get("Content-Type", ""); status = r.status
    texto = bruto.decode("utf-8", "replace")
    try:
        return json.loads(texto)
    except Exception:
        raise RuntimeError(f"resposta inesperada (status {status}, tipo '{tipo}'): {texto[:300]!r}")

def gerar_texto(usuario):
    if PROVEDOR == "ollama":
        corpo = {"model": MODELO, "stream": False, "think": False, "format": "json",
                 "options": {"temperature": 0.2, "num_predict": 500, "num_ctx": 4096},
                 "messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]}
        resp = post_json(f"{OLLAMA_URL}/api/chat", corpo, {})
        return resp.get("message", {}).get("content", "")
    if PROVEDOR == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent"
        corpo = {
            "systemInstruction": {"parts": [{"text": SISTEMA}]},
            "contents": [{"role": "user", "parts": [{"text": usuario}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 900, "responseMimeType": "application/json"},
        }
        resp = post_json(url, corpo, {"x-goog-api-key": GEMINI_KEY})
        partes = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in partes if not p.get("thought"))
    if PROVEDOR == "anthropic":
        corpo = {"model": MODELO, "max_tokens": 700, "temperature": 0.2, "system": SISTEMA,
                 "messages": [{"role": "user", "content": usuario}]}
        resp = post_json("https://api.anthropic.com/v1/messages", corpo,
                         {"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    raise RuntimeError("nenhum provedor configurado")

def extrair_json(texto):
    texto = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S)
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        return json.loads(texto)
    except Exception:
        m = re.search(r"\{.*\}", texto, re.S)
        if not m:
            raise ValueError(f"resposta sem JSON: {texto[:200]!r}")
        return json.loads(m.group(0))

def pedir(materia):
    usuario = (f"Tipo e número: {materia['sigla']} {materia['numero']}/{materia['ano']}\n"
               f"Ementa oficial: {materia['ementa']}")
    j = extrair_json(gerar_texto(usuario))
    resumo = str(j.get("resumo", "")).strip()
    pontos = [str(p).strip() for p in (j.get("pontos") or []) if str(p).strip()][:3]
    quem = str(j.get("quem", "")).strip()
    if len(resumo) < 20:
        raise ValueError("resposta vazia")
    return {"resumo": resumo[:700], "pontos": [p[:240] for p in pontos], "quem": quem[:240]}

def main():
    if not PROVEDOR:
        log("nenhum provedor de IA configurado; pulando"); return
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
    log(f"provedor: {PROVEDOR}; modelo: {MODELO}; pendentes: {len(fila)}; limite desta rodada: {MAX_POR_DIA}")

    feitas, erros = 0, 0
    inicio = time.time()
    pausa = 0 if PROVEDOR == "ollama" else PAUSA
    for m in fila[:MAX_POR_DIA]:
        if TEMPO_MAX_MIN and (time.time() - inicio) / 60 > TEMPO_MAX_MIN:
            log(f"tempo máximo de {TEMPO_MAX_MIN:.0f} min atingido; continua na próxima execução"); break
        try:
            r = pedir(m)
        except urllib.error.HTTPError as e:
            try: detalhe = e.read().decode()[:400]
            except Exception: detalhe = ""
            log(f"{m['id']}: HTTP {e.code} {detalhe}")
            if e.code == 429:
                log("limite gratuito atingido; continua amanhã"); break
            if e.code in (400, 401, 403) and feitas == 0:
                log(f"chave recusada ou modelo indisponível ({e.code}). Confira a chave em Settings > Secrets e o nome do modelo."); break
            if e.code == 404:
                log(f"modelo '{MODELO}' não encontrado; defina MODELO_IA no workflow."); break
            erros += 1; continue
        except Exception as e:
            erros += 1; log(f"{m['id']}: {e}")
            if erros >= 5 and feitas == 0:
                log("5 falhas seguidas sem nenhum sucesso; parando para não gastar a cota"); break
            continue
        r.update({"prioridade": prioridade(m)[1], "ementa": m["ementa"], "modelo": MODELO, "prompt": VERSAO_PROMPT,
                  "gerado_em": datetime.now(timezone.utc).date().isoformat()})
        exp[m["id"]] = r; feitas += 1
        if feitas <= 3:  # amostra no registro, para revisão humana
            log(f"amostra {m['sigla']} {m['numero']}/{m['ano']}: {r['resumo']}")
        if feitas % 10 == 0:
            salvar(exp)
        time.sleep(pausa)
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
