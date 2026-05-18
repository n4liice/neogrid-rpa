"""
Motor do RPA Neogrid EDI — usado pela API e pelo CLI.
Retorna lista de documentos não lidos com PDF em base64.
"""

import os
import time
import base64
import logging
import tempfile
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

USUARIO    = os.environ["NEOGRID_USUARIO"]
SENHA      = os.environ["NEOGRID_SENHA"]
URL_PORTAL = "https://portal.neogrid.com/?lang=pt"
URL_EDI    = "https://edi.neogrid.com/mercador/summaryFrame.jsp"

log = logging.getLogger(__name__)


def criar_driver(headless: bool = True, pasta_download: str = None):
    pasta_download = pasta_download or tempfile.mkdtemp()
    opcoes = Options()
    if headless:
        opcoes.add_argument("--headless=new")
        opcoes.add_argument("--no-sandbox")
        opcoes.add_argument("--disable-dev-shm-usage")
        opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--start-maximized")
    opcoes.add_argument("--disable-notifications")
    opcoes.add_argument("--disable-popup-blocking")
    opcoes.add_experimental_option("prefs", {
        "download.default_directory": pasta_download,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
    })
    driver = webdriver.Chrome(options=opcoes)
    driver.implicitly_wait(5)
    return driver, pasta_download


def fazer_login(driver):
    log.info("Acessando o portal Neogrid...")
    driver.get(URL_PORTAL)
    wait = WebDriverWait(driver, 30)

    campo_usuario = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input[type='email'], input[type='text']")
    ))
    campo_usuario.clear()
    campo_usuario.send_keys(USUARIO)

    botao_proximo = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "button[type='submit'], button[type='button'], button")
    ))
    botao_proximo.click()
    log.info(f"Avançou para senha.")

    campo_senha = wait.until(EC.visibility_of_element_located(
        (By.CSS_SELECTOR, "input[type='password']")
    ))
    campo_senha.clear()
    campo_senha.send_keys(SENHA)

    botao_login = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
    ))
    botao_login.click()
    log.info("Login submetido...")

    wait.until(EC.presence_of_element_located(
        (By.XPATH, "//*[contains(text(), 'EDI Logístico') or contains(text(), 'EDI Logistico')]")
    ))
    log.info("Login realizado com sucesso.")

    # Fecha abas extras
    aba_portal = driver.window_handles[0]
    for aba in driver.window_handles[1:]:
        driver.switch_to.window(aba)
        driver.close()
    driver.switch_to.window(aba_portal)

    # Aceita cookies se aparecer
    try:
        botao_concordo = WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(normalize-space(.),'Concordo')]")
            )
        )
        botao_concordo.click()
        log.info("Cookies aceitos.")
    except Exception:
        pass

    # Fecha modal se aparecer
    try:
        botao_fechar = WebDriverWait(driver, 2).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[aria-label='Close'], .modal button.close, button[class*='close']")
            )
        )
        botao_fechar.click()
    except Exception:
        pass


def acessar_edi_logistico(driver):
    wait = WebDriverWait(driver, 15)
    log.info("Clicando em 'Acessar' no EDI Logístico...")
    botao_acessar = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//tr[td[contains(normalize-space(.),'EDI Logístico')] or td[contains(normalize-space(.),'EDI Logistico')]]"
                   "//button[contains(normalize-space(.),'Acessar')] | "
                   "//*[contains(normalize-space(.),'EDI Logístico') or contains(normalize-space(.),'EDI Logistico')]"
                   "/ancestor::*[self::li or self::div or self::tr][1]"
                   "//button[contains(normalize-space(.),'Acessar')] | "
                   "//button[contains(normalize-space(.),'Acessar')]")
    ))
    botao_acessar.click()


def acessar_webedi(driver):
    if len(driver.window_handles) > 1:
        driver.switch_to.window(driver.window_handles[-1])
    log.info("Navegando para o WebEDI...")
    driver.get(URL_EDI)
    WebDriverWait(driver, 30).until(EC.url_contains("edi.neogrid.com"))
    log.info("WebEDI carregado.")


def mudar_para_frame_transacao(driver):
    driver.switch_to.default_content()
    try:
        driver.switch_to.frame("Transacao")
    except Exception:
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                nome = iframe.get_attribute("name") or ""
                if "transacao" in nome.lower() or "content" in nome.lower():
                    driver.switch_to.frame(iframe)
                    return
            driver.switch_to.frame(0)
        except Exception as e:
            log.warning(f"Não foi possível mudar de frame: {e}")


def acessar_caixa_entrada(driver, data: str):
    wait = WebDriverWait(driver, 30)
    log.info("Acessando Caixa de Entrada...")

    driver.switch_to.default_content()

    try:
        overlay = driver.find_element(By.ID, "walk-wrapper")
        if overlay.is_displayed():
            driver.execute_script("arguments[0].style.display='none';", overlay)
    except Exception:
        pass

    link_caixa = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//a[contains(text(),'Caixa Entrada') or contains(@href,'goInbox')]")
    ))
    driver.execute_script("arguments[0].click();", link_caixa)
    log.info("Clicou em 'Caixa Entrada'.")

    mudar_para_frame_transacao(driver)

    try:
        link_filtro = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//*[contains(text(),'filtro está fechado') or contains(text(),'exibi-lo')]")
            )
        )
        link_filtro.click()
    except Exception:
        pass

    log.info(f"Filtrando por data: {data}")
    campo_data = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//label[contains(text(),'Data Criação Inicial') or contains(text(),'Data Cria')]"
                   "/following-sibling::input | "
                   "//input[@id='dataIni' or @name='dataIni' or @name='dtInicio' or @id='dtInicio' or @id='startDate']")
    ))
    campo_data.clear()
    campo_data.send_keys(data)

    botao_pesquisar = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//button[contains(normalize-space(.),'Pesquisar')] | "
                   "//input[@value='Pesquisar' or @value='pesquisar' or @title='Pesquisar'] | "
                   "//input[@type='submit'] | //input[@type='image'] | "
                   "//a[contains(normalize-space(.),'Pesquisar')]")
    ))
    try:
        botao_pesquisar.click()
    except Exception:
        driver.execute_script("arguments[0].click();", botao_pesquisar)
    log.info("Pesquisa disparada.")
    time.sleep(2)


