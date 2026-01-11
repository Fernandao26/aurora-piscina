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

# --- ROTA PARA COMANDO DE VOZ (SIRI / ATALHOS) ---
@app.route('/aurora', methods=['POST'])
def comando_voz():
    dados = request.get_json()
    if not dados: 
        return jsonify({"resposta": "Erro de conexão com o servidor."})
    
    comando = dados.get('comando', '').lower()
    hoje = time.strftime('%Y-%m-%d')

    # Busca todos os produtos para permitir escolher pelo índice
    estoque = executar_db("SELECT id, nome_produto, preco_por_unidade FROM estoque ORDER BY id", fetch=True)
    
    if not estoque:
        return jsonify({"resposta": "Nenhum produto cadastrado no estoque."})

    # Lógica de seleção de produto (Padrão: 1º da lista)
    idx = 0
    if "segundo" in comando or "número dois" in comando: idx = 1
    elif "terceiro" in comando or "número três" in comando: idx = 2
    elif "quarto" in comando or "número quatro" in comando: idx = 3
    
    if idx >= len(estoque): idx = 0 # Volta para o primeiro se não existir o escolhido
    
    p_id, p_nome, custo_un = estoque[idx]

    # --- COMANDO 1: REGISTRAR O RECEBIMENTO (DINHEIRO) ---
    # Frase: "Recebi 150 reais"
    if "recebi" in comando or "valor" in comando:
        nums = re.findall(r"(\d+[\.,]?\d*)", comando.replace(",", "."))
        if nums:
            valor = float(nums[0])
            executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, 0, ?, 'Pago')", 
                        (hoje, valor, valor))
            return jsonify({"resposta": f"Dinheiro de {valor} reais registrado!"})

    # --- COMANDO 2: USAR PRODUTO (BAIXA DE ESTOQUE) ---
    # Frase: "Usei 0.5 do primeiro" ou "Usei 0.2 do segundo"
    elif "usei" in comando or "gastei" in comando or "coloquei" in comando:
        nums = re.findall(r"(\d+[\.,]?\d*)", comando.replace(",", "."))
        if nums:
            qtd = float(nums[0])
            custo_total = qtd * custo_un
            # Abate o custo do lucro total
            executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, 0, ?, ?, 'Uso Material')", 
                        (hoje, custo_total, -custo_total))
            # Tira do estoque
            executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))
            return jsonify({"resposta": f"Baixado {qtd} de {p_nome}."})

    # --- COMANDO 3: COMPRAR PARA ESTOQUE ---
    # Frase: "Comprar 10 de estoque por 120 reais"
    elif "comprar" in comando:
        nums = re.findall(r"(\d+[\.,]?\d*)", comando.replace(",", "."))
        if len(nums) >= 2:
            qtd, preco_total = float(nums[0]), float(nums[1])
            novo_custo_un = preco_total / qtd
            executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ? WHERE id = ?", 
                        (qtd, novo_custo_un, p_id))
            return jsonify({"resposta": f"Estoque de {p_nome} atualizado."})

    # --- COMANDO 4: GASTOS GERAIS ---
    # Frase: "Gasto de 50 reais com gasolina"
    elif "gasto" in comando or "despesa" in comando:
        nums = re.findall(r"(\d+[\.,]?\d*)", comando.replace(",", "."))
        if nums:
            valor_gasto = float(nums[0])
            desc = comando.split("com ")[-1] if "com " in comando else "Voz"
            executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                        (hoje, valor_gasto, -valor_gasto, f"Voz: {desc}"))
            return jsonify({"resposta": f"Gasto de {valor_gasto} registrado."})

    return jsonify({"resposta": "Aurora não entendeu. Diga: Recebi, Usei ou Comprar."})

