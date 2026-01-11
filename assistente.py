import pandas as pd
import speech_recognition as sr
import os
import time
import sqlite3
import re
from google import genai
from gtts import gTTS
import pygame 

# --- CONFIGURAÇÕES ---
r = sr.Recognizer()
NOME_USUARIO = "Gleison"
AUDIO_FILE = 'temp_audio_aurora.mp3'
LIMITE_ESTOQUE_CRITICO = 2.0 

GEMINI_API_KEY = "AIzaSyCM3Bnj9u7CTr8CESYFUmoznEbpBWrfnnY" 
client = None

# --- FUNÇÕES AUXILIARES ---

def extrair_numero(texto):
    """Extrai apenas números de uma frase, tratando vírgulas e unidades."""
    if not texto: return None
    texto = texto.lower().replace("r$", "").replace("reais", "").replace("quilos", "").replace("kilos", "").replace("ponto", ".")
    numeros = re.findall(r"(\d+\.?\d*)", texto.replace(",", "."))
    return float(numeros[0]) if numeros else None

def consultar_db(query, params=()):
    try:
        conn = sqlite3.connect('piscina.db')
        cursor = conn.cursor()
        cursor.execute(query, params)
        resultado = cursor.fetchall()
        conn.close()
        return resultado
    except Exception as e:
        print(f"Erro SQL: {e}"); return []

def salvar_no_db(query, params=()):
    try:
        conn = sqlite3.connect('piscina.db', timeout=10)
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Erro ao salvar: {e}"); return False

# --- FUNÇÕES DE VOZ E IA ---

def falar(texto):
    print(f"AURORA: {texto}")
    try:
        tts = gTTS(text=texto, lang='pt', slow=False)
        tts.save(AUDIO_FILE)
        pygame.mixer.init()
        pygame.mixer.music.load(AUDIO_FILE)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy(): time.sleep(0.1)
        pygame.mixer.quit()
        if os.path.exists(AUDIO_FILE): os.remove(AUDIO_FILE)
    except Exception as e: print(f"Erro voz: {e}")

def escutar_comando():
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=1.2)
        print("Ouvindo...")
        try:
            audio = r.listen(source, timeout=6)
            return r.recognize_google(audio, language='pt-BR').lower()
        except: return None

def conversar_com_gemini(prompt):
    global client
    if client:
        try:
            response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return response.text
        except: return "ERRO_CONEXAO"
    return "IA offline."

# --- LÓGICA DE NEGÓCIO ---

