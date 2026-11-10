#!/usr/bin/env python3
"""
PotikIA — coletor de dados públicos do Senado Federal.

Roda uma vez por dia no GitHub Actions. Lê apenas dados públicos
(API de Dados Abertos do Senado) e grava data/senado.json, que o site lê.
Não coleta, recebe nem armazena dado pessoal de usuários do site.

Só usa a biblioteca padrão do Python (sem dependências).
Se uma chamada falhar, mantém os dados do dia anterior em vez de apagar.
"""
import json, os, re, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, date

BASE = "https://legis.senado.leg.br/dadosabertos"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "data", "senado.json")
UA = "PotikIA-coletor/0.1 (projeto civico; dados abertos)"

SIGLAS = ["PL", "PEC", "PLP", "PDL", "MPV"]   # tipos de proposição acompanhados
ANOS = [date.today().year, date.today().year - 1]
MAX_RELATORIAS = int(os.environ.get("MAX_RELATORIAS", "400"))  # consultas extras por rodada
PAUSA = 0.35  # segundos entre chamadas, para não sobrecarregar a API

# Temas por palavra-chave na ementa (ajuste livremente)
TEMAS = {
    "Tecnologia e dados": ["inteligência artificial", "dados pessoais", "internet", "digital", "plataforma", "cibern", "tecnologia", "algoritm", "telecomunica"],
    "Saúde": ["saúde", "sus", "medicamento", "hospital", "doença", "vacina", "médic"],
    "Educação": ["educação", "escola", "ensino", "universidade", "professor", "estudante"],
    "Meio ambiente": ["ambiental", "meio ambiente", "clima", "florest", "saneamento", "resíduo", "água", "desmatamento"],
    "Infância e juventude": ["criança", "adolescente", "infância", "juventude", "jovem", "estatuto da criança"],
    "Segurança pública": ["penal", "crime", "polícia", "segurança pública", "violência", "arma", "prisional"],
    "Economia e trabalho": ["tributári", "imposto", "trabalh", "emprego", "previdênci", "salário", "empresa", "crédito", "fiscal"],
    "Cidades e transporte": ["trânsito", "transporte", "mobilidade", "rodovi", "habitação", "urbano", "moradia"],
    "Direitos e cidadania": ["direitos humanos", "mulher", "pessoa com deficiência", "idoso", "igualdade", "indígena", "consumidor"],
}

def log(*a):
    print("[coletor]", *a, file=sys.stderr)

def get_json(path, params=None):
    url = BASE + path + (".json" if not path.endswith(".json") else "")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))

# ---------- utilitários robustos (a API muda nomes/estruturas entre versões) ----------
def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)

def pick(o, *names):
    """Primeiro valor encontrado para qualquer um dos nomes (busca recursiva, ignora maiúsculas)."""
    low = [n.lower() for n in names]
    for d in walk(o):
        for k, v in d.items():
            if k.lower() in low and v not in (None, "", [], {}):
                return v
    return None

