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

# --- ROTA PARA COMANDO DE VOZ (SIRI) ---
@app.route('/aurora', methods=['POST'])
def comando_voz():
    dados = request.get_json()
    comando = dados.get('comando', '').lower().replace(",", ".")
    hoje = time.strftime('%Y-%m-%d')
    respostas = []
    
    # 1. Lógica de KM e Gasolina (Início do Dia)
    if any(word in comando for word in ["começar", "início", "iniciar"]):
        # Busca KM (número grande) e Gasolina (número com ponto ex: 5.80)
        nums = re.findall(r"(\d+\.?\d*)", comando)
        if nums:
            km = float(nums[0])
            # Tenta achar um segundo número que seria o preço da gasolina
            p_gas = float(nums[1]) if len(nums) > 1 else PRECO_GASOLINA_PADRAO
            
            executar_db("INSERT INTO historico_financeiro (data_servico, status_pagamento, valor_cobrado) VALUES (?, ?, 0)", 
                        (hoje, f"KM_START:{km}|GAS:{p_gas}"))
            return jsonify({"resposta": f"Dia iniciado. KM: {km}, Gasolina: R${p_gas:.2f}."})

    # 2. Lógica de Finalização (Cálculo de Combustível)
    elif any(word in comando for word in ["finalizar", "encerrar"]):
        nums = re.findall(r"(\d+\.?\d*)", comando)
        if nums:
            km_f = float(nums[0])
            res = executar_db("SELECT status_pagamento FROM historico_financeiro WHERE data_servico = ? AND status_pagamento LIKE 'KM_START:%' ORDER BY id DESC LIMIT 1", (hoje,), fetch=True)
            if res:
                info_start = res[0][0] # Ex: "KM_START:120000|GAS:5.80"
                km_i = float(re.search(r"KM_START:(\d+\.?\d*)", info_start).group(1))
                try:
                    p_gas = float(re.search(r"GAS:(\d+\.?\d*)", info_start).group(1))
                except:
                    p_gas = PRECO_GASOLINA_PADRAO
                
                dist = km_f - km_i
                custo = (dist / KM_POR_LITRO) * p_gas
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                            (hoje, custo, -custo, f"Viagem: {dist}km"))
                return jsonify({"resposta": f"Encerrado. Rodou {dist}km. Gasto de combustível: R${custo:.2f}."})

    # 3. Lógica de Recebimento e Materiais (O "Coração" do Comando)
    custo_total_dia = 0
    materiais_detectados = []
    
    # Busca todos os produtos cadastrados para comparar com a voz
    produtos_estoque = executar_db("SELECT id, nome_produto, preco_por_unidade FROM estoque", fetch=True)
    
    # Detecta Recebimento
    if "recebi" in comando:
        val_recebido = re.search(r"recebi\s*(\d+\.?\d*)", comando)
        if val_recebido:
            v = float(val_recebido.group(1))
            executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, lucro_liquido, status_pagamento) VALUES (?, ?, ?, 'Pago')", (hoje, v, v))
            respostas.append(f"Recebido R${v:.2f}")

    # Detecta Uso de Materiais (Múltiplos)
    for p_id, p_nome, p_preco in produtos_estoque:
        nome_p = p_nome.lower()
        if nome_p in comando:
            # Busca o número que vem ANTES do nome do produto
            # Ex: "1.5 de cloro" ou "2 algicida"
            match = re.search(rf"(\d+\.?\d*)\s*(?:de|do|dos|da|das)?\s*{nome_p}", comando)
            if match:
                qtd = float(match.group(1))
                custo_item = qtd * p_preco
                custo_total_dia += custo_item
                # Baixa no estoque
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))
                # Lança o custo como uma saída
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                            (hoje, custo_item, -custo_item, f"Uso: {qtd} {p_nome}"))
                materiais_detectados.append(f"{qtd} de {p_nome}")

    if materiais_detectados:
        respostas.append(f"Materiais: {', '.join(materiais_detectados)}")
    
    if respostas:
        return jsonify({"resposta": ". ".join(respostas)})
            
    return jsonify({"resposta": "Aurora não entendeu. Tente dizer 'recebi [valor]' ou 'usei [quantidade] de [produto]'."})

