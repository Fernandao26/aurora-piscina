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

# --- 1. INTERFACE VISUAL COM PAINEL DE LUCRO E FORMULÁRIOS ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        try:
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

    # BUSCA O LUCRO TOTAL E FATURAMENTO PARA O PAINEL SUPERIOR
    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    faturamento_total = resumo[0][0] if resumo[0][0] else 0
    lucro_total = resumo[0][1] if resumo[0][1] else 0

    servicos = executar_db("SELECT id, data_servico, valor_cobrado, lucro_liquido, status_pagamento FROM historico_financeiro ORDER BY id DESC LIMIT 10", fetch=True)
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>A.U.R.O.R.A - Painel</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f0f2f5; padding: 15px; margin: 0; }
            .resumo-card { background: #007aff; color: white; padding: 20px; border-radius: 0 0 20px 20px; text-align: center; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,122,255,0.3); }
            .card { background: white; padding: 15px; border-radius: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); margin-bottom: 20px; }
            input { width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; font-size: 16px; }
            .btn { background: #007aff; color: white; width: 100%; padding: 12px; border: none; border-radius: 8px; font-weight: bold; margin-top: 5px; cursor: pointer; }
            .item-lista { background: white; padding: 12px; border-radius: 10px; margin-bottom: 8px; border-left: 5px solid #34c759; display: flex; justify-content: space-between; align-items: center; }
            .btn-del { color: #ff3b30; text-decoration: none; font-size: 13px; font-weight: bold; }
            h2, h3 { color: #1c1c1e; margin-left: 5px; }
        </style>
    </head>
    <body>
        <div class="resumo-card">
            <p style="margin:0; opacity: 0.8; font-size: 14px;">Lucro Líquido Total</p>
            <h1 style="margin:5px 0; font-size: 32px;">R$ {{lucro_total}}</h1>
            <small>Faturamento: R$ {{faturamento_total}}</small>
        </div>

        <h2>⛽ Iniciar Rota</h2>
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

        <h3>📊 Histórico (Últimos 10)</h3>
        {% for s in servicos %}
        <div class="item-lista">
            <div>
                <small style="color: #8e8e93;">{{s[1]}}</small><br>
                <strong>R${{s[2]}}</strong> <span style="color: #34c759; font-size: 12px;">(Lucro R${{s[3]}})</span>
            </div>
            <a href="/excluir/{{s[0]}}" class="btn-del" onclick="return confirm('Apagar?')">Excluir</a>
        </div>
        {% endfor %}
    </body>
    </html>
    """
    return render_template_string(html, servicos=servicos, lucro_total=f"{lucro_total:.2f}", faturamento_total=f"{faturamento_total:.2f}")

# --- 2. ROTA DE EXCLUSÃO ---
@app.route('/excluir/<int:id>')
def excluir_registro(id):
    executar_db("DELETE FROM historico_financeiro WHERE id = ?", (id,))
    return redirect(url_for('painel_controle'))

# --- 3. ROTA DE COMANDO (VOZ / ATALHOS IPHONE) ---
@app.route('/aurora', methods=['POST'])
def processar_comando():
    dados = request.json
    comando = dados.get('comando', '').lower()
    hoje = time.strftime('%Y-%m-%d')
    
    # KM Inicial
    if "quilometragem" in comando or "rota" in comando:
        nums = re.findall(r"(\d+\.?\d*)", comando.replace(",", "."))
        if len(nums) >= 2:
            km, gas = float(nums[0]), float(nums[1])
            executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km, gas))
            return jsonify({"resposta": f"Rota iniciada! KM {km} e Gasolina a R${gas}."})

    # Consulta de Lucro da Semana (NOVA LÓGICA)
    elif "lucro" in comando or "resumo" in comando or "ganhei" in comando:
        query = "SELECT SUM(lucro_liquido) FROM historico_financeiro WHERE data_servico >= date('now', '-7 days')"
        resultado = executar_db(query, fetch=True)
        total_semana = resultado[0][0] if resultado[0][0] else 0
        return jsonify({"resposta": f"Na última semana, o seu lucro líquido foi de {total_semana:.2f} reais. Bom trabalho!"})

    # Finalizar Serviço
    elif any(p in comando for p in ["concluí", "terminei", "finalizar", "serviço"]):
        nums = re.findall(r"(\d+\.?\d*)", comando.replace(",", "."))
        if len(nums) >= 2:
            valor, cloro = float(nums[0]), float(nums[1])
            custo_un = executar_db("SELECT preco_por_unidade FROM estoque WHERE nome_produto LIKE '%Cloro%'", fetch=True)[0][0]
            custo_total = cloro * custo_un
            lucro = valor - custo_total
            executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, ?, ?, 'Pendente')", (hoje, valor, custo_total, lucro))
            executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE nome_produto LIKE '%Cloro%'", (cloro,))
            return jsonify({"resposta": f"Serviço de {valor} reais registrado. Lucro líquido de {lucro:.2f} reais."})

    return jsonify({"resposta": "Comando recebido pela Aurora."})

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