def as_list(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

def find_records(o, must=("codigo",)):
    """Encontra a lista de registros 'matéria' dentro da resposta."""
    best = []
    for d in walk(o):
        for v in d.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                amostra = json.dumps(v[0]).lower()
                if all(m in amostra for m in must) and len(v) > len(best):
                    best = v
    return best

def temas_de(texto):
    t = (texto or "").lower()
    achados = [tema for tema, kws in TEMAS.items() if any(k in t for k in kws)]
    return achados or ["Outros"]

# ---------- coleta ----------
def senadores():
    data = get_json("/senador/lista/atual")
    out = {}
    for p in as_list(pick(data, "Parlamentar")):
        ident = p.get("IdentificacaoParlamentar", p)
        cod = str(pick(ident, "CodigoParlamentar") or "")
        if not cod: continue
        out[cod] = {
            "nome": pick(ident, "NomeParlamentar") or "",
            "partido": pick(ident, "SiglaPartidoParlamentar") or "",
            "uf": pick(ident, "UfParlamentar") or "",
            "email": pick(ident, "EmailParlamentar") or "",
            "pagina": pick(ident, "UrlPaginaParlamentar") or "",
        }
    log(f"{len(out)} senadores em exercício")
    return out

def materias():
    lista = {}
    for sigla in SIGLAS:
        for ano in ANOS:
            try:
                data = get_json("/materia/pesquisa/lista", {"sigla": sigla, "ano": ano, "tramitando": "S"})
            except Exception as e:
                log(f"falha {sigla}/{ano}: {e}"); continue
            regs = find_records(data, must=("codigo",))
            for m in regs:
                cod = str(pick(m, "CodigoMateria", "Codigo") or "")
                if not cod: continue
                num = pick(m, "NumeroMateria", "Numero") or ""
                ementa = pick(m, "EmentaMateria", "Ementa") or ""
                lista[cod] = {
                    "id": cod,
                    "sigla": pick(m, "SiglaSubtipoMateria", "Sigla") or sigla,
                    "numero": str(num).lstrip("0") or str(num),
                    "ano": str(pick(m, "AnoMateria", "Ano") or ano),
                    "ementa": ementa.strip(),
                    "autor": (pick(m, "NomeAutor", "Autor") or "").strip() if isinstance(pick(m, "NomeAutor", "Autor"), str) else "",
                    "apresentacao": str(pick(m, "DataApresentacao", "Data") or "")[:10],
                    "temas": temas_de(ementa + " " + str(pick(m, "IndexacaoMateria", "Indexacao") or "")),
                }
            log(f"{sigla}/{ano}: {len(regs)} registros")
            time.sleep(PAUSA)
    return lista

RELATORIA_CANDIDATOS = [
    ("/processo/relatoria", lambda c: {"codigoMateria": c}),
    ("/materia/relatorias/{c}", lambda c: None),
]

def relatores(codigo):
    """Relator(es) atuais. Tenta os endpoints conhecidos, do mais novo ao mais antigo."""
    for path, params in RELATORIA_CANDIDATOS:
        try:
            data = get_json(path.format(c=codigo), params(codigo))
        except Exception:
            continue
        cods = []
        for d in walk(data):
            cp = d.get("codigoParlamentar") or d.get("CodigoParlamentar")
            fim = d.get("dataDestituicao") or d.get("DataDestituicao") or d.get("dataFim")
            if cp and not fim:
                cods.append(str(cp))
        if cods or data:
            return sorted(set(cods))
    return []

def main():
    anterior = {}
    if os.path.exists(SAIDA):
        try:
            anterior = json.load(open(SAIDA, encoding="utf-8"))
        except Exception:
            pass
    rel_cache = {m["id"]: m.get("relatores", []) for m in anterior.get("materias", []) if not anterior.get("demo")}

    try:
        sen = senadores()
        mats = materias()
    except Exception as e:
        log("erro na coleta, mantendo dados anteriores:", e); sys.exit(0)
    if not mats:
        log("nenhuma matéria retornada, mantendo dados anteriores"); sys.exit(0)

    # relatoria: prioriza as mais recentes; reaproveita cache das demais
    ordem = sorted(mats.values(), key=lambda m: m["apresentacao"], reverse=True)
    feitas = 0
    for m in ordem:
        if m["id"] in rel_cache and feitas >= MAX_RELATORIAS // 2:
            m["relatores"] = rel_cache[m["id"]]; continue
        if feitas < MAX_RELATORIAS:
            m["relatores"] = relatores(m["id"]); feitas += 1; time.sleep(PAUSA)
        else:
            m["relatores"] = rel_cache.get(m["id"], [])
    log(f"relatorias consultadas: {feitas}")

    # só mantém senadores citados (arquivo menor)
    usados = {c for m in mats.values() for c in m["relatores"]}
    saida = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "Senado Federal — Dados Abertos (legis.senado.leg.br/dadosabertos)",
        "demo": False,
        "senadores": {c: s for c, s in sen.items() if c in usados},
        "materias": ordem,
    }
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    tmp = SAIDA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, SAIDA)
    log(f"ok: {len(ordem)} matérias, {len(saida['senadores'])} senadores -> {SAIDA}")

if __name__ == "__main__":
    main()
