import requests
import os
from msal import ConfidentialClientApplication
from db_config import get_db_connection
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
GRAPH_URL = os.getenv("GRAPH_URL")  # Ex: https://graph.microsoft.com/v1.0




def obter_token():
    app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Erro ao obter token: {result.get('error_description')}")

# 📤 Enviar e-mail via Graph API
def send_email_via_graph(from_email, to_emails, subject, html_body):
    access_token = obter_token()

    to_recipients = [{"emailAddress": {"address": addr}} for addr in to_emails]

    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": html_body
            },
            "toRecipients": to_recipients,
            "internetMessageHeaders": [
                {
                    "name": "X-Signature-Applied",
                    "value": "true"
                }
            ]
        },
        "saveToSentItems": "false"
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    url = f"{GRAPH_URL}/users/{from_email}/sendMail"
    response = requests.post(url, headers=headers, json=message)

    if response.status_code == 202:
        print("✅ E-mail enviado com sucesso via Microsoft Graph")
        return True
    else:
        print("❌ Erro ao enviar e-mail:", response.status_code, response.text)
        return False
        
           