def executar_acao(comando_usuario):
    # 1. SAÍDA
    if any(p in comando_usuario for p in ["desligar", "encerrar", "sair", "parar"]):
        falar(f"Sistemas encerrados. Até logo, {NOME_USUARIO}.")
        return True

    # 2. QUILOMETRAGEM (INICIAL/FINAL)
    elif "quilometragem" in comando_usuario or "marcar km" in comando_usuario:
        falar("É o quilômetro inicial ou final?")
        tipo = escutar_comando()
        falar("Qual o valor no painel?")
        resp_km = escutar_comando()
        km_valor = extrair_numero(resp_km)
        
        if km_valor:
            hoje = time.strftime('%Y-%m-%d')
            if tipo and "inicial" in tipo:
                salvar_no_db("INSERT INTO registro_km (data_registro, km_inicial) VALUES (?, ?)", (hoje, km_valor))
                falar(f"KM inicial de {km_valor} registrado.")
            else:
                salvar_no_db("UPDATE registro_km SET km_final = ?, total_rodado = ? - km_inicial WHERE data_registro = ?", (km_valor, km_valor, hoje))
                falar(f"KM final registrado. Bom descanso!")
        else: falar(f"Não entendi o número. Ouvi: {resp_km}")

    # 3. FERRAMENTAS (MOTO)
    elif "ferramentas" in comando_usuario or "material" in comando_usuario:
        falar("Conferindo equipamentos...")
        ferramentas = consultar_db("SELECT nome_ferramenta, estado_conservacao FROM ferramentas")
        if ferramentas:
            for f in ferramentas:
                falar(f"{f[0]}, estado: {f[1]}")
            falar("Está tudo na moto?")
            confirma = escutar_comando()
            if confirma and ("sim" in confirma or "tá" in confirma): 
                falar("Moto carregada. Boa viagem!")
            else: 
                falar("Melhor verificar o que falta antes de sair.")
        else: falar("Nenhuma ferramenta cadastrada no banco.")

    # 4. FINALIZAR SERVIÇO (LUCRO REAL + ESTOQUE + FINANCEIRO)
    elif any(p in comando_usuario for p in ["concluí", "terminei", "finalizar", "baixar"]):
        falar("Qual cliente você finalizou?")
        nome_cliente_voz = escutar_comando()
        if nome_cliente_voz:
            hoje = time.strftime('%Y-%m-%d')
            cliente = consultar_db("SELECT id, nome FROM clientes WHERE nome LIKE ?", (f"%{nome_cliente_voz}%",))
            if cliente:
                id_cli, nome_cli = cliente[0]
                falar(f"Confirmado: {nome_cli}. Quanto cobrou?")
                resp_valor = escutar_comando()
                valor = extrair_numero(resp_valor)
                
                falar("Quanto de cloro usou?")
                resp_qtd = escutar_comando()
                qtd = extrair_numero(resp_qtd)
                
                if valor is not None and qtd is not None:
                    # Cálculo de Lucro Real
                    dados_custo = consultar_db("SELECT preco_por_unidade FROM estoque WHERE nome_produto LIKE '%Cloro%'")
                    custo_material = (qtd * dados_custo[0][0]) if dados_custo else 0
                    lucro_real = valor - custo_material

                    # Registrar Financeiro Detalhado
                    salvar_no_db("INSERT INTO historico_financeiro (cliente_id, data_servico, valor_cobrado, custo_material, lucro_liquido, status_pagamento) VALUES (?, ?, ?, ?, ?, 'Pendente')", (id_cli, hoje, valor, custo_material, lucro_real))
                    
                    # Atualizar Estoque e Agenda
                    salvar_no_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque - ? WHERE nome_produto LIKE '%Cloro%'", (qtd,))
                    salvar_no_db("UPDATE agenda SET status = 'Concluído' WHERE cliente_id = ? AND data_visita = ?", (id_cli, hoje))
                    
                    falar(f"Serviço finalizado. Custo de material: {custo_material:.2f}. Seu lucro foi de {lucro_real:.2f} reais.")
                else:
                    falar(f"Não entendi os valores. Ouvi {resp_valor} e {resp_qtd}.")
            else: falar(f"Cliente {nome_cliente_voz} não encontrado.")
        return False

    # 5. ABASTECER ESTOQUE
    elif "comprei" in comando_usuario or "abastecer" in comando_usuario:
        falar("Quanto você pagou no total?")
        total = extrair_numero(escutar_comando())
        falar("Quantos quilos comprou?")
        quilos = extrair_numero(escutar_comando())
        if total and quilos:
            novo_custo = total / quilos
            salvar_no_db("UPDATE estoque SET quantidade_estoque = quantidade_estoque + ?, preco_por_unidade = ? WHERE nome_produto LIKE '%Cloro%'", (quilos, novo_custo))
            falar(f"Estoque atualizado! Custo por quilo: {novo_custo:.2f} reais.")
        else: falar("Erro ao processar valores da compra.")

    # 6. COBRANÇA (QUEM DEVE)
    elif "quem me deve" in comando_usuario:
        devedores = consultar_db("SELECT c.nome, SUM(h.valor_cobrado) FROM historico_financeiro h JOIN clientes c ON h.cliente_id = c.id WHERE h.status_pagamento = 'Pendente' GROUP BY c.nome")
        if devedores:
            lista = ", ".join([f"{d[0]} deve {d[1]} reais" for d in devedores])
            falar(f"Pendentes: {lista}.")
        else: falar("Tudo pago por enquanto!")
        return False

    # 7. BAIXA DE PAGAMENTO (Recebi dinheiro)
    elif any(p in comando_usuario for p in ["pagou", "recebi", "dinheiro", "baixa"]):
        falar("Quem fez o pagamento?")
        nome_cli = escutar_comando()
        if nome_cli:
            sucesso = salvar_no_db("UPDATE historico_financeiro SET status_pagamento = 'Pago' WHERE cliente_id = (SELECT id FROM clientes WHERE nome LIKE ?) AND status_pagamento = 'Pendente'", (f"%{nome_cli}%",))
            if sucesso:
                falar(f"Ótimo! Registrei o pagamento de {nome_cli}. Saldo atualizado.")
            else:
                falar("Não encontrei pendências para esse nome.")
        return False

    # 8. RESUMO DO DIA (Faturamento vs Lucro Real)
    elif "resumo" in comando_usuario or "balanço" in comando_usuario:
        hoje = time.strftime('%Y-%m-%d')
        total_dia = consultar_db("SELECT SUM(valor_cobrado), SUM(lucro_liquido) FROM historico_financeiro WHERE data_servico = ?", (hoje,))
        km_dia = consultar_db("SELECT total_rodado FROM registro_km WHERE data_registro = ?", (hoje,))
        
        faturamento = total_dia[0][0] if total_dia[0][0] else 0
        lucro = total_dia[0][1] if total_dia[0][1] else 0
        km = km_dia[0][0] if km_dia and km_dia[0][0] else 0
        
        falar(f"Gleison, hoje você faturou {faturamento} reais. Descontando materiais, o lucro real foi de {lucro} reais. Você rodou {km} quilômetros.")
        return False

    # 9. IA / CONVERSA GERAL
    else:
        res = conversar_com_gemini(comando_usuario)
        if res != "ERRO_CONEXAO":
            falar(res)
    
    return False

# --- INÍCIO ---
if __name__ == "__main__":
    try: 
        client = genai.Client(api_key=GEMINI_API_KEY)
    except: 
        client = None

    falar(f"AURORA online. Tudo pronto, {NOME_USUARIO}.")
    
    encerrar = False
    while not encerrar:
        cmd = escutar_comando()
        if cmd: 
            encerrar = executar_acao(cmd)