# --- PAINEL DE CONTROLE (WEB) ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    if request.method == 'POST':
        try:
            # 1. LANÇAR SERVIÇO MANUAL
            if 'valor_servico' in request.form:
                valor = float(request.form.get('valor_servico').replace(',', '.'))
                produto_id = request.form.get('produto_id')
                qtd_usada = float(request.form.get('qtd_usada').replace(',', '.'))
                
                prod_data = executar_db("SELECT preco_por_unidade FROM estoque WHERE id = ?", (produto_id,), fetch=True)
                custo_un = prod_data[0][0] if prod_data else 0
                custo_total = qtd_usada * custo_un
                lucro = valor - custo_total
                
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, ?, ?, ?, 'Pago')", 
                            (hoje, valor, custo_total, lucro))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd_usada, produto_id))

            # 2. GASTO COM FERRAMENTAS
            elif 'valor_ferramenta' in request.form:
                valor_f = float(request.form.get('valor_ferramenta').replace(',', '.'))
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, 'Ferramenta')", 
                            (hoje, valor_f, -valor_f))

            # 3. ATUALIZAR ESTOQUE
            elif 'nome_prod' in request.form:
                nome = request.form.get('nome_prod').strip().title()
                qtd = float(request.form.get('qtd_compra').replace(',', '.'))
                preco = float(request.form.get('preco_total').replace(',', '.'))
                custo_un = preco / qtd
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?) ON CONFLICT(nome_produto) DO UPDATE SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ?", 
                            (nome, qtd, custo_un, qtd, custo_un))

            # 4. REGISTRO DE KM MANUAL
            elif 'km_inicial' in request.form:
                km = float(request.form.get('km_inicial'))
                p_gas = float(request.form.get('preco_gas').replace(',', '.'))
                executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km, p_gas))

            return redirect(url_for('painel_controle'))
        except Exception as e: return f"Erro: {e}"

    # BUSCA DE DADOS
    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    produtos = executar_db("SELECT id, nome_produto, quantidade_estoque FROM estoque", fetch=True)
    faturamento = resumo[0][0] if resumo[0][0] else 0
    lucro_real = resumo[0][1] if resumo[0][1] else 0

    # (Mantive a string HTML idêntica à sua solicitação de não mexer no HTML)
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
            .btn { width: 100%; padding: 16px; border: none; border-radius: 12px; font-weight: bold; color: white; cursor: pointer; }
            .btn-green { background: #34c759; } .btn-blue { background: #007aff; } .btn-red { background: #ff3b30; } .btn-purple { background: #5856d6; }
        </style>
    </head>
    <body>
        <div class="header">
            <small>LUCRO LÍQUIDO REAL</small>
            <h1 style="font-size: 42px; margin: 10px 0;">R$ {{ "%.2f"|format(lucro_real) }}</h1>
            <p style="margin:0; opacity:0.8;">Faturamento: R$ {{ "%.2f"|format(faturamento) }}</p>
        </div>

        <div class="card">
            <h3>🚀 Registrar Serviço</h3>
            <form method="POST">
                <input type="number" step="0.01" name="valor_servico" placeholder="Valor Cobrado (R$)" required>
                <select name="produto_id" required>
                    <option value="" disabled selected>Selecione o Produto</option>
                    {% for p in produtos %}<option value="{{p[0]}}">{{p[1]}} (Estoque: {{p[2]}})</option>{% endfor %}
                </select>
                <input type="number" step="0.1" name="qtd_usada" placeholder="Qtd Gasta" required>
                <button type="submit" class="btn btn-green">Salvar Trabalho</button>
            </form>
        </div>

        <div class="card">
            <h3>📦 Estoque / Compras</h3>
            <form method="POST">
                <input type="text" name="nome_prod" placeholder="Nome do Produto" required>
                <input type="number" step="0.1" name="qtd_compra" placeholder="Qtd Adquirida" required>
                <input type="number" step="0.01" name="preco_total" placeholder="Preço Total Pago" required>
                <button type="submit" class="btn btn-blue">Atualizar Estoque</button>
            </form>
        </div>

        <div class="card">
            <h3>⛽ Registro de KM / Saída</h3>
            <form method="POST">
                <input type="number" name="km_inicial" placeholder="KM Inicial" required>
                <input type="number" step="0.01" name="preco_gas" placeholder="Preço Gasolina (R$)" required>
                <button type="submit" class="btn btn-purple">Registrar Saída</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, faturamento=faturamento, lucro_real=lucro_real, produtos=produtos)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))