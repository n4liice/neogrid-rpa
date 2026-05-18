# ============================================================
# RPA - Neogrid EDI Logístico | Caixa de Entrada
# Objetivo: Identificar itens NÃO LIDOS e salvar PDF
# Autor: RPA Mandalog
# ============================================================

import os
import time
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ============================================================
# CONFIGURAÇÕES
# ============================================================
USUARIO    = os.environ.get("NEOGRID_USUARIO", "operacional@mandalog.com.br")
SENHA      = os.environ.get("NEOGRID_SENHA", "M@ndalog2026_@")
URL_PORTAL = "https://portal.neogrid.com/?lang=pt"
URL_EDI    = "https://edi.neogrid.com/mercador/summaryFrame.jsp"
DATA_HOJE  = datetime.now().strftime("%d/%m/%Y")

PASTA_PDF  = os.path.join(os.path.expanduser("~"), "Downloads", "EDI_PDFs")
os.makedirs(PASTA_PDF, exist_ok=True)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("rpa_neogrid.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================
# CONFIGURAÇÃO DO DRIVER
# ============================================================
def criar_driver():
    opcoes = Options()
    opcoes.add_argument("--start-maximized")
    opcoes.add_argument("--disable-notifications")
    opcoes.add_argument("--disable-popup-blocking")

    prefs = {
        "download.default_directory": PASTA_PDF,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
    }
    opcoes.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=opcoes)
    driver.implicitly_wait(5)
    return driver


# ============================================================
# PASSO 1 — LOGIN NO PORTAL NEOGRID
# ============================================================
def fazer_login(driver):
    log.info("Acessando o portal Neogrid...")
    driver.get(URL_PORTAL)
    wait = WebDriverWait(driver, 30)

    # Preenche e-mail
    campo_usuario = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input[type='email'], input[type='text']")
    ))
    campo_usuario.clear()
    campo_usuario.send_keys(USUARIO)

    # Clica em Continue
    botao_proximo = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "button[type='submit'], button[type='button'], button")
    ))
    botao_proximo.click()
    log.info(f"Avançou para senha (botão: '{botao_proximo.text}').")

    # Preenche senha (aguarda aparecer)
    campo_senha = wait.until(EC.visibility_of_element_located(
        (By.CSS_SELECTOR, "input[type='password']")
    ))
    campo_senha.clear()
    campo_senha.send_keys(SENHA)

    # Clica em Entrar
    botao_login = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
    ))
    botao_login.click()
    log.info("Login submetido. Aguardando portal...")

    # Aguarda portal carregar
    wait.until(EC.presence_of_element_located(
        (By.XPATH, "//*[contains(text(), 'EDI Logístico') or contains(text(), 'EDI Logistico')]")
    ))
    log.info("Login realizado com sucesso.")

    # Fecha abas extras abertas durante o login
    aba_portal = driver.window_handles[0]
    for aba in driver.window_handles[1:]:
        driver.switch_to.window(aba)
        driver.close()
    driver.switch_to.window(aba_portal)

    # Aceita cookies (Cookiebot) — aparece só na primeira sessão
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


# ============================================================
# PASSO 2 — ACESSAR EDI LOGÍSTICO
# ============================================================
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
    log.info("Clicou em 'Acessar'.")


# ============================================================
# PASSO 3 — NAVEGAR DIRETAMENTE PARA O WEBEDI
# ============================================================
def acessar_antigo_edi(driver):
    # Muda para nova aba se abriu
    if len(driver.window_handles) > 1:
        driver.switch_to.window(driver.window_handles[-1])

    log.info("Navegando diretamente para o WebEDI...")
    driver.get(URL_EDI)

    WebDriverWait(driver, 30).until(EC.url_contains("edi.neogrid.com"))
    log.info(f"WebEDI carregado: {driver.current_url}")


# ============================================================
# PASSO 4 — NAVEGAR PARA CAIXA DE ENTRADA E FILTRAR POR DATA
# ============================================================
def acessar_caixa_entrada_com_filtro(driver):
    wait = WebDriverWait(driver, 30)
    log.info("Acessando Caixa de Entrada...")

    driver.switch_to.default_content()

    # Remove overlay de tutorial se presente
    try:
        overlay = driver.find_element(By.ID, "walk-wrapper")
        if overlay.is_displayed():
            driver.execute_script("arguments[0].style.display='none';", overlay)
    except Exception:
        pass

    # Clica em Caixa Entrada via JS para ignorar overlays
    link_caixa = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//a[contains(text(),'Caixa Entrada') or contains(@href,'goInbox')]")
    ))
    driver.execute_script("arguments[0].click();", link_caixa)
    log.info("Clicou em 'Caixa Entrada'.")

    # Muda para frame da transação
    mudar_para_frame_transacao(driver)

    # Abre filtro se estiver fechado
    try:
        link_filtro = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//*[contains(text(),'filtro está fechado') or contains(text(),'exibi-lo')]")
            )
        )
        link_filtro.click()
        log.info("Filtro aberto.")
    except Exception:
        pass

    # Preenche data de hoje
    log.info(f"Filtrando por data: {DATA_HOJE}")
    campo_data_inicial = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//label[contains(text(),'Data Criação Inicial') or contains(text(),'Data Cria')]"
                   "/following-sibling::input | "
                   "//input[@id='dataIni' or @name='dataIni' or @name='dtInicio' or @id='dtInicio' or @id='startDate']")
    ))
    campo_data_inicial.clear()
    campo_data_inicial.send_keys(DATA_HOJE)

    # Clica em Pesquisar
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


