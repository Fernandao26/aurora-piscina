import os
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
import re
import time

app = Flask(__name__)

# Configuração do banco de dados
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "piscina.db")

# --- CONFIGURAÇÃO DO VEÍCULO ---
KM_POR_LITRO = 10.0
PRECO_GASOLINA = 5.80

def executar_db(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = cursor.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return res

@app.route('/aurora', methods=['POST'])
def comando_voz():
    dados = request.get_json()
    comando = dados.get('comando', '').lower()
    hoje = time.strftime('%Y-%m-%d')
    
    # Lógica de KM
    if "começar" in comando or "início" in comando:
        nums = re.findall(r"(\d+)", comando)
        if nums:
            km = float(nums[-1])
            executar_db("INSERT INTO historico_financeiro (data_servico, status_pagamento, valor_cobrado) VALUES (?, ?, 0)", (hoje, f"KM_START:{km}"))
            return jsonify({"resposta": f"Iniciado com {km} KM."})
            
    elif "finalizar" in comando or "encerrar" in comando:
        nums = re.findall(r"(\d+)", comando)
        if nums:
            km_f = float(nums[-1])
            res = executar_db("SELECT status_pagamento FROM historico_financeiro WHERE data_servico = ? AND status_pagamento LIKE 'KM_START:%' ORDER BY id DESC LIMIT 1", (hoje,), fetch=True)
            if res:
                km_i = float(res[0][0].split(":")[-1])
                dist = km_f - km_i
                custo = (dist / KM_POR_LITRO) * PRECO_GASOLINA
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", (hoje, custo, -custo, f"Viagem: {dist}km"))
                return jsonify({"resposta": f"Rodou {dist}km. Gasto de R${custo:.2f}."})

    # Lógica de Recebimento e Uso (Simplificada)
    estoque = executar_db("SELECT id, nome_produto, preco_por_unidade FROM estoque ORDER BY id", fetch=True)
    if "recebi" in comando:
        nums = re.findall(r"(\d+[\.,]?\d*)", comando.replace(",", "."))
        if nums:
            v = float(nums[0])
            executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, lucro_liquido, status_pagamento) VALUES (?, ?, ?, 'Pago')", (hoje, v, v))
            return jsonify({"resposta": f"Recebido {v} reais."})
            
    return jsonify({"resposta": "Aurora não entendeu."})

# --- PAINEL DE CONTROLE MANUAL ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    if request.method == 'POST':
        try:
            # 1. Registrar Serviço Manual
            if 'valor_servico' in request.form:
                valor = float(request.form.get('valor_servico').replace(',', '.'))
                p_id = request.form.get('produto_id')
                qtd = float(request.form.get('qtd_usada').replace(',', '.'))
                res = executar_db("SELECT preco_por_unidade FROM estoque WHERE id = ?", (p_id,), fetch=True)
                custo_un = res[0][0] if res else 0
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, ?, ?, ?, 'Pago')", 
                            (hoje, valor, (qtd*custo_un), (valor-(qtd*custo_un))))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))

            # 2. Registrar Gasto Manual (Gasolina/Outros)
            elif 'valor_gasto' in request.form:
                valor_g = float(request.form.get('valor_gasto').replace(',', '.'))
                desc = request.form.get('desc_gasto')
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                            (hoje, valor_g, -valor_g, f"Gasto: {desc}"))

            # 3. Cadastrar/Repor Estoque
            elif 'nome_prod' in request.form:
                nome = request.form.get('nome_prod').title()
                qtd = float(request.form.get('qtd_compra'))
                preco = float(request.form.get('preco_total'))
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?) ON CONFLICT(nome_produto) DO UPDATE SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ?", 
                            (nome, qtd, (preco/qtd), qtd, (preco/qtd)))

            return redirect(url_for('painel_controle'))
        except Exception as e: return f"Erro: {e}"

    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    produtos = executar_db("SELECT id, nome_produto, quantidade_estoque FROM estoque ORDER BY id", fetch=True)
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Aurora - Painel</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f4f7f9; margin: 0; padding-bottom: 50px; }
            .header { background: #007aff; color: white; padding: 40px 20px; text-align: center; border-radius: 0 0 25px 25px; }
            .card { background: white; padding: 20px; border-radius: 15px; margin: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
            input, select { width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; }
            .btn { width: 100%; padding: 15px; border: none; border-radius: 10px; color: white; font-weight: bold; cursor: pointer; margin-top: 10px; }
            .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        </style>
    </head>
    <body>
        <div class="header">
            <small>LUCRO ACUMULADO</small>
            <h1>R$ {{ "%.2f"|format(lucro) }}</h1>
        </div>

        <div class="card">
            <h3>🚀 Novo Serviço (Manual)</h3>
            <form method="POST">
                <input type="number" step="0.01" name="valor_servico" placeholder="Valor Recebido (R$)" required>
                <select name="produto_id">
                    {% for p in produtos %}<option value="{{p[0]}}">{{loop.index}}º - {{p[1]}}</option>{% endfor %}
                </select>
                <input type="number" step="0.01" name="qtd_usada" placeholder="Qtd de produto usada" required>
                <button type="submit" class="btn" style="background: #34c759;">Salvar Serviço</button>
            </form>
        </div>

        <div class="card">
            <h3>💸 Registrar Gasto (Extra)</h3>
            <form method="POST">
                <input type="text" name="desc_gasto" placeholder="Ex: Gasolina, Almoço, Peça" required>
                <input type="number" step="0.01" name="valor_gasto" placeholder="Valor (R$)" required>
                <button type="submit" class="btn" style="background: #ff3b30;">Registrar Gasto</button>
            </form>
        </div>

        <div class="card">
            <h3>📦 Gerenciar Estoque</h3>
            <form method="POST">
                <input type="text" name="nome_prod" placeholder="Nome do Produto" required>
                <div class="grid">
                    <input type="number" step="0.01" name="qtd_compra" placeholder="Qtd Comprada" required>
                    <input type="number" step="0.01" name="preco_total" placeholder="Preço Total" required>
                </div>
                <button type="submit" class="btn" style="background: #007aff;">Cadastrar/Atualizar</button>
            </form>
            <hr>
            {% for p in produtos %}
                <p style="margin: 5px 0;"><strong>{{loop.index}}º {{p[1]}}:</strong> {{p[2]}} em estoque</p>
            {% endfor %}
        </div>
    </body>
    </html>
    """
    return render_template_string(html, lucro=(resumo[0][1] or 0), produtos=produtos)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))