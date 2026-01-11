import os
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
import re
import time

app = Flask(__name__)

# Configuração do banco de dados
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "piscina.db")

def executar_db(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = cursor.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return res

# --- 1. INTERFACE VISUAL COMPLETA (PAINEL MANUAL) ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        try:
            # A. CADASTRO MANUAL DE CLIENTE
            if 'nome_cliente' in request.form:
                nome = request.form.get('nome_cliente')
                endereco = request.form.get('endereco_cliente')
                executar_db("INSERT INTO clientes (nome, endereco) VALUES (?, ?)", (nome.title(), endereco))
            
            # B. LANÇAMENTO MANUAL DE SERVIÇO
            elif 'valor' in request.form:
                valor = float(request.form.get('valor').replace(',', '.'))
                cloro = float(request.form.get('cloro').replace(',', '.'))
                estoque_data = executar_db("SELECT preco_por_unidade FROM estoque WHERE nome_produto LIKE '%Cloro%'", fetch=True)
                custo_un = estoque_data[0][0] if estoque_data else 0
                custo_total = cloro * custo_un
                lucro = valor - custo_total
                executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, ?, ?, 'Pago')", 
                            (hoje, valor, custo_total, lucro))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE nome_produto LIKE '%Cloro%'", (cloro,))
            
            # C. REGISTRO DE GASOLINA / ROTA
            elif 'preco_gasolina' in request.form:
                km_ini = float(request.form.get('km_inicial'))
                p_gas = float(request.form.get('preco_gasolina').replace(',', '.'))
                executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km_ini, p_gas))

            # D. ATUALIZAÇÃO MANUAL DE ESTOQUE (COMPRA DE MATERIAL)
            elif 'compra_cloro' in request.form:
                qtd_nova = float(request.form.get('compra_cloro').replace(',', '.'))
                preco_pago = float(request.form.get('preco_pago').replace(',', '.'))
                novo_custo_un = preco_pago / qtd_nova
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ? WHERE nome_produto LIKE '%Cloro%'", (qtd_nova, novo_custo_un))
            
            return redirect(url_for('painel_controle'))
        except Exception as e:
            return f"Erro: {e}"

    # BUSCA DE DADOS PARA O DASHBOARD
    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    estoque = executar_db("SELECT quantidade_estoque FROM estoque WHERE nome_produto LIKE '%Cloro%'", fetch=True)
    servicos = executar_db("SELECT id, data_servico, valor_cobrado, lucro_liquido FROM historico_financeiro ORDER BY id DESC LIMIT 5", fetch=True)
    
    faturamento = resumo[0][0] if resumo[0][0] else 0
    lucro = resumo[0][1] if resumo[0][1] else 0
    qtd_cloro = estoque[0][0] if estoque else 0

    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>A.U.R.O.R.A - Gestão</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f4f7f9; margin: 0; padding-bottom: 40px; }
            .resumo-topo { background: #007aff; color: white; padding: 30px 20px; text-align: center; border-radius: 0 0 25px 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
            .grid-info { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: -20px 15px 20px 15px; }
            .mini-card { background: white; padding: 15px; border-radius: 15px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
            .secao { background: white; padding: 20px; border-radius: 20px; margin: 0 15px 20px 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
            input { width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-size: 16px; }
            .btn { width: 100%; padding: 15px; border: none; border-radius: 10px; font-weight: bold; font-size: 16px; color: white; cursor: pointer; margin-top: 5px; }
            .btn-servico { background: #34c759; } .btn-cliente { background: #ff9500; }
            .btn-estoque { background: #5856d6; } .btn-km { background: #ff3b30; }
            .item-hist { border-bottom: 1px solid #eee; padding: 10px 0; display: flex; justify-content: space-between; }
        </style>
    </head>
    <body>
        <div class="resumo-topo">
            <small style="opacity: 0.8;">LUCRO LÍQUIDO ACUMULADO</small>
            <h1 style="margin: 5px 0; font-size: 36px;">R$ {{lucro}}</h1>
            <p style="margin: 0; opacity: 0.9;">Faturamento Total: R$ {{faturamento}}</p>
        </div>

        <div class="grid-info">
            <div class="mini-card"><small>ESTOQUE CLORO</small><br><strong style="color:#007aff;">{{qtd_cloro}} kg</strong></div>
            <div class="mini-card"><small>STATUS</small><br><strong style="color:#34c759;">SISTEMA OK</strong></div>
        </div>

        <div class="secao">
            <h3 style="margin-top:0;">🚀 Novo Serviço</h3>
            <form method="POST">
                <input type="number" step="0.01" name="valor" placeholder="Valor do Serviço (R$)" required>
                <input type="number" step="0.1" name="cloro" placeholder="Cloro Gasto (kg)" required>
                <button type="submit" class="btn btn-servico">Salvar Serviço</button>
            </form>
        </div>

        <div class="secao">
            <h3 style="margin-top:0;">👤 Novo Cliente</h3>
            <form method="POST">
                <input type="text" name="nome_cliente" placeholder="Nome Completo" required>
                <input type="text" name="endereco_cliente" placeholder="Endereço" required>
                <button type="submit" class="btn btn-cliente">Cadastrar Cliente</button>
            </form>
        </div>

        <div class="secao">
            <h3 style="margin-top:0;">📦 Comprar Material</h3>
            <form method="POST">
                <input type="number" step="0.1" name="compra_cloro" placeholder="Qtd Adquirida (kg)" required>
                <input type="number" step="0.01" name="preco_pago" placeholder="Preço Total Pago (R$)" required>
                <button type="submit" class="btn btn-estoque">Atualizar Estoque</button>
            </form>
        </div>

        <div class="secao">
            <h3 style="margin-top:0;">⛽ Combustível / KM</h3>
            <form method="POST">
                <input type="number" name="km_inicial" placeholder="KM Inicial do Dia" required>
                <input type="number" step="0.01" name="preco_gasolina" placeholder="Preço da Gasolina (R$)" required>
                <button type="submit" class="btn btn-km">Registrar Saída</button>
            </form>
        </div>

        <h3 style="margin: 20px;">📊 Últimos Lançamentos</h3>
        <div class="secao">
            {% for s in servicos %}
            <div class="item-hist">
                <span>{{s[1]}}<br><small style="color:gray;">R$ {{s[2]}}</small></span>
                <span style="color:#34c759; font-weight:bold;">+ R$ {{s[3]}}</span>
            </div>
            {% endfor %}
        </div>
    </body>
    </html>
    """
    return render_template_string(html, lucro=f"{lucro:.2f}", faturamento=f"{faturamento:.2f}", qtd_cloro=f"{qtd_cloro:.1f}", servicos=servicos)

# --- 2. ROTA DE VOZ (SIRI / ATALHOS) ---
@app.route('/aurora', methods=['POST'])
def processar_comando():
    dados = request.json
    comando = dados.get('comando', '').lower()
    hoje = time.strftime('%Y-%m-%d')
    
    if "lucro" in comando or "ganhei" in comando:
        query = "SELECT SUM(lucro_liquido) FROM historico_financeiro WHERE data_servico >= date('now', '-7 days')"
        total = executar_db(query, fetch=True)[0][0] or 0
        return jsonify({"resposta": f"Na última semana seu lucro foi de {total:.2f} reais."})

    elif any(p in comando for p in ["concluí", "finalizar", "serviço"]):
        nums = re.findall(r"(\d+\.?\d*)", comando.replace(",", "."))
        if len(nums) >= 2:
            valor, cloro = float(nums[0]), float(nums[1])
            estoque_data = executar_db("SELECT preco_por_unidade FROM estoque WHERE nome_produto LIKE '%Cloro%'", fetch=True)
            custo_un = estoque_data[0][0] if estoque_data else 0
            lucro = valor - (cloro * custo_un)
            executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, ?, ?, 'Pago')", (hoje, valor, (cloro*custo_un), lucro))
            executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE nome_produto LIKE '%Cloro%'", (cloro,))
            return jsonify({"resposta": f"Serviço de {valor} reais salvo com sucesso."})

    return jsonify({"resposta": "Aurora pronta."})

# --- 3. EXCLUSÃO E WHATSAPP ---
@app.route('/excluir/<int:id>')
def excluir_registro(id):
    executar_db("DELETE FROM historico_financeiro WHERE id = ?", (id,))
    return redirect(url_for('painel_controle'))

@app.route('/whatsapp', methods=['POST'])
def whatsapp_cadastro():
    dados = request.json
    nome, endereco = dados.get('nome'), dados.get('endereco')
    if nome and endereco:
        executar_db("INSERT INTO clientes (nome, endereco) VALUES (?, ?)", (nome.title(), endereco))
        return jsonify({"status": "sucesso"}), 200
    return jsonify({"status": "erro"}), 400

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)