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

# --- 1. INTERFACE VISUAL COM FORMULÁRIO DE SERVIÇO E GASOLINA ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        try:
            # Verifica se é um cadastro de serviço ou de gasolina
            if 'valor' in request.form:
                valor = float(request.form.get('valor').replace(',', '.'))
                cloro = float(request.form.get('cloro').replace(',', '.'))
                custo_un = executar_db("SELECT preco_por_unidade FROM estoque WHERE nome_produto LIKE '%Cloro%'", fetch=True)[0][0]
                custo_total = cloro * custo_un
                lucro = valor - custo_total
                executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, ?, ?, 'Pendente')", 
                            (hoje, valor, custo_total, lucro))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE nome_produto LIKE '%Cloro%'", (cloro,))
            
            elif 'preco_gasolina' in request.form:
                km_ini = float(request.form.get('km_inicial'))
                p_gas = float(request.form.get('preco_gasolina').replace(',', '.'))
                executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km_ini, p_gas))
            
            return redirect(url_for('painel_controle'))
        except Exception as e:
            return f"Erro: {e}"

    servicos = executar_db("SELECT id, data_servico, valor_cobrado, lucro_liquido, status_pagamento FROM historico_financeiro ORDER BY id DESC LIMIT 10", fetch=True)
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>A.U.R.O.R.A - Painel</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f0f2f5; padding: 15px; }
            .card { background: white; padding: 15px; border-radius: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); margin-bottom: 20px; }
            input { width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; font-size: 16px; }
            .btn { background: #007aff; color: white; width: 100%; padding: 12px; border: none; border-radius: 8px; font-weight: bold; margin-top: 5px; }
            .item-lista { background: white; padding: 12px; border-radius: 10px; margin-bottom: 8px; border-left: 5px solid #34c759; }
            .btn-del { color: #ff3b30; text-decoration: none; font-size: 13px; font-weight: bold; }
        </style>
    </head>
    <body>
        <h2>⛽ Iniciar Rota (KM + Gasolina)</h2>
        <div class="card">
            <form method="POST">
                <input type="number" name="km_inicial" placeholder="KM Inicial" required>
                <input type="number" step="0.01" name="preco_gasolina" placeholder="Preço do Litro (R$)" required>
                <button type="submit" class="btn" style="background: #5856d6;">Abrir Dia</button>
            </form>
        </div>

        <h2>🚀 Novo Serviço</h2>
        <div class="card">
            <form method="POST">
                <input type="number" step="0.01" name="valor" placeholder="Valor (R$)" required>
                <input type="number" step="0.1" name="cloro" placeholder="Cloro (kg)" required>
                <button type="submit" class="btn">Salvar Serviço</button>
            </form>
        </div>

        <h3>📊 Histórico</h3>
        {% for s in servicos %}
        <div class="item-lista">
            <div><strong>{{s[1]}}</strong> | R${{s[2]}} (Lucro: R${{s[3]}})</div>
            <a href="/excluir/{{s[0]}}" class="btn-del" onclick="return confirm('Apagar?')">Excluir</a>
        </div>
        {% endfor %}
    </body>
    </html>
    """
    return render_template_string(html, servicos=servicos)

# --- 2. ROTA DE EXCLUSÃO ---
@app.route('/excluir/<int:id>')
def excluir_registro(id):
    executar_db("DELETE FROM historico_financeiro WHERE id = ?", (id,))
    return redirect(url_for('painel_controle'))

# --- 3. ROTA DE COMANDO (VOZ / OFFLINE) COM GASOLINA ---
@app.route('/aurora', methods=['POST'])
def processar_comando():
    dados = request.json
    comando = dados.get('comando', '').lower()
    hoje = time.strftime('%Y-%m-%d')
    
    # KM Inicial com Preço da Gasolina
    if "quilometragem" in comando and "inicial" in comando:
        nums = re.findall(r"(\d+\.?\d*)", comando.replace(",", "."))
        if len(nums) >= 2:
            km, gas = float(nums[0]), float(nums[1])
            executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km, gas))
            return jsonify({"resposta": f"Rota iniciada! KM {km} e Gasolina a R${gas}."})

    # Finalizar Serviço (Lucro + Estoque)
    elif any(p in comando for p in ["concluí", "terminei", "finalizar"]):
        nums = re.findall(r"(\d+\.?\d*)", comando.replace(",", "."))
        if len(nums) >= 2:
            valor, cloro = float(nums[0]), float(nums[1])
            custo_un = executar_db("SELECT preco_por_unidade FROM estoque WHERE nome_produto LIKE '%Cloro%'", fetch=True)[0][0]
            lucro = valor - (cloro * custo_un)
            executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, ?, ?, 'Pendente')", (hoje, valor, (cloro * custo_un), lucro))
            executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE nome_produto LIKE '%Cloro%'", (cloro,))
            return jsonify({"resposta": f"Registrado! Lucro: R${lucro:.2f}."})

    return jsonify({"resposta": "Comando recebido."})

# --- 4. WHATSAPP ---
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