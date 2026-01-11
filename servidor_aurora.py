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
    
    # 1. Lógica de KM, Gasolina e Agenda (Início do Dia)
    if any(word in comando for word in ["começar", "início", "iniciar"]):
        nums = re.findall(r"(\d+\.?\d*)", comando)
        if nums:
            km = float(nums[0])
            p_gas = float(nums[1]) if len(nums) > 1 else PRECO_GASOLINA_PADRAO
            executar_db("INSERT INTO historico_financeiro (data_servico, status_pagamento, valor_cobrado) VALUES (?, ?, 0)", 
                        (hoje, f"KM_START:{km}|GAS:{p_gas}"))
            
            # Consulta a agenda do dia
            agenda_hoje = executar_db("""
                SELECT c.nome FROM agenda a 
                JOIN clientes c ON a.cliente_id = c.id 
                WHERE a.data_visita = ?
            """, (hoje,), fetch=True)
            
            msg_agenda = ""
            if agenda_hoje:
                clientes = ", ".join([row[0] for row in agenda_hoje])
                msg_agenda = f" Seus clientes de hoje são: {clientes}."
            else:
                msg_agenda = " Você não tem agendamentos para hoje."
                
            return jsonify({"resposta": f"Dia iniciado. KM: {km}, Gasolina: R${p_gas:.2f}.{msg_agenda}"})

    # 2. Lógica de Finalização
    elif any(word in comando for word in ["finalizar", "encerrar"]):
        nums = re.findall(r"(\d+\.?\d*)", comando)
        if nums:
            km_f = float(nums[0])
            res = executar_db("SELECT status_pagamento FROM historico_financeiro WHERE data_servico = ? AND status_pagamento LIKE 'KM_START:%' ORDER BY id DESC LIMIT 1", (hoje,), fetch=True)
            if res:
                info_start = res[0][0]
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

    # 3. Lógica de Recebimento e Materiais
    produtos_estoque = executar_db("SELECT id, nome_produto, preco_por_unidade FROM estoque", fetch=True)
    
    if "recebi" in comando:
        val_recebido = re.search(r"recebi\s*(\d+\.?\d*)", comando)
        if val_recebido:
            v = float(val_recebido.group(1))
            executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, lucro_liquido, status_pagamento) VALUES (?, ?, ?, 'Pago')", (hoje, v, v))
            respostas.append(f"Recebido R${v:.2f}")

    for p_id, p_nome, p_preco in produtos_estoque:
        nome_p = p_nome.lower()
        if nome_p in comando:
            match = re.search(rf"(\d+\.?\d*)\s*(?:de|do|dos|da|das)?\s*{nome_p}", comando)
            if match:
                qtd = float(match.group(1))
                custo_item = qtd * p_preco
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, ?)", 
                            (hoje, custo_item, -custo_item, f"Uso: {qtd} {p_nome}"))
                materiais_detectados.append(f"{qtd} de {p_nome}")

    if respostas:
        return jsonify({"resposta": ". ".join(respostas)})
            
    return jsonify({"resposta": "Aurora não entendeu."})

