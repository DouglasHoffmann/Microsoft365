from bs4 import BeautifulSoup
from db_config import get_db_connection

def buscar_dados_assinatura(email):
    clean_email = email.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT full_name, job_title, department, phone_number, user_email
        FROM signatures
        WHERE user_email = ?
    """, (clean_email,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "full_name": row[0],
            "job_title": row[1],
            "department": row[2],
            "phone_number": row[3],
            "email": row[4]
        }
    else:
        return None


def gerar_assinatura_html(full_name, job_title, department, phone, email, cid_logo="logo_empresa"):
    return f"""
<table cellpadding="0" cellspacing="0" style="font-family: Arial, sans-serif; font-size: 14px;">
  <tr>
    <td style="padding-right: 10px;">
      <img src="cid:{cid_logo}" width="100" alt="Logo">
    </td>
    <td>
      <b>{full_name}</b><br>
      <b>{job_title or ''}</b><br>
      {department or ''}<br>
      {phone or ''}<br>
      <a href="mailto:{email}">{email}</a>
    </td>
  </tr>
</table>
"""


def inserir_assinatura_html(html, assinatura):
    soup = BeautifulSoup(html, 'html.parser')
    bloco_citado = soup.find(['blockquote', 'div'], class_='gmail_quote')
    if bloco_citado:
        bloco_citado.insert_before(BeautifulSoup(f"<br><br><!-- assinatura-aplicada -->{assinatura}", 'html.parser'))
    else:
        if soup.body:
            soup.body.append(BeautifulSoup(f"<br><br><!-- assinatura-aplicada -->{assinatura}", 'html.parser'))
        else:
            soup.append(BeautifulSoup(f"<br><br><!-- assinatura-aplicada -->{assinatura}", 'html.parser'))
    return str(soup)


def inserir_assinatura_texto(texto, assinatura):
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if linha.strip().startswith("Em ") and "escreveu" in linha:
            return "\n".join(linhas[:i]) + f"\n\n{assinatura}\n\n" + "\n".join(linhas[i:])
    return texto + f"\n\n{assinatura}"
