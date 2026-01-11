import os
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
import re
import time

app = Flask(__name__)

# Configuração do banco de dados
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "piscina.db")

# --- CONFIGURAÇÕES DO IRMÃO ---
NUMERO_IRMAO = "5512996204209"
KM_POR_LITRO = 10.0
PRECO_GASOLINA_PADRAO = 5.80

def executar_db(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = cursor.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return res

# --- FUNÇÃO PARA CRIAR TABELAS SE NÃO EXISTIREM ---
def inicializar_banco():
    executar_db("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            whatsapp TEXT,
            endereco TEXT,
            valor_mensal REAL
        )
    """)
    executar_db("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            data_visita TEXT,
            status TEXT,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        )
    """)
    executar_db("""
        CREATE TABLE IF NOT EXISTS historico_financeiro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_servico TEXT,
            valor_cobrado REAL,
            custo_material REAL,
            lucro_liquido REAL,
            status_pagamento TEXT
        )
    """)
    executar_db("""
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_produto TEXT UNIQUE,
            quantidade_estoque REAL,
            preco_por_unidade REAL
        )
    """)
    executar_db("""
        CREATE TABLE IF NOT EXISTS registro_km (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_registro TEXT,
            km_inicial REAL,
            preco_gasolina REAL
        )
    """)

inicializar_banco()

# --- ROTA PARA COMANDO DE VOZ (SIRI) ---
@app.route('/aurora', methods=['POST'])
def comando_voz():
    dados = request.get_json()
    comando = dados.get('comando', '').lower().replace(",", ".")
    hoje = time.strftime('%Y-%m-%d')
    
    # 1. NOVO PRODUTO (NÃO EXISTENTE NO ESTOQUE)
    if "cadastrar" in comando or "novo produto" in comando:
        # Tenta extrair o nome (palavra após 'produto' ou 'cadastrar')
        # Ex: "cadastrar novo produto cloro quantidade 10 preço 100"
        nums = re.findall(r"(\d+\.?\d*)", comando)
        nome_match = re.search(r"(?:produto|cadastrar)\s+([a-zA-Záéíóúãõç]+)", comando)
        
        if nome_match and len(nums) >= 2:
            nome_p = nome_match.group(1).title()
            qtd = float(nums[0])
            preco_total = float(nums[1])
            preco_un = preco_total / qtd
            
            try:
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?)", 
                            (nome_p, qtd, preco_un))
                return jsonify({"resposta": f"Produto {nome_p} cadastrado com {qtd} unidades no valor de {preco_total} reais."})
            except:
                return jsonify({"resposta": f"Produto {nome_p} já existe. Use o comando de adicionar."})

    # 2. Iniciar Dia (KM + Agenda)
    if any(word in comando for word in ["começar", "início", "iniciar"]):
        nums = re.findall(r"(\d+\.?\d*)", comando)
        if nums:
            km = float(nums[0])
            p_gas = float(nums[1]) if len(nums) > 1 else PRECO_GASOLINA_PADRAO
            executar_db("INSERT INTO historico_financeiro (data_servico, status_pagamento, valor_cobrado) VALUES (?, ?, 0)", 
                        (hoje, f"KM_START:{km}|GAS:{p_gas}"))
            
            agenda_hoje = executar_db("""
                SELECT c.nome FROM agenda a 
                JOIN clientes c ON a.cliente_id = c.id 
                WHERE a.data_visita = ?
            """, (hoje,), fetch=True)
            
            msg_agenda = " Clientes de hoje: " + ", ".join([r[0] for r in agenda_hoje]) if agenda_hoje else " Sem agendamentos."
            return jsonify({"resposta": f"Dia iniciado com {km} KM.{msg_agenda}"})

    # 3. Finalizar Dia (Cálculo Combustível)
    elif any(word in comando for word in ["finalizar", "encerrar"]):
        nums = re.findall(r"(\d+\.?\d*)", comando)
        if nums:
            km_f = float(nums[0])
            res = executar_db("SELECT status_pagamento FROM historico_financeiro WHERE data_servico = ? AND status_pagamento LIKE 'KM_START:%' ORDER BY id DESC LIMIT 1", (hoje,), fetch=True)
            if res:
                info_start = res[0][0]
                km_i = float(re.search(r"KM_START:(\d+\.?\d*)", info_start).group(1))
                try: p_gas = float(re.search(r"GAS:(\d+\.?\d*)", info_start).group(1))
                except: p_gas = PRECO_GASOLINA_PADRAO
                
                dist = km_f - km_i
                custo_comb = (dist / KM_POR_LITRO) * p_gas
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                            (hoje, custo_comb, -custo_comb, f"Viagem: {dist}km"))
                return jsonify({"resposta": f"Dia encerrado. Rodou {dist}km. Gasto gasolina: R${custo_comb:.2f}."})

    # 4. Gerenciar Estoque EXISTENTE (Entrada e Saída)
    produtos_estoque = executar_db("SELECT id, nome_produto, preco_por_unidade FROM estoque", fetch=True)
    for p_id, p_nome, p_preco in produtos_estoque:
        nome_p = p_nome.lower()
        if nome_p in comando:
            match = re.search(rf"(\d+\.?\d*)\s*(?:de|do|dos|da|das)?\s*{nome_p}", comando)
            if match:
                qtd = float(match.group(1))
                if any(word in comando for word in ["adicionar", "entrou", "estoque", "comprar"]):
                    executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque + ? WHERE id = ?", (qtd, p_id))
                    return jsonify({"resposta": f"Entrada de {qtd} de {p_nome} registrada."})
                else:
                    custo_item = qtd * p_preco
                    executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))
                    executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                                (hoje, custo_item, -custo_item, f"Uso: {qtd} {p_nome}"))
                    return jsonify({"resposta": f"Gasto de {qtd} de {p_nome} abatido."})

    # 5. Recebimento
    if "recebi" in comando:
        val = re.search(r"recebi\s*(\d+\.?\d*)", comando)
        if val:
            v = float(val.group(1))
            executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, lucro_liquido, status_pagamento) VALUES (?, ?, ?, 'Pago')", (hoje, v, v))
            return jsonify({"resposta": f"Registrado recebimento de R${v:.2f}"})

    return jsonify({"resposta": "Aurora não entendeu o comando."})