# --- PAINEL DE CONTROLE VISUAL ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        try:
            if 'valor_servico' in request.form:
                valor = float(request.form.get('valor_servico').replace(',', '.'))
                produto_id = request.form.get('produto_id')
                qtd_usada = float(request.form.get('qtd_usada').replace(',', '.'))
                prod_data =执行db("SELECT preco_por_unidade FROM estoque WHERE id = ?", (produto_id,), fetch=True)
                custo_un = prod_data[0][0] if prod_data else 0
                custo_total = qtd_usada * custo_un
                executar_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (1, ?, ?, ?, ?, 'Pago')", 
                            (hoje, valor, custo_total, (valor - custo_total)))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd_usada, produto_id))
            
            elif 'valor_ferramenta' in request.form:
                desc = request.form.get('desc_ferramenta')
                valor_f = float(request.form.get('valor_ferramenta').replace(',', '.'))
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                            (hoje, valor_f, -valor_f, f"Gasto: {desc}"))

            elif 'nome_prod' in request.form:
                nome = request.form.get('nome_prod').title()
                qtd = float(request.form.get('qtd_compra').replace(',', '.'))
                preco = float(request.form.get('preco_total').replace(',', '.'))
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?) ON CONFLICT(nome_produto) DO UPDATE SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ?", 
                            (nome, qtd, (preco/qtd), qtd, (preco/qtd)))

            return redirect(url_for('painel_controle'))
        except Exception as e:
            return f"Erro: {e}"

    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    produtos = executar_db("SELECT id, nome_produto, quantidade_estoque FROM estoque ORDER BY id", fetch=True)
    faturamento = resumo[0][0] if resumo[0][0] else 0
    lucro_real = resumo[0][1] if resumo[0][1] else 0

    html = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>A.U.R.O.R.A - Gestão</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f4f7f9; margin: 0; padding-bottom: 50px; }
            .header { background: #007aff; color: white; padding: 35px 20px; text-align: center; border-radius: 0 0 30px 30px; }
            .card { background: white; padding: 20px; border-radius: 20px; margin: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
            input, select { width: 100%; padding: 14px; margin: 8px 0; border: 1px solid #ddd; border-radius: 12px; font-size: 16px; box-sizing: border-box; }
            .btn { width: 100%; padding: 16px; border: none; border-radius: 12px; font-weight: bold; font-size: 16px; color: white; cursor: pointer; }
            .btn-green { background: #34c759; } .btn-blue { background: #007aff; } .btn-red { background: #ff3b30; }
        </style>
    </head>
    <body>
        <div class="header">
            <small>LUCRO LÍQUIDO ACUMULADO</small>
            <h1 style="font-size: 42px; margin: 10px 0;">R$ {{ "%.2f"|format(lucro_real) }}</h1>
            <p>Faturamento: R$ {{ "%.2f"|format(faturamento) }}</p>
        </div>
        <div class="card">
            <h3>🚀 Registrar Serviço Manual</h3>
            <form method="POST">
                <input type="number" step="0.01" name="valor_servico" placeholder="Valor Recebido (R$)" required>
                <select name="produto_id" required>
                    <option value="" disabled selected>Escolher Produto</option>
                    {% for p in produtos %}
                    <option value="{{p[0]}}">{{loop.index}}º - {{p[1]}} (Qtd: {{p[2]}})</option>
                    {% endfor %}
                </select>
                <input type="number" step="0.01" name="qtd_usada" placeholder="Quantidade usada" required>
                <button type="submit" class="btn btn-green">Salvar no Sistema</button>
            </form>
        </div>
        <div class="card">
            <h3>📦 Estoque Atual</h3>
            <ul style="list-style: none; padding: 0;">
                {% for p in produtos %}
                <li style="padding: 10px 0; border-bottom: 1px solid #eee;">
                    <strong>{{loop.index}}º {{p[1]}}:</strong> {{p[2]}} em estoque
                </li>
                {% endfor %}
            </ul>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, faturamento=faturamento, lucro_real=lucro_real, produtos=produtos)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)