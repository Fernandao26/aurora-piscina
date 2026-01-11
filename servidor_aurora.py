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

@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        try:
            # 1. LANÇAR SERVIÇO (COM SELEÇÃO DE QUALQUER PRODUTO)
            if 'valor_servico' in request.form:
                valor = float(request.form.get('valor_servico').replace(',', '.'))
                produto_id = request.form.get('produto_id')
                qtd_usada = float(request.form.get('qtd_usada').replace(',', '.'))
                
                prod_data = executar_db("SELECT preco_por_unidade FROM estoque WHERE id = ?", (produto_id,), fetch=True)
                custo_un = prod_data[0][0] if prod_data else 0
                custo_total = qtd_usada * custo_un
                lucro = valor - custo_total
                
                executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, ?, ?, 'Pago')", 
                            (hoje, valor, custo_total, lucro))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd_usada, produto_id))
            
            # 2. GASTO COM FERRAMENTAS (ABATE DIRETO DO LUCRO)
            elif 'valor_ferramenta' in request.form:
                desc = request.form.get('desc_ferramenta')
                valor_f = float(request.form.get('valor_ferramenta').replace(',', '.'))
                # Registra como custo (valor cobrado 0, lucro negativo)
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, 'Ferramenta')", 
                            (hoje, valor_f, -valor_f))

            # 3. COMPRAR/CADASTRAR MATERIAL (QUALQUER PRODUTO)
            elif 'nome_prod' in request.form:
                nome = request.form.get('nome_prod').title()
                qtd = float(request.form.get('qtd_compra').replace(',', '.'))
                preco = float(request.form.get('preco_total').replace(',', '.'))
                custo_un = preco / qtd
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?) ON CONFLICT(nome_produto) DO UPDATE SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ?", 
                            (nome, qtd, custo_un, qtd, custo_un))

            # 4. REGISTRO DE KM
            elif 'km_inicial' in request.form:
                km = float(request.form.get('km_inicial'))
                p_gas = float(request.form.get('preco_gas').replace(',', '.'))
                executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km, p_gas))

            return redirect(url_for('painel_controle'))
        except Exception as e:
            return f"Erro: {e}"

    # BUSCA DE DADOS
    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    produtos = executar_db("SELECT id, nome_produto, quantidade_estoque FROM estoque", fetch=True)
    faturamento = resumo[0][0] if resumo[0][0] else 0
    lucro_real = resumo[0][1] if resumo[0][1] else 0

    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>A.U.R.O.R.A - Gestão Total</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f4f7f9; margin: 0; padding-bottom: 50px; }
            .header { background: #007aff; color: white; padding: 35px 20px; text-align: center; border-radius: 0 0 30px 30px; }
            .card { background: white; padding: 20px; border-radius: 20px; margin: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
            input, select { width: 100%; padding: 14px; margin: 8px 0; border: 1px solid #ddd; border-radius: 12px; font-size: 16px; box-sizing: border-box; }
            .btn { width: 100%; padding: 16px; border: none; border-radius: 12px; font-weight: bold; font-size: 16px; color: white; cursor: pointer; }
            .btn-green { background: #34c759; } .btn-blue { background: #007aff; } .btn-red { background: #ff3b30; } .btn-purple { background: #5856d6; }
            h3 { margin-top: 0; color: #1c1c1e; display: flex; align-items: center; gap: 8px; }
        </style>
    </head>
    <body>
        <div class="header">
            <small style="text-transform: uppercase; letter-spacing: 1px;">Lucro Real (Limpo)</small>
            <h1 style="font-size: 42px; margin: 10px 0;">R$ {{ "%.2f"|format(lucro_real) }}</h1>
            <p>Faturamento: R$ {{ "%.2f"|format(faturamento) }}</p>
        </div>

        <div class="card">
            <h3>🚀 Novo Serviço</h3>
            <form method="POST">
                <input type="number" step="0.01" name="valor_servico" placeholder="Valor Cobrado (R$)" required>
                <select name="produto_id">
                    {% for p in produtos %}
                    <option value="{{p[0]}}">{{p[1]}} (Disponível: {{p[2]}})</option>
                    {% endfor %}
                </select>
                <input type="number" step="0.1" name="qtd_usada" placeholder="Quantidade Usada" required>
                <button type="submit" class="btn btn-green">Salvar Trabalho</button>
            </form>
        </div>

        <div class="card">
            <h3>🛠️ Gastos com Ferramentas</h3>
            <form method="POST">
                <input type="text" name="desc_ferramenta" placeholder="Ex: Peneira, Filtro, Mangueira" required>
                <input type="number" step="0.01" name="valor_ferramenta" placeholder="Valor Pago (R$)" required>
                <button type="submit" class="btn btn-red">Registrar Despesa</button>
            </form>
        </div>

        <div class="card">
            <h3>📦 Comprar Material</h3>
            <form method="POST">
                <input type="text" name="nome_prod" placeholder="Nome (Ex: Algicida, Cloro, Barrilha)" required>
                <input type="number" step="0.1" name="qtd_compra" placeholder="Qtd Total (kg ou L)" required>
                <input type="number" step="0.01" name="preco_total" placeholder="Preço Total Pago" required>
                <button type="submit" class="btn btn-blue">Atualizar Estoque</button>
            </form>
        </div>

        <div class="card">
            <h3>⛽ Combustível / KM</h3>
            <form method="POST">
                <input type="number" name="km_inicial" placeholder="KM Inicial" required>
                <input type="number" step="0.01" name="preco_gas" placeholder="Preço Litro (R$)" required>
                <button type="submit" class="btn btn-purple">Registrar Rota</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, faturamento=faturamento, lucro_real=lucro_real, produtos=produtos)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)