def coletar_nao_lidos(driver) -> list:
    """Lê a tabela e retorna lista de dicts com documentos não lidos."""
    mudar_para_frame_transacao(driver)
    time.sleep(1)

    linhas = driver.find_elements(By.XPATH, "//table//tr[td]")
    log.info(f"Total de linhas: {len(linhas)}")

    nao_lidos = []
    for i, linha in enumerate(linhas):
        try:
            celulas = linha.find_elements(By.TAG_NAME, "td")
            if len(celulas) < 7:
                continue
            remetente      = celulas[1].text.strip()
            numero         = celulas[3].text.strip()
            data_criacao   = celulas[5].text.strip()
            status_leitura = celulas[6].text.strip()

            log.info(f"  [{i+1}] {numero} | {data_criacao} | {status_leitura}")

            if status_leitura.lower() != "lido":
                log.info(f"  *** NÃO LIDO: {numero}")
                nao_lidos.append({
                    "indice": i,
                    "numero": numero,
                    "remetente": remetente,
                    "data_criacao": data_criacao,
                    "status": status_leitura,
                })
        except Exception as e:
            log.warning(f"Erro na linha {i}: {e}")

    log.info(f"Não lidos encontrados: {len(nao_lidos)}")
    return nao_lidos


def baixar_pdf_base64(driver, numero_doc: str, pasta_download: str) -> str | None:
    """Clica no botão PDF do documento e retorna o conteúdo em base64."""
    try:
        mudar_para_frame_transacao(driver)

        linha = driver.find_element(
            By.XPATH, f"//tr[td[contains(text(), '{numero_doc}')]]"
        )
        botao_pdf = linha.find_element(
            By.XPATH, ".//a[contains(@class,'pdf') or contains(text(),'pdf') or contains(text(),'PDF')"
                      " or contains(@href,'pdf') or contains(@onclick,'pdf')]"
                      " | .//span[contains(text(),'pdf') or contains(text(),'PDF')]/.."
                      " | .//td[last()]//a | .//td[last()]//button"
        )

        arquivos_antes = set(os.listdir(pasta_download))
        botao_pdf.click()
        log.info(f"Clicou no PDF: {numero_doc}")

        # Aguarda novo arquivo aparecer
        pdf_path = None
        inicio = time.time()
        while time.time() - inicio < 30:
            arquivos_depois = set(os.listdir(pasta_download))
            novos = arquivos_depois - arquivos_antes
            pdfs = [f for f in novos if f.endswith(".pdf")]
            if pdfs:
                pdf_path = os.path.join(pasta_download, pdfs[0])
                break
            time.sleep(0.5)

        if not pdf_path:
            log.warning(f"PDF não encontrado para: {numero_doc}")
            return None

        # Aguarda download completar (sem .crdownload)
        inicio = time.time()
        while time.time() - inicio < 30:
            if not any(f.endswith(".crdownload") for f in os.listdir(pasta_download)):
                break
            time.sleep(0.5)

        with open(pdf_path, "rb") as f:
            conteudo = base64.b64encode(f.read()).decode("utf-8")

        os.remove(pdf_path)
        log.info(f"PDF capturado e convertido para base64: {numero_doc}")
        return conteudo

    except Exception as e:
        log.error(f"Erro ao capturar PDF de {numero_doc}: {e}")
        return None


def executar_rpa(headless: bool = True) -> dict:
    """
    Executa o RPA completo e retorna dicionário com resultado.
    Retorno:
        {
            "sucesso": bool,
            "data_verificacao": str,
            "total_nao_lidos": int,
            "documentos": [
                {
                    "numero": str,
                    "remetente": str,
                    "data_criacao": str,
                    "status": str,
                    "pdf_base64": str | None,
                    "pdf_nome": str
                }
            ],
            "erro": str | None
        }
    """
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    driver, pasta_download = criar_driver(headless=headless)

    try:
        fazer_login(driver)
        acessar_edi_logistico(driver)
        acessar_webedi(driver)
        acessar_caixa_entrada(driver, data_hoje)

        nao_lidos = coletar_nao_lidos(driver)

        documentos = []
        for item in nao_lidos:
            pdf_b64 = baixar_pdf_base64(driver, item["numero"], pasta_download)
            nome_arquivo = item["numero"].replace(".", "_") + ".pdf"
            documentos.append({
                "numero": item["numero"],
                "remetente": item["remetente"],
                "data_criacao": item["data_criacao"],
                "status": item["status"],
                "pdf_base64": pdf_b64,
                "pdf_nome": nome_arquivo,
            })

        return {
            "sucesso": True,
            "data_verificacao": data_hoje,
            "total_nao_lidos": len(documentos),
            "documentos": documentos,
            "erro": None,
        }

    except Exception as e:
        log.error(f"Erro no RPA: {e}", exc_info=True)
        return {
            "sucesso": False,
            "data_verificacao": data_hoje,
            "total_nao_lidos": 0,
            "documentos": [],
            "erro": str(e),
        }

    finally:
        driver.quit()
        try:
            import shutil
            shutil.rmtree(pasta_download, ignore_errors=True)
        except Exception:
            pass
