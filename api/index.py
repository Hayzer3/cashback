from flask import Flask, request, jsonify
import logging
from flask_cors import CORS
import oracledb
import os
from dotenv import load_dotenv

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
CORS(app)

# Configurações do Banco (Use Variáveis de Ambiente na Vercel!)
load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_DSN = os.getenv("DB_DSN")

def executar_plsql(evento_id):
    # Conecta no modo Thin (importante para Vercel)
    conn = oracledb.connect(user=DB_USER, password=DB_PASS, dsn=DB_DSN)
    cursor = conn.cursor()

    # O Bloco solicitado pelo Checkpoint
    plsql = """
    DECLARE
        CURSOR c_participantes IS
            SELECT i.ID, i.USUARIO_ID, i.VALOR_PAGO, i.TIPO 
            FROM INSCRICOES i 
            WHERE i.STATUS = 'PRESENT' AND i.EVENTO_ID = :evento_id;
        v_total_presencas NUMBER;
        v_percentual      NUMBER;
    BEGIN
        FOR r IN c_participantes LOOP
            -- Subquery de contagem
            SELECT COUNT(*) INTO v_total_presencas 
            FROM INSCRICOES 
            WHERE USUARIO_ID = r.USUARIO_ID AND STATUS = 'PRESENT';

            -- Regra de Negócio (Escalonamento)
            IF v_total_presencas > 3 THEN
                v_percentual := 0.25;
            ELSIF r.TIPO = 'VIP' THEN
                v_percentual := 0.20;
            ELSE
                v_percentual := 0.10;
            END IF;

            -- Atualiza Saldo
            UPDATE USUARIOS 
            SET SALDO = SALDO + (r.VALOR_PAGO * v_percentual)
            WHERE ID = r.USUARIO_ID;
            
            -- Log de Auditoria
            INSERT INTO LOG_AUDITORIA (ID, INSCRICAO_ID, MOTIVO, DATA)
            VALUES (SEQ_LOG.NEXTVAL, r.ID, 'Cashback Processado', SYSDATE);
        END LOOP;
        COMMIT;
    END;
    """
    try:
        cursor.execute(plsql, evento_id=evento_id)
        return True
    except Exception as e:
        app.logger.error(f"Erro PLSQL: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

@app.route('/api/processar', methods=['POST'])
def processar():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    
    evento_id = data.get('evento_id')
    if not evento_id:
        return jsonify({"error": "evento_id is required"}), 400
    
    if executar_plsql(evento_id):
        return jsonify({"message": f"Cashback processado com sucesso para evento {evento_id}!"}), 200
    else:
        return jsonify({"error": "Erro ao processar no banco."}), 500

# Necessário para a Vercel
def handler(event, context):
    return app(event, context)

if __name__ == "__main__":
    app.run(debug=True)