# --- PAINEL DE CONTROLE (WEB) ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    mes_atual = time.strftime('%Y-%m')
    
    if request.method == 'POST':
        try:
            if 'cadastrar_cliente' in request.form:
                executar_db("INSERT INTO clientes (nome, whatsapp, endereco, valor_mensal) VALUES (?, ?, ?, ?)", 
                            (request.form.get('nome_cliente'), request.form.get('whatsapp'), request.form.get('endereco'), float(request.form.get('valor_mensal').replace(',', '.'))))
            elif 'agendar_servico' in request.form:
                executar_db("INSERT INTO agenda (cliente_id, data_visita, status) VALUES (?, ?, 'Agendado')", (request.form.get('cliente_id'), request.form.get('data_visita')))
            elif 'valor_servico' in request.form:
                valor = float(request.form.get('valor_servico').replace(',', '.'))
                p_id = request.form.get('produto_id')
                qtd = float(request.form.get('qtd_usada').replace(',', '.'))
                prod_data = executar_db("SELECT preco_por_unidade FROM estoque WHERE id = ?", (p_id,), fetch=True)
                custo_t = (qtd * prod_data[0][0]) if prod_data else 0
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, ?, ?, ?, 'Pago')", (hoje, valor, custo_t, valor - custo_t))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))
            elif 'nome_prod' in request.form:
                n, q, p = request.form.get('nome_prod').strip().title(), float(request.form.get('qtd_compra').replace(',', '.')), float(request.form.get('preco_total').replace(',', '.'))
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?) ON CONFLICT(nome_produto) DO UPDATE SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ?", (n, q, p/q, q, p/q))
            elif 'km_inicial' in request.form:
                km = float(request.form.get('km_inicial'))
                pg = float(request.form.get('preco_gas').replace(',', '.'))
                executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km, pg))
            return redirect(url_for('painel_controle'))
        except Exception as e: return f"Erro: {e}"

    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    resumo_mes = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro WHERE data_servico LIKE ?", (f"{mes_atual}%",), fetch=True)
    produtos = executar_db("SELECT id, nome_produto, quantidade_estoque FROM estoque", fetch=True)
    lista_c = executar_db("SELECT id, nome FROM clientes", fetch=True)
    
    fat_mes = resumo_mes[0][0] or 0
    lucro_mes = resumo_mes[0][1] or 0
    msg_whats = f"Relatório Aurora - Mês {mes_atual}:%0AFaturamento: R${fat_mes:.2f}%0ALucro Líquido: R${lucro_mes:.2f}"
    link_whats = f"https://wa.me/{NUMERO_IRMAO}?text={msg_whats}"

    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>A.U.R.O.R.A - Painel Profissional</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f0f2f5; margin: 0; padding-bottom: 40px; }
            .header { background: #007aff; color: white; padding: 30px 20px; text-align: center; border-radius: 0 0 25px 25px; }
            .card { background: white; padding: 20px; border-radius: 18px; margin: 15px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h3 { margin-top: 0; color: #333; font-size: 18px; border-left: 4px solid #007aff; padding-left: 10px; }
            input, select { width: 100%; padding: 12px; margin: 6px 0; border: 1px solid #ddd; border-radius: 10px; font-size: 16px; box-sizing: border-box; }
            .btn { width: 100%; padding: 14px; border: none; border-radius: 10px; font-weight: bold; color: white; cursor: pointer; text-decoration: none; display: block; text-align: center; margin-top: 10px; }
            .btn-green { background: #34c759; } .btn-blue { background: #007aff; } .btn-orange { background: #ff9500; } .btn-purple { background: #5856d6; }
        </style>
    </head>
    <body>
        <div class="header">
            <small>LUCRO LÍQUIDO ACUMULADO</small>
            <h1 style="font-size: 38px; margin: 5px 0;">R$ {{ "%.2f"|format(resumo[0][1] or 0) }}</h1>
            <a href="{{ link_whats }}" target="_blank" class="btn btn-green" style="width: auto; display: inline-block; padding: 10px 20px;">📲 Relatório WhatsApp</a>
        </div>

        <div class="card">
            <h3>👤 Novo Cliente</h3>
            <form method="POST">
                <input type="hidden" name="cadastrar_cliente" value="1">
                <input type="text" name="nome_cliente" placeholder="Nome do Cliente" required>
                <input type="text" name="whatsapp" placeholder="WhatsApp">
                <input type="text" name="endereco" placeholder="Endereço">
                <input type="number" step="0.01" name="valor_mensal" placeholder="Valor Mensal (R$)" required>
                <button type="submit" class="btn btn-orange">Cadastrar Cliente</button>
            </form>
        </div>

        <div class="card">
            <h3>📅 Agendar Visita</h3>
            <form method="POST">
                <input type="hidden" name="agendar_servico" value="1">
                <select name="cliente_id" required>
                    <option value="" disabled selected>Selecione o Cliente</option>
                    {% for c in lista_c %}<option value="{{c[0]}}">{{c[1]}}</option>{% endfor %}
                </select>
                <input type="date" name="data_visita" required>
                <button type="submit" class="btn btn-blue">Confirmar Agendamento</button>
            </form>
        </div>

        <div class="card">
            <h3>🚀 Registrar Serviço Hoje</h3>
            <form method="POST">
                <input type="number" step="0.01" name="valor_servico" placeholder="Valor Cobrado (R$)" required>
                <select name="produto_id" required>
                    <option value="" disabled selected>Produto Usado</option>
                    {% for p in produtos %}<option value="{{p[0]}}">{{p[1]}} (Disponível: {{p[2]}})</option>{% endfor %}
                </select>
                <input type="number" step="0.1" name="qtd_usada" placeholder="Quantidade Gasta" required>
                <button type="submit" class="btn btn-green">Salvar e Abater Estoque</button>
            </form>
        </div>

        <div class="card">
            <h3>📦 Comprar/Atualizar Material</h3>
            <form method="POST">
                <input type="text" name="nome_prod" placeholder="Nome do Produto" required>
                <input type="number" step="0.1" name="qtd_compra" placeholder="Qtd Comprada" required>
                <input type="number" step="0.01" name="preco_total" placeholder="Preço Total Pago" required>
                <button type="submit" class="btn btn-blue">Atualizar Estoque</button>
            </form>
        </div>

        <div class="card">
            <h3>⛽ Saída / KM</h3>
            <form method="POST">
                <input type="number" name="km_inicial" placeholder="KM Inicial" required>
                <input type="number" step="0.01" name="preco_gas" placeholder="Preço Gasolina" required>
                <button type="submit" class="btn btn-purple">Registrar KM</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, resumo=resumo, produtos=produtos, lista_c=lista_c, link_whats=link_whats)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))