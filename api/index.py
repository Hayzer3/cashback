from flask import Flask, render_template, request
import oracledb
import os
from dotenv import load_dotenv

load_dotenv()

# Configuração essencial para a Vercel achar a pasta templates
template_dir = os.path.abspath(os.path.dirname(__file__)) + '/templates'
app = Flask(__name__, template_folder=template_dir)

def get_db_connection():
    return oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dsn=os.getenv("DB_DSN")
    )

def buscar_saldos():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ID, NOME, NVL(SALDO, 0) FROM USUARIOS ORDER BY ID")
                return cur.fetchall()
    except:
        return []

def buscar_historico():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT TO_CHAR(DATA, 'DD/MM HH24:MI:SS'), MOTIVO FROM LOG_AUDITORIA ORDER BY ID DESC FETCH FIRST 6 ROWS ONLY")
                return cur.fetchall()
    except:
        return []

@app.route('/')
def index():
    return render_template('index.html', usuarios=buscar_saldos(), historico=buscar_historico())

@app.route('/comprar', methods=['POST'])
def comprar():
    usuario_id = request.form.get('usuario_id')
    evento_id = request.form.get('evento_id')
    valor = float(request.form.get('valor'))
    tipo = request.form.get('tipo')
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT NOME FROM USUARIOS WHERE ID = :1", [usuario_id])
                user_row = cursor.fetchone()
                if not user_row: raise Exception("Usuário não encontrado.")
                
                cursor.execute("SELECT NVL(MAX(ID), 0) + 1 FROM INSCRICOES")
                novo_id = cursor.fetchone()[0]

                cursor.execute("""
                    INSERT INTO INSCRICOES (ID, USUARIO_ID, EVENTO_ID, STATUS, VALOR_PAGO, TIPO) 
                    VALUES (:1, :2, :3, 'PRESENT', :4, :5)
                """, [novo_id, usuario_id, evento_id, valor, tipo])
                
                cursor.execute("""
                    INSERT INTO LOG_AUDITORIA (ID, INSCRICAO_ID, MOTIVO, DATA) 
                    VALUES (SEQ_LOG.NEXTVAL, :1, :2, SYSDATE)
                """, [novo_id, f"Compra R$ {valor:.2f} ({tipo}) no Evento {evento_id}"])
                conn.commit()

        return render_template('index.html', mensagem=f"Ingresso BulbaCash comprado para o usuário {usuario_id}!", usuarios=buscar_saldos(), historico=buscar_historico())
    except Exception as e:
        return render_template('index.html', erro=f"Erro na compra: {e}", usuarios=buscar_saldos(), historico=buscar_historico())

@app.route('/processar', methods=['POST'])
def processar():
    evento_id = request.form.get('evento_id')
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                total_out = cursor.var(oracledb.NUMBER)
                
                plsql = """
                DECLARE
                    CURSOR c_participantes IS
                        SELECT i.ID, i.USUARIO_ID, i.VALOR_PAGO, i.TIPO 
                        FROM INSCRICOES i WHERE i.STATUS = 'PRESENT' AND i.EVENTO_ID = :evento_id;
                    v_total_presencas NUMBER;
                    v_percentual      NUMBER;
                    v_cashback_atual  NUMBER;
                    v_total_geral     NUMBER := 0;
                BEGIN
                    FOR r IN c_participantes LOOP
                        SELECT COUNT(*) INTO v_total_presencas FROM INSCRICOES 
                        WHERE USUARIO_ID = r.USUARIO_ID AND STATUS = 'PRESENT';

                        IF v_total_presencas > 3 THEN v_percentual := 0.25;
                        ELSIF r.TIPO = 'VIP' THEN v_percentual := 0.20;
                        ELSE v_percentual := 0.10;
                        END IF;

                        v_cashback_atual := r.VALOR_PAGO * v_percentual;
                        v_total_geral := v_total_geral + v_cashback_atual;

                        UPDATE USUARIOS SET SALDO = NVL(SALDO, 0) + v_cashback_atual WHERE ID = r.USUARIO_ID;
                        INSERT INTO LOG_AUDITORIA (ID, INSCRICAO_ID, MOTIVO, DATA)
                        VALUES (SEQ_LOG.NEXTVAL, r.ID, 'BulbaCash de R$ ' || v_cashback_atual, SYSDATE);
                    END LOOP;
                    COMMIT;
                    :total_distribuido := v_total_geral;
                END;
                """
                cursor.execute(plsql, evento_id=evento_id, total_distribuido=total_out)
                valor_distribuido = total_out.getvalue()
        
        if valor_distribuido > 0:
            return render_template('index.html', mensagem=f"Folha Navalha! R$ {valor_distribuido:.2f} distribuídos no evento {evento_id}!", usuarios=buscar_saldos(), historico=buscar_historico())
        else:
            return render_template('index.html', aviso=f"Evento {evento_id} vazio. Bulbassauro está confuso.", usuarios=buscar_saldos(), historico=buscar_historico())
            
    except Exception as e:
        return render_template('index.html', erro=f"Erro no banco: {e}", usuarios=buscar_saldos(), historico=buscar_historico())

if __name__ == "__main__":
    app.run(debug=True)