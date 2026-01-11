import os
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
import re
import time

app = Flask(__name__)

# Configuração do banco de dados
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "piscina.db")

# --- CONFIGURAÇÃO PADRÃO DO VEÍCULO ---
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
    # Tabela de Clientes
    executar_db("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            whatsapp TEXT,
            endereco TEXT,
            valor_mensal REAL
        )
    """)
    # Tabela de Agenda
    executar_db("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            data_visita TEXT,
            status TEXT,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        )
    """)
    # Tabela de Histórico Financeiro
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
    # Tabela de Estoque
    executar_db("""
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_produto TEXT UNIQUE,
            quantidade_estoque REAL,
            preco_por_unidade REAL
        )
    """)

# Inicializa as tabelas ao rodar o script
inicializar_banco()

# --- ROTA PARA COMANDO DE VOZ (SIRI) ---
@app.route('/aurora', methods=['POST'])
def comando_voz():
    dados = request.get_json()
    comando = dados.get('comando', '').lower().replace(",", ".")
    hoje = time.strftime('%Y-%m-%d')
    respostas = []
    
    # 1. Lógica de Início (KM + Agenda)
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
            
            msg_agenda = " Seus clientes de hoje são: " + ", ".join([r[0] for r in agenda_hoje]) if agenda_hoje else " Sem agendamentos hoje."
            return jsonify({"resposta": f"Dia iniciado. KM: {km}.{msg_agenda}"})

    # 2. Recebimento Simples
    if "recebi" in comando:
        val = re.search(r"recebi\s*(\d+\.?\d*)", comando)
        if val:
            v = float(val.group(1))
            executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, lucro_liquido, status_pagamento) VALUES (?, ?, ?, 'Pago')", (hoje, v, v))
            return jsonify({"resposta": f"Registrado recebimento de R${v:.2f}"})

    return jsonify({"resposta": "Aurora não entendeu o comando de voz."})

# --- PAINEL DE CONTROLE (WEB) ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    if request.method == 'POST':
        try:
            # Novo Cliente
            if 'cadastrar_cliente' in request.form:
                nome = request.form.get('nome_cliente')
                whatsapp = request.form.get('whatsapp')
                endereco = request.form.get('endereco')
                valor_m = float(request.form.get('valor_mensal').replace(',', '.'))
                executar_db("INSERT INTO clientes (nome, whatsapp, endereco, valor_mensal) VALUES (?, ?, ?, ?)", (nome, whatsapp, endereco, valor_m))

            # Novo Agendamento
            elif 'agendar_servico' in request.form:
                c_id = request.form.get('cliente_id')
                data_v = request.form.get('data_visita')
                executar_db("INSERT INTO agenda (cliente_id, data_visita, status) VALUES (?, ?, 'Agendado')", (c_id, data_v))

            # Registrar Serviço Manual
            elif 'valor_servico' in request.form:
                valor = float(request.form.get('valor_servico').replace(',', '.'))
                p_id = request.form.get('produto_id')
                qtd = float(request.form.get('qtd_usada').replace(',', '.'))
                prod_data = executar_db("SELECT preco_por_unidade FROM estoque WHERE id = ?", (p_id,), fetch=True)
                custo_t = (qtd * prod_data[0][0]) if prod_data else 0
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, ?, ?, ?, 'Pago')", (hoje, valor, custo_t, valor - custo_t))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))

            # Estoque
            elif 'nome_prod' in request.form:
                n = request.form.get('nome_prod').strip().title()
                q = float(request.form.get('qtd_compra').replace(',', '.'))
                p = float(request.form.get('preco_total').replace(',', '.'))
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?) ON CONFLICT(nome_produto) DO UPDATE SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ?", (n, q, p/q, q, p/q))

            return redirect(url_for('painel_controle'))
        except Exception as e: return f"Erro no Processamento: {e}"

    # Dados para carregar a página
    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    produtos = executar_db("SELECT id, nome_produto, quantidade_estoque FROM estoque", fetch=True)
    lista_c = executar_db("SELECT id, nome FROM clientes", fetch=True)
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>A.U.R.O.R.A - Painel Profissional</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f0f2f5; margin: 0; padding-bottom: 40px; }
            .header { background: #007aff; color: white; padding: 30px 20px; text-align: center; border-radius: 0 0 25px 25px; }
            .card { background: white; padding: 20px; border-radius: 18px; margin: 15px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h3 { margin-top: 0; color: #333; font-size: 18px; border-left: 4px solid #007aff; padding-left: 10px; }
            input, select { width: 100%; padding: 12px; margin: 6px 0; border: 1px solid #ddd; border-radius: 10px; font-size: 16px; box-sizing: border-box; }
            .btn { width: 100%; padding: 14px; border: none; border-radius: 10px; font-weight: bold; color: white; cursor: pointer; transition: 0.3s; }
            .btn-green { background: #34c759; } .btn-blue { background: #007aff; } .btn-orange { background: #ff9500; }
        </style>
    </head>
    <body>
        <div class="header">
            <small>LUCRO LÍQUIDO ACUMULADO</small>
            <h1 style="font-size: 38px; margin: 5px 0;">R$ {{ "%.2f"|format(resumo[0][1] or 0) }}</h1>
            <p style="margin:0; opacity:0.8;">Faturamento: R$ {{ "%.2f"|format(resumo[0][0] or 0) }}</p>
        </div>

        <div class="card">
            <h3>👤 Novo Cliente</h3>
            <form method="POST">
                <input type="hidden" name="cadastrar_cliente" value="1">
                <input type="text" name="nome_cliente" placeholder="Nome do Cliente" required>
                <input type="text" name="whatsapp" placeholder="WhatsApp">
                <input type="text" name="endereco" placeholder="Endereço">
                <input type="number" step="0.01" name="valor_mensal" placeholder="Valor Mensal (R$)" required>
                <button type="submit" class="btn btn-orange">Cadastrar no Banco</button>
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
            <h3>📦 Comprar Material</h3>
            <form method="POST">
                <input type="text" name="nome_prod" placeholder="Nome do Produto" required>
                <input type="number" step="0.1" name="qtd_compra" placeholder="Qtd Comprada" required>
                <input type="number" step="0.01" name="preco_total" placeholder="Preço Total Pago" required>
                <button type="submit" class="btn btn-blue">Atualizar Estoque</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, resumo=resumo, produtos=produtos, lista_c=lista_c)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))