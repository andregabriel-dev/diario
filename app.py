import os
import random
import sqlite3
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.utils import secure_filename
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'diario.db')
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('DIARIO_SECRET_KEY', 'troque-esta-chave-antes-de-publicar')

EXTENSOES_PERMITIDAS = {'png', 'jpg', 'jpeg', 'webp'}

DESAFIOS = [
    'Peça o prato que o garçom indicar, sem perguntar o que é.',
    'Tente adivinhar a nota que o outro vai dar pro ambiente antes de ele(a) falar.',
    'Peçam pra dividir a sobremesa, mesmo que vocês digam que não vão querer.',
    'Descubra o prato mais estranho do cardápio e leiam a descrição em voz alta.',
    'Tirem uma foto dos dois sem sorrir de propósito.',
    'Peça uma bebida que você nunca provou antes.',
    'Tentem adivinhar o preço da conta antes de ela chegar.',
    'Conversem sobre o primeiro encontro de vocês enquanto esperam o pedido.',
    'Peçam pra experimentar o prato um do outro antes de comer o próprio.',
    'Descubram juntos qual é o ingrediente secreto de algum prato do menu.',
]

CONQUISTAS = [
    {'id': 'visita_1', 'tipo': 'visitas', 'meta': 1, 'emoji': '🍽️', 'titulo': 'Primeira Mordida', 'descricao': 'Registrem a primeira visita.'},
    {'id': 'visita_5', 'tipo': 'visitas', 'meta': 5, 'emoji': '🧭', 'titulo': 'Exploradores', 'descricao': '5 restaurantes visitados.'},
    {'id': 'visita_10', 'tipo': 'visitas', 'meta': 10, 'emoji': '🔟', 'titulo': 'Dez em Dez', 'descricao': '10 restaurantes visitados.'},
    {'id': 'visita_20', 'tipo': 'visitas', 'meta': 20, 'emoji': '🏆', 'titulo': 'Rota Gastronômica', 'descricao': '20 restaurantes visitados.'},
    {'id': 'lugares_10', 'tipo': 'lugares', 'meta': 10, 'emoji': '🌍', 'titulo': 'Colecionadores de Sabores', 'descricao': '10 lugares diferentes.'},
    {'id': 'desafio_1', 'tipo': 'desafios', 'meta': 1, 'emoji': '🎯', 'titulo': 'Sem Medo de Desafio', 'descricao': 'Completem o primeiro desafio.'},
    {'id': 'desafio_5', 'tipo': 'desafios', 'meta': 5, 'emoji': '🔥', 'titulo': 'Desafiantes', 'descricao': '5 desafios completos.'},
    {'id': 'desafio_10', 'tipo': 'desafios', 'meta': 10, 'emoji': '🏅', 'titulo': 'Mestres do Desafio', 'descricao': '10 desafios completos.'},
]

NIVEIS = [
    (0, 'Aprendiz Gastronômico'),
    (50, 'Curiosos de Cardápio'),
    (100, 'Exploradores de Sabores'),
    (200, 'Gourmets em Formação'),
    (350, 'Sommeliers do Rolê'),
    (500, 'Mestres Cuca'),
]

def calcular_pontos(total_visitas, total_desafios):
    return total_visitas * 10 + total_desafios * 20

