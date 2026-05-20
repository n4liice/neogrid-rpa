"""
Motor do RPA Neogrid EDI — usado pela API e pelo CLI.
Retorna lista de documentos não lidos com PDF em base64.

Estratégia de login: após submeter credenciais, navega IMEDIATAMENTE para
URL_EDI sem esperar o portal dashboard carregar — evita crash do Chrome
ao renderizar a SPA pesada do portal.neogrid.com.
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


# ── helpers ──────────────────────────────────────────────────

def js_click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    driver.execute_script("arguments[0].click();", el)


def dismiss_overlays(driver):
    try:
        driver.execute_script("""
            ['#walk-wrapper','#CybotCookiebotDialog','.cookiebot-overlay',
             '[id*="cookiebot"]','[class*="cookie-banner"]','[class*="overlay"]',
             '[class*="modal-backdrop"]'].forEach(sel => {
                document.querySelectorAll(sel).forEach(el => el.remove());
            });
            document.body.style.overflow = 'auto';
        """)
    except Exception:
        pass


# ── driver ───────────────────────────────────────────────────

def criar_driver(headless=True, pasta_download=None):
    pasta_download = pasta_download or tempfile.mkdtemp()
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-setuid-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
    else:
        opts.add_argument("--start-maximized")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-default-apps")
    opts.add_argument("--no-first-run")
    opts.add_experimental_option("prefs", {
        "download.default_directory": pasta_download,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
    })
    driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(5)
    return driver, pasta_download


# ── login ────────────────────────────────────────────────────

def fazer_login(driver):
    """
    Submete login e aguarda apenas 3s para o cookie de sessão ser processado.
    NÃO espera o portal dashboard — Chrome trava renderizando aquela SPA.
    O chamador deve navegar para URL_EDI logo em seguida.
    """
    log.info("Iniciando login...")
    driver.get(URL_PORTAL)
    wait = WebDriverWait(driver, 30)

    campo = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input[type='email'], input[type='text']")
    ))
    campo.clear()
    campo.send_keys(USUARIO)
    log.info("Email preenchido.")

    dismiss_overlays(driver)
    botao = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "button[type='submit'], button[type='button'], button")
    ))
    js_click(driver, botao)

    campo_senha = wait.until(EC.visibility_of_element_located(
        (By.CSS_SELECTOR, "input[type='password']")
    ))
    campo_senha.clear()
    campo_senha.send_keys(SENHA)
    log.info("Senha preenchida.")

    dismiss_overlays(driver)
    botao_login = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
    ))
    js_click(driver, botao_login)
    log.info("Login submetido. Aguardando 3s para cookie de sessão...")

    # 3s é suficiente para o browser processar o Set-Cookie da resposta de login.
    # Não esperamos mais — navegar para URL_EDI cancela o portal dashboard.
    time.sleep(3)
    log.info(f"URL pós-login: {driver.current_url}")


# ── EDI ──────────────────────────────────────────────────────

def acessar_edi(driver):
    """Navega direto para o WebEDI, cancelando qualquer carregamento em curso."""
    log.info("Navegando para o WebEDI...")
    driver.get(URL_EDI)
    WebDriverWait(driver, 30).until(EC.url_contains("edi.neogrid.com"))
    log.info(f"EDI carregado: {driver.current_url}")

    # Fecha tabs extras que possam ter sido abertas
    principal = driver.window_handles[0]
    for aba in driver.window_handles[1:]:
        driver.switch_to.window(aba)
        driver.close()
    driver.switch_to.window(principal)


# ── caixa de entrada ─────────────────────────────────────────

def mudar_para_frame_transacao(driver):
    driver.switch_to.default_content()
    try:
        driver.switch_to.frame("Transacao")
        return
    except Exception:
        pass
    try:
        for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
            nome = iframe.get_attribute("name") or ""
            if "transacao" in nome.lower() or "content" in nome.lower():
                driver.switch_to.frame(iframe)
                return
        driver.switch_to.frame(0)
    except Exception as e:
        log.warning(f"Frame não encontrado: {e}")


def acessar_caixa_entrada(driver, data):
    wait = WebDriverWait(driver, 30)
    log.info("Acessando Caixa de Entrada...")

    driver.switch_to.default_content()
    dismiss_overlays(driver)

    link = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//a[contains(text(),'Caixa Entrada') or contains(@href,'goInbox')]")
    ))
    js_click(driver, link)
    log.info("Caixa Entrada clicada.")

    mudar_para_frame_transacao(driver)

    try:
        link_filtro = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'filtro está fechado') or contains(text(),'exibi-lo')]")
            )
        )
        js_click(driver, link_filtro)
    except Exception:
        pass

    log.info(f"Filtrando por data: {data}")
    campo_data = wait.until(EC.presence_of_element_located(
        (By.XPATH,
         "//label[contains(text(),'Data Criação Inicial') or contains(text(),'Data Cria')]"
         "/following-sibling::input | "
         "//input[@id='dataIni' or @name='dataIni' or @name='dtInicio' "
         "or @id='dtInicio' or @id='startDate']")
    ))
    campo_data.clear()
    campo_data.send_keys(data)

    botao = wait.until(EC.presence_of_element_located(
        (By.XPATH,
         "//button[contains(normalize-space(.),'Pesquisar')] | "
         "//input[@value='Pesquisar' or @value='pesquisar' or @title='Pesquisar'] | "
         "//input[@type='submit'] | //input[@type='image'] | "
         "//a[contains(normalize-space(.),'Pesquisar')]")
    ))
    js_click(driver, botao)
    log.info("Pesquisa disparada.")
    time.sleep(2)


def coletar_nao_lidos(driver):
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
            remetente    = celulas[1].text.strip()
            numero       = celulas[3].text.strip()
            data_criacao = celulas[5].text.strip()
            status       = celulas[6].text.strip()

            log.info(f"  [{i+1}] {numero} | {data_criacao} | {status}")

            if status.lower() != "lido":
                log.info(f"  *** NÃO LIDO: {numero}")
                nao_lidos.append({
                    "numero": numero,
                    "remetente": remetente,
                    "data_criacao": data_criacao,
                    "status": status,
                })
        except Exception as e:
            log.warning(f"Erro na linha {i}: {e}")

    log.info(f"Não lidos: {len(nao_lidos)}")
    return nao_lidos


def baixar_pdf_base64(driver, numero_doc, pasta_download):
    try:
        mudar_para_frame_transacao(driver)

        linha = driver.find_element(
            By.XPATH, f"//tr[td[contains(text(), '{numero_doc}')]]"
        )
        botao_pdf = linha.find_element(
            By.XPATH,
            ".//a[contains(@class,'pdf') or contains(text(),'pdf') or contains(text(),'PDF')"
            " or contains(@href,'pdf') or contains(@onclick,'pdf')]"
            " | .//span[contains(text(),'pdf') or contains(text(),'PDF')]/.."
            " | .//td[last()]//a | .//td[last()]//button"
        )

        arquivos_antes = set(os.listdir(pasta_download))
        js_click(driver, botao_pdf)
        log.info(f"PDF clicado: {numero_doc}")

        pdf_path = None
        inicio = time.time()
        while time.time() - inicio < 30:
            novos = [f for f in (set(os.listdir(pasta_download)) - arquivos_antes)
                     if f.endswith(".pdf")]
            if novos:
                pdf_path = os.path.join(pasta_download, novos[0])
                break
            time.sleep(0.5)

        if not pdf_path:
            log.warning(f"PDF não encontrado para: {numero_doc}")
            return None

        inicio = time.time()
        while time.time() - inicio < 30:
            if not any(f.endswith(".crdownload") for f in os.listdir(pasta_download)):
                break
            time.sleep(0.5)

        with open(pdf_path, "rb") as f:
            conteudo = base64.b64encode(f.read()).decode()

        os.remove(pdf_path)
        log.info(f"PDF capturado: {numero_doc}")
        return conteudo

    except Exception as e:
        log.error(f"Erro PDF {numero_doc}: {e}")
        return None


# ── orquestrador ─────────────────────────────────────────────

def executar_rpa(headless=True):
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    driver, pasta_download = criar_driver(headless=headless)

    try:
        fazer_login(driver)

        # Navega para EDI imediatamente — cancela carregamento do portal dashboard
        acessar_edi(driver)

        acessar_caixa_entrada(driver, data_hoje)
        nao_lidos = coletar_nao_lidos(driver)

        documentos = []
        for item in nao_lidos:
            pdf_b64 = baixar_pdf_base64(driver, item["numero"], pasta_download)
            documentos.append({
                "numero":       item["numero"],
                "remetente":    item["remetente"],
                "data_criacao": item["data_criacao"],
                "status":       item["status"],
                "pdf_base64":   pdf_b64,
                "pdf_nome":     item["numero"].replace(".", "_") + ".pdf",
            })

        return {
            "sucesso":          True,
            "data_verificacao": data_hoje,
            "total_nao_lidos":  len(documentos),
            "documentos":       documentos,
            "erro":             None,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.error(f"Erro no RPA: {e}\n{tb}")
        return {
            "sucesso":          False,
            "data_verificacao": data_hoje,
            "total_nao_lidos":  0,
            "documentos":       [],
            "erro":             str(e),
            "traceback":        tb,
        }

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(pasta_download, ignore_errors=True)
        except Exception:
            pass