# ============================================================
# HELPER — MUDAR PARA FRAME "Transacao"
# ============================================================
def mudar_para_frame_transacao(driver):
    driver.switch_to.default_content()
    try:
        driver.switch_to.frame("Transacao")
        log.info("Mudou para o frame 'Transacao'.")
    except Exception:
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                nome = iframe.get_attribute("name") or ""
                if "transacao" in nome.lower() or "content" in nome.lower():
                    driver.switch_to.frame(iframe)
                    log.info(f"Mudou para o frame: {nome}")
                    return
            driver.switch_to.frame(0)
            log.info("Mudou para frame pelo índice 0.")
        except Exception as e:
            log.warning(f"Não foi possível mudar de frame: {e}")


# ============================================================
# PASSO 5 — IDENTIFICAR ITENS NÃO LIDOS E SALVAR PDF
# ============================================================
def processar_itens_nao_lidos(driver):
    wait = WebDriverWait(driver, 30)
    log.info("Verificando registros na Caixa de Entrada...")

    mudar_para_frame_transacao(driver)
    time.sleep(1)

    linhas = driver.find_elements(By.XPATH, "//table//tr[td]")
    log.info(f"Total de linhas encontradas: {len(linhas)}")

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

            log.info(f"  [{i+1}] {numero} | {data_criacao} | Status: '{status_leitura}'")

            if status_leitura.lower() != "lido":
                log.info(f"  *** NÃO LIDO: {numero} | Remetente: {remetente}")
                nao_lidos.append({
                    "indice": i,
                    "linha": linha,
                    "numero": numero,
                    "remetente": remetente,
                    "data_criacao": data_criacao,
                    "status": status_leitura
                })

        except Exception as e:
            log.warning(f"Erro ao processar linha {i}: {e}")

    log.info(f"Total de itens NÃO LIDOS: {len(nao_lidos)}")

    if not nao_lidos:
        log.info("Nenhum item novo para processar. Encerrando.")
        return

    for item in nao_lidos:
        salvar_pdf_item(driver, item)

    log.info("Processamento concluído.")


# ============================================================
# PASSO 6 — SALVAR PDF DO ITEM
# ============================================================
def salvar_pdf_item(driver, item):
    log.info(f"Salvando PDF do item: {item['numero']}...")

    try:
        mudar_para_frame_transacao(driver)

        linha = driver.find_element(
            By.XPATH, f"//tr[td[contains(text(), '{item['numero']}')]]"
        )

        botao_pdf = linha.find_element(
            By.XPATH, ".//a[contains(@class,'pdf') or contains(text(),'pdf') or contains(text(),'PDF')"
                      " or contains(@href,'pdf') or contains(@onclick,'pdf')]"
                      " | .//span[contains(text(),'pdf') or contains(text(),'PDF')]/.."
                      " | .//td[last()]//a | .//td[last()]//button"
        )

        botao_pdf.click()
        log.info(f"Clicou no botão PDF: {item['numero']}")

        aguardar_download(PASTA_PDF, timeout=30)
        log.info(f"PDF salvo: {item['numero']}")

    except Exception as e:
        log.error(f"Erro ao salvar PDF de {item['numero']}: {e}")


# ============================================================
# HELPER — AGUARDAR DOWNLOAD CONCLUIR
# ============================================================
def aguardar_download(pasta, timeout=30):
    inicio = time.time()
    while time.time() - inicio < timeout:
        arquivos_temp = [f for f in os.listdir(pasta) if f.endswith(".crdownload") or f.endswith(".tmp")]
        if not arquivos_temp:
            return True
        time.sleep(1)
    log.warning("Timeout ao aguardar download.")
    return False


# ============================================================
# MAIN — ORQUESTRADOR PRINCIPAL
# ============================================================
def main():
    log.info("=" * 60)
    log.info("INICIANDO RPA — Neogrid EDI Logístico")
    log.info(f"Data de execução: {DATA_HOJE}")
    log.info(f"Pasta de PDFs: {PASTA_PDF}")
    log.info("=" * 60)

    driver = criar_driver()

    try:
        fazer_login(driver)
        acessar_edi_logistico(driver)
        acessar_antigo_edi(driver)
        acessar_caixa_entrada_com_filtro(driver)
        processar_itens_nao_lidos(driver)

    except Exception as e:
        log.error(f"Erro geral na execução do RPA: {e}", exc_info=True)

    finally:
        log.info("Encerrando o navegador.")
        driver.quit()
        log.info("RPA finalizado.")


if __name__ == "__main__":
    main()
