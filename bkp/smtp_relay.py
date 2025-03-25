# Versão ajustada com envio via SMTP e assinatura posicionada corretamente
# Desenvolvido com base no original, adaptado por ChatGPT

import ssl
import time
import logging
from logging.handlers import TimedRotatingFileHandler
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP
from db_config import get_db_connection
from prometheus_client import start_http_server, Counter, Summary
from graph_email_service import send_email_via_graph
import os

import sys


sys.stdout.reconfigure(encoding='utf-8')

# ────────────────────────────────
# 🔐 Certificados TLS
CERT_PATH = r"C:\Certificados\fullchain1.pem"
KEY_PATH = r"C:\Certificados\privkey1.pem"

# 📁 Diretório para salvar .eml
SAVE_DIR = "emails_salvos"
os.makedirs(SAVE_DIR, exist_ok=True)

# ────────────────────────────────
# 📊 Prometheus Métricas
EMAILS_PROCESSED = Counter('emails_processed_total', 'Total de e-mails processados com sucesso')
EMAILS_FAILED = Counter('emails_failed_total', 'Total de e-mails que falharam ao processar')
EMAIL_LATENCY = Summary('email_processing_seconds', 'Tempo de processamento por e-mail')

# ────────────────────────────────
# 📝 Logging
log_formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
log_handler = TimedRotatingFileHandler("smtp_relay.log", when="midnight", backupCount=7)
log_handler.setFormatter(log_formatter)

logger = logging.getLogger("smtp_relay")
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# ────────────────────────────────
# 🔍 Buscar assinatura no banco
def buscar_assinatura(sender_email: str) -> str:
    clean_email = sender_email.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("EXEC get_signature ?", (clean_email,))
    row = cursor.fetchone()
    conn.close()

    if row:
        # Se você quiser por índice:
        return row.signature_html if hasattr(row, "signature_html") else row[5]
        # Ou por índice diretamente (6ª coluna = índice 5)
        # return row[5]
    return ""

# ────────────────────────────────
# 📩 Handler SMTP
class EmailHandler:
    @EMAIL_LATENCY.time()
    async def handle_DATA(self, server, session, envelope):

        raw_content = envelope.content.decode('utf-8', errors='replace')

        if '<!-- assinatura-aplicada -->' in raw_content:
            logger.info("🔁 E-mail já contém marca de assinatura. Ignorando para evitar loop.")
            return '250 OK'

        try:
            original_msg = BytesParser(policy=policy.default).parsebytes(envelope.content)
            sender = envelope.mail_from
            recipients = envelope.rcpt_tos
            subject = original_msg.get("Subject", "")
            
            # if "[Assinado]" in subject:
            #     logger.info("🔁 E-mail já assinado anteriormente (assunto marcado). Ignorando.")
            #     return '250 OK'

            signature = buscar_assinatura(sender)

            new_msg = EmailMessage()
            new_msg["From"] = sender
            new_msg["To"] = ", ".join(recipients)
            new_msg["Subject"] = subject

            has_html = False
            has_text = False

            if original_msg.is_multipart():
                for part in original_msg.iter_parts():
                    content_type = part.get_content_type()
                    charset = part.get_content_charset() or "utf-8"

                    if content_type == "application/ms-tnef":
                        logger.info("Ignorando parte winmail.dat")
                        continue

                    content = part.get_content()

                    if content_type == "text/plain" and not has_text:
                        content += f"\n\n{signature}"
                        new_msg.set_content(content, subtype="plain", charset=charset)
                        has_text = True

                    elif content_type == "text/html" and not has_html:
                        content += f"<br><br><!-- assinatura-aplicada -->{signature}"
                        new_msg.add_alternative(content, subtype="html", charset=charset)
                        has_html = True

                    else:
                        new_msg.make_mixed()
                        new_msg.add_attachment(
                            part.get_payload(decode=True),
                            maintype=part.get_content_maintype(),
                            subtype=part.get_content_subtype(),
                            filename=part.get_filename()
                        )

                if not has_html and not has_text:
                    logger.info("E-mail não tinha partes úteis. Adicionando corpo padrão com assinatura.")
                    new_msg.set_content(f"Olá!\n\n{signature}", subtype="plain", charset="utf-8")

            else:
                content = original_msg.get_content()
                content_type = original_msg.get_content_type()
                charset = original_msg.get_content_charset() or "utf-8"

                if "html" in content_type:
                    content += f"<br><br><!-- assinatura-aplicada -->{signature}"
                    new_msg.set_content(content, subtype="html", charset=charset)
                else:
                    content += f"\n\n{signature}"
                    new_msg.set_content(content, subtype="plain", charset=charset)

            envelope.content = new_msg.as_bytes()
            filename = os.path.join(SAVE_DIR, f"email_{int(time.time())}.eml")
            with open(filename, "wb") as f:
                f.write(envelope.content)

            logger.info(f"[ASSINATURA] Aplicada com sucesso: {sender} -> {', '.join(recipients)} | Assunto: {subject}")
            EMAILS_PROCESSED.inc()

            try:
                # Extrai HTML preferencial para enviar via Graph
                body = None
                if new_msg.is_multipart():
                    for part in new_msg.iter_parts():
                        if part.get_content_type() == "text/html":
                            body = part.get_content()
                            break
                if not body:
                    body = new_msg.get_content()

                sucesso = send_email_via_graph(
                    from_email=sender,
                    to_emails=recipients,
                    subject=new_msg["Subject"],
                    html_body=body
                )

                if sucesso:
                    logger.info("E-mail enviado com sucesso via Microsoft Graph")
                else:
                    logger.error("Falha ao enviar e-mail via Microsoft Graph")

            except Exception as e:
                logger.exception(f"Erro ao tentar enviar e-mail via Microsoft Graph: {e}")

            return '250 Message accepted for delivery'

        except Exception as e:
            logger.error(f"Erro ao processar e-mail: {e}")
            EMAILS_FAILED.inc()
            return '550 Failed to process message'


# ────────────────────────────────
# 🚀 TLS SMTP Controller
class CustomSMTP(SMTP):
    def __init__(self, handler):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)
        super().__init__(handler, require_starttls=True, tls_context=context)

class CustomController(Controller):
    def factory(self):
        return CustomSMTP(self.handler)

# ────────────────────────────────
# ▶️ Iniciar
if __name__ == "__main__":
    start_http_server(9100)
    logger.info("Métricas Prometheus disponíveis em http://localhost:9100/metrics")

    handler = EmailHandler()
    controller = CustomController(handler, hostname="170.238.45.85", port=25)
    controller.start()
    logger.info("Servidor SMTP STARTTLS ativo e monitorando com logs, métricas e salvamento de .eml")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Encerrando servidor SMTP...")
        controller.stop()
