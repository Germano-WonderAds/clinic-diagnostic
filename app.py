from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

SEMRUSH_API_KEY = os.environ.get('SEMRUSH_API_KEY', '')
DATAFORSEO_API_KEY = os.environ.get('DATAFORSEO_API_KEY', '')
OPENPAGERANK_API_KEY = os.environ.get('OPENPAGERANK_API_KEY', '')
GMAIL_USER = os.environ.get('GMAIL_USER', '')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

DFS_HEADERS = {
    'Authorization': f'Basic {DATAFORSEO_API_KEY}',
    'Content-Type': 'application/json'
}


def clean_domain(url):
    domain = url.lower().strip()
    for prefix in ['https://', 'http://', 'www.']:
        domain = domain.replace(prefix, '')
    return domain.split('/')[0]


def get_domain_overview(domain, database='pt'):
    # Returns: {'Or': organic_keywords_count, 'Ot': organic_traffic_etv}
    try:
        response = requests.post(
            'https://api.dataforseo.com/v3/dataforseo_labs/google/domain_rank_overview/live',
            headers=DFS_HEADERS,
            json=[{'target': domain, 'location_code': 2620, 'language_code': 'pt'}],
            timeout=15
        )
        data = response.json()
        metrics = data['tasks'][0]['result'][0]['items'][0]['metrics']['organic']
        return {
            'Or': metrics.get('count', 0),
            'Ot': metrics.get('etv', 0)
        }
    except Exception as e:
        print(f"Domain overview error: {e}")
    return {}


def get_backlinks_overview(domain):
    # Authority score from Open PageRank (0-10 scaled to 0-100)
    # Referring domains not available on free tier — returns 0
    try:
        response = requests.get(
            'https://openpagerank.com/api/v1.0/getPageRank',
            params={'domains[]': domain},
            headers={'API-OPR': OPENPAGERANK_API_KEY},
            timeout=10
        )
        data = response.json()
        page_rank = data['response'][0].get('page_rank_decimal', 0) or 0
        # Scale 0-10 to 0-100
        ascore = round(float(page_rank) * 10)
        return {
            'ascore': ascore,
            'domains_num': 0,
            'total': 0
        }
    except Exception as e:
        print(f"Backlinks overview error: {e}")
    return {}


def get_top_keywords(domain, database='pt'):
    try:
        response = requests.post(
            'https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live',
            headers=DFS_HEADERS,
            json=[{
                'target': domain,
                'location_code': 2620,
                'language_code': 'pt',
                'limit': 5,
                'order_by': ['keyword_data.keyword_info.search_volume,desc']
            }],
            timeout=15
        )
        data = response.json()
        items = data['tasks'][0]['result'][0]['items']
        keywords = []
        for item in items:
            kd = item.get('keyword_data', {})
            position = item.get('ranked_serp_element', {}).get('serp_item', {}).get('rank_absolute', 0)
            keywords.append({
                'keyword': kd.get('keyword', ''),
                'position': position,
                'volume': kd.get('keyword_info', {}).get('search_volume', 0)
            })
        return keywords
    except Exception as e:
        print(f"Top keywords error: {e}")
    return []


def calculate_score(domain_data, backlinks_data):
    # Authority Score (0-100), weight 40% (was 35%, +5% redistributed from referring domains)
    authority_score = int(backlinks_data.get('ascore', 0) or 0)
    authority_component = authority_score * 0.40

    # Organic Keywords, weight 30% (was 25%, +5% redistributed from referring domains)
    organic_keywords = int(domain_data.get('Or', 0) or 0)
    kw_score = min(100, (organic_keywords / 200) * 100)
    kw_component = kw_score * 0.30

    # Organic Traffic, weight 30% (was 25%, +5% redistributed from referring domains)
    organic_traffic = int(domain_data.get('Ot', 0) or 0)
    traffic_score = min(100, (organic_traffic / 1000) * 100)
    traffic_component = traffic_score * 0.30

    return round(authority_component + kw_component + traffic_component)


