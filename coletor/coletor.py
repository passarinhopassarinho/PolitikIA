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

def norm_nome(x):
    import unicodedata
    x = unicodedata.normalize("NFD", x or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", x).strip()

AUTOR_RE = re.compile(r"Senador[a]?\s+(.+?)\s*\(([^/()]+)/([A-Z]{2})\)")

def autores_senadores(autor, sen):
    """Códigos dos senadores autores, a partir do texto 'Senador Fulano (PART/UF), ...'."""
    por_nome = {}
    for cod, s in sen.items():
        por_nome.setdefault((norm_nome(s["nome"]), s["uf"]), cod)
    cods = []
    for nome, _partido, uf in AUTOR_RE.findall(autor or ""):
        cod = por_nome.get((norm_nome(nome), uf))
        if not cod:  # tolera nome parlamentar abreviado
            cand = [c for (n, u), c in por_nome.items() if u == uf and (n in norm_nome(nome) or norm_nome(nome) in n)]
            cod = cand[0] if len(cand) == 1 else None
        if cod and cod not in cods:
            cods.append(cod)
    return cods

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
    cache = {} if anterior.get("demo") else {m["id"]: m for m in anterior.get("materias", [])}

    try:
        sen = senadores()
        mats = materias()
    except Exception as e:
        log("erro na coleta, mantendo dados anteriores:", e); sys.exit(0)
    if not mats:
        log("nenhuma matéria retornada, mantendo dados anteriores"); sys.exit(0)

    ordem = sorted(mats.values(), key=lambda m: m["apresentacao"], reverse=True)
    for m in ordem:
        old = cache.get(m["id"], {})
        m["relatores"] = old.get("relatores", [])
        m["rel_consulta"] = old.get("rel_consulta", "")
        m["autores_cod"] = autores_senadores(m["autor"], sen)

    # relatoria: primeiro as nunca consultadas (mais recentes antes), depois as consultadas há mais tempo
    hoje = date.today().isoformat()
    fila = [m for m in ordem if not m["rel_consulta"]] + sorted([m for m in ordem if m["rel_consulta"]], key=lambda m: m["rel_consulta"])
    feitas = 0
    for m in fila[:MAX_RELATORIAS]:
        m["relatores"] = relatores(m["id"]); m["rel_consulta"] = hoje; feitas += 1
        time.sleep(PAUSA)
    pend = sum(1 for m in ordem if not m["rel_consulta"])
    log(f"relatorias consultadas: {feitas}; ainda sem consulta: {pend}")

    usados = {c for m in ordem for c in m["relatores"] + m["autores_cod"]}
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
