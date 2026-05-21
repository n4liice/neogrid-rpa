import asyncio
import logging
import os
import base64
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("/app/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

_DISMISS_JS = """
    [
        '#CybotCookiebotDialog',
        '#CybotCookiebotDialogBodyUnderlay',
        '#react-joyride-portal',
        '#walk-wrapper',
        '[data-test-id="overlay"]',
    ].forEach(sel => {
        document.querySelectorAll(sel).forEach(el => el.remove());
    });
"""


async def dismiss_overlays(p: Page):
    try:
        await p.evaluate(_DISMISS_JS)
    except Exception:
        pass


async def run_rpa(email: str, password: str) -> dict:
    today = datetime.now().strftime("%d/%m/%Y")
    downloaded_files = []
    errors = []

    log.info("=== Iniciando RPA Neogrid EDI ===")
    log.info(f"Data: {today} | Usuário: {email}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        context = await browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 800},
        )
        page = await context.new_page()

        try:
            # PASSO 1: Login
            log.info("[1/8] Abrindo página de login...")
            await page.goto(
                "https://id.neogrid.com/login/?lang=pt",
                wait_until="networkidle",
                timeout=30000
            )

            log.info("[1/8] Preenchendo e-mail...")
            await page.fill("input#login-form_email", email)
            await page.click("button#login_btn_continue_pre_check")

            # PASSO 2: Senha
            log.info("[2/8] Aguardando campo de senha...")
            await page.wait_for_selector("input[type='password']", timeout=15000)
            await page.fill("input[type='password']", password)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("networkidle", timeout=20000)
            log.info("[2/8] Login realizado.")

            # PASSO 3: Portal — clicar em EDI Logístico
            log.info("[3/8] Aguardando botão EDI Logístico no portal...")
            await page.wait_for_selector("button#gtm-btn-access-EDI_Logístico", timeout=15000)
            await page.click("button#gtm-btn-access-EDI_Logístico")
            log.info("[3/8] Clicou em EDI Logístico.")

            await page.wait_for_selector(
                "button#gtm-btn-modal-access-organization-confirm",
                timeout=10000
            )
            await dismiss_overlays(page)

            log.info("[3/8] Confirmando modal de organização...")
            async with context.expect_page() as new_page_info:
                await page.click("button#gtm-btn-modal-access-organization-confirm")

            edi_page = await new_page_info.value
            await edi_page.wait_for_load_state("networkidle", timeout=20000)
            log.info(f"[3/8] Nova aba aberta: {edi_page.url}")

            # PASSO 4: Navegar direto para o EDI antigo
            log.info("[4/8] Navegando direto para edi.neogrid.com...")
            old_edi = edi_page
            await old_edi.goto(
                "https://edi.neogrid.com/mercador/summaryFrame.jsp",
                wait_until="networkidle",
                timeout=30000,
            )
            log.info(f"[4/8] EDI antigo carregado: {old_edi.url}")

            # PASSO 5: Caixa de Entrada
            log.info("[5/8] Clicando em Caixa de Entrada...")
            await old_edi.wait_for_selector(
                'a[href="javascript:top.Navegacao.goInbox();"]',
                timeout=15000
            )
            await dismiss_overlays(old_edi)
            await old_edi.click('a[href="javascript:top.Navegacao.goInbox();"]')
            await old_edi.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)
            log.info("[5/8] Caixa de Entrada aberta.")

            # PASSO 6: Filtrar por data
            log.info("[6/8] Localizando iframe Transacao...")
            transacao_frame = old_edi.frame(name="Transacao")
            if not transacao_frame:
                raise Exception("iframe Transacao não encontrado")

            await transacao_frame.wait_for_selector("input#iniCreationDateFilter", timeout=15000)

            log.info(f"[6/8] Preenchendo filtro de data: {today}")
            await transacao_frame.fill("input#iniCreationDateFilter", today)
            await transacao_frame.press("input#iniCreationDateFilter", "Tab")
            await transacao_frame.fill("input#endCreationDateFilter", today)
            await transacao_frame.press("input#endCreationDateFilter", "Tab")

            await transacao_frame.click('a[onclick="adjustDocumentTypeFilter()"]')
            await old_edi.wait_for_load_state("networkidle", timeout=20000)
            await asyncio.sleep(2)
            log.info("[6/8] Pesquisa realizada.")

            # PASSO 7: Identificar não lidos
            log.info("[7/8] Varrendo tabela de resultados...")
            transacao_frame = old_edi.frame(name="Transacao")
            await transacao_frame.wait_for_selector("table tr td", timeout=15000)

            rows = await transacao_frame.query_selector_all("table tr")
            log.info(f"[7/8] Total de linhas encontradas: {len(rows)}")

            unread_save_links = []
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 7:
                    continue

                leitura_text = (await cells[6].inner_text()).strip()
                if "Lido" not in leitura_text:
                    save_links = await row.query_selector_all("a[onclick^='doSave(']")
                    for link in save_links:
                        onclick = await link.get_attribute("onclick")
                        unread_save_links.append({"link": link, "onclick": onclick})
                        log.info(f"[7/8] Não lido encontrado: {onclick}")

            log.info(f"[7/8] Total não lidos: {len(unread_save_links)}")

            if not unread_save_links:
                log.info("Nenhum documento não lido. Encerrando.")
                return {
                    "success": True,
                    "date": today,
                    "message": "Nenhum documento não lido encontrado para hoje.",
                    "total_downloaded": 0,
                    "files": [],
                    "errors": [],
                }

            # PASSO 8: Baixar cada arquivo
            log.info("[8/8] Iniciando downloads...")
            for item in unread_save_links:
                try:
                    onclick_val = item["onclick"]
                    log.info(f"[8/8] Baixando: {onclick_val}")

                    # Re-busca o elemento no frame para evitar handle stale
                    transacao_frame = old_edi.frame(name="Transacao")
                    link = await transacao_frame.query_selector(f"a[onclick='{onclick_val}']")
                    if not link:
                        raise Exception(f"Link não encontrado no frame: {onclick_val}")

                    await dismiss_overlays(old_edi)

                    async with old_edi.expect_download(timeout=30000) as dl_info:
                        await link.click(force=True)

                    download = await dl_info.value
                    filename = download.suggested_filename or f"doc_{item['onclick']}.txt"
                    filepath = DOWNLOAD_DIR / filename

                    await download.save_as(str(filepath))

                    with open(filepath, "rb") as f:
                        content = f.read()

                    downloaded_files.append({
                        "filename": filename,
                        "content_base64": base64.b64encode(content).decode("utf-8"),
                        "size_bytes": len(content),
                        "downloaded_at": datetime.now().isoformat(),
                        "onclick": item["onclick"],
                    })

                    os.remove(filepath)
                    log.info(f"[8/8] Download concluído: {filename} ({len(content)} bytes)")
                    await asyncio.sleep(0.5)

                except PlaywrightTimeout:
                    log.error(f"[8/8] Timeout ao baixar: {item.get('onclick')}")
                    errors.append({"error": "Timeout ao baixar", "onclick": item.get("onclick")})
                except Exception as e:
                    log.error(f"[8/8] Erro ao baixar {item.get('onclick')}: {e}")
                    errors.append({"error": str(e), "onclick": item.get("onclick")})

            log.info(f"=== RPA concluído: {len(downloaded_files)} arquivo(s) baixado(s), {len(errors)} erro(s) ===")
            return {
                "success": True,
                "date": today,
                "total_downloaded": len(downloaded_files),
                "files": downloaded_files,
                "errors": errors,
            }

        except Exception as e:
            log.exception(f"Erro fatal no RPA: {e}")
            return {
                "success": False,
                "error": str(e),
                "date": today,
                "files": [],
                "errors": errors,
            }
        finally:
            await browser.close()
            log.info("Browser encerrado.")