def get_score_category(score):
    if score < 25:
        return {
            'category': 'critical',
            'label': 'Invisível Online',
            'color': '#ef4444',
            'message': 'A sua clínica está praticamente invisível no Google. Os seus concorrentes estão a captar os pacientes que deviam ser seus todos os dias.',
            'urgency': 'Cada dia sem agir é receita que vai para a concorrência.'
        }
    elif score < 50:
        return {
            'category': 'weak',
            'label': 'Presença Fraca',
            'color': '#f97316',
            'message': 'A sua clínica tem alguma presença online mas está a perder a maioria dos pacientes para a concorrência nas pesquisas locais.',
            'urgency': 'Com a estratégia certa, pode triplicar o tráfego orgânico em 6 meses.'
        }
    elif score < 70:
        return {
            'category': 'moderate',
            'label': 'Potencial por Explorar',
            'color': '#eab308',
            'message': 'A sua clínica tem uma base sólida mas há oportunidades significativas que não estão a ser aproveitadas — incluindo o novo funil do ChatGPT.',
            'urgency': 'Está a 6 meses de dominar o Google na sua área.'
        }
    else:
        return {
            'category': 'strong',
            'label': 'Boa Presença Digital',
            'color': '#22c55e',
            'message': 'A sua clínica tem uma presença digital acima da média. O próximo passo é consolidar posições e expandir para novas pesquisas locais.',
            'urgency': 'Está pronto para escalar — e talvez para uma 2ª localização.'
        }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    raw_url = data.get('url', '').strip()

    if not raw_url:
        return jsonify({'error': 'URL da clínica é obrigatória'}), 400

    domain = clean_domain(raw_url)

    domain_data = get_domain_overview(domain)
    backlinks_data = get_backlinks_overview(domain)
    top_keywords = get_top_keywords(domain)

    score = calculate_score(domain_data, backlinks_data)
    score_info = get_score_category(score)

    organic_keywords = int(domain_data.get('Or', 0) or 0)
    organic_traffic = int(domain_data.get('Ot', 0) or 0)
    authority_score = int(backlinks_data.get('ascore', 0) or 0)
    referring_domains = int(backlinks_data.get('domains_num', 0) or 0)
    total_backlinks = int(backlinks_data.get('total', 0) or 0)

    return jsonify({
        'domain': domain,
        'score': score,
        **score_info,
        'metrics': {
            'authority_score': authority_score,
            'organic_keywords': organic_keywords,
            'organic_traffic': organic_traffic,
            'referring_domains': referring_domains,
            'total_backlinks': total_backlinks
        },
        'top_keywords': top_keywords
    })


def get_routing(faturacao):
    """Route lead to correct product based on annual revenue"""
    try:
        value = int(faturacao.replace('K', '000').replace('k', '000').replace('€', '').replace(' ', ''))
    except Exception:
        return {'product': 'unknown', 'action': 'manual_review', 'label': 'Rever manualmente'}

    if value < 150000:
        return {
            'product': 'online_course',
            'action': 'send_course_info',
            'label': 'Curso Online',
            'description': 'Enviar info do curso — faturação abaixo de 150K'
        }
    elif value <= 300000:
        return {
            'product': 'seo_service',
            'action': 'book_seo_call',
            'label': 'Serviço SEO',
            'description': 'Agendar chamada SEO — faturação entre 150K e 300K'
        }
    else:
        return {
            'product': 'full_audit',
            'action': 'book_audit_call',
            'label': 'Auditoria Gratuita',
            'description': 'Apresentar auditoria gratuita — faturação acima de 300K'
        }


@app.route('/submit-lead', methods=['POST'])
def submit_lead():
    data = request.json
    name = data.get('name', '')
    clinic = data.get('clinic', '')
    email = data.get('email', '')
    phone = data.get('phone', '')
    faturacao = data.get('faturacao', '')
    domain = data.get('domain', '')
    score = data.get('score', '')

    routing = get_routing(faturacao)

    print(f"\n=== NEW LEAD ===")
    print(f"Name: {name} | Clinic: {clinic}")
    print(f"Email: {email} | Phone: {phone}")
    print(f"Faturação Anual: {faturacao}")
    print(f"Domain: {domain} | Score: {score}")
    print(f"→ ROUTE TO: {routing['label']} — {routing['description']}")
    print(f"================\n")

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Novo Lead — {clinic} ({routing["label"]})'
        msg['From'] = GMAIL_USER
        msg['To'] = 'alex@wonder-ads.com, germano@wonder-ads.com'
        html_body = f'''
            <h2>Novo lead do Diagnóstico Digital</h2>
            <table style="border-collapse:collapse;width:100%">
                <tr><td style="padding:8px;color:#666">Nome</td><td style="padding:8px"><strong>{name}</strong></td></tr>
                <tr><td style="padding:8px;color:#666">Clínica</td><td style="padding:8px"><strong>{clinic}</strong></td></tr>
                <tr><td style="padding:8px;color:#666">Email</td><td style="padding:8px"><a href="mailto:{email}">{email}</a></td></tr>
                <tr><td style="padding:8px;color:#666">Telemóvel</td><td style="padding:8px">{phone}</td></tr>
                <tr><td style="padding:8px;color:#666">Faturação</td><td style="padding:8px">{faturacao}</td></tr>
                <tr><td style="padding:8px;color:#666">Website</td><td style="padding:8px">{domain}</td></tr>
                <tr><td style="padding:8px;color:#666">Score SEO</td><td style="padding:8px"><strong>{score}/100</strong></td></tr>
                <tr style="background:#f9f9f9"><td style="padding:8px;color:#666">Rota</td><td style="padding:8px"><strong style="color:#7c3aed">{routing["label"]}</strong> — {routing["description"]}</td></tr>
            </table>
        '''
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, ['alex@wonder-ads.com', 'germano@wonder-ads.com'], msg.as_string())
    except Exception as e:
        print(f"Email send error: {e}")

    return jsonify({'success': True, 'routing': routing})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