# --- PAINEL DE CONTROLE (WEB) ---
@app.route('/painel', methods=['GET', 'POST'])
def painel_controle():
    hoje = time.strftime('%Y-%m-%d')
    if request.method == 'POST':
        try:
            if 'cadastrar_cliente' in request.form:
                nome = request.form.get('nome_cliente')
                whatsapp = request.form.get('whatsapp')
                endereco = request.form.get('endereco')
                valor_m = float(request.form.get('valor_mensal').replace(',', '.'))
                executar_db("INSERT INTO clientes (nome, whatsapp, endereco, valor_mensal) VALUES (?, ?, ?, ?)", (nome, whatsapp, endereco, valor_m))

            elif 'agendar_servico' in request.form:
                c_id = request.form.get('cliente_id')
                data_v = request.form.get('data_visita')
                executar_db("INSERT INTO agenda (cliente_id, data_visita, status) VALUES (?, ?, 'Agendado')", (c_id, data_v))

            elif 'valor_servico' in request.form:
                valor = float(request.form.get('valor_servico').replace(',', '.'))
                p_id = request.form.get('produto_id')
                qtd = float(request.form.get('qtd_usada').replace(',', '.'))
                prod_data = executar_db("SELECT preco_por_unidade FROM estoque WHERE id = ?", (p_id,), fetch=True)
                custo_un = prod_data[0][0] if prod_data else 0
                custo_t = qtd * custo_un
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, ?, ?, ?, 'Pago')", (hoje, valor, custo_t, valor - custo_t))
                executar_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE id = ?", (qtd, p_id))

            elif 'valor_ferramenta' in request.form:
                vf = float(request.form.get('valor_ferramenta').replace(',', '.'))
                executar_db("INSERT INTO historico_financeiro (data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, 0, ?, ?, 'Ferramenta')", (hoje, vf, -vf))

            elif 'nome_prod' in request.form:
                n = request.form.get('nome_prod').strip().title()
                q = float(request.form.get('qtd_compra').replace(',', '.'))
                p = float(request.form.get('preco_total').replace(',', '.'))
                executar_db("INSERT INTO estoque (nome_produto, quantidade_estoque, preco_por_unidade) VALUES (?, ?, ?) ON CONFLICT(nome_produto) DO UPDATE SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ?", (n, q, p/q, q, p/q))

            elif 'km_inicial' in request.form:
                km = float(request.form.get('km_inicial'))
                pg = float(request.form.get('preco_gas').replace(',', '.'))
                executar_db("INSERT INTO registro_km (data_registro, km_inicial, preco_gasolina) VALUES (?, ?, ?)", (hoje, km, pg))

            return redirect(url_for('painel_controle'))
        except Exception as e: return f"Erro: {e}"

    resumo = executar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro", fetch=True)
    produtos = executar_db("SELECT id, nome_produto, quantidade_estoque FROM estoque", fetch=True)
    lista_c = executar_db("SELECT id, nome FROM clientes", fetch=True)
    
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
            .btn-green { background: #34c759; } .btn-blue { background: #007aff; } .btn-purple { background: #5856d6; } .btn-orange { background: #ff9500; }
        </style>
    </head>
    <body>
        <div class="header">
            <small>LUCRO LÍQUIDO REAL</small>
            <h1 style="font-size: 42px; margin: 10px 0;">R$ {{ "%.2f"|format(resumo[0][1] or 0) }}</h1>
            <p style="margin:0; opacity:0.8;">Faturamento: R$ {{ "%.2f"|format(resumo[0][0] or 0) }}</p>
        </div>

        <div class="card">
            <h3>👤 Novo Cliente</h3>
            <form method="POST">
                <input type="hidden" name="cadastrar_cliente" value="1"><input type="text" name="nome_cliente" placeholder="Nome Completo" required>
                <input type="text" name="whatsapp" placeholder="WhatsApp"><input type="text" name="endereco" placeholder="Endereço">
                <input type="number" step="0.01" name="valor_mensal" placeholder="Valor Mensal (R$)" required>
                <button type="submit" class="btn btn-orange">Cadastrar Cliente</button>
            </form>
        </div>

        <div class="card">
            <h3>📅 Agendar Visita</h3>
            <form method="POST">
                <input type="hidden" name="agendar_servico" value="1">
                <select name="cliente_id" required><option value="" disabled selected>Selecione o Cliente</option>
                {% for c in lista_c %}<option value="{{c[0]}}">{{c[1]}}</option>{% endfor %}</select>
                <input type="date" name="data_visita" required><button type="submit" class="btn btn-blue">Confirmar Agendamento</button>
            </form>
        </div>

        <div class="card">
            <h3>🚀 Registrar Serviço</h3>
            <form method="POST">
                <input type="number" step="0.01" name="valor_servico" placeholder="Valor Cobrado (R$)" required>
                <select name="produto_id" required><option value="" disabled selected>Produto</option>
                {% for p in produtos %}<option value="{{p[0]}}">{{p[1]}} (Esq: {{p[2]}})</option>{% endfor %}</select>
                <input type="number" step="0.1" name="qtd_usada" placeholder="Qtd Gasta" required><button type="submit" class="btn btn-green">Salvar Trabalho</button>
            </form>
        </div>

        <div class="card">
            <h3>📦 Estoque</h3>
            <form method="POST">
                <input type="text" name="nome_prod" placeholder="Produto" required><input type="number" step="0.1" name="qtd_compra" placeholder="Qtd" required>
                <input type="number" step="0.01" name="preco_total" placeholder="Preço Total" required><button type="submit" class="btn btn-blue">Atualizar</button>
            </form>
        </div>

        <div class="card">
            <h3>⛽ Saída / KM</h3>
            <form method="POST">
                <input type="number" name="km_inicial" placeholder="KM Inicial" required><input type="number" step="0.01" name="preco_gas" placeholder="Preço Gasolina" required>
                <button type="submit" class="btn btn-purple">Registrar</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, resumo=resumo, produtos=produtos, lista_c=lista_c)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))