def titulo_do_nivel(pontos):
    titulo = NIVEIS[0][1]
    for minimo, nome in NIVEIS:
        if pontos >= minimo:
            titulo = nome
    return titulo

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def fechar_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def inicializar_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                username TEXT PRIMARY KEY,
                senha TEXT NOT NULL,
                nome TEXT NOT NULL,
                primeiro_acesso INTEGER DEFAULT 1
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS registros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local TEXT NOT NULL,
                data TEXT NOT NULL,
                atendimento REAL NOT NULL,
                ambiente REAL NOT NULL,
                sabor REAL NOT NULL,
                notas TEXT,
                autor TEXT,
                desafio TEXT,
                desafio_concluido INTEGER DEFAULT 0,
                criado_em TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS fotos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registro_id INTEGER NOT NULL,
                arquivo TEXT NOT NULL,
                capa INTEGER NOT NULL DEFAULT 0
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS desejos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                adicionado_por TEXT NOT NULL,
                visitado INTEGER NOT NULL DEFAULT 0,
                criado_em TEXT NOT NULL
            )
        ''')

        # Migração caso a coluna capa não exista na tabela fotos
        colunas_fotos = [c[1] for c in db.execute('PRAGMA table_info(fotos)').fetchall()]
        if 'capa' not in colunas_fotos:
            db.execute('ALTER TABLE fotos ADD COLUMN capa INTEGER NOT NULL DEFAULT 0')

        usuarios_padrao = [
            ('andre', '1234', 'André'),
            ('joyce', '1234', 'Joyce')
        ]
        for user, senha, nome in usuarios_padrao:
            existe = db.execute('SELECT 1 FROM usuarios WHERE username = ?', (user,)).fetchone()
            if not existe:
                db.execute('INSERT INTO usuarios (username, senha, nome, primeiro_acesso) VALUES (?, ?, ?, 1)', (user, senha, nome))
        db.commit()

inicializar_db()

def extensao_permitida(nome_arquivo):
    return '.' in nome_arquivo and nome_arquivo.rsplit('.', 1)[1].lower() in EXTENSOES_PERMITIDAS

def salvar_foto_comprimida(arquivo):
    nome_original = secure_filename(arquivo.filename or '')
    if not nome_original or not extensao_permitida(nome_original):
        return None
    nome_final = f'{uuid.uuid4().hex}.jpg'
    caminho_final = os.path.join(UPLOAD_DIR, nome_final)
    imagem = Image.open(arquivo.stream).convert('RGB')
    largura_maxima = 1000
    if imagem.width > largura_maxima:
        proporcao = largura_maxima / imagem.width
        imagem = imagem.resize((largura_maxima, int(imagem.height * proporcao)))
    imagem.save(caminho_final, 'JPEG', quality=75)
    return nome_final

DIAS_SEMANA = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

def formatar_data_longa(iso):
    d = datetime.strptime(iso, '%Y-%m-%d')
    texto = f'{DIAS_SEMANA[d.weekday()]}, {d.day} de {MESES[d.month - 1]} de {d.year}'
    return texto[0].upper() + texto[1:]

def formatar_data_curta(iso):
    d = datetime.strptime(iso, '%Y-%m-%d')
    return d.strftime('%d/%m/%y')

@app.before_request
def exigir_senha():
    rotas_livres = {'entrar', 'mudar_senha', 'static'}
    if request.endpoint in rotas_livres:
        return
    if not session.get('usuario'):
        return redirect(url_for('entrar'))

@app.route('/entrar', methods=['GET', 'POST'])
def entrar():
    erro = None
    if request.method == 'POST':
        username = request.form.get('usuario', '').strip().lower()
        senha = request.form.get('senha', '')
        db = get_db()
        user = db.execute('SELECT * FROM usuarios WHERE username = ?', (username,)).fetchone()
        
        if user and senha == user['senha']:
            session['usuario'] = user['username']
            session['nome'] = user['nome']
            session.permanent = True
            if user['primeiro_acesso'] == 1:
                return redirect(url_for('mudar_senha'))
            return redirect(url_for('desejos'))
        erro = 'Usuário ou senha incorretos.'
    return render_template('entrar.html', erro=erro)

@app.route('/mudar-senha', methods=['GET', 'POST'])
def mudar_senha():
    if not session.get('usuario'):
        return redirect(url_for('entrar'))
    
    erro = None
    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha', '').strip()
        if not nova_senha:
            erro = 'A senha não pode ser vazia.'
        else:
            db = get_db()
            db.execute('UPDATE usuarios SET senha = ?, primeiro_acesso = 0 WHERE username = ?', (nova_senha, session['usuario']))
            db.commit()
            flash('Senha alterada com sucesso! Bem-vindos ao diário.', 'sucesso')
            return redirect(url_for('desejos'))
    return render_template('mudar_senha.html', erro=erro)

@app.route('/sair')
def sair():
    session.clear()
    return redirect(url_for('entrar'))

# ---------- Página Inicial / Lista de Desejos ----------
@app.route('/', methods=['GET', 'POST'])
def desejos():
    db = get_db()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('Escreva o nome do lugar ou o tipo de comida.', 'erro')
            return redirect(url_for('desejos'))

        db.execute(
            'INSERT INTO desejos (nome, adicionado_por, visitado, criado_em) VALUES (?, ?, 0, ?)',
            (nome, session.get('nome', ''), datetime.utcnow().isoformat())
        )
        db.commit()
        flash('Adicionado à lista de desejos! ✨', 'sucesso')
        return redirect(url_for('desejos'))

    lista = db.execute('SELECT * FROM desejos WHERE visitado = 0 ORDER BY criado_em DESC').fetchall()
    
    # Dados para a tela inicial (destaques, total de visitados, foto do dia)
    total_visitas = db.execute('SELECT COUNT(*) FROM registros').fetchone()[0]
    total_lugares = db.execute('SELECT COUNT(DISTINCT LOWER(TRIM(local))) FROM registros').fetchone()[0]
    
    # Foto do dia (pega a foto mais recente cadastrada)
    foto_recente = db.execute('''
        SELECT f.arquivo, r.local, r.data, r.autor 
        FROM fotos f JOIN registros r ON f.registro_id = r.id 
        ORDER BY r.data DESC, f.id DESC LIMIT 1
    ''').fetchone()

    return render_template('desejos.html', ativa='desejos', lista=lista, 
                           total_visitas=total_visitas, total_lugares=total_lugares, 
                           foto_recente=foto_recente)

@app.route('/desejos/excluir/<int:desejo_id>', methods=['POST'])
def excluir_desejo(desejo_id):
    db = get_db()
    db.execute('DELETE FROM desejos WHERE id = ?', (desejo_id,))
    db.commit()
    flash('Removido da lista.', 'sucesso')
    return redirect(url_for('desejos'))

# ---------- Registrar (avaliação de uma visita) ----------
@app.route('/registrar', methods=['GET', 'POST'])
def registrar():
    if request.method == 'POST':
        local = request.form.get('local', '').strip()
        data = request.form.get('data', '').strip()
        notas = request.form.get('notas', '').strip()
        desejo_id = request.form.get('desejo_id', '').strip()
        desafio = request.form.get('desafio', '').strip()
        desafio_concluido = 1 if request.form.get('desafio_concluido') else 0

        try:
            atendimento = float(request.form.get('atendimento', 0))
            ambiente = float(request.form.get('ambiente', 0))
            sabor = float(request.form.get('sabor', 0))
        except ValueError:
            atendimento = ambiente = sabor = 0

        if not local or not data:
            flash('Preencha ao menos o nome do lugar e a data.', 'erro')
            return redirect(url_for('registrar'))

        db = get_db()
        cursor = db.execute(
            'INSERT INTO registros (local, data, atendimento, ambiente, sabor, notas, autor, '
            'desafio, desafio_concluido, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (local, data, atendimento, ambiente, sabor, notas, session.get('nome', ''),
             desafio or None, desafio_concluido, datetime.utcnow().isoformat())
        )
        registro_id = cursor.lastrowid

        for arquivo in request.files.getlist('fotos'):
            if arquivo and arquivo.filename:
                nome_salvo = salvar_foto_comprimida(arquivo)
                if nome_salvo:
                    db.execute('INSERT INTO fotos (registro_id, arquivo) VALUES (?, ?)', (registro_id, nome_salvo))

        if desejo_id:
            db.execute('UPDATE desejos SET visitado = 1 WHERE id = ?', (desejo_id,))

        db.commit()
        flash('Registro salvo! ✅', 'sucesso')
        return redirect(url_for('desejos'))

    hoje = datetime.now().strftime('%Y-%m-%d')
    local_prefill = request.args.get('local', '')
    desejo_id = request.args.get('desejo_id', '')
    desafio_sorteado = random.choice(DESAFIOS) if desejo_id else ''
    return render_template('registrar.html', ativa='desejos', hoje=hoje,
                            local_prefill=local_prefill, desejo_id=desejo_id,
                            desafio_sorteado=desafio_sorteado)

# ---------- Conquistas ----------
@app.route('/conquistas')
def conquistas():
    db = get_db()
    total_visitas = db.execute('SELECT COUNT(*) FROM registros').fetchone()[0]
    total_lugares = db.execute('SELECT COUNT(DISTINCT LOWER(TRIM(local))) FROM registros').fetchone()[0]
    total_desafios = db.execute('SELECT COUNT(*) FROM registros WHERE desafio_concluido = 1').fetchone()[0]

    totais = {'visitas': total_visitas, 'lugares': total_lugares, 'desafios': total_desafios}

    lista_conquistas = []
    for c in CONQUISTAS:
        atual = totais[c['tipo']]
        desbloqueada = atual >= c['meta']
        progresso = min(100, int((atual / c['meta']) * 100)) if c['meta'] else 100
        lista_conquistas.append({**c, 'atual': atual, 'desbloqueada': desbloqueada, 'progresso': progresso})

    desbloqueadas = sum(1 for c in lista_conquistas if c['desbloqueada'])
    pontos = calcular_pontos(total_visitas, total_desafios)
    nivel_atual = titulo_do_nivel(pontos)

    proximo_minimo = None
    for minimo, _ in NIVEIS:
        if minimo > pontos:
            proximo_minimo = minimo
            break
    if proximo_minimo:
        minimo_anterior = max((m for m, _ in NIVEIS if m <= pontos), default=0)
        faixa = proximo_minimo - minimo_anterior
        progresso_nivel = int(((pontos - minimo_anterior) / faixa) * 100) if faixa else 100
    else:
        progresso_nivel = 100

    return render_template(
        'conquistas.html', ativa='conquistas',
        total_visitas=total_visitas, total_lugares=total_lugares, total_desafios=total_desafios,
        desbloqueadas=desbloqueadas, total_conquistas=len(lista_conquistas),
        lista_conquistas=lista_conquistas, pontos=pontos, nivel_atual=nivel_atual,
        proximo_minimo=proximo_minimo, progresso_nivel=progresso_nivel
    )

# ---------- Ranking ----------
@app.route('/ranking')
def ranking():
    db = get_db()
    registros = db.execute('SELECT * FROM registros').fetchall()

    grupos = {}
    for r in registros:
        chave = r['local'].strip().lower()
        grupos.setdefault(chave, {'nome': r['local'].strip(), 'itens': []})
        grupos[chave]['itens'].append(r)

    lista = []
    for grupo in grupos.values():
        itens = grupo['itens']
        n = len(itens)
        atendimento = sum(i['atendimento'] for i in itens) / n
        ambiente = sum(i['ambiente'] for i in itens) / n
        sabor = sum(i['sabor'] for i in itens) / n
        geral = (atendimento + ambiente + sabor) / 3

        capa = None
        for item in sorted(itens, key=lambda i: i['data'], reverse=True):
            foto = db.execute('SELECT arquivo FROM fotos WHERE registro_id = ? LIMIT 1', (item['id'],)).fetchone()
            if foto:
                capa = foto['arquivo']
                break

        lista.append({
            'nome': grupo['nome'], 'visitas': n, 'atendimento': atendimento,
            'ambiente': ambiente, 'sabor': sabor, 'geral': geral, 'capa': capa
        })

    lista.sort(key=lambda x: x['geral'], reverse=True)
    return render_template('ranking.html', ativa='ranking', lista=lista)

# ---------- Memórias ----------
@app.route('/memorias')
def memorias():
    db = get_db()
    registros = db.execute('SELECT * FROM registros ORDER BY data DESC').fetchall()

    por_dia = {}
    for r in registros:
        fotos = db.execute('SELECT id, arquivo FROM fotos WHERE registro_id = ?', (r['id'],)).fetchall()
        if not fotos:
            continue
        data_curta = formatar_data_curta(r['data'])
        for foto in fotos:
            por_dia.setdefault(r['data'], []).append({
                'arquivo': foto['arquivo'],
                'local': r['local'],
                'autor': r['autor'] or '',
                'data_iso': r['data'],
                'data_curta': data_curta,
                'atendimento': r['atendimento'],
                'ambiente': r['ambiente'],
                'sabor': r['sabor'],
                'notas': r['notas'] or '',
                'desafio': r['desafio'] or '',
                'desafio_concluido': r['desafio_concluido'] or 0,
                'registro_id': r['id'],
            })

    dias = []
    for data_iso in sorted(por_dia.keys(), reverse=True):
        dias.append({'texto': formatar_data_longa(data_iso), 'fotos': por_dia[data_iso]})

    return render_template('memorias.html', ativa='memorias', dias=dias)



#--------Capa memórias---------
@app.route('/memorias/capa/<int:foto_id>', methods=['POST'])
def definir_capa(foto_id):
    db = get_db()
    # Descobre a qual registro essa foto pertence
    foto = db.execute('SELECT r.data FROM fotos f JOIN registros r ON f.registro_id = r.id WHERE f.id = ?', (foto_id,)).fetchone()
    if foto:
        data_registro = foto['data']
        # Reseta a capa de todas as fotos dos registros desse mesmo dia
        db.execute('''
            UPDATE fotos SET capa = 0 WHERE registro_id IN (
                SELECT id FROM registros WHERE data = ?
            )
        ''', (data_registro,))
        # Define esta foto específica como capa
        db.execute('UPDATE fotos SET capa = 1 WHERE id = ?', (foto_id,))
        db.commit()
        flash('Foto de capa do dia atualizada! ✨', 'sucesso')
    return redirect(url_for('memorias'))



# ---------- Excluir ----------
@app.route('/excluir/<int:registro_id>', methods=['POST'])
def excluir(registro_id):
    db = get_db()
    fotos = db.execute('SELECT arquivo FROM fotos WHERE registro_id = ?', (registro_id,)).fetchall()
    for foto in fotos:
        caminho = os.path.join(UPLOAD_DIR, foto['arquivo'])
        if os.path.exists(caminho):
            os.remove(caminho)

    db.execute('DELETE FROM fotos WHERE registro_id = ?', (registro_id,))
    db.execute('DELETE FROM registros WHERE id = ?', (registro_id,))
    db.commit()

    flash('Registro excluído.', 'sucesso')
    destino = request.referrer or url_for('ranking')
    return redirect(destino)

if __name__ == '__main__':
    app.run(debug=True)